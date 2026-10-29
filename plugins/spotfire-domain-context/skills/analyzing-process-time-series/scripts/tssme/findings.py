"""Finding: the uniform output contract of every check.

Every check returns a list[Finding]. Nothing else. This is the second contract in the
system (the unit card schema is the first) and it is what lets the agent narrate results,
lets the report layer render them, and lets tests assert on them.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

# What a finding IS, which is independent of how severe it is. Severity alone cannot carry
# this: a candidate diagnosis downgraded to info for unresolved confounders is not the same
# statement as "this invariant passed", and an invariant that could not be evaluated is the
# opposite of a verification. Routing a report on severity alone files all three under
# "healthy" and quietly loses the two that matter.
KINDS = {
    "defect",         # something is wrong; the default
    "candidate",      # a possible diagnosis, not yet established
    "verified",       # positively checked and sound
    "not_evaluated",  # could not be tested here; a coverage gap, never reassurance
}


@dataclass
class Finding:
    check_id: str
    unit_id: str
    severity: str                       # info | low | medium | high | critical
    summary: str                        # one sentence, states the defect
    roles: list[str] = field(default_factory=list)
    window: tuple[str, str] | None = None       # (start_iso, end_iso) of the evidence
    statistic: dict[str, Any] = field(default_factory=dict)  # the numbers behind the claim
    interpretation: str = ""            # SME reading: what it means in the plant
    confounders_tested: dict[str, str] = field(default_factory=dict)  # id -> ruled_out | not_ruled_out | untested
    confidence: str = "unconfirmed"     # unconfirmed | corroborated | confirmed
    next_step: str = ""                 # what a human should do to verify
    source: str = ""                    # literature backing the rule that fired
    kind: str = "defect"                # defect | candidate | verified | not_evaluated

    def __post_init__(self) -> None:
        if self.severity not in SEVERITY_ORDER:
            raise ValueError(f"{self.check_id}: bad severity {self.severity!r}")
        if self.kind not in KINDS:
            raise ValueError(f"{self.check_id}: bad kind {self.kind!r}")

    @property
    def rank(self) -> int:
        return SEVERITY_ORDER[self.severity]

    @property
    def unresolved_confounders(self) -> list[str]:
        return [k for k, v in self.confounders_tested.items() if v != "ruled_out"]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sort_findings(findings: list[Finding]) -> list[Finding]:
    """Most severe first; within a severity, confirmed before unconfirmed."""
    conf = {"confirmed": 0, "corroborated": 1, "unconfirmed": 2}
    return sorted(findings, key=lambda f: (-f.rank, conf.get(f.confidence, 3), f.check_id))
