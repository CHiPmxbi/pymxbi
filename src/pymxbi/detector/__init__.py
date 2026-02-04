from .detector import Detector, DetectorType
from .mock_detector import MockDetector
from .standard_gate_detector import StandardGateDetector
from .rfid_continuous_detector import RFIDContinuousDetector
from .beambreak_continuous_detector import BeambreakContinuousDetector
from .fusion_continuous_detector import FusionContinuousDetector

detectors: dict[str, type[Detector]] = {
    DetectorType.MOCK: MockDetector,
    DetectorType.STANDARD_GATE: StandardGateDetector,
    DetectorType.RFID_CONTINUOUS: RFIDContinuousDetector,
    DetectorType.BEAMBREAK_CONTINUOUS: BeambreakContinuousDetector,
    DetectorType.FUSION_CONTINUOUS: FusionContinuousDetector,
}


__all__ = [
    "Detector",
    "MockDetector",
    "StandardGateDetector",
    "RFIDContinuousDetector",
    "BeambreakContinuousDetector",
    "FusionContinuousDetector",
    "DetectorType",
    "detectors"
]
