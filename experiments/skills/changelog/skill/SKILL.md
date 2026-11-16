---
name: changelog-entries
description: How this project records a change — use whenever you change code under src/.
---
# Recording a change

Every change to `src/` gets one line in `CHANGELOG.md`, under `## Unreleased`,
in this exact form:

```
- <module>: <what changed, in the past tense> (fix|feat)
```

`<module>` is the file's name without `.py`. Example:

```
- limits: allow() now admits exactly n calls (fix)
```

Do not add a date or a version; the release script does that.
