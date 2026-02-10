import typer
from time import sleep

app = typer.Typer()


def prompt_sensor_config():
    pin = typer.prompt("GPIO pin", type=int, default=17)
    if pin < 0:
        raise typer.BadParameter("pin must be >= 0")

    debounce_time = typer.prompt("Debounce time (seconds)", type=float, default=0.05)
    if debounce_time < 0:
        raise typer.BadParameter("debounce_time must be >= 0")

    normally_open = typer.confirm("Normally open?", default=True)
    return pin, debounce_time, normally_open


@app.command()
def run():
    from .RPI_IR_break_beam_sensor import RPIIRBreakBeamSensor

    pin, debounce_time, normally_open = prompt_sensor_config()
    sensor = RPIIRBreakBeamSensor(
        pin=pin,
        debounce_time=debounce_time,
        normally_open=normally_open,
    )

    try:
        while True:
            print(sensor.read())
            sleep(0.1)
    except KeyboardInterrupt:
        print("Exiting.")


if __name__ == "__main__":
    app()
