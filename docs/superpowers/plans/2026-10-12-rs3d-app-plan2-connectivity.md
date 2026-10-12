# RS3D App – Plan 2: Device Connectivity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add everything that talks to the laptop network and to the Shake: saved devices and passwords, the laptop link-local check and [Set IP] commands, SeedLink probing and discovery, SSH, the Status checks, archive download, live streaming and the instrument response.

**Architecture:** New modules in `rs3d-app/src/rs3d/core/`, still with no UI code. Every network dependency is injectable (probe function, shell factory, SFTP object, source factory, fetch function), so unit tests run with fakes and with output captured from the real Shake AM.R77A7. A separate `tests/device/` suite runs against a real Shake only when asked (`-m device`). Spec: `docs/superpowers/specs/2026-10-12-rs3d-app-design.md` (sections 4, 5.2, 5.3, 5.6, 6, 7, 11).

**Tech Stack:** Python ≥ 3.11, uv, ObsPy 1.5.1 (SeedLink, FDSN), paramiko (SSH/SFTP), keyring, platformdirs, psutil, tomli-w, pytest.

**This is plan 2 of 3.** Plan 1 (core data layer) is merged. Plan 3 builds the NiceGUI interface on top of these modules.

---

## Context for the engineer

- The Shake is reached over an Ethernet cable with link-local addresses (`169.254.0.0/16`). Our Shake: `169.254.221.62`, mDNS name `rs.local`, SeedLink on TCP 18000, SSH user `myshake`.
- **SeedLink** is the real-time protocol. ObsPy's `EasySeedLinkClient` is used, but `create_client()` crashes in ObsPy 1.5.1 because it connects before a timeout can be set; we always build the client with `autoconnect=False`, set `conn.timeout`, then `connect()`. ObsPy reconnects internally inside `run()`; we shorten its timers (`conn.netto`, `conn.netdly`) and stop it with `conn.terminate()`.
- **The Shake's own archive** is an SDS tree at `/opt/data/archive/<YEAR>/<NET>/<STA>/<CHA>.D/<NET>.<STA>.<LOC>.<CHA>.D.<YEAR>.<DOY>`; it keeps 7 days (`config.json → other.archkeep`). Today's file keeps growing, so it is always re-downloaded.
- **Status over SSH** runs one shell script that prints sections, each introduced by a line `@@name`. `config.json` on the Shake has no trailing newline, so every marker is printed after a `\n`.
- Shake facts used by checks: `config.json → dataSharing.enabled` (Data Forwarding), marker file `/opt/settings/user/.pwchanged` (password changed), `ntpq -pn` line starting with `*` (selected time source; offset in ms is column 9).
- **Response** (counts → m/s) comes from the Raspberry Shake FDSN service, ObsPy client name `RASPISHAKE`, cached as StationXML.
- Never write to the Shake in v1. The only system change the app makes is [Set IP] on the laptop.
- Test fixtures `tests/data/seedlink_streams.xml` and `tests/data/shake_status.txt` were captured from AM.R77A7 on 2026-10-12 (e-mail address replaced).

## File structure

```
rs3d-app/
├── pyproject.toml                     # + paramiko, keyring, platformdirs, psutil, tomli-w
├── src/rs3d/core/
│   ├── paths.py                       # AppPaths: data folder per OS
│   ├── devices.py                     # DeviceRegistry (config.toml), Passwords (keyring)
│   ├── netcheck.py                    # laptop 169.254 check, [Set IP] commands per OS
│   ├── seedlink.py                    # StationInfo, parse_streams, probe, SeedLinkSource
│   ├── discovery.py                   # rs*.local + neighbour table → probe → Found
│   ├── shell.py                       # Shell (paramiko) + ShellError kinds
│   ├── response.py                    # get_inventory / cached_inventory (FDSN RASPISHAKE)
│   ├── status.py                      # SHAKE_SCRIPT, individual checks, run_checks
│   ├── archive.py                     # list/sync the Shake archive over SFTP
│   └── live.py                        # RingBuffer, LiveStream (reconnect with backoff)
└── tests/
    ├── data/seedlink_streams.xml      # real INFO STREAMS answer
    ├── data/shake_status.txt          # real output of SHAKE_SCRIPT
    ├── core/test_devices.py
    ├── core/test_netcheck.py
    ├── core/test_seedlink_discovery.py
    ├── core/test_response_shell.py
    ├── core/test_status.py
    ├── core/test_archive.py
    ├── core/test_live.py
    └── device/__init__.py, device/test_real_shake.py   # -m device only
```

All commands run from `rs3d-app/` unless stated otherwise.

---

### Task 1: Dependencies, app paths, saved devices and passwords

**Files:**
- Modify: `rs3d-app/pyproject.toml` (dependencies)
- Create: `rs3d-app/src/rs3d/core/paths.py`
- Create: `rs3d-app/src/rs3d/core/devices.py`
- Test: `rs3d-app/tests/core/test_devices.py`

- [ ] **Step 1: Add the dependencies**

Run: `uv add "paramiko>=4" "keyring>=25" "platformdirs>=4" "psutil>=6" "tomli-w>=1.2"`

Expected: the `dependencies` list in `pyproject.toml` becomes:

```toml
dependencies = [
    "obspy>=1.5.1",
    "matplotlib>=3.8",
    "paramiko>=4",
    "keyring>=25",
    "platformdirs>=4",
    "psutil>=6",
    "tomli-w>=1.2",
]
```

- [ ] **Step 2: Write the failing tests** – `rs3d-app/tests/core/test_devices.py`:

```python
from pathlib import Path

from rs3d.core.devices import DEFAULT_PASSWORD, KEYRING_SERVICE, DeviceRegistry, Passwords
from rs3d.core.models import Device
from rs3d.core.paths import ENV_DATA_DIR, AppPaths


class MemoryKeyring:
    def __init__(self):
        self.data = {}

    def get_password(self, service, user):
        return self.data.get((service, user))

    def set_password(self, service, user, password):
        self.data[(service, user)] = password

    def delete_password(self, service, user):
        self.data.pop((service, user), None)


class BrokenKeyring:
    def get_password(self, service, user):
        raise RuntimeError("no keyring backend")

    set_password = delete_password = get_password


def test_registry_roundtrip(tmp_path):
    reg = DeviceRegistry(tmp_path / "config.toml")
    assert reg.load() == []
    a = Device(name="R77A7", host="169.254.221.62", station="R77A7")
    b = Device(name="lab", host="169.254.10.10", key_path=Path("/keys/id_ed25519"))
    reg.save([a, b])
    assert reg.load() == [a, b]
    assert "password" not in (tmp_path / "config.toml").read_text()


def test_registry_upsert_replaces_same_host(tmp_path):
    reg = DeviceRegistry(tmp_path / "config.toml")
    reg.upsert(Device(name="old", host="169.254.221.62"))
    reg.upsert(Device(name="new", host="169.254.221.62"))
    assert [d.name for d in reg.load()] == ["new"]
    assert reg.get("169.254.221.62").name == "new"
    reg.remove("169.254.221.62")
    assert reg.load() == []


def test_passwords_use_keyring():
    ring = MemoryKeyring()
    pw = Passwords(ring)
    assert pw.get_or_default("h") == DEFAULT_PASSWORD
    pw.set("h", "s3cret")
    assert ring.data[(KEYRING_SERVICE, "h")] == "s3cret"
    assert pw.get("h") == "s3cret" and pw.persistent
    pw.delete("h")
    assert pw.get("h") is None


def test_passwords_fall_back_to_session_without_keyring():
    pw = Passwords(BrokenKeyring())
    pw.set("h", "s3cret")
    assert pw.get("h") == "s3cret"
    assert pw.persistent is False


def test_app_paths_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path))
    p = AppPaths.default().ensure()
    assert p.root == tmp_path
    assert p.config == tmp_path / "config.toml"
    assert all(d.is_dir() for d in (p.sds, p.response, p.logs))
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/core/test_devices.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rs3d.core.devices'`

- [ ] **Step 4: Implement** – `rs3d-app/src/rs3d/core/paths.py`:

```python
"""Where the app keeps its files on each OS."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir

ENV_DATA_DIR = "RS3D_DATA_DIR"


@dataclass(frozen=True)
class AppPaths:
    root: Path

    @classmethod
    def default(cls) -> "AppPaths":
        """$RS3D_DATA_DIR if set, else the OS data folder (e.g. %LOCALAPPDATA%\\rs3d)."""
        override = os.environ.get(ENV_DATA_DIR)
        return cls(Path(override) if override else Path(user_data_dir("rs3d", appauthor=False)))

    @property
    def config(self) -> Path:
        return self.root / "config.toml"

    @property
    def sds(self) -> Path:
        return self.root / "sds"

    @property
    def response(self) -> Path:
        return self.root / "response"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def known_hosts(self) -> Path:
        return self.root / "known_hosts"

    def ensure(self) -> "AppPaths":
        for d in (self.root, self.sds, self.response, self.logs):
            d.mkdir(parents=True, exist_ok=True)
        return self
```

`rs3d-app/src/rs3d/core/devices.py`:

