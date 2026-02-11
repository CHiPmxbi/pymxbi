"""Beam-break-only continuous detector.

Uses a through-beam sensor to detect animal presence via edge detection,
driven by a table-driven state machine matching the pattern used by
:class:`FusionContinuousDetector` and :class:`MockDetector`.
"""

from __future__ import annotations

from enum import Enum, auto
from threading import Event, Lock, Thread
from time import sleep, time
from typing import Callable, NamedTuple

from ..peripheral.beam_break_sensor.beam_break_sensor import BeamBreakSensor
from .detector import DetectionResult, DetectorEvent


# ---------------------------------------------------------------------------
# State-machine enums
# ---------------------------------------------------------------------------


class _State(Enum):
    """Internal presence states for the beam-break detector."""

    IDLE = auto()  # Beam clear, no animal
    PRESENT = auto()  # Beam broken, animal present


class _Event(Enum):
    """Events that drive the beam-break state machine."""

    RISING_EDGE = auto()  # Beam just broken  (animal enters)
    FALLING_EDGE = auto()  # Beam just restored (animal leaves)


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

_POLL_INTERVAL_S: float = 1.0


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class BeambreakContinuousDetector:
    """Detect animals using only a through-beam sensor.

    Implements the :class:`Detector` protocol.

    Detection logic
    ---------------
    * **Rising edge** (beam broken — animal arrives): emit
      ``ANIMAL_ENTERED`` with the pre-configured ``animal_id``.
    * **Falling edge** (beam restored — animal leaves): emit
      ``ANIMAL_LEFT``.

    Because the beam-break sensor cannot identify animals, a fixed
    ``animal_id`` is supplied at construction time.

    Parameters
    ----------
    beam_break_sensor : BeamBreakSensor
        The through-beam sensor to poll.
    animal_id : str
        Identity to assign to any detected animal.
    poll_interval : float
        Seconds between polls of the sensor.
    """

    # ---- construction ----------------------------------------------------

    def __init__(
        self,
        beam_break_sensor: BeamBreakSensor,
        animal_id: str = "unknown",
        poll_interval: float = _POLL_INTERVAL_S,
    ) -> None:
        self._beam_break_sensor = beam_break_sensor
        self._animal_id = animal_id
        self._poll_interval = poll_interval

        # Event callbacks: DetectorEvent -> list of subscribers
        self._callbacks: dict[
            DetectorEvent, list[Callable[[DetectionResult], None]]
        ] = {evt: [] for evt in DetectorEvent}

        # State-machine bookkeeping
        self._state: _State = _State.IDLE
        self._prev_beam: bool = False
        self._current_animal: str | None = None

        # Thread control
        self._lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None

        # fmt: off
        # ---- transition table ------------------------------------------------
        noop = self._noop
        self._table: dict[tuple[_State, _Event], _Transition] = {
            # -- IDLE ----------------------------------------------------------
            (_State.IDLE, _Event.RISING_EDGE):  _Transition(_State.PRESENT, self._on_animal_entered),
            (_State.IDLE, _Event.FALLING_EDGE): _Transition(_State.IDLE, noop),
            # -- PRESENT -------------------------------------------------------
            (_State.PRESENT, _Event.RISING_EDGE):  _Transition(_State.PRESENT, noop),
            (_State.PRESENT, _Event.FALLING_EDGE): _Transition(_State.IDLE, self._on_animal_left),
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
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = Thread(
            target=self._worker,
            name="BeambreakDetectorWorker",
            daemon=True,
        )
        self._thread.start()

    def quit(self) -> None:
        """Stop the background detection loop and release resources."""
        self._stop_event.set()
        try:
            self._beam_break_sensor.close()
        finally:
            if self._thread is not None:
                self._thread.join(timeout=1.0)
                self._thread = None

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
            edge = self._detect_edge()
            if edge is not None:
                with self._lock:
                    self._dispatch(edge)

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

    def _on_animal_entered(self) -> None:
        """Beam broken — animal arrived."""
        self._current_animal = self._animal_id
        self._emit(
            DetectorEvent.ANIMAL_ENTERED,
            self._make_result(animal_id=self._animal_id),
        )

    def _on_animal_left(self) -> None:
        """Beam restored — animal left."""
        animal_id = self._current_animal
        self._current_animal = None
        self._emit(
            DetectorEvent.ANIMAL_LEFT,
            self._make_result(animal_id=animal_id),
        )
