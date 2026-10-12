import shutil
from datetime import date
from pathlib import Path

import pytest

from rs3d.core import archive
from rs3d.core.store import Store
from tests.conftest import DAY1, DAY2

NSL = ("AM", "R77A7", "00")


class LocalSftp:
    """Serves a local folder as if it were the Shake's /opt/data/archive."""

    def __init__(self, root: Path, fail_on: str | None = None):
        self.root, self.fail_on, self.gets = root, fail_on, []

    def _local(self, remote: str) -> Path:
        return self.root / Path(remote).relative_to(archive.REMOTE_ROOT)

    def listdir(self, path):
        p = self._local(path)
        if not p.is_dir():
            raise FileNotFoundError(path)
        return sorted(x.name for x in p.iterdir())

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


def test_days_to_fetch_includes_newest_even_if_local():
    remote = {DAY1, DAY2}
    assert archive.days_to_fetch(remote, set(), DAY1, DAY2) == [DAY1, DAY2]
    assert archive.days_to_fetch(remote, {DAY1, DAY2}, DAY1, DAY2) == [DAY2]
    assert archive.days_to_fetch(remote, {DAY1}, DAY1, DAY1) == []


def test_sync_downloads_into_empty_store(shake, tmp_path):
    local = Store(tmp_path / "laptop")
    written = archive.sync(LocalSftp(shake), local, *NSL, ("EHZ", "EHN"), DAY1, DAY2)
    assert len(written) == 4
    assert local.days(*NSL, "EHZ") == {DAY1, DAY2}


def test_sync_second_time_only_refreshes_newest_day(shake, tmp_path):
    local = Store(tmp_path / "laptop")
    archive.sync(LocalSftp(shake), local, *NSL, ("EHZ",), DAY1, DAY2)
    sftp = LocalSftp(shake)
    archive.sync(sftp, local, *NSL, ("EHZ",), DAY1, DAY2)
    assert len(sftp.gets) == 1 and sftp.gets[0].endswith(".285")


def test_interrupted_download_leaves_no_file(shake, tmp_path):
    local = Store(tmp_path / "laptop")
    with pytest.raises(ConnectionResetError):
        archive.sync(LocalSftp(shake, fail_on=".285"), local, *NSL, ("EHZ",), DAY1, DAY2)
    assert local.days(*NSL, "EHZ") == {DAY1}
    assert not list((tmp_path / "laptop").rglob("*.part"))


def test_progress_callback(shake, tmp_path):
    seen = []
    archive.sync(LocalSftp(shake), Store(tmp_path / "laptop"), *NSL, ("EHZ",), DAY1, DAY2,
                 progress=lambda i, n, label: seen.append((i, n, label)))
    assert seen == [(1, 2, "EHZ 2026-10-11"), (2, 2, "EHZ 2026-10-12")]
