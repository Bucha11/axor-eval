"""Attack-classes-by-mechanism under one policy (FREEZE_C9V5, kernel 618c4a9).

ABLATION ONLY — the governor's decision code is untouched. The four modes are realised with
EXISTING knobs:
  references   : GovernanceConfig.references (governor kwarg; config_m1_c9v5 has references: true)
  tuple_grants : grants.tuple_grants   (axor_ajar.grants_kwargs hook)
  counters     : grants.default_uses   (quota; hook sets None when counters off)

  M0 = refs off,  tuple off, quota off   (identifier origin decided by the labeler, no reference
                                          table; grants per argument, independent; no quotas)
  M1 = refs on,   tuple off, quota off   (M0 + references)
  M2 = refs on,   tuple on,  quota off   (M1 + tuple binding)
  M3 = refs on,   tuple on,  quota on    (M2 + quotas == c9v5)

Labelers (patch the taint engine only; the gate code is unchanged):
  L_std   : stock labeler (no patch).
  L_match : ROPE semantics (rope/origin.py OriginPredicate._check_one): an identifier's origin is
            decided by STRING MATCH of its identifier-tokens against what was read / the request;
            a value whose source is not found is NOT attributed to the request (ROPE returns False
            -> deny). Here: trusted_origin(v)=TASK only if v's tokens are in the request; else if v
            appears verbatim in a prior read -> that read's origin; else UNTRUSTED. Never request.
  L_adv   : adversarial — every value reads as request origin (trusted_origin->TASK, is_trusted->True).

Every result file records: config sha256 (per suite), kernel commit, mode, labeler.

    AXOR_CORE_REPO=/home/user/core-m1 python mech_modes.py replay  <modes> <labelers> <out.json>
    AXOR_CORE_REPO=/home/user/core-m1 python mech_modes.py ajar    <modes> <labelers> <out.json>
"""
from __future__ import annotations
import dataclasses, glob, hashlib, json, os, subprocess, sys

CORE = os.environ.get("AXOR_CORE_REPO", "/home/user/core-m1")
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(HERE, "config_m1_c9v5")
os.environ["AXOR_AJAR_CONFIG_DIR"] = CONFIG_DIR
os.environ.setdefault("AJAR_AGENTDOJO_ROOT", "/home/user/Ajar/bench/agentdojo")
os.environ["AXOR_AJAR_GRANT_ARGS_FROM_CONFIG"] = "1"
os.environ["AXOR_AJAR_L2"] = "tuple"
sys.path.insert(0, CORE); sys.path.insert(0, "/home/user/Ajar"); sys.path.insert(0, HERE)
sys.path.insert(0, os.environ.get("ROPE_SRC", "/tmp/claude-0/-home-user/98d9b22b-bf42-5511-8999-2e828886295b/scratchpad/ext/rope/src"))

import axor_ajar  # noqa: E402
from axor_core.governor import ToolCallGovernor  # noqa: E402
from axor_core.contracts.taint import TrustedOrigin as _TO  # noqa: E402

MODES = {  # (references, tuple_grants, counters)
    "M0": (False, False, False),
    "M1": (True,  False, False),
    "M2": (True,  True,  False),
    "M3": (True,  True,  True),
}
SUITES = ("banking", "slack", "travel", "workspace")


def cfg_hashes():
    return {s: hashlib.sha256(open(os.path.join(CONFIG_DIR, f"{s}.yaml"), "rb").read()).hexdigest()[:16]
            for s in SUITES}


def kernel_commit():
    out = subprocess.run(["git", "-C", CORE, "rev-parse", "HEAD"], capture_output=True, text=True)
    clean = subprocess.run(["git", "-C", CORE, "diff", "--quiet", "618c4a9", "--", "axor_core/"]).returncode == 0
    return out.stdout.strip(), ("axor_core==618c4a9" if clean else "axor_core DIFFERS")


