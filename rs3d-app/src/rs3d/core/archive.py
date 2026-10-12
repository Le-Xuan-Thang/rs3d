"""Copy the Shake's own SDS archive (/opt/data/archive) into the local store over SFTP."""

from __future__ import annotations

import posixpath
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Protocol

from rs3d.core.store import Store

REMOTE_ROOT = "/opt/data/archive"


class Sftp(Protocol):
    def listdir(self, path: str) -> list[str]: ...
    def get(self, remotepath: str, localpath: str) -> None: ...


def remote_day_path(network: str, station: str, location: str, channel: str, day: date) -> str:
    doy = day.timetuple().tm_yday
    return posixpath.join(REMOTE_ROOT, str(day.year), network, station, f"{channel}.D",
                          f"{network}.{station}.{location}.{channel}.D.{day.year}.{doy:03d}")


def list_remote_days(sftp: Sftp, network: str, station: str, location: str, channel: str) -> set[date]:
    days: set[date] = set()
    try:
        years = [y for y in sftp.listdir(REMOTE_ROOT) if y.isdigit()]
    except OSError:
        return days
    prefix = f"{network}.{station}.{location}.{channel}.D."
    for year in years:
        folder = posixpath.join(REMOTE_ROOT, year, network, station, f"{channel}.D")
        try:
            names = sftp.listdir(folder)
        except OSError:
            continue
        for name in names:
            if name.startswith(prefix):
                y, doy = name[len(prefix):].split(".")
                days.add(date(int(y), 1, 1) + timedelta(days=int(doy) - 1))
    return days


def days_to_fetch(remote: set[date], local: set[date], start: date, end: date) -> list[date]:
    """Remote days in [start, end] that are missing locally, plus the newest remote day (still growing)."""
    wanted = {d for d in remote if start <= d <= end and d not in local}
    if remote:
        newest = max(remote)
        if start <= newest <= end:
            wanted.add(newest)
    return sorted(wanted)


def download_day(sftp: Sftp, store: Store, network: str, station: str, location: str,
                 channel: str, day: date) -> Path:
    """Download into <file>.part, then rename, so an interrupted copy never looks complete."""
    remote = remote_day_path(network, station, location, channel, day)
    local = store.day_path(network, station, location, channel, day)
    local.parent.mkdir(parents=True, exist_ok=True)
    part = local.with_name(local.name + ".part")
    try:
        sftp.get(remote, str(part))
        part.replace(local)
    finally:
        part.unlink(missing_ok=True)
    return local


def sync(sftp: Sftp, store: Store, network: str, station: str, location: str,
         channels: tuple[str, ...], start: date, end: date,
         progress: Callable[[int, int, str], None] | None = None) -> list[Path]:
    """Fetch every needed day file for the channels in [start, end]. Returns the files written."""
    jobs = []
    for channel in channels:
        remote = list_remote_days(sftp, network, station, location, channel)
        local = store.days(network, station, location, channel)
        jobs += [(channel, d) for d in days_to_fetch(remote, local, start, end)]
    written = []
    for i, (channel, day) in enumerate(jobs, 1):
        if progress:
            progress(i, len(jobs), f"{channel} {day}")
        written.append(download_day(sftp, store, network, station, location, channel, day))
    return written
