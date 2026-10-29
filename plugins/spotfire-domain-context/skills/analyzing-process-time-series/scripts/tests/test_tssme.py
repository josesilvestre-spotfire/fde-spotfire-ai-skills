"""Regression tests for tssme.

Every test here exists because the behaviour it asserts was once wrong. They are written
as plain asserts with a built-in runner so they work without pytest, which is not installed
in the Spotfire Python environment this library has to run in. `python scripts/tests/test_tssme.py`
runs them; pytest will also collect them unchanged.

Nothing here touches a real asset, a real site or a real pack. The only knowledge the
engine's own tests may depend on is the synthetic example that ships with the engine
(`assets/examples/example-pack`), because a test that needs a domain pack installed is a test that
has smuggled a domain into the engine.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import traceback

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tssme import analyse                                      # noqa: E402
from tssme.cards import (Card, CardError, apply_calibration,   # noqa: E402
                         load_card, load_schema, validate)
from tssme.findings import Finding                             # noqa: E402
from tssme.packs import PackError, discover_packs, merged_schema, registry  # noqa: E402
from tssme.prep import build_context, _cusum_segments          # noqa: E402
from tssme.profiles import load_profile                        # noqa: E402
from tssme.resolve import (Resolution, ResolutionError, dedup_key,  # noqa: E402
                           discover_assets, resolve)
from tssme.bundles import BundleError, load_bundle, resolve_bundle, satisfies  # noqa: E402
from tssme.checks import CHECKS, PACK_LOAD_ERRORS, run_checks  # noqa: E402
from tssme.checks.statistical import _band_adjusted_trend, _n_eff  # noqa: E402

ENGINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --------------------------------------------------------------------------- fixtures

# The fixture vocabulary is the example pack's, not a domain pack's. `flow_segment` and
# `example_analyst` are contributed by assets/examples/example-pack, which ships with the engine,
# so these cards validate with no third-party pack installed.
def make_card(**over) -> Card:
    raw = {
        "card_version": "1.0", "unit_id": "test-unit", "unit_class": "flow_segment",
        "service": "test", "persona": "example_analyst",
        "roles": [
            {"id": "inlet_pressure", "description": "in", "kind": "sensor",
             "quantity": "pressure", "units": "kPa", "source": "test"},
            {"id": "outlet_pressure", "description": "out", "kind": "sensor",
             "quantity": "pressure", "units": "kPa", "source": "test"},
            {"id": "flow", "description": "f", "kind": "sensor",
             "quantity": "flow", "units": "m3/h", "source": "test"},
            {"id": "residual", "description": "r", "kind": "calculated",
             "quantity": "differential_pressure", "units": "kPa", "source": "test"},
        ],
        "invariants": [
            {"id": "flow_drops_pressure", "kind": "inequality",
             "expr": "inlet_pressure > outlet_pressure", "severity": "critical",
             "source": "test"},
        ],
        "regimes": [{"id": "flow_band", "by": "flow", "method": "bin",
                     "params": {"width": 20}}],
        "checks": {"enabled": ["rel_inequality"]},
    }
    raw.update(over)
    return Card(raw=raw, path="<test>")


def make_ctx(frame: pd.DataFrame, card: Card | None = None, enabled=None):
    card = card or make_card()
    cols = {c: c for c in frame.columns}
    res = Resolution(asset=None, role_to_column=cols, missing_required=[],
                     unmapped_columns=[], duplicate_candidates={}, detector_columns=[])
    return build_context(frame, card, res)


def daily(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2025-01-01", periods=n, freq="D")


class temp_pack:
    """A throwaway pack on disk. Packs are discovered from the filesystem, so the only
    honest way to test discovery is to put one there."""

    def __init__(self, pack_id: str, manifest: dict, extensions: dict | None = None):
        self.pack_id, self.manifest, self.extensions = pack_id, manifest, extensions

    def __enter__(self) -> str:
        self.root = tempfile.mkdtemp(prefix="tssme-pack-")
        d = os.path.join(self.root, self.pack_id)
        os.makedirs(os.path.join(d, "units"))
        man = {"pack_id": self.pack_id, "version": "1.0.0"} | self.manifest
        if self.extensions is not None:
            man["schema_extensions"] = "schema/extensions.yaml"
            os.makedirs(os.path.join(d, "schema"))
            with open(os.path.join(d, "schema", "extensions.yaml"), "w", encoding="utf-8") as fh:
                yaml.safe_dump(self.extensions, fh)
        with open(os.path.join(d, "pack.yaml"), "w", encoding="utf-8") as fh:
            yaml.safe_dump(man, fh)
        return self.root

    def __exit__(self, *exc):
        shutil.rmtree(self.root, ignore_errors=True)
        return False


def expect(exc_type, fn, *needles):
    """Assert a call raises, and that the message says something useful. An error whose
    text does not name the problem is only marginally better than a silent wrong answer."""
    try:
        fn()
    except exc_type as exc:
        for n in needles:
            assert n in str(exc), f"message {str(exc)!r} does not mention {n!r}"
        return exc
    raise AssertionError(f"expected {exc_type.__name__}, nothing was raised")


# ------------------------------------------------------------------ layer 1: the engine

def test_blanked_row_is_not_an_inequality_violation():
    """A partial row is blanked to NaN by prep. NaN > NaN evaluates to False in pandas,
    not NaN, so reading evaluability off the RESULT counted every blanked row as a
    critical invariant violation."""
    idx = daily(60)
    df = pd.DataFrame({
        "inlet_pressure": np.full(60, 800.0),
        "outlet_pressure": np.full(60, 45.0),
        "flow": np.linspace(100, 160, 60),
        "residual": np.zeros(60),
    }, index=idx)
    df.iloc[-1] = np.nan          # the export snapshot row
    ctx = make_ctx(df)
    out = run_checks(ctx, ["rel_inequality"]).findings
    violations = [f for f in out if f.kind == "defect"]
    assert not violations, f"blanked row produced a false violation: {violations[0].summary}"
    assert any(f.kind == "verified" for f in out), "passing invariant was not reported"
    passed = [f for f in out if f.kind == "verified"][0]
    assert passed.statistic["evaluable_samples"] == 59
    assert passed.statistic["skipped_incomplete_rows"] == 1


def test_trend_survives_bands_that_correlate_with_time():
    """Z-scoring within regime subtracts each band's own mean, which absorbs exactly the
    drift being looked for when band membership moves with time. Band fixed effects keep
    the slope interpretable."""
    n = 300
    idx = daily(n)
    t = np.arange(n, dtype=float)
    flow = 200000 + 300 * t                      # throughput ramps all year
    true_slope = 0.05
    rng = np.random.default_rng(0)
    y = 100.0 + true_slope * t + rng.normal(0, 0.5, n)

    days = pd.Series(t, index=idx)
    band = pd.Series((np.floor(flow / 10000) * 10000).astype(int), index=idx).astype(str)
    fit = _band_adjusted_trend(pd.Series(y, index=idx), days, band)
    assert fit is not None
    assert abs(fit["slope_per_day"] - true_slope) < 0.02, fit
    lo, hi = fit["ci95"]
    assert lo > 0, f"drift not significant: {fit}"

    # The naive approach must demonstrably fail, or this test proves nothing.
    d = pd.DataFrame({"y": y, "t": t, "g": band.to_numpy()})
    z = d.groupby("g")["y"].transform(lambda s: (s - s.mean()) / (s.std() or 1))
    naive = np.polyfit(d["t"], z, 1)[0]
    assert abs(naive) < abs(true_slope) / 5, (
        f"within-band z-scoring should have absorbed the drift but gave slope {naive}")


def test_autocorrelation_shrinks_effective_sample_size():
    rng = np.random.default_rng(1)
    white = rng.normal(0, 1, 500)
    ar = np.zeros(500)
    for i in range(1, 500):
        ar[i] = 0.9 * ar[i - 1] + rng.normal(0, 1)
    n_white, _ = _n_eff(white)
    n_ar, r1 = _n_eff(ar)
    assert n_white > 400, n_white
    assert n_ar < 100, (n_ar, r1)


def test_cusum_does_not_split_the_head_of_a_stepping_series():
    """Seeding the CUSUM reference from the mean of the WHOLE series guarantees a false
    changepoint a few samples into any series that steps or trends: the early data sits far
    from a mean the later data pulled, so the statistic crosses threshold immediately and
    splits off an opening segment corresponding to no event. The reference must come from a
    warmup window."""
    rng = np.random.default_rng(5)
    x = np.concatenate([rng.normal(0, 1, 200), rng.normal(8, 1, 200)])
    segs = _cusum_segments(pd.Series(x))
    boundaries = [i for i in range(1, len(segs)) if segs[i] != segs[i - 1]]
    assert boundaries, "a 8-sigma step produced no changepoint at all"
    assert min(boundaries) > 30, (
        f"spurious changepoint at sample {min(boundaries)}; the step is at 200")
    assert segs[0] == segs[100], "the pre-step head was split into two segments"


def test_rail_saturation_found_and_excluded_from_band_excursions():
    """A clamped value is not a measurement. It must be reported once as a rail and must
    not also be counted as a band excursion under a process explanation."""
    n = 200
    idx = daily(n)
    rng = np.random.default_rng(2)
    temp = rng.uniform(30, 90, n)
    temp[:6] = 20.0        # clamped low rail
    temp[6:12] = 110.0     # clamped high rail
    card = make_card(roles=[
        {"id": "temperature", "description": "t", "kind": "sensor", "quantity": "temperature",
         "units": "degF", "normal": [25, 95], "band_type": "descriptive", "source": "test"},
    ], invariants=[], regimes=[], checks={"enabled": ["dq_rail_saturation", "phys_range"]})
    ctx = make_ctx(pd.DataFrame({"temperature": temp}, index=idx), card)

    rails = [f for f in run_checks(ctx, ["dq_rail_saturation"]).findings]
    assert len(rails) == 1, rails
    assert rails[0].statistic["pinned_samples"] == 12
    assert rails[0].statistic["unclamped_range"][0] > 25

    band = run_checks(ctx, ["phys_range"]).findings
    assert not band, f"clamped samples were double-reported as band excursions: {band}"


def test_normative_band_is_not_treated_as_a_card_calibration_problem():
    """A descriptive band missed 25% of the time means the card is wrong. A normative band
    missed 25% of the time means the unit is off-spec. Collapsing the two either buries a
    real problem or manufactures one."""
    n = 200
    idx = daily(n)
    vals = np.concatenate([np.full(150, 1.0), np.full(50, 40.0)])   # 25% way out

    def build(band_type):
        card = make_card(roles=[
            {"id": "residual", "description": "r", "kind": "calculated",
             "quantity": "differential_pressure", "units": "kPa", "normal": [-5, 5],
             "band_type": band_type, "source": "test"}],
            invariants=[], regimes=[], checks={"enabled": ["phys_range"]})
        ctx = make_ctx(pd.DataFrame({"residual": vals}, index=idx), card)
        return run_checks(ctx, ["phys_range"]).findings[0]

    norm = build("normative")
    desc = build("descriptive")
    assert norm.severity == "high", norm.severity
    assert "Do not widen" in norm.next_step
    assert desc.severity == "low", desc.severity
    assert "does not fit this asset" in desc.summary


def test_changepoint_reports_one_event_across_correlated_roles():
    """One physical event moves many tags. Reporting it once per tag buries the signal."""
    n = 200
    idx = daily(n)
    rng = np.random.default_rng(3)
    step = np.concatenate([np.zeros(100), np.full(100, 60.0)])
    df = pd.DataFrame({
        "outlet_pressure": 800 + step + rng.normal(0, 3, n),
        "residual": 0 + step + rng.normal(0, 3, n),
        "flow": np.full(n, 120.0) + rng.normal(0, 0.2, n),
        "inlet_pressure": np.full(n, 845.0) + rng.normal(0, 0.5, n),
    }, index=idx)
    card = make_card(
        invariants=[], regimes=[],
        failure_modes=[{"id": "fm", "name": "fm", "severity": "high", "onset": "instant",
                        "signature": {"residual": "up", "outlet_pressure": "up"},
                        "confounders": [], "source": "t"}],
        checks={"enabled": ["stat_changepoint"]})
    out = run_checks(make_ctx(df, card), ["stat_changepoint"]).findings
    assert len(out) == 1, [f.summary for f in out]
    assert len(out[0].roles) >= 2, out[0].roles
    assert out[0].confidence == "corroborated"


def test_detector_firing_on_most_samples_is_flagged():
    n = 300
    idx = daily(n)
    rng = np.random.default_rng(4)
    raw = pd.DataFrame({
        "flow": np.full(n, 120.0) + rng.normal(0, 1.0, n),
        "Events - Positive Rate of Change": (rng.random(n) < 0.66).astype(int),
    }, index=idx)
    card = make_card(roles=[{"id": "flow", "description": "f", "kind": "sensor",
                             "quantity": "flow", "units": "m3/h", "source": "t"}],
                     invariants=[], regimes=[],
                     checks={"enabled": ["stat_detector_firing_rate"]})
    res = Resolution(asset=None, role_to_column={"flow": "flow"}, missing_required=[],
                     unmapped_columns=[], duplicate_candidates={},
                     detector_columns=["Events - Positive Rate of Change"])
    ctx = build_context(raw, card, res)
    out = run_checks(ctx, ["stat_detector_firing_rate"]).findings
    assert len(out) == 1 and out[0].severity == "high", out
    assert out[0].statistic["firing_rate"] > 0.5


def test_finding_rejects_an_unknown_kind():
    expect(ValueError,
           lambda: Finding(check_id="x", unit_id="u", severity="low", summary="s", kind="bogus"),
           "bad kind")


# ------------------------------------------------- the requires_roles gate, on every kind

def _gate_card(invariant: dict, enabled: str) -> Card:
    return make_card(invariants=[invariant], regimes=[], checks={"enabled": [enabled]})


def test_monotonic_invariant_with_unmet_preconditions_is_not_evaluated():
    """An invariant that only holds under a condition the data cannot evidence must report
    a coverage gap. Asserting it anyway produces a confident violation that describes the
    missing precondition rather than the equipment."""
    n = 100
    card = _gate_card(
        {"id": "falls_with_flow", "kind": "monotonic",
         "expr": "outlet_pressure decreasing in flow", "requires_roles": ["drive_speed"],
         "source": "test"}, "rel_monotonic")
    df = pd.DataFrame({"outlet_pressure": np.linspace(500, 900, n),
                       "flow": np.linspace(80, 160, n)}, index=daily(n))
    out = run_checks(make_ctx(df, card), ["rel_monotonic"]).findings
    assert len(out) == 1
    assert out[0].kind == "not_evaluated", out[0].kind
    assert "drive_speed" in out[0].summary


def test_range_invariant_with_unmet_preconditions_is_not_evaluated():
    """The gate was honoured only by the relational checks. `range` invariants are consumed
    by stat_residual_bias, which evaluated them regardless, so a card author who declared
    requires_roles was protected on four invariant kinds out of five and never told which.
    The gate now lives in checks/_gates.py so every consumer shares it."""
    n = 200
    rng = np.random.default_rng(6)
    card = _gate_card(
        {"id": "tight_at_reference", "kind": "range",
         "expr": "mean(residual) in [-1, 1]", "window": "full",
         "requires_roles": ["drive_speed"], "severity": "low", "source": "test"},
        "stat_residual_bias")
    df = pd.DataFrame({"residual": 9.0 + rng.normal(0, 0.5, n)}, index=daily(n))
    out = run_checks(make_ctx(df, card), ["stat_residual_bias"]).findings
    assert len(out) == 1, [f.summary for f in out]
    assert out[0].kind == "not_evaluated", (
        f"a badly biased residual was reported as a violation of an invariant whose "
        f"precondition is absent: {out[0].summary}")
    assert "drive_speed" in out[0].summary


def test_balance_invariant_is_evaluated_like_an_identity():
    """`balance` is a schema enum value. No check consumed it, so a mass balance written on a
    card was silently never tested. It is now an identity with a wider tolerance."""
    n = 60
    rng = np.random.default_rng(8)
    feed = 1000.0 + rng.normal(0, 5, n)
    split = feed * 0.4
    df = pd.DataFrame({"flow": feed, "inlet_pressure": split,
                       "outlet_pressure": feed - split}, index=daily(n))
    inv = {"id": "mass_balance", "kind": "balance", "tol": 0.02, "severity": "high",
           "expr": "flow == inlet_pressure + outlet_pressure", "source": "test"}
    card = make_card(invariants=[inv], regimes=[], checks={"enabled": ["rel_identity"]})
    out = run_checks(make_ctx(df, card), ["rel_identity"]).findings
    assert len(out) == 1 and out[0].kind == "verified", [f.summary for f in out]

    df["outlet_pressure"] *= 1.2           # a 12 percent imbalance
    out = run_checks(make_ctx(df, card), ["rel_identity"]).findings
    assert len(out) == 1 and out[0].kind == "defect", [f.summary for f in out]


def test_invariant_with_a_missing_operand_is_reported_not_evaluated():
    """An invariant whose expression names a role absent from the data was skipped without
    a trace. It must surface as a coverage gap, and numeric literals such as 1e6 must not be
    mistaken for role names."""
    n = 60
    df = pd.DataFrame({"flow": np.full(n, 100.0), "inlet_pressure": np.full(n, 1e-4)},
                      index=daily(n))
    invs = [
        {"id": "needs_absent_role", "kind": "identity", "tol_abs": 0.1,
         "expr": "flow == acid_gas_flow * 1e6", "source": "test"},
        {"id": "literal_is_not_a_role", "kind": "identity", "tol_abs": 0.1,
         "expr": "flow == inlet_pressure * 1e6", "source": "test"},
        {"id": "ordering_needs_absent_role", "kind": "inequality",
         "expr": "flow > design_flow", "source": "test"},
    ]
    card = make_card(invariants=invs, regimes=[],
                     checks={"enabled": ["rel_identity", "rel_inequality"]})
    out = run_checks(make_ctx(df, card), ["rel_identity", "rel_inequality"]).findings
    by_inv = {f.statistic.get("invariant", f.summary): f for f in out}
    assert by_inv["needs_absent_role"].kind == "not_evaluated"
    assert "acid_gas_flow" in by_inv["needs_absent_role"].summary
    assert by_inv["ordering_needs_absent_role"].kind == "not_evaluated"
    verified = [f for f in out if f.kind == "verified"]
    assert len(verified) == 1 and "literal_is_not_a_role" in verified[0].summary, (
        [f.summary for f in out])


# ------------------------------------------------------------------ card validation rules

def test_card_validation_separates_confounders_from_differentials():
    """A confounder is a benign explanation; a differential is a competing fault. Listing
    a failure mode as a confounder is a modelling error the validator must catch."""
    raw = make_card().raw | {
        "confounders": [{"id": "flow_shift", "description": "d", "roles": ["flow"],
                         "test": "regime_shift", "source": "t"}],
        "failure_modes": [
            {"id": "restriction", "name": "r", "severity": "high", "onset": "weeks",
             "signature": {"residual": "up", "flow": "unchanged"},
             "confounders": ["flow_shift"], "source": "t"},
            {"id": "drift", "name": "d", "severity": "medium", "onset": "weeks",
             "signature": {"residual": "up", "flow": "unchanged"},
             "confounders": ["restriction"], "source": "t"},   # wrong: that is a fault
        ],
    }
    problems = validate(raw, load_schema())
    assert any("unknown confounder 'restriction'" in p and "differentials" in p
               for p in problems), problems


def test_card_validation_requires_band_type_when_a_band_is_given():
    raw = make_card().raw
    raw["roles"][0]["normal"] = [0, 10]
    problems = validate(raw, load_schema())
    assert any("band_type" in p for p in problems), problems


def test_card_validation_rejects_a_unit_class_no_pack_claims():
    """unit_class is an extensible enum with an empty base: a value is valid exactly when
    some loaded pack claims it. That is what keeps the engine domain-free rather than
    domain-ignorant."""
    raw = make_card().raw | {"unit_class": "not_a_class_any_pack_defines"}
    problems = validate(raw, load_schema())
    assert any("unit_class" in p for p in problems), problems


def test_example_card_validates():
    """The engine's own example card must load and validate with no domain pack present."""
    card = load_card("flow-segment", pack="example")
    assert card.unit_class == "flow_segment"
    assert card.required_roles(), "the example card declares no required roles"


