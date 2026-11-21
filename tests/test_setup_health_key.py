"""setup health reads the same key as every other axor command."""
from __future__ import annotations

import argparse

import pytest

from axor_eval.setup_health import __main__ as cli


def _key(monkeypatch: pytest.MonkeyPatch, **env: str) -> str:
    for k in ("AXOR_INGEST_KEY", "AXOR_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    seen: dict[str, str] = {}
    parse = argparse.ArgumentParser.parse_args

    def spy(self: argparse.ArgumentParser, args: object = None, namespace: object = None) -> object:
        ns = parse(self, args, namespace)  # type: ignore[arg-type]
        seen["key"] = ns.key
        raise SystemExit(0)

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", spy)
    with pytest.raises(SystemExit):
        cli.main(["run", "spec.json"])
    return seen["key"]


def test_the_ingest_key_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _key(monkeypatch, AXOR_INGEST_KEY="k-ingest") == "k-ingest"


def test_the_old_name_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _key(monkeypatch, AXOR_API_KEY="k-old") == "k-old"


def test_the_connection_axor_wrap_saved_is_used(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from axor_wrap import connection

    monkeypatch.setattr(connection, "path", lambda: tmp_path / "connection.json")
    connection.save("https://plane.example", "k-saved")
    assert _key(monkeypatch) == "k-saved"
    from axor_eval.plane_connection import plane_url

    assert plane_url() == "https://plane.example"
