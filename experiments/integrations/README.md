# The four integrations on the current kernel: one compatibility check

axor-claude, axor-openrouter, axor-langchain and axor-wrap, lifted to axor-core
`claude/model-m1` `fa02df1` (c9v4 frozen, c9v5 flags) and the daemon
(`claude/daemon-references` + two fixes found by this check, `d7e1b72`): every tool call goes through `ToolCallGovernor` (or
the daemon) with grants, references and output registration, by one shared protocol
(`gate.py`, sha256 `950916b2…`, byte-identical in the four packages; `compat.py` prints
the four digests). No model is called anywhere here.

| File | What it is |
| --- | --- |
| `drivers.py` | One agent session per path, driven call by call: `shim` (the AgentDojo shim's own sequence, `ajar/axor_ajar.py` + `ajar/final_live/decisions_live.py`, on a bare governor), `wrap`, `langchain` (`AxorMiddleware.wrap_tool_call`), `claude` (`GatedSession` + the real `ClaudeCodeExecutor`; a scripted client stands where the Anthropic API would), `openrouter` (`make_session` + the real `OpenRouterExecutor`; a scripted transport), `daemon` (`DaemonEnforcer`, in process) |
| `compat.py` | The check: the same calls through every path, compared with the shim call by call |
| `accounting.py` | Lines changed by the lift, integration lines vs the rest |
| `TRACE.md` | O3, O5, E, G1, H × integration: where each holds (kernel / daemon / adapter / operator / reasoning), file:line; axor-wrap `runtime.py:235` |
| `results/compat.json`, `results/accounting.json` | The numbers below |

## The check

Per call, against the shim: whether the tool ran, the refusal category, the confirmations
asked, the arguments the tool ran with, and what the agent got back (reference names
fixed by `references_seed`, so the views compare byte for byte; a view carries
`iban_from_untrusted_read_hidden_…` references in banking, for instance).

* **InjecAgent** — every attacker call of the 510 direct-harm and 544 data-stealing base
  cases, built as `../injecagent/full_attack_set.py` builds them (attacker arguments
  synthesized from the instruction by the tool's schema), under its `old` and `final`
  configurations: the user tool's response is read, then the attacker call (dh) or S1
  then S2 (ds) is proposed.
* **AgentDojo** — the 581 recorded live episodes of the final run (o4-mini; A 290; B 291
  with the live oracle as L4: grant arguments equal to a ground-truth call, budget 5,
  a refused call not re-asked), replayed call by call as `decisions_live.py` replays them,
  under `config_m1_c9v4` (frozen) and `config_m1_c9v5`. The shim's own verdicts are
  checked against `ajar/results/live_final_decisions_c9v4_v.json`.

```sh
INJECAGENT_DIR=.../InjecAgent AXOR_CORE_REPO=.../axor-core python compat.py   # ~11 min, no API
python accounting.py <dir holding the four checkouts>
```

Needs the four packages and axor-daemon installed next to the kernel, and `agentdojo`
(0.1.35 here: suites, prompts and ground truth only). Ajar is not needed: the shim
functions used do not touch it.

## Results

**InjecAgent** — attacker call refused:

| config | shim | wrap | langchain | claude | openrouter | daemon |
|---|---|---|---|---|---|---|
| old, dh | 510/510 | 510/510 | 510/510 | 510/510 | 510/510 | 510/510 |
| old, ds | 544/544 | 544/544 | 544/544 | 544/544 | 544/544 | 544/544 |
| final, dh | 510/510 | 510/510 | 510/510 | 510/510 | 510/510 | 510/510 |
| final, ds | 544/544 | 544/544 | 544/544 | 544/544 | 544/544 | 544/544 |

Categories, identical in every path and equal to `full_attack_set_final.json`: old dh
consequence 306 / taint 204, ds taint 544 (the floor); final dh grant 459 / consequence
51, ds content projection 323 / grant 221. Divergences from the shim, call by call: **0**.

**AgentDojo** — 581 episodes, 2234 recorded calls:

| config | shim | wrap | langchain | claude | openrouter | daemon |
|---|---|---|---|---|---|---|
| c9v4: calls run | 2117 | 2117 | 2117 | 2117 | 2117 | 2117 |
| c9v4: confirmations (B) | 80 | 80 | 80 | 80 | 80 | 80 |
| c9v4: rows diverging from the shim | — | 0 | 0 | 0 | 0 | 0 |
| c9v5: calls run | 2032 | 2032 | 2032 | 2032 | 2032 | 2032 |
| c9v5: confirmations (B) | 123 | 123 | 123 | 123 | 123 | 123 |
| c9v5: rows diverging from the shim | — | 0 | 0 | 0 | 0 | 0 |

The shim reproduces the recorded c9v4 verdicts in **581/581** episodes (and B's 80
confirmations are `final_live/LIVE_C9V4.md`'s "105 -> 80").

## Divergences

None: on both sets, both InjecAgent configurations and both AgentDojo configurations,
every path — the four integrations and the daemon — gives every call the shim's
verdict, category, confirmations, executed arguments and agent view.

The daemon at `claude/daemon-references` (`a887ab7`) diverged in 40 rows (c9v4) / 39
(c9v5); both causes are fixed in axor-daemon `d7e1b72`:

1. **No description grants (MODEL.md 9.15).** It registered outputs but never passed a
   declared description source's structure to `observe_structured`, so those grants were
   never minted: slack user tasks 7, 9, 10, 12 and workspace 20 (c9v5: 21) were refused in
   A (`operator_set`, `reference_origin`) and asked of the oracle in B (+21
   confirmations). Fix: the operator passes the platform's parser,
   `--structured module:function` (the `structured=` the in-process integrations take).
2. **An empty path argument rewritten.** `os.path.normpath("")` is `"."`, so
   `search_files_by_filename(filename="")` ran with `"."` (workspace 31, B pass 3). Fix: an
   empty value is left as it is.

Not divergences, but recorded: a tool that raised in the recorded episode raises in the
replay (628 times in the claude and openrouter paths, logged by the session as an
unhandled tool exception and turned into a denial result for the model); its grant use
stays spent and nothing is registered, as in the shim.

## Accounting

`accounting.py` (physical lines; code = not blank, comment or docstring). Lift = `origin/main`
→ branch head; "other" is CI, changelog and the 151-line c9v4 fixture.

| package | lift: source | lift: tests | lift: other | integration (code) | rest (code) |
|---|---|---|---|---|---|
| axor-claude | +234 / −8 | +172 / −0 | +168 / −1 | 748 (482) | 2023 (1274) |
| axor-openrouter | +286 / −79 | +173 / −0 | +155 / −1 | 292 (200) | 1901 (1188) |
| axor-langchain | +362 / −32 | +175 / −32 | +171 / −1 | 485 (332) | 2476 (1717) |
| axor-wrap | +197 / −22 | +146 / −0 | +152 / −1 | 700 (390) | 3255 (2090) |

Integration, by part (physical / code):

* axor-claude — normalizer 438 / 280 (`events.py` stream events → tool calls 266 / 180,
  `normalizer.py` 172 / 100); execution wrapper 86 / 57 (`capability_gate.py`); shared
  gate 128 / 84; wiring `make_session` 96 / 61. Rest: tool handlers 917, model loop 448,
  skills/plugins 281, tool schemas 220, probe/sentinel 103, other 54.
* axor-openrouter — execution wrapper 86 / 57; shared gate 128 / 84; wiring 78 / 59 (no
  normalizer of its own: tool calls arrive parsed from the OpenAI stream in the model
  loop). Rest: cascade 227, codecs 210, transport 199, routing 159, caching 155, budget
  routing 146, tool schemas 144, rates 118, CLI 72, the model loop 276, skills 39,
  probe/sentinel 103, other 53.
* axor-langchain — normalizer 68 / 46; execution wrapper 275 / 190 (`AxorToolWrapper` 172,
  `ToolGate` 66, middleware hooks 37); output registration 14 / 12; shared gate 128 / 84.
  Rest: compression / tool selection / budget / telemetry 2186 (the gate calls inside the
  two tool-call bodies, ~24 lines, are counted here), quality judge 242.
* axor-wrap — execution wrapper 366 / 172 (`runtime.py`); config compilation from
  manifests 206 / 134; shared gate 128 / 84. Rest: control plane 1429, trace 593, scanner
  369, manifests 365, CLI 179, experiments 126, errors 86, other 108.

**Configuration for a typical agent.** The same file for all four: the kernel's
`GovernanceConfig` YAML. AgentDojo, c9v4, compiled by `../ajar/derive_model.py` from the
tool model (`../ajar/model/tools.yaml`: banking 10 lines, slack 13, travel 18, workspace
14) and the entity model derived from the deployment's state: banking 151 lines (33 keys),
slack 181, travel 237, workspace 533 (c9v5: 155 / 185 / 243 / 560). Of these the
description sources and targets (9.15) are 0 / 26 / 57 / 65 lines, and they need the
platform's structure parser (`axor_ajar.structured`, 23 lines) passed as `structured=`.
The Python each integration needs on top:

| package | lines | what |
|---|---|---|
| axor-claude | 1 | `make_session(governance="banking.yaml"[, confirmer=…])` |
| axor-openrouter | 1 (+ the tool handlers and their schemas) | `make_session(api_key=…, handlers=[…], tool_schemas=[…], governance="banking.yaml")` |
| axor-langchain | 1 | `create_agent(…, middleware=[AxorMiddleware(governance="banking.yaml")])` |
| axor-wrap | 2 | `WrappedToolset(tools, manifests, governance="banking.yaml")`, then `begin(task)` per request |
