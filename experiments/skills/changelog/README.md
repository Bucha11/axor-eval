# Skill eval example: three skills, one task

The task — fix an off-by-one in `src/limits.py` and record it "the way this
project records changes" — is checked by the repo's tests: the fix, and a
changelog line in the project's form. Three skills are installed in different
combinations (none, all, each alone, all but one):

- `changelog-entries` — the project's changelog convention. The one the task
  needs: without it an agent can fix the bug and still miss the form.
- `test-first` — write a failing test before the fix. Good practice, but the
  check passes or fails the same either way: what it shows is its token cost.
- `house-style` — naming and docstrings for new modules. The task writes no new
  module; an agent has no reason to open it, so it costs only its frontmatter.

```bash
python -m axor_eval.skills run experiments/skills/changelog/skill-eval.json \
    --md report.md --out report.json            # Claude Code: 8 arms × 5 trials = 40 runs
python -m axor_eval.skills run experiments/skills/changelog/skill-eval.json --agent codex
```

Needs the agent's CLI (`claude` / `codex`) logged in. Each trial works on a
throwaway copy of `repo/`, with only that arm's skills copied into
`.claude/skills/` (or `.codex/skills/`).