```python
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
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/core/test_devices.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add rs3d-app/pyproject.toml rs3d-app/uv.lock rs3d-app/src/rs3d/core/paths.py rs3d-app/src/rs3d/core/devices.py rs3d-app/tests/core/test_devices.py
git commit -m "feat(rs3d-app): app paths, saved devices and keyring passwords"
```

---

### Task 2: Laptop link-local check and [Set IP]

**Files:**
- Create: `rs3d-app/src/rs3d/core/netcheck.py`
- Test: `rs3d-app/tests/core/test_netcheck.py`

[Set IP] lets the OS choose a free link-local address (spec 5.6): Linux enables `ipv4.link-local` on the NetworkManager connection; Windows and macOS switch the interface to DHCP, which self-assigns 169.254.x.x when no DHCP server answers. Commands are wrapped so the OS shows its own privilege prompt. Tests never execute them: `run` is injected.

- [ ] **Step 1: Write the failing tests** – `rs3d-app/tests/core/test_netcheck.py`:

```python
import subprocess

import pytest

from rs3d.core.models import Level
from rs3d.core.netcheck import (
    Interface, check_laptop_ip, elevated, interfaces, link_local, parse_macos_hardware_ports,
    parse_nmcli_connections, set_ip, set_ip_commands,
)


def test_link_local_only_counts_up_interfaces():
    ifaces = [
        Interface("enp2s0", True, ("192.168.204.163", "169.254.8.11")),
        Interface("eth1", False, ("169.254.9.9",)),
        Interface("wlp3s0", True, ("10.10.177.250",)),
    ]
    assert link_local(ifaces) == [("enp2s0", "169.254.8.11")]


def test_check_laptop_ip_ok_and_error():
    ok = check_laptop_ip([Interface("enp2s0", True, ("169.254.8.11",))])
    assert ok.level is Level.OK and ok.value == "169.254.8.11 (enp2s0)"
    bad = check_laptop_ip([Interface("enp2s0", True, ("192.168.204.163",))])
    assert bad.level is Level.ERROR and bad.action == "set_ip"


def test_interfaces_reads_this_machine():
    assert any(i.name for i in interfaces())


def test_parse_nmcli_connections_with_escaped_colon():
    text = "UPTEC:wlp3s0\nnetplan-enp2s0:enp2s0\nmy\\:lab:eth1\neduroam:\n"
    assert parse_nmcli_connections(text) == {
        "wlp3s0": "UPTEC", "enp2s0": "netplan-enp2s0", "eth1": "my:lab"}


def test_parse_macos_hardware_ports():
    text = ("Hardware Port: Wi-Fi\nDevice: en0\nEthernet Address: aa\n\n"
            "Hardware Port: USB 10/100/1000 LAN\nDevice: en7\nEthernet Address: bb\n")
    assert parse_macos_hardware_ports(text) == {"en0": "Wi-Fi", "en7": "USB 10/100/1000 LAN"}


def test_set_ip_commands_per_os():
    assert set_ip_commands("Linux", "enp2s0", "netplan-enp2s0") == [
        ["nmcli", "connection", "modify", "netplan-enp2s0", "ipv4.link-local", "enabled"],
        ["nmcli", "connection", "up", "netplan-enp2s0"]]
    assert set_ip_commands("Windows", "Ethernet", "Ethernet") == [
        ["netsh", "interface", "ipv4", "set", "address", "name=Ethernet", "source=dhcp"]]
    assert set_ip_commands("Darwin", "en7", "USB LAN") == [["networksetup", "-setdhcp", "USB LAN"]]
    with pytest.raises(ValueError):
        set_ip_commands("Plan9", "x", "x")


def test_elevated_wrappers():
    assert elevated("Linux", ["nmcli", "x"]) == ["nmcli", "x"]
    win = elevated("Windows", ["netsh", "interface", "name=Ethernet 2"])
    assert win[0] == "powershell" and "-Verb RunAs" in win[-1] and '"name=Ethernet 2"' in win[-1]
    mac = elevated("Darwin", ["networksetup", "-setdhcp", "USB LAN"])
    assert mac[:2] == ["osascript", "-e"] and "with administrator privileges" in mac[2]
    assert "'USB LAN'" in mac[2]


def test_set_ip_records_commands_without_running_them():
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        out = "netplan-enp2s0:enp2s0\n" if cmd[:2] == ["nmcli", "-t"] else ""
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    ran = set_ip("enp2s0", system="Linux", run=fake_run)
    assert ran == [
        ["nmcli", "connection", "modify", "netplan-enp2s0", "ipv4.link-local", "enabled"],
        ["nmcli", "connection", "up", "netplan-enp2s0"]]
    assert calls[0][:2] == ["nmcli", "-t"]


def test_set_ip_unknown_interface():
    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout="UPTEC:wlp3s0\n", stderr="")

    with pytest.raises(LookupError):
        set_ip("enp9s9", system="Linux", run=fake_run)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/core/test_netcheck.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rs3d.core.netcheck'`

- [ ] **Step 3: Implement** – `rs3d-app/src/rs3d/core/netcheck.py`:

```python
"""Does the laptop have a link-local (169.254.x.x) address, and how to give it one."""

from __future__ import annotations

import ipaddress
import platform
import shlex
import subprocess
from dataclasses import dataclass

from rs3d.core.models import Check, Level

LINK_LOCAL = ipaddress.ip_network("169.254.0.0/16")


@dataclass(frozen=True)
class Interface:
    name: str
    is_up: bool
    ipv4: tuple[str, ...]


def interfaces() -> list[Interface]:
    import psutil

    stats = psutil.net_if_stats()
    result = []
    for name, addrs in psutil.net_if_addrs().items():
        v4 = tuple(a.address for a in addrs if a.family.name == "AF_INET")
        result.append(Interface(name, bool(stats.get(name) and stats[name].isup), v4))
    return result


def link_local(ifaces: list[Interface]) -> list[tuple[str, str]]:
    return [(i.name, ip) for i in ifaces if i.is_up for ip in i.ipv4
            if ipaddress.ip_address(ip) in LINK_LOCAL]


def check_laptop_ip(ifaces: list[Interface] | None = None) -> Check:
    found = link_local(interfaces() if ifaces is None else ifaces)
    if found:
        name, ip = found[0]
        return Check("laptop_ip", Level.OK, f"{ip} ({name})", "laptop_ip")
    return Check("laptop_ip", Level.ERROR, "no 169.254.x.x address", "laptop_ip", action="set_ip")


# ---------------------------------------------------------------- [Set IP]

def parse_nmcli_connections(text: str) -> dict[str, str]:
    """`nmcli -t -f NAME,DEVICE connection show` -> {device: connection}. Handles escaped colons."""
    result = {}
    for line in text.splitlines():
        parts, cur, i = [], "", 0
        while i < len(line):
            if line[i] == "\\" and i + 1 < len(line):
                cur += line[i + 1]
                i += 2
                continue
            if line[i] == ":":
                parts.append(cur)
                cur = ""
            else:
                cur += line[i]
            i += 1
        parts.append(cur)
        if len(parts) == 2 and parts[1]:
            result[parts[1]] = parts[0]
    return result


def parse_macos_hardware_ports(text: str) -> dict[str, str]:
    """`networksetup -listallhardwareports` -> {device: service name}."""
    result, port = {}, None
    for line in text.splitlines():
        if line.startswith("Hardware Port: "):
            port = line.removeprefix("Hardware Port: ").strip()
        elif line.startswith("Device: ") and port:
            result[line.removeprefix("Device: ").strip()] = port
            port = None
    return result


def set_ip_commands(system: str, iface: str, target: str) -> list[list[str]]:
    """Commands that let the OS pick a free link-local address on `iface`.

    target: Linux NetworkManager connection name, macOS network service name,
    Windows interface name (same as iface).
    """
    if system == "Linux":
        return [["nmcli", "connection", "modify", target, "ipv4.link-local", "enabled"],
                ["nmcli", "connection", "up", target]]
    if system == "Windows":
        # With DHCP and no DHCP server, Windows assigns 169.254.x.x itself (APIPA).
        return [["netsh", "interface", "ipv4", "set", "address", f"name={target}", "source=dhcp"]]
    if system == "Darwin":
        # Same on macOS: DHCP without a server gives a self-assigned 169.254.x.x.
        return [["networksetup", "-setdhcp", target]]
    raise ValueError(f"unsupported OS: {system}")


def resolve_target(system: str, iface: str, run=subprocess.run) -> str:
    if system == "Linux":
        out = run(["nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show"],
                  capture_output=True, text=True, check=True).stdout
        conns = parse_nmcli_connections(out)
        if iface not in conns:
            raise LookupError(f"no NetworkManager connection for {iface}")
        return conns[iface]
    if system == "Darwin":
        out = run(["networksetup", "-listallhardwareports"],
                  capture_output=True, text=True, check=True).stdout
        ports = parse_macos_hardware_ports(out)
        if iface not in ports:
            raise LookupError(f"no network service for {iface}")
        return ports[iface]
    return iface


def elevated(system: str, argv: list[str]) -> list[str]:
    """Wrap a command so the OS shows its own privilege prompt."""
    if system == "Linux":
        return argv  # nmcli asks polkit itself
    if system == "Windows":
        args = " ".join(f'"{a}"' if " " in a else a for a in argv[1:])
        return ["powershell", "-NoProfile", "-Command",
                f"Start-Process -FilePath {argv[0]} -ArgumentList '{args}' -Verb RunAs -Wait -WindowStyle Hidden"]
    if system == "Darwin":
        script = shlex.join(argv).replace("\\", "\\\\").replace('"', '\\"')
        return ["osascript", "-e", f'do shell script "{script}" with administrator privileges']
    raise ValueError(f"unsupported OS: {system}")


def set_ip(iface: str, system: str | None = None, run=subprocess.run) -> list[list[str]]:
    """Run the [Set IP] commands with an OS privilege prompt. Returns what was run."""
    system = system or platform.system()
    target = resolve_target(system, iface, run)
    ran = []
    for argv in set_ip_commands(system, iface, target):
        cmd = elevated(system, argv)
        run(cmd, capture_output=True, text=True, check=True)
        ran.append(cmd)
    return ran
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/core/test_netcheck.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add rs3d-app/src/rs3d/core/netcheck.py rs3d-app/tests/core/test_netcheck.py
git commit -m "feat(rs3d-app): laptop link-local check and Set IP commands"
```