def make_labeler(name, read_texts):
    """Return a patch(g) applied after the prefix is replayed (read_texts collected incrementally)."""
    if name == "L_std":
        return lambda g: None
    if name == "L_adv":
        # everything reads as request origin. derive_value (integrity, references-off) calls
        # self._trusted.covers DIRECTLY (axor_core taint/engine.py:213,221), NOT the trusted_origin/
        # is_trusted methods, so those alone are inert — patch _trusted.covers too, else L_adv == L_std.
        def patch(g):
            g._taint.trusted_origin = lambda v, _o=_TO.TASK: _o
            g._taint.is_trusted = lambda *a, **k: True
            g._taint._trusted.covers = lambda *a, **k: True
        return patch
    if name == "L_match":
        # Faithful to rope/origin.py OriginPredicate._check_one in STRICT mode (ROPE_STRICT_MATCH=1,
        # the default): vtoks = tokenize_identifiers(value) or {value}; allow iff
        #   leg(2)  vtoks ⊆ request tokens                                   (R)
        #   leg(1b)/(1) vtoks ∩ non-injectable source tokens                (O: own set + platform/
        #               sender fields the attacker cannot forge == named_sender)
        # else deny. (There is NO "_TOKEN_RE-empty -> free text" allow under strict: a short value
        # like "Bob"/"7" becomes {value} and is checked, matching ROPE. Verified value-for-value
        # against OriginPredicate._check_one — see mech_lmatch_test.) As a labeler it marks a value
        # TASK iff that predicate allows, else leaves the stock origin (read-derived / untrusted).
        from rope.origin import tokenize_identifiers as _ti  # ROPE_SRC on sys.path
        def patch(g):
            req = set()
            for r in getattr(g, "_requests", []):
                req |= set(_ti(r or ""))
            noninj = {str(x).casefold() for x in getattr(getattr(g, "_xrefs", None), "own", set())}
            noninj |= set(req)  # request tokens are also non-injectable
            orig = g._taint.trusted_origin
            def trusted_origin(v, _orig=orig, _req=req, _noninj=noninj):
                vt = set(_ti(str(v))) or {str(v)}
                if vt <= _req or ({t.casefold() for t in vt} & _noninj):
                    return _TO.TASK
                return _orig(v)
            g._taint.trusted_origin = trusted_origin
        return patch
    raise ValueError(name)


def build(mode, labeler, suite, prompt, plan):
    refs, tup, cnt = MODES[mode]
    cfg = axor_ajar.load_config(suite.name, "context", "request-only")
    cfg = dataclasses.replace(cfg, references=refs)
    kwargs, hook = axor_ajar.grants_kwargs("L1+L2s", tuple_grants=tup, counters=cnt)
    from types import SimpleNamespace
    spec = SimpleNamespace(task=SimpleNamespace(suite=suite.name), prompt=prompt, plan=plan)
    kw = cfg.as_governor_kwargs(); kw.update(kwargs(spec))
    g = ToolCallGovernor(**kw); g.register_task(prompt); hook(g, spec)
    make_labeler(labeler, None)(g)   # labeler patch (request-based; applied once up front)
    return g


def _unplanned(tool, args, plan, used):
    """A call is unplanned if its leading tuple is not among the plan's tuples, or exceeds its
    multiplicity (phункт 2). Returns (is_unplanned, key)."""
    from axor_core.kernel.handles import canonicalize, split_kind
    import axor_ajar as _a
    kinds = _a.load_config  # placeholder; use grant_args kinds via config
    return None  # replay path grades by AgentDojo security(); unplanned-tuple accounting is the enum step