# ------------------------------------------------------------------- layer 2: packs

def test_pack_contributes_vocabulary_the_engine_never_heard_of():
    with temp_pack("tmp-dom", {}, {"enums": {"unit_class": ["widget_train"],
                                             "persona": ["widget_engineer"]}}) as root:
        packs = discover_packs([root])
        schema = merged_schema(packs)
        assert "widget_train" in schema["enums"]["unit_class"]
        assert schema["_enum_contributors"]["unit_class"]["widget_train"] == "tmp-dom"


def test_pack_cannot_extend_an_enum_the_engine_branches_on():
    """severity, direction, band_type and the rest are method properties, not vocabulary.
    A pack that adds `severity: catastrophic` would produce findings the report cannot
    route and the caller cannot rank."""
    with temp_pack("tmp-bad", {}, {"enums": {"severity": ["catastrophic"]}}) as root:
        packs = discover_packs([root])
        expect(PackError, lambda: merged_schema(packs),
               "cannot extend enum", "severity")


def test_two_packs_cannot_claim_the_same_vocabulary_term():
    """Two domains claiming one term would silently validate each other's cards."""
    with temp_pack("tmp-a", {}, {"enums": {"unit_class": ["shared_term"]}}) as ra, \
         temp_pack("tmp-b", {}, {"enums": {"unit_class": ["shared_term"]}}) as rb:
        packs = discover_packs([ra, rb])
        assert len(packs) == 2, packs
        expect(PackError, lambda: merged_schema(packs), "both define", "shared_term")


