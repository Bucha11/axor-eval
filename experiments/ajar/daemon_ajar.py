"""The Ajar wrapper through axor-daemon: same governor, decided daemon-side over the socket.

Per (suite, configuration) one daemon is started with its own CLI:

    python -m axor_daemon start --governance <cfg>.yaml --operator-tools handlers \
        --confirm-socket <c.sock> --handler daemon_replay_handlers:T_<tool> ...

<cfg>.yaml is config_rule/<suite>.yaml + context integrity, request-only, and for the
grant configurations the R0 grant args (+ the L2s templates for banking).

decide(spec, context, candidate), per test:
  1. a NEW connection = a new daemon session (fresh governor, grants, counters),
     hello.task = the task's request (seeds trusted origins and the L1 grants);
  2. each executed prefix step is sent as a tool_call; the handler returns the step's
     output (written by this harness to the handler's file), so the daemon registers
     it itself and spends a grant use daemon-side;
  3. the candidate is sent as a tool_call and the daemon's decision is the verdict.
     The candidate does reach a handler when approved — a replay handler with no
     effect — and the session is closed right after, so nothing it registers or
     spends survives into another test (no rollback needed).
L4: the daemon asks its operator socket; an operator thread here answers with the
same oracle as the in-process wrapper (whole-call digest against the plan). The
agent connection never answers a confirmation.
"""
from __future__ import annotations

import json
import os
import socket
import struct
import subprocess
import tempfile
import threading
import time
from typing import Any

import yaml

import axor_ajar
from ajar.core.ir import TaskSpec
from ajar.core.types import Candidate, ContextRef, Verdict

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON_REPO = os.environ.get("AXOR_DAEMON_REPO", "/home/user/axor-daemon")
DAEMON_PY = os.environ.get("AXOR_DAEMON_PY", os.path.join(DAEMON_REPO, ".venv", "bin", "python"))
_H = struct.Struct(">I")


def _send(sock, payload):
    body = json.dumps({"v": 1, **payload}).encode()
    sock.sendall(_H.pack(len(body)) + body)


def _recv(sock):
    def exact(n):
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("daemon closed the connection")
            buf += chunk
        return buf
    n = _H.unpack(exact(_H.size))[0]
    return json.loads(exact(n))


def suite_tools(suite: str) -> list[str]:
    from agentdojo.task_suite.load_suites import get_suite
    from check_wrapper import VERSIONS
    return sorted(t.name for t in get_suite(VERSIONS[suite], suite).tools)


def write_config(suite: str, grants: bool, grant_args: dict, out: str) -> str:
    if os.environ.get("AXOR_AJAR_FINAL") == "1":
        # the final configuration (MODEL.md 8.7 + 8.10) as it is: its own grant args,
        # context / request-only, tuple L2 from its value policies (no file templates)
        cfg = yaml.safe_load(open(os.path.join(axor_ajar.CONFIG_DIR, f"{suite}.yaml")))
        assert cfg["integrity_default"] == "context" and cfg["integrity_origins"] == "request-only"
        yaml.safe_dump(cfg, open(out, "w"), sort_keys=True)
        return out
    cfg = yaml.safe_load(open(os.path.join(HERE, "config_rule", f"{suite}.yaml")))
    cfg["integrity_default"] = "context"
    cfg["integrity_origins"] = "request-only"
    if grants:
        cfg["grant_args"] = grant_args.get(suite, {})
        if suite in axor_ajar.TEMPLATES_SAFE:
            cfg["grant_templates"] = axor_ajar.TEMPLATES_SAFE[suite]
    yaml.safe_dump(cfg, open(out, "w"), sort_keys=True)
    return out


class Daemon:
    """One daemon process (real CLI) for one suite and configuration."""

    def __init__(self, suite: str, config_path: str, workdir: str, confirm: bool = True) -> None:
        self.suite = suite
        self.tools = suite_tools(suite)
        self.sock = os.path.join(workdir, f"{suite}.sock")
        self.confirm_sock = os.path.join(workdir, f"{suite}.confirm.sock")
        self.file = os.path.join(workdir, f"{suite}.out")
        open(self.file, "w").close()
        env = {**os.environ, "AJAR_REPLAY_FILE": self.file, "AJAR_REPLAY_TOOLS": ",".join(self.tools),
               "PYTHONPATH": os.pathsep.join([HERE, DAEMON_REPO])}
        cmd = [DAEMON_PY, "-m", "axor_daemon", "start", "--socket", self.sock, "--governance", config_path,
               "--operator-tools", "handlers", "--log-level", "WARNING"]
        if confirm:  # only the L4 configuration has an operator confirm endpoint
            cmd += ["--confirm-socket", self.confirm_sock]
        for t in self.tools:
            cmd += ["--handler", f"daemon_replay_handlers:T_{t}"]
        self.log = open(os.path.join(workdir, f"{suite}.log"), "w")
        self.proc = subprocess.Popen(cmd, env=env, stdout=self.log, stderr=subprocess.STDOUT)
        for _ in range(300):
            if os.path.exists(self.sock) and (not confirm or os.path.exists(self.confirm_sock)):
                break
            if self.proc.poll() is not None:
                raise RuntimeError(f"daemon for {suite} exited: see {self.log.name}")
            time.sleep(0.05)
        else:
            raise RuntimeError(f"daemon for {suite} did not start")
        self.operator = Operator(self.confirm_sock) if confirm else NoOperator()

    def session(self, task: str) -> "Session":
        return Session(self, task)

    def stop(self) -> None:
        self.operator.close()
        self.proc.terminate()
        self.proc.wait(timeout=10)
        self.log.close()


