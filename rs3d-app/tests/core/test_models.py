import pytest
from obspy import UTCDateTime

from rs3d.core.models import Check, Device, Level, Selection

T0 = UTCDateTime("2026-10-12T00:00:00")


def test_selection_defaults():
    sel = Selection("AM", "R77A7", "00", T0, T0 + 60)
    assert sel.channels == ("EHZ", "EHN", "EHE")
    assert sel.units == "counts"
    assert sel.filter is None


@pytest.mark.parametrize("kwargs, message", [
    ({"end": T0}, "end must be after start"),
    ({"channels": ()}, "at least one channel"),
    ({"units": "g"}, "units must be one of"),
    ({"filter": (10.0, 1.0)}, "0 < fmin < fmax"),
    ({"filter": (0.0, 1.0)}, "0 < fmin < fmax"),
])
def test_selection_rejects_bad_input(kwargs, message):
    args = {"network": "AM", "station": "R77A7", "location": "00", "start": T0, "end": T0 + 60}
    args.update(kwargs)
    with pytest.raises(ValueError, match=message):
        Selection(**args)


def test_device_defaults():
    d = Device(name="R77A7", host="169.254.221.62")
    assert (d.seedlink_port, d.ssh_user, d.network, d.location) == (18000, "myshake", "AM", "00")


def test_check_level_values():
    c = Check(id="ssh", level=Level.ERROR, help_id="ssh.auth")
    assert c.level.value == "error"
    assert c.action is None
