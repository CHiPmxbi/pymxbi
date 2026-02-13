from pydantic import RootModel, ConfigDict
from typing import TypeAlias

from ...paths import FREQUENCY_RESPONSE_TABLE


Frequency: TypeAlias = int
MasterVolume: TypeAlias = int


class FrequencyResponseTable(RootModel[dict[Frequency, MasterVolume]]):
    model_config = ConfigDict(frozen=True)

    def get(self, freq: Frequency, default: MasterVolume | None = None) -> MasterVolume | None:
        return self.root.get(freq, default)

    def get_volume_by_freq(self, freq: Frequency) -> MasterVolume:
        if freq in self.root:
            return self.root[freq]
        closest = min(self.root, key=lambda f: abs(f - freq))
        return self.root[closest]

    @classmethod
    def from_file(cls) -> FrequencyResponseTable | None:
        if not FREQUENCY_RESPONSE_TABLE.exists():
            return None
        return cls.model_validate_json(FREQUENCY_RESPONSE_TABLE.read_text())