class Operator(threading.Thread):
    """The confirm endpoint's client: answers each confirm_request with ``policy``."""

    def __init__(self, path: str) -> None:
        super().__init__(daemon=True)
        self.s = socket.socket(socket.AF_UNIX)
        self.s.connect(path)
        _send(self.s, {"type": "operator"})
        assert _recv(self.s)["type"] == "ready"
        self.policy = None  # callable(sink, args) -> bool, set per test
        self.asked = 0
        self.start()

    def run(self) -> None:
        try:
            while True:
                m = _recv(self.s)
                if m.get("type") != "confirm_request":
                    continue
                self.asked += 1
                ok = bool(self.policy and self.policy(m["sink"], m["args"]))
                _send(self.s, {"type": "confirm_response", "id": m["id"], "approve": ok})
        except (ConnectionError, OSError):
            pass

    def close(self) -> None:
        try:
            self.s.close()
        except OSError:
            pass


class NoOperator:
    policy = None
    asked = 0

    def close(self) -> None:
        pass


class Session:
    def __init__(self, daemon: Daemon, task: str) -> None:
        self.d = daemon
        self.s = socket.socket(socket.AF_UNIX)
        self.s.connect(daemon.sock)
        _send(self.s, {"type": "hello", "mode": "production", "task": task})
        r = _recv(self.s)
        if r.get("type") != "ready":
            raise RuntimeError(f"daemon rejected the session: {r}")
        self.n = 0

    def call(self, tool: str, args: dict, output: str | None) -> dict:
        """Send one tool_call; ``output`` is what the handler returns if approved."""
        with open(self.d.file, "w") as f:
            f.write(output or "")
        self.n += 1
        _send(self.s, {"type": "tool_call", "call_id": f"c{self.n}", "tool": tool, "args": args,
                       "allowed_tools": self.d.tools})
        return _recv(self.s)

    def close(self) -> None:
        try:
            _send(self.s, {"type": "bye"})
        except OSError:
            pass
        self.s.close()


class DaemonDefense:
    """Ajar Defense protocol, verdicts from the daemon."""

    def __init__(self, name: str, daemons: dict[str, Daemon], oracle: bool = False,
                 grant_args: dict | None = None, shadow=None) -> None:
        # MODEL.md §9: with references, the agent writes a hidden value as its reference. The
        # table lives in the daemon; with a fixed references_seed an in-process shadow governor
        # mints the same names, so it can write the calls as the agent would.
        self.shadow = shadow
        self.name = name
        self.daemons = daemons
        self.oracle = oracle
        self.privilege_surface = ("TOOL", "PARAMETER", "SEQUENCE", "PROVENANCE")
        self.times: list[float] = []
        self.log: list[dict[str, Any]] = []
        self._matcher = None
        if oracle:
            # the very same oracle the in-process L4 row uses
            kwargs, _ = axor_ajar.grants_kwargs("L1+L2s+L4", grant_args=grant_args, confirm="oracle")
            self._kwargs = kwargs

    def prepare(self, spec: TaskSpec, llm=None) -> TaskSpec:
        return spec

    def decide(self, spec: TaskSpec, ctx: ContextRef, cand: Candidate) -> Verdict:
        d = self.daemons[spec.task.suite]
        if self.oracle:
            confirmer = self._kwargs(spec)["confirmer"]
            d.operator.policy = lambda sink, args: confirmer.policy(None, (sink, args))
        steps = axor_ajar.PREFIXES.outputs(spec, ctx)
        t0 = time.perf_counter()
        s = d.session(spec.prompt)
        g = self.shadow.governor(spec) if self.shadow is not None else None

        def agent(tool, args, out):
            if g is None:
                return dict(args)
            a = axor_ajar.agent_args(g, dict(args))
            dd = g.evaluate(tool, a)
            if getattr(dd, "grant_id", None) is not None:
                k = g.spend(dd, axor_ajar.spend_args(dd, dict(args)))
                if k is not None:
                    g.grant_store.commit(k)
            if out is not None:
                axor_ajar.present(g, dd, out)
            return a
        try:
            for call, out in steps:
                s.call(call.tool, agent(call.tool, call.args, out), out)
            r = s.call(cand.tool, axor_ajar.agent_args(g, dict(cand.args)) if g is not None else dict(cand.args), "")
        finally:
            s.close()
        self.times.append(time.perf_counter() - t0)
        allowed = r["decision"] == "approved"
        self.log.append({"task": str(spec.task), "ctx": ctx.label, "prefix": list(ctx.prefix),
                         "tool": cand.tool, "args": dict(cand.args), "allowed": allowed,
                         "reason": r.get("denial_reason")})
        return Verdict.ALLOW if allowed else Verdict.DENY


def start_daemons(config: str, grant_args: dict, workdir: str | None = None,
                  suites=("banking", "slack", "travel", "workspace")) -> dict[str, Daemon]:
    workdir = workdir or tempfile.mkdtemp(prefix=f"axd-{config}-")
    out = {}
    for s in suites:
        path = write_config(s, config != "a", grant_args, os.path.join(workdir, f"{s}.yaml"))
        out[s] = Daemon(s, path, workdir, confirm=(config == "c"))
    return out