def test_a_broken_pack_does_not_take_the_engine_down():
    """Check-module import failures are collected, not raised. One unparseable pack must
    leave the engine usable and the failure visible, not make `import tssme` fail."""
    assert isinstance(PACK_LOAD_ERRORS, dict)
    assert not PACK_LOAD_ERRORS, f"a pack failed to load: {PACK_LOAD_ERRORS}"
    assert "dq_flatline" in CHECKS, "the engine's own checks did not register"


def test_example_pack_is_discovered_without_configuration():
    reg = registry(refresh=True)
    assert "example" in reg, sorted(reg)
    assert "flow-segment" in reg["example"].unit_ids()


# -------------------------------------------------------- layer 3a: calibration overlays

def _overlay_card() -> dict:
    return make_card(roles=[
        {"id": "flow", "description": "f", "kind": "sensor", "quantity": "flow",
         "units": "m3/h", "limits": {"lo": 0}, "source": "class knowledge"}],
        derived=[{"id": "residual_pct", "expr": "100.0 * residual / flow",
                  "units": "percent", "description": "r", "normal": [-5, 5],
                  "band_type": "normative", "source": "class knowledge"}],
        invariants=[], regimes=[]).raw


def test_calibration_overlays_a_band_and_records_provenance():
    raw = _overlay_card()
    applied = apply_calibration(raw, {
        "unit": "test-unit", "source": "measured on the example export, 400 samples",
        "roles": {"flow": {"normal": [70, 170], "band_type": "descriptive"}},
    })
    assert applied == ["flow"]
    assert raw["roles"][0]["normal"] == [70, 170]
    assert raw["roles"][0]["limits"] == {"lo": 0}, "the overlay clobbered a class-level limit"


