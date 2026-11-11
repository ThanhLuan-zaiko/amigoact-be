from src.certificates.router import VERIFY_LIMIT, VERIFY_WINDOW, verify_bucket


def test_verify_bucket_is_per_client_ip() -> None:
    assert verify_bucket("10.0.0.1") != verify_bucket("10.0.0.2")
    # Buckets end with the IP, which is how other IP limits are named and cleaned up.
    assert verify_bucket("10.0.0.1").endswith("10.0.0.1")


def test_limit_leaves_room_for_normal_use() -> None:
    # A person checking a few certificates in a row must never hit it.
    assert VERIFY_LIMIT >= 30
    assert VERIFY_WINDOW == 60
