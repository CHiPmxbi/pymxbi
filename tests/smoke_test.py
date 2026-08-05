def main() -> None:
    import pymxbi

    assert pymxbi.__name__ == "pymxbi"

    from pymxbi.detector import (  # noqa: F401
        BeambreakContinuousDetector,
        BeamBreakContinuousDetectorModel,
        Detector,
        DetectorEnum,
        DetectorModel,
        FusionContinuousDetector,
        FusionContinuousDetectorModel,
        MockDetector,
        MockDetectorModel,
        RFIDContinuousDetector,
        RFIDContinuousDetectorModel,
    )
    from pymxbi.mxbi import (  # noqa: F401
        MXBI,
        MXBIModel,
        build_mxbi,
        get_mxbi,
        set_mxbi,
    )
    from pymxbi.rewarder import (  # noqa: F401
        GPIORewarderModel,
        MockRewarder,
        MockRewarderModel,
        Rewarder,
        RewarderEnum,
        RewarderModel,
        RPIGpioRewarder,
        rewarders,
    )


if __name__ == "__main__":
    main()
