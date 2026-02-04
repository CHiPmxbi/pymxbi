"""Detector combining a through-beam sensor and an RFID reader."""

from threading import Thread
from time import sleep, time

from pymxbi.peripheral.rfid.rfid import RFIDReader, RFIDTag
from pymxbi.peripheral.beam_break_sensor.beam_break_sensor import BeamBreakSensor
from .continuous_detector import ContinuousDetector
from .detector import DetectionResult


class FusionContinuousDetector(ContinuousDetector):
    """Detect animals using a beam-break sensor and an RFID reader.

    Parameters
    ----------
    animal_db : dict[str, str]
        Mapping from animal ID to animal name.
    rfid_reader : RFIDReader
        RFID reader used to fetch tags.
    beam_break_sensor : ThroughBeamSensor
        Through-beam sensor used to detect presence.
    detection_frequency : int
        Polling interval in milliseconds.
    """

    def __init__(
        self,
        animal_db: dict[str, str],
        rfid_reader: RFIDReader,
        beam_break_sensor: BeamBreakSensor,
        detection_frequency: int,  # milliseconds
    ) -> None:
        """Initialize the detector.

        Parameters
        ----------
        animal_db : dict[str, str]
            Mapping from animal ID to animal name.
        rfid_reader : RFIDReader
            RFID reader used to fetch tags.
        beam_break_sensor : ThroughBeamSensor
            Through-beam sensor used to detect presence.
        detection_frequency : int
            Polling interval in milliseconds.
        """
        super().__init__(animal_db)
        self.detection_frequency = detection_frequency / 1000.0

        self._rfid_reader = rfid_reader
        self._beam_break_sensor = beam_break_sensor

        self._is_running = False
        self._thread: Thread = Thread(target=self._worker)

    def _worker(self) -> None:
        """Run the background detection loop."""
        animal_present_prev = False
        cached_tag: RFIDTag | None = None
        timeout_seconds = 5

        def emit(
            *,
            timestamp: float,
            animal_id: str | None,
            animal_name: str | None,
            error: bool = False,
        ) -> None:
            self.process_detection(
                DetectionResult(
                    timestamp=timestamp,
                    animal_id=animal_id,
                    animal_name=animal_name,
                    error=error,
                )
            )

        def emit_error() -> None:
            emit(timestamp=time(), animal_id=None, animal_name=None, error=True)

        while self._is_running:
            has_animal = self._beam_break_sensor.read()

            if not has_animal:
                animal_present_prev = False
                cached_tag = None
                sleep(self.detection_frequency)
                continue

            if animal_present_prev:
                if cached_tag is not None:
                    emit(
                        timestamp=cached_tag.detect_time,
                        animal_id=cached_tag.animal_id,
                        animal_name=self._animal_db.get(cached_tag.animal_id),
                        error=False,
                    )
                sleep(self.detection_frequency)
                continue

            animal_present_prev = True
            deadline = time() + timeout_seconds

            tag: RFIDTag | None = None
            while self._is_running and time() < deadline:
                tag = self._rfid_reader.read()
                if tag is not None:
                    break
                sleep(1)

            if tag is None:
                emit_error()
                sleep(self.detection_frequency)
                continue

            animal_name = self._animal_db.get(tag.animal_id)
            if not animal_name:
                emit_error()
                sleep(self.detection_frequency)
                continue

            cached_tag = tag
            emit(
                timestamp=tag.detect_time,
                animal_id=tag.animal_id,
                animal_name=animal_name,
                error=False,
            )
            sleep(self.detection_frequency)

    def _cleanup(self) -> None:
        """Release hardware resources."""
        self._rfid_reader.close()
        self._beam_break_sensor.close()

    def begin(self) -> None:
        """Start detection in a background thread."""
        if self._is_running:
            return

        self._is_running = True
        self._thread.start()

    def quit(self) -> None:
        """Stop detection and close resources."""
        if not self._is_running:
            return

        self._is_running = False
        self._thread.join()

        self._cleanup()
