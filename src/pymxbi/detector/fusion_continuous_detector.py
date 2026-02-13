"""Detector combining a through-beam sensor and an RFID reader."""

from __future__ import annotations

from enum import Enum, auto
from threading import Thread, Event, Lock
from time import sleep, time
from typing import Callable, NamedTuple

from pymxbi.peripheral.beam_break_sensor.beam_break_sensor import BeamBreakSensor
from pymxbi.peripheral.rfid.rfid import RFIDReader, RFIDTag

from .detector import DetectionResult, DetectorEvent


# ---------------------------------------------------------------------------
# State-machine enums
# ---------------------------------------------------------------------------


class _State(Enum):
    """Internal states of the fusion detector."""

    IDLE = auto()  # Beam clear, no animal
    ANIMAL_PRESENT = auto()  # Beam broken, waiting for RFID (within 10 s)
    ANIMAL_CONFIRMED = auto()  # Beam broken and RFID matched
    ANIMAL_UNCONFIRMED = auto()  # Beam broken, RFID timed out (unknown animal)


class _Event(Enum):
    """Events that drive the state machine."""

    RISING_EDGE = auto()  # Beam just broken  (animal enters)
    FALLING_EDGE = auto()  # Beam just restored (animal leaves)
    RFID_READ = auto()  # Valid RFID tag obtained within window
    TIMEOUT = auto()  # 10 s elapsed without RFID while beam broken


# ---------------------------------------------------------------------------
# Transition-table type
# ---------------------------------------------------------------------------

_Action = Callable[[], None]


