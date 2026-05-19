from __future__ import annotations

import hashlib
import hmac
import logging
import pathlib
import platform
import time
import uuid

import requests
from requests.exceptions import RequestException

from scc_agent import __version__
from scc_agent.creds import load as load_creds

log = logging.getLogger(__name__)


def _build_headers(method: str, path: str, body: bytes, key_id: str, secret: str) -> dict[str, str]:
    ts = str(int(time.time()))
    nonce = str(uuid.uuid4())
    body_hash = hashlib.sha256(body).hexdigest()
    msg = f"{method}\n{path}\n{ts}\n{nonce}\n{body_hash}".encode()
    sig = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
    return {
        "Authorization": f"Bearer {key_id}.{secret}",
        "X-Timestamp": ts,
        "X-Nonce": nonce,
        "X-Signature": sig,
        "User-Agent": f"scc-agent/{__version__} ({platform.platform()})",
    }


class Uploader:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def _signed(self, method: str, path: str, *, body: bytes = b"", **kw) -> requests.Response:
        key_id, secret = load_creds()
        headers = _build_headers(method, path, body, key_id, secret)
        if "headers" in kw:
            headers.update(kw.pop("headers"))
        url = self.base_url + path
        return self.session.request(
            method, url, data=body if body else None, headers=headers, timeout=60, **kw
        )

    def start_snapshot(self, folder_path_hash: str | None = None) -> str:
        import json as _json

        body = _json.dumps(
            {"agent_version": __version__, "folder_path_hash": folder_path_hash}
        ).encode()
        r = self._signed(
            "POST",
            "/api/snapshot/start",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        r.raise_for_status()
        return r.json()["snapshot_id"]

    def upload_file(self, snapshot_id: str, path: pathlib.Path, sha256: str) -> None:
        # Multipart upload — we sign the assembled multipart body
        import io
        import secrets

        path_segment = f"/api/snapshot/{snapshot_id}/file"
        boundary = "----scc" + secrets.token_hex(8)
        with path.open("rb") as fp:
            data = fp.read()

        parts = []
        def field(name: str, value: str) -> None:
            parts.append(
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n".encode()
            )

        field("filename", path.name)
        field("sha256", sha256)
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            f"Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n".encode()
        )
        parts.append(data)
        parts.append(f"\r\n--{boundary}--\r\n".encode())
        body = b"".join(parts)

        r = self._signed(
            "POST",
            path_segment,
            body=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        r.raise_for_status()

    def commit_snapshot(self, snapshot_id: str, manifest: list[dict]) -> dict:
        import json as _json

        body = _json.dumps({"manifest": manifest}).encode()
        r = self._signed(
            "POST",
            f"/api/snapshot/{snapshot_id}/commit",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        r.raise_for_status()
        return r.json()

    def snapshot_status(self, snapshot_id: str) -> dict:
        r = self._signed("GET", f"/api/snapshot/{snapshot_id}")
        r.raise_for_status()
        return r.json()


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def with_retry(fn, *args, max_attempts: int = 6, **kwargs):
    """Exponential backoff for transient errors. 4xx (non-429) is fatal."""
    delays = [1, 5, 30, 5 * 60, 30 * 60, 2 * 3600]
    for attempt in range(max_attempts):
        try:
            return fn(*args, **kwargs)
        except RequestException as exc:
            resp = getattr(exc, "response", None)
            if resp is not None and 400 <= resp.status_code < 500 and resp.status_code != 429:
                log.error("permanent error %s: %s", resp.status_code, resp.text[:200])
                raise
            wait = delays[min(attempt, len(delays) - 1)]
            log.warning(
                "transient error on attempt %s, sleeping %ss: %s", attempt + 1, wait, exc
            )
            time.sleep(wait)
    raise RuntimeError("max retries exhausted")