def test_calibration_cannot_redefine_physics():
    """An overlay that can add an invariant or a failure mode is a fork of the knowledge
    base, not a calibration of it, and the class card stops being the one place the
    knowledge lives."""
    for section in ("invariants", "failure_modes", "confounders", "regimes", "checks"):
        raw = _overlay_card()
        exc = expect(CardError,
                     lambda s=section, r=raw: apply_calibration(r, {"source": "s", s: []}),
                     "unknown top-level keys")
        if section in ("invariants", "failure_modes", "confounders", "regimes"):
            assert "class knowledge" in str(exc), (
                f"{section} was refused without explaining why: {exc}")


def test_calibration_cannot_set_a_field_outside_the_overlayable_set():
    raw = _overlay_card()
    expect(CardError,
           lambda: apply_calibration(raw, {"source": "s",
                                           "roles": {"flow": {"quantity": "pressure"}}}),
           "cannot set", "quantity")


def test_calibration_cannot_invent_a_spec():
    raw = _overlay_card()
    expect(CardError,
           lambda: apply_calibration(raw, {"source": "s",
                                           "roles": {"not_on_the_card": {"normal": [0, 1]}}}),
           "cannot", "add")


def test_calibration_without_provenance_is_refused():
    """A band with no source is a number from one asset over one period, read later as
    class knowledge. That is the failure this whole layer exists to prevent."""
    raw = _overlay_card()
    expect(CardError,
           lambda: apply_calibration(raw, {"roles": {"flow": {"normal": [70, 170]}}}),
           "source")


