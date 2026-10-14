"""Replay the recorded live final-run episodes (A and B) through a governor and dump every
decision, so two configurations / kernels can be diffed episode by episode (MODEL.md §8.14:
"the episodes in which a changed rule fires" = a recorded call whose decision differs).

The governor is built as run_agentdojo.make_governor builds it (the config as is), with the
request registered and L1 grants minted; in B also the live oracle (grant arguments, dates and
times excepted, equal to a ground-truth call; budget 5, refused calls not re-asked). Each
recorded call is evaluated in order; an allowed call registers its recorded output (an allowed
call the live run had blocked has none: the empty string) and spends its grant.

    AXOR_CORE_REPO=<kernel> python decisions_live.py <config_dir> <out.json>
"""
from __future__ import annotations

import ast
import glob
import json
import os
import re
import sys

CORE = os.environ.get("AXOR_CORE_REPO", "/home/user/core-m1")
sys.path.insert(0, CORE)
HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.join(HERE, "..", "results", "live_final")

from agentdojo.task_suite.load_suites import get_suite  # noqa: E402
from axor_core.config import GovernanceConfig  # noqa: E402
from axor_core.governor import ToolCallGovernor  # noqa: E402
from axor_core.kernel.confirm import ScriptedConfirmer  # noqa: E402
from axor_core.kernel.handles import canonicalize, split_kind  # noqa: E402

TEMPORAL = re.compile(r"(date|time|day)", re.I)
CALL = re.compile(r"function='(\w+)' args=(\{.*\}) id=")


def proj(kinds, args):
    out = []
    for k, spec in sorted(kinds.items()):
        if TEMPORAL.search(k):
            continue
        kind = split_kind(spec)[0]
        v = args.get(k)
        vals = v if isinstance(v, (list, tuple)) else ([] if v is None else [v])
        try:
            out.append((k, tuple(sorted(canonicalize(kind, x) for x in vals))))
        except ValueError:
            out.append((k, ("<bad>",)))
    return tuple(out)


def governor(cfg, prompt, plan, l4):
    g = ToolCallGovernor(**cfg.as_governor_kwargs())
    g.register_task(prompt)
    if cfg.grant_args:
        g.grants.from_request(prompt)
    if l4 and cfg.grant_args:
        st = {"asked": 0}
        refused = set()

        def ok(action, call):
            tool, args = call
            key = json.dumps([tool, args], sort_keys=True, default=str)
            if key in refused or st["asked"] >= 5:
                return False
            st["asked"] += 1
            kinds = cfg.grant_args.get(tool, {})
            res = any(c.function == tool and proj(kinds, dict(c.args)) == proj(kinds, args) for c in plan)
            if not res:
                refused.add(key)
            return res
        g._confirmer = ScriptedConfirmer(ok)
    return g


def main(cfg_dir, out_path):
    suites = {s: get_suite("v1", s) for s in ("banking", "slack", "travel", "workspace")}
    cfgs = {s: GovernanceConfig.from_yaml(os.path.join(cfg_dir, f"{s}.yaml")) for s in suites}
    out = {}
    for path in sorted(glob.glob(os.path.join(LIVE, "[AB]", "pass*", "traj", "*", "*.json"))):
        rel = os.path.relpath(path, LIVE)
        cfg_name = rel.split(os.sep)[0]
        d = json.load(open(path))
        suite = suites[d["suite"]]
        ut = suite.user_tasks[d["user_task_id"]]
        env = ut.init_environment(suite.load_and_inject_default_environment({}))
        plan = list(ut.ground_truth(env.model_copy(deep=True)))
        g = governor(cfgs[d["suite"]], ut.PROMPT, plan, l4=(cfg_name == "B"))
        seq = []
        for m in d["messages"]:
            if m["role"] != "tool" or not m.get("tool_call"):
                continue
            mm = CALL.match(m["tool_call"])
            tool, args = mm.group(1), ast.literal_eval(mm.group(2))
            asked0 = g.confirmations
            dec = g.evaluate(tool, args)
            seq.append([tool, dec.allowed, dec.category, g.confirmations - asked0])
            if not dec.allowed:
                continue
            if getattr(dec, "grant_id", None) is not None:
                key = g.spend(dec, dict(args))
                if key is not None:
                    g.grant_store.commit(key)
            if not m.get("error"):
                text = "".join(b.get("content", "") for b in (m.get("content") or []) if isinstance(b, dict))
                g.register_output(dec, text)
        out[rel] = {"utility": d["utility"], "decisions": seq}
    json.dump(out, open(out_path, "w"), indent=0)
    print(len(out), "episodes")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
