"""Fill today's DayTrace from the Shake's own archive, so the live helicorder is not empty after a start."""

from __future__ import annotations

import logging

from obspy import UTCDateTime

from rs3d.core import archive
from rs3d.core.day_trace import SECONDS, DayTrace
from rs3d.core.helicorder import load_window
from rs3d.core.models import Device
from rs3d.core.store import Store

log = logging.getLogger(__name__)


def preload_today(sftp: archive.Sftp, store: Store, device: Device, day_trace: DayTrace,
                  channels: tuple[str, ...]) -> list[str]:
    """Copy today's day file of each channel into the local store and read it into `day_trace`.

    Never raises: a channel that cannot be fetched or read is logged and skipped. Returns the channels filled.
    """
    day = day_trace.day
    start = UTCDateTime(day_trace.start)
    done: list[str] = []
    for channel in channels:
        try:
            archive.download_day(sftp, store, device.network, device.station, device.location, channel, day)
            st = load_window(store, device.network, device.station, device.location, channel, start,
                             start + SECONDS)
            day_trace.replace_from(st)
            done.append(channel)
        except Exception as exc:  # a missing file (new day, no archive) or a cut record is not an error
            log.warning("live helicorder: no archive data for %s %s: %s", channel, day, exc)
    return done
