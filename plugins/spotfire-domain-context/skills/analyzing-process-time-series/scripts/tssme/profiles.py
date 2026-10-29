"""Profiles: the deployment layer.

    engine   general time series method      one, shared,       changes rarely
    pack     domain knowledge                many, shared,      changes slowly
    profile  deployment facts                many, site-owned,  changes constantly
    bundle   a named, shippable persona      see tssme.bundles

A profile is everything that is true of one asset at one site and of nothing else: which
unit card applies, what its historian columns are called, what its bands actually measure,
and where the data lives. None of that belongs in a skill, in a pack, or in the engine,
because all three are shared and a site fact shared is a site fact wrong somewhere else.

    profile.yaml
      profile_id:   <id>
      unit:         <unit card id>
      pack:         <pack id>                 # optional, disambiguates a shared unit id
      tagmap:       tagmap.yaml               # relative to the profile directory
      calibration:  calibration.yaml          # optional band overlay
      asset:        <asset id>                # optional, only for multi-asset exports
      data:         <path or glob>            # optional default input
      checks:
        enabled: [...]                        # optional override of the card's list

Profiles are found by scanning `TSSME_PROFILE_PATH` and `<engine_root>/profiles`, and the
shipped examples under `<skill>/assets/examples`. Nothing here knows any real site.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import yaml

from ._paths import ENGINE_ROOT, example_dirs

PROFILE_MANIFEST = "profile.yaml"
PROFILE_PATH_ENV = "TSSME_PROFILE_PATH"

_ALLOWED = {
    "profile_id", "name", "description", "unit", "pack", "tagmap",
    "calibration", "asset", "data", "checks", "notes",
}
_REQUIRED = {"profile_id", "unit", "tagmap"}


class ProfileError(ValueError):
    pass


@dataclass
class Profile:
    profile_id: str
    root: str
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def unit(self) -> str:
        return self.raw["unit"]

    @property
    def pack(self) -> str | None:
        return self.raw.get("pack")

    @property
    def asset(self) -> str | None:
        return self.raw.get("asset")

    @property
    def enabled_checks(self) -> list[str] | None:
        """None means "use the card's list". An empty list means "run nothing", which is a
        different statement and is honoured as written."""
        checks = self.raw.get("checks")
        if not isinstance(checks, dict) or "enabled" not in checks:
            return None
        return list(checks["enabled"])

    def _path(self, key: str) -> str | None:
        val = self.raw.get(key)
        if not val:
            return None
        return val if os.path.isabs(val) else os.path.normpath(os.path.join(self.root, val))

    @property
    def tagmap_path(self) -> str:
        p = self._path("tagmap")
        if p is None:
            raise ProfileError(f"profile {self.profile_id}: no tagmap")
        if not os.path.exists(p):
            raise ProfileError(f"profile {self.profile_id}: tagmap {p} does not exist")
        return p

    @property
    def calibration_path(self) -> str | None:
        p = self._path("calibration")
        if p is not None and not os.path.exists(p):
            raise ProfileError(f"profile {self.profile_id}: calibration {p} does not exist")
        return p

    @property
    def data_path(self) -> str | None:
        return self._path("data")


def _read(root: str) -> Profile | None:
    path = os.path.join(root, PROFILE_MANIFEST)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    missing = _REQUIRED - set(raw)
    if missing:
        raise ProfileError(f"{path}: missing {sorted(missing)}")
    unknown = set(raw) - _ALLOWED
    if unknown:
        raise ProfileError(f"{path}: unknown keys {sorted(unknown)}")
    return Profile(profile_id=raw["profile_id"], root=os.path.abspath(root), raw=raw)


def search_roots() -> list[str]:
    roots = [p for p in os.environ.get(PROFILE_PATH_ENV, "").split(os.pathsep) if p.strip()]
    roots.append(os.path.join(ENGINE_ROOT, "profiles"))
    roots.extend(example_dirs())
    return roots


def discover_profiles(roots: list[str] | None = None) -> dict[str, Profile]:
    found: dict[str, Profile] = {}
    for root in (roots if roots is not None else search_roots()):
        root = os.path.abspath(os.path.expanduser(root))
        if not os.path.isdir(root):
            continue
        candidates = [root] + [
            os.path.join(root, e) for e in sorted(os.listdir(root))
            if os.path.isdir(os.path.join(root, e))
        ]
        for cand in candidates:
            prof = _read(cand)
            if prof is not None and prof.profile_id not in found:
                found[prof.profile_id] = prof
    return found


def load_profile(spec: str) -> Profile:
    """Load a profile by id, by directory, or by path to its profile.yaml."""
    if os.path.isdir(spec):
        prof = _read(spec)
        if prof is None:
            raise ProfileError(f"{spec} contains no {PROFILE_MANIFEST}")
        return prof
    if os.path.isfile(spec):
        prof = _read(os.path.dirname(os.path.abspath(spec)))
        if prof is None:
            raise ProfileError(f"{spec} is not a {PROFILE_MANIFEST}")
        return prof

    profiles = discover_profiles()
    if spec not in profiles:
        raise ProfileError(
            f"no profile {spec!r}. Found: {sorted(profiles)}. "
            f"Pass a directory, or set {PROFILE_PATH_ENV}."
        )
    return profiles[spec]
