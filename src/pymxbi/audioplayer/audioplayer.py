from collections import deque
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from threading import Event, Lock, Thread
from time import perf_counter
from typing import Callable, Literal

import numpy as np
import sounddevice as sd
import soundfile as sf

from pymxbi.audioplayer.frequency_response_table import FrequencyResponseTable
from pymxbi.audioplayer.puretone_generator import PureToneUnit

SampleDType = Literal["int16", "float32"]


class PlayStatus(Enum):
    FINISHED = auto()
    CANCELED = auto()
    ERROR = auto()


@dataclass(frozen=True)
class PlayResult:
    status: PlayStatus
    error: Exception | None = None


DoneCallback = Callable[[PlayResult], None]


@dataclass(frozen=True)
class LoadedWav:
    pcm_bytes: bytes
    sample_rate: int
    channels: int
    sample_dtype: SampleDType


class PlayTask:
    def __init__(self):
        self._lock = Lock()
        self._cancel = Event()
        self._done = False
        self._result: PlayResult | None = None
        self._callbacks: list[DoneCallback] = []

    def cancel(self) -> None:
        self._cancel.set()

    def done(self) -> bool:
        with self._lock:
            return self._done

    def on_finish(self, cb: DoneCallback) -> None:
        result: PlayResult | None = None
        with self._lock:
            if self._done and self._result is not None:
                result = self._result
            else:
                self._callbacks.append(cb)
        if result is not None:
            cb(result)

    def _finish(self, result: PlayResult) -> None:
        with self._lock:
            if self._done:
                return
            self._done = True
            self._result = result
            callbacks = self._callbacks
            self._callbacks = []
        for cb in callbacks:
            cb(result)


