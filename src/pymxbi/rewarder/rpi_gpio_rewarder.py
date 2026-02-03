from .pump_rewarder import PumpRewarder
from ..peripheral.pumps.RPI_gpio_pump import RPIGpioPump


class RPIGpioRewarder:
    def __init__(self, pin: int) -> None:
        self._pump = RPIGpioPump(pin)
        self._rewarder = PumpRewarder(self._pump)

    def reward(self, duration: int) -> None:
        self._rewarder.give_reward(duration)

    def open(self) -> None:
        self._rewarder.open()

    def give_reward(self, duration_ms: int) -> None:
        self._rewarder.give_reward(duration_ms)

    def give_reward_by_volume(self, volume_ul: int) -> None:
        self._rewarder.give_reward_by_volume(volume_ul)

    def give_reward_by_count(self, count: int) -> None:
        self._rewarder.give_reward_by_count(count)

    def stop_reward(self) -> None:
        self._rewarder.stop_reward()

    def close(self) -> None:
        self._rewarder.close()
