"""advisor_contract.py — backward-compatible shim.

All contract logic now lives in ``llm.contracts``.  This module re-exports the
legacy names so existing imports (including tests) keep working.
"""

from __future__ import annotations

# Re-export the council payload functions under the old names
from llm.contracts import (
    council_payload_defaults as advisory_payload_defaults,  # noqa: F401
    parse_council_payload as parse_advisory_payload,  # noqa: F401
)

# Re-export the faction doctrine set used by normalizers
from society_content import FACTION_DOCTRINE_PROFILES  # noqa: F401
