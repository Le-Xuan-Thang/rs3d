from pathlib import Path

from rs3d.core.devices import DEFAULT_PASSWORD, KEYRING_SERVICE, DeviceRegistry, Passwords
from rs3d.core.models import Device
from rs3d.core.paths import ENV_DATA_DIR, AppPaths


class MemoryKeyring:
    def __init__(self):
        self.data = {}

    def get_password(self, service, user):
        return self.data.get((service, user))

    def set_password(self, service, user, password):
        self.data[(service, user)] = password

    def delete_password(self, service, user):
        self.data.pop((service, user), None)


class BrokenKeyring:
    def get_password(self, service, user):
        raise RuntimeError("no keyring backend")

    set_password = delete_password = get_password


def test_registry_roundtrip(tmp_path):
    reg = DeviceRegistry(tmp_path / "config.toml")
    assert reg.load() == []
    a = Device(name="R77A7", host="169.254.221.62", station="R77A7")
    b = Device(name="lab", host="169.254.10.10", key_path=Path("/keys/id_ed25519"))
    reg.save([a, b])
    assert reg.load() == [a, b]
    assert "password" not in (tmp_path / "config.toml").read_text()


def test_registry_upsert_replaces_same_host(tmp_path):
    reg = DeviceRegistry(tmp_path / "config.toml")
    reg.upsert(Device(name="old", host="169.254.221.62"))
    reg.upsert(Device(name="new", host="169.254.221.62"))
    assert [d.name for d in reg.load()] == ["new"]
    assert reg.get("169.254.221.62").name == "new"
    reg.remove("169.254.221.62")
    assert reg.load() == []


def test_passwords_use_keyring():
    ring = MemoryKeyring()
    pw = Passwords(ring)
    assert pw.get_or_default("h") == DEFAULT_PASSWORD
    pw.set("h", "s3cret")
    assert ring.data[(KEYRING_SERVICE, "h")] == "s3cret"
    assert pw.get("h") == "s3cret" and pw.persistent
    pw.delete("h")
    assert pw.get("h") is None


def test_passwords_fall_back_to_session_without_keyring():
    pw = Passwords(BrokenKeyring())
    pw.set("h", "s3cret")
    assert pw.get("h") == "s3cret"
    assert pw.persistent is False


def test_app_paths_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path))
    p = AppPaths.default().ensure()
    assert p.root == tmp_path
    assert p.config == tmp_path / "config.toml"
    assert all(d.is_dir() for d in (p.sds, p.response, p.logs))
