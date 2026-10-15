"""Line accounting for the four integrations of the current kernel.

Per package:
  lift         lines added / removed from origin/main to the branch head, split into
               source, tests and the rest (CI, changelog, fixtures)
  integration  the source that connects the agent framework to the kernel: the tool-call
               normalizer, the execution wrapper, the output registration (gate.py is
               shared byte for byte and counted in every package)
  rest         everything else in the package source (transport, compression, CLI, ...)

A line is counted twice: physically, and as code (not blank, not a comment, not a
docstring). Files that mix both (axor-langchain's middleware.py) are split by function
with ``ast``.

    python accounting.py /home/user   # the parent directory of the four checkouts
"""
from __future__ import annotations

import ast
import io
import json
import os
import subprocess
import sys
import tokenize

# file (or "file::function") -> part. Anything not listed is "rest:<first path part>".
INTEGRATION = {
    "axor-claude": {
        "axor_claude/gate.py": "execution wrapper + output registration (shared gate.py)",
        "axor_claude/capability_gate.py": "execution wrapper (session executor + request seeding)",
        "axor_claude/events.py": "normalizer (stream events -> tool calls)",
        "axor_claude/normalizer.py": "normalizer (tool call -> NormalizedIntent)",
        "axor_claude/__init__.py::make_session": "wiring (make_session)",
    },
    "axor-openrouter": {
        "axor_openrouter/gate.py": "execution wrapper + output registration (shared gate.py)",
        "axor_openrouter/capability_gate.py": "execution wrapper (session executor + request seeding)",
        "axor_openrouter/__init__.py::make_session": "wiring (make_session)",
    },
    "axor-langchain": {
        "axor_langchain/gate.py": "execution wrapper + output registration (shared gate.py)",
        "axor_langchain/governed.py": "execution wrapper (ToolGate, request seeding)",
        "axor_langchain/normalizer.py": "normalizer",
        "axor_langchain/wrapper.py": "execution wrapper (AxorToolWrapper)",
        "axor_langchain/middleware.py::_gate_request": "execution wrapper (middleware)",
        "axor_langchain/middleware.py::_gate_result": "output registration (middleware)",
        "axor_langchain/middleware.py::wrap_tool_call": "execution wrapper (middleware)",
        "axor_langchain/middleware.py::awrap_tool_call": "execution wrapper (middleware)",
    },
    "axor-wrap": {
        "axor_wrap/gate.py": "execution wrapper + output registration (shared gate.py)",
        "axor_wrap/runtime.py": "execution wrapper (WrappedToolset)",
        "axor_wrap/compile.py": "config compilation (manifests -> governor)",
    },
}
REST_NAMES = {
    "axor-claude": {"executor.py": "model loop / transport", "tools": "tool handlers",
                    "extensions": "skills / plugins", "tool_definitions.py": "tool schemas",
                    "security.py": "probe / sentinel wiring"},
    "axor-openrouter": {"executor.py": "model loop", "transport.py": "transport", "routing": "routing",
                        "caching": "caching", "cascade": "cascade", "rates": "rates",
                        "governance": "budget routing", "cli_extensions.py": "CLI",
                        "tools.py": "tool schemas", "envelope_codec.py": "codecs",
                        "usage_codec.py": "codecs", "bus.py": "model loop", "loaders.py": "skills",
                        "security.py": "probe / sentinel wiring"},
    "axor-langchain": {"middleware.py": "compression / tool selection / budget / telemetry",
                       "judge.py": "quality judge"},
    "axor-wrap": {"detect.py": "scanner", "manifest.py": "manifests", "roles.py": "manifests",
                  "cli.py": "CLI", "connect.py": "control plane", "plane": "control plane",
                  "trace.py": "trace", "experiment.py": "experiments", "errors.py": "errors"},
}


