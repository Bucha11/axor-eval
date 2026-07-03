"""Pytest bootstrap: make the axor-core AgentDojo driver importable.

The eval_* harness modules import the AgentDojo driver (``run_agentdojo``,
``agentdojo_adapter``) that lives in the axor-core repo. Importing ``_corepath``
here, before collection, puts the sibling axor-core checkout on ``sys.path`` so
the harness modules (and the tests that import them) resolve.
"""
import _corepath  # noqa: F401
