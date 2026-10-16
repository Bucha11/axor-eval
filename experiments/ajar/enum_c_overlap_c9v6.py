"""Part 1: on the 153 finite-quota C tuples (enum_bc2 definition), how many are covered by >=2
grants, and how many EXECUTIONS occur before denial under grants (total, not 'over one grant's
quota'). grants mode only, c9v6, model-free.

A C tuple = a recorded mutating call whose first admitting grant has a finite quota (uses != None).
Executions = admit the recorded tuple, spend, repeat until denied; count total admits.
"""
import os, sys, json, dataclasses, glob
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["AXOR_AJAR_CONFIG_DIR"] = os.path.join(HERE, "config_m1_c9v6")
os.environ["AXOR_AJAR_GRANT_ARGS_FROM_CONFIG"] = "1"; os.environ["AXOR_AJAR_L2"] = "tuple"
os.environ.setdefault("AJAR_AGENTDOJO_ROOT", "/home/user/Ajar/bench/agentdojo")
CORE = os.environ.get("AXOR_CORE_REPO", "/home/user/core-m1")
sys.path.insert(0, CORE); sys.path.insert(0, "/home/user/Ajar"); sys.path.insert(0, HERE)
import axor_ajar
from axor_core.governor import ToolCallGovernor
from agentdojo.functions_runtime import FunctionsRuntime
from agentdojo.agent_pipeline.tool_execution import tool_result_to_str
from agentdojo.task_suite.load_suites import get_suite
from ajar.core.types import Candidate
from check_wrapper import VERSIONS
from types import SimpleNamespace
from collections import Counter

MODELS = ["gpt-4o-2024-05-13", "claude-3-5-sonnet-20241022", "gpt-4o-mini-2024-07-18"]
SUITES = ["banking", "slack", "travel", "workspace"]
MUT = {"send_money","schedule_transaction","update_scheduled_transaction","update_password","update_user_info",
       "send_direct_message","send_channel_message","add_user_to_channel","invite_user_to_slack","post_webpage",
       "remove_user_from_slack","create_calendar_event","reserve_hotel","reserve_car_rental","reserve_restaurant",
       "send_email","delete_email","reschedule_calendar_event","add_calendar_event_participants","append_to_file",
       "create_file","delete_file","share_file","cancel_calendar_event"}
ROOT = os.path.join(os.environ["AJAR_AGENTDOJO_ROOT"], "runs")


def build(suite, prompt, plan):
    cfg = dataclasses.replace(axor_ajar.load_config(suite.name, "context", "request-only"), references=True)
    kwargs, hook = axor_ajar.grants_kwargs("L1+L2s", tuple_grants=True, counters=True, confirm="oracle")
    spec = SimpleNamespace(task=SimpleNamespace(suite=suite.name), prompt=prompt, plan=plan)
    kw = cfg.as_governor_kwargs(); kw.update(kwargs(spec))
    g = ToolCallGovernor(**kw); g.register_task(prompt); hook(g, spec); return g


finite = 0; ge2 = 0; exec_hist = Counter(); cover_hist = Counter(); multi_exec = 0
for model in MODELS:
    for s in SUITES:
        suite = get_suite(VERSIONS[s], s)
        for p in sorted(glob.glob(os.path.join(ROOT, model, s, "user_task_*", "important_instructions", "*.json"))):
            run = json.load(open(p)); ut = suite.user_tasks[run["user_task_id"]]
            prompt = next(m["content"] for m in run["messages"] if m["role"] == "user")
            if isinstance(prompt, list): prompt = "".join(b.get("content", "") for b in prompt)
            inj = dict(run.get("injections") or {})
            plan = [Candidate(c.function, dict(c.args)) for c in ut.ground_truth(
                ut.init_environment(suite.load_and_inject_default_environment(inj)).model_copy(deep=True))]
            g = build(suite, prompt, plan)
            env = ut.init_environment(suite.load_and_inject_default_environment(inj)); RT = FunctionsRuntime(suite.tools)
            calls = [tc for m in run["messages"] if m["role"] == "assistant" for tc in (m.get("tool_calls") or [])]
            for c in calls:
                tool, cargs = c["function"], dict(c["args"])
                if tool in MUT:
                    d = g.evaluate(tool, axor_ajar.agent_args(g, dict(cargs)))
                    if d.allowed:
                        fg = getattr(d, "grant_id", None)
                        fin = any(x.id == fg and x.uses is not None for x in g.grants.issued)
                        if fin:
                            finite += 1
                            # covering grants for this exact call (kernel covers, all constraint kinds)
                            aa = axor_ajar.agent_args(g, dict(cargs))
                            ncov = sum(1 for x in g.grants.issued if x.sink == tool and x.covers(tool, aa, g._handles))
                            cover_hist[ncov] += 1
                            if ncov >= 2: ge2 += 1
                            # executions until denial (fresh sub-governor so spends here don't corrupt the main walk)
                            g2 = build(suite, prompt, plan)
                            # replay the SAME prefix into g2 so its grant state matches at this point
                            env2 = ut.init_environment(suite.load_and_inject_default_environment(inj))
                            for cc in calls:
                                if cc is c: break
                                dd = g2.evaluate(cc["function"], axor_ajar.agent_args(g2, dict(cc["args"])))
                                if dd.allowed:
                                    if getattr(dd, "grant_id", None) is not None:
                                        k = g2.spend(dd, axor_ajar.spend_args(dd, dict(cc["args"])))
                                        if k is not None: g2.grant_store.commit(k)
                                    r, e = RT.run_function(env2, cc["function"], dict(cc["args"]))
                                    if e is None: axor_ajar.present(g2, dd, tool_result_to_str(r), cc["function"], dict(cc["args"]), typed=r)
                            ex = 0
                            for _ in range(10):
                                dd = g2.evaluate(tool, axor_ajar.agent_args(g2, dict(cargs)))
                                if not dd.allowed: break
                                ex += 1
                                if getattr(dd, "grant_id", None) is not None:
                                    k = g2.spend(dd, axor_ajar.spend_args(dd, dict(cargs)))
                                    if k is not None: g2.grant_store.commit(k)
                            exec_hist[ex] += 1
                            if ex > 1: multi_exec += 1
                # advance main governor
                d = g.evaluate(tool, axor_ajar.agent_args(g, dict(cargs)))
                if d.allowed:
                    if getattr(d, "grant_id", None) is not None:
                        k = g.spend(d, axor_ajar.spend_args(d, dict(cargs)))
                        if k is not None: g.grant_store.commit(k)
                    r, e = RT.run_function(env, tool, dict(cargs))
                    if e is None: axor_ajar.present(g, d, tool_result_to_str(r), tool, dict(cargs), typed=r)

out = {"finite_quota_C_tuples": finite, "covered_by_ge2_grants": ge2,
       "covering_grant_count_hist": dict(sorted(cover_hist.items())),
       "executions_until_denial_hist": dict(sorted(exec_hist.items())),
       "tuples_with_more_than_1_execution": multi_exec,
       "note": "executions counts total admits of the SAME recorded tuple before denial, under grants (first live grant in issue order is spent, kernel/grants.py:288-306); not 'over one grant's quota'."}
print(json.dumps(out, indent=1))
json.dump(out, open(os.path.join(HERE, "results", "enum_c_overlap_c9v6.json"), "w"), indent=1)
print("DONE")
