"""Mock detector implementation for testing and development."""

from collections.abc import Sequence
from threading import Lock, Thread
from time import sleep, time

from .detector import DetectionResult
from .continuous_detector import ContinuousDetector


class MockDetector(ContinuousDetector):
    """Detector stub that performs no I/O.

    This class lets you drive the detector state machine manually to produce
    events such as animal entered/left/changed/remained and fault detected.
    """

    def __init__(
        self,
        animals: Sequence[str],
        detection_frequency_ms: int = 200,
    ) -> None:
        """Create a mock detector with a list of animal names.

        Parameters
        ----------
        animals : Sequence[str]
            Names of animals that can be referenced by index in helper methods.
        detection_frequency_ms : int, default=200
            Polling interval in milliseconds for emitting detection results.
        """
        resolved_animals = list(animals)
        if not resolved_animals:
            raise ValueError("MockDetector requires a non-empty animals sequence.")

        self.animals = resolved_animals
        super().__init__({name: name for name in self.animals})

        self.detection_frequency = detection_frequency_ms / 1000.0

        self._input_lock = Lock()
        self._current_animal: str | None = self.animals[0]

        self._is_running = False
        self._thread: Thread = Thread(target=self._worker, daemon=True)

    def _worker(self) -> None:
        while self._is_running:
            with self._input_lock:
                animal_name = self._current_animal
            self.process_detection(
                DetectionResult(
                    timestamp=time(),
                    animal_id=animal_name if animal_name is not None else None,
                    animal_name=animal_name,
                    error=False,
                )
            )
            sleep(self.detection_frequency)

    def begin(self) -> None:
        """Start emitting detection results in a background thread."""
        if self._is_running:
            return
        self._is_running = True
        self._thread.start()

    def quit(self) -> None:
        """Stop emitting detection results."""
        if not self._is_running:
            return
        self._is_running = False
        self._thread.join()

    def animal_present(self, animal_index: int) -> None:
        """Set the simulated state to "an animal is present"."""
        animal_name = self._resolve_animal(animal_index)
        with self._input_lock:
            self._current_animal = animal_name

    def animal_left(self) -> None:
        """Set the simulated state to "no animal is present"."""
        with self._input_lock:
            self._current_animal = None

    def _resolve_animal(self, animal_index: int) -> str:
        return self.animals[animal_index]
