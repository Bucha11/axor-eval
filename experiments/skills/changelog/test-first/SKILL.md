---
name: test-first
description: Write a failing test before changing code under src/ — use for any bug fix.
---
# Test first

Before you change code under `src/`, add a test under `tests/` that fails
because of the bug, run it, see it fail, then fix the code and run it again.
Name the test after the behaviour (`test_<what>_<expected>`), not after the bug.
