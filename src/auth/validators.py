"""Field validators for the account API.

Errors use PydanticCustomError, so their `type` is a stable code for clients.
"""

import re
from itertools import pairwise

from pydantic_core import PydanticCustomError

VIETNAM_LOCAL_PHONE = re.compile(r"^0(\d{9,10})$")
VIETNAM_INTERNATIONAL_PHONE = re.compile(r"^\+?84(\d{9,10})$")
OTHER_INTERNATIONAL_PHONE = re.compile(r"^\+(?!84)[1-9]\d{6,13}$")
PHONE_SEPARATORS = re.compile(r"[\s.()-]")
TAX_CODE = re.compile(r"^(\d{10})(?:-?(\d{3}))?$")
LEGAL_ID_NUMBER = re.compile(r"^(\d{9}|\d{12})$")
LEGAL_ID_PASSPORT = re.compile(r"^(?=.*[A-Z])[A-Z0-9]{6,20}$")
MAX_REPEATED_PATTERN = 4
MIN_PERSONAL_PART = 4

# Compared after lowercasing and removing trailing digits and symbols,
# so "Password123!" counts as "password".
COMMON_PASSWORD_BASES = frozenset(
    {
        "abc",
        "abcd",
        "abcdef",
        "abcdefgh",
        "admin",
        "administrator",
        "amigoact",
        "anhyeuem",
        "asdf",
        "asdfgh",
        "asdfghjkl",
        "changeme",
        "dragon",
        "emyeuanh",
        "football",
        "hanoi",
        "iloveyou",
        "letmein",
        "login",
        "matkhau",
        "master",
        "pass",
        "passw0rd",
        "password",
        "qazwsx",
        "qwe",
        "qwer",
        "qwerty",
        "qwertyuiop",
        "saigon",
        "secret",
        "sunshine",
        "superman",
        "test",
        "vietnam",
        "welcome",
        "yeuem",
        "yeuemnhieu",
        "zxcvbn",
        "zxcvbnm",
    }
)


def normalize_phone(value: str) -> str:
    """Return one canonical form, so one number cannot register twice."""
    compact = PHONE_SEPARATORS.sub("", value)
    for pattern in (VIETNAM_LOCAL_PHONE, VIETNAM_INTERNATIONAL_PHONE):
        match = pattern.match(compact)
        if match:
            return f"+84{match.group(1)}"
    if OTHER_INTERNATIONAL_PHONE.match(compact):
        return compact
    raise PydanticCustomError("phone_invalid", "Phone number is not valid")


def normalize_tax_code(value: str) -> str:
    """Accept 10 digits, or 13 digits for a branch, stored as NNNNNNNNNN-NNN."""
    match = TAX_CODE.match(value.strip())
    if not match:
        raise PydanticCustomError("tax_code_invalid", "Tax code is not valid")
    head, branch = match.groups()
    return f"{head}-{branch}" if branch else head


def normalize_legal_id(value: str) -> str:
    """Accept a 9 or 12 digit national ID, or a passport number with letters."""
    compact = value.strip().upper()
    if LEGAL_ID_NUMBER.match(compact) or LEGAL_ID_PASSPORT.match(compact):
        return compact
    raise PydanticCustomError("legal_id_invalid", "Legal ID is not valid")


def _is_sequence(text: str) -> bool:
    steps = {ord(right) - ord(left) for left, right in pairwise(text)}
    return steps in ({1}, {-1})


def _repeats_short_pattern(text: str) -> bool:
    for size in range(1, MAX_REPEATED_PATTERN + 1):
        if len(text) % size == 0 and text == text[:size] * (len(text) // size):
            return True
    return False


def is_common_password(password: str) -> bool:
    lowered = password.lower()
    base = re.sub(r"[\d\W_]+$", "", lowered)
    return (
        base in COMMON_PASSWORD_BASES
        or lowered in COMMON_PASSWORD_BASES
        or _is_sequence(lowered)
        or _repeats_short_pattern(lowered)
    )


def has_required_characters(password: str) -> bool:
    """Require an uppercase and a lowercase letter, a digit, and a special character."""
    return (
        any(character.isupper() for character in password)
        and any(character.islower() for character in password)
        and any(character.isdigit() for character in password)
        and any(not character.isalnum() for character in password)
    )


def check_password_strength(password: str) -> str:
    if not has_required_characters(password):
        raise PydanticCustomError(
            "password_too_weak",
            "Password needs uppercase, lowercase, digit, and special characters",
        )
    if is_common_password(password):
        raise PydanticCustomError("password_common", "Password is too common")
    return password


def password_is_personal(password: str, email: str, full_name: str) -> bool:
    """True when the password contains the email name or the full name."""
    lowered = password.lower()
    parts = (email.split("@")[0].lower(), "".join(full_name.lower().split()))
    return any(len(part) >= MIN_PERSONAL_PART and part in lowered for part in parts)
