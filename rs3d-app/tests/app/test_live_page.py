from rs3d.app.pages.live import WINDOWS, band_for, status_text
from rs3d.core.live import RingBuffer


def test_status_shows_error_reason_while_reconnecting():
    assert status_text("reconnecting", False, "[Errno 111] Connection refused") == \
        "reconnecting… ([Errno 111] Connection refused)"
    assert status_text("reconnecting", False, "") == "reconnecting…"


def test_status_live_and_stale():
    assert status_text("live", False, "") == "live"
    assert status_text("live", True, "") == "waiting for data…"


def test_band_for_accepts_only_a_valid_band():
    assert band_for(True, 1.0, 10.0) == (1.0, 10.0)
    assert band_for(False, 1.0, 10.0) is None
    assert band_for(True, 10.0, 1.0) is None
    assert band_for(True, None, 10.0) is None
    assert band_for(True, 0.0, 10.0) is None


def test_longest_window_fits_the_ring_buffer():
    assert max(WINDOWS) <= RingBuffer().seconds
    assert 600 in WINDOWS
