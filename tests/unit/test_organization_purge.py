from src.organizations.purge import purge_blocker


def test_nothing_blocks_a_trashed_organization_without_records() -> None:
    assert purge_blocker(0, 0, 0) is None


def test_open_activities_block_first() -> None:
    assert purge_blocker(1, 2, 3) == "organization_has_open_activities"


def test_certificates_block_before_pending_hours() -> None:
    assert purge_blocker(0, 1, 1) == "organization_has_certificates"


def test_pending_hours_block_on_their_own() -> None:
    assert purge_blocker(0, 0, 4) == "organization_has_pending_hours"