---

### Task 3: SeedLink probe and device discovery

**Files:**
- Create: `rs3d-app/tests/data/seedlink_streams.xml`
- Create: `rs3d-app/src/rs3d/core/seedlink.py`
- Create: `rs3d-app/src/rs3d/core/discovery.py`
- Test: `rs3d-app/tests/core/test_seedlink_discovery.py`

Discovery (spec 11): resolve `rs.local`, `rs-2.local` … `rs-9.local` with the OS resolver (giving up after 2.5 s), add link-local entries of the OS neighbour table, keep only `169.254.0.0/16` (manual entries always kept), probe each candidate's SeedLink port in parallel, and keep one result per station.

- [ ] **Step 1: Create the fixture** – `rs3d-app/tests/data/seedlink_streams.xml`:

```xml
<?xml version="1.0"?>
<seedlink software="SeedLink v3.1 (2009.075)" organization="OSOP" started="2026/10/12 17:15:53.3461">
<station name="R77A7" network="AM" description="AM station" begin_seq="000000" end_seq="0003FD" stream_check="enabled">
<stream location="00" seedname="EHE" type="D" begin_time="2026/10/12 17:15:54.9400" end_time="2026/10/12 17:24:25.9300" begin_recno="000000" end_recno="000342" gap_check="disabled" gap_treshold="500000"/>
<stream location="00" seedname="EHN" type="D" begin_time="2026/10/12 17:15:54.9400" end_time="2026/10/12 17:24:24.9600" begin_recno="000000" end_recno="000393" gap_check="disabled" gap_treshold="500000"/>
<stream location="00" seedname="EHZ" type="D" begin_time="2026/10/12 17:15:54.9400" end_time="2026/10/12 17:24:23.9600" begin_recno="000000" end_recno="000286" gap_check="disabled" gap_treshold="500000"/>
</station>
</seedlink>
```

- [ ] **Step 2: Write the failing tests** – `rs3d-app/tests/core/test_seedlink_discovery.py`:

```python
import time
from pathlib import Path

from rs3d.core.discovery import Found, candidates, discover, parse_neighbours, resolve_names
from rs3d.core.seedlink import StationInfo, parse_streams

DATA = Path(__file__).parent.parent / "data"
STATION = StationInfo("AM", "R77A7", "00", ("EHZ", "EHN", "EHE"))


def test_parse_real_streams_xml():
    assert parse_streams((DATA / "seedlink_streams.xml").read_text()) == [STATION]


def test_parse_neighbours_linux_and_arp():
    linux = ("169.254.221.62 dev enp2s0 lladdr b8:27:eb:09:77:a7 REACHABLE\n"
             "192.168.204.254 dev enp2s0 FAILED\n169.254.169.254 dev enp2s0  FAILED\n")
    assert parse_neighbours(linux) == ["169.254.221.62"]
    windows = ("Interface: 169.254.12.3 --- 0x5\n"
               "  169.254.221.62        b8-27-eb-09-77-a7     dynamic\n")
    assert "169.254.221.62" in parse_neighbours(windows)
    mac = "? (169.254.221.62) at b8:27:eb:9:77:a7 on en7 [ethernet]\n? (169.254.1.1) at (incomplete) on en7\n"
    assert parse_neighbours(mac) == ["169.254.221.62"]


def test_candidates_keep_link_local_unique_manual_first():
    got = candidates(["169.254.221.62", "10.10.178.153"], ["169.254.221.62", "169.254.9.9"], ["192.168.1.5"])
    assert got == ["192.168.1.5", "169.254.221.62", "169.254.9.9"]


def test_resolve_names_ignores_slow_answers():
    def resolver(name):
        if name == "rs.local":
            return ["169.254.221.62"]
        time.sleep(3)
        return ["169.254.1.1"]

    t = time.monotonic()
    assert resolve_names(("rs.local", "rs-2.local"), resolver, timeout=0.5) == ["169.254.221.62"]
    assert time.monotonic() - t < 2


def test_discover_dedupes_by_station_and_drops_non_shakes():
    def fake_probe(host, port, timeout):
        if host == "169.254.9.9":
            raise ConnectionRefusedError()
        return STATION

    found = discover(names_ips=["169.254.221.62"], neighbour_ips=["169.254.9.9", "169.254.221.62"],
                     manual=["169.254.221.62"], probe_fn=fake_probe)
    assert found == [Found("169.254.221.62", STATION)]


def test_discover_nothing():
    assert discover(names_ips=[], neighbour_ips=[]) == []
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/core/test_seedlink_discovery.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rs3d.core.discovery'`

- [ ] **Step 4: Implement** – `rs3d-app/src/rs3d/core/seedlink.py`:

```python
"""Talk to a Shake's SeedLink server (TCP 18000): identify it and stream data."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Callable

from obspy import Trace
from obspy.clients.seedlink.easyseedlink import EasySeedLinkClient


@dataclass(frozen=True)
class StationInfo:
    network: str
    station: str
    location: str
    channels: tuple[str, ...]


def _component_order(channel: str) -> tuple[int, str]:
    return ({"Z": 0, "N": 1, "E": 2}.get(channel[-1:], 9), channel)


def parse_streams(xml_text: str) -> list[StationInfo]:
    """Parse the XML answer to SeedLink `INFO STREAMS`."""
    root = ET.fromstring(xml_text)
    result = []
    for st in root.iter("station"):
        streams = [s for s in st.iter("stream") if s.get("type", "D") == "D"]
        locations = sorted({s.get("location", "") for s in streams})
        channels = tuple(sorted({s.get("seedname", "") for s in streams}, key=_component_order))
        result.append(StationInfo(st.get("network", ""), st.get("name", ""),
                                  locations[0] if locations else "", channels))
    return result


def _client(host: str, port: int, timeout: float) -> EasySeedLinkClient:
    # create_client() connects before a timeout can be set and crashes in ObsPy 1.5.1
    # ('<' not supported between float and NoneType), so connect manually.
    client = EasySeedLinkClient(f"{host}:{port}", autoconnect=False)
    client.conn.timeout = timeout
    client.connect()
    return client


def probe(host: str, port: int = 18000, timeout: float = 5.0) -> StationInfo:
    """Connect, ask which stations/streams exist, disconnect. Raises on failure."""
    client = _client(host, port, timeout)
    try:
        stations = parse_streams(client.get_info("STREAMS"))
    finally:
        client.close()
    if not stations:
        raise LookupError(f"{host}:{port} serves no station")
    return stations[0]


class SeedLinkSource:
    """Blocking stream of Traces from a Shake; `run(on_trace)` returns when the link drops."""

    def __init__(self, host: str, port: int, network: str, station: str,
                 channels: tuple[str, ...], timeout: float = 10.0) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.network, self.station, self.channels = network, station, channels
        self._client: EasySeedLinkClient | None = None

    def run(self, on_trace: Callable[[Trace], None]) -> None:
        client = _client(self.host, self.port, self.timeout)
        # ObsPy reconnects by itself inside run(); defaults (120 s idle, 30 s delay) are too slow for Live.
        client.conn.netto = int(self.timeout)
        client.conn.netdly = 2
        client.on_data = on_trace
        self._client = client
        for channel in self.channels:
            client.select_stream(self.network, self.station, channel)
        client.run()

    def close(self) -> None:
        """Ask the collect loop to finish; run() then returns instead of reconnecting."""
        if self._client is not None:
            try:
                self._client.conn.terminate()
            except Exception:
                pass
```

`rs3d-app/src/rs3d/core/discovery.py`:

