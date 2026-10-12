import numpy as np
import pytest

from rs3d.core.codegen import generate
from rs3d.core.export import load_processed
from rs3d.core.models import Selection
from tests.conftest import GAP_END, GAP_START, T_START


def run(code: str):
    namespace: dict = {}
    exec(compile(code, "<generated>", "exec"), namespace)
    return namespace["st"]


def assert_same(a, b):
    a = sorted(a, key=lambda tr: (tr.id, tr.stats.starttime))
    b = sorted(b, key=lambda tr: (tr.id, tr.stats.starttime))
    assert len(a) == len(b)
    for x, y in zip(a, b):
        assert x.id == y.id and x.stats.starttime == y.stats.starttime
        np.testing.assert_array_equal(x.data, y.data)


@pytest.mark.parametrize("kw", [
    {},
    {"filter": (1.0, 10.0)},
    {"channels": ("EHZ",), "start": GAP_START - 30, "end": GAP_END + 30},
])
def test_generated_code_matches_export(store, kw):
    args = dict(network="AM", station="R77A7", location="00", start=T_START + 10, end=T_START + 40)
    args.update(kw)
    s = Selection(**args)
    assert_same(run(generate(s, store.root)), load_processed(store, s))


def test_generated_code_with_response(store, inventory, tmp_path):
    inv_path = tmp_path / "AM.R77A7.xml"
    inventory.write(str(inv_path), format="STATIONXML")
    s = Selection("AM", "R77A7", "00", T_START + 10, T_START + 40, units="m/s", filter=(1.0, 10.0))
    code = generate(s, store.root, inv_path)
    assert "read_inventory" in code
    assert_same(run(code), load_processed(store, s, inventory))


def test_m_s_without_inventory_path_is_rejected(store):
    s = Selection("AM", "R77A7", "00", T_START, T_START + 10, units="m/s")
    with pytest.raises(ValueError):
        generate(s, store.root)


def test_paths_with_quotes_and_backslashes_are_safe(store):
    s = Selection("AM", "R77A7", "00", T_START, T_START + 10)
    code = generate(s, store.root / "it's\\odd")
    compile(code, "<generated>", "exec")
