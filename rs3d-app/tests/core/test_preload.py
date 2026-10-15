from datetime import date

import numpy as np
from obspy import Stream, Trace, UTCDateTime

from rs3d.core.day_trace import DayTrace
from rs3d.core.models import Device
from rs3d.core.preload import preload_today
from tests.conftest import DAY2, LOC, NET, STA
from tests.core.test_archive import LocalSftp, shake  # noqa: F401  (fixtures)

DEVICE = Device(name="s", host="h", network=NET, station=STA, location=LOC)


def test_preload_fills_the_day_from_the_archive(store, shake, tmp_path):  # noqa: F811
    local = type(store)(tmp_path / "local")
    d = DayTrace(DAY2)
    done = preload_today(LocalSftp(shake), local, DEVICE, d, ("EHZ", "EHN"))
    assert done == ["EHZ", "EHN"]
    assert d.has_data("EHZ") and d.has_data("EHN") and not d.has_data("EHE")
    r0 = d.rows("EHZ")[0]  # fixture data runs 00:00-00:02 and 00:03-00:10
    assert len(r0.values) > 0 and np.isnan(r0.values).any()


def test_preload_survives_a_missing_file(store, shake, tmp_path, caplog):  # noqa: F811
    local = type(store)(tmp_path / "local")
    d = DayTrace(date(2026, 10, 20))  # the archive has nothing for this day
    assert preload_today(LocalSftp(shake), local, DEVICE, d, ("EHZ",)) == []
    assert not d.has_data("EHZ")


def test_preload_survives_a_cut_connection(store, shake, tmp_path):  # noqa: F811
    local = type(store)(tmp_path / "local")
    d = DayTrace(DAY2)
    sftp = LocalSftp(shake, fail_on=".EHZ.D.2026.285")
    assert preload_today(sftp, local, DEVICE, d, ("EHZ", "EHN")) == ["EHN"]
    assert not d.has_data("EHZ") and d.has_data("EHN")
