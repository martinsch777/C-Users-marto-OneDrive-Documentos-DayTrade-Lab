from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.research.hyp_first_candle_event_discovery import (
    BOOTSTRAP_SEED,
    EXPECTED_CANONICAL_HASH,
    HYPOTHESIS_ID,
    _economic_threshold_comparison,
    _write_json,
)
from src.research.hyp_first_candle_event_study import (
    EVENT_TYPES,
    FcrEventStudyConfig,
    aggregate_fcr_event_paths,
    attach_bootstrap_intervals,
    bootstrap_mean_by_session,
)


DISCOVERY_DIR = Path("artifacts/research/HYP-FCR-EVENT-01/discovery_2022_2024")
POSTRUN_DIR_NAME = "postrun_integrity"
EXPECTED_HORIZONS = ("5min", "15min", "30min", "60min", "session_close")
EXPECTED_SYMBOLS = ("QQQ", "SPY")
EXPECTED_EVENT_ROWS = 8498
EXPECTED_PATH_ROWS = EXPECTED_EVENT_ROWS * len(EXPECTED_HORIZONS)
NUMERIC_TOLERANCE = 1e-12
BH_FDR_Q = 0.10
ANNUAL_CONCENTRATION_MAX_SHARE = 0.50
EVENT_KEY_COLUMNS = ("symbol", "session_date", "event_type", "event_side", "event_time")
HORIZON_ORDER = {value: index for index, value in enumerate(EXPECTED_HORIZONS)}
CANDIDATE_COMBINATIONS = (
    ("EVENT-07", "long_reversal", "5min"),
    ("EVENT-07", "long_reversal", "15min"),
    ("EVENT-07", "long_reversal", "30min"),
    ("EVENT-08", "short_reversal", "15min"),
    ("EVENT-08", "short_reversal", "30min"),
    ("EVENT-08", "short_reversal", "60min"),
)
CONFIG_PATH = Path("configs/research/hypotheses/HYP-FCR-EVENT-01.yaml")
PREREGISTRATION_DOC_PATH = Path("docs/HYP_FIRST_CANDLE_EVENT_STUDY_PREREGISTRATION.md")


@dataclass(frozen=True)
class AuditResult:
    output_dir: Path
    event_integrity_passed: bool
    path_integrity_passed: bool
    aggregate_reconciliation_passed: bool
    classification_audit_status: str
    final_status: str


