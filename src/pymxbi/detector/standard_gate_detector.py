"""Standard dual-beam gate detector with RFID.

Uses two through-beam sensors to determine traversal direction and an RFID
reader to identify the animal, driven by a table-driven state machine.
"""

from __future__ import annotations

from enum import Enum, auto
from threading import Event, Lock, Thread
from time import sleep, time
from typing import Callable, NamedTuple

from ..peripheral.beam_break_sensor import BeamBreakSensor
from ..peripheral.rfid import RFIDReader, RFIDTag
from .detector import DetectionResult, DetectorEvent


# ---------------------------------------------------------------------------
# State-machine enums
# ---------------------------------------------------------------------------


class _State(Enum):
    """Internal states of the gate detector.

    The animal crosses two beams (b1, b2) in sequence.  The direction is
    determined by which beam breaks first:

    * **Enter**: b1 breaks → b2 breaks → b1 clears → b2 clears
    * **Leave**: b2 breaks → b1 breaks → b2 clears → b1 clears
    """

    IDLE = auto()

    ENTER_1 = auto()  # b1 broken, waiting for b2
    ENTER_2 = auto()  # b1+b2 broken, waiting for b1 clear
    ENTER_3 = auto()  # b2 broken, b1 clear, waiting for b2 clear

    LEAVE_1 = auto()  # b2 broken, waiting for b1
    LEAVE_2 = auto()  # b1+b2 broken, waiting for b2 clear
    LEAVE_3 = auto()  # b1 broken, b2 clear, waiting for b1 clear


class _Event(Enum):
    """Edge events from the two beam sensors."""

    B1_RISING = auto()  # Beam 1 just broken
    B1_FALLING = auto()  # Beam 1 just restored
    B2_RISING = auto()  # Beam 2 just broken
    B2_FALLING = auto()  # Beam 2 just restored


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

