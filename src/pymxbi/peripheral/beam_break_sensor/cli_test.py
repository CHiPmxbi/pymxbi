import argparse


def parse_args():
    parser = argparse.ArgumentParser(description="Beam break sensor CLI test.")
    parser.add_argument(
        "-p",
        "--pin",
        type=int,
        default=17,
        help="GPIO pin number (default: 10).",
    )
    parser.add_argument(
        "-d",
        "--debounce-time",
        type=float,
        default=0.05,
        help="Debounce time in seconds (default: 0.05).",
    )
    normally_open_group = parser.add_mutually_exclusive_group()
    normally_open_group.add_argument(
        "--normally-open",
        dest="normally_open",
        action="store_true",
        default=True,
        help="Set sensor as normally open (default).",
    )
    normally_open_group.add_argument(
        "--normally-closed",
        dest="normally_open",
        action="store_false",
        help="Set sensor as normally closed.",
    )
    return parser.parse_args()


def cli_test():
    from .RPI_IR_break_beam_sensor import RPIIRBreakBeamSensor

    args = parse_args()
    sensor = RPIIRBreakBeamSensor(
        pin=args.pin,
        debounce_time=args.debounce_time,
        normally_open=args.normally_open,
    )

    try:
        while True:
            print(sensor.read())
    except KeyboardInterrupt:
        print("Exiting.")


if __name__ == "__main__":
    cli_test()
