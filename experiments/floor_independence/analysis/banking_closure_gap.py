#!/usr/bin/env python3
"""The product-closure gap on the stock AgentDojo banking prompts.

`product_closure.py` makes the point on one synthetic request. This measures it
on the benchmark's own 16 user tasks, mechanically, with no judgement about which
pairing a prompt intends.

Per task, from the prompt alone:

    R = the IBANs the request names          (π₁ of what a per-argument rule sees)
    A = the amounts the request names        (π₂)

Any rule that admits each argument independently admits all |R| × |A| tuples.
At most |R| of them can be authorised, since these prompts instruct at most one
payment per named recipient. So

    gap ≥ |R| · (|A| − 1)

is a LOWER bound on the unauthorised (recipient, amount) tuples such a rule
admits — mechanical, and conservative in the direction that understates the gap.

Caveats, stated because the number is only as good as they are:
  * a prompt that legitimately pays one recipient several amounts lowers the
    bound; none of the 16 does, but that is a reading, not a computation;
  * amounts are taken as decimal literals in the prompt, so an amount the agent
    must compute (task 3's "the difference") is not counted — again understating;
  * a task with |A| ≤ 1 or |R| = 0 contributes 0 and is reported as such. A zero
    is not evidence of safety: it means the prompt names too few values for
    mixing to be possible WITHIN one request.
"""

from __future__ import annotations

import re

_IBAN = re.compile(r"\b[A-Z]{2}[0-9]{2}[A-Z0-9]{10,30}\b")
# Decimal literals, excluding anything that reads as a date or a year. Same shape
# as axor's own `_TEXT_NUMBER`: either comma-grouped thousands OR a plain digit
# run. An earlier draft wrote `\d{1,3}(?:,\d{3})*`, which silently matches no
# four-digit number at all (2200 fails every backtrack), and reported a gap of
# zero on prompts that do name several amounts.
_AMOUNT = re.compile(
    r"(?<![\w.\-/:])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\w\-/:])"
)
_YEARISH = re.compile(r"^(19|20)\d{2}$")


def named_values(prompt: str) -> tuple[frozenset[str], frozenset[str]]:
    ibans = frozenset(_IBAN.findall(prompt))
    amounts = frozenset(
        m for m in _AMOUNT.findall(prompt)
        if not _YEARISH.match(m.replace(",", "")) and float(m.replace(",", "")) > 0
    )
    return ibans, amounts


def main() -> int:
    from agentdojo.task_suite.load_suites import get_suites

    suite = get_suites("v1")["banking"]
    rows: list[tuple[str, int, int, int]] = []
    for task_id, task in sorted(suite.user_tasks.items(), key=lambda kv: kv[0]):
        ibans, amounts = named_values(task.PROMPT)
        gap = len(ibans) * max(len(amounts) - 1, 0)
        rows.append((task_id, len(ibans), len(amounts), gap))

    print(f"{'task':<16}{'|R|':>5}{'|A|':>5}{'|R|·|A|':>9}{'gap ≥':>7}")
    print("-" * 42)
    for task_id, r, a, gap in rows:
        print(f"{task_id:<16}{r:>5}{a:>5}{r * a:>9}{gap:>7}")

    total_gap = sum(g for *_, g in rows)
    mixable = [t for t, r, a, g in rows if g > 0]
    print("-" * 42)
    print(f"tasks where mixing is possible within one request: "
          f"{len(mixable)}/{len(rows)}  ({', '.join(mixable)})")
    print(f"unauthorised tuples admitted by any per-argument rule, summed: ≥ {total_gap}")
    print(
        "\nThe declared taxonomies cannot narrow this: `value_policies` is a "
        "per-argument enum or range, so an operator can only ever write the "
        "PROJECTIONS. There is no field in which to write the relation."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