def test_calibration_targeting_the_wrong_unit_is_refused():
    raw = _overlay_card()
    expect(CardError,
           lambda: apply_calibration(raw, {"unit": "some-other-unit", "source": "s",
                                           "roles": {"flow": {"normal": [1, 2]}}}),
           "targets unit")


def test_uncalibrated_descriptive_bands_are_reported_as_a_gap():
    """A class card carries no descriptive bands, so before an overlay every descriptive
    band is missing. Silence there would read as 'in range'."""
    card = load_card("flow-segment", pack="example")
    assert card.uncalibrated_bands() == [], (
        "the uncalibrated card claims descriptive bands it should not have: "
        f"{card.uncalibrated_bands()}")
    prof = load_profile("example-segment")
    calibrated = load_card("flow-segment", pack="example",
                           calibration=prof.calibration_path)
    assert calibrated.calibration_id == "example-segment-2026H1"
    assert calibrated.roles["flow"]["normal"] == [70, 170]


# --------------------------------------------------------------- layer 3b: tag resolution

def test_tagmap_match_strategies():
    """Column naming is a deployment fact. The engine used to hardcode one convention
    because one example export happened to use it."""
    cols = ["Timestamp", "AREA1.PI-1001.PV", "AREA1.FI-1004.PV", "noise"]
    for strategy, template, want in [
        ("exact", "AREA1.PI-1001.PV", "AREA1.PI-1001.PV"),
        ("suffix", "PI-1001.PV", "AREA1.PI-1001.PV"),
        ("prefix", "AREA1.PI", "AREA1.PI-1001.PV"),
        ("regex", r"AREA\d\.PI-\d+\.PV", "AREA1.PI-1001.PV"),
    ]:
        tm = {"time_column": "Timestamp", "match": strategy,
              "roles": {"inlet_pressure": template}}
        res = resolve(cols, tm)
        assert res.role_to_column.get("inlet_pressure") == want, (strategy, res.role_to_column)


