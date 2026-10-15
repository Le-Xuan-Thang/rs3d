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


def test_read_never_raises_on_bad_lines(tmp_path):
    p = tmp_path / "events.jsonl"
    s = EventStore(p)
    s.append(ev(100))
    full = '"end": 1, "peak_ratio": 1.0, "peak_amplitude": 1.0, "channel": "EHZ", "source": "live"'
    with open(p, "ab") as f:
        f.write(b"\xff\xfe not utf8\n")
        f.write(('{"start": null, %s}\n' % full).encode())
        f.write(('{"start": "x", %s}\n' % full).encode())
        f.write(('{"start": true, %s}\n' % full).encode())
        f.write(b'[1, 2]\n')
        f.write(b'{"start": 1, "end": 2, "peak_ratio": 1, "peak_amplitude": 1, "channel": 5, "source": "live"}\n')
    s.append(ev(300))
    assert [e.start for e in s.latest(10)] == [300, 100]
    assert s.skipped == 6
    assert [e.start for e in s.events_between(0, 1000)] == [100, 300]


def test_state_builds_with_bad_events_file(tmp_path):
    from tests.app.test_state_events import make
    (tmp_path / "events.jsonl").write_bytes(b'\xff\xfe\n{"start": null}\n')
    assert make(tmp_path).recent_events is not None


def test_unreadable_file_aborts_replace(tmp_path):
    import os
    import pytest
    if os.geteuid() == 0:
        pytest.skip("root ignores file modes")
    p = tmp_path / "events.jsonl"
    s = EventStore(p)
    s.append(ev(1000, src="live"))
    p.chmod(0o000)
    try:
        assert s.replace_scan_events(0, 86400, [ev(5, src="scan")]) is False
        assert "cannot read" in s.error and "write" not in s.error
        assert s.latest(5) == [] and s.events_between(0, 9999) == []
    finally:
        p.chmod(0o644)
    assert [e.start for e in s.latest(5)] == [1000]
