"""Live preflight for c9v5 (no model calls): verify the kernel commit, the four config files and the
harness match FREEZE_C9V5.md; exit non-zero on any mismatch. Run before any live launch.

    AXOR_CORE_REPO=/home/user/core-m1 python preflight_c9v5.py
"""
import hashlib
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.join(HERE, "..")
FREEZE = os.path.join(EXP, "FREEZE_C9V5.md")
CORE = os.environ.get("AXOR_CORE_REPO", "/home/user/core-m1")


def sha16(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]


def main():
    txt = open(FREEZE).read()
    want = dict(re.findall(r"config (\w+) \| config_m1_c9v5/\w+\.yaml sha256 ([0-9a-f]{16})", txt))
    want_harness = re.search(r"harness \| axor_ajar\.py sha256 ([0-9a-f]{16})", txt)
    want_kernel = re.search(r"kernel \| axor-core \S+ ([0-9a-f]{7,})", txt)
    ok = True
    # kernel commit
    head = subprocess.check_output(["git", "-C", CORE, "rev-parse", "--short", "HEAD"]).decode().strip()
    k = bool(want_kernel) and head.startswith(want_kernel.group(1))
    ok &= k
    print(f"[{'OK' if k else 'MISMATCH'}] kernel axor-core HEAD={head} want={want_kernel.group(1) if want_kernel else '?'}")
    # configs
    for s in ("banking", "slack", "travel", "workspace"):
        got = sha16(os.path.join(EXP, "config_m1_c9v5", f"{s}.yaml"))
        m = want.get(s) == got
        ok &= m
        print(f"[{'OK' if m else 'MISMATCH'}] config {s} sha256 {got} want {want.get(s)}")
    # harness
    got = sha16(os.path.join(EXP, "axor_ajar.py"))
    m = bool(want_harness) and want_harness.group(1) == got
    ok &= m
    print(f"[{'OK' if m else 'MISMATCH'}] harness axor_ajar.py sha256 {got} want {want_harness.group(1) if want_harness else '?'}")
    print("PREFLIGHT", "PASS" if ok else "FAIL — do not launch")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
