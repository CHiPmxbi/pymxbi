"""Mock detector implementation for testing and development."""

from __future__ import annotations

from enum import Enum, auto
from threading import Event, Lock, Thread
from time import sleep, time
from typing import Callable, NamedTuple

from .detector import DetectionResult, DetectorEvent


# ---------------------------------------------------------------------------
# State-machine enums
# ---------------------------------------------------------------------------


class _State(Enum):
    """Internal presence states for the mock state machine."""

    IDLE = auto()
    PRESENT = auto()


class _Event(Enum):
    """Events that drive the mock state machine."""

    ARRIVED = auto()   # No animal → animal present
    DEPARTED = auto()  # Animal present → no animal


# ---------------------------------------------------------------------------
# Transition-table type
# ---------------------------------------------------------------------------

_Action = Callable[[], None]


class _Transition(NamedTuple):
    next_state: _State
    action: _Action


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class MockDetector:
    """Detector stub that performs no I/O.

    Implements the :class:`Detector` protocol.

    This class lets you drive the detector state machine manually to produce
    events such as animal entered/left and unknown animal entered.
    """

    def __init__(
        self,
        detection_frequency_ms: int = 200,
    ) -> None:
        """Create a mock detector.

        Parameters
        ----------
        detection_frequency_ms : int, default=200
            Polling interval in milliseconds for checking state changes.
        """
        self._current_animal_id: str | None = None
        self._prev_animal_id: str | None = None

        self._detection_frequency = detection_frequency_ms / 1000.0

        # Event callbacks: DetectorEvent -> list of subscribers
        self._callbacks: dict[
            DetectorEvent, list[Callable[[DetectionResult], None]]
        ] = {evt: [] for evt in DetectorEvent}

        # State-machine bookkeeping
        self._state: _State = _State.IDLE

        # Thread control
        self._lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None

        # fmt: off
        # ---- transition table ------------------------------------------------
        noop = self._noop
        self._table: dict[tuple[_State, _Event], _Transition] = {
            # -- IDLE ----------------------------------------------------------
            (_State.IDLE, _Event.ARRIVED):  _Transition(_State.PRESENT, self._on_animal_entered),
            (_State.IDLE, _Event.DEPARTED): _Transition(_State.IDLE, noop),
            # -- PRESENT -------------------------------------------------------
            (_State.PRESENT, _Event.ARRIVED):  _Transition(_State.PRESENT, noop),
            (_State.PRESENT, _Event.DEPARTED): _Transition(_State.IDLE, self._on_animal_left),
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
        self._stop_event.clear()
        self._thread = Thread(target=self._worker, daemon=True)
        self._thread.start()

    def quit(self) -> None:
        """Stop the background detection loop and release resources."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None

    # ---- Detector protocol: properties -----------------------------------

    @property
    def current_animal(self) -> str | None:
        """Return the ``animal_id`` of the animal currently on the sensor."""
        with self._lock:
            return self._current_animal_id

    # ---- Mock-specific API -----------------------------------------------

    def animal_present(self, animal_id: str | None = None) -> None:
        """Set the simulated state to "an animal is present".

        Parameters
        ----------
        animal_id : str | None, default=None
            ID of the animal. If None, simulates an unknown animal.
        """
        with self._lock:
            self._current_animal_id = animal_id

    def animal_left(self) -> None:
        """Set the simulated state to "no animal is present"."""
        with self._lock:
            self._current_animal_id = None

    def unknown_animal_entered(self) -> None:
        """Emit an :attr:`DetectorEvent.UNKNOWN_ANIMAL_ENTERED` event."""
        with self._lock:
            self._emit(
                DetectorEvent.UNKNOWN_ANIMAL_ENTERED,
                self._make_result(animal_id=None),
            )

    def fault_detected(self) -> None:
        """Emit a :attr:`DetectorEvent.FAULT_DETECTED` event."""
        with self._lock:
            self._emit(
                DetectorEvent.FAULT_DETECTED,
                self._make_result(error=True),
            )

    # ---- internal: worker loop -------------------------------------------

    def _worker(self) -> None:
        """Background loop: poll current state and emit events on changes."""
        while not self._stop_event.is_set():
            with self._lock:
                current = self._current_animal_id
                prev = self._prev_animal_id

            if current != prev:
                event = self._classify_change(prev, current)
                if event is not None:
                    with self._lock:
                        self._dispatch(event)
                with self._lock:
                    self._prev_animal_id = current

            sleep(self._detection_frequency)

    # ---- internal: sensor helpers ----------------------------------------

    @staticmethod
    def _classify_change(
        prev: str | None, current: str | None
    ) -> _Event | None:
        """Derive an internal event from a change in animal ID."""
        if prev is None and current is not None:
            return _Event.ARRIVED
        if prev is not None and current is None:
            return _Event.DEPARTED
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
        """Create a :class:`DetectionResult` with current timestamp."""
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
        """Animal arrived on the sensor."""
        self._emit(
            DetectorEvent.ANIMAL_ENTERED,
            self._make_result(animal_id=self._current_animal_id),
        )

    def _on_animal_left(self) -> None:
        """Animal left the sensor."""
        self._emit(
            DetectorEvent.ANIMAL_LEFT,
            self._make_result(animal_id=self._prev_animal_id),
        )