def test_per_role_match_strategy_overrides_the_map_default():
    cols = ["Timestamp", "AREA1.PI-1001.PV", "FLOW_TOTAL"]
    tm = {"time_column": "Timestamp", "match": "exact", "roles": {
        "inlet_pressure": {"template": "PI-1001.PV", "match": "suffix"},
        "flow": "FLOW_TOTAL",
    }}
    res = resolve(cols, tm)
    assert res.role_to_column["inlet_pressure"] == "AREA1.PI-1001.PV"
    assert res.role_to_column["flow"] == "FLOW_TOTAL"


def test_join_duplicates_are_detected_without_assuming_a_naming_scheme():
    """`Foo (2)` is what SQL joins, data relations and pandas merges produce, in any
    domain. Detection keys on the counter suffix alone, never on an asset convention."""
    assert dedup_key("FI-1004.PV (2)") == "FI-1004.PV"
    assert dedup_key("Totalizer (17)") == "Totalizer"
    assert dedup_key("clean") == "clean"

    cols = ["Timestamp", "FI-1004.PV", "FI-1004.PV (2)"]
    res = resolve(cols, {"time_column": "Timestamp", "roles": {"flow": "FI-1004.PV"}})
    assert res.role_to_column["flow"] == "FI-1004.PV", "the copy was preferred to the original"
    assert res.duplicate_candidates["flow"] == ["FI-1004.PV", "FI-1004.PV (2)"]
    assert "FI-1004.PV (2)" not in res.unmapped_columns