```python
"""Find Shakes on the Ethernet link: rs*.local names + OS neighbour table, confirmed by SeedLink."""

from __future__ import annotations

import ipaddress
import platform
import re
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Callable

from rs3d.core.netcheck import LINK_LOCAL
from rs3d.core.seedlink import StationInfo, probe

MDNS_NAMES = ("rs.local",) + tuple(f"rs-{i}.local" for i in range(2, 10))
_IPV4 = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")


@dataclass(frozen=True)
class Found:
    host: str
    info: StationInfo


def is_link_local(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in LINK_LOCAL
    except ValueError:
        return False


def resolve_names(names: tuple[str, ...] = MDNS_NAMES, resolver: Callable[[str], list[str]] | None = None,
                  timeout: float = 2.5) -> list[str]:
    """Resolve names in parallel; names that have not answered after `timeout` are ignored."""
    def default(name: str) -> list[str]:
        try:
            return [ai[4][0] for ai in socket.getaddrinfo(name, None, socket.AF_INET)]
        except OSError:
            return []

    resolver = resolver or default
    pool = ThreadPoolExecutor(max_workers=len(names))
    futures = [pool.submit(resolver, n) for n in names]
    done, _ = wait(futures, timeout=timeout)
    pool.shutdown(wait=False, cancel_futures=True)  # unanswered lookups finish in the background
    return [ip for f in futures if f in done for ip in f.result()]


def parse_neighbours(text: str) -> list[str]:
    """IPv4 addresses from `ip -4 neigh` (Linux) or `arp -a` (Windows/macOS); failed entries dropped."""
    ips = []
    for line in text.splitlines():
        if "FAILED" in line or "incomplete" in line:
            continue
        m = _IPV4.search(line)
        if m:
            ips.append(m[1])
    return ips


def neighbour_table(run=subprocess.run) -> list[str]:
    cmd = ["ip", "-4", "neigh"] if platform.system() == "Linux" else ["arp", "-a"]
    try:
        return parse_neighbours(run(cmd, capture_output=True, text=True, timeout=5).stdout)
    except (OSError, subprocess.SubprocessError):
        return []


def candidates(names_ips: list[str], neighbour_ips: list[str], manual: list[str] = ()) -> list[str]:
    """Unique link-local addresses, manual entries first (manual entries kept even if not link-local)."""
    seen, out = set(), []
    for ip in list(manual) + [i for i in names_ips + neighbour_ips if is_link_local(i)]:
        if ip not in seen:
            seen.add(ip)
            out.append(ip)
    return out


def discover(manual: list[str] = (), *, port: int = 18000, timeout: float = 3.0,
             probe_fn: Callable[..., StationInfo] = probe,
             names_ips: list[str] | None = None, neighbour_ips: list[str] | None = None) -> list[Found]:
    """Probe every candidate in parallel; keep the ones that answer SeedLink. One entry per station."""
    hosts = candidates(resolve_names() if names_ips is None else names_ips,
                       neighbour_table() if neighbour_ips is None else neighbour_ips, list(manual))

    def try_host(host: str) -> Found | None:
        try:
            return Found(host, probe_fn(host, port, timeout))
        except Exception:
            return None

    if not hosts:
        return []
    with ThreadPoolExecutor(max_workers=min(16, len(hosts))) as pool:
        found = [f for f in pool.map(try_host, hosts) if f is not None]
    by_station: dict[tuple[str, str], Found] = {}
    for f in found:
        by_station.setdefault((f.info.network, f.info.station), f)
    return list(by_station.values())
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/core/test_seedlink_discovery.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add rs3d-app/tests/data/seedlink_streams.xml rs3d-app/src/rs3d/core/seedlink.py rs3d-app/src/rs3d/core/discovery.py rs3d-app/tests/core/test_seedlink_discovery.py
git commit -m "feat(rs3d-app): SeedLink probe and Shake discovery"
```

---

### Task 4: SSH shell and instrument response

**Files:**
- Create: `rs3d-app/src/rs3d/core/shell.py`
- Create: `rs3d-app/src/rs3d/core/response.py`
- Test: `rs3d-app/tests/core/test_response_shell.py`

`Shell` trusts a Shake's host key on first use and stores it in the app's own `known_hosts`. Errors are reduced to four kinds (`auth`, `unreachable`, `hostkey`, `command`) that map to help texts in Plan 3.

- [ ] **Step 1: Write the failing tests** – `rs3d-app/tests/core/test_response_shell.py`:

```python
import socket

import paramiko
import pytest

from rs3d.core.response import cache_path, cached_inventory, get_inventory
from rs3d.core.shell import ShellError, classify


def test_response_downloads_once_then_uses_cache(tmp_path, inventory):
    calls = []

    def fetch(net, sta):
        calls.append((net, sta))
        return inventory

    assert cached_inventory(tmp_path, "AM", "R77A7") is None
    get_inventory(tmp_path, "AM", "R77A7", fetch=fetch)
    inv = get_inventory(tmp_path, "AM", "R77A7", fetch=fetch)
    assert calls == [("AM", "R77A7")]
    assert cache_path(tmp_path, "AM", "R77A7").exists()
    assert inv[0][0].code == "R77A7"
    assert cached_inventory(tmp_path, "AM", "R77A7") is not None


def test_response_refresh_downloads_again(tmp_path, inventory):
    calls = []
    fetch = lambda n, s: calls.append(1) or inventory
    get_inventory(tmp_path, "AM", "R77A7", fetch=fetch)
    get_inventory(tmp_path, "AM", "R77A7", fetch=fetch, refresh=True)
    assert len(calls) == 2


@pytest.mark.parametrize("exc, kind", [
    (paramiko.AuthenticationException("x"), "auth"),
    (socket.timeout("timed out"), "unreachable"),
    (ConnectionRefusedError("refused"), "unreachable"),
    (ShellError("command", "boom"), "command"),
])
def test_classify(exc, kind):
    assert classify(exc).kind == kind
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/core/test_response_shell.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rs3d.core.response'`

- [ ] **Step 3: Implement** – `rs3d-app/src/rs3d/core/shell.py`:

```python
"""SSH/SFTP session to a Shake (paramiko). Read-only use in v1."""

from __future__ import annotations

import socket
from pathlib import Path

import paramiko

from rs3d.core.models import Device


class ShellError(Exception):
    """kind: auth | unreachable | hostkey | command"""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def classify(exc: BaseException) -> ShellError:
    if isinstance(exc, ShellError):
        return exc
    if isinstance(exc, paramiko.AuthenticationException):
        return ShellError("auth", "wrong user name, password or key")
    if isinstance(exc, paramiko.BadHostKeyException):
        return ShellError("hostkey", "the Shake's host key changed")
    if isinstance(exc, (socket.timeout, TimeoutError, paramiko.ssh_exception.NoValidConnectionsError,
                        ConnectionError, OSError)):
        return ShellError("unreachable", str(exc) or "cannot reach the Shake on port 22")
    return ShellError("unreachable", f"{type(exc).__name__}: {exc}")


class Shell:
    """Use as a context manager. Host keys are trusted on first use and kept in known_hosts."""

    def __init__(self, device: Device, password: str | None, known_hosts: Path, timeout: float = 8.0) -> None:
        self.device, self.password, self.known_hosts, self.timeout = device, password, Path(known_hosts), timeout
        self._client: paramiko.SSHClient | None = None

    def __enter__(self) -> "Shell":
        client = paramiko.SSHClient()
        if self.known_hosts.exists():
            client.load_host_keys(str(self.known_hosts))
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                self.device.host, port=22, username=self.device.ssh_user, password=self.password,
                key_filename=str(self.device.key_path) if self.device.key_path else None,
                timeout=self.timeout, banner_timeout=self.timeout, auth_timeout=self.timeout,
            )
        except Exception as exc:
            client.close()
            raise classify(exc) from exc
        self.known_hosts.parent.mkdir(parents=True, exist_ok=True)
        client.save_host_keys(str(self.known_hosts))
        self._client = client
        return self

    def __exit__(self, *exc) -> None:
        if self._client is not None:
            self._client.close()

    def run(self, command: str, timeout: float = 20.0) -> str:
        assert self._client is not None, "use Shell as a context manager"
        try:
            _, stdout, stderr = self._client.exec_command(command, timeout=timeout)
            out = stdout.read().decode("utf-8", "replace")
            if stdout.channel.recv_exit_status() != 0:
                raise ShellError("command", stderr.read().decode("utf-8", "replace").strip() or out.strip())
            return out
        except ShellError:
            raise
        except Exception as exc:
            raise classify(exc) from exc

    def sftp(self) -> paramiko.SFTPClient:
        assert self._client is not None, "use Shell as a context manager"
        return self._client.open_sftp()
```

`rs3d-app/src/rs3d/core/response.py`:

```python
"""Instrument response (counts -> m/s), downloaded once from the Raspberry Shake FDSN service."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from obspy import Inventory, read_inventory


def cache_path(cache_dir: Path, network: str, station: str) -> Path:
    return Path(cache_dir) / f"{network}.{station}.xml"


def _fetch_from_fdsn(network: str, station: str) -> Inventory:
    from obspy.clients.fdsn import Client

    return Client("RASPISHAKE", timeout=30).get_stations(network=network, station=station, level="response")


def get_inventory(cache_dir: Path, network: str, station: str, *, refresh: bool = False,
                  fetch: Callable[[str, str], Inventory] = _fetch_from_fdsn) -> Inventory:
    """Cached StationXML if present, else download (needs Internet) and cache it."""
    path = cache_path(cache_dir, network, station)
    if path.exists() and not refresh:
        return read_inventory(str(path))
    inv = fetch(network, station)
    path.parent.mkdir(parents=True, exist_ok=True)
    inv.write(str(path), format="STATIONXML")
    return inv


def cached_inventory(cache_dir: Path, network: str, station: str) -> Inventory | None:
    """The cached response, or None. Never touches the network (for the UI's m/s toggle)."""
    path = cache_path(cache_dir, network, station)
    return read_inventory(str(path)) if path.exists() else None
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/core/test_response_shell.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add rs3d-app/src/rs3d/core/shell.py rs3d-app/src/rs3d/core/response.py rs3d-app/tests/core/test_response_shell.py
git commit -m "feat(rs3d-app): SSH shell and cached instrument response"
```

