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
