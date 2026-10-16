"""B and C recomputed on IDENTICAL candidates for both modes (A untouched; A stays as in 9055e07).

B: the recombination tuples generated from the GRANTS-mode grants (no single grant covers them) are
   fed to BOTH the grants gate and the origin-only gate -> admitted in each mode. Same candidate set.
C: only sink-points whose admitting grant (grants mode) has a FINITE quota (uses != None). For each
   such tuple: repeat 1..5 in BOTH modes; count admitted over quota (grants: same finite grant still
   admits; origin-only: admitted repeats of the same tuple). Report how many such finite-quota tuples.

Two modes, 2010 sink-points, c9v6 (config grants, L2=tuple, audience, references, counters, typed),
kernel cad07bc. No amount sum.
"""
import os, sys, json, hashlib, dataclasses, subprocess, itertools, glob, time
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["AXOR_AJAR_CONFIG_DIR"] = os.path.join(HERE, "config_m1_c9v6")
os.environ["AXOR_AJAR_GRANT_ARGS_FROM_CONFIG"] = "1"; os.environ["AXOR_AJAR_L2"] = "tuple"
os.environ.setdefault("AJAR_AGENTDOJO_ROOT", "/home/user/Ajar/bench/agentdojo")
CORE = os.environ.get("AXOR_CORE_REPO", "/home/user/core-m1")
sys.path.insert(0, CORE); sys.path.insert(0, "/home/user/Ajar"); sys.path.insert(0, HERE)
import axor_ajar
from axor_core.governor import ToolCallGovernor
from axor_core.contracts.canonical import ConsequenceClass
from agentdojo.functions_runtime import FunctionsRuntime
from agentdojo.agent_pipeline.tool_execution import tool_result_to_str
from agentdojo.task_suite.load_suites import get_suite
from ajar.core.types import Candidate
from check_wrapper import VERSIONS
from types import SimpleNamespace

MODELS = ["gpt-4o-2024-05-13", "claude-3-5-sonnet-20241022", "gpt-4o-mini-2024-07-18"]
SUITES = ["banking", "slack", "travel", "workspace"]
MUT = {"send_money", "schedule_transaction", "update_scheduled_transaction", "update_password", "update_user_info",
       "send_direct_message", "send_channel_message", "add_user_to_channel", "invite_user_to_slack", "post_webpage",
       "remove_user_from_slack", "create_calendar_event", "reserve_hotel", "reserve_car_rental", "reserve_restaurant",
       "send_email", "delete_email", "reschedule_calendar_event", "add_calendar_event_participants", "append_to_file",
       "create_file", "delete_file", "share_file", "cancel_calendar_event"}
ROOT = os.path.join(os.environ["AJAR_AGENTDOJO_ROOT"], "runs")


def build(suite, prompt, plan, mode):
    cfg = dataclasses.replace(axor_ajar.load_config(suite.name, "context", "request-only"), references=True)
    if mode == "origin":
        cfg = dataclasses.replace(cfg, grant_args={}, grant_templates={}, grant_quotas={}, description_sources={},
                                  description_targets={}, delegated_sources={}, list_union=False, list_args={},
                                  max_unattended_consequence=ConsequenceClass.CONSEQUENTIAL)
        kw = cfg.as_governor_kwargs(); g = ToolCallGovernor(**kw); g.register_task(prompt); return g
    kwargs, hook = axor_ajar.grants_kwargs("L1+L2s", tuple_grants=True, counters=True, confirm="oracle")
    spec = SimpleNamespace(task=SimpleNamespace(suite=suite.name), prompt=prompt, plan=plan)
    kw = cfg.as_governor_kwargs(); kw.update(kwargs(spec))
    g = ToolCallGovernor(**kw); g.register_task(prompt); hook(g, spec); return g


def recomb(grants, sink, base, table):
    args = sorted({a for gr in grants for a in gr.constraints})
    if not args:
        return []
    valsets = {}
    for a in args:
        vs = []
        for gr in grants:
            c = gr.constraints.get(a)
            if c is not None and getattr(c, "values", None):
                vs += [str(v) for v in list(c.values)[:4]]
        valsets[a] = list(dict.fromkeys(vs))[:6] or [None]
    out = []
    for combo in itertools.product(*[valsets[a] for a in args]):
        tup = {a: v for a, v in zip(args, combo) if v is not None}
        if not tup:
            continue
        full = dict(base); full.update(tup)
        if any(gr.covers(sink, full, table) for gr in grants):
            continue
        out.append(full)
        if len(out) >= 64:
            break
    return out


def adm(g, tool, args):
    return g.evaluate(tool, axor_ajar.agent_args(g, dict(args))).allowed


R = {"B_states": 0, "B_cand": 0, "B_admit_grants": 0, "B_admit_origin": 0,
     "C_finite_tuples": 0, "C_over_quota_grants": 0, "C_repeat_admit_origin": 0}


