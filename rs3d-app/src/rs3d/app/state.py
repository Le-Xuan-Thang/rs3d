"""Process-wide app state shared by all pages (one laptop, one user)."""

from __future__ import annotations

import logging
import threading
import tomllib
from collections import deque
from dataclasses import asdict, fields
from datetime import date, datetime, timezone

import tomli_w

from rs3d.core.day_trace import DayTrace
from rs3d.core.devices import DeviceRegistry, Passwords
from rs3d.core.events import Event, EventDetector, EventSettings, validate_settings
from rs3d.core.events_store import EventStore
from rs3d.core.live import LiveStream
from rs3d.core.models import Check, Device
from rs3d.core.paths import AppPaths
from rs3d.core.preload import preload_today
from rs3d.core.seedlink import SeedLinkSource
from rs3d.core.shell import Shell, ShellError
from rs3d.core.status import run_checks
from rs3d.core.store import Store

log = logging.getLogger(__name__)

CHANNELS = ("EHZ", "EHN", "EHE")
DATA_PREF_DEFAULTS = {"units": "counts", "filter": False, "fmin": 1.0, "fmax": 10.0, "station": None}


def _clean_prefs(raw: dict) -> dict:
    """Saved Data-page choices, with anything missing or of the wrong type replaced by its default."""
    prefs = dict(DATA_PREF_DEFAULTS)
    if raw.get("units") in ("counts", "m/s"):
        prefs["units"] = raw["units"]
    if isinstance(raw.get("filter"), bool):
        prefs["filter"] = raw["filter"]
    for key in ("fmin", "fmax"):
        if isinstance(raw.get(key), (int, float)) and not isinstance(raw[key], bool):
            prefs[key] = float(raw[key])
    if isinstance(raw.get("station"), str) and raw["station"]:
        prefs["station"] = raw["station"]
    return prefs


def _clean_event_settings(raw) -> EventSettings:
    """Saved event settings; any missing or wrongly typed value falls back to its default, and a set that
    fails validation (e.g. a hand-edited LTA shorter than STA) falls back entirely."""
    defaults = EventSettings()
    if not isinstance(raw, dict):
        return defaults
    values = {}
    for f in fields(EventSettings):
        default, value = getattr(defaults, f.name), raw.get(f.name)
        if isinstance(default, bool):
            ok = isinstance(value, bool)
        elif isinstance(default, str):
            ok = isinstance(value, str)
        else:
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        values[f.name] = (float(value) if isinstance(default, float) else value) if ok else default
    settings = EventSettings(**values)
    return settings if validate_settings(settings) == "" else defaults


