import tomllib
from importlib import resources

from rs3d.app.strings import guide_markdown, help_text, label
from rs3d.core.status import ORDER

def test_labels_and_fallback():
    assert label("nav.status") == "Status"
    assert label("check.forwarding") == "Data Forwarding"
    assert label("does.not.exist") == "does.not.exist"


def test_help_text_falls_back_to_parent():
    short, detail = help_text("ssh.auth")
    assert "password" in short.lower() and detail
    assert help_text("ssh.nonexistent")[0] == help_text("ssh")[0]
    assert help_text("nothing") == ("", "")


def test_every_check_has_a_label_and_help():
    for check_id in ORDER:
        assert label(f"check.{check_id}") != f"check.{check_id}"
        assert help_text(check_id)[0]


def test_every_help_id_used_by_status_exists():
    ids = ["ssh.auth", "ssh.unreachable", "ssh.hostkey", "ssh.command", "clock.offset", "clock.nosource",
           "wifi.duplicate", "archive.none", "archive.atrisk", "unreadable"]
    data = tomllib.loads(resources.files("rs3d").joinpath("help", "en.toml").read_text())
    for hid in ids:
        node = data["help"]
        for part in hid.split("."):
            node = node[part]
        assert node["short"]


def test_guide_is_bundled():
    assert guide_markdown().startswith("# RS3D Guide")
