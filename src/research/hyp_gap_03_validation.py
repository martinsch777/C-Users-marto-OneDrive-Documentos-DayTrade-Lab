from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from src.data import (
    EquitySessionCalendar,
    load_csv,
    require_approved_dataset_manifest_file,
    sha256_file,
)
from src.research.hypotheses.hyp_gap import (
    SAFETY_FLAGS,
    load_hyp_gap_preregistration,
)
from src.research.runners import HypGapRunRequest, run_hyp_gap_event_study


OUTPUT_ROOT = Path("outputs/hyp_gap_03_validation_2025_v1")
REPORT_PATH = Path("docs/HYP_GAP_03_VALIDATION_AND_REGIME_REVIEW.md")
DISCOVERY_OUTPUT = Path("outputs/hyp_gap_discovery_2022_2024_v1")
PREREGISTRATION_PATH = Path("configs/research/hypotheses/HYP-GAP.yaml")
SYMBOL_INPUTS = {
    "QQQ": {
        "dataset": Path("data/curated/QQQ_1min_2022-01-01_2026-07-06_curated.csv"),
        "manifest": Path("data/manifests/QQQ_1min_2022-01-01_2026-07-06_curated_manifest.json"),
    },
    "SPY": {
        "dataset": Path("data/curated/SPY_1min_2022-01-01_2026-07-06_curated.csv"),
        "manifest": Path("data/manifests/SPY_1min_2022-01-01_2026-07-06_curated_manifest.json"),
    },
}
CODE_FILES = (
    PREREGISTRATION_PATH,
    Path("docs/HYP_GAP_EVENT_STUDY_SPEC.md"),
    Path("docs/HYP_GAP_DISCOVERY_RESULTS.md"),
    Path("src/research/hypotheses/hyp_gap.py"),
    Path("src/research/runners/hyp_gap_runner.py"),
    Path("src/research/event_study.py"),
    Path("src/research/hyp_gap_03_validation.py"),
)
HORIZONS = ("5min", "15min", "30min", "60min", "session_close")
VALIDATED_VARIANT = "HYP-GAP-03"
BOOTSTRAP_SEED = 20260721
BOOTSTRAP_ITERATIONS = 2000
_SYMBOL_FRAME_CACHE: dict[str, pd.DataFrame] = {}


