import io
import shutil
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from obspy import Trace, UTCDateTime, read

from rs3d.core import archive
from rs3d.core.store import Store
from tests.conftest import DAY1, DAY2

NSL = ("AM", "R77A7", "00")


class LocalSftp:
    """Serves a local folder as if it were the Shake's /opt/data/archive."""

    def __init__(self, root: Path, fail_on: str | None = None):
        self.root, self.fail_on, self.gets, self.opens = root, fail_on, [], []

    def _local(self, remote: str) -> Path:
        return self.root / Path(remote).relative_to(archive.REMOTE_ROOT)

    def listdir(self, path):
        p = self._local(path)
        if not p.is_dir():
            raise FileNotFoundError(path)
        return sorted(x.name for x in p.iterdir())

    def stat(self, path):
        return self._local(path).stat()

    def open(self, path, mode="rb"):
        self.opens.append(path)
        return self._local(path).open(mode)

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


def test_download_day_interrupted_leaves_no_file(shake, tmp_path):
    local = Store(tmp_path / "laptop")
    with pytest.raises(ConnectionResetError):
        archive.download_day(LocalSftp(shake, fail_on=".285"), local, *NSL, "EHZ", DAY2)
    assert local.days(*NSL, "EHZ") == set()
    assert not list((tmp_path / "laptop").rglob("*.part"))


# ---------------------------------------------------------------- partial downloads

T0 = UTCDateTime("2026-10-12T00:00:00")


@pytest.fixture
def long_shake(tmp_path):
    """A Shake whose 2026-10-12 EHZ file holds two hours (512-byte records) and 2026-10-11 holds a full short day."""
    root = tmp_path / "longshake"
    for day, seconds, start in ((DAY2, 7200, T0), (DAY1, 3600, T0 - 86400)):
        data = np.random.default_rng(day.day).integers(-3000, 3000, seconds * 100).astype("int32")
        tr = Trace(data, dict(network="AM", station="R77A7", location="00", channel="EHZ", sampling_rate=100.0,
                              starttime=start))
        path = Store(root).day_path(*NSL, "EHZ", day)
        path.parent.mkdir(parents=True, exist_ok=True)
        tr.write(str(path), format="MSEED", reclen=512, encoding="STEIM2")
    # the fake Shake serves /opt/data/archive/<year>/..., the store lays out <root>/<year>/...
    return root


def shake_of(root):
    return LocalSftp(root)


def test_sync_range_copies_only_the_selected_part(long_shake, tmp_path):
    local = Store(tmp_path / "laptop")
    sftp = shake_of(long_shake)
    written = archive.sync_range(sftp, local, *NSL, ("EHZ",), T0 + 1800, T0 + 1860)
    assert len(written) == 1 and sftp.gets == []
    size = written[0].stat().st_size
    assert size < 0.05 * sftp._local(archive.remote_day_path(*NSL, "EHZ", DAY2)).stat().st_size
    tr = read(str(written[0]))[0]
    whole = read(str(sftp._local(archive.remote_day_path(*NSL, "EHZ", DAY2))))[0]
    assert np.array_equal(tr.slice(T0 + 1800, T0 + 1860).data, whole.slice(T0 + 1800, T0 + 1860).data)


def test_asking_again_for_a_covered_range_copies_nothing(long_shake, tmp_path):
    local = Store(tmp_path / "laptop")
    archive.sync_range(shake_of(long_shake), local, *NSL, ("EHZ",), T0 + 1800, T0 + 1860)
    sftp = shake_of(long_shake)
    assert archive.sync_range(sftp, local, *NSL, ("EHZ",), T0 + 1810, T0 + 1850) == [] and sftp.opens == []


def test_a_second_range_is_merged_into_the_same_file(long_shake, tmp_path):
    local = Store(tmp_path / "laptop")
    archive.sync_range(shake_of(long_shake), local, *NSL, ("EHZ",), T0 + 600, T0 + 660)
    archive.sync_range(shake_of(long_shake), local, *NSL, ("EHZ",), T0 + 3000, T0 + 3060)
    st = read(str(local.day_path(*NSL, "EHZ", DAY2)))
    spans = sorted((round(tr.stats.starttime - T0), round(tr.stats.endtime - T0)) for tr in st)
    assert len(spans) == 2 and spans[0][0] <= 600 and spans[0][1] >= 660 and spans[1][0] <= 3000 <= 3060 <= spans[1][1]


def test_plan_downloads_only_lists_the_missing_part(long_shake, tmp_path):
    local = Store(tmp_path / "laptop")
    remote = {DAY1, DAY2}
    jobs = archive.plan_downloads(local, *NSL, ("EHZ",), remote, T0 - 3600, T0 + 3600)
    assert [(j.day, round(j.end - j.start)) for j in jobs] == [(DAY1, 3600), (DAY2, 3600)]
    assert archive.estimate_bytes(jobs) == 7200 * archive.BYTES_PER_SECOND
    archive.sync_range(shake_of(long_shake), local, *NSL, ("EHZ",), T0 - 3600, T0 + 3600)
    assert archive.plan_downloads(local, *NSL, ("EHZ",), remote, T0 - 3600, T0 + 3600) == []


def test_a_whole_day_copy_from_before_is_not_downloaded_again(shake, tmp_path):
    local = Store(tmp_path / "laptop")
    archive.download_day(LocalSftp(shake), local, *NSL, "EHZ", DAY1)
    jobs = archive.plan_downloads(local, *NSL, ("EHZ",), {DAY1, DAY2}, UTCDateTime("2026-10-11T23:55:00"),
                                  UTCDateTime("2026-10-12T00:00:00"))
    assert jobs == []  # DAY1 is complete locally; DAY2 is outside the selection


def test_a_gap_that_was_asked_for_is_a_gap_not_missing(long_shake, tmp_path):
    from rs3d.core.coverage import State, coverage
    local = Store(tmp_path / "laptop")
    remote = {DAY1, DAY2}
    far = T0 - 86400 + 4000  # DAY1 has data only for its first hour: later time is a real gap
    before = coverage(local, *NSL, "EHZ", far, far + 600, remote)
    assert [s.state for s in before] == [State.REMOTE]
    archive.sync_range(shake_of(long_shake), local, *NSL, ("EHZ",), far, far + 600)
    after = coverage(local, *NSL, "EHZ", far, far + 600, remote)
    assert [s.state for s in after] == [State.GAP]


def test_not_miniseed_on_the_shake_falls_back_to_the_whole_file(tmp_path):
    root = tmp_path / "odd"
    path = Store(root).day_path(*NSL, "EHZ", DAY2)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x" * 5000)

    class Sftp(LocalSftp):
        pass

    local = Store(tmp_path / "laptop")
    sftp = Sftp(root)
    archive.sync_range(sftp, local, *NSL, ("EHZ",), T0, T0 + 60)
    assert len(sftp.gets) == 1 and local.day_path(*NSL, "EHZ", DAY2).read_bytes() == b"x" * 5000
