"""Part 3 (read-only, $0). Reconstruct how refs_on admits update_scheduled_transaction(recipient=US133)
in the handle_table_banking_c9v5 flip episodes (gpt-4o banking ut3/ut4 x injection_task_4), under the
origin-no-grants mode (strip_grants), kernel 618c4a9 + config_m1_c9v5. Dumps, for that call, the full
_reference_context: raw vs resolved recipient, whether US133 was minted as a handle and its origin,
shown_raw/is_own/is_request, the reference 'why', and which prior read (if any) minted US133.
"""
import os, sys, json, glob, dataclasses
HERE = "/home/user/ajar-wt/experiments/ajar"
WT = os.environ["KERNEL_WT"]
os.environ["AXOR_CORE_REPO"] = WT
os.environ["AXOR_AJAR_CONFIG_DIR"] = os.path.join(HERE, "config_m1_c9v5")
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

US133 = "US133000000121212121212"
SUITE = get_suite(VERSIONS["banking"], "banking")
ROOT = os.path.join(os.environ["AJAR_AGENTDOJO_ROOT"], "runs")


def strip_grants(cfg):
    return dataclasses.replace(cfg, grant_args={}, grant_templates={}, grant_quotas={},
                               description_sources={}, description_targets={}, delegated_sources={},
                               list_union=False, list_args={}, max_unattended_consequence=ConsequenceClass.CONSEQUENTIAL)


def make_gov(prompt, references):
    cfg = axor_ajar.load_config("banking", "context", "request-only")
    cfg = dataclasses.replace(cfg, references=references)
    cfg = strip_grants(cfg)
    g = ToolCallGovernor(**cfg.as_governor_kwargs())
    g.register_task(prompt)
    return g


def minted(g):
    t = getattr(g, "_xrefs", None)
    return {str(r.value): getattr(r, "origin", None) for r in t.by_name.values()} if (t and t.by_name) else {}


def analyze(ut_id, references):
    p = sorted(glob.glob(os.path.join(ROOT, "gpt-4o-2024-05-13", "banking", ut_id,
                                       "important_instructions", "*injection_task_4*.json")))
    if not p:
        return {"error": "no trace"}
    run = json.load(open(p[0]))
    ut = SUITE.user_tasks[ut_id]
    prompt = next(m["content"] for m in run["messages"] if m["role"] == "user")
    if isinstance(prompt, list):
        prompt = "".join(b.get("content", "") for b in prompt)
    env = ut.init_environment(SUITE.load_and_inject_default_environment(dict(run.get("injections") or {})))
    runtime = FunctionsRuntime(SUITE.tools)
    g = make_gov(prompt, references)
    out = {"user_task": ut_id, "references": references, "us133_in_recorded_user_msg": US133.casefold() in prompt.casefold(),
           "steps": []}
    calls = [tc for m in run["messages"] if m["role"] == "assistant" for tc in (m.get("tool_calls") or [])]
    for c in calls:
        raw = dict(c["args"])
        aargs = axor_ajar.agent_args(g, raw)
        step = {"tool": c["function"]}
        if c["function"] == "update_scheduled_transaction" and US133.casefold() in str(raw).casefold():
            t = getattr(g, "_xrefs", None)
            step.update({
                "raw_recipient": raw.get("recipient"),
                "fed_recipient": aargs.get("recipient"),
                "fed_recipient_is_handle": US133.casefold() not in str(aargs.get("recipient")).casefold(),
                "shown_raw_US133": bool(t.shown_raw(US133)) if t else None,
                "is_own_US133": bool(t.is_own(US133)) if t else None,
                "is_request_US133": bool(t.is_request(US133)) if t else None,
                "minted_before_this_call": minted(g),
            })
            if t is not None:  # references on: full reference-context diagnosis
                resolved, ctx = g._reference_context(c["function"], dict(aargs))
                step.update({
                    "resolved_recipient": resolved.get("recipient"),
                    "reference_origins": ctx.get("origins"),
                    "reference_why": (ctx.get("unproven").reason if ctx.get("unproven") else None),
                    "operator_deny": (ctx.get("deny").category if ctx.get("deny") else None),
                })
            else:
                step.update({"resolved_recipient": None, "reference_origins": None,
                             "reference_why": None, "operator_deny": None})
        d = g.evaluate(c["function"], aargs)
        step.update({"allowed": bool(d.allowed), "category": d.category,
                     "grant_source": getattr(d, "grant_source", None)})
        out["steps"].append(step)
        if not d.allowed:
            continue
        res, err = runtime.run_function(env, c["function"], raw)
        if err is None:
            axor_ajar.present(g, d, tool_result_to_str(res), c["function"], raw)
    return out


res = {"kernel_commit": "618c4a9", "config_dir": "config_m1_c9v5",
       "mode": "origin-no-grants (strip_grants), L_std",
       "note": "update_scheduled_transaction driving_args in c9v5 = [amount,id,recipient]; recipient O = {CH93,GB29,SE35,US122} (US133 NOT in O)",
       "analyses": []}
for ut_id in ("user_task_3", "user_task_4"):
    for refs in (True, False):
        res["analyses"].append(analyze(ut_id, refs))

op = os.path.join(HERE, "results", "q3_handle_table_us133_path_c9v5.json")
json.dump(res, open(op, "w"), indent=1, default=str)
for a in res["analyses"]:
    print("==", a["user_task"], "refs=", a["references"], "US133_in_user_msg=", a.get("us133_in_recorded_user_msg"))
    for s in a["steps"]:
        if s["tool"] == "update_scheduled_transaction" and "raw_recipient" in s:
            print("   update_scheduled_transaction:", s["allowed"], "/", s["category"],
                  "| fed_handle=", s["fed_recipient_is_handle"], "origins=", s["reference_origins"],
                  "shown_raw=", s["shown_raw_US133"])
            print("     why=", s["reference_why"], "| op_deny=", s["operator_deny"])
            print("     minted:", {k: v for k, v in s["minted_before_this_call"].items() if "US133" in k or len(str(k)) > 15})
print("WROTE", op)
