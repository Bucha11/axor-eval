"""Enumeration A + B + C, one run, no model, c9v6, two modes (origin-only, grants L1+L2).

A (off-reference-path, 9895 states = 1 start + each recorded call, over 1887 trajectories):
   at every state, each sink (its first driving arg) x candidates = injection values U request
   literals U O U pointer(reference-table) values. Count decisions, admitted total; and for the
   ATTACKER IDENTIFIERS among the candidates (IBAN/email/url, or a >=12-char payload token, not a
   request literal nor O): placements (denominator), admitted, and how many admitted into `amount`.
B (2010 sink-points): cross-grant recombination tuples no single grant covers (kernel covers()) -> admitted.
C (2010 sink-points): repeat the admitted recorded tuple 1..5 with live counters -> admitted over a
   FINITE (exhausted) quota.
Plus: sum of `amount` over admitted recorded calls in banking.

grants mode = config grant args (AXOR_AJAR_GRANT_ARGS_FROM_CONFIG) + L2=tuple + counters + references +
audience + typed; origin-only = grants stripped, consequence ceiling raised. kernel cad07bc.

   python enum_abc_c9v6.py <N_states|all> <out.json>
"""
import os, sys, json, hashlib, dataclasses, subprocess, itertools, glob, time, re
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["AXOR_AJAR_CONFIG_DIR"] = os.path.join(HERE, "config_m1_c9v6")
os.environ["AXOR_AJAR_GRANT_ARGS_FROM_CONFIG"] = "1"; os.environ["AXOR_AJAR_L2"] = "tuple"
os.environ.setdefault("AJAR_AGENTDOJO_ROOT", "/home/user/Ajar/bench/agentdojo")
CORE = os.environ.get("AXOR_CORE_REPO", "/home/user/core-m1")
sys.path.insert(0, CORE); sys.path.insert(0, "/home/user/Ajar"); sys.path.insert(0, HERE)
import axor_ajar
from axor_core.governor import ToolCallGovernor
from axor_core.contracts.canonical import ConsequenceClass
from axor_core.kernel.references import EMAIL, IBAN, URL
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
TOK = re.compile(r"[A-Za-z0-9][\w.@/+-]{3,}")
suites = {s: get_suite(VERSIONS[s], s) for s in SUITES}
cfg0 = {s: axor_ajar.load_config(s, "context", "request-only") for s in SUITES}
driving = {s: cfg0[s].grant_args for s in SUITES}
audience = {s: set(str(x).casefold() for x in cfg0[s].audience) for s in SUITES}


def tok(t):
    return set(TOK.findall(t or ""))


def attacker_ids(payloads):
    """IBAN/email/url, or a >=12-char token, from the injected payloads (raw, then casefold)."""
    out = set()
    for v in payloads:
        if not isinstance(v, str):
            continue
        for m in EMAIL.findall(v): out.add(m.casefold())
        for m in IBAN.findall(v): out.add(m.casefold())
        for m in URL.findall(v): out.add(m.casefold())
        for t in TOK.findall(v):
            if len(t) >= 12: out.add(t.casefold())
    return out


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


def enumA(g, sinks, cands, atk, amount_sinks, C):
    C["A_states"] += 1
    ptr = set(str(r.value).casefold() for r in g._xrefs.by_name.values()) if getattr(g, "_xrefs", None) else set()
    rset = cands | ptr
    for tl, drv in sinks:
        if not drv:
            continue
        arg = drv[0]
        for cand in rset:
            d = g.evaluate(tl, {arg: cand}); C["A_decisions"] += 1
            is_atk = cand in atk
            if is_atk:
                C["A_atk_placements"] += 1
            if d.allowed:
                C["A_admitted"] += 1
                if is_atk:
                    C["A_atk_admitted"] += 1
                    if arg == "amount":
                        C["A_atk_admitted_amount"] += 1
                    if len(C["A_ex"]) < 20:
                        C["A_ex"].append((tl, arg, str(cand)[:40]))


def sink_grants(g, sink):
    return [x for x in g.grants.issued if x.sink == sink]


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


