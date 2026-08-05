from typing import Annotated, Literal, TypeAlias, Union

from pydantic import BaseModel, Field

from .beambreak_continuous_detector import BeambreakContinuousDetector
from .detector import Detector, DetectorEnum
from .fusion_continuous_detector import FusionContinuousDetector
from .mock_detector import MockDetector
from .rfid_continuous_detector import RFIDContinuousDetector


class MockDetectorModel(BaseModel):
    type: Literal[DetectorEnum.MOCK] = DetectorEnum.MOCK
    id: int = Field(default=0, ge=0)

    enabled: bool = False

    @property
    def device_type(self) -> str:
        return str(self.type)


class RFIDContinuousDetectorModel(BaseModel):
    type: Literal[DetectorEnum.RFID_CONTINUOUS] = DetectorEnum.RFID_CONTINUOUS
    id: int = Field(default=0, ge=0)

    enabled: bool = False

    port: str = Field(default="/dev/ttyUSB0")
    baudrate: int = Field(default=9600, ge=1)

    poll_interval: float = 1.0
    max_tag_age_seconds: float = 1.0

    @property
    def device_type(self) -> str:
        return str(self.type)


class BeamBreakContinuousDetectorModel(BaseModel):
    type: Literal[DetectorEnum.BEAMBREAK_CONTINUOUS] = DetectorEnum.BEAMBREAK_CONTINUOUS
    id: int = Field(default=0, ge=0)

    enabled: bool = False

    pin: int = Field(default=11, ge=0)
    animal_id: str = "unknown"
    poll_interval: float = 1.0

    @property
    def device_type(self) -> str:
        return str(self.type)


class FusionContinuousDetectorModel(BaseModel):
    type: Literal[DetectorEnum.FUSION_CONTINUOUS] = DetectorEnum.FUSION_CONTINUOUS
    id: int = Field(default=0, ge=0)

    enabled: bool = False

    pin: int = Field(default=11, ge=0)

    port: str = Field(default="/dev/ttyUSB0")
    baudrate: int = Field(default=57600, ge=1)

    poll_interval: float = 10.0
    rfid_timeout: float = 0.05

    @property
    def device_type(self) -> str:
        return str(self.type)


DetectorModel: TypeAlias = Annotated[
    Union[
        MockDetectorModel,
        RFIDContinuousDetectorModel,
        BeamBreakContinuousDetectorModel,
        FusionContinuousDetectorModel,
    ],
    Field(discriminator="type"),
]


__all__ = [
    "BeamBreakContinuousDetectorModel",
    "BeambreakContinuousDetector",
    "Detector",
    "DetectorEnum",
    "DetectorModel",
    "FusionContinuousDetector",
    "FusionContinuousDetectorModel",
    "MockDetector",
    "MockDetectorModel",
    "RFIDContinuousDetector",
    "RFIDContinuousDetectorModel",
]
