from rs3d.app.latest import LatestOnly


def test_only_the_newest_token_is_current():
    latest = LatestOnly()
    first = latest.next()
    assert latest.is_current(first)
    second = latest.next()
    assert latest.is_current(second) and not latest.is_current(first)
