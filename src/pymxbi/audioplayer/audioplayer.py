import wave
from collections import deque
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Callable

import numpy as np
import pyaudio
from pyaudio import PyAudio

from pymxbi.audioplayer.frequency_response_table import FrequencyResponseTable
from pymxbi.audioplayer.puretone_generator import PureToneUnit
from pymxbi.infra.amixer import set_digital_volume, set_master_volume


# --- Result types ---
class PlayStatus(Enum):
    FINISHED = auto()
    CANCELED = auto()
    ERROR = auto()


@dataclass(frozen=True)
class PlayResult:
    status: PlayStatus
    error: BaseException | None = None


DoneCallback = Callable[[PlayResult], None]


@dataclass(frozen=True)
class _WavCacheEntry:
    pcm_bytes: bytes
    sample_rate: int
    channels: int
    sample_width_bytes: int
    mtime_ns: int
    size: int


# --- Task handle (main-thread callbacks) ---
class PlayTask:
    def __init__(self):
        self._cancel = Event()
        self._done = False
        self._result: PlayResult | None = None
        self._callbacks: list[DoneCallback] = []

    def cancel(self) -> None:
        self._cancel.set()

    def done(self) -> bool:
        return self._done

    def on_finish(self, cb: DoneCallback) -> None:
        if self._done and self._result is not None:
            # Already finished: invoke immediately in caller thread.
            cb(self._result)
            return
        self._callbacks.append(cb)

    def _finish(self, result: PlayResult) -> None:
        if self._done:
            return
        self._done = True
        self._result = result
        cbs = self._callbacks
        self._callbacks = []
        for cb in cbs:
            cb(result)