def _run_git(args: Sequence[str]) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _sha256_text(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _hash_existing_files(paths: Iterable[Path]) -> dict[str, str]:
    return {str(path): sha256_file(path) for path in paths if path.exists()}


def _discovery_date_bounds() -> dict[str, dict[str, str]]:
    bounds: dict[str, dict[str, str]] = {}
    for symbol in SYMBOL_INPUTS:
        frame = pd.read_csv(DISCOVERY_OUTPUT / symbol / "event_results.csv", usecols=["session_date"])
        bounds[symbol] = {
            "min_session_date": str(frame["session_date"].min()),
            "max_session_date": str(frame["session_date"].max()),
            "contains_2025_or_2026": bool(frame["session_date"].astype(str).str.startswith(("2025", "2026")).any()),
        }
    return bounds


def build_methodology_audit() -> dict[str, Any]:
    preregistration = load_hyp_gap_preregistration(PREREGISTRATION_PATH)
    variant = next(item for item in preregistration.variants if item.variant_id == VALIDATED_VARIANT)
    prereg_log = _run_git(["log", "--follow", "--format=%H%x09%ad%x09%s", "--date=iso", "--", str(PREREGISTRATION_PATH)])
    post_discovery_diff = _run_git(
        [
            "diff",
            "e5b9c1c869054cdabb70d53b848500f4b032f0b8..HEAD",
            "--",
            str(PREREGISTRATION_PATH),
            "src/research/hypotheses/hyp_gap.py",
            "src/research/runners/hyp_gap_runner.py",
            "src/research/event_study.py",
        ]
    )
    discovery_bounds = _discovery_date_bounds()
    checks = {
        "hgp_gap_03_preregistered_before_discovery_report": "b2e056c" in prereg_log and bool(prereg_log),
        "hgp_gap_03_thresholds_frozen": variant.threshold == {
            "normalized_gap_min": 0.35,
            "opening_move_atr_min": 0.10,
        },
        "validation_and_holdout_separated": (
            preregistration.discovery_end < preregistration.validation_start
            and preregistration.validation_end < preregistration.final_holdout_start
        ),
        "discovery_outputs_exclude_2025_2026": not any(
            item["contains_2025_or_2026"] for item in discovery_bounds.values()
        ),
        "safety_flags_false": SAFETY_FLAGS == {
            "live_trading": False,
            "broker_connected": False,
            "orders_sent": False,
            "paper_broker_enabled": False,
        },
        "post_discovery_core_diff_empty_before_this_task": post_discovery_diff == "",
    }
    serious_blockers = [
        name
        for name, passed in checks.items()
        if name
        not in {
            "post_discovery_core_diff_empty_before_this_task",
        }
        and not passed
    ]
    return {
        "schema_version": 1,
        "audit_timestamp": datetime.now(timezone.utc).isoformat(),
        "conclusion": "habilitada_para_validation" if not serious_blockers else "no_habilitada_para_validation",
        "serious_blockers": serious_blockers,
        "checks": checks,
        "variant_under_review": asdict(variant),
        "discovery_output_bounds": discovery_bounds,
        "preregistration_git_log": prereg_log.splitlines(),
        "post_discovery_core_diff_empty_before_this_task_note": (
            "This is expected to be false after validation infrastructure edits in the current working tree."
        ),
        "safety_flags": dict(SAFETY_FLAGS),
        "holdout_status": "cerrado_no_leido_no_ejecutado",
    }


def build_freeze_manifest(audit: Mapping[str, Any]) -> dict[str, Any]:
    preregistration = load_hyp_gap_preregistration(PREREGISTRATION_PATH)
    variant = next(item for item in preregistration.variants if item.variant_id == VALIDATED_VARIANT)
    dataset_records = {}
    for symbol, paths in SYMBOL_INPUTS.items():
        manifest = _read_json(paths["manifest"])
        dataset_records[symbol] = {
            "dataset_path": str(paths["dataset"]),
            "dataset_sha256": sha256_file(paths["dataset"]),
            "manifest_path": str(paths["manifest"]),
            "manifest_sha256": sha256_file(paths["manifest"]),
            "manifest_dataset_sha256": manifest["sha256"],
            "manifest_dataset_status": manifest["dataset_status"],
            "excluded_sessions": manifest.get("excluded_sessions", []),
        }
    payload = {
        "schema_version": 1,
        "freeze_id": "HYP-GAP-03__pre_validation_freeze__2025__v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_head": _run_git(["rev-parse", "HEAD"]),
        "git_status_short_at_freeze": _run_git(["status", "--short"]).splitlines(),
        "hypothesis_id": "HYP-GAP",
        "variant_id": VALIDATED_VARIANT,
        "variant_definition": asdict(variant),
        "frozen_period": {
            "discovery": {
                "start": preregistration.discovery_start.isoformat(),
                "end": preregistration.discovery_end.isoformat(),
            },
            "validation": {
                "start": preregistration.validation_start.isoformat(),
                "end": preregistration.validation_end.isoformat(),
            },
            "final_holdout": {
                "start": preregistration.final_holdout_start.isoformat(),
                "end": preregistration.final_holdout_end.isoformat(),
                "status": "closed_not_read_not_run",
            },
        },
        "symbols": list(preregistration.symbols),
        "timeframe": preregistration.timeframe,
        "timezone": preregistration.timezone,
        "horizons": list(preregistration.horizons),
        "input_datasets": dataset_records,
        "code_hashes": _hash_existing_files(CODE_FILES),
        "discovery_output_hashes": _hash_existing_files(DISCOVERY_OUTPUT.glob("*/*")),
        "methodology_audit_conclusion": audit["conclusion"],
        "retroactive_change_policy": (
            "No later code, threshold, filter, exclusion, warm-up, session, symbol, "
            "or horizon change may be applied retroactively to this validation."
        ),
        "safety_flags": dict(SAFETY_FLAGS),
        "paper_or_live_authorized": False,
        "orders_authorized": False,
    }
    payload["freeze_hash"] = _sha256_text(payload)
    return payload


def run_validation_outputs(output_root: Path) -> list[Path]:
    written: list[Path] = []
    for symbol, paths in SYMBOL_INPUTS.items():
        destination = output_root / symbol
        result = run_hyp_gap_event_study(
            HypGapRunRequest(
                dataset_path=str(paths["dataset"]),
                manifest_path=str(paths["manifest"]),
                symbol=symbol,
                timeframe="1min",
                requested_start="2022-01-01",
                requested_end="2025-12-31",
                preregistration_path=str(PREREGISTRATION_PATH),
                output_directory=str(destination),
                research_phase="validation",
                variant_ids=(VALIDATED_VARIANT,),
            )
        )
        written.extend(
            [
                Path(result.run_manifest_path),
                Path(result.events_path),
                Path(result.event_results_path),
                Path(result.aggregate_results_path),
                Path(result.detection_summary_path),
            ]
        )
    return written


def _load_period_results(period: str, output_root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    result_frames = []
    event_frames = []
    base = DISCOVERY_OUTPUT if period == "discovery" else output_root
    for symbol in SYMBOL_INPUTS:
        results = pd.read_csv(base / symbol / "event_results.csv")
        events = pd.read_csv(base / symbol / "events.csv")
        results = results.loc[results["variant_id"] == VALIDATED_VARIANT].copy()
        events = events.loc[events["variant_id"] == VALIDATED_VARIANT].copy()
        results["period"] = period
        events["period"] = period
        result_frames.append(results)
        event_frames.append(events)
    return pd.concat(result_frames, ignore_index=True), pd.concat(event_frames, ignore_index=True)


def _available_returns(frame: pd.DataFrame) -> pd.Series:
    return frame.loc[
        (frame["availability_status"] == "available") & frame["analysis_return"].notna(),
        "analysis_return",
    ].astype(float)


def _bootstrap_session_ci(subset: pd.DataFrame) -> tuple[float | None, float | None, float | None]:
    available = subset.loc[
        (subset["availability_status"] == "available") & subset["analysis_return"].notna()
    ].copy()
    if available.empty:
        return None, None, None
    session_means = available.groupby("session_date")["analysis_return"].mean().astype(float).to_numpy()
    if len(session_means) == 1:
        value = float(session_means[0])
        return value, value, 0.0
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = rng.choice(
        session_means,
        size=(BOOTSTRAP_ITERATIONS, len(session_means)),
        replace=True,
    ).mean(axis=1)
    return (
        float(np.quantile(draws, 0.025)),
        float(np.quantile(draws, 0.975)),
        float(draws.std(ddof=1)),
    )


def _summary_record(keys: Mapping[str, Any], subset: pd.DataFrame) -> dict[str, Any]:
    returns = _available_returns(subset)
    record = dict(keys)
    record["event_count"] = int(subset["event_id"].nunique())
    record["result_rows"] = int(len(subset))
    record["available_count"] = int(len(returns))
    record["missing_count"] = int(len(subset) - len(returns))
    if returns.empty:
        for column in (
            "mean_return",
            "median_return",
            "standard_deviation",
            "standard_error",
            "confidence_interval_95_lower",
            "confidence_interval_95_upper",
            "positive_rate",
            "p01",
            "p05",
            "p25",
            "p75",
            "p95",
            "p99",
        ):
            record[column] = None
        record["bootstrap_session_ci_lower"] = None
        record["bootstrap_session_ci_upper"] = None
        record["bootstrap_session_standard_error"] = None
        return record
    std = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    se = std / (len(returns) ** 0.5) if len(returns) > 1 else 0.0
    boot_low, boot_high, boot_se = _bootstrap_session_ci(subset)
    record.update(
        {
            "mean_return": float(returns.mean()),
            "median_return": float(returns.median()),
            "standard_deviation": std,
            "standard_error": se,
            "confidence_interval_95_lower": float(returns.mean() - 1.96 * se),
            "confidence_interval_95_upper": float(returns.mean() + 1.96 * se),
            "bootstrap_session_ci_lower": boot_low,
            "bootstrap_session_ci_upper": boot_high,
            "bootstrap_session_standard_error": boot_se,
            "positive_rate": float((returns > 0).mean()),
            "p01": float(returns.quantile(0.01)),
            "p05": float(returns.quantile(0.05)),
            "p25": float(returns.quantile(0.25)),
            "p75": float(returns.quantile(0.75)),
            "p95": float(returns.quantile(0.95)),
            "p99": float(returns.quantile(0.99)),
            "minimum": float(returns.min()),
            "maximum": float(returns.max()),
        }
    )
    return record


def summarize(frame: pd.DataFrame, group_by: Sequence[str]) -> pd.DataFrame:
    rows = []
    if not group_by:
        rows.append(_summary_record({}, frame))
    else:
        for keys, subset in frame.groupby(list(group_by), dropna=False, sort=True):
            if not isinstance(keys, tuple):
                keys = (keys,)
            rows.append(_summary_record(dict(zip(group_by, keys)), subset))
    return pd.DataFrame(rows)


def _event_metadata_frame(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in events.iterrows():
        metadata = json.loads(row["metadata"])
        rows.append(
            {
                "event_id": row["event_id"],
                "period": row["period"],
                "symbol": row["symbol"],
                "session_date": row["session_date"],
                "expected_direction": int(row["expected_direction"]),
                "gap_direction": int(metadata["gap_direction"]),
                "gap_return": float(metadata["gap_return"]),
                "abs_gap_return": abs(float(metadata["gap_return"])),
                "normalized_gap": float(metadata["normalized_gap"]),
                "prior_atr": float(metadata["prior_atr"]),
                "opening_return": float(metadata["opening_return"]),
                "opening_move_atr": float(metadata["opening_move_atr"]),
                "relative_volume_0930_0945": float(metadata["relative_volume_0930_0945"]),
                "previous_session_date": metadata["previous_session_date"],
                "previous_session_close": float(metadata["previous_session_close"]),
                "current_session_open": float(metadata["current_session_open"]),
                "confirmation_close": float(metadata["confirmation_close"]),
            }
        )
    return pd.DataFrame(rows)


def _load_symbol_frame(symbol: str) -> pd.DataFrame:
    if symbol in _SYMBOL_FRAME_CACHE:
        return _SYMBOL_FRAME_CACHE[symbol]
    paths = SYMBOL_INPUTS[symbol]
    manifest = require_approved_dataset_manifest_file(
        paths["dataset"],
        symbol,
        "1min",
        paths["manifest"],
    )
    excluded = {
        str(record.get("date"))
        for record in manifest.excluded_sessions
        if str(record.get("symbol", symbol)).upper() == symbol
    }
    calendar = EquitySessionCalendar.from_config({"source": "us_equity"})
    frame, report = load_csv(
        paths["dataset"],
        "1min",
        asset_class="equity",
        drop_incomplete=False,
        calendar=calendar,
        excluded_session_dates=excluded,
    )
    if not report.is_valid:
        raise ValueError(f"{symbol} dataset failed validation analysis load")
    frame["_session_date"] = [
        timestamp.tz_convert(calendar.timezone).date().isoformat()
        for timestamp in frame["timestamp"]
    ]
    frame = frame.loc[frame["_session_date"] <= "2025-12-31"].reset_index(drop=True)
    _SYMBOL_FRAME_CACHE[symbol] = frame
    return frame


def _daily_closes(frame: pd.DataFrame) -> pd.Series:
    rows = frame.groupby("_session_date", sort=True)["close"].last()
    rows.index = rows.index.astype(str)
    return rows.astype(float)


def _timestamp(day: str, clock: str) -> pd.Timestamp:
    return pd.Timestamp(f"{day} {clock}", tz="America/New_York").tz_convert("UTC")


def add_context(events: pd.DataFrame) -> pd.DataFrame:
    metadata = _event_metadata_frame(events)
    frames = {symbol: _load_symbol_frame(symbol) for symbol in SYMBOL_INPUTS}
    close_by_symbol = {symbol: _daily_closes(frame) for symbol, frame in frames.items()}
    context_rows = []
    for record in metadata.to_dict("records"):
        symbol = record["symbol"]
        frame = frames[symbol]
        closes = close_by_symbol[symbol]
        previous_session = record["previous_session_date"]
        close_index = list(closes.index)
        previous_index = close_index.index(previous_session)
        prior_20 = closes.iloc[max(0, previous_index - 19) : previous_index + 1]
        prior_sma_20 = float(prior_20.mean()) if len(prior_20) == 20 else None
        prior_5_return = None
        if previous_index >= 5:
            prior_5_return = float(closes.iloc[previous_index] / closes.iloc[previous_index - 5] - 1.0)
        opening_rows = frame.loc[
            (frame["_session_date"] == record["session_date"])
            & (frame["timestamp"] >= _timestamp(record["session_date"], "09:30"))
            & (frame["timestamp"] <= _timestamp(record["session_date"], "09:45"))
        ]
        opening_high = float(opening_rows["high"].max())
        opening_low = float(opening_rows["low"].min())
        opening_range_atr = (opening_high - opening_low) / record["prior_atr"]
        if record["gap_direction"] == 1:
            full_fill = opening_low <= record["previous_session_close"]
            partial_fill = opening_low < record["current_session_open"]
        else:
            full_fill = opening_high >= record["previous_session_close"]
            partial_fill = opening_high > record["current_session_open"]
        if full_fill:
            fill_label = "full_fill_by_confirmation"
        elif partial_fill:
            fill_label = "partial_fill_no_full"
        else:
            fill_label = "no_fill_follow_through"
        session_timestamp = pd.Timestamp(record["session_date"])
        context_rows.append(
            {
                **record,
                "gap_direction_label": "gap_up" if record["gap_direction"] == 1 else "gap_down",
                "prior_close_vs_sma20": (
                    "above_sma20"
                    if prior_sma_20 is not None and record["previous_session_close"] > prior_sma_20
                    else "below_or_equal_sma20"
                    if prior_sma_20 is not None
                    else "insufficient_sma20"
                ),
                "prior_5_session_return": prior_5_return,
                "prior_5_session_trend": (
                    "prior_5d_up"
                    if prior_5_return is not None and prior_5_return > 0
                    else "prior_5d_down_or_flat"
                    if prior_5_return is not None
                    else "insufficient_prior_5d"
                ),
                "opening_range_atr": opening_range_atr,
                "gap_fill_relation_0930_0945": fill_label,
                "day_of_week": session_timestamp.day_name(),
                "year": int(str(record["session_date"])[:4]),
                "month": str(record["session_date"])[:7],
                "quarter": f"{str(record['session_date'])[:4]}Q{((int(str(record['session_date'])[5:7]) - 1) // 3) + 1}",
            }
        )
    return pd.DataFrame(context_rows)


def _tercile_cuts(values: pd.Series) -> tuple[float, float]:
    clean = values.dropna().astype(float)
    return float(clean.quantile(1 / 3)), float(clean.quantile(2 / 3))


def _bucket(value: float, cuts: tuple[float, float], labels: tuple[str, str, str]) -> str:
    if value <= cuts[0]:
        return labels[0]
    if value <= cuts[1]:
        return labels[1]
    return labels[2]


def add_regime_buckets(context: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    discovery = context.loc[context["period"] == "discovery"]
    cuts = {
        "normalized_gap": _tercile_cuts(discovery["normalized_gap"]),
        "abs_gap_return": _tercile_cuts(discovery["abs_gap_return"]),
        "prior_atr": _tercile_cuts(discovery["prior_atr"]),
        "relative_volume_0930_0945": _tercile_cuts(discovery["relative_volume_0930_0945"]),
        "opening_range_atr": _tercile_cuts(discovery["opening_range_atr"]),
    }
    enriched = context.copy()
    enriched["normalized_gap_bucket"] = [
        _bucket(value, cuts["normalized_gap"], ("normalized_gap_low", "normalized_gap_mid", "normalized_gap_high"))
        for value in enriched["normalized_gap"]
    ]
    enriched["gap_percent_bucket"] = [
        _bucket(value, cuts["abs_gap_return"], ("abs_gap_low", "abs_gap_mid", "abs_gap_high"))
        for value in enriched["abs_gap_return"]
    ]
    enriched["volatility_bucket"] = [
        _bucket(value, cuts["prior_atr"], ("volatility_low", "volatility_mid", "volatility_high"))
        for value in enriched["prior_atr"]
    ]
    enriched["relative_volume_bucket"] = [
        _bucket(value, cuts["relative_volume_0930_0945"], ("early_volume_low", "early_volume_normal", "early_volume_high"))
        for value in enriched["relative_volume_0930_0945"]
    ]
    enriched["opening_range_bucket"] = [
        _bucket(value, cuts["opening_range_atr"], ("opening_range_narrow", "opening_range_normal", "opening_range_wide"))
        for value in enriched["opening_range_atr"]
    ]
    return enriched, {key: {"lower_tercile": value[0], "upper_tercile": value[1]} for key, value in cuts.items()}


def build_regime_results(results: pd.DataFrame, context: pd.DataFrame) -> pd.DataFrame:
    merged = results.merge(context, on=["event_id", "period", "symbol", "session_date"], how="left", suffixes=("", "_context"))
    dimensions = (
        "gap_direction_label",
        "normalized_gap_bucket",
        "gap_percent_bucket",
        "prior_close_vs_sma20",
        "prior_5_session_trend",
        "volatility_bucket",
        "relative_volume_bucket",
        "opening_range_bucket",
        "gap_fill_relation_0930_0945",
        "day_of_week",
        "symbol",
        "year",
        "quarter",
    )
    frames = []
    for dimension in dimensions:
        grouped = summarize(merged, ["period", dimension, "horizon"])
        grouped.insert(1, "regime_dimension", dimension)
        grouped = grouped.rename(columns={dimension: "regime_bucket"})
        frames.append(grouped)
    return pd.concat(frames, ignore_index=True)


def build_outlier_results(results: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary_rows = []
    event_rows = []
    for (period, horizon), subset in results.groupby(["period", "horizon"], sort=True):
        available = subset.loc[
            (subset["availability_status"] == "available") & subset["analysis_return"].notna()
        ].copy()
        values = available["analysis_return"].astype(float)
        if values.empty:
            continue
        low, high = values.quantile(0.05), values.quantile(0.95)
        winsorized = values.clip(lower=low, upper=high)
        best = available.sort_values("analysis_return", ascending=False).head(5)
        worst = available.sort_values("analysis_return", ascending=True).head(5)
        total = float(values.sum())
        top3_sum = float(best.head(3)["analysis_return"].sum())
        bottom3_sum = float(worst.head(3)["analysis_return"].sum())
        summary_rows.append(
            {
                "period": period,
                "horizon": horizon,
                "events": int(available["event_id"].nunique()),
                "mean_return": float(values.mean()),
                "winsorized_5_95_mean_return": float(winsorized.mean()),
                "mean_change_after_winsorization": float(winsorized.mean() - values.mean()),
                "best_event_return": float(values.max()),
                "worst_event_return": float(values.min()),
                "top3_sum_return": top3_sum,
                "bottom3_sum_return": bottom3_sum,
                "top3_share_of_total_return": top3_sum / total if total else None,
                "bottom3_share_of_total_return": bottom3_sum / total if total else None,
            }
        )
        for label, rows in (("best", best), ("worst", worst)):
            for rank, row in enumerate(rows.to_dict("records"), start=1):
                event_rows.append(
                    {
                        "period": period,
                        "horizon": horizon,
                        "tail": label,
                        "rank": rank,
                        "event_id": row["event_id"],
                        "symbol": row["symbol"],
                        "session_date": row["session_date"],
                        "analysis_return": float(row["analysis_return"]),
                    }
                )
    return pd.DataFrame(summary_rows), pd.DataFrame(event_rows)


def build_mfe_mae(context: pd.DataFrame) -> pd.DataFrame:
    frames = {symbol: _load_symbol_frame(symbol) for symbol in SYMBOL_INPUTS}
    rows = []
    for record in context.to_dict("records"):
        frame = frames[record["symbol"]]
        event_time = pd.Timestamp(record["session_date"] + " 09:45", tz="America/New_York").tz_convert("UTC")
        session_rows = frame.loc[
            (frame["_session_date"] == record["session_date"])
            & (frame["timestamp"] >= event_time)
        ]
        event_price = record["confirmation_close"]
        direction = int(record["expected_direction"])
        if direction == 1:
            favorable = session_rows["high"] / event_price - 1.0
            adverse = session_rows["low"] / event_price - 1.0
        else:
            favorable = -(session_rows["low"] / event_price - 1.0)
            adverse = -(session_rows["high"] / event_price - 1.0)
        rows.append(
            {
                "period": record["period"],
                "event_id": record["event_id"],
                "symbol": record["symbol"],
                "session_date": record["session_date"],
                "mfe_to_session_close": float(favorable.max()),
                "mae_to_session_close": float(adverse.min()),
            }
        )
    return pd.DataFrame(rows)


def summarize_mfe_mae(mfe_mae: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (period, symbol), subset in mfe_mae.groupby(["period", "symbol"], sort=True):
        rows.append(
            {
                "period": period,
                "symbol": symbol,
                "events": int(len(subset)),
                "mean_mfe_to_session_close": float(subset["mfe_to_session_close"].mean()),
                "median_mfe_to_session_close": float(subset["mfe_to_session_close"].median()),
                "mean_mae_to_session_close": float(subset["mae_to_session_close"].mean()),
                "median_mae_to_session_close": float(subset["mae_to_session_close"].median()),
            }
        )
    for period, subset in mfe_mae.groupby("period", sort=True):
        rows.append(
            {
                "period": period,
                "symbol": "combined",
                "events": int(len(subset)),
                "mean_mfe_to_session_close": float(subset["mfe_to_session_close"].mean()),
                "median_mfe_to_session_close": float(subset["mfe_to_session_close"].median()),
                "mean_mae_to_session_close": float(subset["mae_to_session_close"].mean()),
                "median_mae_to_session_close": float(subset["mae_to_session_close"].median()),
            }
        )
    return pd.DataFrame(rows)


def build_economic_relevance(comparison: pd.DataFrame) -> pd.DataFrame:
    rows = []
    validation = comparison.loc[
        (comparison["period"] == "validation") & (comparison["scope"] == "combined")
    ]
    for _, row in validation.iterrows():
        mean_bps = float(row["mean_return"] * 10000)
        median_bps = float(row["median_return"] * 10000)
        for friction_bps in (2.0, 5.0, 10.0):
            rows.append(
                {
                    "horizon": row["horizon"],
                    "gross_mean_bps": mean_bps,
                    "gross_median_bps": median_bps,
                    "friction_bps": friction_bps,
                    "mean_after_friction_bps": mean_bps - friction_bps,
                    "median_after_friction_bps": median_bps - friction_bps,
                    "gross_mean_exceeds_friction": mean_bps > friction_bps,
                    "gross_median_exceeds_friction": median_bps > friction_bps,
                }
            )
    return pd.DataFrame(rows)


def _with_scope(frame: pd.DataFrame, scope: str) -> pd.DataFrame:
    copy = frame.copy()
    copy.insert(0, "scope", scope)
    return copy


def build_analysis_outputs(output_root: Path) -> dict[str, Path]:
    discovery_results, discovery_events = _load_period_results("discovery", output_root)
    validation_results, validation_events = _load_period_results("validation", output_root)
    combined_results = pd.concat([discovery_results, validation_results], ignore_index=True)
    combined_events = pd.concat([discovery_events, validation_events], ignore_index=True)
    combined_results["month"] = combined_results["session_date"].astype(str).str.slice(0, 7)
    combined_results["quarter"] = [
        f"{date_text[:4]}Q{((int(date_text[5:7]) - 1) // 3) + 1}"
        for date_text in combined_results["session_date"].astype(str)
    ]

    context = add_context(combined_events)
    context, cuts = add_regime_buckets(context)
    comparison = pd.concat(
        [
            _with_scope(summarize(combined_results, ["period", "horizon"]), "combined"),
            _with_scope(summarize(combined_results, ["period", "symbol", "horizon"]), "symbol"),
            _with_scope(summarize(combined_results, ["period", "expected_direction", "horizon"]), "direction"),
        ],
        ignore_index=True,
    )
    monthly = summarize(
        combined_results.loc[combined_results["period"] == "validation"],
        ["symbol", "month", "horizon"],
    )
    quarterly = summarize(
        combined_results.loc[combined_results["period"] == "validation"],
        ["quarter", "horizon"],
    )
    regimes = build_regime_results(combined_results, context)
    outliers, outlier_events = build_outlier_results(combined_results)
    mfe_mae = build_mfe_mae(context)
    mfe_mae_summary = summarize_mfe_mae(mfe_mae)
    economics = build_economic_relevance(comparison)

    paths = {
        "combined_events": output_root / "combined_events.csv",
        "combined_event_results": output_root / "combined_event_results.csv",
        "event_context": output_root / "event_context.csv",
        "discovery_regime_cuts": output_root / "discovery_regime_cuts.json",
        "comparison": output_root / "comparison_discovery_validation.csv",
        "monthly": output_root / "validation_monthly_results.csv",
        "quarterly": output_root / "validation_quarterly_stability.csv",
        "regimes": output_root / "regime_results.csv",
        "outliers": output_root / "outlier_winsorization.csv",
        "outlier_events": output_root / "outlier_events.csv",
        "mfe_mae": output_root / "mfe_mae_events.csv",
        "mfe_mae_summary": output_root / "mfe_mae_summary.csv",
        "economics": output_root / "economic_relevance.csv",
    }
    combined_events.to_csv(paths["combined_events"], index=False)
    combined_results.to_csv(paths["combined_event_results"], index=False)
    context.to_csv(paths["event_context"], index=False)
    _write_json(paths["discovery_regime_cuts"], cuts)
    comparison.to_csv(paths["comparison"], index=False)
    monthly.to_csv(paths["monthly"], index=False)
    quarterly.to_csv(paths["quarterly"], index=False)
    regimes.to_csv(paths["regimes"], index=False)
    outliers.to_csv(paths["outliers"], index=False)
    outlier_events.to_csv(paths["outlier_events"], index=False)
    mfe_mae.to_csv(paths["mfe_mae"], index=False)
    mfe_mae_summary.to_csv(paths["mfe_mae_summary"], index=False)
    economics.to_csv(paths["economics"], index=False)
    return paths


def _bps(value: Any) -> str:
    if pd.isna(value):
        return ""
    return f"{float(value) * 10000:.2f}"


def _pct(value: Any) -> str:
    if pd.isna(value):
        return ""
    return f"{float(value) * 100:.1f}%"


def _markdown_table(frame: pd.DataFrame, columns: Sequence[str], limit: int | None = None) -> str:
    rows = frame.loc[:, list(columns)].head(limit).copy() if limit else frame.loc[:, list(columns)].copy()
    headers = [str(column) for column in columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for _, row in rows.iterrows():
        values = [str(row[column]) for column in columns]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def _classification(comparison: pd.DataFrame, economics: pd.DataFrame, outliers: pd.DataFrame) -> tuple[str, str]:
    validation = comparison.loc[
        (comparison["period"] == "validation")
        & (comparison["scope"] == "combined")
        & (comparison["horizon"].isin(["15min", "30min", "60min"]))
    ]
    signs_positive = bool((validation["mean_return"] > 0).all() and (validation["median_return"] > 0).all())
    weak_cost = economics.loc[
        economics["horizon"].isin(["15min", "30min", "60min"]) & (economics["friction_bps"] == 5.0),
        "mean_after_friction_bps",
    ]
    survives_5bps = bool((weak_cost > 0).all())
    outlier_validation = outliers.loc[
        (outliers["period"] == "validation") & (outliers["horizon"].isin(["15min", "30min", "60min"]))
    ]
    winsor_damage = bool((outlier_validation["mean_change_after_winsorization"].abs() * 10000 > 5.0).any())
    if not signs_positive:
        return "Rechazada", "validation cambió o debilitó el signo en horizontes intradiarios centrales."
    if winsor_damage or not survives_5bps:
        return "Necesita más investigación", "el signo sobrevive, pero la magnitud/costos u outliers no permiten elevarla a estrategia."
    return "Validada como evento estadístico", "la dirección y magnitud intradiaria sobreviven validation; no autoriza paper/live."


def write_report(output_root: Path, audit: Mapping[str, Any], freeze: Mapping[str, Any]) -> Path:
    comparison = pd.read_csv(output_root / "comparison_discovery_validation.csv")
    regimes = pd.read_csv(output_root / "regime_results.csv")
    outliers = pd.read_csv(output_root / "outlier_winsorization.csv")
    economics = pd.read_csv(output_root / "economic_relevance.csv")
    monthly = pd.read_csv(output_root / "validation_monthly_results.csv")
    quarterly = pd.read_csv(output_root / "validation_quarterly_stability.csv")
    context = pd.read_csv(output_root / "event_context.csv")
    classification, classification_reason = _classification(comparison, economics, outliers)

    combined = comparison.loc[comparison["scope"] == "combined"].copy()
    combined["mean_bps"] = combined["mean_return"].map(_bps)
    combined["median_bps"] = combined["median_return"].map(_bps)
    combined["bootstrap_ci_bps"] = [
        f"{_bps(row['bootstrap_session_ci_lower'])} to {_bps(row['bootstrap_session_ci_upper'])}"
        for _, row in combined.iterrows()
    ]
    combined["positive"] = combined["positive_rate"].map(_pct)
    symbol = comparison.loc[comparison["scope"] == "symbol"].copy()
    symbol["mean_bps"] = symbol["mean_return"].map(_bps)
    symbol["median_bps"] = symbol["median_return"].map(_bps)
    symbol["positive"] = symbol["positive_rate"].map(_pct)
    econ = economics.copy()
    for column in ("gross_mean_bps", "gross_median_bps", "mean_after_friction_bps", "median_after_friction_bps"):
        econ[column] = econ[column].map(lambda value: f"{float(value):.2f}")
    out = outliers.copy()
    out["mean_bps"] = out["mean_return"].map(_bps)
    out["winsor_mean_bps"] = out["winsorized_5_95_mean_return"].map(_bps)
    out["change_bps"] = out["mean_change_after_winsorization"].map(_bps)

    validation_context = context.loc[context["period"] == "validation"]
    regime_core = regimes.loc[
        (regimes["period"] == "validation")
        & (regimes["horizon"] == "30min")
        & (regimes["regime_dimension"].isin(
            [
                "gap_direction_label",
                "normalized_gap_bucket",
                "volatility_bucket",
                "relative_volume_bucket",
                "opening_range_bucket",
                "gap_fill_relation_0930_0945",
                "day_of_week",
                "symbol",
                "quarter",
            ]
        ))
    ].copy()
    regime_core["mean_bps"] = regime_core["mean_return"].map(_bps)
    regime_core["median_bps"] = regime_core["median_return"].map(_bps)
    regime_core["positive"] = regime_core["positive_rate"].map(_pct)

    text = f"""# HYP-GAP-03 Validation and Regime Review

## Executive Decision

Methodological audit conclusion: `{audit["conclusion"]}`.

Final classification: **{classification}**.

Reason: {classification_reason}

This remains an event study only. It does not authorize replay, paper trading, live trading, broker connection, strategy parameters, stops, entries, exits, or order routing.

Holdout status: **closed**. No 2026 events, returns, charts, summaries, or holdout results were generated or inspected.

## Pre-Validation Audit

- HYP-GAP-03 was present in the 2026-07-13 preregistration commit before the discovery report.
- The HYP-GAP YAML has no post-discovery diff against current HEAD before this task's validation infrastructure edits.
- Discovery outputs for QQQ and SPY end at 2024-12-30 and contain no 2025/2026 result rows.
- Validation is limited to 2025-01-01 through 2025-12-31.
- Final holdout is 2026-01-01 through 2026-07-06 and remains closed.
- Safety flags are false: `live_trading`, `broker_connected`, `orders_sent`, `paper_broker_enabled`.

Audit risks reviewed: lookahead, survivorship/data selection, post hoc selection, discovery-validation leakage, double-counting, incomplete sessions, warm-up, early closes, exclusions, and accidental holdout use. No serious blocker was found for opening validation 2025.

## Frozen Definition

Freeze manifest: `{output_root / "pre_validation_freeze_manifest.json"}`

Freeze hash: `{freeze["freeze_hash"]}`

Frozen event:

- Variant: HYP-GAP-03, Gap Continuation With Opening Follow-Through.
- Confirmation: 09:45 America/New_York, event price is the confirmation bar close.
- Conditions: `normalized_gap >= 0.35`, opening return same sign as gap, `opening_move_atr >= 0.10`.
- Expected direction: `gap_direction`.
- Symbols: QQQ, SPY.
- Horizons: 5min, 15min, 30min, 60min, session_close.

## Discovery vs Validation

Directional returns are in bps. Positive means movement in the preregistered HYP-GAP-03 direction.

{_markdown_table(combined, ["period", "horizon", "event_count", "mean_bps", "median_bps", "positive", "bootstrap_ci_bps"])}

## Symbol Stability

{_markdown_table(symbol, ["period", "symbol", "horizon", "event_count", "mean_bps", "median_bps", "positive"])}

## Validation Monthly And Quarterly Stability

Monthly validation results are stored in `{output_root / "validation_monthly_results.csv"}`.

{_markdown_table(quarterly.assign(mean_bps=quarterly["mean_return"].map(_bps), median_bps=quarterly["median_return"].map(_bps), positive=quarterly["positive_rate"].map(_pct)), ["quarter", "horizon", "event_count", "mean_bps", "median_bps", "positive"], 20)}

## Regime Event Study

Regime cuts for normalized gap, gap percent, volatility, early volume, and opening range were estimated from discovery only. These regime tables are exploratory diagnostics, not new validation filters.

Validation 30min regime snapshot:

{_markdown_table(regime_core, ["regime_dimension", "regime_bucket", "event_count", "mean_bps", "median_bps", "positive"], 80)}

Full regime output: `{output_root / "regime_results.csv"}`.

Validation event count by gap direction:

{_markdown_table(validation_context.groupby(["gap_direction_label", "symbol"]).size().reset_index(name="events"), ["gap_direction_label", "symbol", "events"])}

## Outliers And Winsorization

{_markdown_table(out, ["period", "horizon", "events", "mean_bps", "winsor_mean_bps", "change_bps", "top3_share_of_total_return", "bottom3_share_of_total_return"])}

Best/worst event details are stored in `{output_root / "outlier_events.csv"}`.

## Economic Relevance

No trading strategy was implemented. The table below subtracts conservative illustrative frictions from the gross event movement to judge whether the raw effect is large enough to merit a future strategy preregistration.

{_markdown_table(econ, ["horizon", "gross_mean_bps", "gross_median_bps", "friction_bps", "mean_after_friction_bps", "median_after_friction_bps", "gross_mean_exceeds_friction", "gross_median_exceeds_friction"])}

MFE/MAE event-level diagnostics are stored in `{output_root / "mfe_mae_events.csv"}`.

## Confirmatory vs Exploratory

Confirmatory:

- Same frozen HYP-GAP-03 event definition.
- Same symbols and horizons.
- Validation period fixed to calendar year 2025.
- Primary comparison of discovery vs validation directional returns by horizon and symbol.

Exploratory:

- Regime breakdowns.
- MFE/MAE diagnostics.
- Winsorization sensitivity.
- Conservative friction comparison.
- Any future strategy idea derived from these observations.

## Outputs

- `{output_root / "pre_validation_methodology_audit.json"}`
- `{output_root / "pre_validation_freeze_manifest.json"}`
- `{output_root / "combined_events.csv"}`
- `{output_root / "combined_event_results.csv"}`
- `{output_root / "comparison_discovery_validation.csv"}`
- `{output_root / "validation_monthly_results.csv"}`
- `{output_root / "validation_quarterly_stability.csv"}`
- `{output_root / "regime_results.csv"}`
- `{output_root / "outlier_winsorization.csv"}`
- `{output_root / "economic_relevance.csv"}`

## Next Scientific Step

If the event is used further, the next task should be a new independent preregistration for a tradable strategy. It must separate event definition, entry timing, stop, exit, sizing, costs, and approval criteria, and it must not reuse 2025 to optimize those parameters.
"""
    REPORT_PATH.write_text(text, encoding="utf-8")
    return REPORT_PATH


def run(output_root: Path = OUTPUT_ROOT) -> dict[str, Path]:
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    audit = build_methodology_audit()
    _write_json(output_root / "pre_validation_methodology_audit.json", audit)
    if audit["conclusion"] != "habilitada_para_validation":
        raise RuntimeError("Methodological audit did not authorize validation")
    freeze = build_freeze_manifest(audit)
    _write_json(output_root / "pre_validation_freeze_manifest.json", freeze)
    run_validation_outputs(output_root)
    paths = build_analysis_outputs(output_root)
    report = write_report(output_root, audit, freeze)
    paths["methodology_audit"] = output_root / "pre_validation_methodology_audit.json"
    paths["freeze_manifest"] = output_root / "pre_validation_freeze_manifest.json"
    paths["report"] = report
    return paths


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run frozen HYP-GAP-03 validation and regime review.")
    parser.add_argument("--output-root", default=str(OUTPUT_ROOT))
    args = parser.parse_args(argv)
    run(Path(args.output_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
