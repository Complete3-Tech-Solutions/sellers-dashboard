from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet
from jose import JWTError, jwt

from app.settings import settings

_ph = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=4)


def hash_password(plain: str) -> str:
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        _ph.verify(hashed, plain)
        return True
    except VerifyMismatchError:
        return False


def needs_rehash(hashed: str) -> bool:
    return _ph.check_needs_rehash(hashed)


def _ensure_keys() -> tuple[str, str]:
    if settings.jwt_private_key_pem and settings.jwt_public_key_pem:
        return settings.jwt_private_key_pem, settings.jwt_public_key_pem
    if settings.env != "dev":
        raise RuntimeError("JWT keys must be configured outside dev")
    # Generate an ephemeral dev keypair so local boots work without manual setup.
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    pub = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    settings.jwt_private_key_pem = priv
    settings.jwt_public_key_pem = pub
    return priv, pub


def issue_access_token(*, user_id: uuid.UUID, tenant_id: uuid.UUID, role: str) -> str:
    priv, _ = _ensure_keys()
    now = datetime.now(tz=UTC)
    claims = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.jwt_access_ttl_seconds)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, priv, algorithm="RS256")


def decode_access_token(token: str) -> dict[str, Any]:
    _, pub = _ensure_keys()
    try:
        return jwt.decode(token, pub, algorithms=["RS256"])
    except JWTError as exc:
        raise ValueError(str(exc)) from exc


def new_refresh_token() -> tuple[str, str]:
    """Returns (plaintext, sha256_hex)."""
    raw = secrets.token_urlsafe(48)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def hash_refresh_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def new_api_key() -> tuple[str, str, str]:
    """Returns (full_plaintext, key_id, secret)."""
    key_id = "scc_live_" + secrets.token_urlsafe(12)
    secret = secrets.token_urlsafe(48)
    return f"{key_id}.{secret}", key_id, secret


def sha256_hex(b: bytes | str) -> str:
    if isinstance(b, str):
        b = b.encode()
    return hashlib.sha256(b).hexdigest()


def _fernet() -> Fernet:
    key = settings.kms_fernet_key
    if not key:
        if settings.env != "dev":
            raise RuntimeError("KMS_FERNET_KEY must be set outside dev")
        # Dev: deterministic but ephemeral
        seed = b"dev-only-do-not-use-in-prod" + b"0" * 16
        key = base64.urlsafe_b64encode(seed[:32]).decode()
        settings.kms_fernet_key = key
    return Fernet(key.encode())


def encrypt_secret(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode())


def decrypt_secret(ciphertext: bytes) -> str:
    return _fernet().decrypt(ciphertext).decode()


def hmac_message(method: str, path: str, ts: str, nonce: str, body: bytes) -> bytes:
    body_hash = sha256_hex(body)
    return f"{method}\n{path}\n{ts}\n{nonce}\n{body_hash}".encode()


def hmac_sign(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def hmac_verify(secret: str, message: bytes, signature: str) -> bool:
    expected = hmac_sign(secret, message)
    return hmac.compare_digest(expected, signature)


def now_unix() -> int:
    return int(time.time())
