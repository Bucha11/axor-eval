from __future__ import annotations


class AxorEvalError(Exception):
    """Base error for all axor-eval domain errors."""


class ContractViolation(AxorEvalError):
    """Raised when an EvidenceCase or scoring contract invariant is violated."""
