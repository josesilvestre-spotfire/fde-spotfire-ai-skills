"""Load and validate unit cards, and overlay asset calibration onto them.

A card that does not validate is not usable SME knowledge. Validation is strict on
structure and on the `source` rule: every numeric bound must be sourced or explicitly
marked UNVERIFIED, and UNVERIFIED items are surfaced, never silently accepted.

Cards live in packs, not in the engine. The structural schema is the engine's
(`schema/core.yaml`); the vocabulary a card draws on is contributed by whichever packs are
loaded. See `tssme.packs`.

Three layers meet here:

    class card   what a unit IS and how it FAILS      shared, changes rarely
    + overlay    what one asset MEASURES              site-specific, changes often
    = Card       what this analysis runs against

The overlay may only touch band-shaped fields. An overlay that could add an invariant or a
failure mode would be a fork of the knowledge base wearing a different name.
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from typing import Any

import yaml

from . import packs as _packs

# Kept as a module-level default so a caller can still point at a bare directory of cards
# (tests do this). None means "resolve through the pack registry".
UNITS_DIR: str | None = None


class CardError(ValueError):
    pass


@dataclass
class Card:
    raw: dict[str, Any]
    path: str
    pack_id: str | None = None
    calibration: dict[str, Any] = field(default_factory=dict)

    # --- convenience accessors -------------------------------------------------
    @property
    def unit_id(self) -> str:
        return self.raw["unit_id"]

    @property
    def unit_class(self) -> str:
        return self.raw["unit_class"]

    @property
    def persona(self) -> str:
        return self.raw["persona"]

    @property
    def roles(self) -> dict[str, dict]:
        return {r["id"]: r for r in self.raw.get("roles", [])}

    @property
    def derived(self) -> list[dict]:
        return self.raw.get("derived", [])

    @property
    def invariants(self) -> list[dict]:
        return self.raw.get("invariants", [])

    @property
    def failure_modes(self) -> list[dict]:
        return self.raw.get("failure_modes", [])

    @property
    def confounders(self) -> dict[str, dict]:
        return {c["id"]: c for c in self.raw.get("confounders", [])}

    @property
    def regimes(self) -> list[dict]:
        return self.raw.get("regimes", [])

    @property
    def enabled_checks(self) -> list[str]:
        return self.raw.get("checks", {}).get("enabled", [])

    @property
    def calibration_id(self) -> str | None:
        return self.calibration.get("calibration_id")

    def banded_specs(self) -> dict[str, dict]:
        """Roles and derived quantities that carry a `normal` band, for phys_range.

        Derived quantities are included because that is often where the well-formed band
        lives: a residual in psi is rate-biased and has no single meaningful band, while
        the same residual as a percentage of predicted drop does.
        """
        out = {r["id"]: r for r in self.raw.get("roles", []) if r.get("normal")}
        out.update({d["id"]: d for d in self.raw.get("derived", []) if d.get("normal")})
        return out

    def required_roles(self) -> list[str]:
        return [r["id"] for r in self.raw.get("roles", []) if r.get("required", True)]

    def unverified(self) -> list[str]:
        """Everything in this card resting on an unsourced number. Always reported."""
        out = []
        for section in ("roles", "derived", "invariants", "failure_modes"):
            for item in self.raw.get(section, []):
                src = str(item.get("source", ""))
                if "UNVERIFIED" in src.upper():
                    out.append(f"{section}.{item.get('id')}: {src}")
        notes = str(self.raw.get("notes", ""))
        if "UNVERIFIED" in notes.upper():
            out.append("notes: contains UNVERIFIED assumptions")
        return out

    def uncalibrated_bands(self) -> list[str]:
        """Banded specs whose band did not come from this asset.

        A class card carries specs and model targets. Anything descriptive is, by
        definition, a claim about some asset. If it was not calibrated here, say so rather
        than letting the reader assume the band was fitted to their unit.
        """
        overlaid = set(self.calibration.get("_applied", []))
        out = []
        for sid, spec in self.banded_specs().items():
            if spec.get("band_type", "descriptive") == "descriptive" and sid not in overlaid:
                out.append(sid)
        return sorted(out)


_ALLOWED_TOP = {
    "card_version", "unit_id", "unit_class", "service", "persona", "roles",
    "description", "topology", "derived", "invariants", "failure_modes",
    "confounders", "regimes", "checks", "notes",
}
_REQUIRED_TOP = {"card_version", "unit_id", "unit_class", "service", "persona", "roles"}

_OVERLAY_ALLOWED_TOP = {
    "calibration_version", "calibration_id", "unit", "pack", "asset",
    "source", "notes", "roles", "derived",
}


def load_schema() -> dict:
    """The core schema merged with every discovered pack's vocabulary."""
    return _packs.merged_schema()