---

### Task 5: Status checks

**Files:**
- Create: `rs3d-app/tests/data/shake_status.txt`
- Create: `rs3d-app/src/rs3d/core/status.py`
- Test: `rs3d-app/tests/core/test_status.py`

Order and dependencies follow spec 5.2: a laptop IP error skips everything else; an SSH error skips the SSH-based checks but SeedLink and Channels still run. Unexpected output from the Shake turns one check into `ERROR / could not read` instead of breaking the page.

- [ ] **Step 1: Create the fixture** – `rs3d-app/tests/data/shake_status.txt` (exact content, including the blank lines):

```text

@@ntpq
     remote           refid      st t when poll reach   delay   offset  jitter
==============================================================================
 169.254.8.11    185.125.190.122  3 u   23   64    3    0.644    3.835   0.108
 127.127.28.0    .GPS.            0 l    -   16    0    0.000    0.000   0.000
 127.127.28.1    .PPS.            0 l    -   16    0    0.000    0.000   0.000
+91.209.16.78    194.117.47.44    3 u    4   64  377   10.906    0.982   2.072
+81.193.254.213  150.214.94.5     2 u   66   64  377   13.044   -0.355 237.016
*188.241.16.61   129.134.26.123   2 u   66   64  377   12.399    0.853 237.046

@@df
Filesystem       1-blocks       Used  Available Capacity Mounted on
/dev/root      7891935232 3219992576 4574498816      42% /

@@archive
/opt/data/archive/2024/AM/R77A7/EHZ.D/:

/opt/data/archive/2025/AM/R77A7/EHZ.D/:
AM.R77A7.00.EHZ.D.2025.268

/opt/data/archive/2026/AM/R77A7/EHZ.D/:
AM.R77A7.00.EHZ.D.2026.285

@@config
{
  "hwVersion": "V4",
  "geophoneType": "Factory",
  "network": {
    "static": false,
    "ipaddress": "",
    "gateway": "",
    "dns1": "",
    "dns2": "",
    "dns3": "",
    "ssid": "",
    "password": "",
    "wifi": true
  },
  "other": {
    "heliscaling": 0.5,
    "archkeep": 7
  },
  "dataSharing": {
    "enabled": false,
    "firstName": "NCREP",
    "lastName": "",
    "mailAddress": "user@example.org",
    "lat": 41.1499,
    "lon": -8.6152,
    "elevation": 104,
    "floor": 3,
    "totalFloors": 4,
    "licenseAgreed": true,
    "purpose": "Aftershock Studies"
  },
  "archivingEnabled": true,
  "ntpServers": [],
  "odfSerialPort": "",
  "helicorderEnabled": true,
  "streams": [
    {
      "name": "UDPSTREAM1",
      "host": "169.254.8.11",
      "port": "8888"
    }
  ],
  "boomFilter": 1,
  "enableStatic": false,
  "enableStaticWifi": false,
  "dnsServer": "193.137.55.20",
  "dnsServerWifi": "193.137.55.20"
}
@@pwchanged
yes

@@wlan
3: wlan0    inet 10.10.178.153/21 brd 10.10.183.255 scope global dynamic wlan0\       valid_lft 172159sec preferred_lft 172159sec

@@internet
ok
```

- [ ] **Step 2: Write the failing tests** – `rs3d-app/tests/core/test_status.py`:

```python
from datetime import date
from pathlib import Path

import pytest

from rs3d.core.models import Check, Device, Level
from rs3d.core.seedlink import StationInfo
from rs3d.core.shell import ShellError
from rs3d.core.status import (
    ORDER, SHAKE_SCRIPT, archive_check, clock_check, forwarding_check, parse_sections,
    password_check, remote_days, run_checks, storage_check, wifi_check,
)

DATA = Path(__file__).parent.parent / "data"
REAL = (DATA / "shake_status.txt").read_text()  # captured from AM.R77A7 on 2026-10-12
DEVICE = Device(name="R77A7", host="169.254.221.62", station="R77A7")
STATION = StationInfo("AM", "R77A7", "00", ("EHZ", "EHN", "EHE"))
TODAY = date(2026, 10, 12)


class FakeShell:
    def __init__(self, output=REAL, error=None):
        self.output, self.error = output, error

    def __enter__(self):
        if self.error:
            raise self.error
        return self

    def __exit__(self, *exc):
        return None

    def run(self, command):
        assert command == SHAKE_SCRIPT
        return self.output


def ok_ip():
    return Check("laptop_ip", Level.OK, "169.254.8.11 (enp2s0)", "laptop_ip")


def checks(**kw):
    args = dict(laptop_ip=ok_ip, probe_fn=lambda host, port: STATION,
                shell_factory=lambda dev, pw: FakeShell(), today=TODAY)
    args.update(kw)
    return {c.id: c for c in run_checks(DEVICE, "pw", **args)}


def test_parse_sections_of_real_output():
    s = parse_sections(REAL)
    assert set(s) == {"ntpq", "df", "archive", "config", "pwchanged", "wlan", "internet"}
    assert s["pwchanged"] == "yes"
    assert s["config"].startswith("{") and s["config"].endswith("}")


def test_all_checks_on_real_output():
    c = checks(local_days={date(2026, 10, 12)})
    assert [k for k in c] == list(ORDER)
    assert c["clock"].level is Level.OK and "ms via" in c["clock"].value
    assert c["internet"].value == "yes"
    assert c["wifi"].value == "10.10.178.153"
    assert c["storage"].level is Level.OK
    assert c["forwarding"].value == "OFF"
    assert c["password"].value == "changed"
    # 2025-09-25 (recorded with the wrong clock) is older than the 7-day retention
    assert c["archive"].level is Level.WARN and "keeps 7 days" in c["archive"].value


def test_laptop_ip_error_skips_everything_else():
    bad = lambda: Check("laptop_ip", Level.ERROR, "no 169.254.x.x address", "laptop_ip", "set_ip")
    c = checks(laptop_ip=bad)
    assert c["laptop_ip"].level is Level.ERROR
    assert all(c[i].level is Level.SKIPPED for i in ORDER[1:])


def test_ssh_failure_skips_ssh_checks_but_not_seedlink():
    c = checks(shell_factory=lambda d, p: FakeShell(error=ShellError("auth", "wrong user name, password or key")))
    assert c["ssh"].level is Level.ERROR and c["ssh"].help_id == "ssh.auth"
    assert c["seedlink"].level is Level.OK and c["channels"].level is Level.OK
    assert all(c[i].level is Level.SKIPPED for i in ("clock", "storage", "archive", "password"))


def test_seedlink_failure():
    def boom(host, port):
        raise ConnectionRefusedError("refused")
    c = checks(probe_fn=boom)
    assert c["seedlink"].level is Level.ERROR and c["channels"].level is Level.SKIPPED


def test_garbled_section_becomes_unreadable_not_crash():
    c = checks(shell_factory=lambda d, p: FakeShell(REAL.replace("@@df", "@@dfx")))
    assert c["storage"].level is Level.ERROR and c["storage"].value == "could not read"


@pytest.mark.parametrize("line, level", [
    ("*81.193.254.213  150.214.94.5     2 u   10   64   37   12.638    0.753   1.342", Level.OK),
    ("*81.193.254.213  150.214.94.5     2 u   10   64   37   12.638  250.000   1.342", Level.WARN),
    ("*81.193.254.213  150.214.94.5     2 u   10   64   37   12.638 -1500.00   1.342", Level.ERROR),
    (" 81.193.254.213  150.214.94.5     2 u   10   64   37   12.638    0.753   1.342", Level.ERROR),
])
def test_clock_levels(line, level):
    assert clock_check("header\n=====\n" + line).level is level


def test_storage_warns_below_ten_percent():
    df = "Filesystem 1-blocks Used Available Capacity Mounted on\n/dev/root 1000 950 50 95% /"
    assert storage_check(df).level is Level.WARN


def test_remote_days_and_archive_ok():
    listing = "/x/EHZ.D/:\nAM.R77A7.00.EHZ.D.2026.284\nAM.R77A7.00.EHZ.D.2026.285"
    assert remote_days(listing) == {date(2026, 10, 11), date(2026, 10, 12)}
    c = archive_check(listing, {"other": {"archkeep": 7}}, set(), TODAY)
    assert c.level is Level.OK and c.value == "2026-10-11 → 2026-10-12 · keeps 7 days"


def test_archive_none():
    assert archive_check("", {}, set(), TODAY).help_id == "archive.none"


def test_forwarding_password_wifi():
    assert forwarding_check({"dataSharing": {"enabled": True}}).level is Level.WARN
    assert password_check("no").level is Level.WARN
    two = ("3: wlan0 inet 10.10.178.153/21 brd x\n3: wlan0 inet 10.10.176.119/21 brd x")
    assert wifi_check(two).level is Level.WARN and wifi_check(two).help_id == "wifi.duplicate"
    assert wifi_check("").value == "not used"
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/core/test_status.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rs3d.core.status'`