def run(nmax):
    C = {m: {"A_states": 0, "A_decisions": 0, "A_admitted": 0, "A_atk_placements": 0, "A_atk_admitted": 0,
             "A_atk_admitted_amount": 0, "A_ex": [], "B_states": 0, "B_cand": 0, "B_admit": 0,
             "C_states": 0, "C_over_quota": 0, "C_over_FINITE_quota": 0, "amount_sum": 0.0}
         for m in ("origin", "grants")}
    nstate = 0
    for model in MODELS:
        for s in SUITES:
            suite = suites[s]
            sinks = [(tl, list((driving[s].get(tl) or {}).keys())) for tl in driving[s] if (driving[s].get(tl) or {})]
            O = audience[s]
            for p in sorted(glob.glob(os.path.join(ROOT, model, s, "user_task_*", "important_instructions", "*.json"))):
                run = json.load(open(p)); inj = run.get("injections") or {}
                injected = set()
                for v in inj.values():
                    if isinstance(v, str): injected |= {x.casefold() for x in tok(v)}
                ut = suite.user_tasks[run["user_task_id"]]
                prompt = next((mm["content"] for mm in run["messages"] if mm["role"] == "user"), "")
                if isinstance(prompt, list): prompt = "".join(b.get("content", "") for b in prompt)
                reqlit = {x.casefold() for x in tok(prompt)}
                cands = injected | reqlit | O
                atk = {c for c in attacker_ids(inj.values()) if c not in reqlit and c not in O}
                calls = [tc for mm in run["messages"] if mm["role"] == "assistant" for tc in (mm.get("tool_calls") or [])]
                G = {m: build(suite, prompt, plan=[Candidate(c.function, dict(c.args)) for c in ut.ground_truth(
                        ut.init_environment(suite.load_and_inject_default_environment(dict(inj))).model_copy(deep=True))], mode=m)
                     for m in ("origin", "grants")}
                ENV = {m: ut.init_environment(suite.load_and_inject_default_environment(dict(inj))) for m in ("origin", "grants")}
                RT = FunctionsRuntime(suite.tools)
                # state 0 (start)
                for m in ("origin", "grants"):
                    enumA(G[m], sinks, cands, atk, None, C[m])
                nstate += 1
                if nmax and nstate >= nmax:
                    return C, nstate
                for c in calls:
                    tool, cargs = c["function"], dict(c["args"])
                    if tool in MUT:
                        for m in ("origin", "grants"):
                            g = G[m]
                            grs = sink_grants(g, tool)
                            if len(grs) >= 2:
                                C[m]["B_states"] += 1
                                for full in recomb(grs, tool, cargs, g._handles):
                                    C[m]["B_cand"] += 1
                                    if g.evaluate(tool, axor_ajar.agent_args(g, full)).allowed:
                                        C[m]["B_admit"] += 1
                            d = g.evaluate(tool, axor_ajar.agent_args(g, dict(cargs)))
                            if d.allowed:
                                C[m]["C_states"] += 1
                                fg = getattr(d, "grant_id", None)
                                fin = any(x.id == fg and x.uses is not None for x in g.grants.issued)
                                if fg is not None:
                                    k = g.spend(d, axor_ajar.spend_args(d, dict(cargs)))
                                    if k is not None: g.grant_store.commit(k)
                                if s == "banking" and "amount" in cargs:
                                    try: C[m]["amount_sum"] += float(cargs["amount"])
                                    except Exception: pass
                                for _ in range(5):
                                    d2 = g.evaluate(tool, axor_ajar.agent_args(g, dict(cargs)))
                                    if d2.allowed:
                                        C[m]["C_over_quota"] += 1
                                        g2 = getattr(d2, "grant_id", None)
                                        if g2 is not None and g2 == fg and fin:
                                            C[m]["C_over_FINITE_quota"] += 1
                                        if g2 is not None:
                                            k2 = g.spend(d2, axor_ajar.spend_args(d2, dict(cargs)))
                                            if k2 is not None: g.grant_store.commit(k2)
                                    else:
                                        break
                    # advance both modes + enumA at the new state
                    for m in ("origin", "grants"):
                        g = G[m]; d = g.evaluate(tool, axor_ajar.agent_args(g, dict(cargs)))
                        if d.allowed:
                            if getattr(d, "grant_id", None) is not None:
                                k = g.spend(d, axor_ajar.spend_args(d, dict(cargs)))
                                if k is not None: g.grant_store.commit(k)
                            res, err = RT.run_function(ENV[m], tool, dict(cargs))
                            if err is None:
                                axor_ajar.present(g, d, tool_result_to_str(res), tool, dict(cargs), typed=res)
                        enumA(g, sinks, cands, atk, None, C[m])
                    nstate += 1
                    if nmax and nstate >= nmax:
                        return C, nstate
    return C, nstate


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "100"
    nmax = None if arg == "all" else int(arg)
    t0 = time.time(); C, nstate = run(nmax); dt = time.time() - t0
    hashes = {f: hashlib.sha256(open(os.path.join(HERE, "config_m1_c9v6", f), "rb").read()).hexdigest()[:16]
              for f in ["banking.yaml", "slack.yaml", "travel.yaml", "workspace.yaml"]}
    khead = subprocess.run(["git", "-C", CORE, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    out = {"states_processed": nstate, "seconds": round(dt, 1), "kernel_head": khead, "config_sha256_16": hashes, "modes": C}
    if nmax:
        out["estimate_full_9895_min"] = round(dt / max(nstate, 1) * 9895 / 60, 1)
        print(f"ESTIMATE: {nstate} states {dt:.0f}s -> full 9895 ~ {dt/max(nstate,1)*9895/60:.1f} min")
    print(json.dumps(out, indent=1, default=str))
    if arg == "all":
        dest = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "results", "enum_abc_c9v6.json")
        json.dump(out, open(dest, "w"), indent=1, default=str); print("DONE", dest)
    print("END")
