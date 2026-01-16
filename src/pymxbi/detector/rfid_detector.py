"""RFID-only detector implementation.

This detector turns raw RFID tag reads into `DetectionResult` events suitable for
the built-in detector state machine.
"""

from threading import Event, Lock, Thread, Timer
from time import sleep, time

from pymxbi.detector.detector import DetectionResult, Detector
from pymxbi.peripheral.rfid.rfid import RFIDReader, RFIDTag


class RFIDDetector(Detector):
    """Detect animals using only an RFID reader.

    Parameters
    ----------
    animal_db : dict[str, str]
        Mapping from animal ID (as reported by the reader) to animal name.
    rfid_reader : RFIDReader
        RFID reader that produces tag results.
    detection_interval : float
        Seconds to keep an animal "present" after the last tag read. Each new tag
        read resets this timer; when it expires, the detector emits "no animal".
    poll_interval : float, default=0.05
        Seconds between polls of `rfid_reader.read()`.
    max_tag_age_seconds : float | None, default=5.0
        Ignore tag reads older than this many seconds. Use `None` to disable.
    """

    def __init__(
        self,
        animal_db: dict[str, str],
        rfid_reader: RFIDReader,
        detection_interval: float,
        poll_interval: float = 0.05,
        max_tag_age_seconds: float | None = 5.0,
    ) -> None:
        super().__init__(animal_db)
        self._rfid_reader = rfid_reader

        self.detection_interval = detection_interval
        self.poll_interval = poll_interval
        self.max_tag_age_seconds = max_tag_age_seconds

        self._stop_event = Event()
        self._lock = Lock()

        self._timer: Timer | None = None
        self._worker_thread: Thread | None = None

        self._last_handled_key: tuple[float, str] | None = None
        self._last_errno: str = ""

    def begin(self) -> None:
        """Open the reader and start polling results in a background thread."""
        if self._worker_thread and self._worker_thread.is_alive():
            return

        self._stop_event.clear()
        self._last_handled_key = None
        self._last_errno = ""

        self._rfid_reader.open()
        try:
            self._rfid_reader.begin()
        except RuntimeError:
            # `DorsetLID665v42.begin()` starts a thread which cannot be started
            # more than once; treat repeated starts as a no-op.
            pass

        self._worker_thread = Thread(
            target=self._worker,
            name="RFIDDetectorWorker",
            daemon=True,
        )
        self._worker_thread.start()

    def quit(self) -> None:
        """Stop polling and close the reader."""
        self._stop_event.set()

        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None

        self._rfid_reader.close()

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.0)
        self._worker_thread = None

    def _worker(self) -> None:
        while not self._stop_event.is_set():
            errno = self._rfid_reader.errno
            if errno and errno != self._last_errno:
                self._last_errno = errno
                self.process_detection(DetectionResult(error=True))
            elif not errno and self._last_errno:
                self._last_errno = ""

            tag = self._rfid_reader.read()
            if tag is None:
                sleep(self.poll_interval)
                continue

            if (
                self.max_tag_age_seconds is not None
                and time() - tag.detect_time > self.max_tag_age_seconds
            ):
                sleep(self.poll_interval)
                continue

            key = (tag.detect_time, tag.animal_id)
            if key == self._last_handled_key:
                sleep(self.poll_interval)
                continue
            self._last_handled_key = key

            self._handle_tag(tag)
            sleep(self.poll_interval)

    def _handle_tag(self, tag: RFIDTag) -> None:
        animal_name = self.animal_db.get(tag.animal_id)
        if not animal_name:
            return

        with self._lock:
            if self._stop_event.is_set():
                return

            if self._timer:
                self._timer.cancel()

            self._timer = Timer(self.detection_interval, self._on_timeout)
            self._timer.daemon = True
            self._timer.start()

        self.process_detection(DetectionResult(animal_name=animal_name, error=False))

    def _on_timeout(self) -> None:
        with self._lock:
            if self._stop_event.is_set():
                return

            self._timer = None

        self.process_detection(DetectionResult(animal_name=None, error=False))
