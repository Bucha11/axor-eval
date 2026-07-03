# Eval experiments

Reproducible experiment harnesses for the four integrity properties, run on live
models (GPT-4o, Qwen-2.5-72b via OpenRouter). These live in **axor-eval** because
they are eval-layer code: they exercise the kernel and *measure* it. They import
`axor_core` and `axor_eval` — that is the allowed one-way direction (eval → core).
axor-core never imports anything here.

They reuse the AgentDojo driver and attack payloads that remain in the
**axor-core** repo, unchanged (`examples/agentdojo`, `examples/attacks`). The
`_corepath.py` bootstrap in each subdirectory puts a sibling axor-core checkout on
`sys.path`; set `AXOR_CORE_REPO` if the two repos are not checked out side by
side. `OPEN_ROUTER_API_KEY` is required for the live runs.

## `agentdojo/` — the four properties on the AgentDojo benchmark

| harness | property | mechanism |
|---|---|---|
| `eval_bridge.py` | attribution + Wilson CI | maps AgentDojo outcomes to Tool / Instruction / Data-Flow / Judgment, with confidence intervals |
| `eval_claims.py` | Tool, Budget | structured self-report claims (`submit_findings`, `report_usage`); deterministic fabrication / budget-misreport detection |
| `eval_deprivation.py` | Tool | governance + a layered silent-fault executor with meta-tool bypass |
| `eval_protocol.py` | — | forces the model to emit a claim when it stops with prose |
| `eval_fabrication.py` | Tool | live fabrication run |
| `eval_budget.py` | Budget | token meter + live budget-misreport run |

Unit tests: `test_eval_*.py` (`python -m pytest experiments/agentdojo`).

## `attacks/` — judgment drift, measured

| harness | what it shows |
|---|---|
| `nnsi_openrouter.py` | nested-instruction exfiltration; binary drift (poisoned vs clean) |
| `split_doc_openrouter.py` | split-document judge-bypass; the LLM compliance judge is the exploit |
| `drift_curve.py` | **dose-response judgment drift** — compositional poison measured step by step, per model |

Results notes: `*_results.md`. Example:

```sh
OPEN_ROUTER_API_KEY=... AXOR_DRIFT_MODEL=openai/gpt-4o \
    python experiments/attacks/drift_curve.py
```