class _Transition(NamedTuple):
    next_state: _State
    action: _Action


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RFID_TIMEOUT_S: float = 10.0
_POLL_INTERVAL_S: float = 0.05


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class FusionContinuousDetector:
    """Fuses a through-beam sensor with an RFID reader.

    Implements the :class:`Detector` protocol.

    Detection logic
    ---------------
    * **Rising edge** (beam broken — animal arrives): start a 10 s window to
      acquire an RFID tag.  If a tag whose ``detect_time`` falls within the
      window is read, emit ``ANIMAL_ENTERED`` with the animal's identity.
      If the window expires without a valid tag, emit
      ``UNKNOWN_ANIMAL_ENTERED`` with ``animal_id=None`` and ``error=True``
      (unknown animal).
    * **Falling edge** (beam restored — animal leaves): emit ``ANIMAL_LEFT``
      immediately — no recent RFID result is required.
    """

    # ---- construction ----------------------------------------------------

    def __init__(
        self,
        rfid_reader: RFIDReader,
        beam_break_sensor: BeamBreakSensor,
        poll_interval: float = _POLL_INTERVAL_S,
        rfid_timeout: float = _RFID_TIMEOUT_S,
    ) -> None:
        self._rfid_reader = rfid_reader
        self._beam_break_sensor = beam_break_sensor
        self._poll_interval = poll_interval
        self._rfid_timeout = rfid_timeout

        # Event callbacks: DetectorEvent -> list of subscribers
        self._callbacks: dict[
            DetectorEvent, list[Callable[[DetectionResult], None]]
        ] = {evt: [] for evt in DetectorEvent}

        # State-machine bookkeeping
        self._state: _State = _State.IDLE
        self._prev_beam: bool = False
        self._edge_time: float = 0.0
        self._last_tag: RFIDTag | None = None
        self._current_animal: str | None = None

        # Thread control
        self._lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None

        # fmt: off
        # ---- transition table ------------
        noop = self._noop
        self._table: dict[tuple[_State, _Event], _Transition] = {
            # -- IDLE ------------------------------------------------------
            (_State.IDLE, _Event.RISING_EDGE):  _Transition(_State.ANIMAL_PRESENT, self._on_rising_edge),
            (_State.IDLE, _Event.FALLING_EDGE): _Transition(_State.IDLE, noop),
            (_State.IDLE, _Event.RFID_READ):    _Transition(_State.IDLE, noop),
            (_State.IDLE, _Event.TIMEOUT):      _Transition(_State.IDLE, noop),
            # -- ANIMAL_PRESENT (beam broken, awaiting RFID) ---------------
            (_State.ANIMAL_PRESENT, _Event.RISING_EDGE):  _Transition(_State.ANIMAL_PRESENT, noop),
            (_State.ANIMAL_PRESENT, _Event.FALLING_EDGE): _Transition(_State.IDLE, self._on_left_unconfirmed),
            (_State.ANIMAL_PRESENT, _Event.RFID_READ):    _Transition(_State.ANIMAL_CONFIRMED, self._on_entered_confirmed),
            (_State.ANIMAL_PRESENT, _Event.TIMEOUT):      _Transition(_State.ANIMAL_UNCONFIRMED, self._on_entered_unknown),
            # -- ANIMAL_CONFIRMED (beam broken, RFID matched) --------------
            (_State.ANIMAL_CONFIRMED, _Event.RISING_EDGE):  _Transition(_State.ANIMAL_CONFIRMED, noop),
            (_State.ANIMAL_CONFIRMED, _Event.FALLING_EDGE): _Transition(_State.IDLE, self._on_left_confirmed),
            (_State.ANIMAL_CONFIRMED, _Event.RFID_READ):    _Transition(_State.ANIMAL_CONFIRMED, noop),
            (_State.ANIMAL_CONFIRMED, _Event.TIMEOUT):      _Transition(_State.ANIMAL_CONFIRMED, noop),
            # -- ANIMAL_UNCONFIRMED (beam broken, RFID timed out) ----------
            (_State.ANIMAL_UNCONFIRMED, _Event.RISING_EDGE):  _Transition(_State.ANIMAL_UNCONFIRMED, noop),
            (_State.ANIMAL_UNCONFIRMED, _Event.FALLING_EDGE): _Transition(_State.IDLE, self._on_left_unconfirmed),
            (_State.ANIMAL_UNCONFIRMED, _Event.RFID_READ):    _Transition(_State.ANIMAL_UNCONFIRMED, noop),
            (_State.ANIMAL_UNCONFIRMED, _Event.TIMEOUT):      _Transition(_State.ANIMAL_UNCONFIRMED, noop),
        }
        # fmt: on

    # ---- Detector protocol: registration ---------------------------------

    def register_event(
        self,
        event: DetectorEvent,
        callback: Callable[[DetectionResult], None],
    ) -> None:
        """Subscribe *callback* to a specific :class:`DetectorEvent`."""
        self._callbacks[event].append(callback)

    # ---- Detector protocol: lifecycle ------------------------------------

    def begin(self) -> None:
        """Start the background detection loop."""
        self._rfid_reader.open()
        self._rfid_reader.begin()
        self._stop_event.clear()
        self._thread = Thread(target=self._worker, daemon=True)
        self._thread.start()

    def quit(self) -> None:
        """Stop the background detection loop and release resources."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        self._rfid_reader.close()
        self._beam_break_sensor.close()

    # ---- Detector protocol: properties -----------------------------------

    @property
    def current_animal(self) -> str | None:
        """Return the ``animal_id`` of the animal currently on the sensor."""
        with self._lock:
            return self._current_animal

    # ---- internal: worker loop -------------------------------------------

    def _worker(self) -> None:
        """Background loop: poll beam sensor, drive state machine."""
        while not self._stop_event.is_set():
            now = time()
            events: list[_Event] = []

            # 1. Edge detection (beam break sensor)
            edge = self._detect_edge()
            if edge is not None:
                events.append(edge)

            # 2. RFID read — the reader has its own background thread;
            #    we just grab the latest result and let the state table
            #    decide whether the event is relevant.
            rfid = self._try_read_rfid(now)
            if rfid is not None:
                events.append(rfid)

            # 3. Timeout check
            timeout = self._check_timeout(now)
            if timeout is not None:
                events.append(timeout)

            # 4. Dispatch all collected events (priority: edge > rfid > timeout)
            with self._lock:
                for evt in events:
                    self._dispatch(evt)

            sleep(self._poll_interval)

    # ---- internal: sensor helpers ----------------------------------------

    def _detect_edge(self) -> _Event | None:
        """Read beam sensor and return a rising / falling edge or *None*."""
        current = self._beam_break_sensor.read()
        edge: _Event | None = None

        if current and not self._prev_beam:
            edge = _Event.RISING_EDGE
        elif not current and self._prev_beam:
            edge = _Event.FALLING_EDGE

        self._prev_beam = current
        return edge

    def _try_read_rfid(self, now: float) -> _Event | None:
        """Read RFID on-demand and return ``RFID_READ`` if a valid tag is available.

        The RFID reader maintains its own background thread; we simply call
        ``read()`` to retrieve the latest result when the state machine needs it.
        """
        tag = self._rfid_reader.read()
        if tag is None:
            return None
        if now - tag.detect_time <= self._rfid_timeout:
            self._last_tag = tag
            return _Event.RFID_READ
        return None

    def _check_timeout(self, now: float) -> _Event | None:
        """Return ``TIMEOUT`` when the RFID window has expired."""
        if self._state == _State.ANIMAL_PRESENT:
            if self._edge_time > 0 and (now - self._edge_time) > self._rfid_timeout:
                return _Event.TIMEOUT
        return None

    # ---- internal: state-machine dispatch --------------------------------

    def _dispatch(self, event: _Event) -> None:
        transition = self._table.get((self._state, event))
        if transition is None:
            return

        transition.action()
        self._state = transition.next_state

    # ---- internal: result helpers ----------------------------------------

    def _make_result(
        self,
        *,
        animal_id: str | None = None,
        error: bool = False,
    ) -> DetectionResult:
        return DetectionResult(
            timestamp=time(),
            animal_id=animal_id,
            error=error,
        )

    def _emit(self, event: DetectorEvent, result: DetectionResult) -> None:
        """Notify all subscribers of *event*."""
        for cb in self._callbacks[event]:
            cb(result)

    # ---- state-machine actions -------------------------------------------

    def _noop(self) -> None:
        """No side-effect transition."""

    def _on_rising_edge(self) -> None:
        """Beam broken — start RFID acquisition window."""
        self._edge_time = time()

    def _on_entered_confirmed(self) -> None:
        """RFID read while beam is broken — identified animal entered."""
        if self._last_tag is None:
            return
        animal_id = self._last_tag.animal_id
        self._current_animal = animal_id
        self._emit(
            DetectorEvent.ANIMAL_ENTERED,
            self._make_result(animal_id=animal_id),
        )

    def _on_entered_unknown(self) -> None:
        """RFID window expired — unknown animal entered."""
        self._current_animal = None
        self._emit(
            DetectorEvent.UNKNOWN_ANIMAL_ENTERED,
            self._make_result(error=True),
        )

    def _on_left_confirmed(self) -> None:
        """Beam restored after RFID confirmation — animal left."""
        animal_id = self._last_tag.animal_id if self._last_tag else self._current_animal
        self._emit(
            DetectorEvent.ANIMAL_LEFT,
            self._make_result(animal_id=animal_id),
        )
        self._current_animal = None
        self._last_tag = None
        self._edge_time = 0.0

    def _on_left_unconfirmed(self) -> None:
        """Beam restored before RFID arrived — animal left without ID."""
        self._emit(
            DetectorEvent.ANIMAL_LEFT,
            self._make_result(),
        )
        self._current_animal = None
        self._last_tag = None
        self._edge_time = 0.0