def _check_band(problems: list[str], label: str, item: dict, enums: dict) -> None:
    """A `normal` band must be well formed, and must say which kind of band it is."""
    if "normal" in item:
        n = item["normal"]
        if not (isinstance(n, list) and len(n) == 2 and n[0] < n[1]):
            problems.append(f"{label}: normal must be [lo, hi] with lo < hi")
    bt = item.get("band_type")
    if bt is not None and bt not in enums["band_type"]:
        problems.append(f"{label}: band_type {bt!r} not in schema enum")
    if "normal" in item and bt is None:
        problems.append(
            f"{label}: has a `normal` band but no `band_type`. Declare whether it is "
            "`descriptive` (what this asset does, so a wide miss means the card is wrong) "
            "or `normative` (what it should do, so a wide miss is the finding)."
        )


def validate(raw: dict, schema: dict | None = None) -> list[str]:
    """Return a list of problems. Empty list means the card is valid."""
    schema = schema or load_schema()
    enums = schema["enums"]
    problems: list[str] = []

    missing = _REQUIRED_TOP - set(raw)
    if missing:
        problems.append(f"missing required keys: {sorted(missing)}")
    unknown = set(raw) - _ALLOWED_TOP
    if unknown:
        problems.append(f"unknown top-level keys: {sorted(unknown)}")

    # unit_class and persona come from packs. An unknown value usually means the pack that
    # owns the vocabulary is not on the search path, so say which values ARE available.
    for key in ("unit_class", "persona"):
        if raw.get(key) not in enums[key]:
            known = enums[key] or ["<none: no pack loaded>"]
            problems.append(f"{key} {raw.get(key)!r} not in schema enum. Known: {known}")

    role_ids = set()
    for r in raw.get("roles", []):
        rid = r.get("id", "<no id>")
        role_ids.add(rid)
        for req in ("id", "description", "kind", "quantity", "units", "source"):
            if req not in r:
                problems.append(f"role {rid}: missing {req}")
        if r.get("kind") not in enums["kind"]:
            problems.append(f"role {rid}: kind {r.get('kind')!r} not in schema enum")
        if r.get("quantity") not in enums["quantity"]:
            problems.append(f"role {rid}: quantity {r.get('quantity')!r} not in schema enum")
        if "control_role" in r and r["control_role"] not in enums["control_role"]:
            problems.append(f"role {rid}: control_role {r['control_role']!r} not in schema enum")
        _check_band(problems, f"role {rid}", r, enums)

    known = role_ids | {d.get("id") for d in raw.get("derived", [])}

    for d in raw.get("derived", []):
        for req in ("id", "expr", "units", "source"):
            if req not in d:
                problems.append(f"derived {d.get('id', '?')}: missing {req}")
        _check_band(problems, f"derived {d.get('id', '?')}", d, enums)

    for inv in raw.get("invariants", []):
        iid = inv.get("id", "?")
        for req in ("id", "kind", "expr", "source"):
            if req not in inv:
                problems.append(f"invariant {iid}: missing {req}")
        if inv.get("kind") not in enums["invariant_kind"]:
            problems.append(f"invariant {iid}: kind {inv.get('kind')!r} not in schema enum")
        if inv.get("severity", "medium") not in enums["severity"]:
            problems.append(f"invariant {iid}: bad severity")
        # requires_roles is deliberately NOT validated against `known`. Naming a role the
        # card does not define is the normal way to say "this invariant needs a measurement
        # we do not have", which is exactly what the field is for.
        if not isinstance(inv.get("requires_roles", []), list):
            problems.append(f"invariant {iid}: requires_roles must be a list")

    conf_ids = {c.get("id") for c in raw.get("confounders", [])}
    for c in raw.get("confounders", []):
        for req in ("id", "description", "roles", "test", "source"):
            if req not in c:
                problems.append(f"confounder {c.get('id', '?')}: missing {req}")
        for rid in c.get("roles", []):
            if rid not in known:
                problems.append(f"confounder {c.get('id')}: unknown role {rid!r}")

    fm_ids = {fm.get("id") for fm in raw.get("failure_modes", [])}
    for fm in raw.get("failure_modes", []):
        fid = fm.get("id", "?")
        for req in ("id", "name", "severity", "onset", "signature", "confounders", "source"):
            if req not in fm:
                problems.append(f"failure_mode {fid}: missing {req}")
        if fm.get("severity") not in enums["severity"]:
            problems.append(f"failure_mode {fid}: bad severity")
        if fm.get("onset") not in enums["onset"]:
            problems.append(f"failure_mode {fid}: bad onset {fm.get('onset')!r}")
        sig = fm.get("signature", {})
        # Hard rule: a one-role signature is a threshold alarm, not a signature.
        if len(sig) < 2:
            problems.append(f"failure_mode {fid}: signature needs >= 2 roles, got {len(sig)}")
        for rid, direction in sig.items():
            if rid not in known:
                problems.append(f"failure_mode {fid}: signature references unknown role {rid!r}")
            if direction not in enums["direction"]:
                problems.append(f"failure_mode {fid}: bad direction {direction!r} for {rid}")
        # Hard rule: no confounders means nobody thought about it.
        if not fm.get("confounders"):
            problems.append(f"failure_mode {fid}: must list confounders")
        for cid in fm.get("confounders", []):
            if cid not in conf_ids:
                hint = (" (this is a failure_mode id -- a competing fault belongs in "
                        "`differentials`, not `confounders`)" if cid in fm_ids else "")
                problems.append(f"failure_mode {fid}: unknown confounder {cid!r}{hint}")
        for did in fm.get("differentials", []):
            if did not in fm_ids:
                problems.append(f"failure_mode {fid}: unknown differential {did!r}")
            if did == fid:
                problems.append(f"failure_mode {fid}: lists itself as a differential")

    for reg in raw.get("regimes", []):
        if reg.get("by") not in known:
            problems.append(f"regime {reg.get('id')}: unknown role {reg.get('by')!r}")

    return problems


