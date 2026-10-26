from datetime import date

from rs3d.app.pages.data import download_text
from rs3d.core.archive import BYTES_PER_SECOND, Job


def test_download_text_counts_parts_and_size():
    assert download_text([]) == "To download: 0"
    jobs = [Job("EHZ", date(2026, 10, 12), 0.0, 600.0), Job("EHN", date(2026, 10, 12), 0.0, 600.0)]
    assert download_text(jobs) == f"To download: 2 · {2 * 600 * BYTES_PER_SECOND / 1e6:.1f} MB"
