from __future__ import annotations

import pathlib
import sys

import pytest

from scc_agent import creds


@pytest.mark.skipif(sys.platform == "win32", reason="DPAPI requires real Windows context for tests")
def test_dev_roundtrip(tmp_path: pathlib.Path):
    p = tmp_path / "creds.bin"
    creds.save("scc_live_abc", "secretvalue", path=p)
    kid, sec = creds.load(path=p)
    assert kid == "scc_live_abc"
    assert sec == "secretvalue"
