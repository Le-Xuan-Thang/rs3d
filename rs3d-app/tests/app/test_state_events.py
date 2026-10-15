import numpy as np
from obspy import Trace, UTCDateTime

from rs3d.app.state import AppState
from rs3d.core.devices import Passwords
from rs3d.core.events import EventSettings
from rs3d.core.live import LiveStream
from rs3d.core.paths import AppPaths

RATE = 100.0
T0 = 1_700_000_000.0


class NoKeyring:
    def get_password(self, *a):
        return None

    def set_password(self, *a):
        pass

    def delete_password(self, *a):
        pass


def make(tmp_path):
    return AppState(AppPaths(tmp_path), passwords=Passwords(NoKeyring()))


def noise(seconds, burst=None, start=T0, amp=2000.0):
    rng = np.random.default_rng(1)
    n = int(seconds * RATE)
    x = rng.normal(0, 20, n)
    if burst:
        t = np.arange(int(burst[0] * RATE), int(burst[1] * RATE)) / RATE
        x[int(burst[0] * RATE):int(burst[1] * RATE)] += amp * np.sin(2 * np.pi * 3 * t)
    return Trace(x, header={"sampling_rate": RATE, "starttime": UTCDateTime(start), "channel": "EHZ"})


def test_event_settings_default_save_and_load(tmp_path):
    state = make(tmp_path)
    assert state.event_settings == EventSettings()
    new = EventSettings(sta=4.0, lta=40.0, on=3.0, reset=1.0, highpass=1.0, lowpass=8.0, channel="EHN")
    assert state.set_event_settings(new) == ""
    assert make(tmp_path).event_settings == new


def test_invalid_event_settings_rejected_and_old_kept(tmp_path):
    state = make(tmp_path)
    err = state.set_event_settings(EventSettings(sta=10.0, lta=5.0))
    assert "LTA" in err
    assert state.event_settings == EventSettings()
    assert make(tmp_path).event_settings == EventSettings()


def test_bad_saved_event_settings_fall_back(tmp_path):  # Review Focus 4
    (tmp_path / "settings.toml").write_text('[events]\nlta = 2.0\nsta = 6.0\n')
    assert make(tmp_path).event_settings == EventSettings()
    (tmp_path / "settings.toml").write_text('[events]\nsta = "six"\nenabled = "yes"\nchannel = 5\non = 2.5\n')
    s = make(tmp_path).event_settings
    assert s.sta == 6.0 and s.enabled is True and s.channel == "EHZ" and s.on == 2.5
    (tmp_path / "settings.toml").write_text('events = 3\n')
    assert make(tmp_path).event_settings == EventSettings()


def test_event_settings_do_not_clobber_other_settings(tmp_path):
    state = make(tmp_path)
    state.set_use_local_time(True)
    state.set_data_prefs(units="m/s")
    state.set_event_settings(EventSettings(on=4.5))
    again = make(tmp_path)
    assert again.use_local_time is True and again.data_prefs["units"] == "m/s" and again.event_settings.on == 4.5


def test_detector_callbacks_update_state_and_log(tmp_path):
    state = make(tmp_path)
    d = state._new_detector()
    d.feed(noise(300, burst=(120, 130)))
    d.flush()
    assert state.event_open is None
    ev = state.event_last
    assert ev is not None and ev.source == "live" and ev.peak_ratio > 3.95
    assert state.recent_events[-1] == ev
    assert state.events.latest(5) == [ev]


def test_event_open_is_set_while_event_runs(tmp_path):
    state = make(tmp_path)
    d = state._new_detector()
    d.feed(noise(200, burst=(150, 199.9), amp=5000))
    assert state.event_open is not None and state.event_last is None
    start, ratio = state.event_open
    assert start > T0 + 140 and ratio > 3.95


def test_recent_events_seeded_from_log(tmp_path):
    state = make(tmp_path)
    d = state._new_detector()
    d.feed(noise(300, burst=(120, 130)))
    d.flush()
    again = make(tmp_path)
    assert list(again.recent_events) == [state.event_last]
    assert again.event_last is None  # a banner is not restored after a restart


