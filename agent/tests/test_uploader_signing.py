from __future__ import annotations

import hashlib
import hmac

from scc_agent.uploader import _build_headers


def test_signature_format():
    headers = _build_headers("POST", "/api/snapshot/start", b"{}", "scc_live_x", "secret")
    assert headers["Authorization"] == "Bearer scc_live_x.secret"
    msg = (
        f"POST\n/api/snapshot/start\n{headers['X-Timestamp']}\n{headers['X-Nonce']}\n"
        f"{hashlib.sha256(b'{}').hexdigest()}"
    ).encode()
    expected = hmac.new(b"secret", msg, hashlib.sha256).hexdigest()
    assert headers["X-Signature"] == expected
