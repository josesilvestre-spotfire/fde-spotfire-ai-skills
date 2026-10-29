"""Pack discovery: how domain knowledge gets appended to a domain-free engine.

The engine knows about time series. It knows nothing about pumps, columns, or contactors,
and it must never need to. A **pack** is a directory containing `pack.yaml` that supplies
three things the engine deliberately lacks:

  1. vocabulary  -- `unit_class`, `persona` and domain `quantity` values, merged into the
                    core schema's extensible enums,
  2. unit cards  -- the knowledge itself, as validated YAML,
  3. checks      -- domain-specific check functions, registered into the same registry as
                    the general ones.

Nothing here hardcodes a pack. Packs are found by looking for `pack.yaml`, so adding a
domain means adding a directory, never editing the engine.

Search order (first match for a given pack_id wins):

  1. `TSSME_PACK_PATH`          -- os.pathsep separated; each entry is a pack or a dir of packs
  2. `<engine_root>/packs/*`    -- vendored packs in a deployed copy of the engine
  3. sibling skills' `assets/*` -- packs shipped by other skills installed next to this one
  4. `<skill>/assets/examples/*` -- the synthetic example pack shipped for tests and docs

Vendored packs outrank siblings so that a deployed copy is self-contained and cannot be
silently altered by whatever happens to be installed next to it.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from dataclasses import dataclass, field
from typing import Any

import yaml

from ._paths import ENGINE_ROOT, example_dirs, sibling_asset_dirs

_HERE = os.path.dirname(os.path.abspath(__file__))
CORE_SCHEMA_PATH = os.path.join(_HERE, "schema", "core.yaml")

PACK_MANIFEST = "pack.yaml"
PACK_PATH_ENV = "TSSME_PACK_PATH"

# Only these enums may be extended by a pack. The others (`severity`, `direction`,
# `band_type`, ...) are branched on by engine code, so a pack adding a value would
# introduce a case no check knows how to handle.
_EXTENSIBLE = ("unit_class", "persona", "quantity")


class PackError(ValueError):
    pass


@dataclass
class Pack:
    pack_id: str
    root: str
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.raw.get("name", self.pack_id)

    @property
    def version(self) -> str:
        return str(self.raw.get("version", "0.0.0"))

    @property
    def units_dir(self) -> str:
        return os.path.join(self.root, self.raw.get("units_dir", "units"))

    @property
    def check_modules(self) -> list[str]:
        return [os.path.join(self.root, m) for m in self.raw.get("check_modules", [])]

    def unit_ids(self) -> list[str]:
        d = self.units_dir
        if not os.path.isdir(d):
            return []
        return sorted(
            f[:-5] for f in os.listdir(d)
            if f.endswith(".yaml") and not f.startswith("_")
        )

    def card_path(self, unit_id: str) -> str | None:
        p = os.path.join(self.units_dir, f"{unit_id}.yaml")
        return p if os.path.exists(p) else None

    def schema_extensions(self) -> dict:
        rel = self.raw.get("schema_extensions")
        if not rel:
            return {}
        path = os.path.join(self.root, rel)
        if not os.path.exists(path):
            raise PackError(f"pack {self.pack_id}: schema_extensions {path} does not exist")
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}


# --------------------------------------------------------------------------- discovery

def _read_manifest(root: str) -> Pack | None:
    path = os.path.join(root, PACK_MANIFEST)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    pid = raw.get("pack_id")
    if not pid:
        raise PackError(f"{path}: missing pack_id")
    return Pack(pack_id=pid, root=os.path.abspath(root), raw=raw)


def search_roots() -> list[str]:
    """Directories to scan, in precedence order. Each may be a pack or hold packs."""
    roots: list[str] = []
    env = os.environ.get(PACK_PATH_ENV, "")
    roots.extend(p for p in env.split(os.pathsep) if p.strip())
    roots.append(os.path.join(ENGINE_ROOT, "packs"))
    roots.extend(sibling_asset_dirs())
    roots.extend(example_dirs())
    return roots


def discover_packs(roots: list[str] | None = None) -> dict[str, Pack]:
    """Map pack_id -> Pack. Earlier roots win, so a vendored pack beats a sibling."""
    found: dict[str, Pack] = {}
    for root in (roots if roots is not None else search_roots()):
        root = os.path.abspath(os.path.expanduser(root))
        if not os.path.isdir(root):
            continue
        candidates = [root] + [
            os.path.join(root, e) for e in sorted(os.listdir(root))
            if os.path.isdir(os.path.join(root, e))
        ]
        for cand in candidates:
            try:
                pack = _read_manifest(cand)
            except OSError:
                continue
            if pack is not None and pack.pack_id not in found:
                found[pack.pack_id] = pack
    return found


_CACHE: dict[str, Pack] | None = None


def registry(refresh: bool = False) -> dict[str, Pack]:
    global _CACHE
    if _CACHE is None or refresh:
        _CACHE = discover_packs()
    return _CACHE


def get_pack(pack_id: str) -> Pack:
    packs = registry()
    if pack_id not in packs:
        raise PackError(
            f"no pack {pack_id!r}. Found: {sorted(packs)}. "
            f"Searched: {[r for r in search_roots()]}"
        )
    return packs[pack_id]


def find_unit(unit_id: str, pack_id: str | None = None) -> tuple[Pack, str]:
    """Locate a unit card by id across all packs, or within one named pack."""
    packs = registry()
    if pack_id is not None:
        pack = get_pack(pack_id)
        path = pack.card_path(unit_id)
        if path is None:
            raise PackError(
                f"pack {pack_id!r} has no unit {unit_id!r}. Available: {pack.unit_ids()}"
            )
        return pack, path

    hits = [(p, p.card_path(unit_id)) for p in packs.values() if p.card_path(unit_id)]
    if not hits:
        avail = {pid: p.unit_ids() for pid, p in sorted(packs.items())}
        raise PackError(f"no unit {unit_id!r} in any loaded pack. Available: {avail}")
    if len(hits) > 1:
        # Ambiguity is a real configuration problem, not something to guess through.
        raise PackError(
            f"unit {unit_id!r} is defined in multiple packs: "
            f"{sorted(p.pack_id for p, _ in hits)}. Pass pack= to disambiguate."
        )
    return hits[0][0], hits[0][1]


def list_units() -> list[tuple[str, str]]:
    """(pack_id, unit_id) for every card in every discovered pack."""
    return [
        (pid, uid)
        for pid, pack in sorted(registry().items())
        for uid in pack.unit_ids()
    ]


# ------------------------------------------------------------------------------ schema

def load_core_schema() -> dict:
    with open(CORE_SCHEMA_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def merged_schema(packs: dict[str, Pack] | None = None) -> dict:
    """Core schema with every pack's vocabulary folded into the extensible enums.

    The result is what a card validates against. A card using `unit_class:
    distillation_column` is valid exactly when some loaded pack claims that value, which
    is what makes the engine domain-free rather than domain-ignorant.
    """
    schema = load_core_schema()
    enums: dict[str, list] = {k: list(v) for k, v in schema.get("enums", {}).items()}
    for key, spec in schema.get("extensible_enums", {}).items():
        enums.setdefault(key, list(spec.get("base", []) or []))

    contributors: dict[str, dict[str, str]] = {k: {} for k in enums}
    for pid, pack in sorted((packs if packs is not None else registry()).items()):
        ext = pack.schema_extensions()
        for key, values in (ext.get("enums") or {}).items():
            if key not in _EXTENSIBLE:
                raise PackError(
                    f"pack {pid}: cannot extend enum {key!r}. Engine code branches on it; "
                    f"extensible enums are {list(_EXTENSIBLE)}."
                )
            for v in values:
                prior = contributors[key].get(v)
                if prior is not None and prior != pid:
                    raise PackError(
                        f"packs {prior!r} and {pid!r} both define {key} value {v!r}. "
                        "Two domains claiming one vocabulary term will silently validate "
                        "each other's cards; rename one."
                    )
                if v not in enums[key]:
                    enums[key].append(v)
                contributors[key][v] = pid
        for rule in ext.get("hard_rules") or []:
            schema.setdefault("hard_rules", []).append(f"[{pid}] {rule}")

    schema["enums"] = enums
    schema["_enum_contributors"] = contributors
    return schema


# ------------------------------------------------------------------------- check loading

_LOADED_MODULES: set[str] = set()


def load_pack_checks(
    packs: dict[str, Pack] | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Import each pack's check modules for their registration side effects.

    Packs are plain directories, not installed Python packages, so this goes through
    importlib rather than `import`. Modules are registered in `sys.modules` under a
    namespaced name so a second pack shipping `checks/rotating.py` cannot shadow the first.

    Returns (loaded module names, {pack/module: error}). Failures are returned rather than
    raised so that one broken pack cannot take the engine down with it, and so the failure
    can be reported as a coverage gap instead of disappearing.
    """
    loaded: list[str] = []
    errors: dict[str, str] = {}
    for pid, pack in sorted((packs if packs is not None else registry()).items()):
        for path in pack.check_modules:
            label = f"{pid}:{os.path.basename(path)}"
            mod_name = f"tssme_pack_{pid.replace('-', '_')}_{os.path.basename(path)[:-3]}"
            if mod_name in _LOADED_MODULES:
                continue
            try:
                if not os.path.exists(path):
                    raise PackError(f"check module {path} does not exist")
                spec = importlib.util.spec_from_file_location(mod_name, path)
                if spec is None or spec.loader is None:
                    raise PackError(f"cannot load check module {path}")
                module = importlib.util.module_from_spec(spec)
                sys.modules[mod_name] = module
                spec.loader.exec_module(module)
            except Exception as exc:  # noqa: BLE001 - returned to the caller, not swallowed
                sys.modules.pop(mod_name, None)
                errors[label] = f"{type(exc).__name__}: {exc}"
                continue
            _LOADED_MODULES.add(mod_name)
            loaded.append(mod_name)
    return loaded, errors
