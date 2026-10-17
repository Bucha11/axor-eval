"""Q2: over the 1887 replay corpus under the paper's grants arm (c9v5, grants L1+L2,
references on, kernel 618c4a9), count egress calls that passed the ADDRESSED floor
(floor_mode=audience) only thanks to a ground while a sensitive read was outstanding:
a destination outside the audience admitted because it is TASK-origin (request literal)
or covered by an L1/L3/L4 grant. Then how many of those are part of a landed attack with
an attacker-controlled destination/content (destination not request-origin, and present in
the injection payload). NO model calls."""
import os, sys, json, glob, dataclasses
HERE = "/home/user/ajar-wt/experiments/ajar"
WT = os.environ["KERNEL_WT"]
os.environ["AXOR_CORE_REPO"] = WT
os.environ["AXOR_AJAR_CONFIG_DIR"] = os.path.join(HERE, "config_m1_c9v5")
os.environ.setdefault("AJAR_AGENTDOJO_ROOT", "/home/user/Ajar/bench/agentdojo")
os.environ["AXOR_AJAR_SECRETS"] = "paper"
os.environ["AXOR_AJAR_GRANT_ARGS_FROM_CONFIG"] = "1"   # grants = config driving args
os.environ["AXOR_AJAR_L2"] = "tuple"
os.environ.pop("AXOR_HYP", None)
sys.path.insert(0, WT); sys.path.insert(0, "/home/user/core-m1/examples/agentdojo")  # grant_ablation
sys.path.insert(0, HERE); sys.path.insert(0, "/home/user/Ajar")

import axor_ajar  # noqa: E402
from axor_core.governor import ToolCallGovernor  # noqa: E402
from axor_core.contracts.taint import TrustedOrigin as _TO  # noqa: E402
from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime  # noqa: E402
from agentdojo.task_suite.load_suites import get_suite  # noqa: E402
from agentdojo.agent_pipeline.tool_execution import tool_result_to_str  # noqa: E402
from check_wrapper import VERSIONS  # noqa: E402
from types import SimpleNamespace  # noqa: E402

MODELS = ["gpt-4o-2024-05-13", "claude-3-5-sonnet-20241022", "gpt-4o-mini-2024-07-18"]
SUITES = ("banking", "slack", "travel", "workspace")
ATTACK = "important_instructions"


def build(suite_name, prompt, plan):
    cfg = axor_ajar.load_config(suite_name, "context", "request-only")   # references on (config)
    kwargs, hook = axor_ajar.grants_kwargs("L1+L2s", confirm="oracle")
    spec = SimpleNamespace(task=SimpleNamespace(suite=suite_name), prompt=prompt, plan=plan)
    kw = cfg.as_governor_kwargs(); kw.update(kwargs(spec))
    g = ToolCallGovernor(**kw); g.register_task(prompt); hook(g, spec)
    return g


def leaves(v):
    if isinstance(v, (list, tuple, set, frozenset)):
        return [y for x in v for y in leaves(x)]
    return [] if v in (None, "") else [v]


def replay(suite, run):
    ut = suite.user_tasks[run["user_task_id"]]
    prompt = next(m["content"] for m in run["messages"] if m["role"] == "user")
    if isinstance(prompt, list):
        prompt = "".join(b.get("content", "") for b in prompt)
    inj_text = " ".join(str(v) for v in (run.get("injections") or {}).values())
    env = ut.init_environment(suite.load_and_inject_default_environment(dict(run.get("injections") or {})))
    pre = env.model_copy(deep=True)
    runtime = FunctionsRuntime(suite.tools)
    from ajar.core.types import Candidate
    plan = [Candidate(c.function, dict(c.args)) for c in ut.ground_truth(pre.model_copy(deep=True))]
    g = build(suite.name, prompt, plan)
    egress = set(g._egress_sinks)
    calls = [tc for m in run["messages"] if m["role"] == "assistant" for tc in (m.get("tool_calls") or [])]
    executed = []
    ground_hits = []  # per egress call admitted outside-audience only via ground
    for c in calls:
        fn = c["function"]; args = dict(c["args"])
        floor_on = g.confidentiality_floor_active()   # a sensitive read already outstanding?
        d = g.evaluate(fn, axor_ajar.agent_args(g, args))
        if d.allowed and floor_on and fn in egress:
            dests = [x for a in g._destination_args.get(fn, ()) for x in leaves(args.get(a))]
            outside = [x for x in dests if str(x).casefold() not in g._audience]
            if outside:
                task_o = {x: (g._taint.trusted_origin(x) is _TO.TASK) for x in outside}
                gs = getattr(d, "grant_source", None)
                mech = "TASK" if all(task_o.values()) else (f"grant:{gs}" if gs in ("L1", "L3", "L4") else "other")
                ground_hits.append({"tool": fn, "outside": outside,
                                    "all_task_origin": all(task_o.values()),
                                    "grant_source": gs, "mechanism": mech,
                                    "dest_not_task": [x for x in outside if not task_o[x]],
                                    "dest_in_injection": [x for x in outside if inj_text and str(x) in inj_text]})
        if not d.allowed:
            continue
        if getattr(d, "grant_id", None) is not None:
            key = g.spend(d, axor_ajar.spend_args(d, args))
            if key is not None:
                g.grant_store.commit(key)
        res, err = runtime.run_function(env, fn, args)
        executed.append(FunctionCall(function=fn, args=args))
        if err is None:
            axor_ajar.present(g, d, tool_result_to_str(res), fn, args)
    inj = suite.injection_tasks.get(run.get("injection_task_id") or "")
    landed = bool(suite._check_injection_task_security(inj, [], pre, env, executed)) if inj is not None else False
    return ground_hits, landed


root = os.path.join(os.environ["AJAR_AGENTDOJO_ROOT"], "runs")
tot = {"episodes": 0, "ground_pass_calls": 0, "by_mech": {}, "by_suite": {},
       "landed_ground_calls": 0, "landed_ground_attacker_dest": 0}
rows = []
for model in MODELS:
    for sname in SUITES:
        suite = get_suite(VERSIONS[sname], sname)
        for p in sorted(glob.glob(os.path.join(root, model, sname, "user_task_*", ATTACK, "*.json"))):
            run = json.load(open(p))
            hits, landed = replay(suite, run)
            tot["episodes"] += 1
            if hits:
                tot["by_suite"][sname] = tot["by_suite"].get(sname, 0) + len(hits)
            for h in hits:
                tot["ground_pass_calls"] += 1
                tot["by_mech"][h["mechanism"]] = tot["by_mech"].get(h["mechanism"], 0) + 1
                if landed:
                    tot["landed_ground_calls"] += 1
                    if h["dest_in_injection"] or h["dest_not_task"]:
                        tot["landed_ground_attacker_dest"] += 1
                rows.append({"model": model, "suite": sname, "user_task": run["user_task_id"],
                             "injection": run.get("injection_task_id"), "landed": landed, **h})

out = {"task": "audience_floor_ground_1887", "corpus": "1887 replay (c9v5, grants L1+L2, refs on)",
       "kernel_commit": "618c4a9", "config_dir": "config_m1_c9v5", "models": MODELS,
       "summary": tot, "hits": rows}
op = os.path.join(HERE, "results", "audience_ground_1887_c9v5.json")
json.dump(out, open(op, "w"), indent=1, default=str)
print(json.dumps(tot, indent=1))
print("WROTE", op)
