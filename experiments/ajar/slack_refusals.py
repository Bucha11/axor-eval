"""live_v5 (grants, no human): classify the slack refusals by where the denied call's
grant-argument values come from (residuals_rules.md revision 4).

    python slack_refusals.py results/live_v5/trajectories.tgz
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys
import tarfile
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
R0 = json.load(open(os.path.join(HERE, "live", "grant_args_R0.json")))["slack"]


def canon(t):
    return re.sub(r"\s+", " ", str(t)).strip().casefold()


def strip_url(v):
    return re.sub(r"^[a-z]+://", "", canon(v)).rstrip("/")


def in_text(text, v):
    v = strip_url(v)
    return bool(v) and re.search(r"(?<!\w)" + re.escape(v) + r"(?!\w)", canon(text)) is not None


def quoted(text, v):
    v = strip_url(v)
    return any(canon(q) == v for q in re.findall(r"'([^']+)'|\"([^\"]+)\"|`([^`]+)`", text) for q in q if q)


def text_of(msg):
    c = msg.get("content")
    if isinstance(c, list):
        return "\n".join(b.get("content", "") or "" for b in c if isinstance(b, dict))
    return str(c or "")


def main(path):
    tf = tarfile.open(path)
    by_tool, total, rows = defaultdict(Counter), Counter(), []
    for m in tf.getmembers():
        if "/slack/" not in m.name or not m.name.endswith(".json"):
            continue
        d = json.load(tf.extractfile(m))
        if d["user_task_id"] == "user_task_4":
            continue
        msgs = d["messages"]
        prompt = next(text_of(x) for x in msgs if x["role"] == "user")
        reads = ""
        for x in msgs:
            if x["role"] == "tool":
                if "governance kernel" in str(x.get("error")):
                    tc = str(x.get("tool_call"))
                    fn = re.search(r"function='(\w+)'", tc).group(1)
                    args = ast.literal_eval(re.search(r"args=(\{.*?\}) id=", tc, re.S).group(1))
                    vals = [str(args.get(a)) for a in R0.get(fn, {}) if args.get(a) not in (None, "", [])]
                    cls = []
                    for v in vals:
                        if in_text(prompt, v):
                            cls.append("request (quoted)" if quoted(prompt, v) else "request (unquoted)")
                        elif in_text(reads, v):
                            cls.append("only in a read")
                        else:
                            cls.append("other")
                    # the call's class: its weakest arg (a read-only value decides)
                    order = ["other", "only in a read", "request (unquoted)", "request (quoted)"]
                    c = min(cls, key=order.index) if cls else "other"
                    by_tool[fn][c] += 1
                    total[c] += 1
                    rows.append({"pass": m.name.split("/")[1], "task": d["user_task_id"], "tool": fn,
                                 "args": {a: args.get(a) for a in R0.get(fn, {})}, "class": c, "per_arg": cls})
                else:
                    reads += "\n" + text_of(x)
    out = {"total": dict(total), "by_tool": {k: dict(v) for k, v in by_tool.items()}, "rows": rows}
    json.dump(out, open(os.path.join(HERE, "results", "live_v5_slack_refusals.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
