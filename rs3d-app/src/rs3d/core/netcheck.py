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
