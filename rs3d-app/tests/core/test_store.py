from datetime import date

from obspy import UTCDateTime

from rs3d.core.models import Selection
from rs3d.core.store import Store
from tests.conftest import DAY1, DAY2, GAP_END, GAP_START, T_START


def test_day_path_is_sds_layout(tmp_path):
    s = Store(tmp_path)
    p = s.day_path("AM", "R77A7", "00", "EHZ", date(2026, 10, 12))
    assert p == tmp_path / "2026" / "AM" / "R77A7" / "EHZ.D" / "AM.R77A7.00.EHZ.D.2026.285"


def test_days_lists_files(store):
    assert store.days("AM", "R77A7", "00", "EHZ") == {DAY1, DAY2}
    assert store.days("AM", "R77A7", "00", "XXX") == set()


def test_load_trims_to_selection_across_midnight(store):
    sel = Selection("AM", "R77A7", "00", T_START + 60, UTCDateTime("2026-10-12T00:01:00"))
    st = store.load(sel)
    assert sorted(tr.stats.channel for tr in st) == ["EHE", "EHN", "EHZ"]
    for tr in st:
        assert tr.stats.starttime == sel.start
        assert abs(tr.stats.endtime - sel.end) <= tr.stats.delta


def test_load_keeps_gap_as_separate_traces(store):
    sel = Selection("AM", "R77A7", "00", GAP_START - 30, GAP_END + 30, channels=("EHZ",))
    st = store.load(sel)
    assert len(st) == 2
    first, second = sorted(st, key=lambda tr: tr.stats.starttime)
    assert first.stats.endtime < GAP_START
    assert second.stats.starttime == GAP_END
