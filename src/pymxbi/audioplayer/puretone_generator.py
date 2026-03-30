from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from numpy.typing import NDArray


@dataclass
class PureToneUnit:
    frequency_hz: int  # Hz
    duration_ms: int  # ms
    intensity: float | None = None  # 0.0~1.0, None -> generator default
    stimulus: NDArray[np.int16] | None = None
    master_volume: int | None = None
    digital_volume: int | None = None


class PureToneGenerator:
    def __init__(
        self,
        sample_rate: int = 44100,
        fade_ms: float = 4.5,
        intensity: float = 0.5,
        cache_size: int = 128,
    ) -> None:
        if not (0.0 <= intensity <= 1.0):
            raise ValueError(f"intensity must be in [0.0, 1.0], got {intensity}")
        self.sample_rate = sample_rate
        self.fade_ms = fade_ms
        self.intensity = intensity
        self._cached_wave_unit = lru_cache(maxsize=cache_size)(self._wave_unit_impl)

    # ---------- low-level ----------

    def _wave_unit_impl(
        self, frequency: int, duration: int, intensity: float
    ) -> NDArray[np.int16]:
        samples = int(self.sample_rate * duration / 1000)
        if samples <= 0:
            return np.zeros(0, dtype=np.int16)

        if frequency <= 0:
            return np.zeros(samples, dtype=np.int16)

        if intensity <= 0:
            return np.zeros(samples, dtype=np.int16)

        t = np.arange(samples) / self.sample_rate
        tone = np.sin(2 * np.pi * frequency * t)

        fade_samples = min(
            int(self.fade_ms * self.sample_rate / 1000),
            samples // 2,
        )
        if fade_samples > 0:
            envelope = np.ones(samples)
            envelope[:fade_samples] = np.linspace(0, 1, fade_samples)
            envelope[-fade_samples:] = np.linspace(1, 0, fade_samples)
            tone *= envelope

        max_i16 = np.iinfo(np.int16).max
        scaled = tone * (max_i16 * intensity)
        scaled = np.clip(scaled, -max_i16, max_i16)
        return scaled.astype(np.int16)

    def gen_wave_unit(
        self, frequency: int, duration: int, *, intensity: float | None = None
    ) -> NDArray[np.int16]:
        effective_intensity = self.intensity if intensity is None else intensity
        if not (0.0 <= effective_intensity <= 1.0):
            raise ValueError(
                f"intensity must be in [0.0, 1.0], got {effective_intensity}"
            )
        return self._cached_wave_unit(frequency, duration, effective_intensity).copy()

    # ---------- public ----------

    def gen_stimulus_unit(
        self,
        unit: PureToneUnit,
    ) -> PureToneUnit:
        stimulus = self.gen_wave_unit(
            unit.frequency_hz, unit.duration_ms, intensity=unit.intensity
        )

        return PureToneUnit(
            frequency_hz=unit.frequency_hz,
            duration_ms=unit.duration_ms,
            intensity=unit.intensity,
            stimulus=stimulus,
            master_volume=unit.master_volume,
            digital_volume=unit.digital_volume,
        )

    def generate_stimulus_sequence(
        self,
        units: list[PureToneUnit],
        total_duration: int,  # ms
    ) -> list[PureToneUnit]:
        if total_duration <= 0 or not units:
            return []

        unit_durations = [u.duration_ms for u in units]
        cycle_duration = sum(unit_durations)
        if cycle_duration <= 0:
            return []

        k, r = divmod(total_duration, cycle_duration)

        sequence = [self.gen_stimulus_unit(u) for _ in range(k) for u in units]

        for unit, dur in zip(units, unit_durations):
            if r >= dur:
                r -= dur
                sequence.append(self.gen_stimulus_unit(unit))
            else:
                break

        return sequence
