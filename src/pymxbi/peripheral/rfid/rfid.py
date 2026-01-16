"""RFID reader interfaces."""

from typing import Protocol


class RFIDTag(Protocol):
    """Protocol for RFID tag read results."""

    detect_time: float
    animal_id: str


class RFIDReader(Protocol):
    """Protocol for RFID reader peripherals."""

    @property
    def errno(self) -> str:
        """Return the latest reader/parser error message (or empty string)."""
        ...

    def read(self) -> RFIDTag | None:
        """Return the most recently read tag (if any)."""
        ...

    def open(self) -> None:
        """Open the reader (for example, a serial port)."""
        ...

    def begin(self) -> None:
        """Start the reader background loop (if applicable)."""
        ...

    def close(self) -> None:
        """Close the reader and release resources."""
        ...

