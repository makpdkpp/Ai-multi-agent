from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from pwdlib import PasswordHash

password_hasher = PasswordHash.recommended()
_dummy_password_hash = password_hasher.hash("not-a-real-password")
_email_local_pattern = re.compile(r"^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+$")
_domain_label_pattern = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if password_hash is None:
        password_hasher.verify(password, _dummy_password_hash)
        return False
    return password_hasher.verify(password, password_hash)


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def secure_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


def normalized_email(email: str) -> str:
    normalized = email.strip().casefold()
    if len(normalized) > 254 or normalized.count("@") != 1:
        raise ValueError("Enter a valid email address")

    local_part, domain = normalized.split("@")
    if (
        not local_part
        or len(local_part) > 64
        or local_part.startswith(".")
        or local_part.endswith(".")
        or ".." in local_part
        or not _email_local_pattern.fullmatch(local_part)
    ):
        raise ValueError("Enter a valid email address")

    labels = domain.split(".")
    if not domain or len(domain) > 253 or any(
        not _domain_label_pattern.fullmatch(label) for label in labels
    ):
        raise ValueError("Enter a valid email address")
    return normalized
