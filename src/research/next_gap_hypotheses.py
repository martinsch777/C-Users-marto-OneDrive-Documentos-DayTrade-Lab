from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from src.data import EquitySessionCalendar, load_csv, sha256_file


SAFETY_FLAGS = {
    "live_trading": False,
    "broker_connected": False,
    "orders_sent": False,
    "paper_broker_enabled": False,
}
SYMBOLS = ("QQQ", "SPY")
YEARS = (2022, 2023, 2024)
HORIZONS = ("5min", "15min", "30min", "60min", "session_close")
MINUTE_HORIZONS = {
    "5min": pd.Timedelta(minutes=5),
    "15min": pd.Timedelta(minutes=15),
    "30min": pd.Timedelta(minutes=30),
    "60min": pd.Timedelta(minutes=60),
}
RESEARCH_POOL_START = date(2022, 1, 1)
RESEARCH_POOL_END = date(2024, 12, 31)
VALIDATION_OBSERVED_START = date(2025, 1, 1)
HOLDOUT_START = date(2026, 1, 1)
BOOTSTRAP_SEED = 20260721
BOOTSTRAP_ITERATIONS = 2000
OUTPUT_ROOT = Path("outputs/next_gap_hypotheses_research_pool_v1")
ASYM_CONFIG = Path("configs/research/hypotheses/HYP-GAP-ASYM-01.yaml")
OR_CONFIG = Path("configs/research/hypotheses/HYP-GAP-OR-01.yaml")
REGISTRY_PATH = Path("docs/RESEARCH_HYPOTHESIS_REGISTRY.md")
PLAN_REPORT = Path("docs/NEXT_GAP_HYPOTHESES_RESEARCH_PLAN.md")
ASYM_REPORT = Path("docs/HYP_GAP_ASYM_01_RETROSPECTIVE_RESULTS.md")
OR_REPORT = Path("docs/HYP_GAP_OR_01_RETROSPECTIVE_RESULTS.md")


@dataclass(frozen=True)
class ResearchPoolInput:
    symbol: str
    year: int
    csv_path: Path
    manifest_path: Path
    manifest_sha256: str
    dataset_sha256: str
    dataset_status: str
    audit_critical_warnings: tuple[str, ...]