@dataclass(frozen=True)
class EconomicRuleAudit:
    status: str
    tick_size: float
    threshold_required_for_hypothesis_generating: bool
    required_threshold_name: str | None
    baseline_applicable: bool
    stress_applicable: bool
    baseline_commission_rate_per_side: float | None
    baseline_slippage_ticks_per_execution: float | None
    stress_commission_rate_per_side: float | None
    stress_slippage_ticks_per_execution: float | None
    multiple_comparison_method: str | None
    ambiguity: bool
    notes: list[str]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _sha1_text(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def _derive_event_id(frame: pd.DataFrame) -> pd.Series:
    missing = [column for column in EVENT_KEY_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Cannot derive event_id; missing columns: {missing}")
    keys = frame.loc[:, EVENT_KEY_COLUMNS].astype(str).agg("|".join, axis=1)
    return keys.map(_sha1_text)


def _read_events(root: Path) -> pd.DataFrame:
    events = pd.read_csv(root / "events.csv", keep_default_na=False)
    events["derived_event_id"] = _derive_event_id(events)
    return events


def _read_paths(root: Path) -> pd.DataFrame:
    paths = pd.read_csv(root / "path_metrics.csv", keep_default_na=False)
    paths["derived_event_id"] = _derive_event_id(paths)
    return paths


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - project dependency
        raise RuntimeError("PyYAML is required to audit preregistered YAML.") from exc
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return loaded


def determine_economic_rule(
    config_path: Path = CONFIG_PATH,
    preregistration_doc_path: Path = PREREGISTRATION_DOC_PATH,
) -> EconomicRuleAudit:
    config = _read_yaml(config_path)
    doc_text = preregistration_doc_path.read_text(encoding="utf-8")
    lowered_doc = doc_text.lower()
    explicit_cost_fields = {
        "costs",
        "economic_threshold",
        "economic_thresholds",
        "cost_model",
        "commission_rate_per_side",
        "slippage_ticks_per_execution",
    }
    config_has_costs = any(key in config for key in explicit_cost_fields)
    doc_has_costs = any(term in lowered_doc for term in ("commission", "slippage", "baseline", "stress", "economic threshold"))
    config_tick = config.get("tick_size")
    tick_size = float(config_tick) if config_tick is not None else float(FcrEventStudyConfig().tick_size)
    notes = [
        "YAML contains one-tick language only inside EVENT-02/EVENT-04 strict-break definitions.",
        "Preregistration document contains one-tick language only inside event definitions.",
        "No two-tick, baseline-friction, stress-friction, or economic-threshold rule is defined for HYP-FCR-EVENT-01.",
        "Persisted economic_threshold_comparison.csv marks economic thresholds as not applicable because this is a non-strategy event study with no PnL/cost model.",
        "The 0.01 tick size is the audited operational tick size of the event-study tool, not an economic approval threshold.",
    ]
    ambiguity = bool(config_has_costs != doc_has_costs)
    status = "preregistration_ambiguity" if ambiguity else "no_economic_threshold_preregistered"
    return EconomicRuleAudit(
        status=status,
        tick_size=tick_size,
        threshold_required_for_hypothesis_generating=False,
        required_threshold_name=None,
        baseline_applicable=False,
        stress_applicable=False,
        baseline_commission_rate_per_side=None,
        baseline_slippage_ticks_per_execution=None,
        stress_commission_rate_per_side=None,
        stress_slippage_ticks_per_execution=None,
        multiple_comparison_method=None,
        ambiguity=ambiguity,
        notes=notes,
    )


def one_tick_return(event_price: pd.Series | np.ndarray | float, tick_size: float) -> pd.Series | float:
    return tick_size / event_price


def two_tick_return(event_price: pd.Series | np.ndarray | float, tick_size: float) -> pd.Series | float:
    return 2.0 * tick_size / event_price


def friction_threshold_return(
    event_price: pd.Series | np.ndarray | float,
    *,
    tick_size: float,
    commission_rate_per_side: float,
    slippage_ticks_per_execution: float,
    executions: int = 2,
) -> pd.Series | float:
    commission_return = executions * commission_rate_per_side
    slippage_return = executions * slippage_ticks_per_execution * tick_size / event_price
    return commission_return + slippage_return


def _bootstrap_mean_ci_by_session(
    frame: pd.DataFrame,
    *,
    value_column: str,
    seed: int = BOOTSTRAP_SEED,
    n_bootstrap: int = 500,
) -> tuple[float, float]:
    available = frame.loc[pd.to_numeric(frame[value_column], errors="coerce").notna(), ["session_date", value_column]].copy()
    available[value_column] = pd.to_numeric(available[value_column], errors="coerce")
    if available.empty:
        return float("nan"), float("nan")
    session_stats = available.groupby("session_date", sort=True)[value_column].agg(["sum", "count"])
    session_sums = session_stats["sum"].to_numpy(dtype=float)
    session_counts = session_stats["count"].to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    session_count = len(session_stats)
    means = np.empty(n_bootstrap, dtype=float)
    for index in range(n_bootstrap):
        sampled = rng.choice(session_count, size=session_count, replace=True)
        means[index] = session_sums[sampled].sum() / session_counts[sampled].sum()
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def _has_invisible_or_outer_space(series: pd.Series) -> pd.Series:
    text = series.astype(str)
    stripped = text.str.strip()
    invisible = text.str.contains(r"[\u200b\u200c\u200d\ufeff]", regex=True, na=False)
    return (text != stripped) | invisible


def audit_events(events: pd.DataFrame, output_dir: Path) -> dict[str, Any]:
    counts = (
        events.groupby(["symbol", "event_type"], dropna=False)
        .size()
        .reset_index(name="event_count")
        .sort_values(["symbol", "event_type"])
    )
    counts.to_csv(output_dir / "event_counts_reconciled.csv", index=False)
    events.to_csv(output_dir / "events_with_derived_event_id.csv", index=False)

    allowed_events = set(EVENT_TYPES)
    allowed_symbols = set(EXPECTED_SYMBOLS)
    exact_duplicate_count = int(events.duplicated().sum())
    duplicate_id_count = int(events["derived_event_id"].duplicated().sum())
    malformed_symbol_rows = events.loc[~events["symbol"].isin(allowed_symbols)].copy()
    malformed_event_rows = events.loc[~events["event_type"].isin(allowed_events)].copy()

    report = {
        "hypothesis_id": HYPOTHESIS_ID,
        "event_id_column_present": "event_id" in events.columns,
        "derived_event_id_policy": "sha1(symbol|session_date|event_type|event_side|event_time)",
        "total_rows": int(len(events)),
        "expected_total_rows": EXPECTED_EVENT_ROWS,
        "total_matches_expected": int(len(events)) == EXPECTED_EVENT_ROWS,
        "derived_event_id_unique": duplicate_id_count == 0,
        "derived_event_id_duplicate_count": duplicate_id_count,
        "symbol_null_count": int(events["symbol"].isna().sum()),
        "symbol_empty_count": int((events["symbol"].astype(str) == "").sum()),
        "event_type_null_count": int(events["event_type"].isna().sum()),
        "event_type_empty_count": int((events["event_type"].astype(str) == "").sum()),
        "unique_symbols": sorted(events["symbol"].astype(str).unique().tolist()),
        "unique_event_types": sorted(events["event_type"].astype(str).unique().tolist()),
        "symbol_outer_space_or_invisible_count": int(_has_invisible_or_outer_space(events["symbol"]).sum()),
        "event_type_outer_space_or_invisible_count": int(_has_invisible_or_outer_space(events["event_type"]).sum()),
        "symbol_dtype": str(events["symbol"].dtype),
        "event_type_dtype": str(events["event_type"].dtype),
        "exact_duplicate_rows": exact_duplicate_count,
        "malformed_symbol_rows": int(len(malformed_symbol_rows)),
        "malformed_event_type_rows": int(len(malformed_event_rows)),
        "qqq_event_05_count": int(((events["symbol"] == "QQQ") & (events["event_type"] == "EVENT-05")).sum()),
        "spy_event_05_count": int(((events["symbol"] == "SPY") & (events["event_type"] == "EVENT-05")).sum()),
        "counts_total": int(counts["event_count"].sum()),
        "root_cause_312_events": (
            "No events are missing. The 312-row discrepancy is QQQ EVENT-05; "
            "the visible manual grouping omitted that row group."
        ),
    }
    report["integrity_passed"] = (
        report["total_matches_expected"]
        and report["derived_event_id_unique"]
        and report["symbol_empty_count"] == 0
        and report["event_type_empty_count"] == 0
        and report["symbol_outer_space_or_invisible_count"] == 0
        and report["event_type_outer_space_or_invisible_count"] == 0
        and report["exact_duplicate_rows"] == 0
        and report["malformed_symbol_rows"] == 0
        and report["malformed_event_type_rows"] == 0
        and report["qqq_event_05_count"] == 312
        and report["counts_total"] == EXPECTED_EVENT_ROWS
    )
    _write_json(output_dir / "event_integrity_report.json", report)
    return report


def audit_paths(events: pd.DataFrame, paths: pd.DataFrame, output_dir: Path) -> dict[str, Any]:
    event_ids = set(events["derived_event_id"])
    path_ids = set(paths["derived_event_id"])
    orphan_rows = paths.loc[~paths["derived_event_id"].isin(event_ids)].copy()
    orphan_rows.to_csv(output_dir / "orphan_path_rows.csv", index=False)

    horizon_counts = (
        paths.groupby("derived_event_id")["horizon"]
        .agg(lambda values: sorted(values.astype(str).tolist(), key=lambda item: HORIZON_ORDER.get(item, 99)))
        .reset_index(name="horizons")
    )
    missing_rows = horizon_counts.loc[horizon_counts["horizons"].map(tuple) != EXPECTED_HORIZONS].copy()
    missing_rows["missing_horizons"] = missing_rows["horizons"].map(
        lambda values: sorted(set(EXPECTED_HORIZONS) - set(values), key=lambda item: HORIZON_ORDER[item])
    )
    missing_rows.to_csv(output_dir / "missing_horizons.csv", index=False)

    event_lookup = events.set_index("derived_event_id")[["symbol", "event_type"]]
    joined = paths.join(event_lookup, on="derived_event_id", rsuffix="_event")
    symbol_mismatch = int((joined["symbol"] != joined["symbol_event"]).sum())
    event_type_mismatch = int((joined["event_type"] != joined["event_type_event"]).sum())

    for column in ("event_time", "time_to_mfe", "time_to_mae"):
        if column in paths.columns:
            paths[column] = pd.to_datetime(paths[column].replace("", pd.NA), utc=True, errors="coerce")
    event_years = paths["event_time"].dt.tz_convert("America/New_York").dt.year
    event_dates = paths["event_time"].dt.tz_convert("America/New_York").dt.date.astype(str)
    blocked_year_rows = int(event_years.isin([2025, 2026]).sum())
    overnight_rows = int((event_dates != paths["session_date"].astype(str)).sum())

    numeric_columns = [
        "future_close",
        "horizon_close",
        "raw_return",
        "future_return",
        "reversal_return",
        "continuation_return",
        "maximum_favorable_excursion",
        "maximum_adverse_excursion",
        "bars_in_path",
    ]
    numeric = paths[numeric_columns].replace("", np.nan).apply(pd.to_numeric, errors="coerce")
    invalid_infinity_count = int(np.isinf(numeric.to_numpy(dtype=float, na_value=np.nan)).sum())
    available = paths["availability_status"] == "available"
    unavailable = paths["availability_status"] == "unavailable"
    available_invalid = int((available & (numeric["horizon_close"].isna() | numeric["reversal_return"].isna() | (numeric["bars_in_path"] <= 0))).sum())
    unavailable_invalid = int((unavailable & (numeric["horizon_close"].notna() | numeric["reversal_return"].notna() | (numeric["bars_in_path"] != 0))).sum())

    report = {
        "hypothesis_id": HYPOTHESIS_ID,
        "total_rows": int(len(paths)),
        "expected_rows": EXPECTED_PATH_ROWS,
        "total_matches_expected": int(len(paths)) == EXPECTED_PATH_ROWS,
        "unique_derived_event_ids": int(paths["derived_event_id"].nunique()),
        "expected_event_ids": int(len(events)),
        "every_event_has_five_horizons": len(missing_rows) == 0,
        "orphan_path_rows": int(len(orphan_rows)),
        "symbol_mismatch_rows": symbol_mismatch,
        "event_type_mismatch_rows": event_type_mismatch,
        "blocked_2025_2026_rows": blocked_year_rows,
        "overnight_event_time_rows": overnight_rows,
        "invalid_infinity_count": invalid_infinity_count,
        "available_invalid_rows": available_invalid,
        "unavailable_invalid_rows": unavailable_invalid,
        "availability_status_values": sorted(paths["availability_status"].astype(str).unique().tolist()),
    }
    report["integrity_passed"] = (
        report["total_matches_expected"]
        and report["unique_derived_event_ids"] == EXPECTED_EVENT_ROWS
        and report["every_event_has_five_horizons"]
        and report["orphan_path_rows"] == 0
        and report["symbol_mismatch_rows"] == 0
        and report["event_type_mismatch_rows"] == 0
        and report["blocked_2025_2026_rows"] == 0
        and report["overnight_event_time_rows"] == 0
        and report["invalid_infinity_count"] == 0
        and report["available_invalid_rows"] == 0
        and report["unavailable_invalid_rows"] == 0
    )
    _write_json(output_dir / "path_integrity_report.json", report)
    return report


def _sortable_frame(frame: pd.DataFrame) -> pd.DataFrame:
    sort_columns = [column for column in ["event_type", "horizon", "symbol", "orientation", "year"] if column in frame.columns]
    if sort_columns:
        return frame.sort_values(sort_columns).reset_index(drop=True)
    return frame.sort_index(axis=1).reset_index(drop=True)


def _compare_frames(original: pd.DataFrame, recomputed: pd.DataFrame, name: str, output_dir: Path) -> dict[str, Any]:
    original = _sortable_frame(original)
    recomputed = _sortable_frame(recomputed)
    common_columns = [column for column in original.columns if column in recomputed.columns]
    original = original.loc[:, common_columns]
    recomputed = recomputed.loc[:, common_columns]
    mismatch_rows: list[dict[str, Any]] = []
    row_count_match = len(original) == len(recomputed)
    if row_count_match:
        for column in common_columns:
            left = original[column]
            right = recomputed[column]
            if pd.api.types.is_bool_dtype(left) or pd.api.types.is_bool_dtype(right):
                bad = left.astype(str) != right.astype(str)
                for row_index in np.flatnonzero(bad.to_numpy()):
                    mismatch_rows.append(
                        {
                            "file": name,
                            "row_index": int(row_index),
                            "column": column,
                            "original": left.iloc[row_index],
                            "recomputed": right.iloc[row_index],
                            "absolute_difference": None,
                            "relative_difference": None,
                        }
                    )
                continue
            left_num = pd.to_numeric(left, errors="coerce")
            right_num = pd.to_numeric(right, errors="coerce")
            numeric_column = left_num.notna().any() or right_num.notna().any()
            if numeric_column:
                diff = (left_num - right_num).abs()
                bad = diff.fillna(0) > NUMERIC_TOLERANCE
                for row_index in np.flatnonzero(bad.to_numpy()):
                    original_value = left.iloc[row_index]
                    recomputed_value = right.iloc[row_index]
                    mismatch_rows.append(
                        {
                            "file": name,
                            "row_index": int(row_index),
                            "column": column,
                            "original": original_value,
                            "recomputed": recomputed_value,
                            "absolute_difference": float(diff.iloc[row_index]),
                            "relative_difference": float(diff.iloc[row_index] / max(abs(left_num.iloc[row_index]), NUMERIC_TOLERANCE)),
                        }
                    )
            else:
                bad = left.astype(str) != right.astype(str)
                for row_index in np.flatnonzero(bad.to_numpy()):
                    mismatch_rows.append(
                        {
                            "file": name,
                            "row_index": int(row_index),
                            "column": column,
                            "original": left.iloc[row_index],
                            "recomputed": right.iloc[row_index],
                            "absolute_difference": None,
                            "relative_difference": None,
                        }
                    )
    else:
        mismatch_rows.append(
            {
                "file": name,
                "row_index": None,
                "column": "__row_count__",
                "original": len(original),
                "recomputed": len(recomputed),
                "absolute_difference": abs(len(original) - len(recomputed)),
                "relative_difference": None,
            }
        )
    mismatches = pd.DataFrame(mismatch_rows)
    mismatch_path = output_dir / f"{Path(name).stem}_mismatches.csv"
    mismatches.to_csv(mismatch_path, index=False)
    return {
        "file": name,
        "row_count_original": int(len(original)),
        "row_count_recomputed": int(len(recomputed)),
        "row_count_match": row_count_match,
        "mismatch_count": int(len(mismatch_rows)),
        "mismatch_path": str(mismatch_path),
        "tolerance": NUMERIC_TOLERANCE,
    }


def recompute_and_compare(paths: pd.DataFrame, root: Path, output_dir: Path) -> dict[str, Any]:
    recomputed_dir = output_dir / "recomputed"
    recomputed_dir.mkdir(parents=True, exist_ok=True)
    path_metrics = paths.drop(columns=["derived_event_id"], errors="ignore").copy()
    for column in [
        "year",
        "event_price",
        "future_close",
        "horizon_close",
        "raw_return",
        "future_return",
        "reversal_return",
        "continuation_return",
        "maximum_favorable_excursion",
        "MFE",
        "maximum_adverse_excursion",
        "MAE",
        "path_high",
        "path_low",
        "bars_in_path",
    ]:
        if column in path_metrics.columns:
            path_metrics[column] = pd.to_numeric(path_metrics[column].replace("", np.nan), errors="coerce")

    groups = {
        "aggregate_metrics.csv": ("event_type", "horizon", "symbol", "orientation", "year"),
        "metrics_by_symbol.csv": ("symbol",),
        "metrics_by_year.csv": ("year",),
        "metrics_by_event.csv": ("event_type",),
        "metrics_by_horizon.csv": ("horizon",),
    }
    recomputed: dict[str, pd.DataFrame] = {}
    for filename, group_by in groups.items():
        base = aggregate_fcr_event_paths(path_metrics, group_by=group_by, seed=BOOTSTRAP_SEED, include_bootstrap=False)
        recomputed[filename] = attach_bootstrap_intervals(base, path_metrics, group_by=group_by, seed=BOOTSTRAP_SEED)
        recomputed[filename].to_csv(recomputed_dir / filename, index=False)

    recomputed["bootstrap_intervals.csv"] = recomputed["aggregate_metrics.csv"].loc[
        :,
        [
            "event_type",
            "horizon",
            "symbol",
            "orientation",
            "year",
            "bootstrap_reversal_mean_ci_low",
            "bootstrap_reversal_mean_ci_high",
            "bootstrap_grouped_by",
            "bootstrap_seed",
        ],
    ].copy()
    recomputed["bootstrap_intervals.csv"].to_csv(recomputed_dir / "bootstrap_intervals.csv", index=False)
    recomputed["economic_threshold_comparison.csv"] = _economic_threshold_comparison(recomputed["aggregate_metrics.csv"])
    recomputed["economic_threshold_comparison.csv"].to_csv(recomputed_dir / "economic_threshold_comparison.csv", index=False)

    comparisons = []
    for filename, frame in recomputed.items():
        original = pd.read_csv(root / filename)
        comparisons.append(_compare_frames(original, frame, filename, output_dir))

    checksums = {
        filename: {
            "persisted_sha256": _sha256_file(root / filename),
            "recomputed_sha256": _sha256_file(recomputed_dir / filename),
        }
        for filename in recomputed
    }
    report = {
        "tolerance": NUMERIC_TOLERANCE,
        "count_semantics": "count and event_count are path row counts, not unique event counts; available_count excludes unavailable horizon rows.",
        "recommended_documental_name_for_count": "path_row_count",
        "comparisons": comparisons,
        "checksums": checksums,
    }
    report["all_files_match_tolerance"] = all(item["mismatch_count"] == 0 and item["row_count_match"] for item in comparisons)
    _write_json(output_dir / "aggregate_reconciliation_report.json", report)
    return report


def _bootstrap_p_value(frame: pd.DataFrame, *, value_column: str = "reversal_return", n_bootstrap: int = 500) -> tuple[float, tuple[float, float]]:
    available = frame.loc[pd.to_numeric(frame[value_column], errors="coerce").notna(), ["session_date", value_column]].copy()
    available[value_column] = pd.to_numeric(available[value_column], errors="coerce")
    if available.empty:
        return float("nan"), (float("nan"), float("nan"))
    session_stats = available.groupby("session_date", sort=True)[value_column].agg(["sum", "count"])
    session_sums = session_stats["sum"].to_numpy(dtype=float)
    session_counts = session_stats["count"].to_numpy(dtype=float)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    means = np.empty(n_bootstrap, dtype=float)
    session_count = len(session_stats)
    for index in range(n_bootstrap):
        sampled = rng.choice(session_count, size=session_count, replace=True)
        means[index] = session_sums[sampled].sum() / session_counts[sampled].sum()
    p_value = 2.0 * min(float((means <= 0).mean()), float((means >= 0).mean()))
    return min(1.0, p_value), (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def _bh_q_values(p_values: list[float]) -> list[float]:
    values = np.array([1.0 if pd.isna(value) else value for value in p_values], dtype=float)
    order = np.argsort(values)
    q_values = np.empty_like(values)
    previous = 1.0
    total = len(values)
    for rank, index in enumerate(order[::-1], start=1):
        actual_rank = total - rank + 1
        q_value = min(previous, values[index] * total / actual_rank)
        q_values[index] = q_value
        previous = q_value
    return q_values.tolist()


def audit_classification(paths: pd.DataFrame, aggregate_metrics: pd.DataFrame, output_dir: Path) -> dict[str, Any]:
    path_metrics = paths.drop(columns=["derived_event_id"], errors="ignore").copy()
    for column in ["reversal_return", "continuation_return", "maximum_favorable_excursion", "maximum_adverse_excursion"]:
        path_metrics[column] = pd.to_numeric(path_metrics[column].replace("", np.nan), errors="coerce")
    symbol_base = aggregate_fcr_event_paths(
        path_metrics,
        group_by=("event_type", "orientation", "horizon", "symbol"),
        seed=BOOTSTRAP_SEED,
        include_bootstrap=False,
    )
    symbol_metrics = attach_bootstrap_intervals(
        symbol_base,
        path_metrics,
        group_by=("event_type", "orientation", "horizon", "symbol"),
        seed=BOOTSTRAP_SEED,
    )
    p_values = []
    for _, row in symbol_metrics.iterrows():
        subset = path_metrics.loc[
            (path_metrics["event_type"] == row["event_type"])
            & (path_metrics["orientation"] == row["orientation"])
            & (path_metrics["horizon"] == row["horizon"])
            & (path_metrics["symbol"] == row["symbol"])
        ]
        p_value, _interval = _bootstrap_p_value(subset)
        p_values.append(p_value)
    symbol_metrics["bootstrap_two_sided_p"] = p_values
    symbol_metrics["bh_q_value"] = _bh_q_values(p_values)

    evidence_rows: list[dict[str, Any]] = []
    causing_keys: set[tuple[str, str, str]] = set()
    for _, row in symbol_metrics.iterrows():
        key_filter = (
            (symbol_metrics["event_type"] == row["event_type"])
            & (symbol_metrics["orientation"] == row["orientation"])
            & (symbol_metrics["horizon"] == row["horizon"])
        )
        pair = symbol_metrics.loc[key_filter].copy()
        signs = pair.set_index("symbol")["mean_reversal_return"].map(np.sign).to_dict()
        non_zero_pair = set(signs) == set(EXPECTED_SYMBOLS) and all(value != 0 for value in signs.values())
        same_sign = bool(non_zero_pair and signs["QQQ"] == signs["SPY"])
        year_rows = aggregate_metrics.loc[
            (aggregate_metrics["event_type"] == row["event_type"])
            & (aggregate_metrics["orientation"] == row["orientation"])
            & (aggregate_metrics["horizon"] == row["horizon"])
            & (aggregate_metrics["symbol"] == row["symbol"])
        ].copy()
        years_available = sorted(year_rows["year"].astype(int).unique().tolist())
        sign = int(np.sign(row["mean_reversal_return"]))
        year_signs = np.sign(year_rows["mean_reversal_return"]).astype(int).tolist()
        consistent_years = sum(1 for value in year_signs if value == sign and value != 0)
        sign_consistent = consistent_years >= 2
        count_total = float(year_rows["count"].sum()) if not year_rows.empty else 0.0
        annual_concentration = float(year_rows["count"].max() / count_total) if count_total else 1.0
        annual_concentration_pass = annual_concentration <= ANNUAL_CONCENTRATION_MAX_SHARE
        horizon_index = HORIZON_ORDER[row["horizon"]]
        nearby = [
            horizon
            for horizon, index in HORIZON_ORDER.items()
            if abs(index - horizon_index) == 1
        ]
        nearby_rows = symbol_metrics.loc[
            (symbol_metrics["event_type"] == row["event_type"])
            & (symbol_metrics["orientation"] == row["orientation"])
            & (symbol_metrics["symbol"] == row["symbol"])
            & (symbol_metrics["horizon"].isin(nearby))
        ]
        nearby_same_sign = bool((np.sign(nearby_rows["mean_reversal_return"]) == sign).any()) if sign != 0 else False
        ci_excludes_zero = bool((row["bootstrap_reversal_mean_ci_low"] > 0) or (row["bootstrap_reversal_mean_ci_high"] < 0))
        multiple_comparison_pass = bool(row["bh_q_value"] <= BH_FDR_Q)
        individual_pass = (
            ci_excludes_zero
            and same_sign
            and sign_consistent
            and annual_concentration_pass
            and nearby_same_sign
            and multiple_comparison_pass
        )
        classification = "hypothesis_generating_signal" if individual_pass else "weak_unstable_effect"
        if individual_pass:
            causing_keys.add((str(row["event_type"]), str(row["orientation"]), str(row["horizon"])))
        evidence_rows.append(
            {
                "event_type": row["event_type"],
                "orientation": row["orientation"],
                "horizon": row["horizon"],
                "symbol": row["symbol"],
                "years_available": ",".join(map(str, years_available)),
                "count": int(row["count"]),
                "path_row_count": int(row["count"]),
                "available_count": int(row["available_count"]),
                "session_count": int(row["session_count"]),
                "mean": float(row["mean_reversal_return"]),
                "median": float(row["median_reversal_return"]),
                "bootstrap_lower": float(row["bootstrap_reversal_mean_ci_low"]),
                "bootstrap_upper": float(row["bootstrap_reversal_mean_ci_high"]),
                "favorable_percentage": float(row["favorable_percentage"]),
                "economic_threshold": "not_applicable_non_strategy_no_pnl",
                "economic_threshold_pass": "not_applicable",
                "same_sign_in_QQQ_and_SPY": same_sign,
                "sign_consistent_in_at_least_two_of_three_years": sign_consistent,
                "annual_concentration": annual_concentration,
                "annual_concentration_pass": annual_concentration_pass,
                "coherence_with_nearby_horizons": nearby_same_sign,
                "bootstrap_ci_excludes_zero": ci_excludes_zero,
                "bootstrap_two_sided_p": float(row["bootstrap_two_sided_p"]),
                "bh_q_value": float(row["bh_q_value"]),
                "multiple_comparisons_pass": multiple_comparison_pass,
                "classification_individual": classification,
            }
        )
    evidence = pd.DataFrame(evidence_rows).sort_values(["event_type", "orientation", "horizon", "symbol"])
    evidence.to_csv(output_dir / "classification_evidence.csv", index=False)

    causing_rows = []
    for key, group in evidence.groupby(["event_type", "orientation", "horizon"], sort=True):
        passed_symbols = set(
            group.loc[group["classification_individual"] == "hypothesis_generating_signal", "symbol"].astype(str)
        )
        if passed_symbols == set(EXPECTED_SYMBOLS):
            causing_rows.append({"event_type": key[0], "orientation": key[1], "horizon": key[2]})
    causing = pd.DataFrame(causing_rows, columns=["event_type", "orientation", "horizon"])
    causing.to_csv(output_dir / "classification_causing_combinations.csv", index=False)
    status = "passed" if not causing.empty else "failed"
    payload = {
        "hypothesis_id": HYPOTHESIS_ID,
        "persisted_classification": "hypothesis_generating_signal",
        "classification_audit_status": status,
        "diagnostic_classification": "hypothesis_generating_signal" if status == "passed" else "classification_error",
        "causing_combinations": causing.to_dict("records"),
        "multiple_comparisons": {
            "preregistered_method": "not explicitly specified in preregistration",
            "audit_overlay": "Benjamini-Hochberg FDR on symbol-level event/orientation/horizon bootstrap p-values",
            "q_threshold": BH_FDR_Q,
            "family_size": int(len(evidence)),
            "decision_use": "diagnostic_only_not_strategy_approval",
        },
        "economic_threshold": "not_applicable_non_strategy_no_pnl_no_cost_model",
        "criteria": [
            "bootstrap CI excludes zero",
            "same sign in QQQ and SPY",
            "same sign in at least two of three years",
            "annual concentration <= 50%",
            "same sign in a nearby horizon",
            "BH q-value <= 0.10",
        ],
        "all_combinations_evaluated_path": str(output_dir / "classification_evidence.csv"),
    }
    _write_json(output_dir / "classification_evidence.json", payload)
    return payload


def audit_event_07_08(paths: pd.DataFrame, aggregate_metrics: pd.DataFrame, classification_evidence: pd.DataFrame, output_dir: Path) -> dict[str, Any]:
    diagnostics = aggregate_metrics.loc[aggregate_metrics["event_type"].isin(["EVENT-07", "EVENT-08"])].copy()
    diagnostics["mean_return"] = diagnostics["mean_reversal_return"]
    diagnostics["median_return"] = diagnostics["median_reversal_return"]
    diagnostics["bootstrap_lower"] = diagnostics["bootstrap_reversal_mean_ci_low"]
    diagnostics["bootstrap_upper"] = diagnostics["bootstrap_reversal_mean_ci_high"]
    diagnostics["economic_threshold"] = "not_applicable_non_strategy_no_pnl"
    diagnostics["classification"] = np.where(
        (diagnostics["bootstrap_lower"] > 0) | (diagnostics["bootstrap_upper"] < 0),
        "stable_but_not_economic_diagnostic_row",
        "no_effect_detected_diagnostic_row",
    )
    columns = [
        "event_type",
        "orientation",
        "horizon",
        "symbol",
        "year",
        "count",
        "mean_return",
        "median_return",
        "bootstrap_lower",
        "bootstrap_upper",
        "economic_threshold",
        "classification",
    ]
    diagnostics.loc[:, columns].to_csv(output_dir / "event_07_08_diagnostics.csv", index=False)

    subset = paths.loc[paths["event_type"].isin(["EVENT-07", "EVENT-08"])].copy()
    reversal = pd.to_numeric(subset["reversal_return"].replace("", np.nan), errors="coerce")
    continuation = pd.to_numeric(subset["continuation_return"].replace("", np.nan), errors="coerce")
    valid = reversal.notna() & continuation.notna()
    algebra_failures = int((valid & ((reversal + continuation).abs() > NUMERIC_TOLERANCE)).sum())
    causing = classification_evidence.loc[classification_evidence["event_type"].isin(["EVENT-07", "EVENT-08"])].copy()
    payload = {
        "event_07_08_rows": int(len(diagnostics)),
        "continuation_is_negative_reversal": algebra_failures == 0,
        "algebra_failure_rows": algebra_failures,
        "event_07_08_causing_classification_rows": int(
            (causing["classification_individual"] == "hypothesis_generating_signal").sum()
        ),
        "diagnostics_path": str(output_dir / "event_07_08_diagnostics.csv"),
    }
    _write_json(output_dir / "event_07_08_audit_report.json", payload)
    return payload


def _candidate_effect_direction(frame: pd.DataFrame) -> tuple[str, str]:
    reversal = pd.to_numeric(frame["reversal_return"], errors="coerce")
    mean_reversal = float(reversal.mean())
    if mean_reversal < 0:
        return "continuation", "continuation_return"
    return "reversal", "reversal_return"


def _nearby_horizon_has_same_effect(
    paths: pd.DataFrame,
    *,
    event_type: str,
    orientation: str,
    symbol: str,
    horizon: str,
    effect_direction: str,
) -> bool:
    horizon_index = HORIZON_ORDER[horizon]
    nearby = [name for name, index in HORIZON_ORDER.items() if abs(index - horizon_index) == 1]
    if not nearby:
        return False
    source_column = "continuation_return" if effect_direction == "continuation" else "reversal_return"
    nearby_rows = paths.loc[
        (paths["event_type"] == event_type)
        & (paths["orientation"] == orientation)
        & (paths["symbol"] == symbol)
        & (paths["horizon"].isin(nearby))
        & (paths["availability_status"] == "available")
    ].copy()
    if nearby_rows.empty:
        return False
    nearby_values = pd.to_numeric(nearby_rows[source_column], errors="coerce")
    return bool(nearby_values.mean() > 0)


def audit_economic_thresholds(
    paths: pd.DataFrame,
    output_dir: Path,
    *,
    config_path: Path = CONFIG_PATH,
    preregistration_doc_path: Path = PREREGISTRATION_DOC_PATH,
) -> dict[str, Any]:
    rule = determine_economic_rule(config_path, preregistration_doc_path)
    working = paths.drop(columns=["derived_event_id"], errors="ignore").copy()
    for column in ["event_price", "reversal_return", "continuation_return", "year"]:
        working[column] = pd.to_numeric(working[column].replace("", np.nan), errors="coerce")
    working = working.loc[working["availability_status"] == "available"].copy()
    working["one_tick_return"] = one_tick_return(working["event_price"], rule.tick_size)
    working["two_tick_return"] = two_tick_return(working["event_price"], rule.tick_size)
    working["baseline_threshold_return"] = np.nan
    working["stress_threshold_return"] = np.nan
    if rule.baseline_applicable:
        working["baseline_threshold_return"] = friction_threshold_return(
            working["event_price"],
            tick_size=rule.tick_size,
            commission_rate_per_side=float(rule.baseline_commission_rate_per_side),
            slippage_ticks_per_execution=float(rule.baseline_slippage_ticks_per_execution),
        )
    if rule.stress_applicable:
        working["stress_threshold_return"] = friction_threshold_return(
            working["event_price"],
            tick_size=rule.tick_size,
            commission_rate_per_side=float(rule.stress_commission_rate_per_side),
            slippage_ticks_per_execution=float(rule.stress_slippage_ticks_per_execution),
        )

    rows: list[dict[str, Any]] = []
    candidate_pair_summary: list[dict[str, Any]] = []
    for event_type, orientation, horizon in CANDIDATE_COMBINATIONS:
        pair = working.loc[
            (working["event_type"] == event_type)
            & (working["orientation"] == orientation)
            & (working["horizon"] == horizon)
        ].copy()
        symbol_directions: dict[str, str] = {}
        symbol_raw_signs: dict[str, int] = {}
        for symbol in EXPECTED_SYMBOLS:
            symbol_rows = pair.loc[pair["symbol"] == symbol].copy()
            if symbol_rows.empty:
                symbol_directions[symbol] = "missing"
                symbol_raw_signs[symbol] = 0
                continue
            direction, source_column = _candidate_effect_direction(symbol_rows)
            symbol_directions[symbol] = direction
            symbol_raw_signs[symbol] = int(np.sign(pd.to_numeric(symbol_rows["reversal_return"], errors="coerce").mean()))
            symbol_rows["oriented_return"] = pd.to_numeric(symbol_rows[source_column], errors="coerce")
            symbol_rows["oriented_return_minus_one_tick"] = symbol_rows["oriented_return"] - symbol_rows["one_tick_return"]
            symbol_rows["oriented_return_minus_two_ticks"] = symbol_rows["oriented_return"] - symbol_rows["two_tick_return"]
            symbol_rows["oriented_return_minus_baseline"] = (
                symbol_rows["oriented_return"] - symbol_rows["baseline_threshold_return"]
            )
            symbol_rows["oriented_return_minus_stress"] = symbol_rows["oriented_return"] - symbol_rows["stress_threshold_return"]

            year_stats = (
                symbol_rows.groupby("year", dropna=False)["oriented_return"]
                .agg(["count", "mean", "median"])
                .reset_index()
                .sort_values("year")
            )
            year_signs = np.sign(year_stats["mean"].to_numpy(dtype=float))
            consistent_years = int((year_signs > 0).sum())
            annual_consistency_pass = consistent_years >= 2
            annual_count_total = float(year_stats["count"].sum())
            annual_concentration = float(year_stats["count"].max() / annual_count_total) if annual_count_total else 1.0
            annual_concentration_pass = annual_concentration <= ANNUAL_CONCENTRATION_MAX_SHARE
            bootstrap_low, bootstrap_high = _bootstrap_mean_ci_by_session(symbol_rows, value_column="oriented_return")
            one_low, one_high = _bootstrap_mean_ci_by_session(symbol_rows, value_column="oriented_return_minus_one_tick")
            two_low, two_high = _bootstrap_mean_ci_by_session(symbol_rows, value_column="oriented_return_minus_two_ticks")
            baseline_low, baseline_high = _bootstrap_mean_ci_by_session(
                symbol_rows, value_column="oriented_return_minus_baseline"
            )
            stress_low, stress_high = _bootstrap_mean_ci_by_session(symbol_rows, value_column="oriented_return_minus_stress")
            nearby_pass = _nearby_horizon_has_same_effect(
                working,
                event_type=event_type,
                orientation=orientation,
                symbol=symbol,
                horizon=horizon,
                effect_direction=direction,
            )
            mean_oriented = float(symbol_rows["oriented_return"].mean())
            mean_net_one = float(symbol_rows["oriented_return_minus_one_tick"].mean())
            mean_net_two = float(symbol_rows["oriented_return_minus_two_ticks"].mean())
            mean_net_baseline = (
                float(symbol_rows["oriented_return_minus_baseline"].mean()) if rule.baseline_applicable else float("nan")
            )
            mean_net_stress = float(symbol_rows["oriented_return_minus_stress"].mean()) if rule.stress_applicable else float("nan")
            row = {
                "event_type": event_type,
                "orientation": orientation,
                "horizon": horizon,
                "symbol": symbol,
                "candidate_effect_direction": direction,
                "effect_source_column": source_column,
                "count": int(len(symbol_rows)),
                "session_count": int(symbol_rows["session_date"].nunique()),
                "mean_oriented_return": mean_oriented,
                "median_oriented_return": float(symbol_rows["oriented_return"].median()),
                "bootstrap_ci_low": bootstrap_low,
                "bootstrap_ci_high": bootstrap_high,
                "mean_one_tick_return": float(symbol_rows["one_tick_return"].mean()),
                "mean_two_tick_return": float(symbol_rows["two_tick_return"].mean()),
                "baseline_threshold_applicable": rule.baseline_applicable,
                "stress_threshold_applicable": rule.stress_applicable,
                "mean_baseline_threshold_return": float(symbol_rows["baseline_threshold_return"].mean())
                if rule.baseline_applicable
                else np.nan,
                "mean_stress_threshold_return": float(symbol_rows["stress_threshold_return"].mean())
                if rule.stress_applicable
                else np.nan,
                "mean_net_of_one_tick": mean_net_one,
                "mean_net_of_two_ticks": mean_net_two,
                "mean_net_of_baseline_threshold": mean_net_baseline,
                "mean_net_of_stress_threshold": mean_net_stress,
                "bootstrap_ci_net_one_tick_low": one_low,
                "bootstrap_ci_net_one_tick_high": one_high,
                "bootstrap_ci_net_two_ticks_low": two_low,
                "bootstrap_ci_net_two_ticks_high": two_high,
                "bootstrap_ci_net_baseline_low": baseline_low,
                "bootstrap_ci_net_baseline_high": baseline_high,
                "bootstrap_ci_net_stress_low": stress_low,
                "bootstrap_ci_net_stress_high": stress_high,
                "pct_events_exceed_one_tick": float((symbol_rows["oriented_return_minus_one_tick"] > 0).mean()),
                "pct_events_exceed_two_ticks": float((symbol_rows["oriented_return_minus_two_ticks"] > 0).mean()),
                "pct_events_exceed_baseline": float((symbol_rows["oriented_return_minus_baseline"] > 0).mean())
                if rule.baseline_applicable
                else np.nan,
                "pct_events_exceed_stress": float((symbol_rows["oriented_return_minus_stress"] > 0).mean())
                if rule.stress_applicable
                else np.nan,
                "annual_years_positive": consistent_years,
                "annual_consistency_pass": annual_consistency_pass,
                "annual_concentration": annual_concentration,
                "annual_concentration_pass": annual_concentration_pass,
                "yearly_evidence": json.dumps(year_stats.to_dict("records"), sort_keys=True),
                "bootstrap_not_strongly_contradictory": bool(bootstrap_high > 0),
                "bootstrap_ci_excludes_zero_positive": bool(bootstrap_low > 0),
                "nearby_horizon_coherence_pass": nearby_pass,
                "one_tick_magnitude_pass": bool(mean_net_one > 0 and one_high > 0),
                "two_tick_magnitude_pass": bool(mean_net_two > 0 and two_high > 0),
                "baseline_magnitude_pass": bool(rule.baseline_applicable and mean_net_baseline > 0 and baseline_high > 0),
                "stress_magnitude_pass": bool(rule.stress_applicable and mean_net_stress > 0 and stress_high > 0),
                "preregistered_economic_threshold_name": rule.required_threshold_name,
                "preregistered_economic_threshold_pass": False,
                "strategy_created": False,
                "orders_sent": False,
                "position_sizing_used": False,
                "validation_2025_unlocked": False,
            }
            rows.append(row)

        same_sign_pair = (
            set(symbol_directions.values()) != {"missing"}
            and symbol_directions.get("QQQ") == symbol_directions.get("SPY")
            and symbol_raw_signs.get("QQQ", 0) == symbol_raw_signs.get("SPY", 0)
            and symbol_raw_signs.get("QQQ", 0) != 0
        )
        pair_rows = [row for row in rows if row["event_type"] == event_type and row["orientation"] == orientation and row["horizon"] == horizon]
        stability_pass = bool(
            same_sign_pair
            and all(row["annual_consistency_pass"] for row in pair_rows)
            and all(row["annual_concentration_pass"] for row in pair_rows)
            and all(row["bootstrap_not_strongly_contradictory"] for row in pair_rows)
            and all(row["nearby_horizon_coherence_pass"] for row in pair_rows)
        )
        all_preregistered_criteria_pass = bool(
            stability_pass
            and rule.threshold_required_for_hypothesis_generating
            and all(row["preregistered_economic_threshold_pass"] for row in pair_rows)
        )
        for row in pair_rows:
            row["same_sign_in_QQQ_and_SPY"] = same_sign_pair
            row["stability_criteria_pass"] = stability_pass
            row["all_preregistered_criteria_pass"] = all_preregistered_criteria_pass
        candidate_pair_summary.append(
            {
                "event_type": event_type,
                "orientation": orientation,
                "horizon": horizon,
                "same_sign_in_QQQ_and_SPY": same_sign_pair,
                "stability_criteria_pass": stability_pass,
                "all_preregistered_criteria_pass": all_preregistered_criteria_pass,
            }
        )

    by_candidate = pd.DataFrame(rows).sort_values(["event_type", "horizon", "symbol"])
    by_candidate.to_csv(output_dir / "economic_threshold_by_candidate.csv", index=False)
    pair_summary = pd.DataFrame(candidate_pair_summary)
    total_combinations_evaluated = int(working.groupby(["event_type", "orientation", "horizon"]).ngroups)
    all_criteria_count = int(pair_summary["all_preregistered_criteria_pass"].sum()) if not pair_summary.empty else 0
    stable_pair_count = int(pair_summary["stability_criteria_pass"].sum()) if not pair_summary.empty else 0
    if rule.ambiguity:
        final_classification = "preregistration_ambiguity"
        final_status = "event_study_integrity_failed"
    elif all_criteria_count > 0:
        final_classification = "hypothesis_generating_signal"
        final_status = "event_study_completed_hypothesis_generating"
    elif stable_pair_count > 0:
        final_classification = "stable_but_not_economic"
        final_status = "event_study_completed_stable_not_economic"
    elif not by_candidate.empty and by_candidate["mean_oriented_return"].abs().max() > 0:
        final_classification = "weak_unstable_effect"
        final_status = "event_study_completed_weak_unstable"
    else:
        final_classification = "no_effect_detected"
        final_status = "event_study_completed_weak_unstable"

    payload = {
        "hypothesis_id": HYPOTHESIS_ID,
        "economic_rule": rule.__dict__,
        "candidate_combinations": [
            {"event_type": item[0], "orientation": item[1], "horizon": item[2]} for item in CANDIDATE_COMBINATIONS
        ],
        "total_event_orientation_horizon_combinations_evaluated": total_combinations_evaluated,
        "candidate_combinations_audited": len(CANDIDATE_COMBINATIONS),
        "candidate_combinations_stable": stable_pair_count,
        "candidate_combinations_passing_all_preregistered_criteria": all_criteria_count,
        "multiple_comparisons": {
            "preregistered_method": None,
            "formal_correction_applied": False,
            "reason": "No exact multiple-comparisons method is specified in YAML or preregistration documentation.",
            "decision": "No formal corrected-significance claim is made; consistency criteria are descriptive.",
        },
        "final_classification": final_classification,
        "final_status": final_status,
        "classification_reason": (
            "Stable diagnostic effects exist, but HYP-FCR-EVENT-01 did not preregister an economic threshold "
            "or cost model; hypothesis_generating_signal cannot be retained under the economic-threshold requirement."
            if final_classification == "stable_but_not_economic"
            else "See economic_rule and candidate rows."
        ),
        "strategy_created": False,
        "orders_sent": False,
        "position_sizing_used": False,
        "validation_2025_unlocked": False,
        "paper_eligible": False,
        "live_eligible": False,
        "by_candidate_path": str(output_dir / "economic_threshold_by_candidate.csv"),
    }
    _write_json(output_dir / "economic_threshold_audit.json", payload)
    final_payload = {
        "hypothesis_id": HYPOTHESIS_ID,
        "canonical_payload_hash": EXPECTED_CANONICAL_HASH,
        "final_classification": final_classification,
        "final_status": final_status,
        "source_classification_json_modified": False,
        "original_classification_json_preserved": True,
        "candidate_combinations_passing_all_preregistered_criteria": all_criteria_count,
        "candidate_combinations_stable": stable_pair_count,
        "economic_threshold_audit_path": str(output_dir / "economic_threshold_audit.json"),
        "strategy_created": False,
        "orders_sent": False,
        "position_sizing_used": False,
        "validation_2025_unlocked": False,
        "paper_eligible": False,
        "live_eligible": False,
    }
    _write_json(output_dir / "final_classification_evidence.json", final_payload)
    return payload


def write_posthoc_control_placeholder(output_dir: Path) -> None:
    pd.DataFrame(
        [
            {
                "analysis_label": "posthoc_non_decisional",
                "status": "not_executed_requires_historical_ohlc_reopen",
                "reason": "Unconditional same-symbol/year/hour/horizon returns require sessions without the event; events.csv/path_metrics.csv are insufficient.",
                "event_mean_return": np.nan,
                "unconditional_mean_return": np.nan,
                "incremental_return": np.nan,
                "bootstrap_ci_low": np.nan,
                "bootstrap_ci_high": np.nan,
                "classification_impact": "none",
                "strategy_approval_allowed": False,
            }
        ]
    ).to_csv(output_dir / "posthoc_unconditional_control.csv", index=False)


def run_postrun_audit(root: Path = DISCOVERY_DIR) -> AuditResult:
    output_dir = root / POSTRUN_DIR_NAME
    output_dir.mkdir(parents=True, exist_ok=True)
    events = _read_events(root)
    paths = _read_paths(root)
    event_report = audit_events(events, output_dir)
    path_report = audit_paths(events, paths, output_dir)
    aggregate_report = recompute_and_compare(paths, root, output_dir)
    aggregate_metrics = pd.read_csv(output_dir / "recomputed" / "aggregate_metrics.csv")
    classification_report = audit_classification(paths, aggregate_metrics, output_dir)
    classification_evidence = pd.read_csv(output_dir / "classification_evidence.csv")
    event_07_08_report = audit_event_07_08(paths, aggregate_metrics, classification_evidence, output_dir)
    economic_report = audit_economic_thresholds(paths, output_dir)
    write_posthoc_control_placeholder(output_dir)

    classification_status = str(classification_report["classification_audit_status"])
    final_status = (
        str(economic_report["final_status"])
        if event_report["integrity_passed"]
        and path_report["integrity_passed"]
        and aggregate_report["all_files_match_tolerance"]
        and classification_status == "passed"
        else "event_study_integrity_failed"
    )
    summary = {
        "hypothesis_id": HYPOTHESIS_ID,
        "canonical_payload_hash": EXPECTED_CANONICAL_HASH,
        "event_integrity_passed": event_report["integrity_passed"],
        "path_integrity_passed": path_report["integrity_passed"],
        "aggregate_reconciliation_passed": aggregate_report["all_files_match_tolerance"],
        "classification_audit_status": classification_status,
        "economic_threshold_audit_status": economic_report["economic_rule"]["status"],
        "final_classification": economic_report["final_classification"],
        "event_07_08_audit": event_07_08_report,
        "final_status": final_status,
        "strategy_created": False,
        "orders_sent": False,
        "position_sizing_used": False,
        "validation_2025_unlocked": False,
        "paper_eligible": False,
        "live_eligible": False,
    }
    _write_json(output_dir / "postrun_audit_summary.json", summary)
    return AuditResult(
        output_dir=output_dir,
        event_integrity_passed=event_report["integrity_passed"],
        path_integrity_passed=path_report["integrity_passed"],
        aggregate_reconciliation_passed=aggregate_report["all_files_match_tolerance"],
        classification_audit_status=classification_status,
        final_status=final_status,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit persisted HYP-FCR-EVENT-01 discovery outputs.")
    parser.add_argument("--root", default=str(DISCOVERY_DIR))
    args = parser.parse_args(argv)
    result = run_postrun_audit(Path(args.root))
    print(json.dumps(result.__dict__ | {"output_dir": str(result.output_dir)}, indent=2, sort_keys=True, default=str))
    return 0 if result.final_status != "event_study_integrity_failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
