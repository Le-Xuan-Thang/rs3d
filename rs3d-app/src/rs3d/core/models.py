"""Plain data types shared by the core modules and the UI."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from obspy import UTCDateTime

UNITS = ("counts", "m/s")


class Level(str, Enum):
    OK = "ok"
    WARN = "warn"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class Device:
    """A Shake the app can talk to. The SSH password lives in the keyring, not here."""

    name: str
    host: str
    seedlink_port: int = 18000
    ssh_user: str = "myshake"
    key_path: Path | None = None
    network: str = "AM"
    station: str = ""
    location: str = "00"


@dataclass(frozen=True)
class Check:
    """One row of the Status page. Wording comes from help/en.yaml via help_id."""

    id: str
    level: Level
    value: str = ""
    help_id: str = ""
    action: str | None = None


@dataclass(frozen=True)
class Selection:
    """What the user picked on the Data page. Export and codegen both consume it."""

    network: str
    station: str
    location: str
    start: UTCDateTime
    end: UTCDateTime
    channels: tuple[str, ...] = ("EHZ", "EHN", "EHE")
    filter: tuple[float, float] | None = None
    units: str = "counts"

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if not self.channels:
            raise ValueError("select at least one channel")
        if self.units not in UNITS:
            raise ValueError(f"units must be one of {UNITS}")
        if self.filter is not None:
            fmin, fmax = self.filter
            if not 0 < fmin < fmax:
                raise ValueError("filter must satisfy 0 < fmin < fmax")
