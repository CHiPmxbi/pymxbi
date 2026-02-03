from typing import Mapping, Any
from pymxbi.rewarder.rewarder import Rewarder
from pymxbi.detector.detector import Detector
from pymxbi.screen import Screen


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
        self._rewarder = self._normalize(rewarder, "rewarder")
        self._detector = self._normalize(detector, "detector")

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

    @property
    def screen_size(self):
        return self._screen_size


_current_mxbi: MXBI | None = None


def get_mxbi() -> MXBI:
    global _current_mxbi
    if _current_mxbi is None:
        raise RuntimeError("MXBI not initialized")
    return _current_mxbi


def set_mxbi(mxbi: MXBI) -> None:
    global _current_mxbi
    if _current_mxbi is not None:
        raise RuntimeError("MXBI already initialized")
    _current_mxbi = mxbi
