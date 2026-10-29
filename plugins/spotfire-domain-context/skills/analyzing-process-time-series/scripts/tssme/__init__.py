"""tssme -- SME-grounded time series analysis for historian data.

Four layers, each owning one kind of change:

    engine   this package               general time series method   changes rarely
    pack     pack.yaml + units/*.yaml   what a unit is and how it    changes slowly
                                        fails, as validated data
    profile  profile.yaml               tags, bands, data source     changes constantly
    bundle   bundles/*.yaml             a named shippable persona    see tssme.bundles

The engine's assumption about its input is deliberately small: a wide frame, a timestamp
index, and N columns of sensors and conditions. Column naming is a tag map's business; a
measured band is a calibration overlay's; neither is the engine's.

Typical use:

    from tssme import analyse
    ctx, result = analyse(profile="<profile-id>")                  # everything declared
    ctx, result = analyse("export.csv", unit="<unit>", tagmap="<map>")   # or piecewise
    ctx, result = analyse(frame, unit="<unit>", tagmap="<map>")    # an in-memory DataFrame
"""

from __future__ import annotations

import pandas as pd

from .cards import Card, CardError, apply_calibration, list_cards, load_card
from .checks import CHECKS, PACK_LOAD_ERRORS, RunResult, run_checks
from .findings import Finding, sort_findings
from .packs import Pack, PackError, get_pack, list_units
from .packs import registry as pack_registry
from .prep import Context, build_context, frame_from, load_frame
from .profiles import Profile, ProfileError, discover_profiles, load_profile
from .report import report_md
from .resolve import Resolution, ResolutionError, discover_assets, load_tagmap, resolve

__all__ = [
    "Card", "CardError", "Context", "Finding", "Pack", "PackError", "Profile",
    "ProfileError", "Resolution", "ResolutionError", "RunResult", "CHECKS",
    "PACK_LOAD_ERRORS", "analyse", "apply_calibration", "build_context",
    "discover_assets", "discover_profiles", "frame_from", "get_pack", "list_cards",
    "list_units", "load_card", "load_frame", "load_profile", "load_tagmap", "pack_registry",
    "report_md", "resolve", "run_checks", "sort_findings",
]

__version__ = "1.2.0"


def analyse(
    data_path: str | pd.DataFrame | None = None,
    unit: str | None = None,
    tagmap: str | None = None,
    asset: str | None = None,
    enabled: list[str] | None = None,
    profile: str | None = None,
    pack: str | None = None,
    calibration: str | None = None,
) -> tuple[Context, RunResult]:
    """Full pipeline: load, resolve, derive, segment, check.

    `data_path` is a CSV path or an in-memory DataFrame (a Spotfire data function input).
    Pass `profile` to take unit, tag map, calibration, asset and data from a deployment
    profile. Any explicit argument overrides the profile, which is what makes a profile
    usable against an ad-hoc export without editing it.
    """
    prof = load_profile(profile) if profile else None
    if prof is not None:
        unit = unit or prof.unit
        pack = pack or prof.pack
        tagmap = tagmap or prof.tagmap_path
        calibration = calibration or prof.calibration_path
        asset = asset or prof.asset
        if data_path is None:
            data_path = prof.data_path
        if enabled is None:
            enabled = prof.enabled_checks

    if not unit:
        raise CardError("analyse() needs a unit, either directly or via a profile")
    if not tagmap:
        raise ResolutionError("analyse() needs a tagmap, either directly or via a profile")
    if data_path is None or (isinstance(data_path, str) and not data_path):
        raise ValueError("analyse() needs data (a CSV path or a DataFrame), either directly "
                         "or via a profile")

    card = load_card(unit, pack=pack, calibration=calibration)
    tm = load_tagmap(tagmap)
    time_column = tm.get("time_column", "Timestamp")
    if isinstance(data_path, pd.DataFrame):
        raw = frame_from(data_path, time_column)
    else:
        raw = load_frame(data_path, time_column)

    if asset is None:
        # Only resolve an asset if the tag map says there is such a dimension. A wide
        # export of one unit is the ordinary case and must not be made to invent an id.
        assets = discover_assets(list(raw.columns), tm)
        if len(assets) == 1:
            asset = assets[0]
        elif len(assets) > 1:
            raise ResolutionError(
                f"this export contains several assets {assets}. Pass asset= to choose one; "
                "resolving roles across assets would mix two units into one analysis."
            )

    res = resolve(list(raw.columns), tm, asset, card.required_roles())
    ctx = build_context(raw, card, res)
    return ctx, run_checks(ctx, enabled)
