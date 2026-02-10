"""Raspberry Pi IR through-beam sensor implementation — polling mode."""

import time
from threading import Thread, Lock, Event

from gpiozero import InputDevice


class RPIIRBreakBeamSensor:
    """Read an IR break-beam sensor via polling.

    Parameters
    ----------
    pin : int
        GPIO pin connected to the sensor output.
    normally_open : bool
        ``True`` for normally-open sensor, ``False`` for normally-closed.
    debounce_time : float
        Debounce window in seconds (default 0.05).
    poll_interval : float
        How often to sample the pin in seconds (default 0.01).
    """

    def __init__(
        self,
        pin: int,
        normally_open: bool = True,
        debounce_time: float = 0.05,
        poll_interval: float = 0.01,
    ) -> None:
        self._normally_open = normally_open
        self._debounce_time = debounce_time
        self._poll_interval = poll_interval
        self._lock = Lock()
        self._stop_event = Event()

        try:
            self._device = InputDevice(pin, pull_up=False)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to initialize IR break beam sensor on pin {pin}: {exc}"
            ) from exc

        self._last_stable: bool = self._sample()
        self._pending: bool = self._last_stable
        self._pending_since: float = time.monotonic()

        self._poll_thread = Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def read(self) -> bool:
        """Return the debounced beam state.

        Returns
        -------
        bool
            ``True`` when the beam is broken, ``False`` when intact.
        """
        with self._lock:
            return self._last_stable

    def close(self) -> None:
        """Stop polling and release GPIO resources."""
        self._stop_event.set()
        self._poll_thread.join(timeout=1.0)
        self._device.close()

    # -- internals ------------------------------------------------------------

    def _sample(self) -> bool:
        raw = bool(self._device.value)
        return not raw if self._normally_open else raw

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            current = self._sample()
            now = time.monotonic()

            with self._lock:
                if current != self._pending:
                    self._pending = current
                    self._pending_since = now
                elif (
                    current != self._last_stable
                    and (now - self._pending_since) >= self._debounce_time
                ):
                    self._last_stable = current

            self._stop_event.wait(self._poll_interval)
