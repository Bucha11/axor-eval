# Premises × integrations: where each one is enforced

Kernel: axor-core `claude/model-m1` `1d9549a` (c9v4 frozen; c9v5 = 9.18 + 9.19 + 9.20). Daemon:
axor-daemon `claude/upgrade-axor-packages-core-n06zj7` `24a961d` (`claude/daemon-references` + the description-grant and empty-path fixes). Integrations on branch
`claude/upgrade-axor-packages-core-n06zj7` of each package. Lines are at those heads.

`gate.py` is the same file (sha256 `950916b2…`) in all four packages; its lines are given
once as `gate.py:N`.

Where: **kernel** — the governor decides it; **daemon** — the daemon process enforces it;
**adapter** — the integration's code enforces it; **operator** — holds only if whoever
deploys the agent does something; **reasoning** — holds by an argument, not by code or a
test that would catch its loss.

## The premises

| | Statement | Source |
|---|---|---|
| **O3** | Complete mediation: no effect bypasses `allow`; an unknown sink fails closed; ceilings cannot be widened | axor-core `docs/kernel-theorem.md` §O3 (A-3) |
| **O5** | Check-and-decrement is linearizable; at most one execution per spend | axor-core `docs/task-scoped-grants.md` (Invariants) |
| **E** | No interleaving between check and send; what is checked is what runs | axor-daemon `tests/test_governance.py:138` |
| **G1** | Grant issuance is unreachable from the agent | axor-daemon `tests/test_governance.py:205` |
| **H** | L4: a human confirms the exact call (every field), on a channel the agent cannot answer; no answer is a refusal | not named as "H" in any repository; read here as the L4 channel of `docs/task-scoped-grants.md` and axor-daemon `confirm.py:2-18` |

## Table

