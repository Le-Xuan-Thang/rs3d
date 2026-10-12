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
