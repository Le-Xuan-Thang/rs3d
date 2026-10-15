"""Process-wide app state shared by all pages (one laptop, one user)."""

from __future__ import annotations

import tomllib

import tomli_w

from rs3d.core.devices import DeviceRegistry, Passwords
from rs3d.core.live import LiveStream
from rs3d.core.models import Check, Device
from rs3d.core.paths import AppPaths
from rs3d.core.seedlink import SeedLinkSource
from rs3d.core.shell import Shell
from rs3d.core.status import run_checks
from rs3d.core.store import Store

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


class AppState:
    def __init__(self, paths: AppPaths, passwords: Passwords | None = None) -> None:
        self.paths = paths.ensure()
        self.registry = DeviceRegistry(paths.config)
        self.passwords = passwords or Passwords()
        self.store = Store(paths.sds)
        self._settings_path = paths.root / "settings.toml"
        settings = tomllib.loads(self._settings_path.read_text()) if self._settings_path.exists() else {}
        self.use_local_time: bool = bool(settings.get("use_local_time", False))
        self.data_prefs: dict = _clean_prefs(settings.get("data_prefs", {}))
        devices = self.registry.load()
        self.current_host: str | None = settings.get("current_host") or (devices[0].host if devices else None)
        self._live: dict[str, LiveStream] = {}

    # ---------------------------------------------------------------- settings
    def save_settings(self) -> None:
        data: dict = {"use_local_time": self.use_local_time,
                      "data_prefs": {k: v for k, v in self.data_prefs.items() if v is not None}}
        if self.current_host:
            data["current_host"] = self.current_host
        self._settings_path.write_text(tomli_w.dumps(data))

    def set_use_local_time(self, value: bool) -> None:
        self.use_local_time = value
        self.save_settings()

    def set_data_prefs(self, **changes) -> None:
        self.data_prefs = _clean_prefs({**self.data_prefs, **changes})
        self.save_settings()

    # ---------------------------------------------------------------- devices
    def devices(self) -> list[Device]:
        return self.registry.load()

    def current(self) -> Device | None:
        devices = self.devices()
        return next((d for d in devices if d.host == self.current_host), devices[0] if devices else None)

    def select(self, host: str) -> None:
        self.current_host = host
        self.save_settings()

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
                                                       device.station, CHANNELS))
            self._live[device.host] = stream
        stream.start()
        return stream

    def stop_live(self, host: str) -> None:
        stream = self._live.pop(host, None)
        if stream:
            stream.stop()

    def stop_all(self) -> None:
        for host in list(self._live):
            self.stop_live(host)
