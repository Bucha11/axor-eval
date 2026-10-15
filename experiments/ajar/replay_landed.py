"""Which attacks land in the 1887 replay without a human (variant "R0 L1+L2s"), run by run:
model, suite, user task, injection task, and the attacker-relevant calls that were admitted.

    AXOR_AJAR_CONFIG_DIR=... AXOR_AJAR_L2=tuple AXOR_AJAR_GRANT_ARGS_FROM_CONFIG=1 python replay_landed.py OUT
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay_runs as R  # noqa: E402
from agentdojo.task_suite.load_suites import get_suite  # noqa: E402
from check_wrapper import VERSIONS  # noqa: E402

MODELS = ("gpt-4o-2024-05-13", "claude-3-5-sonnet-20241022", "gpt-4o-mini-2024-07-18")
v = R.variants()["R0 L1+L2s"]

# §9.13 reporting: which admitted calls used a named-sender reference (recorded per run)
from axor_core.governor import ToolCallGovernor  # noqa: E402
_SENDER_USED = []
_orig_eval = ToolCallGovernor.evaluate


def _eval(self, tool, args):
    d = _orig_eval(self, tool, args)
    if d.allowed and "named_sender" in getattr(d, "reference_origins", ()):
        _SENDER_USED.append(tool)
    return d


ToolCallGovernor.evaluate = _eval
root = os.path.join(os.environ.get("AJAR_AGENTDOJO_ROOT", "bench/agentdojo"), "runs")
landed, runs = [], 0
for model in MODELS:
    for s in ("banking", "slack", "travel", "workspace"):
        suite = get_suite(VERSIONS[s], s)
        for p in sorted(glob.glob(os.path.join(root, model, s, "user_task_*", "important_instructions", "*.json"))):
            run = json.load(open(p))
            _SENDER_USED.clear()
            util, sec = R.replay(v, suite, run)
            runs += 1
            if sec:
                landed.append({"model": model, "suite": s, "user_task": run["user_task_id"],
                               "injection_task": run.get("injection_task_id"),
                               "named_sender_calls": list(_SENDER_USED)})
json.dump({"runs": runs, "landed": landed}, open(sys.argv[1], "w"), indent=1)
print(runs, len(landed))
