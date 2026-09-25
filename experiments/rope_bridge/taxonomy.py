"""Hand-authored axor tool taxonomy for the banking suite.

SCHEMA-ONLY: each tool is classified by its intrinsic data-flow role read off
the tool's signature/docstring, NOT by peeking at the injection tasks (that
would be authoring-to-the-benchmark, the exact A3 critique). One role list per
tool; a tool absent from every list is 'unclassified' and STRICT denies it.

Rationale per tool (banking):

  egress_sinks (send value/data outside the user's account):
    send_money, schedule_transaction, update_scheduled_transaction
      -> driving arg = recipient (where the money/value goes).

  untrusted_sources (return third-party-authored content the attacker can write):
    read_file                     -> arbitrary file body (bill files, etc.)
    get_most_recent_transactions  -> transaction 'subject'/'description' are
                                     counterparty-authored free text (the
                                     documented injection carrier).

  sensitive_sources (return the user's own private data; arm the confidentiality
  floor so it cannot later egress):
    get_user_info                 -> the user's name/address/PII.
    NOTE: get_iban / get_scheduled_transactions are the user's own account
    state; classifying them sensitive would arm the floor on every subsequent
    money transfer (banking's only sink), collapsing utility. Banking's threat
    is integrity (redirect a payment), not text-exfil (it has no email/post
    tool), so we keep the floor for genuine PII only. This is an explicit,
    auditable taxonomy judgment — flip SENSITIVE_SOURCES to include them to
    measure the floor's utility cost.

  benign_tools (observation, or a state-change axor's egress model does not
  cover): get_balance, get_iban, get_scheduled_transactions,
    update_password, update_user_info.
    LIMITATION: update_password/update_user_info are state-changing writes whose
    content param ROPE guards as PROMPT (must come from the request). axor's
    egress model has no 'must-be-from-prompt' marker for a non-egress cred/PII
    write, so they land in benign_tools here. Documented gap, not a silent one.
"""
from __future__ import annotations

import sys
sys.path.insert(0, "/home/user/axor-core")

BANKING = {
    "egress_sinks": {"send_money", "schedule_transaction", "update_scheduled_transaction"},
    "driving_args": {
        "send_money": ["recipient"],
        "schedule_transaction": ["recipient"],
        "update_scheduled_transaction": ["recipient"],
    },
    "untrusted_sources": {"read_file", "get_most_recent_transactions"},
    "sensitive_sources": {"get_user_info"},
    "benign_tools": {
        "get_balance", "get_iban", "get_scheduled_transactions",
        "update_password", "update_user_info",
    },
    # Optional: charge the consequence axis. update_password / update_user_info are
    # credential/PII-changing actions; declaring them CATASTROPHIC (> the default
    # CONSEQUENTIAL unattended ceiling) makes consequence_gate deny them unattended.
    # This is content-blind (denies legit AND injected alike) — unlike ROPE's
    # origin PROMPT marker — so it closes the it7 password residual at a possible
    # clean-utility cost on legit change tasks. Empty = the as-run config.
    "consequence_overrides": {},
}

# Charged variant used by the second run.
from axor_core.contracts.canonical import ConsequenceClass as _C
BANKING_CHARGED = {**BANKING, "consequence_overrides": {
    "update_password": _C.CATASTROPHIC,
    "update_user_info": _C.CATASTROPHIC,
}}

# ORIGIN variant (the sound, no-oracle config): integrity_default=context, no
# ground-truth allowlist anywhere. Credential/PII writes are integrity_sinks: their
# driving arg must trace to a trusted origin (the user's request), reproducing
# ROPE's PROMPT marker via the integrity axis. Egress recipients are likewise
# guarded by the integrity axis (no value_policy enum), so a recipient the user
# named passes and one derived from attacker-writable content is denied.
BANKING_ORIGIN = {
    "egress_sinks": {"send_money", "schedule_transaction", "update_scheduled_transaction"},
    "integrity_sinks": {"update_password", "update_user_info"},
    "driving_args": {
        "send_money": ["recipient"],
        "schedule_transaction": ["recipient"],
        "update_scheduled_transaction": ["recipient"],
        "update_password": ["password"],
        "update_user_info": ["first_name", "last_name", "street", "city"],
    },
    "untrusted_sources": {"read_file", "get_most_recent_transactions"},
    "sensitive_sources": {"get_user_info"},
    "benign_tools": {"get_balance", "get_iban", "get_scheduled_transactions"},
    # Explicit consequence class for EVERY tool. Upstream STRICT is fail-closed on
    # the consequence axis (commit fc73b0c): a tool with no explicit class is
    # treated CATASTROPHIC and denied at the consequence gate before any other axis
    # runs — so all tools must be classified, not just the writes. This is an
    # intrinsic action-class property (read = BENIGN, money/credential change =
    # CONSEQUENTIAL), schema-only, NOT a value allowlist. Pinning the writes at the
    # default unattended ceiling (CONSEQUENTIAL) lets the consequence gate pass so
    # the origin check (integrity_sinks + context) is what decides.
    "consequence_overrides": {
        # reads
        "get_balance": _C.BENIGN, "get_iban": _C.BENIGN,
        "get_most_recent_transactions": _C.BENIGN, "get_scheduled_transactions": _C.BENIGN,
        "read_file": _C.BENIGN, "get_user_info": _C.BENIGN,
        # state changes (at/below the unattended ceiling; origin axis decides)
        "send_money": _C.CONSEQUENTIAL, "schedule_transaction": _C.CONSEQUENTIAL,
        "update_scheduled_transaction": _C.CONSEQUENTIAL,
        "update_password": _C.CONSEQUENTIAL, "update_user_info": _C.CONSEQUENTIAL,
    },
}
