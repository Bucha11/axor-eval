"""The Control Plane this machine reports to — the one ``axor-wrap connect``
saved, so ``--plane`` needs no address and no key on the command line or in
the shell. The environment (``AXOR_PLANE_URL`` / ``AXOR_INGEST_KEY``) still
wins; an axor-wrap without ``connect`` (before 0.3.1) falls back to it alone.
"""
from __future__ import annotations

import os


def plane_url() -> str:
    try:
        from axor_wrap import connection
    except ImportError:
        return os.environ.get("AXOR_PLANE_URL", "")
    return connection.plane_url() or ""


def ingest_key() -> str:
    try:
        from axor_wrap import connection
    except ImportError:
        return os.environ.get("AXOR_INGEST_KEY") or os.environ.get("AXOR_API_KEY", "")
    return connection.ingest_key() or os.environ.get("AXOR_API_KEY", "")
