from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Screen:
    width: int
    height: int
