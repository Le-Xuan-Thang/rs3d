"""Local SDS (SeisComP Data Structure) store of miniSEED day files."""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from obspy import Stream
from obspy.clients.filesystem.sds import Client

from rs3d.core.models import Selection

_DAY_FILE = re.compile(r"^(?P<net>[^.]+)\.(?P<sta>[^.]+)\.(?P<loc>[^.]*)\.(?P<cha>[^.]+)\.D\.(?P<year>\d{4})\.(?P<doy>\d{3})$")


class Store:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def day_path(self, network: str, station: str, location: str, channel: str, day: date) -> Path:
        doy = day.timetuple().tm_yday
        name = f"{network}.{station}.{location}.{channel}.D.{day.year}.{doy:03d}"
        return self.root / str(day.year) / network / station / f"{channel}.D" / name

    def days(self, network: str, station: str, location: str, channel: str) -> set[date]:
        """Days that have a file in the store for this channel."""
        found: set[date] = set()
        for path in self.root.glob(f"*/{network}/{station}/{channel}.D/*"):
            m = _DAY_FILE.match(path.name)
            if m and m["loc"] == location:
                found.add(date(int(m["year"]), 1, 1) + timedelta(days=int(m["doy"]) - 1))
        return found

    def load(self, sel: Selection) -> Stream:
        """Raw counts for the selection, trimmed to [start, end]. Gaps stay as separate traces."""
        client = Client(str(self.root))
        st = Stream()
        for channel in sel.channels:
            st += client.get_waveforms(sel.network, sel.station, sel.location, channel, sel.start, sel.end)
        st.trim(sel.start, sel.end)
        return st
