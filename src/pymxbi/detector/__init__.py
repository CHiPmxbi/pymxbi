from typing import Annotated, Literal, TypeAlias, Union

from pydantic import BaseModel, Field

from .beambreak_continuous_detector import BeambreakContinuousDetector
from .detector import Detector, DetectorEnum
from .mock_detector import MockDetector
from .rfid_continuous_detector import RFIDContinuousDetector
from .standard_gate_detector import StandardGateDetector

detectors: dict[str, type[Detector]] = {
    DetectorEnum.MOCK: MockDetector,
    DetectorEnum.STANDARD_GATE: StandardGateDetector,
    DetectorEnum.RFID_CONTINUOUS: RFIDContinuousDetector,
    DetectorEnum.BEAMBREAK_CONTINUOUS: BeambreakContinuousDetector,
}


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

    @property
    def device_type(self) -> str:
        return str(self.type)


class BeamBreakContinuousDetectorModel(BaseModel):
    type: Literal[DetectorEnum.BEAMBREAK_CONTINUOUS] = DetectorEnum.BEAMBREAK_CONTINUOUS
    id: int = Field(default=0, ge=0)

    enabled: bool = False

    pin: int = Field(default=17, ge=0)

    @property
    def device_type(self) -> str:
        return str(self.type)


class FusionContinuousDetectorModel(BaseModel):
    type: Literal[DetectorEnum.FUSION_CONTINUOUS] = DetectorEnum.FUSION_CONTINUOUS
    id: int = Field(default=0, ge=0)

    enabled: bool = False

    pin: int = Field(default=17, ge=0)
    port: str = Field(default="/dev/ttyUSB0")
    baudrate: int = Field(default=9600, ge=1)

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
    "Detector",
    "MockDetector",
    "MockDetectorModel",
    "StandardGateDetector",
    "RFIDContinuousDetector",
    "RFIDContinuousDetectorModel",
    "BeambreakContinuousDetector",
    "BeamBreakContinuousDetectorModel",
    "FusionContinuousDetectorModel",
    "DetectorEnum",
    "DetectorModel",
    "detectors",
]
