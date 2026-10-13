"""Two follow-ups to the residual routes (no model, no API).

    python residuals_extra.py baseline_diff   -> results/residuals_baseline_diff.json
    python residuals_extra.py traj_floor      -> results/residuals_traj_floor.json

baseline_diff  why the floor_scope base row (addressee + declared secrets) differs
               from the paper row (e0-ctx): the same Ajar tests, verdict by verdict.
traj_floor     cost of each floor_scope on recorded benign trajectories: AgentDojo's
               shipped no-attack runs of the three replay models (none/none.json,
               slack/user_task_4 excluded -> 3 x 96). Each recorded call is evaluated
               in order on a governor (configuration (a), declared secrets) with every
               recorded output registered, as the trajectory actually ran; a call is
               "held by the floor" when it is denied on the confidentiality axis.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import axor_ajar  # noqa: E402
import residuals as R  # noqa: E402

from axor_core.governor import ToolCallGovernor  # noqa: E402

MODELS = ("gpt-4o-2024-05-13", "claude-3-5-sonnet-20241022", "gpt-4o-mini-2024-07-18")


def baseline_diff():
    import paper_opl
    import run_ajar
    from ajar.core.types import Label
    from ajar.runner import run_defense
    data = run_ajar.load(None)
    paper = axor_ajar.AxorDefense("paper e0-ctx", integrity_default="context", integrity_origins="request-only")
    decl = R.floor_defense("a|addressee+declared secrets", None, "oracle", "addressee")
    runs_p, runs_d, diffs = [], [], []
    per_task = []
    for spec, probes in data:
        lp, ld = len(paper.log), len(decl.log)
        rp, rd = run_defense(paper, spec, probes), run_defense(decl, spec, probes)
        runs_p.append((spec, probes, rp))
        runs_d.append((spec, probes, rd))
        logd = decl.log[ld:]
        changed = 0
        for i, (x, y) in enumerate(zip(rp, rd)):
            if x.verdict is not y.verdict:
                changed += 1
                diffs.append({"task": str(spec.task), "suite": spec.task.suite, "prefix": list(x.probe.context.prefix),
                              "tool": x.probe.candidate.tool, "expected": x.probe.expected_label.name,
                              "paper": x.verdict.name, "declared": y.verdict.name,
                              "declared_category": logd[i]["category"],
                              "prefix_tools": [spec.plan[j].tool for j in x.probe.context.prefix]})
        if changed:
            per_task.append({"task": str(spec.task), "changed": changed})
    mp = paper_opl.summarize(paper.name, runs_p)
    md = paper_opl.summarize(decl.name, runs_d)
    by = Counter((d["suite"], d["tool"], d["expected"], d["paper"], d["declared"], d["declared_category"]) for d in diffs)
    secret_in_prefix = sum(1 for d in diffs if set(d["prefix_tools"]) & R.SECRETS[d["suite"]])
    # per-task sufficiency / provisioning change
    from ajar.score.scorer import score
    suff = []
    for (spec, probes, rp), (_, _, rd) in zip(runs_p, runs_d):
        if not spec.is_gradeable:
            continue
        a, b = score("p", probes, rp), score("d", probes, rd)
        if a.sufficiency != b.sufficiency or a.gate_passed != b.gate_passed:
            suff.append({"task": str(spec.task), "sufficiency": [a.sufficiency, b.sufficiency],
                         "provisioned": [bool(a.gate_passed), bool(b.gate_passed)]})
    out = {"paper": {k: v for k, v in mp.items() if k != "admitted_attack_calls"},
           "declared": {k: v for k, v in md.items() if k != "admitted_attack_calls"},
           "divergent_tests": len(diffs), "divergent_with_secret_read_in_prefix": secret_in_prefix,
           "by_kind": [{"suite": k[0], "tool": k[1], "expected": k[2], "paper": k[3], "declared": k[4],
                        "category": k[5], "n": n} for k, n in by.most_common()],
           "tasks_changed": per_task, "gradeable_tasks_changed": suff, "diffs": diffs[:300]}
    json.dump(out, open(os.path.join(R.RESULTS, "residuals_baseline_diff.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k not in ("diffs",)}, indent=1)[:6000])


def _gov(suite, prompt, scope, secrets=True):
    cfg = R.base_cfg(suite, secrets=secrets, scope=scope)
    g = ToolCallGovernor(**cfg.as_governor_kwargs())
    g.register_task(prompt)
    return g


def _parse(v):
    import ast
    if isinstance(v, str):
        try:
            return ast.literal_eval(v)
        except (ValueError, SyntaxError):
            return v
    return v


def traj_floor():
    root = os.path.join(os.environ.get("AJAR_AGENTDOJO_ROOT", "bench/agentdojo"), "runs")
    variants = [("addressee (paper secrets)", "addressee", False)] + [(s, s, True) for s in R.SCOPES]
    agg = {v[0]: defaultdict(lambda: {"trajectories": 0, "calls": 0, "held_calls": 0, "tasks_hit": 0,
                                       "successful_tasks_hit": 0, "held_tools": Counter()}) for v in variants}
    n_traj = 0
    for model in MODELS:
        for suite in ("banking", "slack", "travel", "workspace"):
            for path in sorted(glob.glob(os.path.join(root, model, suite, "user_task_*", "none", "none.json"))):
                run = json.load(open(path))
                if (suite, run["user_task_id"]) == ("slack", "user_task_4"):
                    continue
                n_traj += 1
                msgs = run["messages"]
                prompt = next(m["content"] for m in msgs if m["role"] == "user")
                if isinstance(prompt, list):
                    prompt = "".join(b.get("content", "") for b in prompt)
                outputs = {m.get("tool_call_id"): m.get("content") for m in msgs if m["role"] == "tool"}
                calls = []
                for m in msgs:
                    if m["role"] == "assistant" and m.get("tool_calls") not in (None, "None"):
                        for tc in _parse(m["tool_calls"]) or []:
                            calls.append((tc["function"], dict(tc["args"]), outputs.get(tc.get("id"))))
                for name, scope, secrets in variants:
                    g = _gov(suite, prompt, scope, secrets)
                    held = []
                    for tool, args, out in calls:
                        d = g.evaluate(tool, dict(args))
                        if not d.allowed and "confidentiality" in (d.reason or ""):
                            held.append(tool)
                        # the trajectory as it ran: every recorded output is registered
                        if d.allowed:
                            if out is not None:
                                g.register_output(d, out)
                        else:
                            _register_anyway(g, tool, args, out)
                    a = agg[name][suite]
                    a["trajectories"] += 1
                    a["calls"] += len(calls)
                    a["held_calls"] += len(held)
                    a["tasks_hit"] += int(bool(held))
                    a["successful_tasks_hit"] += int(bool(held) and bool(run.get("utility")))
                    a["held_tools"].update(held)
    out = {}
    for name in agg:
        tot = {k: sum(agg[name][s][k] for s in agg[name]) for k in
               ("trajectories", "calls", "held_calls", "tasks_hit", "successful_tasks_hit")}
        out[name] = {"all": tot, "suites": {s: {**v, "held_tools": dict(v["held_tools"])} for s, v in agg[name].items()}}
        print(name, tot)
    out["n_trajectories"] = n_traj
    json.dump(out, open(os.path.join(R.RESULTS, "residuals_traj_floor.json"), "w"), indent=1)


def _register_anyway(g, tool, args, out):
    """A recorded output of a call the governor would deny: the trajectory still ran
    it, so its provenance is registered as if allowed (a fresh, unconstrained decision
    for the same call carries the normalized intent the ledger needs)."""
    if out is None:
        return
    shadow = ToolCallGovernor(untrusted_sources=g._untrusted_sources, sensitive_sources=g._sensitive_sources)
    d = shadow.evaluate(tool, dict(args))
    if d.allowed:
        g.register_output(d, out)


def grants_return():
    """Admissions in (b) and not in (a), over Ajar's tests, split by the probe's
    expected label: ALLOW (a plan call — what grants give back in utility) vs DENY
    (an attacker / over-privilege candidate). Also (c)-oracle vs (a)."""
    import run_ajar
    from ajar.runner import run_defense
    data = run_ajar.load(None)
    a = axor_ajar.AxorDefense("a", integrity_default="context", integrity_origins="request-only")
    b = axor_ajar.grants_defense("b", "L1+L2s", grant_args=R.r0())
    c = axor_ajar.grants_defense("c", "L1+L2s+L4", grant_args=R.r0(), confirm="oracle")
    out = {"b_not_a": Counter(), "c_not_a": Counter(), "a_not_b": Counter(), "examples_b_not_a_deny": []}
    for spec, probes in data:
        ra, rb, rc = run_defense(a, spec, probes), run_defense(b, spec, probes), run_defense(c, spec, probes)
        for x, y, z in zip(ra, rb, rc):
            lab = x.probe.expected_label.name
            A, B, C = (r.verdict.name == "ALLOW" for r in (x, y, z))
            if B and not A:
                out["b_not_a"][lab] += 1
                if lab == "DENY" and len(out["examples_b_not_a_deny"]) < 40:
                    out["examples_b_not_a_deny"].append({"task": str(spec.task), "k": len(x.probe.context.prefix),
                                                         "tool": x.probe.candidate.tool,
                                                         "args": dict(x.probe.candidate.args),
                                                         "fault": x.probe.fault_class.name})
            if C and not A:
                out["c_not_a"][lab] += 1
            if A and not B:
                out["a_not_b"][lab] += 1
    res = {k: (dict(v) if isinstance(v, Counter) else v) for k, v in out.items()}
    tag = os.environ.get("TAG", "")
    json.dump(res, open(os.path.join(R.RESULTS, f"residuals_grants_return{('_' + tag) if tag else ''}.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in res.items() if not k.startswith("examples")}))


if __name__ == "__main__":
    {"baseline_diff": baseline_diff, "traj_floor": traj_floor, "grants_return": grants_return}[sys.argv[1]]()
