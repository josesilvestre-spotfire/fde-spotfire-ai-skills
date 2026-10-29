"""CLI: python -m tssme <command>

  analyse  --profile ID [--data CSV] [--out FILE] [--json] [--verbose]
  analyse  --data CSV --unit UNIT --tagmap MAP|PATH [--pack ID] [--calibration PATH]
           [--asset ID] [--out FILE] [--json] [--verbose]
  assets   --data CSV --tagmap MAP|PATH
  cards    [--validate] [--pack ID]
  checks
  packs
  profiles
  bundles  [--show ID]
"""

from __future__ import annotations

import argparse
import json
import sys

from . import analyse, discover_assets, load_frame, load_tagmap, report_md
from .cards import load_card
from .checks import CATEGORY_ORDER, CHECKS, PACK_LOAD_ERRORS
from . import bundles as _bundles
from . import packs as _packs
from . import profiles as _profiles


def _warn_pack_errors() -> None:
    """A pack that failed to load is a silent loss of coverage. Never let it be silent."""
    for label, err in PACK_LOAD_ERRORS.items():
        print(f"WARNING pack checks not loaded [{label}]: {err}", file=sys.stderr)


def _cmd_analyse(a: argparse.Namespace) -> int:
    _warn_pack_errors()
    ctx, result = analyse(
        data_path=a.data, unit=a.unit, tagmap=a.tagmap, asset=a.asset,
        profile=a.profile, pack=a.pack, calibration=a.calibration,
    )
    if a.json:
        payload = {
            "unit": ctx.unit_id,
            "pack": ctx.card.pack_id,
            "asset": ctx.resolution.asset,
            "calibration": ctx.card.calibration_id,
            "uncalibrated_bands": ctx.card.uncalibrated_bands(),
            "ran": result.ran, "skipped": result.skipped, "errored": result.errored,
            "findings": [f.to_dict() for f in result.findings],
        }
        text = json.dumps(payload, indent=2, default=str)
    else:
        text = report_md(ctx, result, verbose=a.verbose)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {a.out}")
    else:
        print(text)
    return 1 if any(f.severity in ("high", "critical") for f in result.findings) else 0


def _cmd_assets(a: argparse.Namespace) -> int:
    tm = load_tagmap(a.tagmap)
    raw = load_frame(a.data, tm.get("time_column", "Timestamp"))
    found = discover_assets(list(raw.columns), tm)
    if not found:
        print("(no asset dimension: this tag map has no asset_pattern, so the export is "
              "treated as one unit)")
        return 0
    for asset in found:
        print(asset)
    return 0


def _cmd_cards(a: argparse.Namespace) -> int:
    _warn_pack_errors()
    rc = 0
    units = (
        [(a.pack, u) for u in _packs.get_pack(a.pack).unit_ids()]
        if a.pack else _packs.list_units()
    )
    if not units:
        print("no unit cards found. Discovered packs: "
              f"{sorted(_packs.registry())}; searched {_packs.search_roots()}")
        return 1
    for pack_id, unit in units:
        if not a.validate:
            print(f"{pack_id:<20} {unit}")
            continue
        try:
            card = load_card(unit, pack=pack_id)
        except Exception as exc:
            print(f"FAIL {unit}: {exc}")
            rc = 1
            continue
        unver = card.unverified()
        uncal = card.uncalibrated_bands()
        print(f"OK   {unit}  ({len(card.roles)} roles, {len(card.invariants)} invariants, "
              f"{len(card.failure_modes)} failure modes"
              + (f", {len(unver)} UNVERIFIED" if unver else "")
              + (f", {len(uncal)} band(s) needing calibration" if uncal else "") + ")")
    return rc


def _cmd_checks(a: argparse.Namespace) -> int:
    _warn_pack_errors()
    for cat in CATEGORY_ORDER:
        for spec in sorted(CHECKS.values(), key=lambda s: s.check_id):
            if spec.category == cat:
                mod = getattr(spec.fn, "__module__", "")
                origin = "" if mod.startswith("tssme.") else "  [pack]"
                req = f"  requires {list(spec.requires)}" if spec.requires else ""
                print(f"{cat:<13} {spec.check_id:<34} {spec.description}{req}{origin}")
    return 0


def _cmd_packs(a: argparse.Namespace) -> int:
    reg = _packs.registry()
    if not reg:
        print(f"no packs found. Searched: {_packs.search_roots()}")
        return 1
    for pid, pack in sorted(reg.items()):
        print(f"{pid}  v{pack.version}  {pack.name}")
        print(f"    root:  {pack.root}")
        print(f"    units: {pack.unit_ids() or '(none)'}")
        ext = pack.schema_extensions().get("enums", {})
        for key in sorted(ext):
            print(f"    {key}: {ext[key]}")
    _warn_pack_errors()
    return 0


def _cmd_profiles(a: argparse.Namespace) -> int:
    found = _profiles.discover_profiles()
    if not found:
        print(f"no profiles found. Searched: {_profiles.search_roots()}")
        return 0
    for pid, prof in sorted(found.items()):
        print(f"{pid}  unit={prof.unit}"
              + (f" pack={prof.pack}" if prof.pack else "")
              + (f" asset={prof.asset}" if prof.asset else ""))
        print(f"    root: {prof.root}")
    return 0


def _cmd_bundles(a: argparse.Namespace) -> int:
    if a.show:
        bundle = _bundles.load_bundle(a.show)
        print(json.dumps(_bundles.resolve_bundle(bundle), indent=2, default=str))
        return 0
    found = _bundles.discover_bundles()
    if not found:
        print(f"no bundles found. Searched: {_bundles.search_roots()}")
        return 0
    for bid, b in sorted(found.items()):
        print(f"{bid}  v{b.version}  {b.name}  persona={b.persona}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tssme", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("analyse")
    pa.add_argument("--profile", help="deployment profile id or directory")
    pa.add_argument("--data", help="wide CSV; overrides the profile's data path")
    pa.add_argument("--unit")
    pa.add_argument("--pack")
    pa.add_argument("--tagmap", help="tagmap id or path")
    pa.add_argument("--calibration", help="asset calibration overlay path")
    pa.add_argument("--asset", help="only for exports holding several assets")
    pa.add_argument("--out")
    pa.add_argument("--json", action="store_true")
    pa.add_argument("--verbose", action="store_true")
    pa.set_defaults(fn=_cmd_analyse)

    ps = sub.add_parser("assets")
    ps.add_argument("--data", required=True)
    ps.add_argument("--tagmap", required=True)
    ps.set_defaults(fn=_cmd_assets)

    pc = sub.add_parser("cards")
    pc.add_argument("--validate", action="store_true")
    pc.add_argument("--pack")
    pc.set_defaults(fn=_cmd_cards)

    pk = sub.add_parser("checks")
    pk.set_defaults(fn=_cmd_checks)

    pp = sub.add_parser("packs")
    pp.set_defaults(fn=_cmd_packs)

    pr = sub.add_parser("profiles")
    pr.set_defaults(fn=_cmd_profiles)

    pb = sub.add_parser("bundles")
    pb.add_argument("--show", help="bundle id or path; prints the resolved manifest")
    pb.set_defaults(fn=_cmd_bundles)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