_POLL_INTERVAL_S: float = 0.01


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class StandardGateDetector:
    """Dual-beam gate detector with RFID identification.

    Implements the :class:`Detector` protocol.

    Detection logic
    ---------------
    * Two beams (b1, b2) are monitored for rising/falling edges.
    * The beam that breaks first determines direction: b1 first → *enter*,
      b2 first → *leave*.
    * While the crossing sequence is in progress, RFID tags are collected.
    * When the sequence completes, ``ANIMAL_ENTERED`` or ``ANIMAL_LEFT``
      is emitted for each collected tag.  If no tags were collected,
      ``UNKNOWN_ANIMAL_ENTERED`` is emitted instead.

    Parameters
    ----------
    rfid_reader : RFIDReader
        RFID reader for animal identification.
    b1 : BeamBreakSensor
        First beam sensor (entry side).
    b2 : BeamBreakSensor
        Second beam sensor (exit side).
    poll_interval : float
        Seconds between sensor polls.
    """

    # ---- construction ----------------------------------------------------

    def __init__(
        self,
        rfid_reader: RFIDReader,
        b1: BeamBreakSensor,
        b2: BeamBreakSensor,
        poll_interval: float = _POLL_INTERVAL_S,
    ) -> None:
        self._rfid_reader = rfid_reader
        self._b1 = b1
        self._b2 = b2
        self._poll_interval = poll_interval

        # Event callbacks: DetectorEvent -> list of subscribers
        self._callbacks: dict[
            DetectorEvent, list[Callable[[DetectionResult], None]]
        ] = {evt: [] for evt in DetectorEvent}

        # State-machine bookkeeping
        self._state: _State = _State.IDLE
        self._prev_b1: bool = False
        self._prev_b2: bool = False
        self._current_animal: str | None = None

        # RFID tags collected during the current crossing sequence
        self._sequence_start: float = 0.0
        self._collected_tags: dict[str, RFIDTag] = {}

        # Thread control
        self._lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None

        # fmt: off
        # ---- transition table ------------------------------------------------
        noop = self._noop
        S = _State
        E = _Event
        T = _Transition
        self._table: dict[tuple[_State, _Event], _Transition] = {
            # -- IDLE ----------------------------------------------------------
            (S.IDLE, E.B1_RISING):  T(S.ENTER_1, self._on_start),
            (S.IDLE, E.B1_FALLING): T(S.IDLE, noop),
            (S.IDLE, E.B2_RISING):  T(S.LEAVE_1, self._on_start),
            (S.IDLE, E.B2_FALLING): T(S.IDLE, noop),
            # -- ENTER_1 (b1 broken, waiting for b2) ---------------------------
            (S.ENTER_1, E.B1_RISING):  T(S.ENTER_1, noop),
            (S.ENTER_1, E.B1_FALLING): T(S.IDLE, self._on_cancel),
            (S.ENTER_1, E.B2_RISING):  T(S.ENTER_2, noop),
            (S.ENTER_1, E.B2_FALLING): T(S.ENTER_1, noop),
            # -- ENTER_2 (b1+b2 broken, waiting for b1 clear) -----------------
            (S.ENTER_2, E.B1_RISING):  T(S.ENTER_2, noop),
            (S.ENTER_2, E.B1_FALLING): T(S.ENTER_3, noop),
            (S.ENTER_2, E.B2_RISING):  T(S.ENTER_2, noop),
            (S.ENTER_2, E.B2_FALLING): T(S.ENTER_1, noop),
            # -- ENTER_3 (b2 broken, b1 clear, waiting for b2 clear) ----------
            (S.ENTER_3, E.B1_RISING):  T(S.ENTER_2, noop),
            (S.ENTER_3, E.B1_FALLING): T(S.ENTER_3, noop),
            (S.ENTER_3, E.B2_RISING):  T(S.ENTER_3, noop),
            (S.ENTER_3, E.B2_FALLING): T(S.IDLE, self._on_entered),
            # -- LEAVE_1 (b2 broken, waiting for b1) ---------------------------
            (S.LEAVE_1, E.B1_RISING):  T(S.LEAVE_2, noop),
            (S.LEAVE_1, E.B1_FALLING): T(S.LEAVE_1, noop),
            (S.LEAVE_1, E.B2_RISING):  T(S.LEAVE_1, noop),
            (S.LEAVE_1, E.B2_FALLING): T(S.IDLE, self._on_cancel),
            # -- LEAVE_2 (b1+b2 broken, waiting for b2 clear) -----------------
            (S.LEAVE_2, E.B1_RISING):  T(S.LEAVE_2, noop),
            (S.LEAVE_2, E.B1_FALLING): T(S.LEAVE_1, noop),
            (S.LEAVE_2, E.B2_RISING):  T(S.LEAVE_2, noop),
            (S.LEAVE_2, E.B2_FALLING): T(S.LEAVE_3, noop),
            # -- LEAVE_3 (b1 broken, b2 clear, waiting for b1 clear) ----------
            (S.LEAVE_3, E.B1_RISING):  T(S.LEAVE_3, noop),
            (S.LEAVE_3, E.B1_FALLING): T(S.IDLE, self._on_left),
            (S.LEAVE_3, E.B2_RISING):  T(S.LEAVE_2, noop),
            (S.LEAVE_3, E.B2_FALLING): T(S.LEAVE_3, noop),
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

        self._rfid_reader.open()
        self._rfid_reader.begin()

        self._stop_event.clear()
        self._thread = Thread(
            target=self._worker,
            name="GateDetectorWorker",
            daemon=True,
        )
        self._thread.start()

    def quit(self) -> None:
        """Stop the background detection loop and release resources."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        self._rfid_reader.close()
        self._b1.close()
        self._b2.close()

    # ---- Detector protocol: properties -----------------------------------

    @property
    def current_animal(self) -> str | None:
        """Return the ``animal_id`` of the animal currently on the sensor."""
        with self._lock:
            return self._current_animal

    # ---- internal: worker loop -------------------------------------------

    def _worker(self) -> None:
        """Background loop: poll beam sensors and RFID, drive state machine."""
        while not self._stop_event.is_set():
            events: list[_Event] = []

            # 1. Edge detection for both beams
            edges = self._detect_edges()
            events.extend(edges)

            # 2. Collect RFID tags while a crossing sequence is active
            if self._state != _State.IDLE:
                self._collect_rfid()

            # 3. Dispatch all collected events
            with self._lock:
                for evt in events:
                    self._dispatch(evt)

            sleep(self._poll_interval)

    # ---- internal: sensor helpers ----------------------------------------

    def _detect_edges(self) -> list[_Event]:
        """Read both beam sensors and return edge events."""
        b1 = self._b1.read()
        b2 = self._b2.read()
        edges: list[_Event] = []

        if b1 and not self._prev_b1:
            edges.append(_Event.B1_RISING)
        elif not b1 and self._prev_b1:
            edges.append(_Event.B1_FALLING)

        if b2 and not self._prev_b2:
            edges.append(_Event.B2_RISING)
        elif not b2 and self._prev_b2:
            edges.append(_Event.B2_FALLING)

        self._prev_b1 = b1
        self._prev_b2 = b2
        return edges

    def _collect_rfid(self) -> None:
        """Grab the latest RFID tag and stash it if it's fresh."""
        tag = self._rfid_reader.read()
        if tag is None:
            return
        if tag.animal_id is None:
            return
        if tag.detect_time > self._sequence_start:
            self._collected_tags[tag.animal_id] = tag

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

    def _reset_sequence(self) -> None:
        """Clear crossing-sequence bookkeeping."""
        self._sequence_start = 0.0
        self._collected_tags.clear()

    # ---- state-machine actions -------------------------------------------

    def _noop(self) -> None:
        """No side-effect transition."""

    def _on_start(self) -> None:
        """First beam broken — begin a crossing sequence."""
        self._sequence_start = time()
        self._collected_tags.clear()

    def _on_cancel(self) -> None:
        """Sequence aborted (beam restored before completion)."""
        self._reset_sequence()

    def _on_entered(self) -> None:
        """Full enter sequence completed — animal entered."""
        self._finish(DetectorEvent.ANIMAL_ENTERED)

    def _on_left(self) -> None:
        """Full leave sequence completed — animal left."""
        self._finish(DetectorEvent.ANIMAL_LEFT)

    def _finish(self, event: DetectorEvent) -> None:
        """Emit results for a completed crossing sequence."""
        if self._collected_tags:
            for animal_id in self._collected_tags:
                self._emit(event, self._make_result(animal_id=animal_id))
                if event == DetectorEvent.ANIMAL_ENTERED:
                    self._current_animal = animal_id
                else:
                    self._current_animal = None
        else:
            self._emit(
                DetectorEvent.UNKNOWN_ANIMAL_ENTERED,
                self._make_result(error=True),
            )

        self._reset_sequence()
