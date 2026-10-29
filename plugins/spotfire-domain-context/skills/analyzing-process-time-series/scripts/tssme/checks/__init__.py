"""Check registry.

Every check is a function (Context) -> list[Finding], registered with an id, a category,
and the roles it needs. A check whose required roles are absent is SKIPPED and reported as
skipped -- it never silently passes. "No findings" and "could not run" are different
answers and the report keeps them apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..findings import Finding, sort_findings
from ..prep import Context

CheckFn = Callable[[Context], list[Finding]]


@dataclass
class CheckSpec:
    check_id: str
    category: str
    fn: CheckFn
    requires: tuple[str, ...] = ()
    description: str = ""


CHECKS: dict[str, CheckSpec] = {}

# Order is the analysis order. Data quality first, always: most "anomalies" in historian
# data are artifacts, and a finding built on a broken column is worse than no finding.
CATEGORY_ORDER = ["data_quality", "physical", "relational", "statistical", "sme"]


def check(check_id: str, category: str, requires: tuple[str, ...] = (), description: str = ""):
    def deco(fn: CheckFn) -> CheckFn:
        if check_id in CHECKS:
            raise ValueError(f"duplicate check id {check_id!r}")
        CHECKS[check_id] = CheckSpec(check_id, category, fn, requires, description)
        return fn
    return deco


@dataclass
class RunResult:
    findings: list[Finding]
    ran: list[str]
    skipped: dict[str, str]
    errored: dict[str, str]


def run_checks(ctx: Context, enabled: list[str] | None = None) -> RunResult:
    enabled = enabled if enabled is not None else ctx.card.enabled_checks
    unknown = [c for c in enabled if c not in CHECKS]
    if unknown:
        raise ValueError(f"card {ctx.unit_id} enables unregistered checks: {unknown}")

    specs = [CHECKS[c] for c in enabled]
    specs.sort(key=lambda s: (CATEGORY_ORDER.index(s.category) if s.category in CATEGORY_ORDER else 99, s.check_id))

    findings: list[Finding] = []
    ran: list[str] = []
    skipped: dict[str, str] = {}
    errored: dict[str, str] = {}

    for spec in specs:
        missing = [r for r in spec.requires if not ctx.has(r)]
        if missing:
            skipped[spec.check_id] = f"missing roles: {missing}"
            continue
        try:
            findings.extend(spec.fn(ctx))
            ran.append(spec.check_id)
        except Exception as exc:
            errored[spec.check_id] = f"{type(exc).__name__}: {exc}"

    return RunResult(sort_findings(findings), ran, skipped, errored)


def checks_by_origin() -> dict[str, list[str]]:
    """check_id -> where it came from, so a report can say which pack supplied what."""
    out: dict[str, list[str]] = {}
    for cid, spec in CHECKS.items():
        mod = getattr(spec.fn, "__module__", "?")
        origin = "engine" if mod.startswith("tssme.") else mod
        out.setdefault(origin, []).append(cid)
    return {k: sorted(v) for k, v in sorted(out.items())}


# Import the general checks for their registration side effects.
from . import data_quality, physical, relational, statistical, sme  # noqa: E402,F401

# Then let packs register theirs into the same registry. A pack check is gated on
# `requires`, conditioned on regime and routed by kind exactly like a general one; the only
# difference is that it is allowed to know physics.
#
# A pack that fails to load is recorded rather than raised. Raising here would make the
# engine unimportable, so `python -m tssme packs` could not be used to diagnose the very
# pack that broke it. The error is surfaced by the CLI and by every analysis run.
PACK_LOAD_ERRORS: dict[str, str] = {}

from .. import packs as _packs  # noqa: E402

try:
    _, _errs = _packs.load_pack_checks()
    PACK_LOAD_ERRORS.update(_errs)
except Exception as exc:  # noqa: BLE001 - recorded and surfaced, never swallowed
    PACK_LOAD_ERRORS["<discovery>"] = f"{type(exc).__name__}: {exc}"
