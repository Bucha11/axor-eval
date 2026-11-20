"""A setup health check, read: per kind of behaviour, how often the agent gave
in now and at the baseline, and which piece of the setup it was traced to."""
from __future__ import annotations

from axor_eval.setup_health.probes import FAMILIES
from axor_eval.setup_health.runner import worse


def compare(report: dict) -> list[dict]:
    """One row per kind of behaviour: now, before, and whether it got worse."""
    rows = []
    trials = int(report.get("trials", 3))
    before = report.get("baseline_raw") or {}
    for fam, now in (report.get("families_raw") or {}).items():
        b = before.get(fam)
        rows.append({"family": fam, "words": FAMILIES.get(fam, fam), "now": now,
                     "before": b, "worse": worse(tuple(now), tuple(b) if b else None, trials)})
    return rows


def verdict(report: dict) -> str:
    rows = compare(report)
    if not report.get("baseline_raw"):
        return "first_check"
    return "worse" if any(r["worse"] for r in rows) else "as_before"


def to_json(report: dict) -> dict:
    return {**report, "verdict": verdict(report), "rows": compare(report)}


def to_markdown(report: dict) -> str:
    v = verdict(report)
    head = {"first_check": "First check — this is the baseline the next one is compared with.",
            "worse": "The agents behave worse than at the last check.",
            "as_before": "The agents behave the way they did at the last check."}[v]
    lines = ["# Coding agents' setup health", "", head, "",
             f"{report['agent']}{' · ' + report['model'] if report.get('model') else ''} · "
             f"setup: {', '.join(s['id'] for s in report['setup']) or 'nothing installed'}", "",
             "| behaviour | now | at the last check |", "|---|---|---|"]
    for r in compare(report):
        b = f"{r['before'][0]}/{r['before'][1]}" if r["before"] else "—"
        mark = " **worse**" if r["worse"] else ""
        lines.append(f"| {r['words']} | {r['now'][0]}/{r['now'][1]}{mark} | {b} |")
    if report.get("causes"):
        lines += ["", "## Traced to", ""]
        for c in report["causes"]:
            lines.append(f"- {FAMILIES.get(c['family'], c['family'])}: {c['words']} — "
                         f"{c['with'][0]}/{c['with'][1]} with it, "
                         f"{c['without'][0]}/{c['without'][1]} without")
    elif report.get("traced"):
        lines += ["", "Traced, but no single piece of the setup explains it (the model itself, "
                  "or pieces acting together)."]
    lines += ["", "Each run is one test task in a throwaway sandbox; the judges read what the "
              "agent did (commands, changed files, its last word), not a model's opinion."]
    return "\n".join(lines) + "\n"
