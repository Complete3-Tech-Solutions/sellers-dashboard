from __future__ import annotations

import uuid

from app.security import (
    decode_access_token,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    hmac_message,
    hmac_sign,
    hmac_verify,
    issue_access_token,
    new_api_key,
    new_refresh_token,
    verify_password,
)


def test_password_hash_roundtrip():
    h = hash_password("hunter22!ok")
    assert verify_password("hunter22!ok", h)
    assert not verify_password("wrong", h)


def test_jwt_roundtrip():
    uid = uuid.uuid4()
    tid = uuid.uuid4()
    token = issue_access_token(user_id=uid, tenant_id=tid, role="admin")
    claims = decode_access_token(token)
    assert claims["sub"] == str(uid)
    assert claims["tid"] == str(tid)
    assert claims["role"] == "admin"


def test_refresh_token_distinct():
    a, _ = new_refresh_token()
    b, _ = new_refresh_token()
    assert a != b


def test_api_key_format():
    full, kid, secret = new_api_key()
    assert full == f"{kid}.{secret}"
    assert kid.startswith("scc_live_")
    assert len(secret) >= 32


def test_fernet_roundtrip():
    ct = encrypt_secret("topsecret")
    assert decrypt_secret(ct) == "topsecret"


def test_hmac_sign_verify():
    secret = "s3kr3t"
    body = b"hello world"
    msg = hmac_message("POST", "/api/snapshot/start", "1700000000", "nonce-1", body)
    sig = hmac_sign(secret, msg)
    assert hmac_verify(secret, msg, sig)
    assert not hmac_verify(secret, msg, "00" + sig[2:])
