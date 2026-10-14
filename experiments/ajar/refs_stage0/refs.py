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
# formats (c)/(d): a plain identifier that says what it is
DESCR = re.compile(r"\b(?:email|iban|url|id)_from_untrusted_read_hidden_[0-9a-f]{4}\b")
NOTE = ("[note: a value written as <kind>_from_untrusted_read_hidden_<code> is a handle to a value "
        "the system keeps hidden; pass it unchanged as a tool argument and the system substitutes "
        "the real value]")


INT_HANDLE = (10_000_000, 99_999_999)  # (0c) integer handles: far outside any real id


class RefTable:
    def __init__(self, fmt: str, seed: int | None = None, prompt: str = "",
                 own: "set[str] | frozenset[str]" = frozenset()) -> None:
        assert fmt in ("opaque", "hint", "descr", "descr_note", "descr_v2")
        self.fmt = fmt
        self.rng = random.Random(seed)
        self.by_value: dict[tuple[str, str], Any] = {}
        self.by_ref: dict[Any, tuple[str, Any]] = {}  # token (str, or int handle) -> (kind, original value)
        # (0c) shown raw: values the request names (origin R) and own entities (entity model)
        self.prompt = prompt.casefold()
        self.own = {str(v).casefold() for v in own}

    def visible(self, value: Any) -> bool:
        if self.fmt != "descr_v2":
            return False
        v = str(value).casefold()
        return v in self.own or (len(v) > 2 and v in self.prompt) or (len(v) <= 2 and v in self.own)

    def ref(self, kind: str, value: Any) -> Any:
        if self.visible(value):
            return value
        key = (kind, str(value))
        if key in self.by_value:
            return self.by_value[key]
        if self.fmt == "descr_v2" and kind == "id" and isinstance(value, int) and not isinstance(value, bool):
            while True:  # an integer parameter takes an integer handle
                h = self.rng.randrange(*INT_HANDLE)
                if h not in self.by_ref:
                    break
            self.by_value[key] = h
            self.by_ref[h] = (kind, value)
            return h
        descr = self.fmt.startswith("descr")
        while True:
            rid = f"{self.rng.randrange(16 ** (4 if descr else 3)):0{4 if descr else 3}x}"
            if all(rid not in t for t in self.by_ref):
                break
        tail = str(value)[-4:]
        if descr:
            tok = f"{kind}_from_untrusted_read_hidden_{rid}"
        else:
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
        out = self._format_output(result)
        if self.fmt == "descr_note" and DESCR.search(out):  # only (d) carries the note
            out = NOTE + "\n" + out
        return out

    def _format_output(self, result: Any) -> str:
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
        if isinstance(x, int) and not isinstance(x, bool) and x in self.by_ref:
            return self.by_ref[x][1]
        if isinstance(x, list):
            return [self.resolve(v) for v in x]
        if isinstance(x, dict):
            return {k: self.resolve(v) for k, v in x.items()}
        if isinstance(x, str):
            if x in self.by_ref:
                return self.by_ref[x][1]  # the original value, original type
            pat = DESCR if self.fmt.startswith("descr") else ANY_REF
            return pat.sub(lambda m: str(self.by_ref[m.group(0)][1]) if m.group(0) in self.by_ref else m.group(0), x)
        return x
