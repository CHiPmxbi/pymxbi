from dataclasses import dataclass
from enum import StrEnum, auto
from typing import Callable, Protocol


class DetectorEnum(StrEnum):
    MOCK = auto()
    RFID_CONTINUOUS = auto()
    BEAMBREAK_CONTINUOUS = auto()
    FUSION_CONTINUOUS = auto()


class DetectorEvent(StrEnum):
    """Detector events emitted on state transitions.

    Attributes
    ----------
    ANIMAL_ENTERED
        An identified animal has been detected.
    ANIMAL_LEFT
        The animal is no longer detected.
    UNKNOWN_ANIMAL_ENTERED
        An animal was detected but could not be identified.
    FAULT_DETECTED
        A fault occurred while reading sensor inputs.
    """

    ANIMAL_ENTERED = auto()
    ANIMAL_LEFT = auto()
    UNKNOWN_ANIMAL_ENTERED = auto()
    FAULT_DETECTED = auto()


@dataclass
class DetectionResult:
    """Detection result emitted alongside a :class:`DetectorEvent`.

    Attributes
    ----------
    timestamp : float
        Unix timestamp of the detection.
    animal_id : str | None
        Identifier of the detected animal, or ``None`` if unknown.
    error : bool
        Whether a fault was detected while reading sensor inputs.
    """

    timestamp: float = 0.0
    animal_id: str | None = None
    error: bool = False


class Detector(Protocol):
    def register_event(
        self, event: DetectorEvent, callback: Callable[[DetectionResult], None]
    ) -> None: ...

    def begin(self) -> None: ...

    def quit(self) -> None: ...

    @property
    def current_animal(self) -> str | None: ...
