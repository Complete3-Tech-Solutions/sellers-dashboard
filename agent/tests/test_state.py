from __future__ import annotations

import pathlib

from scc_agent.state import Store


def test_upsert_and_get(tmp_path: pathlib.Path):
    s = Store(tmp_path / "state.db")
    assert s.get("foo.xlsx") is None
    s.upsert("foo.xlsx", "abc", 100, 1.0)
    row = s.get("foo.xlsx")
    assert row is not None and row.sha256 == "abc" and row.size_bytes == 100

    s.upsert("foo.xlsx", "def", 200, 2.0)
    row = s.get("foo.xlsx")
    assert row.sha256 == "def"

    s.upsert("bar.xlsx", "xyz", 1, 1.0)
    assert s.known_filenames() == {"foo.xlsx", "bar.xlsx"}

    s.delete("foo.xlsx")
    assert s.get("foo.xlsx") is None
    assert s.known_filenames() == {"bar.xlsx"}