def code_lines(src: str, lo: int = 1, hi: int | None = None) -> tuple[int, int]:
    """(physical, code) lines of src[lo..hi]: code = not blank, comment or docstring."""
    lines = src.splitlines()
    hi = hi or len(lines)
    doc: set[int] = set()
    try:
        tree = ast.parse(src)
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                    and isinstance(getattr(body[0], "value", None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                doc.update(range(body[0].lineno, body[0].end_lineno + 1))
    except SyntaxError:
        pass
    comment: set[int] = set()
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT and not lines[tok.start[0] - 1][:tok.start[1]].strip():
            comment.add(tok.start[0])
    phys = hi - lo + 1
    code = sum(1 for i in range(lo, hi + 1)
               if lines[i - 1].strip() and i not in doc and i not in comment)
    return phys, code


def functions(src: str) -> dict[str, tuple[int, int]]:
    out = {}
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            out.setdefault(node.name, (start, node.end_lineno))
    return out


def account(root: str, pkg: str) -> dict:
    repo = os.path.join(root, pkg)
    mod = pkg.replace("-", "_")
    parts: dict[str, list[int]] = {}
    for dirpath, dirs, files in os.walk(os.path.join(repo, mod)):
        dirs[:] = [d for d in dirs if not d.startswith("__")]
        for f in files:
            if not f.endswith(".py"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, f), repo)
            src = open(os.path.join(repo, rel)).read()
            total = code_lines(src)
            taken = [0, 0]
            for key, label in INTEGRATION[pkg].items():
                path, _, fn = key.partition("::")
                if path != rel:
                    continue
                if fn:
                    lo, hi = functions(src)[fn]
                    p, c = code_lines(src, lo, hi)
                else:
                    p, c = total
                acc = parts.setdefault("integration: " + label, [0, 0])
                acc[0] += p
                acc[1] += c
                taken[0] += p
                taken[1] += c
            if taken[0] < total[0]:
                inner = os.path.relpath(rel, mod)
                head = inner.split(os.sep)[0]
                label = REST_NAMES[pkg].get(head, "other")
                acc = parts.setdefault("rest: " + label, [0, 0])
                acc[0] += total[0] - taken[0]
                acc[1] += total[1] - taken[1]
    integ = [sum(v[i] for k, v in parts.items() if k.startswith("integration")) for i in (0, 1)]
    rest = [sum(v[i] for k, v in parts.items() if k.startswith("rest")) for i in (0, 1)]
    return {"parts": parts, "integration": integ, "rest": rest, "lift": lift(repo, mod)}


def lift(repo: str, mod: str) -> dict:
    out = subprocess.run(["git", "-C", repo, "diff", "--numstat", "origin/main...HEAD"],
                         capture_output=True, text=True, check=True).stdout
    acc = {"source": [0, 0], "tests": [0, 0], "other": [0, 0]}
    files = {"source": [], "tests": [], "other": []}
    for line in out.splitlines():
        a, r, path = line.split("\t")
        kind = ("source" if path.startswith(mod + "/") and path.endswith(".py")
                else "tests" if path.startswith("tests/") and path.endswith(".py") else "other")
        acc[kind][0] += int(a) if a != "-" else 0
        acc[kind][1] += int(r) if r != "-" else 0
        files[kind].append(path)
    return {k: {"added": v[0], "removed": v[1], "files": files[k]} for k, v in acc.items()}


def main() -> None:
    root = sys.argv[1] if len(sys.argv) > 1 else "/home/user"
    res = {pkg: account(root, pkg) for pkg in INTEGRATION}
    for pkg, r in res.items():
        L = r["lift"]
        print(f"== {pkg}: lift src +{L['source']['added']}/-{L['source']['removed']}  "
              f"tests +{L['tests']['added']}/-{L['tests']['removed']}  "
              f"other +{L['other']['added']}/-{L['other']['removed']}  |  integration "
              f"{r['integration'][0]} lines ({r['integration'][1]} code)  rest {r['rest'][0]} ({r['rest'][1]} code)")
        for k, (p, c) in sorted(r["parts"].items()):
            print(f"     {k:<72} {p:>5} {c:>5}")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "accounting.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(res, open(out, "w"), indent=1)
    print("wrote", out)


if __name__ == "__main__":
    main()
