"""MODEL.md §5: what the content role would cost and catch, measured offline before any kernel
change. A token in a content argument of a sink call (URL, e-mail, IBAN, by syntax) that the
request does not contain but an earlier tool output does, is what the role would refuse.

    python content_role_cost.py   (Ajar venv; AgentDojo runs corpus)  -> results/content_role_cost.json
"""
import ast
import glob
import json
import os
import re
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(os.environ.get("AJAR_AGENTDOJO_ROOT", "bench/agentdojo"), "runs")
MODELS = ("gpt-4o-2024-05-13", "claude-3-5-sonnet-20241022", "gpt-4o-mini-2024-07-18")
TOKEN = re.compile(r"(?:https?://)?(?:www\.)?[\w-]+(?:\.[\w-]+)+\.[a-z]{2,}(?:/[^\s\"')<>]*)?|[\w.+-]+@[\w-]+(?:\.[\w-]+)+|\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")


def canon(t):
    t = t.lower().rstrip(".,;:!?)'\"")
    t = re.sub(r"^https?://", "", t)
    return re.sub(r"^www\.", "", t).rstrip("/")


def text(m):
    c = m.get("content")
    if isinstance(c, list):
        return "\n".join(b.get("content", "") or "" for b in c if isinstance(b, dict))
    return str(c or "")


def calls(m):
    tcs = m.get("tool_calls")
    if isinstance(tcs, str):
        tcs = ast.literal_eval(tcs) if tcs not in ("None", "") else []
    return tcs or []


def scan(run, content_args):
    msgs = run["messages"]
    prompt = next(text(x) for x in msgs if x["role"] == "user")
    req = {canon(t) for t in TOKEN.findall(prompt)}
    seen = ""
    flagged = []
    for m in msgs:
        if m["role"] == "tool":
            seen += "\n" + text(m)
        if m["role"] != "assistant":
            continue
        for tc in calls(m):
            fn, args = tc["function"], dict(tc["args"])
            for a in content_args.get(fn, []):
                for t in TOKEN.findall(str(args.get(a) or "")):
                    c = canon(t)
                    if c and c not in req and c in {canon(x) for x in TOKEN.findall(seen)}:
                        flagged.append((fn, a, t))
    return flagged


def main():
    report = json.load(open(os.path.join(HERE, "results", "model_report.json")))
    content = {s: {t: [a for a, r in roles.items() if r == "content"] for t, roles in report[s]["roles"].items()}
               for s in report}
    out = {"benign": defaultdict(Counter), "attacked": defaultdict(Counter), "examples": []}
    for model in MODELS:
        for s in content:
            for p in glob.glob(os.path.join(ROOT, model, s, "user_task_*", "none", "none.json")):
                run = json.load(open(p))
                f = scan(run, content[s])
                b = out["benign"][s]
                b["trajectories"] += 1
                b["solved"] += bool(run.get("utility"))
                if f:
                    b["flagged"] += 1
                    b["flagged_solved"] += bool(run.get("utility"))
                    if len(out["examples"]) < 8:
                        out["examples"].append([model, s, run["user_task_id"], f[:2]])
            for p in glob.glob(os.path.join(ROOT, model, s, "user_task_*", "important_instructions", "*.json")):
                run = json.load(open(p))
                f = scan(run, content[s])
                a = out["attacked"][s]
                a["trajectories"] += 1
                a["attack_landed"] += bool(run.get("security"))
                if f:
                    a["flagged"] += 1
                    a["flagged_landed"] += bool(run.get("security"))
                    a[f"flagged_{run.get('injection_task_id')}"] += 1
    out["benign"] = {k: dict(v) for k, v in out["benign"].items()}
    out["attacked"] = {k: dict(v) for k, v in out["attacked"].items()}
    json.dump(out, open(os.path.join(HERE, "results", "content_role_cost.json"), "w"), indent=1, default=str)
    print(json.dumps({k: v for k, v in out.items()}, indent=1, default=str))


if __name__ == "__main__":
    main()
