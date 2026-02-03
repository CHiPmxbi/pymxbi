"""Raspberry Pi IR through-beam sensor implementation."""

from typing import Callable

from gpiozero import DigitalInputDevice


class RPIIRBreakBeamSensor:
    """Read an IR break-beam sensor via a Raspberry Pi GPIO input.

    Parameters
    ----------
    pin : int
        GPIO pin connected to the sensor output.
    """

    def __init__(self, pin: int) -> None:
        """Initialize the sensor.

        Parameters
        ----------
        pin : int
            GPIO pin connected to the sensor output.

        Raises
        ------
        RuntimeError
            If the GPIO pin cannot be initialized.
        """
        self._pin = pin
        try:
            self._sensor = DigitalInputDevice(pin, pull_up=True, active_state=False)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to initialize IR break beam sensor on pin {pin}: {exc}"
            )

    def read(self) -> bool:
        """Read the sensor state.

        Returns
        -------
        bool
            ``True`` when the beam is broken, otherwise ``False``.
        """
        if self._sensor.value == 0:
            return True  # Beam is broken
        else:
            return False  # Beam is intact

    def close(self) -> None:
        """Release GPIO resources."""
        self._sensor.close()

    def on_beam_broken(self, callback: Callable[[], None]) -> None:
        """Register a callback invoked when the beam transitions to broken.

        Parameters
        ----------
        callback : Callable[[], None]
            Function called when the sensor is activated.
        """
        self._sensor.when_activated = callback