def _json(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        import yaml  # type: ignore

        payload = yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a mapping")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _session_date(timestamp: pd.Timestamp, calendar: EquitySessionCalendar) -> str:
    return pd.Timestamp(timestamp).tz_convert(calendar.timezone).date().isoformat()


def _local_timestamp(day: str, clock: time, calendar: EquitySessionCalendar) -> pd.Timestamp:
    return pd.Timestamp(
        datetime.combine(date.fromisoformat(day), clock),
        tz=calendar.timezone,
    ).tz_convert("UTC")


def _read_excluded_sessions(symbol: str) -> set[str]:
    path = Path("data/quality_overrides/excluded_sessions.json")
    if not path.exists():
        return set()
    payload = _json(path)
    return {
        str(record["date"])
        for record in payload.get("excluded_sessions", [])
        if str(record.get("symbol", "")).upper() == symbol.upper()
    }


def annual_input(symbol: str, year: int) -> ResearchPoolInput:
    csv_path = Path(
        f"data/raw/{symbol}_1min_{year}-01-01_{year}-12-31_alpaca_sip_raw_rth.csv"
    )
    manifest_path = Path(
        f"data/manifests/{symbol}_1min_{year}-01-01_{year}-12-31_alpaca_sip_raw_rth_manifest.json"
    )
    manifest = _json(manifest_path)
    if manifest.get("symbol") != symbol or manifest.get("timeframe") != "1min":
        raise ValueError(f"Manifest mismatch for {symbol} {year}")
    if str(manifest.get("start")) != f"{year}-01-01" or str(manifest.get("end")) != f"{year}-12-31":
        raise ValueError(f"Manifest period mismatch for {symbol} {year}")
    actual_hash = sha256_file(csv_path)
    if actual_hash != manifest.get("sha256"):
        raise ValueError(f"Dataset hash mismatch for {csv_path}")
    warnings = tuple(str(item) for item in manifest.get("audit_critical_warnings", []))
    if manifest.get("dataset_status") != "approved_for_or_fvg_backtest":
        allowed_spy_2023 = symbol == "SPY" and year == 2023 and _read_excluded_sessions(symbol)
        if not allowed_spy_2023:
            raise ValueError(f"Unapproved research-pool annual dataset: {manifest_path}")
    return ResearchPoolInput(
        symbol=symbol,
        year=year,
        csv_path=csv_path,
        manifest_path=manifest_path,
        manifest_sha256=sha256_file(manifest_path),
        dataset_sha256=actual_hash,
        dataset_status=str(manifest.get("dataset_status")),
        audit_critical_warnings=warnings,
    )


def load_research_pool_symbol(symbol: str) -> tuple[pd.DataFrame, list[ResearchPoolInput]]:
    calendar = EquitySessionCalendar.from_config({"source": "us_equity"})
    excluded = _read_excluded_sessions(symbol)
    frames: list[pd.DataFrame] = []
    inputs: list[ResearchPoolInput] = []
    for year in YEARS:
        record = annual_input(symbol, year)
        frame, report = load_csv(
            record.csv_path,
            "1min",
            asset_class="equity",
            drop_incomplete=False,
            calendar=calendar,
            excluded_session_dates=excluded,
        )
        if not report.is_valid:
            raise ValueError(f"{symbol} {year} research-pool data failed validation")
        frame["_session_date"] = [_session_date(value, calendar) for value in frame["timestamp"]]
        bad_dates = frame["_session_date"].loc[frame["_session_date"] > RESEARCH_POOL_END.isoformat()]
        if not bad_dates.empty:
            raise ValueError(f"Research pool attempted to load after 2024: {bad_dates.iloc[0]}")
        frames.append(frame)
        inputs.append(record)
    combined = pd.concat(frames, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
    return combined, inputs


def _expected_session_timestamps(day: str, calendar: EquitySessionCalendar) -> pd.DatetimeIndex:
    return calendar.expected_timestamps(date.fromisoformat(day), date.fromisoformat(day), "1min")


def _session_complete(rows: pd.DataFrame, day: str, calendar: EquitySessionCalendar) -> bool:
    expected = _expected_session_timestamps(day, calendar)
    return len(rows) == len(expected) and set(rows["timestamp"]) == set(expected)


def _session_close_timestamp(day: str, calendar: EquitySessionCalendar) -> pd.Timestamp:
    expected = _expected_session_timestamps(day, calendar)
    if expected.empty:
        raise ValueError(f"No expected timestamps for {day}")
    return expected[-1]


def _price_at(close_by_timestamp: Mapping[pd.Timestamp, float], timestamp: pd.Timestamp) -> float | None:
    value = close_by_timestamp.get(timestamp)
    return float(value) if value is not None else None


def _return_to(value: float | None, base: float) -> float | None:
    if value is None or base == 0:
        return None
    return value / base - 1.0


def build_gap_event_features(symbol: str, frame: pd.DataFrame) -> pd.DataFrame:
    calendar = EquitySessionCalendar.from_config({"source": "us_equity"})
    excluded = _read_excluded_sessions(symbol)
    rows_by_session = {day: group.copy() for day, group in frame.groupby("_session_date", sort=True)}
    close_by_timestamp = {row["timestamp"]: float(row["close"]) for _, row in frame.iterrows()}
    history: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []

    for item in pd.date_range(RESEARCH_POOL_START, RESEARCH_POOL_END, freq="D"):
        day = item.date().isoformat()
        if calendar.session_close(item.date()) is None or day in excluded:
            continue
        rows = rows_by_session.get(day)
        if rows is None or not _session_complete(rows, day, calendar):
            continue
        previous = history[-1] if history else None
        true_range = None
        if previous is not None:
            true_range = max(
                float(rows["high"].max()) - float(rows["low"].min()),
                abs(float(rows["high"].max()) - float(previous["close"])),
                abs(float(rows["low"].min()) - float(previous["close"])),
            )
        prior_tr = [float(record["true_range"]) for record in history if record["true_range"] is not None]
        if previous is not None and len(prior_tr) >= 20:
            open_ts = _local_timestamp(day, time(9, 30), calendar)
            confirmation_ts = _local_timestamp(day, time(9, 45), calendar)
            or_end_ts = _local_timestamp(day, time(10, 0), calendar)
            open_row = rows.loc[rows["timestamp"] == open_ts]
            confirmation_row = rows.loc[rows["timestamp"] == confirmation_ts]
            opening_range_rows = rows.loc[
                (rows["timestamp"] >= open_ts) & (rows["timestamp"] < or_end_ts)
            ]
            if not open_row.empty and not confirmation_row.empty and len(opening_range_rows) == 30:
                previous_close = float(previous["close"])
                current_open = float(open_row.iloc[0]["open"])
                gap_return = current_open / previous_close - 1.0
                if gap_return != 0:
                    gap_direction = 1 if gap_return > 0 else -1
                    prior_atr = float(pd.Series(prior_tr[-20:]).mean())
                    confirmation_close = float(confirmation_row.iloc[0]["close"])
                    opening_high = float(opening_range_rows["high"].max())
                    opening_low = float(opening_range_rows["low"].min())
                    record: dict[str, Any] = {
                        "hypothesis_family": "NEXT_GAP",
                        "event_id": f"NEXT-GAP:{symbol}:{day}",
                        "symbol": symbol,
                        "session_date": day,
                        "year": item.year,
                        "month": day[:7],
                        "quarter": f"{item.year}Q{((item.month - 1) // 3) + 1}",
                        "previous_session_date": previous["session_date"],
                        "previous_session_close": previous_close,
                        "current_session_open": current_open,
                        "confirmation_close": confirmation_close,
                        "gap_return": gap_return,
                        "gap_bps": gap_return * 10000,
                        "abs_gap_bps": abs(gap_return) * 10000,
                        "gap_direction": gap_direction,
                        "gap_direction_label": "gap_up" if gap_direction == 1 else "gap_down",
                        "prior_atr": prior_atr,
                        "normalized_gap": abs(current_open - previous_close) / prior_atr,
                        "opening_range_high": opening_high,
                        "opening_range_low": opening_low,
                        "opening_range_width": opening_high - opening_low,
                        "opening_range_width_atr": (opening_high - opening_low) / prior_atr,
                        "opening_range_width_bps": ((opening_high - opening_low) / current_open) * 10000,
                        "is_early_close": calendar.session_close(item.date()) != calendar.regular_close,
                        "full_gap_closed": (
                            bool(float(rows["low"].min()) <= previous_close)
                            if gap_direction == 1
                            else bool(float(rows["high"].max()) >= previous_close)
                        ),
                        "partial_gap_closed": (
                            bool(float(rows["low"].min()) < current_open)
                            if gap_direction == 1
                            else bool(float(rows["high"].max()) > current_open)
                        ),
                    }
                    session_after_open = rows.loc[rows["timestamp"] >= open_ts]
                    if gap_direction == 1:
                        favorable = session_after_open["high"] / current_open - 1.0
                        adverse = session_after_open["low"] / current_open - 1.0
                    else:
                        favorable = -(session_after_open["low"] / current_open - 1.0)
                        adverse = -(session_after_open["high"] / current_open - 1.0)
                    record["mfe_open_continuation"] = float(favorable.max())
                    record["mae_open_continuation"] = float(adverse.min())
                    for horizon in HORIZONS:
                        if horizon == "session_close":
                            future_ts = _session_close_timestamp(day, calendar)
                        else:
                            future_ts = open_ts + MINUTE_HORIZONS[horizon]
                        open_return = _return_to(_price_at(close_by_timestamp, future_ts), current_open)
                        record[f"open_raw_return_{horizon}"] = open_return
                        record[f"open_gap_continuation_return_{horizon}"] = (
                            open_return * gap_direction if open_return is not None else None
                        )
                        record[f"open_gap_reversal_return_{horizon}"] = (
                            -open_return * gap_direction if open_return is not None else None
                        )
                        if horizon == "session_close":
                            confirmation_future_ts = future_ts
                        else:
                            confirmation_future_ts = confirmation_ts + MINUTE_HORIZONS[horizon]
                        confirmation_return = _return_to(
                            _price_at(close_by_timestamp, confirmation_future_ts),
                            confirmation_close,
                        )
                        record[f"confirmation_raw_return_{horizon}"] = confirmation_return
                        record[f"confirmation_gap_continuation_return_{horizon}"] = (
                            confirmation_return * gap_direction if confirmation_return is not None else None
                        )
                        record[f"confirmation_gap_reversal_return_{horizon}"] = (
                            -confirmation_return * gap_direction if confirmation_return is not None else None
                        )
                    records.append(record)
        history.append(
            {
                "session_date": day,
                "close": float(rows.loc[rows["timestamp"] == _session_close_timestamp(day, calendar), "close"].iloc[0]),
                "true_range": true_range,
            }
        )
    return pd.DataFrame(records)


def build_research_pool_events() -> tuple[pd.DataFrame, list[ResearchPoolInput]]:
    frames = []
    inputs: list[ResearchPoolInput] = []
    for symbol in SYMBOLS:
        frame, symbol_inputs = load_research_pool_symbol(symbol)
        frames.append(build_gap_event_features(symbol, frame))
        inputs.extend(symbol_inputs)
    events = pd.concat(frames, ignore_index=True).sort_values(["session_date", "symbol"]).reset_index(drop=True)
    if events["session_date"].ge("2025-01-01").any():
        raise ValueError("Retrospective discovery attempted to include 2025+ events")
    return events, inputs


def compute_tercile_limits(events: pd.DataFrame) -> dict[str, dict[str, float]]:
    return {
        "opening_range_width_atr": {
            "narrow_max": float(events["opening_range_width_atr"].quantile(1 / 3)),
            "wide_min": float(events["opening_range_width_atr"].quantile(2 / 3)),
        },
        "normalized_gap": {
            "small_max": float(events["normalized_gap"].quantile(1 / 3)),
            "large_min": float(events["normalized_gap"].quantile(2 / 3)),
        },
    }


def apply_frozen_regime_limits(events: pd.DataFrame, limits: Mapping[str, Mapping[str, float]]) -> pd.DataFrame:
    data = events.copy()
    or_limits = limits["opening_range_width_atr"]
    gap_limits = limits["normalized_gap"]
    data["opening_range_bucket"] = np.select(
        [
            data["opening_range_width_atr"] <= float(or_limits["narrow_max"]),
            data["opening_range_width_atr"] >= float(or_limits["wide_min"]),
        ],
        ["narrow", "wide"],
        default="normal",
    )
    data["gap_size_bucket"] = np.select(
        [
            data["normalized_gap"] <= float(gap_limits["small_max"]),
            data["normalized_gap"] >= float(gap_limits["large_min"]),
        ],
        ["small", "large"],
        default="medium",
    )
    return data


def _bootstrap_ci(values: pd.Series, sessions: pd.Series) -> tuple[float | None, float | None]:
    available = pd.DataFrame({"value": values, "session": sessions}).dropna()
    if available.empty:
        return None, None
    session_means = available.groupby("session")["value"].mean().to_numpy(dtype=float)
    if len(session_means) == 1:
        value = float(session_means[0])
        return value, value
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = rng.choice(session_means, size=(BOOTSTRAP_ITERATIONS, len(session_means)), replace=True).mean(axis=1)
    return float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))


