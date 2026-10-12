"""Saved devices (config.toml, no secrets) and SSH passwords (OS keyring)."""

from __future__ import annotations

import tomllib
from dataclasses import asdict
from pathlib import Path
from typing import Any

import tomli_w

from rs3d.core.models import Device

KEYRING_SERVICE = "rs3d"
DEFAULT_PASSWORD = "shakeme"


class DeviceRegistry:
    """Devices are stored as [[device]] tables in config.toml, keyed by host."""

    def __init__(self, config_path: Path) -> None:
        self.path = Path(config_path)

    def load(self) -> list[Device]:
        if not self.path.exists():
            return []
        data = tomllib.loads(self.path.read_text(encoding="utf-8"))
        devices = []
        for row in data.get("device", []):
            if row.get("key_path"):
                row["key_path"] = Path(row["key_path"])
            devices.append(Device(**row))
        return devices

    def save(self, devices: list[Device]) -> None:
        rows: list[dict[str, Any]] = []
        for d in devices:
            row = asdict(d)
            if row["key_path"] is None:
                del row["key_path"]  # TOML has no null
            else:
                row["key_path"] = str(row["key_path"])
            rows.append(row)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(tomli_w.dumps({"device": rows}), encoding="utf-8")

    def upsert(self, device: Device) -> list[Device]:
        devices = [d for d in self.load() if d.host != device.host] + [device]
        self.save(devices)
        return devices

    def remove(self, host: str) -> list[Device]:
        devices = [d for d in self.load() if d.host != host]
        self.save(devices)
        return devices

    def get(self, host: str) -> Device | None:
        return next((d for d in self.load() if d.host == host), None)


class Passwords:
    """SSH passwords in the OS keyring, with a per-session fallback when there is none.

    `backend` is any object with get_password/set_password/delete_password(service, user[, pw]),
    normally the `keyring` module itself.
    """

    def __init__(self, backend: Any = None) -> None:
        if backend is None:
            import keyring as backend
        self._backend = backend
        self._session: dict[str, str] = {}
        self.persistent = True

    def get(self, host: str) -> str | None:
        if host in self._session:
            return self._session[host]
        try:
            return self._backend.get_password(KEYRING_SERVICE, host)
        except Exception:
            self.persistent = False
            return None

    def set(self, host: str, password: str) -> None:
        try:
            self._backend.set_password(KEYRING_SERVICE, host, password)
            self._session.pop(host, None)
        except Exception:
            self.persistent = False
            self._session[host] = password

    def delete(self, host: str) -> None:
        self._session.pop(host, None)
        try:
            self._backend.delete_password(KEYRING_SERVICE, host)
        except Exception:
            pass

    def get_or_default(self, host: str) -> str:
        return self.get(host) or DEFAULT_PASSWORD