- [ ] **Step 4: Implement** – `rs3d-app/src/rs3d/core/status.py`:

```python
"""Read-only health checks of the laptop link and the Shake -> list[Check] for the Status page."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Callable

from rs3d.core.models import Check, Device, Level
from rs3d.core.netcheck import check_laptop_ip
from rs3d.core.seedlink import StationInfo, probe
from rs3d.core.shell import Shell, ShellError

# One SSH round trip: every section starts with a line "@@name" (printed after a newline,
# because some files, e.g. config.json, do not end with one).
SHAKE_SCRIPT = r"""
printf '\n@@ntpq\n'; ntpq -pn 2>&1
printf '\n@@df\n'; df -P -B1 / 2>&1
printf '\n@@archive\n'; ls -1 /opt/data/archive/*/*/*/EHZ.D/ 2>/dev/null
printf '\n@@config\n'; cat /opt/settings/config/config.json 2>/dev/null
printf '\n@@pwchanged\n'; test -e /opt/settings/user/.pwchanged && echo yes || echo no
printf '\n@@wlan\n'; ip -4 -o addr show wlan0 2>/dev/null
printf '\n@@internet\n'; timeout 4 bash -c "</dev/tcp/1.1.1.1/443" 2>/dev/null && echo ok || echo fail
"""

ORDER = ("laptop_ip", "seedlink", "channels", "ssh", "clock", "internet", "wifi",
         "storage", "archive", "forwarding", "password")
SSH_DEPENDENT = ("clock", "internet", "wifi", "storage", "archive", "forwarding", "password")


def parse_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("@@"):
            current = line[2:].strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


# ---------------------------------------------------------------- individual checks (pure)

def clock_check(ntpq: str) -> Check:
    for line in ntpq.splitlines():
        if line.startswith("*"):
            fields = line[1:].split()
            remote, offset_ms = fields[0], float(fields[8])
            value = f"±{abs(offset_ms):.2f} ms via {remote}"
            if abs(offset_ms) > 1000:
                return Check("clock", Level.ERROR, value, "clock.offset")
            if abs(offset_ms) > 100:
                return Check("clock", Level.WARN, value, "clock.offset")
            return Check("clock", Level.OK, value, "clock")
    return Check("clock", Level.ERROR, "no time source", "clock.nosource")


def storage_check(df: str) -> Check:
    fields = df.splitlines()[-1].split()
    total, avail = int(fields[1]), int(fields[3])
    free = avail / total
    value = f"{avail / 1e9:.1f} GB free ({free:.0%})"
    return Check("storage", Level.WARN if free < 0.10 else Level.OK, value, "storage")


_DAY_FILE = re.compile(r"\.D\.(\d{4})\.(\d{3})$")


def remote_days(listing: str) -> set[date]:
    days = set()
    for name in listing.split():
        m = _DAY_FILE.search(name)
        if m:
            days.add(date(int(m[1]), 1, 1) + timedelta(days=int(m[2]) - 1))
    return days


def archive_check(listing: str, config: dict, local_days: set[date], today: date) -> Check:
    days = remote_days(listing)
    keep = int(config.get("other", {}).get("archkeep", 0) or 0)
    if not days:
        return Check("archive", Level.WARN, "no archive on the Shake", "archive.none")
    value = f"{min(days)} → {max(days)} · keeps {keep} days" if keep else f"{min(days)} → {max(days)}"
    at_risk = [d for d in days if d not in local_days and keep and (today - d).days >= keep - 1]
    if at_risk:
        return Check("archive", Level.WARN, value + f" · {len(at_risk)} day(s) about to be deleted",
                     "archive.atrisk", action="download")
    return Check("archive", Level.OK, value, "archive")


def forwarding_check(config: dict) -> Check:
    enabled = bool(config.get("dataSharing", {}).get("enabled", False))
    return Check("forwarding", Level.WARN if enabled else Level.OK, "ON" if enabled else "OFF", "forwarding")


def password_check(pwchanged: str) -> Check:
    changed = pwchanged.strip() == "yes"
    return Check("password", Level.OK if changed else Level.WARN,
                 "changed" if changed else "default", "password")


def internet_check(result: str) -> Check:
    ok = result.strip() == "ok"
    return Check("internet", Level.OK if ok else Level.WARN, "yes" if ok else "no", "internet")


def wifi_check(wlan: str) -> Check:
    ips = re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", wlan)
    if not ips:
        return Check("wifi", Level.OK, "not used", "wifi")
    if len(ips) > 1:
        return Check("wifi", Level.WARN, " + ".join(ips), "wifi.duplicate")
    return Check("wifi", Level.OK, ips[0], "wifi")


# ---------------------------------------------------------------- orchestration

def run_checks(
    device: Device,
    password: str | None,
    *,
    local_days: set[date] = frozenset(),
    today: date | None = None,
    laptop_ip: Callable[[], Check] = check_laptop_ip,
    probe_fn: Callable[[str, int], StationInfo] = probe,
    shell_factory: Callable[[Device, str | None], Shell] | None = None,
) -> list[Check]:
    """All checks in display order. Failed prerequisites turn dependent checks into SKIPPED."""
    today = today or date.today()
    results: dict[str, Check] = {}

    results["laptop_ip"] = laptop_ip()
    if results["laptop_ip"].level is Level.ERROR:
        return [results["laptop_ip"]] + [Check(i, Level.SKIPPED, "", i) for i in ORDER[1:]]

    try:
        info = probe_fn(device.host, device.seedlink_port)
        results["seedlink"] = Check("seedlink", Level.OK, f"{device.host}:{device.seedlink_port}", "seedlink")
        expected = {"EHZ", "EHN", "EHE"}
        missing = expected - set(info.channels)
        results["channels"] = Check("channels", Level.WARN if missing else Level.OK,
                                    " ".join(info.channels) or "none", "channels")
    except Exception as exc:
        results["seedlink"] = Check("seedlink", Level.ERROR, str(exc) or "unreachable", "seedlink")
        results["channels"] = Check("channels", Level.SKIPPED, "", "channels")

    try:
        if shell_factory is None:
            raise RuntimeError("no shell factory")
        with shell_factory(device, password) as sh:
            sections = parse_sections(sh.run(SHAKE_SCRIPT))
        results["ssh"] = Check("ssh", Level.OK, device.ssh_user, "ssh")
    except ShellError as exc:
        results["ssh"] = Check("ssh", Level.ERROR, str(exc), f"ssh.{exc.kind}")
        sections = None

    if sections is None:
        for i in SSH_DEPENDENT:
            results[i] = Check(i, Level.SKIPPED, "", i)
    else:
        try:
            config = json.loads(sections.get("config") or "{}")
        except json.JSONDecodeError:
            config = {}
        checks = {
            "clock": lambda: clock_check(sections.get("ntpq", "")),
            "internet": lambda: internet_check(sections.get("internet", "")),
            "wifi": lambda: wifi_check(sections.get("wlan", "")),
            "storage": lambda: storage_check(sections.get("df", "")),
            "archive": lambda: archive_check(sections.get("archive", ""), config, set(local_days), today),
            "forwarding": lambda: forwarding_check(config),
            "password": lambda: password_check(sections.get("pwchanged", "")),
        }
        for check_id, fn in checks.items():
            try:
                results[check_id] = fn()
            except Exception:  # unexpected output from the Shake must not break the page
                results[check_id] = Check(check_id, Level.ERROR, "could not read", "unreadable")

    return [results[i] for i in ORDER]
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/core/test_status.py -v`
Expected: 14 passed

- [ ] **Step 6: Commit**

```bash
git add rs3d-app/tests/data/shake_status.txt rs3d-app/src/rs3d/core/status.py rs3d-app/tests/core/test_status.py
git commit -m "feat(rs3d-app): read-only status checks in one SSH round trip"
```

---

### Task 6: Archive download

**Files:**
- Create: `rs3d-app/src/rs3d/core/archive.py`
- Test: `rs3d-app/tests/core/test_archive.py`

The tests serve the Plan 1 fixture store as a fake Shake archive through a small `LocalSftp` class, including an interrupted transfer.

- [ ] **Step 1: Write the failing tests** – `rs3d-app/tests/core/test_archive.py`:

