"""Render findings. Severity first, evidence attached, confounder status always visible."""

from __future__ import annotations

from .cards import Card
from .checks import RunResult
from .findings import Finding
from .prep import Context

_ICON = {"critical": "[CRITICAL]", "high": "[HIGH]", "medium": "[MEDIUM]",
         "low": "[LOW]", "info": "[OK]"}


def _fmt_stat(v) -> str:
    if isinstance(v, float):
        return f"{v:,.4g}"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k}: {_fmt_stat(x)}" for k, x in list(v.items())[:6]) + "}"
    if isinstance(v, list):
        return "[" + ", ".join(_fmt_stat(x) for x in v[:6]) + ("...]" if len(v) > 6 else "]")
    return str(v)


def _label(f: Finding) -> str:
    # A candidate must never render as [OK] just because its severity was downgraded for
    # unresolved confounders.
    if f.kind == "candidate":
        return f"[CANDIDATE/{f.severity.upper()}]"
    if f.kind == "not_evaluated":
        return "[NOT EVALUATED]"
    return _ICON[f.severity]


def finding_md(f: Finding, verbose: bool = False) -> str:
    lines = [f"### {_label(f)} {f.summary}"]
    meta = [f"check `{f.check_id}`", f"confidence **{f.confidence}**"]
    if f.roles:
        meta.append("roles " + ", ".join(f"`{r}`" for r in f.roles))
    if f.window:
        meta.append(f"window {f.window[0]} to {f.window[1]}")
    lines.append("  \n".join([" | ".join(meta)]))
    if f.interpretation:
        lines.append(f"\n{f.interpretation}")
    if f.statistic:
        keep = f.statistic if verbose else {
            k: v for k, v in f.statistic.items() if k not in ("confounder_evidence", "observed", "per_band")
        }
        if keep:
            lines.append("\n" + "\n".join(f"- {k}: {_fmt_stat(v)}" for k, v in keep.items()))
    if f.confounders_tested:
        lines.append("\nConfounders:")
        for cid, status in f.confounders_tested.items():
            mark = {"ruled_out": "ruled out", "not_ruled_out": "NOT RULED OUT",
                    "untested": "untested"}[status]
            lines.append(f"- {cid}: {mark}")
    if f.next_step:
        lines.append(f"\nNext step: {f.next_step}")
    if f.source:
        lines.append(f"\nSource: {f.source}")
    return "\n".join(lines)


def report_md(ctx: Context, result: RunResult, verbose: bool = False) -> str:
    card: Card = ctx.card
    # Route on kind, not severity. A candidate diagnosis downgraded to info because its
    # confounders are unresolved is still a candidate, and an invariant that could not be
    # evaluated is a coverage gap. Filing either under "healthy" is how a report reassures
    # a reader about something it never checked.
    real = [f for f in result.findings if f.kind == "defect"]
    candidates = [f for f in result.findings if f.kind == "candidate"]
    verified = [f for f in result.findings if f.kind == "verified"]
    ungraded = [f for f in result.findings if f.kind == "not_evaluated"]

    counts: dict[str, int] = {}
    for f in real:
        counts[f.severity] = counts.get(f.severity, 0) + 1

    lines = [
        f"# Time series analysis: {card.unit_id} / {ctx.resolution.label}",
        "",
        f"- Unit class: {card.unit_class} | persona: {card.persona}"
        + (f" | pack: {card.pack_id}" if card.pack_id else "")
        + (f" | calibration: {card.calibration_id}" if card.calibration_id else ""),
        f"- Samples: {len(ctx.X)} | period: {ctx.X.index.min()} to {ctx.X.index.max()}"
        + (f" | {ctx.meta['invalid_rows']['count']} row(s) blanked as partial"
           if ctx.meta.get("invalid_rows") else ""),
        f"- Roles resolved: {len(ctx.resolution.role_to_column)} of {len(card.roles)}"
        + (f" | MISSING REQUIRED: {ctx.resolution.missing_required}" if ctx.resolution.missing_required else ""),
        f"- Operating regimes: {ctx.meta.get('regime_count', 'n/a')}",
        f"- Checks run: {len(result.ran)}"
        + (f" | skipped: {len(result.skipped)}" if result.skipped else "")
        + (f" | ERRORED: {len(result.errored)}" if result.errored else ""),
        f"- Findings: " + (", ".join(f"{n} {sev}" for sev, n in counts.items()) if counts else "none")
        + (f" | {len(candidates)} candidate diagnosis(es)" if candidates else "")
        + (f" | {len(ungraded)} not evaluated" if ungraded else ""),
        "",
    ]

    unver = card.unverified()
    if unver:
        lines += ["## Unverified card assumptions", "",
                  "These findings rest on numbers that are not sourced. Confirm before acting.", ""]
        lines += [f"- {u}" for u in unver] + [""]

    uncal = card.uncalibrated_bands()
    if uncal:
        lines += [
            "## Uncalibrated bands", "",
            "These carry a descriptive band that was not calibrated from this asset, so an "
            "excursion may be describing a different unit rather than this one. Calibrate "
            "them in the profile overlay before acting on a band finding.", "",
        ]
        lines += [f"- {u}" for u in uncal] + [""]

    warn: list[str] = []
    for role, cands in ctx.resolution.duplicate_candidates.items():
        warn.append(f"- `{role}` matched multiple columns: {cands}; used `{cands[0]}`")
    for role, want in ctx.resolution.matched_loosely.items():
        warn.append(
            f"- `{role}` did not match `{want}` exactly; it was matched after normalising "
            f"punctuation and case to `{ctx.resolution.role_to_column[role]}`. Confirm it is "
            "the right tag and fix the tag map."
        )
    if warn:
        lines += ["## Tag resolution warnings", ""] + warn + [""]

    if real:
        lines += ["## Findings", ""]
        lines += [finding_md(f, verbose) + "\n" for f in real]
    else:
        lines += ["## Findings", "", "No defects found.", ""]

    if candidates:
        lines += ["## Candidate diagnoses", "",
                  "Signature matches against the unit card. These are hypotheses, not "
                  "conclusions: read the confounder status on each before acting.", ""]
        lines += [finding_md(f, verbose) + "\n" for f in candidates]

    if ungraded:
        lines += ["## Not evaluated", "",
                  "These checks could not run against this dataset. They are coverage gaps, "
                  "not clean bills of health.", ""]
        lines += [f"- {f.summary}" for f in ungraded] + [""]

    if verified:
        lines += ["## Verified as healthy", ""]
        lines += [f"- {f.summary}" for f in verified] + [""]

    if result.skipped:
        lines += ["## Checks skipped", ""]
        lines += [f"- `{k}`: {v}" for k, v in result.skipped.items()] + [""]
    if result.errored:
        lines += ["## Checks errored", ""]
        lines += [f"- `{k}`: {v}" for k, v in result.errored.items()] + [""]
    if ctx.meta.get("derived_skipped"):
        lines += ["## Derived roles not computed", ""]
        lines += [f"- `{k}`: {v}" for k, v in ctx.meta["derived_skipped"].items()] + [""]

    return "\n".join(lines)