# --- Player ---
class AudioPlayer:
    def __init__(self):
        self._pa = PyAudio()
        self._active_lock = Lock()
        self._active_tasks: set[PlayTask] = set()
        self._wav_cache_lock = Lock()
        self._wav_cache: dict[Path, _WavCacheEntry] = {}
        self._done_lock = Lock()
        self._done_deque: deque[tuple[PlayTask, PlayResult]] = deque()
        self._frequency_response_table = FrequencyResponseTable.from_file()

    @property
    def frequency_response_table(self) -> FrequencyResponseTable | None:
        return self._frequency_response_table

    def close(self) -> None:
        self.cancel_all()
        self._pa.terminate()

    def cancel_all(self) -> int:
        """
        Request cancellation for all currently playing tasks.

        Cancellation is cooperative: tasks stop between audio chunk writes.
        Returns the number of tasks that were asked to cancel.
        """
        with self._active_lock:
            tasks = list(self._active_tasks)
        for task in tasks:
            task.cancel()
        return len(tasks)

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

    def update(self) -> None:
        # Drain completion queue and dispatch callbacks on the main thread.
        with self._done_lock:
            if not self._done_deque:
                return
            drained = list(self._done_deque)
            self._done_deque.clear()
        for task, result in drained:
            task._finish(result)

    def play_wav(
        self, file_path: Path, *, on_done: DoneCallback | None = None
    ) -> PlayTask:
        task = PlayTask()
        self._register_task(task)
        if on_done:
            task.on_finish(on_done)

        wav_path = Path(file_path).expanduser().resolve()
        try:
            st = wav_path.stat()
        except OSError:
            st = None

        if st is not None:
            with self._wav_cache_lock:
                cached = self._wav_cache.get(wav_path)
            if (
                cached is not None
                and cached.mtime_ns == st.st_mtime_ns
                and cached.size == st.st_size
            ):
                self._play_pcm_async(
                    task,
                    cached.pcm_bytes,
                    cached.sample_rate,
                    cached.channels,
                    cached.sample_width_bytes,
                )
                return task

        try:
            with wave.open(str(wav_path), "rb") as wf:
                channels = wf.getnchannels()
                sample_rate = wf.getframerate()
                sample_width_bytes = wf.getsampwidth()
                frame_count = wf.getnframes()
                pcm_bytes = wf.readframes(frame_count)
        except BaseException as e:
            self._finish_task(task, PlayResult(PlayStatus.ERROR, error=e))
            return task

        if st is None:
            try:
                st = wav_path.stat()
            except OSError:
                st = None
        if st is not None:
            with self._wav_cache_lock:
                self._wav_cache[wav_path] = _WavCacheEntry(
                    pcm_bytes=pcm_bytes,
                    sample_rate=sample_rate,
                    channels=channels,
                    sample_width_bytes=sample_width_bytes,
                    mtime_ns=st.st_mtime_ns,
                    size=st.st_size,
                )

        self._play_pcm_async(task, pcm_bytes, sample_rate, channels, sample_width_bytes)
        return task

    def play_pcm(
        self,
        pcm_bytes: bytes,
        *,
        on_done: DoneCallback | None = None,
        sample_rate: int = 44100,
        channels: int = 1,
        sample_width_bytes: int = 2,
    ) -> PlayTask:
        task = PlayTask()
        self._register_task(task)
        if on_done:
            task.on_finish(on_done)

        self._play_pcm_async(task, pcm_bytes, sample_rate, channels, sample_width_bytes)
        return task

    def play_puretone_sequence(
        self,
        units: list[PureToneUnit],
        *,
        sample_rate: int = 44100,
        on_done: DoneCallback | None = None,
    ) -> PlayTask:
        task = PlayTask()
        self._register_task(task)
        if on_done:
            task.on_finish(on_done)

        if not units:
            self._finish_task(task, PlayResult(PlayStatus.FINISHED))
            return task

        self._play_puretone_sequence_async(task, units, sample_rate)

        return task

    def _play_puretone_sequence_async(
        self,
        task: PlayTask,
        units: list[PureToneUnit],
        sample_rate: int,
    ) -> None:
        def worker() -> None:
            stream = None
            try:
                if sample_rate <= 0:
                    raise ValueError(f"sample_rate must be positive, got {sample_rate}")

                for u in units:
                    if u.stimulus is None:
                        raise ValueError(
                            "PureToneUnit.stimulus is None; generate stimulus via PureToneGenerator before playback"
                        )
                    if u.stimulus.dtype != np.dtype(np.int32):
                        raise ValueError(
                            f"PureToneUnit.stimulus must be int32, got {u.stimulus.dtype}"
                        )

                stream = self._pa.open(
                    format=pyaudio.paInt32,
                    channels=1,
                    rate=sample_rate,
                    output=True,
                )

                chunk = 4096
                for unit in units:
                    if task._cancel.is_set():
                        self._finish_task(task, PlayResult(PlayStatus.CANCELED))
                        return

                    # Apply per-unit volume overrides before playback.
                    if unit.master_volume is not None:
                        set_master_volume(unit.master_volume)
                    if unit.digital_volume is not None:
                        set_digital_volume(unit.digital_volume)

                    data = _unit_to_pcm_bytes(unit, sample_rate=sample_rate)

                    for i in range(0, len(data), chunk):
                        if task._cancel.is_set():
                            self._finish_task(task, PlayResult(PlayStatus.CANCELED))
                            return
                        # Write in chunks so cancel() can interrupt between writes.
                        stream.write(data[i : i + chunk])

                self._finish_task(task, PlayResult(PlayStatus.FINISHED))

            except BaseException as e:
                self._finish_task(task, PlayResult(PlayStatus.ERROR, error=e))

            finally:
                try:
                    if stream is not None:
                        stream.stop_stream()
                        stream.close()
                except Exception:
                    pass

        Thread(target=worker, daemon=True).start()

    def _play_pcm_async(
        self,
        task: PlayTask,
        pcm_bytes: bytes,
        sample_rate: int,
        channels: int,
        sample_width_bytes: int,
    ) -> None:
        def worker() -> None:
            stream = None
            try:
                match sample_width_bytes:
                    case 2:
                        fmt = pyaudio.paInt16
                    case 1:
                        fmt = pyaudio.paUInt8
                    case 3:
                        fmt = pyaudio.paInt24
                    case 4:
                        fmt = pyaudio.paInt32
                    case _:
                        raise ValueError(
                            f"Unsupported sample width: {sample_width_bytes}"
                        )

                stream = self._pa.open(
                    format=fmt,
                    channels=channels,
                    rate=sample_rate,
                    output=True,
                )

                chunk = 4096
                for i in range(0, len(pcm_bytes), chunk):
                    if task._cancel.is_set():
                        self._finish_task(task, PlayResult(PlayStatus.CANCELED))
                        return
                    # Blocking write happens on a background thread.
                    stream.write(pcm_bytes[i : i + chunk])

                self._finish_task(task, PlayResult(PlayStatus.FINISHED))

            except BaseException as e:
                self._finish_task(task, PlayResult(PlayStatus.ERROR, error=e))

            finally:
                try:
                    if stream is not None:
                        stream.stop_stream()
                        stream.close()
                except Exception:
                    pass

        Thread(target=worker, daemon=True).start()


# --- Helpers ---
def _unit_to_pcm_bytes(unit: PureToneUnit, *, sample_rate: int) -> bytes:
    if unit.stimulus is not None:
        return unit.stimulus.tobytes()

    raise ValueError(
        "PureToneUnit.stimulus is None; generate stimulus via PureToneGenerator before playback"
    )
