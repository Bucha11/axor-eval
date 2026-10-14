"""Stage 0 reference wrapper (harness only; the kernel is not touched, no gate).

Tool outputs: every target identifier — e-mail, IBAN, URL (in any string), and the value of an
id field (id / id_ / file_id / event_id / email_id) — is replaced by a reference. Tool calls: a
reference in an argument is resolved back to its value before the tool runs. The user's request
is not rewritten. Two formats:
    opaque  ⟨iban:7f3⟩
    hint    ⟨iban:7f3…1234⟩   (last 4 characters of the value)
Reference ids are random 3-hex strings, unique within the session, not sequential; the same value
gets the same reference for the whole session.
"""
from __future__ import annotations

import random
import re
from typing import Any

import yaml
from pydantic import BaseModel

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
URL = re.compile(r"(?:https?://|www\.)[^\s<>\"'),]+")
ID_KEYS = {"id", "id_", "file_id", "event_id", "email_id"}
REF = re.compile(r"⟨(email|iban|url|id):([0-9a-f]{3})(?:…([^⟩]{1,8}))?⟩")
ANY_REF = re.compile(r"⟨[^⟩]{0,40}⟩")  # anything ref-shaped, valid or not


class RefTable:
    def __init__(self, fmt: str, seed: int | None = None) -> None:
        assert fmt in ("opaque", "hint")
        self.fmt = fmt
        self.rng = random.Random(seed)
        self.by_value: dict[tuple[str, str], str] = {}
        self.by_ref: dict[str, tuple[str, Any]] = {}  # token -> (kind, original value)

    def ref(self, kind: str, value: Any) -> str:
        key = (kind, str(value))
        if key in self.by_value:
            return self.by_value[key]
        while True:
            rid = f"{self.rng.randrange(16 ** 3):03x}"
            if all(not t.startswith(f"⟨{kind}:{rid}") for t in self.by_ref):
                break
        tail = str(value)[-4:]
        tok = f"⟨{kind}:{rid}⟩" if self.fmt == "opaque" else f"⟨{kind}:{rid}…{tail}⟩"
        self.by_value[key] = tok
        self.by_ref[tok] = (kind, value)
        return tok

    # ── tool output side ──────────────────────────────────────────────────────
    def mint_text(self, s: str) -> str:
        s = EMAIL.sub(lambda m: self.ref("email", m.group(0)), s)
        s = IBAN.sub(lambda m: self.ref("iban", m.group(0)), s)
        return URL.sub(lambda m: self.ref("url", m.group(0).rstrip(".;:!?")) + m.group(0)[len(m.group(0).rstrip(".;:!?")):], s)

    def mint(self, x: Any, key: str | None = None) -> Any:
        if isinstance(x, BaseModel):
            return self.mint(x.model_dump())
        if isinstance(x, dict):
            return {k: self.mint(v, k) for k, v in x.items()}
        if isinstance(x, list):
            return [self.mint(v, key) for v in x]
        if key in ID_KEYS and x is not None and not isinstance(x, (dict, list)):
            return self.ref("id", x)
        if isinstance(x, str):
            return self.mint_text(x)
        return x

    def format_output(self, result: Any) -> str:
        """As agentdojo's tool_result_to_str, on the minted value."""
        if isinstance(result, BaseModel):
            return yaml.safe_dump(self.mint(result), allow_unicode=True).strip()
        if isinstance(result, list):
            return yaml.safe_dump([self.mint(i) if isinstance(i, BaseModel) else self.mint(i) for i in result], allow_unicode=True).strip()
        if isinstance(result, str):
            return self.mint_text(result)
        return str(self.mint(result))

    # ── call side ─────────────────────────────────────────────────────────────
    def resolve(self, x: Any) -> Any:
        if isinstance(x, list):
            return [self.resolve(v) for v in x]
        if isinstance(x, dict):
            return {k: self.resolve(v) for k, v in x.items()}
        if isinstance(x, str):
            if x in self.by_ref:
                return self.by_ref[x][1]  # the original value, original type
            return ANY_REF.sub(lambda m: str(self.by_ref[m.group(0)][1]) if m.group(0) in self.by_ref else m.group(0), x)
        return x