class AudioPlayer:
    def __init__(self, *, blocksize: int = 1024):
        if blocksize <= 0:
            raise ValueError("blocksize must be positive")
        self._blocksize = blocksize
        self._active_lock = Lock()
        self._active_tasks: set[PlayTask] = set()
        self._done_lock = Lock()
        self._done_deque: deque[tuple[PlayTask, PlayResult]] = deque()
        self._frequency_response_table = FrequencyResponseTable.from_file()

    @property
    def frequency_response_table(self) -> FrequencyResponseTable | None:
        return self._frequency_response_table

    def close(self) -> None:
        self.cancel_all()

    def cancel_all(self) -> int:
        with self._active_lock:
            tasks = list(self._active_tasks)
        for task in tasks:
            task.cancel()
        return len(tasks)

    def update(self) -> None:
        with self._done_lock:
            if not self._done_deque:
                return
            drained = list(self._done_deque)
            self._done_deque.clear()
        for task, result in drained:
            task._finish(result)

    def load_wav(self, file_path: Path) -> LoadedWav:
        wav_path = Path(file_path).expanduser().resolve()
        with sf.SoundFile(str(wav_path), "r") as sound_file:
            channels = sound_file.channels
            sample_rate = sound_file.samplerate
            subtype = sound_file.subtype

            if subtype == "PCM_16":
                data = sound_file.read(dtype="int16", always_2d=False)
                sample_dtype: SampleDType = "int16"
            elif subtype == "FLOAT":
                data = sound_file.read(dtype="float32", always_2d=False)
                sample_dtype = "float32"
            else:
                raise ValueError(
                    f"Unsupported WAV subtype for playback: {subtype} ({wav_path})"
                )

        pcm_bytes = np.ascontiguousarray(data).tobytes()
        return LoadedWav(
            pcm_bytes=pcm_bytes,
            sample_rate=sample_rate,
            channels=channels,
            sample_dtype=sample_dtype,
        )

    def play_wav(self, file_path: Path) -> PlayTask:
        try:
            loaded_wav = self.load_wav(file_path)
        except Exception as e:
            task = PlayTask()
            self._register_task(task)
            self._finish_task(task, PlayResult(PlayStatus.ERROR, error=e))
            return task
        return self.play_loaded_wav(loaded_wav)

    def play_loaded_wav(self, loaded_wav: LoadedWav) -> PlayTask:
        task = PlayTask()
        self._register_task(task)

        def worker() -> None:
            wav_start_t = perf_counter()
            print(f"[wav-start] t={wav_start_t:.6f}")
            try:
                status = self._play_loaded_wav_with_callback(task, loaded_wav)
                wav_end_t = perf_counter()
                total_ms = (wav_end_t - wav_start_t) * 1000
                print(f"[wav-end] t={wav_end_t:.6f} total_ms={total_ms:.2f}")
                self._finish_task(task, PlayResult(status))
            except Exception as e:
                wav_end_t = perf_counter()
                total_ms = (wav_end_t - wav_start_t) * 1000
                print(
                    f"[wav-end] t={wav_end_t:.6f} total_ms={total_ms:.2f} status=ERROR"
                )
                self._finish_task(task, PlayResult(PlayStatus.ERROR, error=e))

        Thread(target=worker, daemon=True).start()
        return task

    def play_puretone_sequence(
        self,
        units: list[PureToneUnit],
        *,
        sample_rate: int = 44100,
    ) -> PlayTask:
        task = PlayTask()
        self._register_task(task)

        if not units:
            self._finish_task(task, PlayResult(PlayStatus.FINISHED))
            return task

        def worker() -> None:
            try:
                status = self._play_puretone_sequence_with_callback(
                    task, units, sample_rate
                )
                self._finish_task(task, PlayResult(status))
            except Exception as e:
                self._finish_task(task, PlayResult(PlayStatus.ERROR, error=e))

        Thread(target=worker, daemon=True).start()
        return task

    def _play_loaded_wav_with_callback(
        self, task: PlayTask, loaded_wav: LoadedWav
    ) -> PlayStatus:
        sample_width = 2 if loaded_wav.sample_dtype == "int16" else 4
        frame_width = sample_width * loaded_wav.channels
        if len(loaded_wav.pcm_bytes) % frame_width != 0:
            raise ValueError(
                f"PCM byte length {len(loaded_wav.pcm_bytes)} is not aligned to frame width {frame_width}"
            )
        total_frames = len(loaded_wav.pcm_bytes) // frame_width

        print(
            f"Playing | {loaded_wav.sample_rate}Hz | {loaded_wav.channels}ch | "
            f"{loaded_wav.sample_dtype} | {total_frames} frames"
        )

        return self._play_pcm_bytes_with_callback(
            task,
            loaded_wav.pcm_bytes,
            sample_rate=loaded_wav.sample_rate,
            channels=loaded_wav.channels,
            sample_dtype=loaded_wav.sample_dtype,
        )

    def _play_puretone_sequence_with_callback(
        self,
        task: PlayTask,
        units: list[PureToneUnit],
        sample_rate: int,
    ) -> PlayStatus:
        if sample_rate <= 0:
            raise ValueError(f"sample_rate must be positive, got {sample_rate}")

        seq_start_t = perf_counter()
        print(f"[seq-start] t={seq_start_t:.6f}")
        baked_parts: list[np.ndarray] = []
        total_frames = 0

        for idx, unit in enumerate(units, start=1):
            if task._cancel.is_set():
                seq_end_t = perf_counter()
                total_ms = (seq_end_t - seq_start_t) * 1000
                print(
                    f"[seq-end] t={seq_end_t:.6f} total_ms={total_ms:.2f} status=CANCELED"
                )
                return PlayStatus.CANCELED

            if unit.stimulus is None:
                raise ValueError(
                    "PureToneUnit.stimulus is None; generate stimulus before playback"
                )
            if unit.stimulus.dtype != np.dtype(np.int16):
                raise ValueError(
                    f"PureToneUnit.stimulus must be int16, got {unit.stimulus.dtype}"
                )

            master_gain = 1.0
            if unit.master_volume is not None:
                master_gain = max(0.0, min(1.0, unit.master_volume / 100.0))
            digital_gain = 1.0
            if unit.digital_volume is not None:
                digital_gain = max(0.0, min(1.0, unit.digital_volume / 100.0))
            combined_gain = master_gain * digital_gain

            stimulus_f32 = unit.stimulus.astype(np.float32)
            if combined_gain != 1.0:
                stimulus_f32 *= combined_gain
            stimulus_f32 = np.clip(stimulus_f32, -32768.0, 32767.0)
            baked_i16 = stimulus_f32.astype(np.int16, copy=False)

            frames = int(baked_i16.shape[0])
            total_frames += frames
            baked_parts.append(baked_i16)

            print(
                f"Baking | unit {idx}/{len(units)} | {unit.frequency_hz}Hz | {unit.duration_ms}ms"
                f" | frames={frames} | gain={combined_gain:.3f}"
            )

        sequence_pcm_bytes = np.concatenate(baked_parts).tobytes()

        print(
            f"Playing | {sample_rate}Hz | 1ch | int16 | {total_frames} frames"
            f" | units={len(units)} | mode=baked-single-stream"
        )

        status = self._play_pcm_bytes_with_callback(
            task,
            sequence_pcm_bytes,
            sample_rate=sample_rate,
            channels=1,
            sample_dtype="int16",
        )
        if status is PlayStatus.CANCELED:
            seq_end_t = perf_counter()
            total_ms = (seq_end_t - seq_start_t) * 1000
            print(
                f"[seq-end] t={seq_end_t:.6f} total_ms={total_ms:.2f} status=CANCELED"
            )
            return PlayStatus.CANCELED

        seq_end_t = perf_counter()
        total_ms = (seq_end_t - seq_start_t) * 1000
        print(f"[seq-end] t={seq_end_t:.6f} total_ms={total_ms:.2f} status=FINISHED")
        return PlayStatus.FINISHED

    def _play_pcm_bytes_with_callback(
        self,
        task: PlayTask,
        pcm_bytes: bytes,
        *,
        sample_rate: int,
        channels: int,
        sample_dtype: SampleDType,
    ) -> PlayStatus:
        sample_width = 2 if sample_dtype == "int16" else 4
        frame_width = sample_width * channels
        if len(pcm_bytes) % frame_width != 0:
            raise ValueError(
                f"PCM byte length {len(pcm_bytes)} is not aligned to frame width {frame_width}"
            )

        cursor = 0
        canceled = False
        callback_error: Exception | None = None
        finished = Event()

        def callback(outdata, frames, _time, status) -> None:
            nonlocal cursor, canceled, callback_error
            if status:
                print(f"[warning] callback status: {status}")

            required = frames * frame_width
            out_view = memoryview(outdata)

            try:
                if task._cancel.is_set():
                    canceled = True
                    out_view[:] = bytes(required)
                    raise sd.CallbackStop()

                remaining = len(pcm_bytes) - cursor
                to_copy = min(remaining, required)

                if to_copy > 0:
                    out_view[:to_copy] = pcm_bytes[cursor : cursor + to_copy]
                    cursor += to_copy

                if to_copy < required:
                    out_view[to_copy:required] = bytes(required - to_copy)
                    raise sd.CallbackStop()

            except sd.CallbackStop:
                raise
            except Exception as e:
                callback_error = e
                raise sd.CallbackAbort()

        with sd.RawOutputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype=sample_dtype,
            blocksize=self._blocksize,
            callback=callback,
            finished_callback=finished.set,
        ):
            finished.wait()

        if callback_error is not None:
            raise callback_error
        if canceled:
            return PlayStatus.CANCELED
        return PlayStatus.FINISHED

    def _register_task(self, task: PlayTask) -> None:
        with self._active_lock:
            self._active_tasks.add(task)

    def _enqueue_done(self, task: PlayTask, result: PlayResult) -> None:
        with self._done_lock:
            self._done_deque.append((task, result))

    def _finish_task(self, task: PlayTask, result: PlayResult) -> None:
        with self._active_lock:
            self._active_tasks.discard(task)
        self._enqueue_done(task, result)
