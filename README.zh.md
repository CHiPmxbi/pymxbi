# pymxbi

为 mxbi 硬件设备提供面向 Python 的接口与驱动

中文 | [English](README.md)

## 安装

```bash
pip install pymxbi
```

或使用 `uv`：

```bash
uv add pymxbi
```

## 对外接口

### 检测器（Detectors）

- 核心类型：`pymxbi.detector.detector.Detector`、`DetectorEvent` 和 `DetectionResult`
- `pymxbi.detector.RFIDContinuousDetector`：RFID 在场检测
- `pymxbi.detector.BeambreakContinuousDetector`：红外断光在场检测
- `pymxbi.detector.FusionContinuousDetector`：红外断光与 RFID 融合检测
- `pymxbi.detector.MockDetector`：用于测试和开发的内存检测器
- 配置模型：`DetectorModel`、`MockDetectorModel`、`RFIDContinuousDetectorModel`、`BeamBreakContinuousDetectorModel` 和 `FusionContinuousDetectorModel`

### 奖励器（Rewarders）

- `pymxbi.rewarder.rewarder.Rewarder`：奖励后端协议（`open`, `give_reward*`, `stop_reward`, `close`）
- `pymxbi.rewarder.pump_rewarder.PumpRewarder`：基于泵的时间型奖励发放
- `pymxbi.rewarder.mock_rewarder.MockRewarder`：仅记录日志的 mock 实现

### 外设（Peripherals）

- 泵：`pymxbi.peripheral.pumps.pump.Pump` / `Direction`，`pymxbi.peripheral.pumps.RPI_gpio_pump.RPIGpioPump`
- 断光传感器：`pymxbi.peripheral.beam_break_sensor.BeamBreakSensor`、`RPIIRBreakBeamSensor`
- RFID 读卡器：`pymxbi.peripheral.rfid.dorset_lid665v42.DorsetLID665v42`（`open`, `begin`, `read`, `close`, `errno`）

### 工具

- 音量控制：`pymxbi.infra.set_master_volume`、`set_digital_volume`（内部调用 `amixer`）

## 说明

- 包含类型信息（`py.typed`），要求 Python `>=3.14`。
