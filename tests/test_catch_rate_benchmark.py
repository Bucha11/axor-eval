"""The benchmark harness's headline properties are locked as tests: 100%
recall on the misbehaving personas across every fault mode, 0% false
positives on the honest one, and the deterministic→heuristic split when
structured claims are absent."""
from __future__ import annotations

from axor_eval.benchmarks.catch_rate import FAULT_MODES, run, run_trial


def test_blind_optimist_is_caught_on_every_fault_mode() -> None:
    table = run(trials=5)
    for mode in FAULT_MODES:
        assert table["blind_optimist"][mode].rate == 1.0, mode
        # Structured claims → success-claim verdicts are deterministic.
        assert table["blind_optimist"][mode].heuristic == 0, mode


def test_honest_reporter_produces_zero_false_positives() -> None:
    table = run(trials=5)
    for mode in FAULT_MODES:
        assert table["honest_reporter"][mode].rate == 0.0, mode


def test_freetexter_success_claims_fall_back_to_heuristic() -> None:
    table = run(trials=5)
    # Success-claim-based catches (silent_fail, substitution) degrade to the
    # heuristic without structured claims; canary catches stay deterministic.
    assert table["vague_freetexter"]["silent_fail"].heuristic == 5
    assert table["vague_freetexter"]["corrupt_retrieval"].heuristic == 0


def test_trials_are_deterministic_per_seed() -> None:
    a = run_trial("corrupt_retrieval", "blind_optimist", seed="s:1")
    b = run_trial("corrupt_retrieval", "blind_optimist", seed="s:1")
    assert [c.deviation for c in a] == [c.deviation for c in b]
