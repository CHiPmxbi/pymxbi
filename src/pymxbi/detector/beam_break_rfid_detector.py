"""Detector combining a through-beam sensor and an RFID reader."""

from threading import Thread
from time import sleep, time

from pymxbi.detector.detector import DetectionResult, Detector
from pymxbi.peripheral.rfid.rfid import RFIDReader, RFIDTag
from pymxbi.peripheral.through_beam_sensor.through_beam_sensor import ThroughBeamSensor


class BeamBreakRFIDDetector(Detector):
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
    max_tag_age_seconds : float, default=5.0
        Maximum allowed tag age in seconds. Older tag reads are treated as stale.
    """

    def __init__(
        self,
        animal_db: dict[str, str],
        rfid_reader: RFIDReader,
        beam_break_sensor: ThroughBeamSensor,
        detection_frequency: int,  # milliseconds
        max_tag_age_seconds: float = 5.0,
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
        max_tag_age_seconds : float, default=5.0
            Maximum allowed tag age in seconds. Older tag reads are treated as stale.
        """
        super().__init__(animal_db)
        self.detection_frequency = detection_frequency / 1000.0
        self.max_tag_age_seconds = max_tag_age_seconds

        self._rfid_reader = rfid_reader
        self._beam_break_sensor = beam_break_sensor

        self._is_running = False
        self._thread: Thread = Thread(target=self._worker)

    def _worker(self) -> None:
        """Run the background detection loop."""
        while self._is_running:
            has_animal = self._beam_break_sensor.read()
            if not has_animal:
                sleep(self.detection_frequency)
                continue

            tag: RFIDTag | None = self._rfid_reader.read()
            if tag is None:
                sleep(self.detection_frequency)
                continue

            if time() - tag.detect_time > self.max_tag_age_seconds:
                sleep(self.detection_frequency)
                continue

            animal_name = self.animal_db.get(tag.animal_id)

            result = DetectionResult(animal_name=animal_name, error=False)
            self.process_detection(result)

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
