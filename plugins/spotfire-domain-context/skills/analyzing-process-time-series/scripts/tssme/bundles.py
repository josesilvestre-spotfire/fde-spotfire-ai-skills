"""Bundles: a named, deployable persona assembled from engine + packs + profiles.

A bundle is the thing you actually ship and the thing a user actually names. "Pump
Reliability Agent" is not an engine, a pack or a profile; it is a selection across all
three plus a brief that says what it does and, just as importantly, what it refuses.

    bundle_id:  pump-reliability-agent
    name:       Pump Reliability Agent
    version:    1.0.0
    persona:    rotating_equipment_engineer

    engine:   {id: tssme, version: ">=1.1,<2.0"}
    packs:
      - {id: <pack-id>, version: ">=1.0", units: [<unit-id>, ...]}   # units optional
    profiles: [<profile-id>, ...]                                    # optional

    brief:
      scope:      one sentence on what this persona analyses
      leads_with: the question it answers first
      refuses:    [things it will not do, stated so the agent declines instead of guessing]

    outputs:
      agent:    <path>          # an agent definition generated from the bundle (not built)
      spotfire: <dir>           # vendored deployment (packager deliberately not built yet)

Everything below a bundle is referenced **by id, never by path**, because a bundle has to
resolve in two different worlds:

  development  ids resolve against the local search paths; packs and profiles are shared
               and edited in place
  deployment   ids resolve inside a self-contained vendored directory with pinned
               versions, because a Spotfire CPython data function cannot reach into a
               developer's home directory

Paths in a manifest would only ever be right in one of those. This module implements the
development side: parse, resolve, and report what is missing. The packager that produces
the vendored directory is deliberately not built until the deployment target is decided,
because its layout is determined by that target and guessing it would be wasted work.

Omitting `units:` means "every unit in this pack owned by the bundle's persona", which is
usually what distinguishes one persona from another and saves restating it.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from . import packs as _packs
from . import profiles as _profiles

from ._paths import ENGINE_ROOT, example_dirs

BUNDLE_PATH_ENV = "TSSME_BUNDLE_PATH"

_ALLOWED = {
    "bundle_id", "name", "version", "description", "persona", "engine",
    "packs", "profiles", "brief", "outputs", "notes",
}
_REQUIRED = {"bundle_id", "name", "version", "persona", "packs"}
_BRIEF_KEYS = {"scope", "leads_with", "refuses", "audience"}


class BundleError(ValueError):
    pass


# ------------------------------------------------------------------ version constraints

_OPS = ["<=", ">=", "==", "!=", "<", ">"]
_VER = re.compile(r"^\d+(\.\d+)*$")


def _parse_version(v: str) -> tuple[int, ...]:
    v = str(v).strip()
    if not _VER.match(v):
        raise BundleError(f"version {v!r} must be dotted integers, e.g. 1.2.0")
    return tuple(int(p) for p in v.split("."))


def _pad(a: tuple[int, ...], b: tuple[int, ...]) -> tuple[tuple, tuple]:
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)), b + (0,) * (n - len(b))


def satisfies(version: str, constraint: str | None) -> bool:
    """Check a dotted version against a comma-separated constraint like '>=1.0,<2.0'."""
    if not constraint:
        return True
    have = _parse_version(version)
    for clause in str(constraint).split(","):
        clause = clause.strip()
        if not clause:
            continue
        op = next((o for o in _OPS if clause.startswith(o)), None)
        if op is None:
            op, rhs = "==", clause
        else:
            rhs = clause[len(op):]
        a, b = _pad(have, _parse_version(rhs))
        ok = {
            "<=": a <= b, ">=": a >= b, "==": a == b,
            "!=": a != b, "<": a < b, ">": a > b,
        }[op]
        if not ok:
            return False
    return True


# ------------------------------------------------------------------------------ manifest

@dataclass
class Bundle:
    bundle_id: str
    path: str
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.raw["name"]

    @property
    def version(self) -> str:
        return str(self.raw["version"])

    @property
    def persona(self) -> str:
        return self.raw["persona"]

    @property
    def engine_constraint(self) -> str | None:
        eng = self.raw.get("engine") or {}
        return eng.get("version") if isinstance(eng, dict) else str(eng)

    @property
    def pack_refs(self) -> list[dict]:
        out = []
        for entry in self.raw.get("packs", []):
            out.append({"id": entry, "version": None, "units": None}
                       if isinstance(entry, str) else
                       {"id": entry.get("id"), "version": entry.get("version"),
                        "units": entry.get("units")})
        return out

    @property
    def profile_ids(self) -> list[str]:
        return list(self.raw.get("profiles") or [])

    @property
    def brief(self) -> dict:
        return dict(self.raw.get("brief") or {})


def _validate(raw: dict, path: str) -> dict:
    missing = _REQUIRED - set(raw)
    if missing:
        raise BundleError(f"{path}: missing {sorted(missing)}")
    unknown = set(raw) - _ALLOWED
    if unknown:
        raise BundleError(f"{path}: unknown keys {sorted(unknown)}")
    _parse_version(raw["version"])
    bad_brief = set(raw.get("brief") or {}) - _BRIEF_KEYS
    if bad_brief:
        raise BundleError(f"{path}: unknown brief keys {sorted(bad_brief)}")
    for entry in raw.get("packs", []):
        if isinstance(entry, dict) and not entry.get("id"):
            raise BundleError(f"{path}: pack entry {entry!r} needs an id")
    # A bundle that will not say what it refuses is a bundle that will answer anything.
    if not (raw.get("brief") or {}).get("refuses"):
        raise BundleError(
            f"{path}: brief.refuses is required. A persona that does not declare its limits "
            "will improvise past them, which is how a pump agent ends up opining on leak "
            "detection."
        )
    return raw


def load_bundle(spec: str) -> Bundle:
    """Load a bundle by id or by path."""
    path = spec
    if not (os.path.isfile(spec) and spec.endswith((".yaml", ".yml"))):
        found = discover_bundles()
        if spec not in found:
            raise BundleError(
                f"no bundle {spec!r}. Found: {sorted(found)}. Searched: {search_roots()}"
            )
        return found[spec]
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    _validate(raw, path)
    return Bundle(bundle_id=raw["bundle_id"], path=os.path.abspath(path), raw=raw)


def search_roots() -> list[str]:
    roots = [p for p in os.environ.get(BUNDLE_PATH_ENV, "").split(os.pathsep) if p.strip()]
    roots.append(os.path.join(ENGINE_ROOT, "bundles"))
    roots.extend(os.path.join(d, "bundles") for d in example_dirs())
    return roots


def discover_bundles(roots: list[str] | None = None) -> dict[str, Bundle]:
    found: dict[str, Bundle] = {}
    for root in (roots if roots is not None else search_roots()):
        root = os.path.abspath(os.path.expanduser(root))
        if not os.path.isdir(root):
            continue
        for entry in sorted(os.listdir(root)):
            if not entry.endswith((".yaml", ".yml")):
                continue
            path = os.path.join(root, entry)
            with open(path, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            if "bundle_id" not in raw:
                continue
            _validate(raw, path)
            found.setdefault(
                raw["bundle_id"],
                Bundle(bundle_id=raw["bundle_id"], path=os.path.abspath(path), raw=raw),
            )
    return found


# ----------------------------------------------------------------------------- resolution

def resolve_bundle(bundle: Bundle) -> dict:
    """Resolve a bundle against what is actually installed, in development mode.

    Returns a plain dict describing what the bundle would run with and, deliberately in the
    same structure, everything that is missing. A resolution that quietly drops an
    unsatisfiable pack would produce an agent with silent coverage gaps, which is the exact
    failure this whole design is built to avoid.
    """
    from . import __version__ as engine_version

    reg = _packs.registry()
    profs = _profiles.discover_profiles()

    out: dict[str, Any] = {
        "bundle_id": bundle.bundle_id,
        "name": bundle.name,
        "version": bundle.version,
        "persona": bundle.persona,
        "engine": {
            "id": "tssme",
            "installed": engine_version,
            "constraint": bundle.engine_constraint,
            "satisfied": satisfies(engine_version, bundle.engine_constraint),
        },
        "packs": [],
        "units": [],
        "profiles": [],
        "brief": bundle.brief,
        "problems": [],
    }

    if not out["engine"]["satisfied"]:
        out["problems"].append(
            f"engine {engine_version} does not satisfy {bundle.engine_constraint!r}"
        )

    for ref in bundle.pack_refs:
        pid = ref["id"]
        pack = reg.get(pid)
        if pack is None:
            out["problems"].append(f"pack {pid!r} not found; discovered {sorted(reg)}")
            out["packs"].append({"id": pid, "found": False, "constraint": ref["version"]})
            continue

        ok = satisfies(pack.version, ref["version"])
        if not ok:
            out["problems"].append(
                f"pack {pid} v{pack.version} does not satisfy {ref['version']!r}"
            )

        if ref["units"] is None:
            # The persona default: everything in this pack that this persona owns.
            units, skipped = [], []
            for uid in pack.unit_ids():
                with open(pack.card_path(uid), encoding="utf-8") as fh:
                    raw = yaml.safe_load(fh) or {}
                (units if raw.get("persona") == bundle.persona else skipped).append(uid)
            selection = "persona-default"
        else:
            units, skipped = [], []
            available = set(pack.unit_ids())
            for uid in ref["units"]:
                if uid in available:
                    units.append(uid)
                else:
                    out["problems"].append(
                        f"pack {pid} has no unit {uid!r}; available {sorted(available)}"
                    )
            selection = "explicit"

        out["packs"].append({
            "id": pid, "found": True, "version": pack.version,
            "constraint": ref["version"], "satisfied": ok, "root": pack.root,
            "selection": selection, "units": units,
            "units_not_owned_by_persona": skipped,
        })
        out["units"].extend(units)

    if not out["units"]:
        out["problems"].append(
            f"no units selected. No card in the listed packs declares persona "
            f"{bundle.persona!r}, so this bundle would ship a persona with nothing to analyse."
        )

    for pid in bundle.profile_ids:
        prof = profs.get(pid)
        if prof is None:
            out["problems"].append(f"profile {pid!r} not found; discovered {sorted(profs)}")
            out["profiles"].append({"id": pid, "found": False})
            continue
        in_scope = prof.unit in out["units"]
        if not in_scope:
            out["problems"].append(
                f"profile {pid} targets unit {prof.unit!r}, which this bundle does not include"
            )
        out["profiles"].append({
            "id": pid, "found": True, "unit": prof.unit, "asset": prof.asset,
            "root": prof.root, "in_scope": in_scope,
        })

    out["resolved"] = not out["problems"]
    return out
