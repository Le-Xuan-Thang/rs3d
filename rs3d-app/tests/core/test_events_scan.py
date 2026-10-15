from datetime import date

import numpy as np
from obspy import Stream, Trace, UTCDateTime

from rs3d.core.events import EventSettings
from rs3d.core.events_scan import days_between, scan_day
from rs3d.core.events_store import EventStore
from rs3d.core.store import Store

RATE = 100.0
DAY = date(2026, 10, 12)
MIDNIGHT = UTCDateTime(2026, 10, 12)


def put(store, start, seconds, burst=None, seed=1):
    """Write `seconds` of EHZ noise starting at `start` into the SDS file of that UTC day."""
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    x = rng.normal(0, 20, n)
    if burst:
        b0, b1 = burst
        t = np.arange(int(b0 * RATE), int(b1 * RATE)) / RATE
        x[int(b0 * RATE):int(b1 * RATE)] += 2000 * np.sin(2 * np.pi * 3 * t)
    tr = Trace(x.astype("int32"), header={"network": "AM", "station": "R77A7", "location": "00", "channel": "EHZ",
                                          "starttime": start, "sampling_rate": RATE})
    path = store.day_path("AM", "R77A7", "00", "EHZ", start.date)
    path.parent.mkdir(parents=True, exist_ok=True)
    Stream([tr]).write(str(path), format="MSEED")


def test_days_between_is_inclusive():
    assert days_between(date(2026, 10, 11), date(2026, 10, 13)) == [date(2026, 10, 11), date(2026, 10, 12),
                                                                     date(2026, 10, 13)]
    assert days_between(DAY, DAY) == [DAY]


def test_scan_day_stores_scan_events_and_keeps_live(tmp_path):
    store, log = Store(tmp_path / "sds"), EventStore(tmp_path / "events.jsonl")
    put(store, MIDNIGHT + 3600, 300, burst=(120, 130))
    from rs3d.core.events import Event
    log.append(Event(MIDNIGHT.timestamp + 10, MIDNIGHT.timestamp + 20, 5.0, 1.0, "EHZ", "live"))
    n = scan_day(store, log, EventSettings(), "AM", "R77A7", "00", DAY)
    assert n == 1
    assert sorted(e.source for e in log.latest(10)) == ["live", "scan"]
    assert scan_day(store, log, EventSettings(), "AM", "R77A7", "00", DAY) == 1  # rescan replaces, no duplicates
    assert len(log.latest(10)) == 2


def test_scan_day_without_data_clears_old_scan_events(tmp_path):
    store, log = Store(tmp_path / "sds"), EventStore(tmp_path / "events.jsonl")
    from rs3d.core.events import Event
    log.append(Event(MIDNIGHT.timestamp + 100, MIDNIGHT.timestamp + 110, 5.0, 1.0, "EHZ", "scan"))
    assert scan_day(store, log, EventSettings(), "AM", "R77A7", "00", DAY) == 0
    assert log.latest(10) == []


def test_scan_day_uses_previous_day_for_warmup(tmp_path):  # Review Focus 6
    store, log = Store(tmp_path / "sds"), EventStore(tmp_path / "events.jsonl")
    put(store, MIDNIGHT - 120, 120)                                 # last 2 minutes of the previous day
    put(store, MIDNIGHT, 120, burst=(10, 20), seed=2)               # shaking 10 s after midnight
    assert scan_day(store, log, EventSettings(), "AM", "R77A7", "00", DAY) == 1
    e = log.latest(1)[0]
    assert MIDNIGHT.timestamp <= e.start < MIDNIGHT.timestamp + 20
    # the same burst with no previous-day data is inside the warm-up, so it is (correctly) ignored
    store2, log2 = Store(tmp_path / "sds2"), EventStore(tmp_path / "events2.jsonl")
    put(store2, MIDNIGHT, 120, burst=(10, 20), seed=2)
    assert scan_day(store2, log2, EventSettings(), "AM", "R77A7", "00", DAY) == 0


def test_event_from_previous_day_is_not_stored_for_this_day(tmp_path):
    store, log = Store(tmp_path / "sds"), EventStore(tmp_path / "events.jsonl")
    put(store, MIDNIGHT - 200, 200, burst=(150, 190))               # shaking before midnight, still going at 00:00
    put(store, MIDNIGHT, 100, seed=3)
    scan_day(store, log, EventSettings(), "AM", "R77A7", "00", DAY)
    assert all(e.start >= MIDNIGHT.timestamp for e in log.latest(10))


def test_burst_across_a_chunk_boundary_gives_one_event(tmp_path):
    from rs3d.core.events import detect
    from rs3d.core.models import Selection
    store, log = Store(tmp_path / "sds"), EventStore(tmp_path / "events.jsonl")
    put(store, MIDNIGHT, 7200, burst=(3580, 3620))                  # straddles the 3600 s boundary
    n = scan_day(store, log, EventSettings(), "AM", "R77A7", "00", DAY)
    whole = detect(store.load(Selection("AM", "R77A7", "00", MIDNIGHT, MIDNIGHT + 86400, channels=("EHZ",))),
                   EventSettings())
    assert n == 1 and len(whole) == 1
    assert log.latest(5)[0].start == whole[0].start


def test_chunks_are_at_most_an_hour_and_contiguous():
    from rs3d.core.events_scan import chunked
    tr = Trace(np.arange(int(2.5 * 3600 * 10), dtype="float64"),
               header={"sampling_rate": 10.0, "starttime": MIDNIGHT, "channel": "EHZ"})
    parts = list(chunked(tr, 3600))
    assert [len(p.data) for p in parts] == [36000, 36000, 18000]
    assert parts[1].stats.starttime == MIDNIGHT + 3600
    assert np.concatenate([p.data for p in parts]).tolist() == tr.data.tolist()
