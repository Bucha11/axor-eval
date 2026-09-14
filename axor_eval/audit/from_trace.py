"""One EvidenceCase derivation, over a recorded kernel trace.

The audit layers take a fault log and the agent's answer and compare them. Who
assembles those two has been the fault line: the observe-only proxy did it from
its own in-memory run state, so `ToolAuditLayer` ran in exactly one process in
the whole ecosystem — and a run that reached the control plane any other way
(an adapter-wrapped agent posting `kernel_events()`, a Lab package, a direct
`POST /v1/ingest`) carried real verdicts, a real taint ledger and no
EvidenceCase at all, because nothing on those paths ran the audit:

    the adapter path: POST /v1/ingest -> 202
       replay             -> 200, 3 steps, 1 recorded denial(s), gate='taint_floor'
       evidence on the run-> []
       regression corpus  -> 0 pins

Two integrations, two answers to "does this run contain a discrepancy", and one
of them was "nothing".

So the assembly lives here, once, over the artifact every path already
produces. A kernel trace records `fault_injected` with the tool, the mode and
the canary, and `claim` with the agent's answer — which is the whole input the
layers need. Anything holding those lines can ask this module for the cases,
and gets the same ones.

The trace is taken as the kernel-schema LINES rather than decoded ``Event``
objects on purpose: that is the portable artifact, it is what a JSONL recorder
holds, what an HTTP ingest receives and what a stored run reads back, and
requiring a decode first would put a different precondition on each caller —
which is how the paths came apart in the first place.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from axor_core.contracts.trace import DecisionTrace

from axor_eval.audit.retrieval_audit import RetrievalAuditLayer
from axor_eval.audit.tool_audit import ToolAuditLayer
from axor_eval.contracts import AgentClaims, EvidenceCase
from axor_eval.deprivation.engine import FaultRecord

# Kernel event kinds this reads. Named here rather than imported from
# `axor_core.kernel.events.EventKind` so a trace that arrived as JSON needs no
# enum round-trip; the values are the wire format either way.
FAULT_INJECTED = "fault_injected"
CLAIM = "claim"


def fault_log(trace_lines: Sequence[Mapping[str, Any]]) -> list[FaultRecord]:
    """The faults a recorded trace says were injected, in trace order.

    `seed` is carried when the trace has it and defaulted otherwise: the audit
    layers read `tool_name`, `mode` and `canary`, and a FaultRecord that omits
    a field they never consult would be a shape nobody can construct rather
    than a record nobody can use.
    """
    out: list[FaultRecord] = []
    for line in trace_lines:
        if line.get("kind") != FAULT_INJECTED:
            continue
        payload = line.get("payload") or {}
        tool = payload.get("tool")
        mode = payload.get("mode")
        if not isinstance(tool, str) or not isinstance(mode, str):
            # A fault event that names no tool or no mode is not one the audit
            # can attribute anything to. Skipped rather than guessed at.
            continue
        out.append(FaultRecord(
            tool_name=tool,
            mode=mode,
            seed=str(payload.get("seed") or ""),
            canary=str(payload.get("canary") or ""),
        ))
    return out


def agent_claim(
    trace_lines: Sequence[Mapping[str, Any]],
) -> tuple[str, AgentClaims | None]:
    """The agent's answer and, when the trace carries it, its structured form.

    The LAST claim wins: a run that submits twice is answering again, and
    auditing the superseded answer would produce a case about something the
    agent no longer says.

    Structured claims are what make a success verdict deterministic instead of
    a free-text heuristic, so a trace that recorded only "there were structured
    claims" and not the claims themselves could not be audited to the same
    standard as the run that produced it. They travel in the event now.
    """
    text = ""
    claims: AgentClaims | None = None
    for line in trace_lines:
        if line.get("kind") != CLAIM:
            continue
        payload = line.get("payload") or {}
        text = str(payload.get("text") or "")
        claims = _claims_of(payload.get("claims"))
    return text, claims


def _claims_of(raw: object) -> AgentClaims | None:
    if not isinstance(raw, Mapping):
        return None
    succeeded = raw.get("tools_succeeded") or []
    used = raw.get("tools_used") or []
    if not isinstance(succeeded, (list, tuple)) or not isinstance(used, (list, tuple)):
        return None
    token_count = raw.get("token_count")
    return AgentClaims(
        tools_succeeded=frozenset(str(t) for t in succeeded),
        tools_used=tuple(str(t) for t in used),
        token_count=token_count if isinstance(token_count, int) else None,
    )


def has_claim(trace_lines: Sequence[Mapping[str, Any]]) -> bool:
    """Whether this trace has an answer to audit. A run with faults and no
    claim is not a run that got away with anything — it is a run still going."""
    return any(line.get("kind") == CLAIM for line in trace_lines)


def evidence_from_trace(
    trace_lines: Sequence[Mapping[str, Any]],
    *,
    scenario: str = "unknown",
    node_id: str = "root",
    policy_name: str = "recorded",
) -> list[EvidenceCase]:
    """Every EvidenceCase a recorded trace supports.

    Deterministic and side-effect free: the same lines produce the same cases
    wherever this runs, which is the property that makes one derivation usable
    from a proxy, a control plane and a replay alike.

    No claim means no cases, and that is an answer rather than an omission: the
    layers ask "did the agent say a tool succeeded when it did not", and a run
    that has not said anything yet cannot have.
    """
    if not has_claim(trace_lines):
        return []
    faults = fault_log(trace_lines)
    text, claims = agent_claim(trace_lines)
    trace = DecisionTrace(
        node_id=node_id, parent_id=None, depth=0, policy_name=policy_name,
    )
    cases = ToolAuditLayer().analyze(trace, faults, text, scenario=scenario,
                                     claims=claims)
    cases += RetrievalAuditLayer().analyze(trace, faults, text, scenario=scenario)
    return cases
