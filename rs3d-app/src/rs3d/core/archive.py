"""Copy the Shake's own SDS archive (/opt/data/archive) into the local store over SFTP."""

from __future__ import annotations

import posixpath
import struct
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Protocol

from obspy import UTCDateTime

from rs3d.core.coverage import local_spans
from rs3d.core.miniseed_records import RecordError, merge_records, read_range, record_length
from rs3d.core.store import Store

REMOTE_ROOT = "/opt/data/archive"


class Sftp(Protocol):
    def listdir(self, path: str) -> list[str]: ...
    def get(self, remotepath: str, localpath: str) -> None: ...
    def stat(self, path: str) -> object: ...  # with st_size
    def open(self, path: str, mode: str = "rb") -> object: ...  # file-like: seek, read, close


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


@dataclass(frozen=True)
class Job:
    """One piece to copy: the part of one day file of one channel that covers the selection."""

    channel: str
    day: date
    start: float  # epoch seconds
    end: float


TOLERANCE_S = 5.0  # uncovered time shorter than this is not worth a request
BYTES_PER_SECOND = 330  # one channel at 100 Hz, about 28 MB per day


def _uncovered(needed: tuple[float, float], covered: list[tuple[float, float]]) -> float:
    """Seconds of `needed` that no span in `covered` includes."""
    a, b = needed
    merged: list[list[float]] = []
    for s, e in sorted(covered):
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return max((b - a) - sum(max(0.0, min(e, b) - max(s, a)) for s, e in merged), 0.0)


def plan_downloads(store: Store, network: str, station: str, location: str, channels: tuple[str, ...],
                   remote: set[date], start: UTCDateTime, end: UTCDateTime) -> list[Job]:
    """The pieces of the Shake's archive that the selection needs and the laptop does not have yet."""
    jobs = []
    newest = max(remote) if remote else None
    first, last = start.date, (end - 1e-6).date
    for channel in channels:
        key = store.fetched.key(network, station, location, channel)
        local_days = store.days(network, station, location, channel)
        spans = store.fetched.spans(key)
        for i in range((last - first).days + 1):
            day = first + timedelta(days=i)
            if day not in remote:
                continue
            if day in local_days and not store.fetched.has_day(key, day) and day != newest:
                continue  # a whole-day copy from before partial downloads
            day0 = UTCDateTime(day.year, day.month, day.day)
            a, b = max(start, day0).timestamp, min(end, day0 + 86400).timestamp
            covered = [(s.timestamp, e.timestamp) for s, e in
                       local_spans(store, network, station, location, channel, UTCDateTime(a), UTCDateTime(b))]
            if _uncovered((a, b), covered + spans) > TOLERANCE_S:
                jobs.append(Job(channel, day, a, b))
    return jobs


def estimate_bytes(jobs: list[Job]) -> int:
    return int(sum(j.end - j.start for j in jobs) * BYTES_PER_SECOND)


def download_range(sftp: Sftp, store: Store, network: str, station: str, location: str, job: Job) -> Path:
    """Copy only the records of the day file that cover the job and merge them into the local day file.

    Falls back to copying the whole day file when the remote file is not a plain run of fixed-length records
    or its record length differs from the local file's.
    """
    remote = remote_day_path(network, station, location, job.channel, job.day)
    local = store.day_path(network, station, location, job.channel, job.day)
    key = store.fetched.key(network, station, location, job.channel)
    day0 = UTCDateTime(job.day.year, job.day.month, job.day.day).timestamp
    try:
        size = sftp.stat(remote).st_size
        with sftp.open(remote, "rb") as f:
            records, data_end, length = read_range(f, size, job.start, job.end)
        existing = local.read_bytes() if local.exists() else b""
        if existing and record_length(existing[:64]) != length:
            raise RecordError("record length differs from the local file")
        merged = merge_records(existing, records, length)
    except (RecordError, OSError, struct.error):
        path = download_day(sftp, store, network, station, location, job.channel, job.day)
        store.fetched.add(key, day0, day0 + 86400)
        return path
    local.parent.mkdir(parents=True, exist_ok=True)
    part = local.with_name(local.name + ".part")
    try:
        part.write_bytes(merged)
        part.replace(local)
    finally:
        part.unlink(missing_ok=True)
    store.fetched.add(key, job.start, min(job.end, data_end))
    return local


def sync_range(sftp: Sftp, store: Store, network: str, station: str, location: str, channels: tuple[str, ...],
               start: UTCDateTime, end: UTCDateTime,
               progress: Callable[[int, int, str], None] | None = None) -> list[Path]:
    """Copy the pieces of the Shake's archive that cover [start, end]. Returns the files written."""
    remote = set()
    for channel in channels:
        remote |= list_remote_days(sftp, network, station, location, channel)
    jobs = plan_downloads(store, network, station, location, channels, remote, start, end)
    written = []
    for i, job in enumerate(jobs, 1):
        if progress:
            progress(i, len(jobs), f"{job.channel} {job.day}")
        written.append(download_range(sftp, store, network, station, location, job))
    return written
