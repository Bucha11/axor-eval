# Skill eval example: changelog-entries

A project convention as a skill: every change to `src/` gets one line in
`CHANGELOG.md` in a fixed form. The task (fix an off-by-one in `src/limits.py`
and record it "the way this project records changes") is checked by the repo's
tests — the fix, and a changelog line in that form. Without the skill an agent
can fix the bug and still miss the form; with it, the question is whether it
reads the skill and follows it.

```bash
python -m axor_eval.skills run experiments/skills/changelog/skill-eval.json \
    --md report.md --out report.json            # Claude Code, 5 trials an arm
python -m axor_eval.skills run experiments/skills/changelog/skill-eval.json --agent codex
```

Needs the agent's CLI (`claude` / `codex`) logged in. Each trial works on a
throwaway copy of `repo/`; the skill is copied into `.claude/skills/` (or
`.codex/skills/`) only for the "with" arm.
