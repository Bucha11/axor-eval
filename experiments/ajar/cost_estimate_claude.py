"""Cost estimate for a Claude live Table-4 run, from the REAL o4-mini token logs
(spend.jsonl per condition). No API calls. Reprices measured token totals at
claude.com/pricing rates with a tokenizer/thinking uncertainty multiplier."""
import json, statistics as st

PASSES_MEASURED = 3
TASKS = 96
# measured 3-pass (288-episode) token totals per Table-4 condition (prompt=input, completion=output incl reasoning)
COND = {  # from results/*/spend.jsonl
    "undefended":          {"in": 3141750, "out": 761813, "src": "≈ L1+L2 profile (no undef spend.jsonl; near-identical loop)"},
    "origin_only":         {"in": 3289976, "out": 696119, "src": "live_origin_c9v5_v2/spend.jsonl"},
    "grants_L1L2":         {"in": 3141750, "out": 761813, "src": "live_v5/spend.jsonl"},
    "grants_L1L2_L4view":  {"in": 3339145, "out": 712618, "src": "live_c9v5/spend.jsonl (B = A+B/2)"},
}
PRICE = {"haiku-5-5": (0.10, 0.50), "sonnet-5-5": (2.00, 10.00)}  # $/1M (in, out), prompts <100K
MULT = {"central": 1.15, "upper": 1.50}  # Claude tokenizer + adaptive-thinking output vs o4-mini


def run_cost(model, passes, mult):
    pin, pout = PRICE[model]
    tin = sum(c["in"] for c in COND.values()) / PASSES_MEASURED * passes * mult
    tout = sum(c["out"] for c in COND.values()) / PASSES_MEASURED * passes * mult
    return tin / 1e6 * pin + tout / 1e6 * pout


def undefended_pass(model, mult):
    pin, pout = PRICE[model]
    c = COND["undefended"]
    tin = c["in"] / PASSES_MEASURED * mult
    tout = c["out"] / PASSES_MEASURED * mult
    return tin / 1e6 * pin + tout / 1e6 * pout


out = {"source": "real o4-mini token logs (spend.jsonl); repriced at claude.com/pricing",
       "pricing_$per_1M": PRICE, "multiplier": MULT,
       "note": "output includes reasoning/thinking tokens; o4-mini out is ~84% reasoning. "
               "Disabling Claude thinking (haiku: disabled@≤high; sonnet: between_tools@≤high) cuts output ~5x.",
       "per_condition_3pass_tokens_o4mini": COND,
       "full_run_4cond": {}, "one_undefended_pass": {}}
for model in PRICE:
    out["full_run_4cond"][model] = {}
    for passes in (1, 2, 3):
        out["full_run_4cond"][model][f"{passes}pass"] = {
            "central_$": round(run_cost(model, passes, MULT["central"]), 2),
            "upper_$": round(run_cost(model, passes, MULT["upper"]), 2)}
    out["one_undefended_pass"][model] = {
        "central_$": round(undefended_pass(model, MULT["central"]), 2),
        "upper_$": round(undefended_pass(model, MULT["upper"]), 2)}

# budget fit (30% margin => spend <= $35)
BUD, MARGIN = 50.0, 0.30
ceil = BUD * (1 - MARGIN)
out["budget"] = {"cap_$": BUD, "margin": MARGIN, "spend_ceiling_$": ceil}
out["fits_with_margin"] = {m: {f"{p}pass": out["full_run_4cond"][m][f"{p}pass"]["upper_$"] <= ceil
                               for p in (1, 2, 3)} for m in PRICE}
out["recommendation"] = ("Haiku-5-5 full 3 passes x 4 conditions (upper ${:.0f}) + Sonnet-5-5 1 pass x 4 "
                         "conditions (upper ${:.0f}) = ${:.0f} upper, within $35 ceiling.").format(
    out["full_run_4cond"]["haiku-5-5"]["3pass"]["upper_$"],
    out["full_run_4cond"]["sonnet-5-5"]["1pass"]["upper_$"],
    out["full_run_4cond"]["haiku-5-5"]["3pass"]["upper_$"] + out["full_run_4cond"]["sonnet-5-5"]["1pass"]["upper_$"])
json.dump(out, open("results/cost_estimate_claude.json", "w"), indent=1)
print(json.dumps(out, indent=1))
