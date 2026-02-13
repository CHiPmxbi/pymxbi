import os
from pathlib import Path

XDG_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
CONFIG_DIR = XDG_CONFIG_HOME / "mxbi"

FREQUENCY_RESPONSE_TABLE = CONFIG_DIR / "frequency_response_table.json"
