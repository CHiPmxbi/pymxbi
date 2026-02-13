"""RFID reader implementation for Dorset LID665v42 devices."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum, auto
from threading import Lock, Thread

from serial import EIGHTBITS, PARITY_NONE, STOPBITS_ONE, Serial, SerialException


class ProtocolState(StrEnum):
    """Internal parser states for the Dorset frame protocol."""

    WAIT_FOR_START = auto()
    IN_FRAME = auto()
    AFTER_ESCAPE = auto()
    AWAIT_TRAILER = auto()


# Control bytes used by the Dorset serial protocol.
START = b"\x02"
STOP = b"\x03"
DLE = b"\x10"


@dataclass
class Frame:
    """Parsed raw frame segments (escaped payload already removed)."""

    header: bytes = field(default_factory=lambda: DLE + START)
    payload: bytes = b""
    footer: bytes = field(default_factory=lambda: DLE + STOP)
    checksum: bytes = b"\x00"


@dataclass
class FrameData:
    """Decoded payload fields within a Dorset frame."""

    host: bytes
    unit: bytes
    command: bytes
    data: bytes


@dataclass
class Result:
    """High-level output produced by the reader.

    Attributes
    ----------
    detect_time : float
        UNIX timestamp when the frame start marker was received.
    animal_id : str
        Extracted animal identifier (format depends on device config).
    """

    detect_time: float
    animal_id: str


class _LID665v42FrameParser:
    """State machine that understands the Dorset LID665v42 frame structure."""

    def __init__(self) -> None:
        self._state = ProtocolState.WAIT_FOR_START
        self._frame_buffer = bytearray()
        self._frame_started_at = 0.0
        self._last_error: str = ""

    def reset(self) -> None:
        self._state = ProtocolState.WAIT_FOR_START
        self._frame_buffer.clear()
        self._frame_started_at = 0.0

    @property
    def last_error(self) -> str:
        return self._last_error

    def record_error(self, message: str) -> None:
        """Save an error message for later inspection via `last_error`."""
        self._last_error = message

    def feed(self, byte: bytes) -> Result | None:
        """Consume a single byte and return a parsed `Result` when a frame completes."""
        match self._state:
            case ProtocolState.WAIT_FOR_START:
                self._handle_wait_for_start(byte)
                return None
            case ProtocolState.IN_FRAME:
                self._handle_in_frame(byte)
                return None
            case ProtocolState.AFTER_ESCAPE:
                self._handle_after_escape(byte)
                return None
            case ProtocolState.AWAIT_TRAILER:
                return self._handle_trailer(byte)
            case _:
                self._last_error = f"Unhandled protocol state: {self._state}"
                self.reset()
                return None

    def _handle_wait_for_start(self, byte: bytes) -> None:
        if byte == START:
            self._frame_started_at = datetime.now().timestamp()
            self._frame_buffer.extend(DLE)
            self._frame_buffer.extend(byte)
            self._state = ProtocolState.IN_FRAME
        else:
            self._last_error = f"Expected {START!r} but received {byte!r}"

    def _handle_in_frame(self, byte: bytes) -> None:
        if byte == DLE:
            self._frame_buffer.extend(DLE)
            self._state = ProtocolState.AFTER_ESCAPE
            return

        self._frame_buffer.extend(byte)

    def _handle_after_escape(self, byte: bytes) -> None:
        if byte == STOP:
            self._frame_buffer.extend(byte)
            self._state = ProtocolState.AWAIT_TRAILER
            return

        self._frame_buffer.extend(byte)
        self._state = ProtocolState.IN_FRAME

    def _handle_trailer(self, byte: bytes) -> Result | None:
        self._frame_buffer.extend(byte)
        return self._build_result()

    def _build_result(self) -> Result | None:
        try:
            result = self._parse_frame(
                bytes(self._frame_buffer), self._frame_started_at
            )
            self._last_error = ""
            return result
        except ValueError as e:
            self._last_error = str(e)
            return None
        finally:
            self.reset()

    def _parse_frame(self, data: bytes, started_at: float) -> Result:
        """Validate, unescape, and decode a complete Dorset frame."""
        if len(data) < 6:
            raise ValueError("Received frame shorter than protocol minimum")

        if not data.startswith(DLE + START):
            raise ValueError(f"Frame missing start marker: {data!r}")

        if data[-3:-1] != DLE + STOP:
            raise ValueError(f"Frame missing end marker: {data!r}")

        frame = Frame(
            header=data[:2],
            payload=self._unescape_payload(data[2:-3]),
            footer=data[-3:-1],
            checksum=data[-1:],
        )

        if len(frame.payload) < 3:
            raise ValueError("Frame payload missing host/unit/command fields")

        frame_data = FrameData(
            host=frame.payload[0:1],
            unit=frame.payload[1:2],
            command=frame.payload[2:3],
            data=frame.payload[3:],
        )

        # TODO: Confirm host/unit values and the correct ID extraction offsets.
        # The current implementation derives the ID from the decoded payload bytes:
        # `data.hex()[6:10]` corresponds to bytes 3..4 of `frame_data.data`.
        animal_id = frame_data.data.hex()[6:10]

        return Result(
            detect_time=started_at,
            animal_id=animal_id,
        )

    def _unescape_payload(self, payload: bytes) -> bytes:
        """Remove DLE-based escaping from a Dorset payload.

        The transport duplicates any byte that follows a DLE inside the frame. This
        method treats the first DLE as an escape indicator and keeps only the
        subsequent byte.
        """
        result = bytearray()
        i = 0
        while i < len(payload):
            byte = payload[i]
            if byte == DLE:
                i += 1
                if i >= len(payload):
                    raise ValueError("Dangling DLE escape in Dorset payload")
                result.append(payload[i])
            else:
                result.append(byte)
            i += 1
        return bytes(result)


class DorsetLID665v42:
    """Serial reader for the Dorset `LID665v42` device.

    Call `open()` then `begin()` to start the background read loop. Subscribe to
    parsed results via `read()`.
    """

    def __init__(
        self,
        port: str,
        baudrate: int,
        unit: str = "01",
        host: str = "FE",
    ) -> None:
        """Initialize the reader bound to a serial port.

        Parameters
        ----------
        port : str
            Serial device path (for example, ``/dev/ttyUSB0``).
        baudrate : int
            Serial baud rate (device-dependent).
        unit : str, default="01"
            Unit identifier used by the protocol (currently stored only).
        host : str, default="FE"
            Host identifier used by the protocol (currently stored only).

        Raises
        ------
        SerialException
            If the serial port cannot be configured.
        """
        self._serial = Serial(
            port,
            baudrate,
            parity=PARITY_NONE,
            stopbits=STOPBITS_ONE,
            bytesize=EIGHTBITS,
            timeout=1,
        )
        self._unit = unit
        self._host = host

        self._parser = _LID665v42FrameParser()

        self._reader_thread: Thread | None = None

        self._current_result: Result | None = None
        self._current_result_lock = Lock()

    @property
    def errno(self) -> str:
        """Get the latest parser error message.

        Returns
        -------
        str
            Error message, or an empty string when healthy.
        """
        return self._parser.last_error

    def read(self) -> Result | None:
        """Return the most recently parsed result.

        Returns
        -------
        Result | None
            Latest parsed result, or ``None`` if nothing has been read yet.
        """
        with self._current_result_lock:
            result = self._current_result
            self._current_result = None
            return result

    def begin(self) -> None:
        """Start reading from the serial port on a daemon thread."""
        if self._reader_thread is not None and self._reader_thread.is_alive():
            return
        self._parser.reset()
        self._reader_thread = Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()

    def open(self) -> None:
        """Open the serial port if not already open.

        :raises SerialException: If opening the serial port fails.
        """
        if not self._serial.is_open:
            self._serial.open()

    def close(self) -> None:
        """Close the serial port if it is open."""
        if self._serial.is_open:
            self._serial.close()

    def _read_loop(self) -> None:
        """Continuously read from the serial port and store parsed frames."""
        while self._serial.is_open:
            try:
                byte = self._serial.read(1)
            except (SerialException, OSError, TypeError) as exc:
                # Closing the serial port from another thread can interrupt reads.
                self._parser.record_error(f"Serial read aborted: {exc}")
                self._parser.reset()
                break
            if not byte:
                continue

            frame = self._parser.feed(byte)
            if frame is not None:
                with self._current_result_lock:
                    self._current_result = frame


if __name__ == "__main__":
    # Manual testing utility for local development.
    import sys
    import time

    from prompt_toolkit import prompt
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.shortcuts import choice
    from prompt_toolkit.validation import Validator
    from serial.tools import list_ports

    animal_count = 0
    last_error = ""

    ports = [port.device for port in list_ports.comports()]
    if not ports:
        print("❌ No serial ports found.")
        sys.exit(1)

    port_options = [(port, port) for port in ports]

    try:
        selected_port = choice(
            message="Available serial ports: ",
            options=port_options,
            default=ports[0],
            show_frame=True,
            bottom_toolbar=HTML(
                " Press <b>[Up]</b>/<b>[Down]</b> to select, <b>[Enter]</b> to accept, <b>[Ctrl+C]</b> to quit."
            ),
            mouse_support=True,
        )
    except KeyboardInterrupt:
        print("\n🛑 Manually stopped by user.")
        sys.exit(0)

    baudrate_text = prompt(
        "BAUDRATE [57600]: ",
        default="57600",
        validator=Validator.from_callable(
            lambda text: text.isdigit() and int(text) > 0,
            error_message="Baudrate must be a positive integer.",
        ),
        validate_while_typing=False,
    )

    PORT = selected_port
    BAUDRATE = int(baudrate_text)

    reader = DorsetLID665v42(port=PORT, baudrate=BAUDRATE)

    try:
        reader.open()
        reader.begin()
        print(f"✅ Serial port {PORT} opened with baudrate {BAUDRATE}")
        print(
            "📡 Listening for Dorset LID665v42 data frames... (Press Ctrl+C to stop)\n"
        )

        while True:
            time.sleep(0.1)
            result = reader.read()
            if result is not None:
                animal_count += 1
                t = time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(result.detect_time)
                )
                print(
                    f"[{t}] 🐒 Animal detected #{animal_count}: ID={result.animal_id}"
                )
            if reader.errno and reader.errno != last_error:
                last_error = reader.errno
                print(f"⚠️ Reader warning: {last_error}")

    except KeyboardInterrupt:
        print("\n🛑 Manually stopped by user.")

    except Exception as e:
        print(f"❌ Error: {e}")

    finally:
        reader.close()
        print(f"🔌 Serial port closed. Total animals detected: {animal_count}")
