"""Where the app keeps its files on each OS."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir

ENV_DATA_DIR = "RS3D_DATA_DIR"


@dataclass(frozen=True)
class AppPaths:
    root: Path

    @classmethod
    def default(cls) -> "AppPaths":
        """$RS3D_DATA_DIR if set, else the OS data folder (e.g. %LOCALAPPDATA%\\rs3d)."""
        override = os.environ.get(ENV_DATA_DIR)
        return cls(Path(override) if override else Path(user_data_dir("rs3d", appauthor=False)))

    @property
    def config(self) -> Path:
        return self.root / "config.toml"

    @property
    def sds(self) -> Path:
        return self.root / "sds"

    @property
    def response(self) -> Path:
        return self.root / "response"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def known_hosts(self) -> Path:
        return self.root / "known_hosts"

    def ensure(self) -> "AppPaths":
        for d in (self.root, self.sds, self.response, self.logs):
            d.mkdir(parents=True, exist_ok=True)
        return self
