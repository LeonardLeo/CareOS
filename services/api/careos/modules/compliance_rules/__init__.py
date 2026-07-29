"""Compliance rules engine — cross-cutting, consumed by every phase.

Importing this package registers the Phase 1 rule set. Phase 2 (documentation flags) and
Phase 3 (claim scrubbing) add their own rule modules against the same `engine`.
"""

from careos.modules.compliance_rules.engine import (
    Finding,
    Rule,
    RuleConfig,
    RuleEngine,
    Severity,
    engine,
)
from careos.modules.compliance_rules.evv_rules import register_phase1_rules

register_phase1_rules()

__all__ = ["Finding", "Rule", "RuleConfig", "RuleEngine", "Severity", "engine"]
