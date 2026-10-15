"""Local SDS (SeisComP Data Structure) store of miniSEED day files."""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from obspy import Stream, UTCDateTime, read
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

    def stations(self) -> list[tuple[str, str, str]]:
        """(network, station, location) of everything in the store, sorted."""
        found = set()
        for path in self.root.glob("*/*/*/*.D/*"):
            m = _DAY_FILE.match(path.name)
            if m:
                found.add((m["net"], m["sta"], m["loc"]))
        return sorted(found)

    def channels(self, network: str, station: str, location: str) -> list[str]:
        found = set()
        for path in self.root.glob(f"*/{network}/{station}/*.D/*"):
            m = _DAY_FILE.match(path.name)
            if m and m["loc"] == location:
                found.add(m["cha"])
        order = {"Z": 0, "N": 1, "E": 2}
        return sorted(found, key=lambda c: (order.get(c[-1:], 9), c))

    def import_file(self, path: Path | str) -> list[Path]:
        """Copy any miniSEED file into the store, split into SDS day files.

        Data already in the store for the same channel and day is kept; overlapping
        samples are merged (identical overlaps collapse, gaps stay gaps).
        """
        st = read(str(path))
        written = []
        for tr_id in sorted({tr.id for tr in st}):
            part = st.select(id=tr_id)
            first = min(tr.stats.starttime for tr in part).date
            last = max(tr.stats.endtime for tr in part).date
            net, sta, loc, cha = tr_id.split(".")
            day = first
            while day <= last:
                start = UTCDateTime(day.year, day.month, day.day)
                piece = part.slice(start, start + 86400 - 1e-6).copy()
                if piece:
                    target = self.day_path(net, sta, loc, cha, day)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists():
                        piece += read(str(target))
                        piece.merge(method=1)
                    piece.split().write(str(target), format="MSEED")
                    written.append(target)
                day += timedelta(days=1)
        return written
