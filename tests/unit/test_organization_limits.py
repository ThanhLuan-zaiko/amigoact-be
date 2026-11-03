from src.organizations.service import MAX_OWNED_ORGANIZATIONS, can_own_another


def test_owner_below_the_limit_can_own_another() -> None:
    assert can_own_another(0)
    assert can_own_another(MAX_OWNED_ORGANIZATIONS - 1)


def test_owner_at_the_limit_cannot_own_another() -> None:
    assert not can_own_another(MAX_OWNED_ORGANIZATIONS)
    assert not can_own_another(MAX_OWNED_ORGANIZATIONS + 1)
