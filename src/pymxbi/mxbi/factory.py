from pydantic import BaseModel, Field

from ..detector import (
    BeambreakContinuousDetector,
    Detector,
    DetectorEnum,
    DetectorModel,
    FusionContinuousDetector,
    MockDetector,
    RFIDContinuousDetector,
)
from ..peripheral.beam_break_sensor import RPIIRBreakBeamSensor
from ..peripheral.rfid import DorsetLID665v42
from ..rewarder import (
    MockRewarder,
    Rewarder,
    RewarderEnum,
    RewarderModel,
    RPIGpioRewarder,
)
from .mxbi import MXBI


class MXBIModel(BaseModel):
    mxbi_id: str = Field(default="debug")
    screen_size: tuple[int, int] = Field(default=(1024, 600))
    rewarders: list[RewarderModel] = Field(default_factory=list)
    detectors: list[DetectorModel] = Field(default_factory=list)


def build_mxbi(config: MXBIModel, logger=None) -> MXBI:
    return MXBI(
        config.screen_size,
        _build_rewarders(config.rewarders, logger),
        _build_detectors(config.detectors),
    )


def _build_rewarders(
    configs: list[RewarderModel],
    logger=None,
) -> dict[int, Rewarder]:

    enabled = [c for c in configs if c.enabled]
    if not enabled:
        raise ValueError("No rewarders configured")

    rewarders = {c.id: _make_rewarder(c, logger) for c in enabled}
    return rewarders


def _make_rewarder(config: RewarderModel, logger=None) -> Rewarder:
    match config.type:
        case RewarderEnum.MOCK:
            return MockRewarder(logger)

        case RewarderEnum.RPI_GPIO:
            return RPIGpioRewarder(config.pin)

        case _:
            raise ValueError(f"Unknown rewarder type: {config.type}")


def _build_detectors(configs: list[DetectorModel]) -> dict[int, Detector]:
    enabled = [c for c in configs if c.enabled]
    if not enabled:
        raise ValueError("No detectors configured")

    detectors = {c.id: _make_detector(c) for c in enabled}
    return detectors


def _make_detector(config: DetectorModel) -> Detector:
    match config.type:
        case DetectorEnum.MOCK:
            return MockDetector()

        case DetectorEnum.RFID_CONTINUOUS:
            rfid_reader = DorsetLID665v42(config.port, config.baudrate)
            return RFIDContinuousDetector(rfid_reader)

        case DetectorEnum.BEAMBREAK_CONTINUOUS:
            sensor = RPIIRBreakBeamSensor(config.pin)
            return BeambreakContinuousDetector(sensor)

        case DetectorEnum.FUSION_CONTINUOUS:
            rfid_reader = DorsetLID665v42(config.port, config.baudrate)
            sensor = RPIIRBreakBeamSensor(config.pin)
            return FusionContinuousDetector(rfid_reader, sensor)

        case _:
            raise ValueError(f"Unknown detector type: {config.type}")