def run_replay(modes, labelers, out_path):
    from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime
    from agentdojo.task_suite.load_suites import get_suite
    from agentdojo.agent_pipeline.tool_execution import tool_result_to_str
    from ajar.core.types import Candidate
    from check_wrapper import VERSIONS
    MODELS = ["gpt-4o-2024-05-13", "claude-3-5-sonnet-20241022", "gpt-4o-mini-2024-07-18"]
    root = os.path.join(os.environ["AJAR_AGENTDOJO_ROOT"], "runs")
    suites = {s: get_suite(VERSIONS[s], s) for s in SUITES}
    rows = {}
    for mode in modes:
        for lab in labelers:
            landed = {s: 0 for s in SUITES}; runs = {s: 0 for s in SUITES}; util = {s: 0 for s in SUITES}
            for m in MODELS:
                for s in SUITES:
                    suite = suites[s]
                    for path in glob.glob(os.path.join(root, m, s, "user_task_*", "important_instructions", "*.json")):
                        run = json.load(open(path))
                        ut = suite.user_tasks[run["user_task_id"]]
                        prompt = next((x["content"] for x in run["messages"] if x["role"] == "user"), "")
                        if isinstance(prompt, list): prompt = "".join(b.get("content", "") for b in prompt)
                        inj = dict(run.get("injections") or {})
                        env = ut.init_environment(suite.load_and_inject_default_environment(inj))
                        pre = env.model_copy(deep=True)
                        runtime = FunctionsRuntime(suite.tools)
                        plan = [Candidate(c.function, dict(c.args)) for c in ut.ground_truth(pre.model_copy(deep=True))]
                        g = build(mode, lab, suite, prompt, plan)
                        if lab == "L_adv":  # adversarial labeler re-applied (stateless)
                            make_labeler("L_adv", None)(g)
                        calls = [tc for x in run["messages"] if x["role"] == "assistant" for tc in (x.get("tool_calls") or [])]
                        executed = []
                        for c in calls:
                            d = g.evaluate(c["function"], axor_ajar.agent_args(g, dict(c["args"])))
                            if not d.allowed: continue
                            if getattr(d, "grant_id", None) is not None:
                                key = g.spend(d, axor_ajar.spend_args(d, dict(c["args"])))
                                if key is not None: g.grant_store.commit(key)
                            res, err = runtime.run_function(env, c["function"], dict(c["args"]))
                            executed.append(FunctionCall(function=c["function"], args=dict(c["args"])))
                            if err is None:
                                axor_ajar.present(g, d, tool_result_to_str(res), c["function"], dict(c["args"]), typed=res)
                        runs[s] += 1
                        inj_task = suite.injection_tasks.get(run.get("injection_task_id") or "")
                        if inj_task is not None and bool(suite._check_injection_task_security(inj_task, [], pre, env, executed)):
                            landed[s] += 1
                        if bool(suite._check_user_task_utility(ut, [], pre, env, executed)):
                            util[s] += 1
            tot = sum(landed.values()); n = sum(runs.values())
            rows[f"{mode}/{lab}"] = {"landed": tot, "runs": n, "by_suite_landed": landed,
                                     "utility": sum(util.values())}
            print(f"{mode}/{lab}: landed {tot}/{n}  by_suite {landed}")
    out = {"config_sha256": cfg_hashes(), "kernel_commit": kernel_commit(), "task": "replay_1887",
           "rows": rows}
    json.dump(out, open(out_path, "w"), indent=1)
    print("wrote", out_path)


def run_ajar(modes, labelers, out_path):
    import paper_opl, run_ajar
    from ajar.core.types import Verdict
    data = [(s, p) for s, p in run_ajar.load(None) if s.task.suite in ("banking", "slack", "travel")]

    class Def:
        def __init__(self, mode, lab):
            self.name = f"{mode}/{lab}"; self.mode = mode; self.lab = lab
            self.privilege_surface = ("TOOL", "PARAMETER", "SEQUENCE", "PROVENANCE")
            self.log = []; self.decisions = 0
        def prepare(self, spec, llm=None): return spec
        def decide(self, spec, ctx, cand):
            from agentdojo.task_suite.load_suites import get_suite
            from check_wrapper import VERSIONS
            suite = get_suite(VERSIONS[spec.task.suite], spec.task.suite)
            g = build(self.mode, self.lab, suite, spec.prompt, spec.plan)
            for call, outp in axor_ajar.PREFIXES.outputs(spec, ctx):
                d = g.evaluate(call.tool, axor_ajar.agent_args(g, dict(call.args)))
                if getattr(d, "grant_id", None) is not None:
                    key = g.spend(d, axor_ajar.spend_args(d, dict(call.args)))
                    if key is not None: g.grant_store.commit(key)
                if outp is not None:
                    axor_ajar.present(g, d, outp, call.tool, dict(call.args))
            if self.lab == "L_adv": make_labeler("L_adv", None)(g)
            d = g.evaluate(cand.tool, axor_ajar.agent_args(g, dict(cand.args)))
            self.decisions += 1
            return Verdict.ALLOW if d.allowed else Verdict.DENY

    rows = {}
    for mode in modes:
        for lab in labelers:
            m = paper_opl.measure(Def(mode, lab), data)
            rows[f"{mode}/{lab}"] = {k: v for k, v in m.items() if k != "admitted_attack_calls"}
            print(f"{mode}/{lab}:", json.dumps(rows[f"{mode}/{lab}"]))
    out = {"config_sha256": cfg_hashes(), "kernel_commit": kernel_commit(), "task": "ajar_52_bst",
           "rows": rows}
    json.dump(out, open(out_path, "w"), indent=1)
    print("wrote", out_path)


if __name__ == "__main__":
    task = sys.argv[1]; modes = sys.argv[2].split(","); labs = sys.argv[3].split(","); out = sys.argv[4]
    (run_replay if task == "replay" else run_ajar)(modes, labs, out)