| | axor-claude | axor-openrouter | axor-langchain | axor-wrap |
|---|---|---|---|---|
| **O3** | **kernel** `node/intent_loop.py:1046` (the only path that approves a tool intent calls the capability executor; every other return is a denial) + **adapter** `capability_gate.py:44-64` (handler only after `Admitted`) + **operator** `__init__.py:101` (handlers are registered only in the gated executor). Daemon mode: **daemon** `enforcer.py:145,173-226`. Code in the agent's own process can still call a handler: **reasoning** (the agent is the model; against code, the daemon or `LockedExecutor`) | same as axor-claude; `__init__.py:113-114` | **adapter** `middleware.py:1765-1782` → `_gate_request` `:1463-1481` (gate before the tool cache, `:1831`, `:1922`) and `wrapper.py:110` + **operator**: the middleware must be in `create_agent(middleware=[…])` or the tools wrapped with `wrap_tools`; a tool invoked outside the agent's ToolNode is not mediated | **adapter** `runtime.py:259-279` (refusal raises before the callable is looked up) + **operator**: the agent must be handed `callables()` (`runtime.py:210`), not the raw functions |
| **O5** | **kernel** `kernel/grants.py:272` reserve, `:302` commit; `governor.py:1072` spend + **adapter** `gate.py:88-100` (evaluate + reserve under `gate.lock`, `gate.py:59`), commit `gate.py:109`, a raising tool keeps the use spent `gate.py:125-128`; one call at a time `capability_gate.py:54`. Daemon mode: **daemon** `enforcer.py:173,200,216`. One process only: two processes sharing a grant store are not covered (**reasoning**) | same as axor-claude | **kernel** as left + **adapter** `gate.py:88-100`; `middleware.py:1772,1782`, `wrapper.py:121`; a call that spends a grant use never takes the cache path `middleware.py:1831,1922` | **kernel** as left + **adapter** `gate.py:88-100`, `runtime.py:259` |
| **E** | interleaving: **kernel** (the session loop awaits one tool intent at a time) + **adapter** `capability_gate.py:54` (asyncio lock; child nodes share the executor). checked = run: **adapter** `gate.py:96` (a private copy of the resolved arguments) → `capability_gate.py:60`. Daemon mode: **daemon** `enforcer.py:169,173,199`. Test: `tests/test_kernel_gate.py::test_concurrent_calls_are_decided_after_each_other_E` | same as axor-claude | interleaving: **adapter** `middleware.py:1772,1782`, `wrapper.py:121` (LangGraph runs one message's tool calls concurrently; the test fails without the lock). checked = run: **adapter** `middleware.py:1480` hands the tool the resolved arguments, but the ToolNode then validates them through the tool's `args_schema` (pydantic may coerce `"50"` → `50.0`): **reasoning** for type-coercing schemas | interleaving: **adapter** `runtime.py:259`. checked = run: **adapter** `runtime.py:270` (`**verdict.args`) |
| **G1** | **kernel**: grants are minted only by `GrantMinter` from trusted inputs (`kernel/grants.py:449,736`) + **adapter**: the only mint call is `gate.py:80` (`begin`), reached from `GatedSession.run` `capability_gate.py:79-86` with the text the application passed to `run` (a child node's model-written task never reaches it) + **operator**: `run(task)` must carry the user's words. In process, code in the agent's process can reach `gate.governor.grants`: **reasoning**. Daemon mode: **daemon** `server.py:127,154-157` (hello / tool_call / bye only), but `hello.task` is client-asserted (`enforcer.py:107-125`): a compromised agent process widens L1 to what it claims | same as axor-claude | **adapter** `governed.py:53-56` seeds L1 from every human message of the agent state + **operator / reasoning**: any component that writes a `HumanMessage` (a retrieval or hand-off middleware) mints grants from it | **operator**: `runtime.py:240` `begin(task)` is called by the deploying code |
| **H** | **kernel** `governor.py:841-843` (asked only for a call every other gate admits), `kernel/confirm.py:123` (`call_digest`: the whole call), `:54` (`render`), `kernel/grants.py:736`; no confirmer = refusal + **operator** `make_session(confirmer=…)` `__init__.py:101` must reach a human; the agent has no channel to it (its only output is tool calls). Daemon mode: **daemon** `confirm.py` (`--confirm-socket`, never the agent's connection; timeout / drop = refusal) | same as axor-claude (`__init__.py:114`) | **kernel** as left + **operator** `AxorMiddleware(confirmer=…)` | **kernel** as left + **operator** `WrappedToolset(confirmer=…)` |

Measured on every one of the five rows by the compatibility check (`compat.py`): the four
integrations ask the same confirmations (B episodes, live oracle as L4), spend the same
grant uses, run the same arguments and give the agent the same view as the shim, call by
call (README.md).

## axor-wrap `runtime.py:235` — "denied-but-executed"

At `origin/main` (`34a93e9`), `WrappedToolset.call`:

```
232        if not decision.allowed and self.enforcement == ENFORCEMENT_ON:
233            raise ToolDenied(decision.reason, decision.category)
234        # observe-only: the verdict is recorded and reported, the call proceeds.
235        # register_output still runs, so a denied-but-executed call's output
238        output = self._tools[name](**args)
```

A denied call executes exactly when `self.enforcement != "on"`. The constructor admits
only `"on"` and `"off"` (`runtime.py:130`), so through the API that is `enforcement="off"`:
the observe-only arm of an experiment (`experiment.enforcement_of(arm)`), which is meant to
measure what an ungoverned agent does. Under `"on"` a denied call never executed. The gap:
`enforcement` is a public attribute and the test was "equals on", so any other value set
after construction (`ts.enforcement = "ON"`) ran denied calls — fail-open.

Now (`runtime.py:268-285`): an admitted call runs; a refused one raises unless
`enforcement == "off"` (`runtime.py:278`) — fail-closed for every other value — and only
that branch executes a denied call (`runtime.py:284`). Tests:
`tests/test_kernel_gate.py::test_enforce_mode_never_executes_a_denied_call` and
`::test_observe_mode_is_the_only_one_that_executes_a_denied_call`.

## The description parser (MODEL.md 9.15): where it comes from, who writes it, what happens without it

A description grant ("the channel starting with External") is computed by the kernel
from the *structure* of a declared description source's output (`description_sources`),
never from its text. Turning a tool's output into that structure depends on the
platform (AgentDojo's `get_channels` prints a YAML list; another platform returns JSON),
so it is a parser `structured(tool, result) -> structure | None` that the kernel does not
contain and no integration ships. **The operator writes it** for the tools it deploys;
for AgentDojo it is `../ajar/axor_ajar.py::structured` (23 lines).

| path | where the operator passes it | what the parser receives | where it is used |
|---|---|---|---|
| axor-claude | `make_session(structured=…)` `axor_claude/__init__.py:53,102` (in-process); with `daemon_socket` the daemon's `--structured` | the handler's return value | `gate.py:119-122` |
| axor-openrouter | `make_session(structured=…)` `axor_openrouter/__init__.py:60,114`; with `daemon_socket` the daemon's | the handler's return value | `gate.py:119-122` |
| axor-langchain | `AxorMiddleware(structured=…)` `middleware.py:966` (→ `governed.py:45`); `wrap_tools` wrappers share that gate | middleware: the `ToolMessage` text; `AxorToolWrapper`: the tool's `invoke` result | `gate.py:119-122` |
| axor-wrap | `WrappedToolset(structured=…)` / `wrap_callables(structured=…)` `runtime.py:153,367` | the callable's return value | `gate.py:119-122` |
| axor-daemon | `--structured module.path:function` (or `AXOR_DAEMON_STRUCTURED`) `__main__.py:122,261` → `DaemonEnforcer(structured=)` `enforcer.py:88` | the handler's return value | `enforcer.py:227-230` |

**Without it** no description grant is built. Nothing else changes: a call that only a
description would authorize meets the gate exactly as if the request had not described
it, and is refused (`operator_set` in the test scenario; in AgentDojo `operator_set` or
`reference_origin`, or an L4 question). A missing parser can only remove admissions,
never add one: description grants are the only thing it feeds, and a grant only admits.

Tested, through each path's public entry point, on one scenario ("Add Charlie to the
channel starting with External"; `get_channels` lists four channels): with the parser
the call runs; without it it is refused with `operator_set` and the tool never runs —
`tests/test_kernel_gate.py::test_description_grant_needs_the_parser` in axor-claude,
axor-openrouter and axor-langchain, `::DescriptionParserTest` in axor-wrap,
`tests/test_governance.py::test_a_description_grant_needs_the_platform_parser` in
axor-daemon. Measured on the 581 AgentDojo episodes by `compat.py --parser both`
(README.md, "Parser ablation"): for every path, every call admitted without the parser
is admitted with it.