def test_ambiguous_match_is_an_error_not_a_guess():
    cols = ["Timestamp", "A.FLOW", "B.FLOW"]
    tm = {"time_column": "Timestamp", "match": "suffix", "roles": {"flow": "FLOW"}}
    expect(ResolutionError, lambda: resolve(cols, tm), "matches multiple", "Tighten")


def test_a_single_asset_export_has_no_asset_dimension():
    """A tag map without asset_pattern describes one unit. The answer is 'no asset
    dimension', not a crash and not an invented id."""
    assert discover_assets(["Timestamp", "FI-1004.PV"], {"roles": {}}) == []


def test_asset_pattern_must_name_the_asset_group():
    expect(ResolutionError,
           lambda: discover_assets(["FI_A1"], {"asset_pattern": r"_(\w+)$", "roles": {}}),
           "(?P<asset>")


def test_missing_required_roles_are_reported_not_silently_dropped():
    res = resolve(["Timestamp", "FI-1004.PV"],
                  {"time_column": "Timestamp", "roles": {"flow": "FI-1004.PV"}},
                  required_roles=["flow", "inlet_pressure"])
    assert res.missing_required == ["inlet_pressure"]


# ------------------------------------------------------------------- layer 4: bundles

def test_version_constraints():
    assert satisfies("1.1.0", ">=1.1,<2.0")
    assert not satisfies("2.0.0", ">=1.1,<2.0")
    assert not satisfies("1.0.9", ">=1.1,<2.0")
    assert satisfies("1.1.0", None)
    assert satisfies("1.2", ">=1.1")


def test_bundle_must_declare_what_it_refuses():
    """A persona that will not state its limits will improvise past them."""
    d = tempfile.mkdtemp(prefix="tssme-bundle-")
    try:
        path = os.path.join(d, "b.yaml")
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump({"bundle_id": "b", "name": "B", "version": "1.0.0",
                            "persona": "example_analyst", "packs": ["example"],
                            "brief": {"scope": "everything"}}, fh)
        expect(BundleError, lambda: load_bundle(path), "refuses")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_example_bundle_resolves_across_all_four_layers():
    out = resolve_bundle(load_bundle("example-agent"))
    assert out["problems"] == [], out["problems"]
    assert out["resolved"]
    assert out["engine"]["satisfied"]
    assert out["units"] == ["flow-segment"]
    assert out["packs"][0]["selection"] == "persona-default", (
        "omitting units: must select by persona")
    assert out["profiles"][0]["in_scope"]


# ------------------------------------------------------------- end to end, all four layers

