from rs3d.app.state import AppState
from rs3d.core.paths import AppPaths


class NoKeyring:
    def get_password(self, *a):
        return None

    def set_password(self, *a):
        pass

    def delete_password(self, *a):
        pass


def make(tmp_path):
    from rs3d.core.devices import Passwords
    return AppState(AppPaths(tmp_path), passwords=Passwords(NoKeyring()))


def test_data_prefs_default_and_roundtrip(tmp_path):
    state = make(tmp_path)
    assert state.data_prefs == {"units": "counts", "filter": False, "fmin": 1.0, "fmax": 10.0, "station": None}
    state.set_data_prefs(units="m/s", filter=True, fmin=0.5, fmax=5.0, station="AM.R77A7.00")
    again = make(tmp_path)
    assert again.data_prefs == {"units": "m/s", "filter": True, "fmin": 0.5, "fmax": 5.0,
                                "station": "AM.R77A7.00"}


def test_prefs_do_not_clobber_other_settings(tmp_path):
    state = make(tmp_path)
    state.set_use_local_time(True)
    state.set_data_prefs(units="m/s")
    again = make(tmp_path)
    assert again.use_local_time is True and again.data_prefs["units"] == "m/s"


def test_bad_values_in_file_fall_back_to_defaults(tmp_path):
    (tmp_path / "settings.toml").write_text('[data_prefs]\nunits = "furlongs"\nfmin = "x"\nfilter = true\n')
    state = make(tmp_path)
    assert state.data_prefs["units"] == "counts" and state.data_prefs["fmin"] == 1.0
    assert state.data_prefs["filter"] is True