```python
import shutil
from datetime import date
from pathlib import Path

import pytest

from rs3d.core import archive
from rs3d.core.store import Store
from tests.conftest import DAY1, DAY2

NSL = ("AM", "R77A7", "00")


class LocalSftp:
    """Serves a local folder as if it were the Shake's /opt/data/archive."""

    def __init__(self, root: Path, fail_on: str | None = None):
        self.root, self.fail_on, self.gets = root, fail_on, []

    def _local(self, remote: str) -> Path:
        return self.root / Path(remote).relative_to(archive.REMOTE_ROOT)

    def listdir(self, path):
        p = self._local(path)
        if not p.is_dir():
            raise FileNotFoundError(path)
        return sorted(x.name for x in p.iterdir())

    def get(self, remotepath, localpath):
        self.gets.append(remotepath)
        if self.fail_on and remotepath.endswith(self.fail_on):
            Path(localpath).write_bytes(b"half")
            raise ConnectionResetError("cable pulled")
        shutil.copyfile(self._local(remotepath), localpath)


@pytest.fixture
def shake(store, tmp_path):
    """A fake Shake archive with the fixture data, in the same SDS layout."""
    root = tmp_path / "shake"
    shutil.copytree(store.root, root)
    return root


def test_remote_day_path():
    assert archive.remote_day_path(*NSL, "EHZ", date(2026, 10, 12)) == \
        "/opt/data/archive/2026/AM/R77A7/EHZ.D/AM.R77A7.00.EHZ.D.2026.285"


def test_list_remote_days(shake):
    assert archive.list_remote_days(LocalSftp(shake), *NSL, "EHZ") == {DAY1, DAY2}
    assert archive.list_remote_days(LocalSftp(shake), *NSL, "XXX") == set()


def test_days_to_fetch_includes_newest_even_if_local():
    remote = {DAY1, DAY2}
    assert archive.days_to_fetch(remote, set(), DAY1, DAY2) == [DAY1, DAY2]
    assert archive.days_to_fetch(remote, {DAY1, DAY2}, DAY1, DAY2) == [DAY2]
    assert archive.days_to_fetch(remote, {DAY1}, DAY1, DAY1) == []


def test_sync_downloads_into_empty_store(shake, tmp_path):
    local = Store(tmp_path / "laptop")
    written = archive.sync(LocalSftp(shake), local, *NSL, ("EHZ", "EHN"), DAY1, DAY2)
    assert len(written) == 4
    assert local.days(*NSL, "EHZ") == {DAY1, DAY2}


def test_sync_second_time_only_refreshes_newest_day(shake, tmp_path):
    local = Store(tmp_path / "laptop")
    archive.sync(LocalSftp(shake), local, *NSL, ("EHZ",), DAY1, DAY2)
    sftp = LocalSftp(shake)
    archive.sync(sftp, local, *NSL, ("EHZ",), DAY1, DAY2)
    assert len(sftp.gets) == 1 and sftp.gets[0].endswith(".285")


def test_interrupted_download_leaves_no_file(shake, tmp_path):
    local = Store(tmp_path / "laptop")
    with pytest.raises(ConnectionResetError):
        archive.sync(LocalSftp(shake, fail_on=".285"), local, *NSL, ("EHZ",), DAY1, DAY2)
    assert local.days(*NSL, "EHZ") == {DAY1}
    assert not list((tmp_path / "laptop").rglob("*.part"))


def test_progress_callback(shake, tmp_path):
    seen = []
    archive.sync(LocalSftp(shake), Store(tmp_path / "laptop"), *NSL, ("EHZ",), DAY1, DAY2,
                 progress=lambda i, n, label: seen.append((i, n, label)))
    assert seen == [(1, 2, "EHZ 2026-10-11"), (2, 2, "EHZ 2026-10-12")]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/core/test_archive.py -v`
Expected: FAIL with `ImportError: cannot import name 'archive' from 'rs3d.core'`

- [ ] **Step 3: Implement** – `rs3d-app/src/rs3d/core/archive.py`:

```python
"""Copy the Shake's own SDS archive (/opt/data/archive) into the local store over SFTP."""

from __future__ import annotations

import posixpath
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Protocol

from rs3d.core.store import Store

REMOTE_ROOT = "/opt/data/archive"


class Sftp(Protocol):
    def listdir(self, path: str) -> list[str]: ...
    def get(self, remotepath: str, localpath: str) -> None: ...


def remote_day_path(network: str, station: str, location: str, channel: str, day: date) -> str:
    doy = day.timetuple().tm_yday
    return posixpath.join(REMOTE_ROOT, str(day.year), network, station, f"{channel}.D",
                          f"{network}.{station}.{location}.{channel}.D.{day.year}.{doy:03d}")


def list_remote_days(sftp: Sftp, network: str, station: str, location: str, channel: str) -> set[date]:
    days: set[date] = set()
    try:
        years = [y for y in sftp.listdir(REMOTE_ROOT) if y.isdigit()]
    except OSError:
        return days
    prefix = f"{network}.{station}.{location}.{channel}.D."
    for year in years:
        folder = posixpath.join(REMOTE_ROOT, year, network, station, f"{channel}.D")
        try:
            names = sftp.listdir(folder)
        except OSError:
            continue
        for name in names:
            if name.startswith(prefix):
                y, doy = name[len(prefix):].split(".")
                days.add(date(int(y), 1, 1) + timedelta(days=int(doy) - 1))
    return days


def days_to_fetch(remote: set[date], local: set[date], start: date, end: date) -> list[date]:
    """Remote days in [start, end] that are missing locally, plus the newest remote day (still growing)."""
    wanted = {d for d in remote if start <= d <= end and d not in local}
    if remote:
        newest = max(remote)
        if start <= newest <= end:
            wanted.add(newest)
    return sorted(wanted)


def download_day(sftp: Sftp, store: Store, network: str, station: str, location: str,
                 channel: str, day: date) -> Path:
    """Download into <file>.part, then rename, so an interrupted copy never looks complete."""
    remote = remote_day_path(network, station, location, channel, day)
    local = store.day_path(network, station, location, channel, day)
    local.parent.mkdir(parents=True, exist_ok=True)
    part = local.with_name(local.name + ".part")
    try:
        sftp.get(remote, str(part))
        part.replace(local)
    finally:
        part.unlink(missing_ok=True)
    return local


def sync(sftp: Sftp, store: Store, network: str, station: str, location: str,
         channels: tuple[str, ...], start: date, end: date,
         progress: Callable[[int, int, str], None] | None = None) -> list[Path]:
    """Fetch every needed day file for the channels in [start, end]. Returns the files written."""
    jobs = []
    for channel in channels:
        remote = list_remote_days(sftp, network, station, location, channel)
        local = store.days(network, station, location, channel)
        jobs += [(channel, d) for d in days_to_fetch(remote, local, start, end)]
    written = []
    for i, (channel, day) in enumerate(jobs, 1):
        if progress:
            progress(i, len(jobs), f"{channel} {day}")
        written.append(download_day(sftp, store, network, station, location, channel, day))
    return written
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/core/test_archive.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add rs3d-app/src/rs3d/core/archive.py rs3d-app/tests/core/test_archive.py
git commit -m "feat(rs3d-app): download the Shake archive over SFTP"
```

---

### Task 7: Live stream

**Files:**
- Create: `rs3d-app/src/rs3d/core/live.py`
- Test: `rs3d-app/tests/core/test_live.py`

`RingBuffer` keeps 10 minutes per channel as contiguous chunks; `snapshot()` returns `(times, values)` with a `NaN` between chunks so charts show gaps, and decimates long windows by min/max so peaks survive. `LiveStream` runs a source in a daemon thread and reconnects after 2, 4, 8, 16, 30 s (reset after a successful connection).

- [ ] **Step 1: Write the failing tests** – `rs3d-app/tests/core/test_live.py`:

```python
import threading

import numpy as np
from obspy import Trace, UTCDateTime

from rs3d.core.live import BACKOFF, LiveStream, RingBuffer

T0 = UTCDateTime("2026-10-12T12:00:00")


def trace(channel, start, n, rate=100.0, value=1.0):
    return Trace(np.full(n, value), header={"channel": channel, "starttime": start, "sampling_rate": rate})


def test_contiguous_packets_merge():
    buf = RingBuffer()
    buf.add(trace("EHZ", T0, 100))
    buf.add(trace("EHZ", T0 + 1, 100))
    t, v = buf.snapshot("EHZ", 10)
    assert len(t) == 200 and not np.isnan(v).any()
    assert buf.latest() == (T0 + 2).timestamp


def test_gap_is_marked_with_nan():
    buf = RingBuffer()
    buf.add(trace("EHZ", T0, 100))
    buf.add(trace("EHZ", T0 + 5, 100))
    t, v = buf.snapshot("EHZ", 10)
    assert np.isnan(v).sum() == 1 and len(t) == 201


def test_old_data_is_dropped():
    buf = RingBuffer(seconds=60)
    buf.add(trace("EHZ", T0, 100))
    buf.add(trace("EHZ", T0 + 120, 100))
    t, _ = buf.snapshot("EHZ", 600)
    assert t.min() >= (T0 + 120).timestamp


def test_snapshot_window_and_unknown_channel():
    buf = RingBuffer()
    buf.add(trace("EHZ", T0, 1000))
    t, _ = buf.snapshot("EHZ", 2)
    assert len(t) == 200 and t[-1] < (T0 + 10).timestamp
    assert buf.snapshot("EHN", 2)[0].size == 0


def test_decimation_keeps_peaks():
    buf = RingBuffer()
    data = np.zeros(30000)
    data[12345] = 999.0
    buf.add(Trace(data, header={"channel": "EHZ", "starttime": T0, "sampling_rate": 100.0}))
    t, v = buf.snapshot("EHZ", 300, max_points=1000)
    assert len(t) <= 1000 and v.max() == 999.0


class FakeSource:
    def __init__(self, traces, fail=None):
        self.traces, self.fail, self.closed = traces, fail, False

    def run(self, on_trace):
        for tr in self.traces:
            on_trace(tr)
        if self.fail:
            raise self.fail

    def close(self):
        self.closed = True


def test_reconnects_with_backoff_and_resets_after_success():
    sleeps, made = [], []
    stop_after = threading.Event()

    def factory():
        n = len(made)
        if n in (0, 1):
            src = FakeSource([], fail=ConnectionRefusedError("refused"))
        elif n == 2:
            src = FakeSource([trace("EHZ", T0, 100)], fail=ConnectionResetError("cable"))
        else:
            stop_after.set()
            src = FakeSource([], fail=ConnectionRefusedError("refused"))
        made.append(src)
        return src

    live = LiveStream(factory, sleep=lambda s: sleeps.append(s))
    live.start()
    assert stop_after.wait(5)
    live.stop()
    assert sleeps[:3] == [BACKOFF[0], BACKOFF[1], BACKOFF[0]]
    assert live.buffer.snapshot("EHZ", 10)[0].size == 100
    assert live.state == "stopped"


def test_is_stale_before_any_data():
    live = LiveStream(lambda: FakeSource([]))
    assert live.is_stale()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/core/test_live.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rs3d.core.live'`