def test_example_profile_runs_end_to_end():
    """The one test that exercises every layer at once against a concrete instance of the
    input contract: a wide frame, a timestamp index, N columns of sensors and conditions.

    The expected findings are listed in references/example-walkthrough.md. Anything asserted
    here is a fault deliberately planted by assets/examples/make_data.py, so a failure means the engine
    stopped detecting something it used to, not that the data changed."""
    ctx, run = analyse(profile="example-segment")

    assert not ctx.resolution.missing_required, ctx.resolution.missing_required
    assert ctx.resolution.role_to_column["flow"] == "FI-1004.PV"
    assert ctx.card.calibration_id == "example-segment-2026H1"

    by_check: dict[str, list] = {}
    for f in run.findings:
        by_check.setdefault(f.check_id, []).append(f)

    for check_id in ["dq_flatline",               # constant additive dose
                     "dq_partial_rows",           # blank trailing row
                     "dq_duplicate_series",       # the join duplicate
                     "dq_rail_saturation",        # temperature clipped at both ends
                     "dq_zero_order_hold",        # density held between assays
                     "stat_detector_firing_rate", # detector thresholded on sign
                     "stat_regime_drift",         # the planted restriction ramp
                     "stat_changepoint"]:         # the planted step
        assert check_id in by_check, f"planted fault no longer detected by {check_id}"

    drift = [f for f in by_check["stat_regime_drift"] if "residual" in f.roles]
    assert drift and drift[0].severity == "high", "the restriction ramp lost its severity"
    assert drift[0].statistic["slope_per_month"] > 1.0

    band = [f for f in by_check["phys_range"] if "residual_pct" in f.roles]
    assert band and band[0].statistic["band_type"] == "normative"
    assert "Do not widen" in band[0].next_step

    gaps = [f for f in run.findings if f.kind == "not_evaluated"]
    assert any("efficiency_at_reference" in f.summary for f in gaps), (
        "the requires_roles gate stopped reporting its coverage gap")

    verified = {f.summary for f in run.findings if f.kind == "verified"}
    assert any("residual_identity" in s for s in verified)
    assert any("flow_drops_pressure" in s for s in verified), (
        "the blank trailing row was read as an inequality violation")


# ------------------------------------------------- running inside a Spotfire data function

def test_analyse_accepts_an_in_memory_frame():
    """A Spotfire data function receives its input table as a DataFrame, not as a path.
    The in-memory route must produce exactly the findings the CSV route produces."""
    prof = load_profile("example-segment")
    frame = pd.read_csv(prof.data_path, encoding="utf-8-sig")
    _, from_path = analyse(profile="example-segment")
    _, from_frame = analyse(frame, profile="example-segment")
    assert ([f.summary for f in from_frame.findings]
            == [f.summary for f in from_path.findings])


def test_rank_correlation_and_robust_slope_match_scipy():
    """The NumPy paths in tssme.robust exist because the Python bundled with Spotfire
    Analyst 15.0 has no scipy. They must give the numbers scipy gives, ties included."""
    from tssme import robust
    try:
        from scipy import stats
    except ImportError:
        return                      # nothing to compare against in this environment
    rng = np.random.default_rng(11)
    cases = [(rng.normal(size=n), None) for n in (20, 57, 200)]
    tied_x = np.repeat(np.arange(30.0), 2)
    cases.append((tied_x, np.round(0.5 * tied_x + rng.normal(size=60))))
    for x, y in cases:
        if y is None:
            y = 0.3 * x + rng.normal(size=len(x))
        rho, p = robust.spearman_numpy(x, y)
        ref = stats.spearmanr(x, y)
        assert abs(rho - float(ref[0])) < 1e-12 and abs(p - float(ref[1])) < 1e-9 * max(1, p)
        mine = robust.theil_sen_numpy(y, x, 0.95)
        theirs = stats.theilslopes(y, x, alpha=0.95)
        assert np.allclose(mine, [float(v) for v in theirs[:4]], rtol=1e-12, atol=1e-12), (
            mine, theirs)


def test_engine_runs_end_to_end_without_scipy():
    """Run the example in a child interpreter where importing scipy fails, which is the
    situation inside the Python bundled with Spotfire Analyst 15.0."""
    import subprocess
    code = (
        "import sys; sys.modules['scipy'] = None; sys.modules['scipy.stats'] = None\n"
        f"sys.path.insert(0, {ENGINE_ROOT!r})\n"
        "from tssme import analyse, robust\n"
        "assert not robust.have_scipy()\n"
        "ctx, run = analyse(profile='example-segment')\n"
        "assert not run.errored, run.errored\n"
        "print(len(run.findings))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    _, with_scipy = analyse(profile="example-segment")
    assert int(out.stdout.strip().splitlines()[-1]) == len(with_scipy.findings)


# --------------------------------------------------------------------------- runner

def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = []
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception:
            failed.append(name)
            print(f"  FAIL  {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
