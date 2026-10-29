"""Historian tag -> canonical role resolution.

The single biggest practical failure in this workflow is guessing which tag is which.
A wrong guess produces a confident, sourced, completely false finding. So: resolution is
explicit (a tag map), ambiguity is an error, and unmapped columns are reported rather
than ignored.

The engine's assumption about the input is deliberately small: **a wide frame, a timestamp
index, and N columns of sensors and conditions.** Everything past that -- whether columns
carry an asset suffix, a prefix, a plant code, or nothing at all -- is a naming convention,
and a naming convention is a deployment fact. It is declared per tag map via `match`, not
assumed by the engine.

    match: exact    (default)  column == template
    match: suffix              column ends with template
    match: prefix              column starts with template
    match: regex               re.fullmatch(template, column)

`{asset}` in a template is substituted when an asset is supplied. A tag map with no
`{asset}` and no `asset_pattern` is the ordinary single-asset case and needs neither.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

import yaml

from ._paths import ENGINE_ROOT, example_dirs

TAGMAP_PATH_ENV = "TSSME_TAGMAP_PATH"
DEFAULT_DETECTOR_PATTERN = r"^Events?\s*-\s*"

# A join that fans out duplicates the column and suffixes a counter. This is a property of
# the tools (SQL joins, Spotfire data relations, pandas merge), not of any plant's naming.
_DUP = re.compile(r"\s*\(\d+\)")


class ResolutionError(ValueError):
    pass


@dataclass
class Resolution:
    asset: str | None = None                    # None when the export holds one unit
    role_to_column: dict[str, str] = field(default_factory=dict)
    missing_required: list[str] = field(default_factory=list)
    unmapped_columns: list[str] = field(default_factory=list)
    duplicate_candidates: dict[str, list[str]] = field(default_factory=dict)
    detector_columns: list[str] = field(default_factory=list)
    matched_loosely: dict[str, str] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.asset or "(single asset)"

    def column(self, role: str) -> str:
        if role not in self.role_to_column:
            raise ResolutionError(f"role {role!r} is not mapped for {self.label}")
        return self.role_to_column[role]

    def has(self, *roles: str) -> bool:
        return all(r in self.role_to_column for r in roles)


# ----------------------------------------------------------------------------- loading

def tagmap_search_dirs() -> list[str]:
    """Where a bare tagmap id is looked up. Tag maps are deployment facts, so the search
    is over locations a deployment owns, never over the engine package itself."""
    dirs = [d for d in os.environ.get(TAGMAP_PATH_ENV, "").split(os.pathsep) if d.strip()]
    dirs.append(os.path.join(ENGINE_ROOT, "tagmaps"))
    for examples in example_dirs():
        dirs.extend(
            os.path.join(examples, e) for e in sorted(os.listdir(examples))
            if os.path.isdir(os.path.join(examples, e))
        )
    return dirs


def load_tagmap(spec: str, tagmaps_dir: str | None = None) -> dict[str, Any]:
    """Load a tag map from a path, or by id from the search path."""
    if os.path.exists(spec) and os.path.isfile(spec):
        with open(spec, encoding="utf-8") as fh:
            return _validate_tagmap(yaml.safe_load(fh), spec)
    if spec.endswith((".yaml", ".yml")):
        raise ResolutionError(f"no tagmap file at {spec!r}")

    dirs = [tagmaps_dir] if tagmaps_dir else tagmap_search_dirs()
    tried = []
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        path = os.path.join(d, f"{spec}.yaml")
        tried.append(d)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                return _validate_tagmap(yaml.safe_load(fh), path)
    available = sorted({
        f[:-5] for d in tried for f in os.listdir(d) if f.endswith(".yaml")
    })
    raise ResolutionError(
        f"no tagmap {spec!r}. Searched {tried}, found {available}. "
        f"Pass a path, or set {TAGMAP_PATH_ENV}."
    )


_MATCHERS: dict[str, Callable[[str, str], bool]] = {
    "exact":  lambda col, want: col == want,
    "suffix": lambda col, want: col.endswith(want),
    "prefix": lambda col, want: col.startswith(want),
    "regex":  lambda col, want: re.fullmatch(want, col) is not None,
}


def _validate_tagmap(tm: dict, path: str) -> dict:
    if not isinstance(tm, dict) or "roles" not in tm:
        raise ResolutionError(f"{path}: tagmap needs a `roles` mapping")
    bad = sorted({
        m for m in [tm.get("match", "exact")]
        + [r.get("match") for r in tm["roles"].values() if isinstance(r, dict)]
        if m is not None and m not in _MATCHERS
    })
    if bad:
        raise ResolutionError(f"{path}: unknown match strategy {bad}, expected {sorted(_MATCHERS)}")
    return tm


def _role_spec(entry: Any) -> tuple[str, str | None]:
    """A role entry is either a template string or {template:, match:}."""
    if isinstance(entry, dict):
        if "template" not in entry:
            raise ResolutionError(f"role entry {entry!r} needs a `template`")
        return entry["template"], entry.get("match")
    return str(entry), None


# -------------------------------------------------------------------------- discovery

def discover_assets(columns: list[str], tagmap: dict) -> list[str]:
    """Asset ids present in the columns, if the tag map declares how to find them.

    A tag map without `asset_pattern` describes a single-asset export. That is the common
    case and it is not an error: the answer is "no asset dimension", not a crash.
    """
    pat = tagmap.get("asset_pattern")
    if not pat:
        return []
    compiled = re.compile(pat)
    if "asset" not in compiled.groupindex:
        raise ResolutionError(
            f"asset_pattern {pat!r} must contain a named group (?P<asset>...) so the engine "
            "knows which part of the column name is the asset id."
        )
    found = {m.group("asset") for c in columns if (m := compiled.search(c))}
    return sorted(found)


# --------------------------------------------------------------------------- resolution

def dedup_key(column: str) -> str:
    """Strip a join's duplicate counter, so `Foo (2)_BAR` and `Foo_BAR` collapse together."""
    return _DUP.sub("", column)


