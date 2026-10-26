from rs3d.app.pages.frequencies import box_range


def test_box_range_reads_a_line_x_brush_in_seconds():
    assert box_range({"areas": [{"coordRange": [1_000_000.0, 61_000.0 * 1000]}]}) == (1000, 61000)
    assert box_range({"areas": [{"coordRange": [[2_000_000.0, 1_000_000.0], [0, 1]]}]}) == (1000, 2000)  # reversed drag


def test_box_range_ignores_empty_or_tiny_boxes():
    assert box_range({"areas": []}) is None and box_range({}) is None
    assert box_range({"areas": [{"coordRange": [1_000_000.0, 1_005_000.0]}]}) is None  # 5 s
