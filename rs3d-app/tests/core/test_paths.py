import sys

from rs3d.core.paths import ENV_DATA_DIR, PORTABLE_MARKER, AppPaths


def _frozen(monkeypatch, exe_dir):
    monkeypatch.delenv(ENV_DATA_DIR, raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "RS3D.exe"))


def test_portable_marker_next_to_exe_keeps_data_beside_it(tmp_path, monkeypatch):
    (tmp_path / PORTABLE_MARKER).write_text("")
    _frozen(monkeypatch, tmp_path)
    assert AppPaths.default().root == tmp_path / "data"


def test_no_marker_uses_os_data_folder(tmp_path, monkeypatch):
    _frozen(monkeypatch, tmp_path)
    assert AppPaths.default().root != tmp_path / "data"


def test_marker_ignored_when_not_frozen(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_DATA_DIR, raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python"))
    (tmp_path / PORTABLE_MARKER).write_text("")
    assert AppPaths.default().root != tmp_path / "data"


def test_env_override_beats_portable(tmp_path, monkeypatch):
    (tmp_path / PORTABLE_MARKER).write_text("")
    _frozen(monkeypatch, tmp_path)
    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path / "x"))
    assert AppPaths.default().root == tmp_path / "x"