def test_settings_change_closes_open_event(tmp_path):  # Review Focus 5
    state = make(tmp_path)
    stream = LiveStream(lambda: None, detector=state._new_detector())
    state._live["h"] = stream
    stream._on_trace(noise(200, burst=(150, 199.9), amp=5000))
    assert state.event_open is not None
    assert state.set_event_settings(EventSettings(on=4.5)) == ""
    assert state.event_open is None and state.event_last is not None
    assert state.events.latest(5)[0] == state.event_last
    assert stream.detector is not None and stream.detector.settings.on == 4.5 and not stream.detector.active


def test_switching_off_closes_open_event(tmp_path):  # Review Focus 5
    state = make(tmp_path)
    stream = LiveStream(lambda: None, detector=state._new_detector())
    state._live["h"] = stream
    stream._on_trace(noise(200, burst=(150, 199.9), amp=5000))
    state.set_event_settings(EventSettings(enabled=False))
    assert state.event_open is None and len(state.events.latest(5)) == 1


def test_reset_event_settings(tmp_path):
    state = make(tmp_path)
    state.set_event_settings(EventSettings(on=5.0))
    state.reset_event_settings()
    assert state.event_settings == EventSettings()


def test_log_failure_keeps_banner_state(tmp_path):
    state = make(tmp_path)
    blocker = tmp_path / "blocked"
    blocker.write_text("x")
    state.events.path = blocker / "events.jsonl"
    d = state._new_detector()
    d.feed(noise(300, burst=(120, 130)))
    d.flush()
    assert state.event_last is not None and state.recent_events[-1] == state.event_last
    assert state.events.error


def test_live_channels(tmp_path):
    from rs3d.core.models import Device
    state = make(tmp_path)
    dev = Device(name="x", host="h")
    assert state.live_channels(dev) == set()
    stream = LiveStream(lambda: None)
    stream._on_trace(noise(1))
    state._live["h"] = stream
    assert state.live_channels(dev) == {"EHZ"}


def test_stop_live_closes_open_event(tmp_path):
    state = make(tmp_path)
    stream = LiveStream(lambda: None, detector=state._new_detector())
    state._live["h"] = stream
    stream._on_trace(noise(200, burst=(150, 199.9), amp=5000))
    assert state.event_open is not None
    state.stop_live("h")
    assert state.event_open is None and len(state.events.latest(5)) == 1


def test_discarded_detector_cannot_open_a_late_event(tmp_path):
    state = make(tmp_path)
    stream = LiveStream(lambda: None, detector=state._new_detector())
    state._live["h"] = stream
    old = stream.detector
    state.set_event_settings(EventSettings(on=4.5))
    old.feed(noise(200, burst=(150, 199.9), amp=5000))  # a packet the live thread already held
    assert state.event_open is None and not old.active


def test_start_current_starts_live_for_current_device(tmp_path, monkeypatch):
    from rs3d.core.models import Device
    state = make(tmp_path)
    calls = []
    monkeypatch.setattr(state, "live", lambda d: calls.append(d.host))
    state.start_current()
    assert calls == []  # no device yet
    state.save_device(Device(name="a", host="ha"))
    assert calls == ["ha"]
    state.save_device(Device(name="b", host="hb"))
    assert calls == ["ha", "hb"]
    state.select("ha")
    assert calls == ["ha", "hb", "ha"]
    calls.clear()
    state.start_current()
    assert calls == ["ha"]


def test_start_current_logs_failures(tmp_path, monkeypatch, caplog):
    from rs3d.core.models import Device
    state = make(tmp_path)
    state.registry.upsert(Device(name="a", host="ha"))

    def boom(d):
        raise RuntimeError("no socket")
    monkeypatch.setattr(state, "live", boom)
    state.start_current()  # must not raise
    assert "no socket" in caplog.text
