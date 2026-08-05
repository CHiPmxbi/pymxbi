# pymxbi

Python interfaces and drivers for mxbi

English | [中文](README.zh.md)

## Install

```bash
pip install pymxbi
```

Or with `uv`:

```bash
uv add pymxbi
```

## Public API

### Detectors

- Core types: `pymxbi.detector.detector.Detector`, `DetectorEvent`, and `DetectionResult`
- `pymxbi.detector.RFIDContinuousDetector`: RFID presence detection
- `pymxbi.detector.BeambreakContinuousDetector`: beam-break presence detection
- `pymxbi.detector.FusionContinuousDetector`: combined beam-break and RFID detection
- `pymxbi.detector.MockDetector`: in-memory detector for testing and development
- Configuration models: `DetectorModel`, `MockDetectorModel`, `RFIDContinuousDetectorModel`, `BeamBreakContinuousDetectorModel`, and `FusionContinuousDetectorModel`

### Rewarders

- `pymxbi.rewarder.rewarder.Rewarder`: reward backend protocol (`open`, `give_reward*`, `stop_reward`, `close`)
- `pymxbi.rewarder.pump_rewarder.PumpRewarder`: time-based reward delivery via a pump
- `pymxbi.rewarder.mock_rewarder.MockRewarder`: logging-only mock implementation

### Peripherals

- Pumps: `pymxbi.peripheral.pumps.pump.Pump` / `Direction`, `pymxbi.peripheral.pumps.RPI_gpio_pump.RPIGpioPump`
- Beam-break sensors: `pymxbi.peripheral.beam_break_sensor.BeamBreakSensor`, `RPIIRBreakBeamSensor`
- RFID reader: `pymxbi.peripheral.rfid.dorset_lid665v42.DorsetLID665v42` (`open`, `begin`, `read`, `close`, `errno`)

### Utilities

- Audio volume: `pymxbi.infra.set_master_volume`, `set_digital_volume` (calls `amixer`)

## Notes

- Typed package (`py.typed`), requires Python `>=3.14`.
