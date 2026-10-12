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
