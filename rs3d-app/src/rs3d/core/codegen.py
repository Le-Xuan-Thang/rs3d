"""Generate ObsPy code that reproduces exactly what export.load_processed() returns."""

from __future__ import annotations

from pathlib import Path

from rs3d.core.models import Selection


def generate(sel: Selection, sds_root: Path, inventory_path: Path | None = None) -> str:
    if sel.units == "m/s" and inventory_path is None:
        raise ValueError("units 'm/s' need inventory_path")
    lines = [
        "from obspy import Stream, UTCDateTime",
        "from obspy.clients.filesystem.sds import Client",
    ]
    if sel.units == "m/s":
        lines.append("from obspy import read_inventory")
    lines += [
        "",
        f"client = Client({str(sds_root)!r})",
        f"start = UTCDateTime({str(sel.start)!r})",
        f"end = UTCDateTime({str(sel.end)!r})",
        "",
        "st = Stream()",
        f"for channel in {tuple(sel.channels)!r}:",
        f"    st += client.get_waveforms({sel.network!r}, {sel.station!r}, {sel.location!r}, channel, start, end)",
        "st.trim(start, end)",
    ]
    if sel.units == "m/s":
        lines += [
            "",
            "# counts -> ground velocity (m/s)",
            f"inv = read_inventory({str(inventory_path)!r})",
            'st.remove_response(inventory=inv, output="VEL")',
        ]
    if sel.filter is not None:
        fmin, fmax = sel.filter
        lines += [
            "",
            'st.detrend("demean")',
            f'st.filter("bandpass", freqmin={fmin!r}, freqmax={fmax!r}, corners=4, zerophase=True)',
        ]
    lines += ["", "print(st)", ""]
    return "\n".join(lines)
