from typing import Any, Mapping

from ..audioplayer import AudioPlayer
from ..detector.detector import Detector
from ..rewarder.rewarder import Rewarder
from ..screen import Screen


class MXBI:
    def __init__(
        self,
        screen_size: Screen | tuple[int, int],
        rewarder: Rewarder | dict[int, Rewarder],
        detector: Detector | dict[int, Detector],
    ):
        if not isinstance(screen_size, Screen):
            screen_size = Screen(width=screen_size[0], height=screen_size[1])
        self._screen_size = screen_size
        self._rewarder: dict[int, Rewarder] = self._normalize(rewarder, "rewarder")
        self._detector: dict[int, Detector] = self._normalize(detector, "detector")
        self._aplayer = AudioPlayer()

    @staticmethod
    def _normalize(obj, name: str) -> dict[int, Any]:
        if isinstance(obj, Mapping):
            if not obj:
                raise ValueError(f"{name} mapping cannot be empty")
            return dict(obj)
        return {0: obj}

    @property
    def rewarder(self) -> Rewarder:
        rewarder = self._rewarder.get(0)
        if rewarder is None:
            raise RuntimeError("No rewarder with id 0 found")
        return rewarder

    def get_rewarder(self, rewarder_id: int) -> Rewarder:
        rewarder = self._rewarder.get(rewarder_id)
        if rewarder is None:
            raise RuntimeError(f"No rewarder with id {rewarder_id} found")
        return rewarder

    @property
    def detector(self) -> Detector:
        detector = self._detector.get(0)
        if detector is None:
            raise RuntimeError("No detector with id 0 found")
        return detector

    def get_detector(self, detector_id: int) -> Detector:
        detector = self._detector.get(detector_id)
        if detector is None:
            raise RuntimeError(f"No detector with id {detector_id} found")
        return detector

    def begin(self) -> None:
        """Start all detectors and open all rewarders."""
        for rewarder in self._rewarder.values():
            rewarder.open()
        for detector in self._detector.values():
            detector.begin()

    def quit(self) -> None:
        """Stop all detectors and close all rewarders."""
        for detector in self._detector.values():
            detector.quit()
        for rewarder in self._rewarder.values():
            rewarder.close()

    @property
    def screen_size(self):
        return self._screen_size

    @property
    def aplayer(self) -> AudioPlayer:
        return self._aplayer
