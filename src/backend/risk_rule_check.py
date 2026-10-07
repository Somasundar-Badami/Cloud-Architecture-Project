"""
risk_rule_check.py

Independent, best-effort re-implementation of the Section 3 severity rules
from the frozen implementation spec, expressed purely in terms of the
engineered ML features (public_exposure, security_sensitivity,
privilege_change, encryption_change, change_magnitude).

IMPORTANT: this is NOT the source of truth for risk_label. The source of
truth is the approved 20-scenario table (scenario_definitions.py ->
SCENARIO_REGISTRY[i]["risk_label"]), which a human derived directly from
the Section 3 rules with full context per scenario.

This module exists purely as a VALIDATION cross-check: for every generated
record we ask "does this simple 5-feature rule-of-thumb reach the same
label the approved table assigned?" Agreement is expected for most
scenarios but is not guaranteed to be 100%, because five coarse features
cannot always capture every nuance a security reviewer considered (for
example: an unplanned security-group cross-reference (E7) and an IAM
permissions-boundary removal (I6) can produce an identical feature
signature -- privilege_change=True, change_magnitude=Medium -- yet were
deliberately assigned different approved severities, because one expands
lateral movement only within the internal network while the other removes
a global safety net). Disagreements are reported in the validation report,
not silently hidden or forced to match.
"""

from typing import Dict, Any


def rule_based_label(features: Dict[str, Any]) -> str:
    """
    Apply the Section 3 severity rules to an engineered feature dict.

    Rule (documented, matches frozen spec Section 3):
      Critical: public exposure of a High-sensitivity attribute,
                OR privilege escalation with a High-magnitude change
      High:     encryption removed, OR any privilege change not already
                Critical, OR public exposure of a non-High-sensitivity
                attribute
      Medium:   Medium/High intrinsic sensitivity with a real (non-"None")
                change magnitude, not already Critical/High
      Low:      everything else, including no-drift records
    """
    public_exposure = features["public_exposure"]
    security_sensitivity = features["security_sensitivity"]
    privilege_change = features["privilege_change"]
    encryption_change = features["encryption_change"]
    change_magnitude = features["change_magnitude"]

    if (public_exposure and security_sensitivity == "High") or (
        privilege_change and change_magnitude == "High"
    ):
        return "Critical"

    if encryption_change or privilege_change or (public_exposure and security_sensitivity != "High"):
        return "High"

    if security_sensitivity in ("Medium", "High") and change_magnitude != "None":
        return "Medium"

    return "Low"
