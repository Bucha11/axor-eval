---
name: house-style
description: Our Python house style — docstrings, naming, imports. Use when writing new modules.
---
# House style

- One module per concept; a module docstring that says what it is for.
- Names say what a thing is: `limiter`, not `lim`; `remaining_calls`, not `rc`.
- Imports: standard library, third party, ours — one blank line between groups.
- No abbreviations in public names. No single-letter names outside comprehensions.
- Prefer a dataclass to a dict that travels between functions.