def _summary(values: pd.Series, sessions: pd.Series) -> dict[str, Any]:
    clean = values.dropna().astype(float)
    if clean.empty:
        return {
            "event_count": int(len(values)),
            "available_count": 0,
            "mean_return": None,
            "median_return": None,
            "standard_deviation": None,
            "standard_error": None,
            "ci_95_lower": None,
            "ci_95_upper": None,
            "bootstrap_ci_95_lower": None,
            "bootstrap_ci_95_upper": None,
            "positive_rate": None,
            "winsor_1pct_mean_return": None,
            "winsor_5pct_mean_return": None,
            "exclude_top_bottom_5_mean_return": None,
            "minimum": None,
            "maximum": None,
        }
    std = float(clean.std(ddof=1)) if len(clean) > 1 else 0.0
    se = std / (len(clean) ** 0.5) if len(clean) > 1 else 0.0
    boot_low, boot_high = _bootstrap_ci(values, sessions)
    trimmed = clean.sort_values().iloc[5:-5] if len(clean) > 10 else clean.iloc[0:0]
    return {
        "event_count": int(len(values)),
        "available_count": int(len(clean)),
        "mean_return": float(clean.mean()),
        "median_return": float(clean.median()),
        "standard_deviation": std,
        "standard_error": se,
        "ci_95_lower": float(clean.mean() - 1.96 * se),
        "ci_95_upper": float(clean.mean() + 1.96 * se),
        "bootstrap_ci_95_lower": boot_low,
        "bootstrap_ci_95_upper": boot_high,
        "positive_rate": float((clean > 0).mean()),
        "winsor_1pct_mean_return": float(clean.clip(clean.quantile(0.01), clean.quantile(0.99)).mean()),
        "winsor_5pct_mean_return": float(clean.clip(clean.quantile(0.05), clean.quantile(0.95)).mean()),
        "exclude_top_bottom_5_mean_return": float(trimmed.mean()) if not trimmed.empty else None,
        "minimum": float(clean.min()),
        "maximum": float(clean.max()),
    }


