"""Interfaces for through-beam sensors."""

from typing import Protocol


class BeamBreakSensor(Protocol):
    """Protocol for sensors that detect a broken through-beam."""

    def read(self) -> bool:
        """Read the sensor state.

        Returns
        -------
        bool
            ``True`` when the beam is broken, otherwise ``False``.
        """
        ...

    def close(self) -> None:
        """Release any resources held by the sensor."""
        ...
