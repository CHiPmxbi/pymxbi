"""RFID-only continuous detector.

Turns raw RFID tag reads into detector events using a table-driven state
machine, matching the pattern used by :class:`FusionContinuousDetector` and
:class:`MockDetector`.
"""

from __future__ import annotations

from enum import Enum, auto
from threading import Event, Lock, Thread
from time import sleep, time
from typing import Callable, NamedTuple

from ..peripheral.rfid import RFIDReader, RFIDTag
from .detector import DetectionResult, DetectorEvent


# ---------------------------------------------------------------------------
# State-machine enums
# ---------------------------------------------------------------------------


class _State(Enum):
    """Internal presence states for the RFID detector."""

    IDLE = auto()  # No animal detected
    PRESENT = auto()  # Animal detected via RFID


class _Event(Enum):
    """Events that drive the RFID state machine."""

    TAG_READ = auto()  # Valid RFID tag received
    NO_TAG = auto()  # No valid tag this poll cycle
    FAULT = auto()  # Reader reported an error


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
_MAX_TAG_AGE_S: float = 1.0


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class RFIDContinuousDetector:
    """Detect animals using only an RFID reader.

    Implements the :class:`Detector` protocol.

    Detection logic
    ---------------
    * **Tag read**: when a valid (non-stale, non-duplicate) tag is received,
      emit ``ANIMAL_ENTERED``.  If a *different* animal is read while one is
      already present, emit ``ANIMAL_LEFT`` for the previous animal followed
      by ``ANIMAL_ENTERED`` for the new one.
    * **No tag**: when a poll cycle yields no valid tag while an animal is
      present, emit ``ANIMAL_LEFT``.
    * **Fault**: when ``rfid_reader.errno`` becomes non-empty, emit
      ``FAULT_DETECTED``.

    Parameters
    ----------
    rfid_reader : RFIDReader
        RFID reader that produces tag results.
    poll_interval : float
        Seconds between polls of ``rfid_reader.read()``.
    max_tag_age_seconds : float
        Ignore tag reads older than this many seconds.
    """

    # ---- construction ----------------------------------------------------

    def __init__(
        self,
        rfid_reader: RFIDReader,
        poll_interval: float = _POLL_INTERVAL_S,
        max_tag_age_seconds: float = _MAX_TAG_AGE_S,
    ) -> None:
        self._rfid_reader = rfid_reader
        self._poll_interval = poll_interval
        self._max_tag_age_seconds = max_tag_age_seconds

        # Event callbacks: DetectorEvent -> list of subscribers
        self._callbacks: dict[
            DetectorEvent, list[Callable[[DetectionResult], None]]
        ] = {evt: [] for evt in DetectorEvent}

        # State-machine bookkeeping
        self._state: _State = _State.IDLE
        self._current_animal: str | None = None
        self._last_handled_key: tuple[float, str] | None = None
        self._last_errno: str = ""

        # Thread control
        self._lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None

        # Pending tag for actions to consume
        self._pending_tag: RFIDTag | None = None

        # fmt: off
        # ---- transition table ------------------------------------------------
        noop = self._noop
        self._table: dict[tuple[_State, _Event], _Transition] = {
            # -- IDLE ----------------------------------------------------------
            (_State.IDLE, _Event.TAG_READ): _Transition(_State.PRESENT, self._on_animal_entered),
            (_State.IDLE, _Event.NO_TAG):   _Transition(_State.IDLE, noop),
            (_State.IDLE, _Event.FAULT):    _Transition(_State.IDLE, self._on_fault),
            # -- PRESENT -------------------------------------------------------
            (_State.PRESENT, _Event.TAG_READ): _Transition(_State.PRESENT, self._on_tag_while_present),
            (_State.PRESENT, _Event.NO_TAG):   _Transition(_State.IDLE, self._on_animal_left),
            (_State.PRESENT, _Event.FAULT):    _Transition(_State.IDLE, self._on_fault),
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
        self._last_handled_key = None
        self._last_errno = ""

        self._rfid_reader.open()
        try:
            self._rfid_reader.begin()
        except RuntimeError:
            pass

        self._thread = Thread(
            target=self._worker,
            name="RFIDDetectorWorker",
            daemon=True,
        )
        self._thread.start()

    def quit(self) -> None:
        """Stop the background detection loop and release resources."""
        self._stop_event.set()
        self._rfid_reader.close()
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
        """Background loop: poll RFID reader, drive state machine."""
        while not self._stop_event.is_set():
            now = time()
            events: list[_Event] = []

            # 1. Fault detection
            fault = self._check_fault()
            if fault is not None:
                events.append(fault)

            # 2. RFID tag read (produces TAG_READ or NO_TAG)
            events.append(self._poll_tag(now))

            # 3. Dispatch all collected events (priority: fault > tag)
            with self._lock:
                for evt in events:
                    self._dispatch(evt)

            sleep(self._poll_interval)

    # ---- internal: sensor helpers ----------------------------------------

    def _check_fault(self) -> _Event | None:
        """Check for reader errors and return ``FAULT`` on new errors."""
        errno = self._rfid_reader.errno
        if errno and errno != self._last_errno:
            self._last_errno = errno
            return _Event.FAULT
        if not errno and self._last_errno:
            self._last_errno = ""
        return None

    def _poll_tag(self, now: float) -> _Event:
        """Poll the RFID reader; always returns ``TAG_READ`` or ``NO_TAG``."""
        tag = self._rfid_reader.read()
        if tag is None:
            return _Event.NO_TAG

        if now - tag.detect_time > self._max_tag_age_seconds:
            return _Event.NO_TAG

        key = (tag.detect_time, tag.animal_id)
        if key == self._last_handled_key:
            return _Event.NO_TAG
        self._last_handled_key = key

        self._pending_tag = tag
        return _Event.TAG_READ

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
        """First tag read from IDLE — animal arrived."""
        tag = self._pending_tag
        if tag is None:
            return
        self._current_animal = tag.animal_id
        self._emit(
            DetectorEvent.ANIMAL_ENTERED,
            self._make_result(animal_id=tag.animal_id),
        )
        self._pending_tag = None

    def _on_tag_while_present(self) -> None:
        """Tag read while an animal is already present.

        If the same animal, no-op.  If a different animal, emit
        ``ANIMAL_LEFT`` for the old one and ``ANIMAL_ENTERED`` for the new one.
        """
        tag = self._pending_tag
        if tag is None:
            return

        if tag.animal_id != self._current_animal:
            self._emit(
                DetectorEvent.ANIMAL_LEFT,
                self._make_result(animal_id=self._current_animal),
            )
            self._current_animal = tag.animal_id
            self._emit(
                DetectorEvent.ANIMAL_ENTERED,
                self._make_result(animal_id=tag.animal_id),
            )

        self._pending_tag = None

    def _on_animal_left(self) -> None:
        """No tag this cycle — animal left."""
        animal_id = self._current_animal
        self._current_animal = None
        self._last_handled_key = None
        self._emit(
            DetectorEvent.ANIMAL_LEFT,
            self._make_result(animal_id=animal_id),
        )

    def _on_fault(self) -> None:
        """Reader error detected."""
        self._emit(
            DetectorEvent.FAULT_DETECTED,
            self._make_result(error=True),
        )
