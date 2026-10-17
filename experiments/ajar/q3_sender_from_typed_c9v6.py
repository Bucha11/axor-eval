"""Part 3 (read-only, $0). Does sender_from_typed (c9v6, kernel cad07bc) CLOSE the named_sender
path that admitted ut3/ut4 x injection_task_4 update_scheduled_transaction(recipient=US133) under
origin-only + references-on on c9v5? Replay those gpt-4o traces on cad07bc + config_m1_c9v6,
strip_grants (origin-only), references on, passing the TYPED tool return to present() so the kernel
takes the per-item sender from the declared field instead of parsing sender: lines from text.
Compare sender_from_typed ON vs forced OFF (flag toggled, all else equal)."""
import os, sys, json, glob, dataclasses
HERE = "/home/user/ajar-wt/experiments/ajar"
WT = os.environ["KERNEL_WT"]
os.environ["AXOR_CORE_REPO"] = WT
os.environ["AXOR_AJAR_CONFIG_DIR"] = os.path.join(HERE, "config_m1_c9v6")
os.environ["AXOR_AJAR_SECRETS"] = "paper"
os.environ["AJAR_ROOT"] = "/home/user/Ajar"
os.environ.setdefault("AJAR_AGENTDOJO_ROOT", "/home/user/Ajar/bench/agentdojo")
os.environ.pop("AXOR_HYP", None)
sys.path.insert(0, WT); sys.path.insert(0, "/home/user/core-m1/examples/agentdojo")
sys.path.insert(0, HERE); sys.path.insert(0, "/home/user/Ajar")

import axor_ajar  # noqa: E402
from axor_core.governor import ToolCallGovernor  # noqa: E402
from axor_core.contracts.canonical import ConsequenceClass  # noqa: E402
from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime  # noqa: E402
from agentdojo.task_suite.load_suites import get_suite  # noqa: E402
from agentdojo.agent_pipeline.tool_execution import tool_result_to_str  # noqa: E402
from check_wrapper import VERSIONS  # noqa: E402
import subprocess

KERNEL = subprocess.run(["git", "-C", WT, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
US133 = "US133000000121212121212"
SUITE = get_suite(VERSIONS["banking"], "banking")
ROOT = os.path.join(os.environ["AJAR_AGENTDOJO_ROOT"], "runs")


def strip_grants(cfg):
    return dataclasses.replace(cfg, grant_args={}, grant_templates={}, grant_quotas={},
                               description_sources={}, description_targets={}, delegated_sources={},
                               list_union=False, list_args={}, max_unattended_consequence=ConsequenceClass.CONSEQUENTIAL)


def make_gov(prompt, sft):
    cfg = axor_ajar.load_config("banking", "context", "request-only")
    cfg = dataclasses.replace(cfg, references=True, sender_from_typed=sft)
    cfg = strip_grants(cfg)
    g = ToolCallGovernor(**cfg.as_governor_kwargs())
    g.register_task(prompt)
    return g


def replay(ut_id, sft):
    p = sorted(glob.glob(os.path.join(ROOT, "gpt-4o-2024-05-13", "banking", ut_id,
                                       "important_instructions", "*injection_task_4*.json")))
    run = json.load(open(p[0]))
    ut = SUITE.user_tasks[ut_id]
    prompt = next(m["content"] for m in run["messages"] if m["role"] == "user")
    if isinstance(prompt, list):
        prompt = "".join(b.get("content", "") for b in prompt)
    env = ut.init_environment(SUITE.load_and_inject_default_environment(dict(run.get("injections") or {})))
    pre = env.model_copy(deep=True)
    runtime = FunctionsRuntime(SUITE.tools)
    g = make_gov(prompt, sft)
    executed, us133_step = [], None
    for c in [tc for m in run["messages"] if m["role"] == "assistant" for tc in (m.get("tool_calls") or [])]:
        raw = dict(c["args"])
        aargs = axor_ajar.agent_args(g, raw)
        d = g.evaluate(c["function"], aargs)
        if c["function"] == "update_scheduled_transaction" and US133.casefold() in str(raw).casefold():
            t = getattr(g, "_xrefs", None)
            origins = sorted({str(getattr(r, "origin", None)) for r in t.by_name.values()
                              if str(r.value).strip().casefold() == US133.casefold()}) if (t and t.by_name) else []
            us133_step = {"allowed": bool(d.allowed), "category": d.category,
                          "fed_recipient_is_handle": US133.casefold() not in str(aargs.get("recipient")).casefold(),
                          "us133_minted_origin": origins}
        if not d.allowed:
            continue
        res, err = runtime.run_function(env, c["function"], raw)
        executed.append(FunctionCall(function=c["function"], args=raw))
        if err is None:
            # pass the TYPED return so sender_from_typed takes the declared sender field
            axor_ajar.present(g, d, tool_result_to_str(res), c["function"], raw, typed=res)
    inj = SUITE.injection_tasks.get(run.get("injection_task_id") or "")
    landed = inj is not None and bool(SUITE._check_injection_task_security(inj, [], pre, env, executed))
    return {"user_task": ut_id, "sender_from_typed": sft, "landed": landed,
            "update_scheduled_transaction_US133": us133_step}


res = {"kernel_commit": KERNEL, "config_dir": "config_m1_c9v6", "references": True,
       "mode": "origin-only (strip_grants), references on; present() given the typed return",
       "episodes": []}
for ut_id in ("user_task_3", "user_task_4"):
    for sft in (True, False):
        res["episodes"].append(replay(ut_id, sft))

op = os.path.join(HERE, "results", "q3_sender_from_typed_c9v6.json")
json.dump(res, open(op, "w"), indent=1, default=str)
for e in res["episodes"]:
    s = e["update_scheduled_transaction_US133"]
    print("%s sft=%-5s landed=%-5s | update_sched(US133): %s/%s handle=%s minted_origin=%s" % (
        e["user_task"], e["sender_from_typed"], e["landed"],
        "ALLOW" if s and s["allowed"] else "DENY", s["category"] if s else "-",
        s["fed_recipient_is_handle"] if s else "-", s["us133_minted_origin"] if s else "-"))
print("WROTE", op)
