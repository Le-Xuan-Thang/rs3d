from rs3d.core.events import Event
from rs3d.core.events_store import EventStore
from rs3d.core.paths import AppPaths


def ev(start, end=None, src="live"):
    return Event(start, end or start + 10, 5.0, 100.0, "EHZ", src)


def test_paths_has_events_file(tmp_path):
    assert AppPaths(tmp_path).events == tmp_path / "events.jsonl"


def test_round_trip(tmp_path):
    s = EventStore(tmp_path / "events.jsonl")
    assert s.append(ev(100)) and s.append(ev(200))
    assert [e.start for e in s.latest(5)] == [200, 100]
    assert [e.start for e in s.events_between(150, 250)] == [200]


def test_corrupt_line_skipped(tmp_path):
    p = tmp_path / "events.jsonl"
    s = EventStore(p)
    s.append(ev(100))
    with open(p, "a") as f:
        f.write("{not json\n")
        f.write('{"start": 1}\n')
        f.write('{"start": 5, "end": 6')  # a line cut short by a crash
    s.append(ev(300))
    assert len(s.latest(10)) == 2 and s.skipped >= 2


def test_replace_keeps_live_and_other_days(tmp_path):
    s = EventStore(tmp_path / "events.jsonl")
    s.append(ev(1000, src="live"))
    s.append(ev(500, src="scan"))     # in the day
    s.append(ev(90000, src="scan"))   # next day
    assert s.replace_scan_events(0, 86400, [ev(700, src="scan")])
    got = {(e.start, e.source) for e in s.latest(10)}
    assert got == {(1000, "live"), (700, "scan"), (90000, "scan")}


def test_overlap_lists_only_live(tmp_path):
    s = EventStore(tmp_path / "events.jsonl")
    s.append(ev(100, 120, "live"))
    s.append(ev(110, 130, "scan"))
    assert [e.source for e in s.latest(10)] == ["live"]


def test_write_failure_sets_error_and_reads_stay_empty(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    s = EventStore(blocker / "events.jsonl")  # parent is a file, so nothing can be written
    assert s.append(ev(1)) is False and s.error
    assert s.latest(5) == []


def test_error_clears_after_a_good_write(tmp_path):
    s = EventStore(tmp_path / "sub" / "events.jsonl")
    s.error = "old"
    assert s.append(ev(1)) and s.error == ""
