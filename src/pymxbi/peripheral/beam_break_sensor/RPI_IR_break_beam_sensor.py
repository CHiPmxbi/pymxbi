"""Raspberry Pi IR through-beam sensor implementation."""

from threading import Timer, Lock
from typing import Optional

from gpiozero import DigitalInputDevice


class RPIIRBreakBeamSensor:
    """Read an IR break-beam sensor via a Raspberry Pi GPIO input.

    Parameters
    ----------
    pin : int
        GPIO pin connected to the sensor output.
    normally_open : bool
        If ``True`` (default), the sensor is normally-open: output LOW when
        the beam is intact, HIGH when broken.  If ``False``, the sensor is
        normally-closed (inverted logic).
    debounce_time : float
        Software debounce window in seconds.  Default is 0.05 s (50 ms).
        Set to 0 to disable.
    """

    def __init__(
        self,
        pin: int,
        normally_open: bool = True,
        debounce_time: float = 0.05,
    ) -> None:
        self._pin = pin
        self._debounce_time = debounce_time
        self._lock = Lock()
        self._debounce_timer: Optional[Timer] = None

        pull_up = normally_open
        active_state = not normally_open

        try:
            self._sensor = DigitalInputDevice(
                pin, pull_up=pull_up, active_state=active_state,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to initialize IR break beam sensor on pin {pin}: {exc}"
            ) from exc

        self._last_stable_state: bool = bool(self._sensor.value)

        if self._debounce_time > 0:
            self._sensor.when_activated = self._on_raw_edge
            self._sensor.when_deactivated = self._on_raw_edge

    def read(self) -> bool:
        """Read the debounced sensor state.

        Returns
        -------
        bool
            ``True`` when the beam is broken, otherwise ``False``.
        """
        if self._debounce_time <= 0:
            return bool(self._sensor.value)
        with self._lock:
            return self._last_stable_state

    def close(self) -> None:
        """Release GPIO resources."""
        with self._lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
        self._sensor.close()

    # -- internals ------------------------------------------------------------

    def _on_raw_edge(self) -> None:
        with self._lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
            self._debounce_timer = Timer(
                self._debounce_time, self._on_debounce_expired,
            )
            self._debounce_timer.daemon = True
            self._debounce_timer.start()

    def _on_debounce_expired(self) -> None:
        with self._lock:
            self._last_stable_state = bool(self._sensor.value)