def resolve(
    columns: list[str],
    tagmap: dict,
    asset: str | None = None,
    required_roles: list[str] | None = None,
) -> Resolution:
    """Map columns to roles, optionally for one asset out of several.

    The declared `match` strategy runs first. If it finds nothing, a normalised comparison
    is tried as a last resort, and recorded as a loose match so the report can say the
    column name did not actually agree with the map. Ambiguity is never resolved silently.
    """
    required_roles = required_roles or []
    res = Resolution(asset=asset)
    colset = list(columns)
    claimed: set[str] = set()

    det_pat = re.compile(tagmap.get("detector_pattern", DEFAULT_DETECTOR_PATTERN))
    res.detector_columns = [c for c in colset if det_pat.search(c)]

    default_match = tagmap.get("match", "exact")

    for role, entry in tagmap["roles"].items():
        template, role_match = _role_spec(entry)
        strategy = role_match or default_match

        if "{asset}" in template:
            if asset is None:
                raise ResolutionError(
                    f"role {role!r} template {template!r} needs {{asset}} but no asset was "
                    "given. Pass --asset, or drop {asset} from the tag map if this export "
                    "holds one unit."
                )
            want = template.format(asset=asset)
        else:
            want = template

        pred = _MATCHERS[strategy]
        cands = [c for c in colset if pred(c, want)]

        if cands:
            keys = {dedup_key(c) for c in cands}
            if len(keys) > 1:
                raise ResolutionError(
                    f"role {role!r}{f' for {asset}' if asset else ''} matches multiple "
                    f"distinct columns via {strategy}: {sorted(cands)}. Tighten the tag map "
                    "rather than guessing."
                )
            # Prefer the un-suffixed name as primary; a `(2)` is the copy, not the original.
            primary = min(cands, key=lambda c: (_DUP.search(c) is not None, len(c), c))
        else:
            loose = [c for c in colset if _norm(c) == _norm(want)]
            if not loose:
                continue
            if len({dedup_key(c) for c in loose}) > 1:
                raise ResolutionError(
                    f"role {role!r}{f' for {asset}' if asset else ''} is ambiguous between "
                    f"{sorted(loose)}. Disambiguate in the tag map rather than guessing."
                )
            primary = min(loose, key=lambda c: (_DUP.search(c) is not None, len(c), c))
            res.matched_loosely[role] = want

        res.role_to_column[role] = primary
        claimed.add(primary)

        # Join duplicates of the chosen column, found without assuming any naming scheme.
        dups = [c for c in colset if c != primary and dedup_key(c) == dedup_key(primary)]
        if dups:
            res.duplicate_candidates[role] = [primary] + sorted(dups)
            claimed.update(dups)

    res.missing_required = [r for r in required_roles if r not in res.role_to_column]

    time_col = tagmap.get("time_column", "Timestamp")
    asset_pat = tagmap.get("asset_pattern")
    def _belongs(c: str) -> bool:
        # With no asset dimension every unclaimed column is in scope. With one, a column
        # carrying a different asset's id is not this unit's business.
        if not asset_pat or asset is None:
            return True
        return asset in c or not re.search(asset_pat, c)

    res.unmapped_columns = [
        c for c in colset
        if c not in claimed and c not in res.detector_columns and c != time_col and _belongs(c)
    ]
    return res


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())
