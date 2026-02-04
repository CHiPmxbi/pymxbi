from dataclasses import dataclass, field
from enum import StrEnum, auto
from time import time, sleep
from typing import Callable

from ..peripheral.beam_break_sensor import BeamBreakSensor
from ..peripheral.rfid import RFIDReader, RFIDTag
from .detector import DetectionResult, DetectorEvent


@dataclass
class GateSensors:
    rfid: RFIDReader
    b1: BeamBreakSensor
    b2: BeamBreakSensor


@dataclass
class _GateSensorState:
    now: float
    rfid_tag: RFIDTag | None
    b1_on: bool
    b1_off: bool
    b2_on: bool
    b2_off: bool


class _DetectorState(StrEnum):
    IDLE = auto()
    DETECTING = auto()
    FAULT = auto()


class _Direction(StrEnum):
    ENTER = auto()
    LEAVE = auto()


@dataclass
class _DetectorCtx:
    direction: _Direction
    step: int
    start_ts: float
    last_ts: float
    tags: dict[str, RFIDTag] = field(default_factory=dict)


class GateStateMachine:
    def __init__(self, detector: StandardGateDetector) -> None:
        self._detector = detector
        self._state: _DetectorState = _DetectorState.IDLE
        self._ctx: _DetectorCtx | None = None

    def transition(self, state: _GateSensorState) -> None:
        if self._ctx is not None and state.rfid_tag is not None:
            self._ctx.last_ts = state.now
            if state.rfid_tag.detect_time > self._ctx.start_ts:
                if state.rfid_tag.animal_id is not None:
                    self._ctx.tags[state.rfid_tag.animal_id] = state.rfid_tag

        match self._state:
            case _DetectorState.IDLE:
                self._handle_idle(state)
            case _DetectorState.DETECTING:
                self._handle_detecting(state)
            case _DetectorState.FAULT:
                self._handle_fault(state)

    def _handle_idle(self, state: _GateSensorState) -> None:
        first_on = (state.b1_on and not state.b2_on) or (
            state.b2_on and not state.b1_on
        )

        if first_on:
            direction = _Direction.ENTER if state.b1_on else _Direction.LEAVE
            self._ctx = _DetectorCtx(
                direction=direction,
                step=1,
                start_ts=state.now,
                last_ts=state.now,
            )
            self._state = _DetectorState.DETECTING
            return

        if state.b1_on and state.b2_on:
            self._state = _DetectorState.FAULT
            return

    def _handle_detecting(self, state: _GateSensorState) -> None:
        assert self._ctx is not None
        self._ctx.last_ts = state.now

        if self._ctx.direction == _Direction.ENTER:
            self._advance_enter(state)
        else:
            self._advance_leave(state)

    def _advance_enter(self, state: _GateSensorState) -> None:
        assert self._ctx is not None

        step = self._ctx.step

        if step == 1:
            if state.b2_on:
                self._ctx.step = 2
                return

            if state.b1_off:
                self._state = _DetectorState.IDLE
                return

        elif step == 2:
            if state.b1_off:
                self._ctx.step = 3
                return

            if state.b2_off:
                self._ctx.step = 1
                return

        elif step == 3:
            if state.b2_off:
                self._finish(_Direction.ENTER)
                return

            if state.b1_on:
                self._ctx.step = 2
                return

    def _advance_leave(self, state: _GateSensorState) -> None:
        assert self._ctx is not None

        step = self._ctx.step

        if step == 1:
            if state.b1_on:
                self._ctx.step = 2
                return

            if state.b2_off:
                self._state = _DetectorState.IDLE
                return

        elif step == 2:
            if state.b2_off:
                self._ctx.step = 3
                return

            if state.b1_off:
                self._ctx.step = 1
                return

        elif step == 3:
            if state.b1_off:
                self._finish(_Direction.LEAVE)
                return
            if state.b2_on:
                self._ctx.step = 2
                return

    def _finish(self, direction: _Direction):
        assert self._ctx is not None

        last_ts = self._ctx.last_ts
        animal_db = self._detector._animal_db

        results = [
            DetectionResult(
                timestamp=last_ts, animal_id=animal_id, animal_name=animal_name
            )
            for tag in self._ctx.tags.values()
            if (animal_id := tag.animal_id) is not None
            and (animal_name := animal_db.get(animal_id)) is not None
        ]

        if not results:
            results.append(
                DetectionResult(
                    timestamp=self._ctx.last_ts,
                    animal_id=None,
                    animal_name=None,
                )
            )

        handler = (
            self._handle_animal_entered
            if direction == _Direction.ENTER
            else self._handle_animal_left
        )
        for result in results:
            handler(result)

        self._state = _DetectorState.IDLE
        self._ctx = None

    def _handle_fault(self, state: _GateSensorState) -> None: ...
    def _handle_animal_entered(self, result: DetectionResult) -> None:
        self._detector._emit_event(DetectorEvent.ANIMAL_ENTERED, result)

    def _handle_animal_left(self, result: DetectionResult) -> None:
        self._detector._emit_event(DetectorEvent.ANIMAL_LEFT, result)


class StandardGateDetector:
    def __init__(self, animal_db: dict[str, str], sensors: GateSensors) -> None:
        self._callbacks: dict[
            DetectorEvent, list[Callable[[DetectionResult], None]]
        ] = {}

        self._animal_db = animal_db
        self._sensors = sensors

        self._state_machine = GateStateMachine(self)

        self._running = False

    def process_detection(self, detection_result: DetectionResult) -> None: ...

    def register_event(
        self, event: DetectorEvent, callback: Callable[[DetectionResult], None]
    ) -> None:
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)

    def begin(self) -> None:
        self._running = True

    def quit(self) -> None:
        self._running = False

    def _emit_event(
        self, event: DetectorEvent, detection_result: DetectionResult
    ) -> None:
        """Emit an event to registered callbacks."""
        if event not in self._callbacks:
            return
        for callback in self._callbacks[event]:
            callback(detection_result)

    def _worker(self) -> None:
        prev_b1 = self._sensors.b1.read()
        prev_b2 = self._sensors.b2.read()
        while self._running:
            now = time()

            tag = self._sensors.rfid.read()

            b1 = self._sensors.b1.read()
            b2 = self._sensors.b2.read()

            b1_on = b1 and not prev_b1
            b1_off = not b1 and prev_b1
            b2_on = b2 and not prev_b2
            b2_off = not b2 and prev_b2

            state = _GateSensorState(
                now=now,
                rfid_tag=tag,
                b1_on=b1_on,
                b1_off=b1_off,
                b2_on=b2_on,
                b2_off=b2_off,
            )

            self._state_machine.transition(state)

            prev_b1 = b1
            prev_b2 = b2

            sleep(0.01)

    @property
    def current_animal(self) -> str | None: ...

    @property
    def animal_list(self) -> list[str]: ...