class AppState:
    def __init__(self, paths: AppPaths, passwords: Passwords | None = None, preload: bool = False) -> None:
        self.preload = preload  # fill the live helicorder from the Shake's archive when a stream starts
        self.paths = paths.ensure()
        self.registry = DeviceRegistry(paths.config)
        self.passwords = passwords or Passwords()
        self.store = Store(paths.sds)
        self._settings_path = paths.root / "settings.toml"
        settings = tomllib.loads(self._settings_path.read_text()) if self._settings_path.exists() else {}
        self.use_local_time: bool = bool(settings.get("use_local_time", False))
        self.data_prefs: dict = _clean_prefs(settings.get("data_prefs", {}))
        self.event_settings: EventSettings = _clean_event_settings(settings.get("events", {}))
        self.events = EventStore(paths.events)
        self.event_open: tuple[float, float] | None = None  # (start, ratio) while an event is in progress
        self.event_last: Event | None = None  # last finished event; the banner shows it until dismissed
        self.recent_events: deque[Event] = deque(reversed([e for e in self.events.latest(50) if e.source == "live"]), maxlen=50)  # oldest first
        devices = self.registry.load()
        self.current_host: str | None = settings.get("current_host") or (devices[0].host if devices else None)
        self._live: dict[str, LiveStream] = {}
        self._days: dict[str, DayTrace] = {}
        self._preload_lock = threading.Lock()
        self._preloading: set[str] = set()  # hosts whose archive preload is running
        self._preloaded: dict[str, date] = {}  # host -> UTC day that a preload filled

    # ---------------------------------------------------------------- settings
    def save_settings(self) -> None:
        data: dict = {"use_local_time": self.use_local_time,
                      "data_prefs": {k: v for k, v in self.data_prefs.items() if v is not None},
                      "events": asdict(self.event_settings)}
        if self.current_host:
            data["current_host"] = self.current_host
        self._settings_path.write_text(tomli_w.dumps(data))

    def set_use_local_time(self, value: bool) -> None:
        self.use_local_time = value
        self.save_settings()

    def set_data_prefs(self, **changes) -> None:
        self.data_prefs = _clean_prefs({**self.data_prefs, **changes})
        self.save_settings()

    def set_event_settings(self, new: EventSettings) -> str:
        """Use `new` from now on. Returns '' or the reason it was rejected (the old settings stay active)."""
        error = validate_settings(new)
        if error:
            return error
        self.event_settings = new
        for stream in self._live.values():
            old = stream.detector
            if old is not None:
                old.close()  # an event in progress ends here and is logged; a packet already in flight is ignored
            stream.detector = self._new_detector()  # warm-up starts again with the new values
        self.save_settings()
        return ""

    def reset_event_settings(self) -> None:
        self.set_event_settings(EventSettings())

    def _new_detector(self) -> EventDetector:
        return EventDetector(self.event_settings, self._event_ended, self._event_started)

    def _event_started(self, start: float, ratio: float) -> None:
        self.event_open = (start, ratio)
        self.event_last = None

    def _event_ended(self, event: Event) -> None:
        self.event_open = None
        self.event_last = event
        self.recent_events.append(event)
        self.events.append(event)  # a failed write sets events.error; the banner still works

    # ---------------------------------------------------------------- devices
    def devices(self) -> list[Device]:
        return self.registry.load()

    def current(self) -> Device | None:
        devices = self.devices()
        return next((d for d in devices if d.host == self.current_host), devices[0] if devices else None)

    def select(self, host: str) -> None:
        self.current_host = host
        self.save_settings()
        self.start_current()

    def start_current(self) -> None:
        """Start the live stream (and so the event detector) of the current device, if there is one."""
        device = self.current()
        if device is None:
            return
        try:
            self.live(device)
        except Exception:
            log.exception("could not start the live stream for %s", device.host)
            return
        if self.preload:
            self._start_preload(device)

    def _start_preload(self, device: Device) -> None:
        """Start the archive preload unless one is running or already filled today for this Shake."""
        with self._preload_lock:
            if device.host in self._preloading or self._preloaded.get(device.host) == self.day_trace(device).day:
                return
            self._preloading.add(device.host)
            threading.Thread(target=self._preload, args=(device,), name="rs3d-preload", daemon=True).start()

    def _preload(self, device: Device) -> None:
        """Fill today's helicorder from the Shake's archive. Runs in a thread and never raises."""
        try:
            day = self.day_trace(device).day
            with self.shell(device) as sh:
                filled = preload_today(sh.sftp(), self.store, device, self.day_trace(device), CHANNELS)
            if filled:  # a run that filled nothing may be retried by the next start_current
                self._preloaded[device.host] = day
        except ShellError as exc:
            log.warning("live helicorder: cannot reach %s for the archive: %s", device.host, exc)
        except Exception:
            log.exception("live helicorder preload failed")
        finally:
            with self._preload_lock:
                self._preloading.discard(device.host)

    def save_device(self, device: Device, password: str | None = None) -> None:
        self.registry.upsert(device)
        if password:
            self.passwords.set(device.host, password)
        self.select(device.host)

    def remove_device(self, host: str) -> None:
        self.stop_live(host)
        self.registry.remove(host)
        self.passwords.delete(host)
        if self.current_host == host:
            remaining = self.devices()
            self.current_host = remaining[0].host if remaining else None
            self.save_settings()

    # ---------------------------------------------------------------- connections
    def shell(self, device: Device) -> Shell:
        """SSH session; tries the SSH key/agent first, then the stored (or default) password."""
        return Shell(device, self.passwords.get_or_default(device.host), self.paths.known_hosts)

    def test_connection(self, device: Device) -> None:
        """Raises ShellError when SSH login fails."""
        with self.shell(device):
            pass

    def checks(self, device: Device) -> list[Check]:
        local_days = self.store.days(device.network, device.station, device.location, "EHZ")
        return run_checks(device, self.passwords.get_or_default(device.host), local_days=local_days,
                          shell_factory=lambda d, p: Shell(d, p, self.paths.known_hosts))

    def live(self, device: Device) -> LiveStream:
        stream = self._live.get(device.host)
        if stream is None:
            stream = LiveStream(lambda: SeedLinkSource(device.host, device.seedlink_port, device.network,
                                                       device.station, CHANNELS),
                                detector=self._new_detector(), day_trace=self.day_trace(device))
            self._live[device.host] = stream
        stream.start()
        return stream

    def day_trace(self, device: Device) -> DayTrace:
        """Today's min/max data of this Shake (the live helicorder); one per Shake, created on first use."""
        trace = self._days.get(device.host)
        if trace is None:
            trace = self._days[device.host] = DayTrace(datetime.now(timezone.utc).date())
        return trace

    def stop_live(self, host: str) -> None:
        stream = self._live.pop(host, None)
        if stream:
            stream.stop()
            flush = getattr(stream.detector, "flush", None)
            if callable(flush):
                flush()  # an event still open when the stream stops is closed and logged

    def stop_all(self) -> None:
        for host in list(self._live):
            self.stop_live(host)

    def live_channels(self, device: Device) -> set[str]:
        """Channels the live stream of this device has delivered so far (empty before any data)."""
        stream = self._live.get(device.host)
        return set(stream.buffer.channels()) if stream else set()
