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
