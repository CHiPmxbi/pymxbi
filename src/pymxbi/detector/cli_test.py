import typer

app = typer.Typer()


def prompt_detector_config() -> tuple[str, int, int, float, float]:
    port = typer.prompt("RFID serial port", type=str, default="/dev/ttyUSB0")
    if not port.strip():
        raise typer.BadParameter("port cannot be empty")

    baudrate = typer.prompt("RFID baudrate", type=int, default=9600)
    if baudrate <= 0:
        raise typer.BadParameter("baudrate must be > 0")

    pin = typer.prompt("Beam-break GPIO pin", type=int, default=17)
    if pin < 0:
        raise typer.BadParameter("pin must be >= 0")

    poll_interval = typer.prompt(
        "Detector poll interval (seconds)", type=float, default=0.05
    )
    if poll_interval <= 0:
        raise typer.BadParameter("poll_interval must be > 0")

    rfid_timeout = typer.prompt(
        "RFID timeout window (seconds)", type=float, default=10.0
    )
    if rfid_timeout <= 0:
        raise typer.BadParameter("rfid_timeout must be > 0")

    return port, baudrate, pin, poll_interval, rfid_timeout


@app.command()
def run():
    from time import sleep

    from .detector import DetectorEvent
    from .fusion_continuous_detector import FusionContinuousDetector
    from ..peripheral.rfid.dorset_lid665v42 import DorsetLID665v42
    from ..peripheral.beam_break_sensor.RPI_IR_break_beam_sensor import (
        RPIIRBreakBeamSensor,
    )

    port, baudrate, pin, poll_interval, rfid_timeout = prompt_detector_config()

    rfid_reader = DorsetLID665v42(port=port, baudrate=baudrate)
    beam_break_sensor = RPIIRBreakBeamSensor(pin=pin)

    detector = FusionContinuousDetector(
        rfid_reader,
        beam_break_sensor,
        poll_interval=poll_interval,
        rfid_timeout=rfid_timeout,
    )

    detector.register_event(DetectorEvent.ANIMAL_ENTERED, print_animal_entered)
    detector.register_event(DetectorEvent.ANIMAL_LEFT, print_animal_exited)

    rfid_reader.open()
    rfid_reader.begin()
    detector.begin()

    typer.echo("Listening detector events... (Ctrl+C to stop)")
    try:
        while True:
            sleep(1.0)
    except KeyboardInterrupt:
        typer.echo("Exiting.")
    finally:
        detector.quit()
        rfid_reader.close()
        beam_break_sensor.close()


def print_animal_entered(result) -> None:
    typer.echo(f"[ENTER] animal_id={result.animal_id}, error={result.error}")


def print_animal_exited(result) -> None:
    typer.echo(f"[LEAVE] animal_id={result.animal_id}, error={result.error}")


if __name__ == "__main__":
    app()