- [ ] **Step 3: Implement** – `rs3d-app/src/rs3d/core/live.py`:

```python
"""Live data: a background thread feeds a ring buffer; the UI takes snapshots."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Protocol

import numpy as np
from obspy import Trace, UTCDateTime

BACKOFF = (2, 4, 8, 16, 30)  # seconds between reconnect attempts


class Source(Protocol):
    def run(self, on_trace: Callable[[Trace], None]) -> None: ...
    def close(self) -> None: ...


@dataclass
class _Chunk:
    start: float  # epoch seconds of the first sample
    rate: float
    data: np.ndarray

    @property
    def end(self) -> float:  # time just after the last sample
        return self.start + len(self.data) / self.rate


class RingBuffer:
    """Recent samples per channel, as a list of contiguous chunks. Thread-safe."""

    def __init__(self, seconds: float = 600.0) -> None:
        self.seconds = seconds
        self._chunks: dict[str, list[_Chunk]] = {}
        self._lock = threading.Lock()

    def add(self, tr: Trace) -> None:
        chunk = _Chunk(tr.stats.starttime.timestamp, tr.stats.sampling_rate, tr.data.astype(float))
        with self._lock:
            chunks = self._chunks.setdefault(tr.stats.channel, [])
            last = chunks[-1] if chunks else None
            if last and abs(chunk.start - last.end) <= 0.5 / chunk.rate and last.rate == chunk.rate:
                last.data = np.concatenate([last.data, chunk.data])
            else:
                chunks.append(chunk)
            horizon = chunk.end - self.seconds
            self._chunks[tr.stats.channel] = [c for c in chunks if c.end > horizon]

    def latest(self) -> float | None:
        with self._lock:
            ends = [cs[-1].end for cs in self._chunks.values() if cs]
        return max(ends) if ends else None

    def snapshot(self, channel: str, seconds: float, end: float | None = None,
                 max_points: int = 2000) -> tuple[np.ndarray, np.ndarray]:
        """(times, values) for the last `seconds` before `end`. A NaN separates non-contiguous chunks.

        Long windows are decimated by min/max pairs so peaks stay visible.
        """
        end = end if end is not None else (self.latest() or time.time())
        start = end - seconds
        times, values = [], []
        with self._lock:
            chunks = list(self._chunks.get(channel, []))
        for c in chunks:
            if c.end <= start or c.start >= end:
                continue
            i0 = max(0, int(np.ceil((start - c.start) * c.rate)))
            i1 = min(len(c.data), int(np.floor((end - c.start) * c.rate)))
            if i1 <= i0:
                continue
            t = c.start + np.arange(i0, i1) / c.rate
            v = c.data[i0:i1]
            if times:
                times.append(np.array([t[0]]))
                values.append(np.array([np.nan]))
            times.append(t)
            values.append(v)
        if not times:
            return np.array([]), np.array([])
        t, v = np.concatenate(times), np.concatenate(values)
        if len(t) > max_points:
            t, v = _minmax_decimate(t, v, max_points)
        return t, v


def _minmax_decimate(t: np.ndarray, v: np.ndarray, max_points: int) -> tuple[np.ndarray, np.ndarray]:
    bins = max_points // 2
    edges = np.linspace(0, len(t), bins + 1).astype(int)
    out_t, out_v = [], []
    for a, b in zip(edges[:-1], edges[1:]):
        if b <= a:
            continue
        seg = v[a:b]
        if np.all(np.isnan(seg)):
            out_t.append(t[a])
            out_v.append(np.nan)
            continue
        lo, hi = a + int(np.nanargmin(seg)), a + int(np.nanargmax(seg))
        for i in sorted((lo, hi)):
            out_t.append(t[i])
            out_v.append(v[i])
    return np.array(out_t), np.array(out_v)


class LiveStream:
    """Keeps a Source running in a daemon thread; reconnects with backoff when it fails."""

    def __init__(self, source_factory: Callable[[], Source], buffer: RingBuffer | None = None,
                 sleep: Callable[[float], None] | None = None) -> None:
        self.buffer = buffer or RingBuffer()
        self.state = "stopped"  # stopped | connecting | live | reconnecting
        self.error = ""
        self.last_data: float | None = None  # time.monotonic() of the last trace
        self._factory = source_factory
        self._stop = threading.Event()
        self._sleep = sleep or (lambda s: self._stop.wait(s))
        self._thread: threading.Thread | None = None
        self._source: Source | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="rs3d-live", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._source:
            self._source.close()
        if self._thread:
            self._thread.join(timeout)
        self.state = "stopped"

    def _on_trace(self, tr: Trace) -> None:
        self.state = "live"
        self.last_data = time.monotonic()
        self.buffer.add(tr)

    def is_stale(self, seconds: float = 5.0) -> bool:
        """True when no data arrived recently (ObsPy may be reconnecting inside the source)."""
        return self.last_data is None or time.monotonic() - self.last_data > seconds

    def _loop(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            self.state = "connecting" if attempt == 0 else "reconnecting"
            try:
                self._source = self._factory()
                self._source.run(self._on_trace)
                self.error = "connection closed"
            except Exception as exc:
                self.error = str(exc) or type(exc).__name__
            if self._stop.is_set():
                break
            if self.state == "live":
                attempt = 0  # it worked for a while: start the backoff again
            delay = BACKOFF[min(attempt, len(BACKOFF) - 1)]
            attempt += 1
            self.state = "reconnecting"
            self._sleep(delay)
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/core/test_live.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add rs3d-app/src/rs3d/core/live.py rs3d-app/tests/core/test_live.py
git commit -m "feat(rs3d-app): live ring buffer with reconnecting stream"
```

---

### Task 8: Device tests and full suite

**Files:**
- Create: `rs3d-app/tests/device/__init__.py` (empty)
- Create: `rs3d-app/tests/device/test_real_shake.py`

- [ ] **Step 1: Create the device tests** – `rs3d-app/tests/device/test_real_shake.py`:

```python
"""Run with a Shake on the cable: RS3D_HOST=169.254.221.62 uv run pytest -m device -v

Uses the laptop's SSH key or agent (no password stored in tests).
"""

import os
import time
from datetime import date, timedelta

import pytest

from rs3d.core import archive
from rs3d.core.discovery import discover
from rs3d.core.live import LiveStream
from rs3d.core.models import Device, Level
from rs3d.core.seedlink import SeedLinkSource, probe
from rs3d.core.shell import Shell
from rs3d.core.status import run_checks
from rs3d.core.store import Store

pytestmark = pytest.mark.device
HOST = os.environ.get("RS3D_HOST", "169.254.221.62")


@pytest.fixture(scope="module")
def info():
    return probe(HOST)


@pytest.fixture
def device(info):
    return Device(name=info.station, host=HOST, station=info.station, network=info.network,
                  location=info.location)


def test_probe(info):
    assert {"EHZ", "EHN", "EHE"} <= set(info.channels)


def test_discover_finds_it(info):
    assert any(f.info.station == info.station for f in discover())


def test_status_has_no_errors(device, tmp_path):
    results = run_checks(device, None, shell_factory=lambda d, p: Shell(d, p, tmp_path / "kh"))
    assert [c.id for c in results if c.level is Level.ERROR] == []


def test_archive_sync_today(device, tmp_path):
    store = Store(tmp_path / "sds")
    with Shell(device, None, tmp_path / "kh") as sh:
        written = archive.sync(sh.sftp(), store, device.network, device.station, device.location,
                               ("EHZ",), date.today() - timedelta(days=1), date.today())
    assert written


def test_live_receives_data(device):
    live = LiveStream(lambda: SeedLinkSource(HOST, 18000, device.network, device.station, ("EHZ",)))
    live.start()
    try:
        deadline = time.monotonic() + 20
        while live.is_stale() and time.monotonic() < deadline:
            time.sleep(0.5)
        assert not live.is_stale()
    finally:
        live.stop()
```

- [ ] **Step 2: Run the unit suite**

Run: `uv run pytest -q`
Expected: `89 passed, 5 deselected`

- [ ] **Step 3: Run the device suite (only with a Shake on the cable and an SSH key installed on it)**

Run: `uv run pytest -m device -v`
Expected: 5 passed. Without a Shake these tests fail with connection errors; that is expected and not a reason to change code.

- [ ] **Step 4: Commit**

```bash
git add rs3d-app/tests/device
git commit -m "test(rs3d-app): device tests against a real Shake"
```
