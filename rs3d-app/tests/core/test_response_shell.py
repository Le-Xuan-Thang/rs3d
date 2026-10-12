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
