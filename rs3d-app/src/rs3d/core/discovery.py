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