def run():
    r = dict(R)
    for model in MODELS:
        for s in SUITES:
            suite = get_suite(VERSIONS[s], s)
            for p in sorted(glob.glob(os.path.join(ROOT, model, s, "user_task_*", "important_instructions", "*.json"))):
                run = json.load(open(p))
                ut = suite.user_tasks[run["user_task_id"]]
                prompt = next(m["content"] for m in run["messages"] if m["role"] == "user")
                if isinstance(prompt, list): prompt = "".join(b.get("content", "") for b in prompt)
                inj = dict(run.get("injections") or {})
                plan = [Candidate(c.function, dict(c.args)) for c in ut.ground_truth(
                    ut.init_environment(suite.load_and_inject_default_environment(inj)).model_copy(deep=True))]
                G = {m: build(suite, prompt, plan, m) for m in ("origin", "grants")}
                ENV = {m: ut.init_environment(suite.load_and_inject_default_environment(inj)) for m in ("origin", "grants")}
                RT = FunctionsRuntime(suite.tools)
                calls = [tc for m in run["messages"] if m["role"] == "assistant" for tc in (m.get("tool_calls") or [])]
                for c in calls:
                    tool, cargs = c["function"], dict(c["args"])
                    if tool in MUT:
                        gg = G["grants"]
                        grs = [x for x in gg.grants.issued if x.sink == tool]
                        # B: recomb from grants mode, fed to BOTH gates (identical candidates)
                        if len(grs) >= 2:
                            r["B_states"] += 1
                            for full in recomb(grs, tool, cargs, gg._handles):
                                r["B_cand"] += 1
                                if adm(gg, tool, full): r["B_admit_grants"] += 1
                                if adm(G["origin"], tool, full): r["B_admit_origin"] += 1
                        # C: finite-quota tuples only (defined by grants mode)
                        dg = gg.evaluate(tool, axor_ajar.agent_args(gg, dict(cargs)))
                        if dg.allowed:
                            fg = getattr(dg, "grant_id", None)
                            fin = any(x.id == fg and x.uses is not None for x in gg.grants.issued)
                            if fin:
                                r["C_finite_tuples"] += 1
                                # grants: spend first, then 5 repeats -> over-quota admits
                                if fg is not None:
                                    k = gg.spend(dg, axor_ajar.spend_args(dg, dict(cargs)))
                                    if k is not None: gg.grant_store.commit(k)
                                for _ in range(5):
                                    d2 = gg.evaluate(tool, axor_ajar.agent_args(gg, dict(cargs)))
                                    if d2.allowed:
                                        r["C_over_quota_grants"] += 1
                                        g2 = getattr(d2, "grant_id", None)
                                        if g2 is not None:
                                            k2 = gg.spend(d2, axor_ajar.spend_args(d2, dict(cargs)))
                                            if k2 is not None: gg.grant_store.commit(k2)
                                    else:
                                        break
                                # origin: same tuple repeated 1..5 (no quota) -> admitted repeats
                                go = G["origin"]
                                for _ in range(5):
                                    if adm(go, tool, dict(cargs)): r["C_repeat_admit_origin"] += 1
                                    else: break
                    # advance both governors with the recorded call
                    for m in ("origin", "grants"):
                        g = G[m]; d = g.evaluate(tool, axor_ajar.agent_args(g, dict(cargs)))
                        if d.allowed:
                            if getattr(d, "grant_id", None) is not None:
                                k = g.spend(d, axor_ajar.spend_args(d, dict(cargs)))
                                if k is not None: g.grant_store.commit(k)
                            res, err = RT.run_function(ENV[m], tool, dict(cargs))
                            if err is None:
                                axor_ajar.present(g, d, tool_result_to_str(res), tool, dict(cargs), typed=res)
    return r


if __name__ == "__main__":
    t0 = time.time(); r = run(); dt = time.time() - t0
    hashes = {f: hashlib.sha256(open(os.path.join(HERE, "config_m1_c9v6", f), "rb").read()).hexdigest()[:16]
              for f in ["banking.yaml", "slack.yaml", "travel.yaml", "workspace.yaml"]}
    khead = subprocess.run(["git", "-C", CORE, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    A = json.load(open(os.path.join(HERE, "results", "enum_abc_c9v6.json")))["modes"]
    out = {"seconds": round(dt, 1), "kernel_head": khead, "config_sha256_16": hashes,
           "A_unchanged_from_9055e07": {m: {k: A[m][k] for k in ("A_states", "A_decisions", "A_admitted",
                "A_atk_placements", "A_atk_admitted", "A_atk_admitted_amount")} for m in ("origin", "grants")},
           "BC_same_candidates": r}
    print(json.dumps(out, indent=1))
    dest = os.path.join(HERE, "results", "enum_bc2_c9v6.json")
    json.dump(out, open(dest, "w"), indent=1); print("DONE", dest)
