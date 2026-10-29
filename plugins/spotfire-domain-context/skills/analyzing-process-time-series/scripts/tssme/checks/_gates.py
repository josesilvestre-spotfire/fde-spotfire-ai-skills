"""Preconditions shared by every check that evaluates a card invariant.

This lives outside any one check module because the gate has to hold everywhere. An
invariant declares `requires_roles` once, on the card; if only some of the checks that
consume invariants honour it, the declaration protects the `identity` invariants and
silently fails to protect the `range` ones, which is worse than not having the gate at
all -- the card author believes they are covered.
"""

from __future__ import annotations

import re

from ..findings import Finding
from ..prep import Context


def unmet_precondition(ctx: Context, inv: dict, check_id: str) -> Finding | None:
    """Report an invariant whose preconditions are not in the data, instead of testing it.

    Some invariants are only true under a condition you cannot see. A pump's head falls
    with flow along its H-Q curve at CONSTANT speed and a fixed number of pumps; a unit
    that brings a second pump online or ramps a VFD to push more throughput will show head
    RISING with flow, and the invariant will fire a confident violation describing nothing
    but normal operation. Declaring `requires_roles: [pump_speed]` turns that into a
    visible "not evaluated" rather than a wrong answer.

    Returns None when the preconditions are met, so a caller can use it as a guard.
    """
    need = [r for r in inv.get("requires_roles", []) if r not in ctx.X.columns]
    if not need:
        return None
    return Finding(
        check_id=check_id, unit_id=ctx.unit_id, severity="info",
        roles=sorted(need),
        summary=(f"Invariant {inv['id']!r} was not evaluated: it requires "
                 f"{', '.join(need)}, which is not in this dataset."),
        statistic={"invariant": inv["id"], "expr": inv.get("expr", ""),
                   "missing_roles": need},
        kind="not_evaluated",
        interpretation="The invariant holds only under a condition this dataset cannot "
                       "evidence. Testing it anyway would produce a confident violation that "
                       "describes the missing precondition rather than the equipment.",
        next_step=f"Add {', '.join(need)} to the tag map to enable this invariant.",
        source=inv.get("source", ""),
    )


_EXPR_HELPERS = {"np", "pd", "abs", "mean", "in", "increasing", "decreasing", "n",
                 "and", "or", "not", "True", "False", "None"}
# A name is not preceded by a word character or a dot, so `1e6` and `np.log` are skipped.
_NAME = re.compile(r"(?<![\w.])[A-Za-z_]\w*")


def missing_operands(ctx: Context, expr: str) -> list[str]:
    """Names in an invariant expression that are neither data columns nor helpers."""
    names = set(_NAME.findall(expr))
    return sorted(n for n in names - _EXPR_HELPERS if n not in ctx.X.columns)


def not_evaluated(ctx: Context, inv: dict, check_id: str, reason: str) -> Finding:
    """Report an invariant a check could not evaluate, instead of skipping it silently.

    A card author who wrote an invariant expects it to be tested. When its operands are not
    in the data, or its expression has a form the check does not parse, the honest output
    is a visible coverage gap, the same outcome the requires_roles gate produces.
    """
    return Finding(
        check_id=check_id, unit_id=ctx.unit_id, severity="info",
        summary=f"Invariant {inv['id']!r} was not evaluated: {reason}.",
        statistic={"invariant": inv["id"], "expr": inv.get("expr", ""), "reason": reason},
        kind="not_evaluated",
        interpretation="The invariant could not be tested against this dataset, so it provides "
                       "no evidence either way.",
        next_step="Map the missing roles in the tag map, or correct the expression on the card.",
        source=inv.get("source", ""),
    )