def metric_table(
    events: pd.DataFrame,
    *,
    hypothesis_id: str,
    group_by: Sequence[str],
    return_bases: Sequence[str] = ("open", "confirmation"),
    outcomes: Sequence[str] = ("gap_continuation", "gap_reversal"),
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for basis in return_bases:
        for outcome in outcomes:
            for horizon in HORIZONS:
                column = f"{basis}_{outcome}_return_{horizon}"
                if group_by:
                    grouped = events.groupby(list(group_by), dropna=False, sort=True)
                    for keys, subset in grouped:
                        if not isinstance(keys, tuple):
                            keys = (keys,)
                        record = dict(zip(group_by, keys))
                        record.update(
                            {
                                "hypothesis_id": hypothesis_id,
                                "return_basis": basis,
                                "outcome": outcome,
                                "horizon": horizon,
                            }
                        )
                        record.update(_summary(subset[column], subset["session_date"]))
                        rows.append(record)
                else:
                    record = {
                        "hypothesis_id": hypothesis_id,
                        "return_basis": basis,
                        "outcome": outcome,
                        "horizon": horizon,
                    }
                    record.update(_summary(events[column], events["session_date"]))
                    rows.append(record)
    return pd.DataFrame(rows)


def build_outlier_table(events: pd.DataFrame, hypothesis_id: str) -> pd.DataFrame:
    rows = []
    for basis in ("open", "confirmation"):
        for outcome in ("gap_continuation", "gap_reversal"):
            for horizon in HORIZONS:
                column = f"{basis}_{outcome}_return_{horizon}"
                available = events.loc[events[column].notna()].copy()
                if available.empty:
                    continue
                available = available.sort_values(column)
                for tail, subset in (("worst", available.head(10)), ("best", available.tail(10).iloc[::-1])):
                    for rank, row in enumerate(subset.to_dict("records"), start=1):
                        rows.append(
                            {
                                "hypothesis_id": hypothesis_id,
                                "return_basis": basis,
                                "outcome": outcome,
                                "horizon": horizon,
                                "tail": tail,
                                "rank": rank,
                                "event_id": row["event_id"],
                                "symbol": row["symbol"],
                                "session_date": row["session_date"],
                                "return": row[column],
                                "return_bps": row[column] * 10000,
                            }
                        )
    return pd.DataFrame(rows)


def build_economic_relevance(metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    combined = metrics.loc[
        (metrics["return_basis"] == "open")
        & (metrics["outcome"].isin(["gap_continuation", "gap_reversal"]))
    ]
    for _, row in combined.iterrows():
        for friction_bps in (2.0, 5.0, 10.0):
            mean_bps = None if pd.isna(row["mean_return"]) else float(row["mean_return"]) * 10000
            median_bps = None if pd.isna(row["median_return"]) else float(row["median_return"]) * 10000
            rows.append(
                {
                    "hypothesis_id": row["hypothesis_id"],
                    "outcome": row["outcome"],
                    "horizon": row["horizon"],
                    "gross_mean_bps": mean_bps,
                    "gross_median_bps": median_bps,
                    "friction_bps": friction_bps,
                    "mean_after_friction_bps": None if mean_bps is None else mean_bps - friction_bps,
                    "median_after_friction_bps": None if median_bps is None else median_bps - friction_bps,
                }
            )
    return pd.DataFrame(rows)


def _hash_outputs(paths: Iterable[Path]) -> dict[str, str]:
    return {str(path): sha256_file(path) for path in paths if path.exists() and path.is_file()}


def _write_csv(path: Path, frame: pd.DataFrame) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return path


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
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for _, row in rows.iterrows():
        lines.append("| " + " | ".join(str(row[column]) for column in columns) + " |")
    return "\n".join(lines)


def classify_hypothesis(metrics: pd.DataFrame, by_symbol: pd.DataFrame, by_year: pd.DataFrame) -> tuple[str, str]:
    core = metrics.loc[
        (metrics["return_basis"] == "open")
        & (metrics["outcome"] == "gap_continuation")
        & (metrics["horizon"].isin(["15min", "30min", "60min"]))
    ]
    if core.empty or core["available_count"].min() < 100:
        return "exploratoria_e_insuficiente", "muestra o disponibilidad insuficiente en horizontes centrales"
    mean_abs_bps = (core["mean_return"].abs() * 10000).max()
    symbol_signs = by_symbol.loc[
        (by_symbol["return_basis"] == "open")
        & (by_symbol["outcome"] == "gap_continuation")
        & (by_symbol["horizon"] == "30min")
    ]["mean_return"].dropna().map(np.sign).unique()
    year_positive = by_year.loc[
        (by_year["return_basis"] == "open")
        & (by_year["outcome"] == "gap_continuation")
        & (by_year["horizon"] == "30min")
    ]["mean_return"].dropna().map(np.sign)
    stable_years = int((year_positive == year_positive.mode().iloc[0]).sum()) if not year_positive.empty else 0
    if mean_abs_bps < 5 or len(symbol_signs) > 1 or stable_years < 2:
        return "rechazada", "efecto debil o inestable entre simbolos/anios"
    return (
        "elegible_para_futura_validacion",
        "senal retrospectiva razonablemente estable; requiere datos nuevos independientes",
    )


def write_hypothesis_outputs(
    *,
    hypothesis_id: str,
    events: pd.DataFrame,
    output_dir: Path,
    group_by: Sequence[str],
    preregistration_path: Path,
    inputs: Sequence[ResearchPoolInput],
    extra_config: Mapping[str, Any],
) -> dict[str, Path]:
    metrics = metric_table(events, hypothesis_id=hypothesis_id, group_by=group_by)
    by_symbol = metric_table(events, hypothesis_id=hypothesis_id, group_by=("symbol", *group_by))
    by_year = metric_table(events, hypothesis_id=hypothesis_id, group_by=("year", *group_by))
    by_month = metric_table(events, hypothesis_id=hypothesis_id, group_by=("month", *group_by))
    regime_group = tuple(dict.fromkeys((*group_by, "gap_size_bucket")))
    regimes = metric_table(events, hypothesis_id=hypothesis_id, group_by=regime_group)
    outliers = build_outlier_table(events, hypothesis_id)
    mfe_mae = events.loc[
        :,
        [
            "event_id",
            "symbol",
            "session_date",
            "gap_direction_label",
            "mfe_open_continuation",
            "mae_open_continuation",
            "opening_range_bucket",
            "gap_size_bucket",
            "is_early_close",
        ],
    ].copy()
    economics = build_economic_relevance(metrics)
    classification, reason = classify_hypothesis(metrics, by_symbol, by_year)
    config = {
        "hypothesis_id": hypothesis_id,
        "analysis_label": "retrospective_discovery_research_pool",
        "research_pool": {"start": "2022-01-01", "end": "2024-12-31"},
        "validation_2025_status": "previously_observed_hypothesis_generation_evidence_not_clean_validation",
        "holdout_2026_status": "closed_not_read_not_run",
        "preregistration_path": str(preregistration_path),
        "preregistration_sha256": sha256_file(preregistration_path),
        "safety_flags": dict(SAFETY_FLAGS),
        "inputs": [record.__dict__ for record in inputs],
        **dict(extra_config),
    }
    paths = {
        "events": _write_csv(output_dir / "events.csv", events),
        "metrics": _write_csv(output_dir / "metrics.csv", metrics),
        "metrics_by_symbol": _write_csv(output_dir / "metrics_by_symbol.csv", by_symbol),
        "metrics_by_year": _write_csv(output_dir / "metrics_by_year.csv", by_year),
        "metrics_by_month": _write_csv(output_dir / "metrics_by_month.csv", by_month),
        "regime_results": _write_csv(output_dir / "regime_results.csv", regimes),
        "outliers": _write_csv(output_dir / "outliers.csv", outliers),
        "mfe_mae": _write_csv(output_dir / "mfe_mae.csv", mfe_mae),
        "economic_relevance": _write_csv(output_dir / "economic_relevance.csv", economics),
    }
    config_path = output_dir / "config.json"
    _write_json(config_path, {**config, "classification": classification, "classification_reason": reason})
    paths["config"] = config_path
    manifest_path = output_dir / "run_manifest.json"
    _write_json(
        manifest_path,
        {
            "schema_version": 1,
            "run_id": f"{hypothesis_id}__retrospective_discovery__2022_2024__v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "hypothesis_id": hypothesis_id,
            "classification": classification,
            "classification_reason": reason,
            "event_count": int(events["event_id"].nunique()),
            "output_hashes": _hash_outputs(paths.values()),
            "safety_flags": dict(SAFETY_FLAGS),
            "validation_2025_used_as_clean_validation": False,
            "holdout_2026_opened": False,
            "broker_connected": False,
            "orders_sent": False,
        },
    )
    paths["run_manifest"] = manifest_path
    return paths


def write_reports(output_root: Path) -> None:
    asym_metrics = pd.read_csv(output_root / "HYP-GAP-ASYM-01" / "metrics.csv")
    asym_symbol = pd.read_csv(output_root / "HYP-GAP-ASYM-01" / "metrics_by_symbol.csv")
    asym_config = _json(output_root / "HYP-GAP-ASYM-01" / "config.json")
    or_metrics = pd.read_csv(output_root / "HYP-GAP-OR-01" / "metrics.csv")
    or_regimes = pd.read_csv(output_root / "HYP-GAP-OR-01" / "regime_results.csv")
    or_config = _json(output_root / "HYP-GAP-OR-01" / "config.json")

    def decorate(frame: pd.DataFrame) -> pd.DataFrame:
        data = frame.copy()
        for column in ("mean_return", "median_return", "bootstrap_ci_95_lower", "bootstrap_ci_95_upper"):
            if column in data.columns:
                data[column + "_bps"] = data[column].map(_bps)
        if "positive_rate" in data.columns:
            data["positive"] = data["positive_rate"].map(_pct)
        return data

    asym_core = decorate(
        asym_metrics.loc[
            (asym_metrics["return_basis"] == "open")
            & (asym_metrics["horizon"].isin(["15min", "30min", "60min", "session_close"]))
        ]
    )
    asym_symbol_core = decorate(
        asym_symbol.loc[
            (asym_symbol["return_basis"] == "open")
            & (asym_symbol["horizon"] == "30min")
        ]
    )
    or_core = decorate(
        or_metrics.loc[
            (or_metrics["return_basis"] == "open")
            & (or_metrics["horizon"] == "30min")
        ]
    )
    or_regime_core = decorate(
        or_regimes.loc[
            (or_regimes["return_basis"] == "open")
            & (or_regimes["outcome"] == "gap_continuation")
            & (or_regimes["horizon"] == "30min")
        ]
    )
    ASYM_REPORT.write_text(
        f"""# HYP-GAP-ASYM-01 Retrospective Results

Analysis label: retrospective discovery / research-pool analysis. This is not independent validation.

Classification: **{asym_config["classification"]}**. Reason: {asym_config["classification_reason"]}.

2025 was previously observed during HYP-GAP-03 validation and regime review, so it is hypothesis-generation evidence only. 2026 remains closed.

## Core Results

{_markdown_table(asym_core, ["gap_direction_label", "outcome", "horizon", "event_count", "mean_return_bps", "median_return_bps", "positive"], 20)}

## Symbol Check

{_markdown_table(asym_symbol_core, ["symbol", "gap_direction_label", "outcome", "event_count", "mean_return_bps", "median_return_bps", "positive"], 20)}

## Outputs

- `{output_root / "HYP-GAP-ASYM-01" / "events.csv"}`
- `{output_root / "HYP-GAP-ASYM-01" / "metrics.csv"}`
- `{output_root / "HYP-GAP-ASYM-01" / "metrics_by_symbol.csv"}`
- `{output_root / "HYP-GAP-ASYM-01" / "metrics_by_year.csv"}`
- `{output_root / "HYP-GAP-ASYM-01" / "outliers.csv"}`
- `{output_root / "HYP-GAP-ASYM-01" / "mfe_mae.csv"}`
- `{output_root / "HYP-GAP-ASYM-01" / "run_manifest.json"}`
""",
        encoding="utf-8",
    )
    OR_REPORT.write_text(
        f"""# HYP-GAP-OR-01 Retrospective Results

Analysis label: retrospective discovery / research-pool analysis. This is not independent validation.

Classification: **{or_config["classification"]}**. Reason: {or_config["classification_reason"]}.

Frozen tercile limits were calculated from 2022-2024 feature distributions before reading outcome summaries:

- opening_range_width_atr narrow <= {or_config["frozen_regime_limits"]["opening_range_width_atr"]["narrow_max"]:.6f}
- opening_range_width_atr wide >= {or_config["frozen_regime_limits"]["opening_range_width_atr"]["wide_min"]:.6f}
- normalized_gap small <= {or_config["frozen_regime_limits"]["normalized_gap"]["small_max"]:.6f}
- normalized_gap large >= {or_config["frozen_regime_limits"]["normalized_gap"]["large_min"]:.6f}

2025 was previously observed during HYP-GAP-03 regime review, so it is hypothesis-generation evidence only. 2026 remains closed.

## Core Results

{_markdown_table(or_core, ["gap_direction_label", "opening_range_bucket", "outcome", "event_count", "mean_return_bps", "median_return_bps", "positive"], 40)}

## Regime Results

{_markdown_table(or_regime_core, ["gap_direction_label", "opening_range_bucket", "gap_size_bucket", "event_count", "mean_return_bps", "median_return_bps", "positive"], 40)}

## Outputs

- `{output_root / "HYP-GAP-OR-01" / "events.csv"}`
- `{output_root / "HYP-GAP-OR-01" / "metrics.csv"}`
- `{output_root / "HYP-GAP-OR-01" / "metrics_by_symbol.csv"}`
- `{output_root / "HYP-GAP-OR-01" / "metrics_by_year.csv"}`
- `{output_root / "HYP-GAP-OR-01" / "regime_results.csv"}`
- `{output_root / "HYP-GAP-OR-01" / "outliers.csv"}`
- `{output_root / "HYP-GAP-OR-01" / "mfe_mae.csv"}`
- `{output_root / "HYP-GAP-OR-01" / "run_manifest.json"}`
""",
        encoding="utf-8",
    )
    PLAN_REPORT.write_text(
        f"""# Next Gap Hypotheses Research Plan

## Methodology Audit

2022-2024 has been observed for HYP-GAP discovery, S2/S5 discovery, and this retrospective research-pool analysis. It remains usable for exploratory replication and feature-threshold freezing only.

2025 has been observed for HYP-GAP-03 validation and exploratory regime review. The gap-up/gap-down asymmetry, normalized gap, opening range width, and quarterly diagnostics were inspected there, so 2025 cannot be reused as clean validation for HYP-GAP-ASYM-01 or HYP-GAP-OR-01.

2026 remains closed. No 2026 events, returns, charts, thresholds, summaries, or reports were generated by this task.

## Contamination Matrix

| Component | 2022-2024 | 2025 | 2026 | Future permitted use |
| --- | --- | --- | --- | --- |
| HYP-GAP original | Discovery observed | HYP-GAP-03 validation used HYP-GAP family context | Holdout closed | Exploratory only unless future data arrives |
| HYP-GAP-03 | Discovery observed | Validation opened and rejected | Holdout closed | Rejected; do not reopen with post hoc filters |
| Gap-up/gap-down | Observed in discovery outputs and this research pool | Inspected in regime review | Holdout closed | Hypothesis generation only; validate on new data |
| Gap normalized | Thresholds and regime cuts inspected | Regime cuts inspected | Holdout closed | Frozen descriptors only |
| Opening Range width | Existing OR work and HYP-GAP regime review observed | Regime review inspected | Holdout closed | Frozen terciles from 2022-2024 only |
| Results by quarter | Discovery/year stability observed | Q2 weakness inspected | Holdout closed | Descriptive only |
| QQQ | S2/S5 and HYP-GAP observed | HYP-GAP-03 validation observed | Holdout closed | Research pool only until new data |
| SPY | HYP-GAP observed | HYP-GAP-03 validation observed | Holdout closed | Research pool only until new data |

## Period Use

| Period | Status | Allowed now | Not allowed |
| --- | --- | --- | --- |
| 2022-2024 | contaminated discovery/research pool | Retrospective discovery, feature terciles, robustness diagnostics | Clean validation claims |
| 2025 | observed validation and hypothesis generation | Documentation as previously observed evidence | Independent validation for new hypotheses |
| 2026 | closed holdout | No use in this task | Any event, metric, threshold, chart, or strategy decision |

## Decisions

- HYP-GAP-ASYM-01: {asym_config["classification"]}; {asym_config["classification_reason"]}.
- HYP-GAP-OR-01: {or_config["classification"]}; {or_config["classification_reason"]}.

No strategy, stop, target, trailing stop, entry optimizer, broker integration, paper trading, or live trading was implemented.

## Future Validation Plan

If a hypothesis remains eligible, validation should wait for data collected after this freeze. Minimum gate: at least 100 new events per hypothesis or one full additional calendar year, whichever is stricter. 2026 should remain closed until an explicit future validation preregistration opens it; alternatively a liquid symbol not previously inspected, such as IWM or DIA, may be documented for external replication later, but no data was downloaded here.

## Reproducible Commands

- `.\\.venv\\Scripts\\python.exe -m unittest discover -s tests`
- `.\\.venv\\Scripts\\python.exe -m src.research.next_gap_hypotheses --output-root outputs\\next_gap_hypotheses_research_pool_v1`
- `git diff --check`
- `git status --short`

## Safety Flags

- live_trading=false
- broker_connected=false
- orders_sent=false
- paper_broker_enabled=false
""",
        encoding="utf-8",
    )


def run(output_root: Path = OUTPUT_ROOT) -> dict[str, Path]:
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {output_root}")
    events, inputs = build_research_pool_events()
    limits = compute_tercile_limits(events)
    events = apply_frozen_regime_limits(events, limits)
    asym_events = events.copy()
    or_events = events.copy()
    paths: dict[str, Path] = {}
    asym_paths = write_hypothesis_outputs(
        hypothesis_id="HYP-GAP-ASYM-01",
        events=asym_events,
        output_dir=output_root / "HYP-GAP-ASYM-01",
        group_by=("gap_direction_label",),
        preregistration_path=ASYM_CONFIG,
        inputs=inputs,
        extra_config={"frozen_regime_limits": limits},
    )
    or_paths = write_hypothesis_outputs(
        hypothesis_id="HYP-GAP-OR-01",
        events=or_events,
        output_dir=output_root / "HYP-GAP-OR-01",
        group_by=("gap_direction_label", "opening_range_bucket"),
        preregistration_path=OR_CONFIG,
        inputs=inputs,
        extra_config={"frozen_regime_limits": limits},
    )
    write_reports(output_root)
    paths.update({f"asym_{key}": value for key, value in asym_paths.items()})
    paths.update({f"or_{key}": value for key, value in or_paths.items()})
    paths["asym_report"] = ASYM_REPORT
    paths["or_report"] = OR_REPORT
    paths["plan_report"] = PLAN_REPORT
    return paths


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run next gap hypotheses research-pool analysis.")
    parser.add_argument("--output-root", default=str(OUTPUT_ROOT))
    args = parser.parse_args(argv)
    run(Path(args.output_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