# ------------------------------------------------------------------- calibration overlay

def apply_calibration(raw: dict, overlay: dict, schema: dict | None = None) -> list[str]:
    """Merge an asset calibration overlay into a card dict, in place.

    Returns the list of spec ids that were overlaid, for provenance. Raises CardError on
    anything the overlay is not allowed to do: the restriction is the whole point, because
    an overlay that can redefine physics is a fork, and a fork means the class card stops
    being the single place the knowledge lives.
    """
    schema = schema or load_schema()
    allowed = set(schema["calibration"]["overlayable_fields"])
    refused = set(schema["calibration"]["refused_sections"])

    unknown = set(overlay) - _OVERLAY_ALLOWED_TOP
    if unknown:
        hit = sorted(unknown & refused)
        extra = (
            f" Sections {hit} are class knowledge: if this asset truly needs different "
            "physics or failure modes, it is a different unit class, not an overlay."
            if hit else ""
        )
        raise CardError(f"calibration: unknown top-level keys {sorted(unknown)}.{extra}")

    if overlay.get("unit") and overlay["unit"] != raw.get("unit_id"):
        raise CardError(
            f"calibration targets unit {overlay['unit']!r} but card is {raw.get('unit_id')!r}"
        )

    index: dict[str, dict[str, dict]] = {
        "roles": {r["id"]: r for r in raw.get("roles", [])},
        "derived": {d["id"]: d for d in raw.get("derived", [])},
    }

    applied: list[str] = []
    for section in ("roles", "derived"):
        for spec_id, patch in (overlay.get(section) or {}).items():
            target = index[section].get(spec_id)
            if target is None:
                raise CardError(
                    f"calibration: {section}.{spec_id!r} is not defined on card "
                    f"{raw.get('unit_id')!r}. An overlay adjusts existing specs; it cannot "
                    "add them."
                )
            bad = sorted(set(patch) - allowed)
            if bad:
                raise CardError(
                    f"calibration: {section}.{spec_id}: cannot set {bad}. "
                    f"Overlayable fields are {sorted(allowed)}."
                )
            target.update(copy.deepcopy(patch))
            applied.append(spec_id)

    # A band arriving without provenance is exactly the failure this layer exists to
    # prevent: a number from one asset, over one period, read later as class knowledge.
    if applied and not (overlay.get("source") or overlay.get("notes")):
        raise CardError(
            "calibration: overlays must carry a `source` recording which asset these "
            "numbers were measured from and over what period."
        )
    return applied


def load_calibration(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


# ------------------------------------------------------------------------------ loading

def load_card(
    unit_id: str,
    units_dir: str | None = None,
    pack: str | None = None,
    calibration: str | dict | None = None,
) -> Card:
    """Load a unit card by id, optionally from one pack, optionally calibrated.

    `units_dir` bypasses pack resolution and reads a bare directory of cards. That is for
    tests and for one-off authoring; normal use goes through the pack registry.
    """
    pack_id = pack
    d = units_dir if units_dir is not None else UNITS_DIR
    if d is not None:
        path = os.path.join(d, f"{unit_id}.yaml")
        if not os.path.exists(path):
            available = sorted(
                f[:-5] for f in os.listdir(d) if f.endswith(".yaml") and not f.startswith("_")
            )
            raise CardError(f"no card {unit_id!r} in {d}. Available: {available}")
    else:
        found, path = _packs.find_unit(unit_id, pack_id)
        pack_id = found.pack_id

    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if raw.get("unit_id") != unit_id:
        raise CardError(f"card unit_id {raw.get('unit_id')!r} does not match filename {unit_id!r}")

    schema = load_schema()
    cal: dict = {}
    if calibration is not None:
        cal = load_calibration(calibration) if isinstance(calibration, str) else dict(calibration)
        cal["_applied"] = apply_calibration(raw, cal, schema)

    # Validated AFTER the overlay, because the overlay can introduce a malformed band and
    # a card that is only valid before calibration is not valid.
    problems = validate(raw, schema)
    if problems:
        where = f"card {unit_id}" + (" (after calibration)" if cal else "")
        raise CardError(f"{where} failed validation:\n  - " + "\n  - ".join(problems))

    return Card(raw=raw, path=path, pack_id=pack_id, calibration=cal)


def list_cards(units_dir: str | None = None) -> list[str]:
    """Unit ids available, from a bare directory if given, else from all packs."""
    d = units_dir if units_dir is not None else UNITS_DIR
    if d is not None:
        return sorted(
            f[:-5] for f in os.listdir(d) if f.endswith(".yaml") and not f.startswith("_")
        )
    return sorted({uid for _, uid in _packs.list_units()})
