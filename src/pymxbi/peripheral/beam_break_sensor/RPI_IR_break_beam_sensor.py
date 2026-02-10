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
        If ``True`` (default), the sensor is normally-open: HIGH means beam
        broken.  If ``False``, the logic is inverted (HIGH means beam intact).
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
        self._normally_open = normally_open
        self._debounce_time = debounce_time
        self._lock = Lock()
        self._debounce_timer: Optional[Timer] = None

        try:
            self._sensor = DigitalInputDevice(pin)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to initialize IR break beam sensor on pin {pin}: {exc}"
            ) from exc

        self._last_stable_state: bool = self._sample()

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
            return self._sample()
        with self._lock:
            return self._last_stable_state

    def close(self) -> None:
        """Release GPIO resources."""
        with self._lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
        self._sensor.close()

    # -- internals ------------------------------------------------------------

    def _sample(self) -> bool:
        """Read raw pin and apply NO/NC logic."""
        raw = bool(self._sensor.value)
        return raw if self._normally_open else not raw

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
            self._last_stable_state = self._sample()