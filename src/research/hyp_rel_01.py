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
import yaml

from src.data import EquitySessionCalendar, load_csv, sha256_file
from src.research.qqq_s2_s5 import resample_rth_1min_to_5min


HYPOTHESIS_ID = "HYP-REL-01"
PREREGISTRATION_PATH = Path("configs/research/hypotheses/HYP-REL-01.yaml")
REPORT_PATH = Path("docs/HYP_REL_01_INTRADAY_DIVERGENCE_RESULTS.md")
OUTPUT_ROOT = Path("outputs/hyp_rel_01_intraday_divergence_v1")
SYMBOLS = ("QQQ", "SPY")
HORIZONS = ("5min", "15min", "30min", "60min", "session_close")
HORIZON_BARS = {"5min": 1, "15min": 3, "30min": 6, "60min": 12}
SAFETY_FLAGS = {
    "live_trading": False,
    "broker_connected": False,
    "orders_sent": False,
    "paper_broker_enabled": False,
}
DISCOVERY_YEARS = (2022, 2023, 2024)
VALIDATION_YEARS = (2025,)
DISCOVERY_START = "2022-01-01"
DISCOVERY_END = "2024-12-31"
VALIDATION_START = "2025-01-01"
VALIDATION_END = "2025-12-31"
HOLDOUT_START = "2026-01-01"
BOOTSTRAP_SEED = 20260721
BOOTSTRAP_ITERATIONS = 2000


@dataclass(frozen=True)
class DatasetInput:
    symbol: str
    year: int
    csv_path: Path
    manifest_path: Path
    dataset_sha256: str
    manifest_sha256: str
    dataset_status: str
    audit_critical_warnings: tuple[str, ...]


def _read_yaml(path: Path = PREREGISTRATION_PATH) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return payload


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _write_csv(path: Path, frame: pd.DataFrame) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return path


def _localize(timestamp: pd.Timestamp, calendar: EquitySessionCalendar) -> pd.Timestamp:
    return pd.Timestamp(timestamp).tz_convert(calendar.timezone)


def _session_date(timestamp: pd.Timestamp, calendar: EquitySessionCalendar) -> str:
    return _localize(timestamp, calendar).date().isoformat()


def _clock(timestamp: pd.Timestamp, calendar: EquitySessionCalendar) -> time:
    return _localize(timestamp, calendar).time().replace(tzinfo=None)


def _period_years(period: str) -> tuple[int, ...]:
    if period == "discovery":
        return DISCOVERY_YEARS
    if period == "validation":
        return VALIDATION_YEARS
    raise ValueError(f"Unsupported period: {period}")


def _excluded_sessions(symbol: str) -> set[str]:
    path = Path("data/quality_overrides/excluded_sessions.json")
    if not path.exists():
        return set()
    payload = _read_json(path)
    return {
        str(record["date"])
        for record in payload.get("excluded_sessions", [])
        if str(record.get("symbol", "")).upper() == symbol
    }


def dataset_input(symbol: str, year: int) -> DatasetInput:
    csv_path = Path(f"data/raw/{symbol}_1min_{year}-01-01_{year}-12-31_alpaca_sip_raw_rth.csv")
    manifest_path = Path(f"data/manifests/{symbol}_1min_{year}-01-01_{year}-12-31_alpaca_sip_raw_rth_manifest.json")
    manifest = _read_json(manifest_path)
    if manifest.get("symbol") != symbol or manifest.get("timeframe") != "1min":
        raise ValueError(f"Manifest mismatch for {symbol} {year}")
    expected_hash = sha256_file(csv_path)
    if manifest.get("sha256") != expected_hash:
        raise ValueError(f"Dataset sha256 mismatch for {csv_path}")
    warnings = tuple(str(item) for item in manifest.get("audit_critical_warnings", []))
    if manifest.get("dataset_status") != "approved_for_or_fvg_backtest":
        allowed_spy_2023 = symbol == "SPY" and year == 2023 and "2023-06-05" in _excluded_sessions(symbol)
        if not allowed_spy_2023:
            raise ValueError(f"Dataset is not approved for HYP-REL-01: {manifest_path}")
    return DatasetInput(
        symbol=symbol,
        year=year,
        csv_path=csv_path,
        manifest_path=manifest_path,
        dataset_sha256=expected_hash,
        manifest_sha256=sha256_file(manifest_path),
        dataset_status=str(manifest.get("dataset_status")),
        audit_critical_warnings=warnings,
    )


def load_symbol_5min(symbol: str, years: Sequence[int]) -> tuple[pd.DataFrame, list[DatasetInput]]:
    calendar = EquitySessionCalendar.from_config({"source": "us_equity"})
    excluded = _excluded_sessions(symbol)
    frames: list[pd.DataFrame] = []
    inputs: list[DatasetInput] = []
    for year in years:
        item = dataset_input(symbol, year)
        frame, report = load_csv(
            item.csv_path,
            "1min",
            asset_class="equity",
            drop_incomplete=False,
            calendar=calendar,
            excluded_session_dates=excluded,
        )
        if not report.is_valid:
            raise ValueError(f"{symbol} {year} failed OHLCV validation after approved exclusions")
        frame = frame.assign(_session_date=[_session_date(value, calendar) for value in frame["timestamp"]])
        frame = frame.loc[~frame["_session_date"].isin(excluded)].reset_index(drop=True)
        bars = resample_rth_1min_to_5min(frame, calendar)
        bars["symbol"] = symbol
        bars["session_date"] = [_session_date(value, calendar) for value in bars["timestamp"]]
        bars["bar_time"] = [_clock(value, calendar).strftime("%H:%M") for value in bars["timestamp"]]
        bars["bar_index"] = bars.groupby("session_date").cumcount()
        frames.append(bars)
        inputs.append(item)
    combined = pd.concat(frames, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
    if combined["session_date"].ge(HOLDOUT_START).any():
        raise ValueError("HYP-REL-01 attempted to load holdout rows")
    return combined, inputs


def synchronize_pair(
    qqq: pd.DataFrame,
    spy: pd.DataFrame,
    *,
    calendar: EquitySessionCalendar | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    calendar = calendar or EquitySessionCalendar.from_config({"source": "us_equity"})
    q = qqq.add_prefix("qqq_").rename(columns={"qqq_timestamp": "timestamp"})
    s = spy.add_prefix("spy_").rename(columns={"spy_timestamp": "timestamp"})
    pair = q.merge(s, on="timestamp", how="inner")
    pair["session_date"] = [_session_date(value, calendar) for value in pair["timestamp"]]
    pair["bar_time"] = [_clock(value, calendar).strftime("%H:%M") for value in pair["timestamp"]]
    pair["bar_index"] = pair.groupby("session_date").cumcount()
    pair = pair.sort_values("timestamp").reset_index(drop=True)
    pair["qqq_log_return_5m"] = np.log(pair["qqq_close"].astype(float) / pair["qqq_close"].shift(1).astype(float))
    pair["spy_log_return_5m"] = np.log(pair["spy_close"].astype(float) / pair["spy_close"].shift(1).astype(float))
    new_session = pair["session_date"].ne(pair["session_date"].shift(1))
    pair.loc[new_session, ["qqq_log_return_5m", "spy_log_return_5m"]] = np.nan
    expected_sessions = set(qqq["session_date"]).union(set(spy["session_date"]))
    common_sessions = set(pair["session_date"])
    diagnostics = pd.DataFrame(
        [
            {
                "session_date": day,
                "qqq_5m_bars": int((qqq["session_date"] == day).sum()),
                "spy_5m_bars": int((spy["session_date"] == day).sum()),
                "common_5m_bars": int((pair["session_date"] == day).sum()),
                "status": "common" if day in common_sessions else "dropped_not_common",
            }
            for day in sorted(expected_sessions)
        ]
    )
    return pair, diagnostics


def prepare_pair_data(period: str) -> tuple[pd.DataFrame, pd.DataFrame, list[DatasetInput]]:
    years = _period_years(period)
    qqq, q_inputs = load_symbol_5min("QQQ", years)
    spy, s_inputs = load_symbol_5min("SPY", years)
    pair, sync = synchronize_pair(qqq, spy)
    return pair, sync, [*q_inputs, *s_inputs]


def estimate_beta(prior: pd.DataFrame) -> tuple[float | None, int]:
    clean = prior[["qqq_log_return_5m", "spy_log_return_5m"]].dropna()
    if len(clean) < 1000:
        return None, int(len(clean))
    denominator = float((clean["spy_log_return_5m"] ** 2).sum())
    if denominator <= 0:
        return None, int(len(clean))
    return float((clean["qqq_log_return_5m"] * clean["spy_log_return_5m"]).sum() / denominator), int(len(clean))


def _session_order(pair: pd.DataFrame) -> list[str]:
    return sorted(pair["session_date"].dropna().unique())


def _prior_sessions(day: str, sessions: Sequence[str], count: int = 20) -> list[str]:
    index = sessions.index(day)
    if index < count:
        return []
    return list(sessions[index - count : index])


def add_causal_divergence_features(pair: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    sessions = _session_order(pair)
    records: list[pd.DataFrame] = []
    blocked: list[dict[str, Any]] = []
    for day in sessions:
        prior_days = _prior_sessions(day, sessions, 20)
        current = pair.loc[pair["session_date"] == day].copy()
        if len(prior_days) < 20:
            current["beta"] = np.nan
            current["relative_residual"] = np.nan
            current["z_score"] = np.nan
            blocked.append({"session_date": day, "reason": "insufficient_prior_sessions", "bar_time": ""})
            records.append(current)
            continue
        prior = pair.loc[pair["session_date"].isin(prior_days)].copy()
        beta, beta_observations = estimate_beta(prior)
        current["beta"] = beta
        current["beta_observations"] = beta_observations
        current["qqq_log_return_30m"] = np.log(current["qqq_close"] / current["qqq_close"].shift(6))
        current["spy_log_return_30m"] = np.log(current["spy_close"] / current["spy_close"].shift(6))
        current["relative_residual"] = current["qqq_log_return_30m"] - float(beta or np.nan) * current["spy_log_return_30m"]
        prior_for_z = prior.copy()
        prior_for_z["qqq_30"] = np.log(
            prior_for_z["qqq_close"] / prior_for_z.groupby("session_date")["qqq_close"].shift(6)
        )
        prior_for_z["spy_30"] = np.log(
            prior_for_z["spy_close"] / prior_for_z.groupby("session_date")["spy_close"].shift(6)
        )
        prior_for_z["prior_residual_30m"] = prior_for_z["qqq_30"] - float(beta or np.nan) * prior_for_z["spy_30"]
        z_values = []
        for _, row in current.iterrows():
            if beta is None or pd.isna(row["relative_residual"]):
                z_values.append(np.nan)
                continue
            prior_residuals = prior_for_z.loc[
                prior_for_z["bar_index"] == int(row["bar_index"]),
                "prior_residual_30m",
            ].dropna()
            if len(prior_residuals) < 15 or float(prior_residuals.std(ddof=1)) <= 0:
                z_values.append(np.nan)
                blocked.append({"session_date": day, "bar_time": row["bar_time"], "reason": "insufficient_zscore_history"})
                continue
            z_values.append(float((row["relative_residual"] - prior_residuals.mean()) / prior_residuals.std(ddof=1)))
        current["z_score"] = z_values
        records.append(current)
    return pd.concat(records, ignore_index=True), pd.DataFrame(blocked)


def _future_index(frame: pd.DataFrame, idx: int, horizon: str) -> int | None:
    if horizon == "session_close":
        return int(frame.index[-1])
    target = idx + HORIZON_BARS[horizon]
    if target >= len(frame):
        return None
    return int(target)


def _relative_future_return(row: pd.Series, future: pd.Series) -> tuple[float, float, float]:
    q_ret = float(np.log(future["qqq_close"] / row["qqq_close"]))
    s_ret = float(np.log(future["spy_close"] / row["spy_close"]))
    relative = q_ret - float(row["beta"]) * s_ret
    return q_ret, s_ret, relative


def detect_events(features: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    emitted: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    enabled_start = time.fromisoformat("10:00")
    enabled_end = time.fromisoformat("15:00")
    for day, session in features.groupby("session_date", sort=True):
        session = session.reset_index(drop=True)
        last_event_idx: int | None = None
        direction_seen: set[str] = set()
        for idx, row in session.iterrows():
            clock = time.fromisoformat(str(row["bar_time"]))
            if clock < enabled_start or clock > enabled_end:
                continue
            if pd.isna(row["z_score"]) or pd.isna(row["beta"]):
                blocked.append({"session_date": day, "bar_time": row["bar_time"], "reason": "missing_causal_zscore"})
                continue
            direction = "qqq_overperformance" if float(row["z_score"]) >= 2.0 else "qqq_underperformance" if float(row["z_score"]) <= -2.0 else ""
            if not direction:
                continue
            if direction in direction_seen:
                blocked.append({"session_date": day, "bar_time": row["bar_time"], "reason": "direction_daily_limit"})
                continue
            if last_event_idx is not None and idx - last_event_idx < 12:
                blocked.append({"session_date": day, "bar_time": row["bar_time"], "reason": "cooldown_60_minutes"})
                continue
            future_rows: dict[str, pd.Series] = {}
            missing = []
            for horizon in HORIZONS:
                target = _future_index(session, idx, horizon)
                if target is None:
                    missing.append(horizon)
                else:
                    future_rows[horizon] = session.iloc[target]
            if missing:
                blocked.append({"session_date": day, "bar_time": row["bar_time"], "reason": "missing_future_horizon", "horizons": ",".join(missing)})
                continue
            sign = 1 if direction == "qqq_overperformance" else -1
            record: dict[str, Any] = {
                "event_id": f"{HYPOTHESIS_ID}:{day}:{direction}",
                "hypothesis_id": HYPOTHESIS_ID,
                "session_date": day,
                "timestamp": row["timestamp"],
                "bar_time": row["bar_time"],
                "year": int(str(day)[:4]),
                "month": str(day)[:7],
                "hour": str(row["bar_time"])[:2] + ":00",
                "direction": direction,
                "direction_sign": sign,
                "z_score": float(row["z_score"]),
                "beta": float(row["beta"]),
                "beta_observations": int(row["beta_observations"]),
                "relative_residual": float(row["relative_residual"]),
                "qqq_close": float(row["qqq_close"]),
                "spy_close": float(row["spy_close"]),
            }
            future_relative_path = []
            for horizon, future in future_rows.items():
                q_ret, s_ret, relative = _relative_future_return(row, future)
                record[f"qqq_future_return_{horizon}"] = q_ret
                record[f"spy_future_return_{horizon}"] = s_ret
                record[f"relative_future_return_{horizon}"] = relative
                record[f"continuation_return_{horizon}"] = relative * sign
                record[f"mean_reversion_return_{horizon}"] = -relative * sign
                future_relative_path.append((horizon, relative * sign))
            after = session.iloc[idx + 1 :].copy()
            signed_path = []
            convergence_minutes = None
            for step, (_, future_row) in enumerate(after.iterrows(), start=1):
                _, _, relative = _relative_future_return(row, future_row)
                signed = relative * sign
                signed_path.append(signed)
                if convergence_minutes is None and signed <= 0:
                    convergence_minutes = step * 5
            record["continuation_mfe"] = float(max(signed_path)) if signed_path else np.nan
            record["continuation_mae"] = float(min(signed_path)) if signed_path else np.nan
            record["mean_reversion_mfe"] = float(max([-value for value in signed_path])) if signed_path else np.nan
            record["mean_reversion_mae"] = float(min([-value for value in signed_path])) if signed_path else np.nan
            record["time_to_convergence_minutes"] = convergence_minutes
            emitted.append(record)
            direction_seen.add(direction)
            last_event_idx = idx
    return pd.DataFrame(emitted), pd.DataFrame(blocked)


def _bootstrap_ci(values: pd.Series, sessions: pd.Series) -> tuple[float | None, float | None]:
    clean = pd.DataFrame({"value": values, "session": sessions}).dropna()
    if clean.empty:
        return None, None
    session_means = clean.groupby("session")["value"].mean().to_numpy(dtype=float)
    if len(session_means) == 1:
        value = float(session_means[0])
        return value, value
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = rng.choice(session_means, size=(BOOTSTRAP_ITERATIONS, len(session_means)), replace=True).mean(axis=1)
    return float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))


def _metric_summary(values: pd.Series, sessions: pd.Series) -> dict[str, Any]:
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
            "favorable_rate": None,
            "p01": None,
            "p05": None,
            "p25": None,
            "p75": None,
            "p95": None,
            "p99": None,
            "winsor_1pct_mean_return": None,
            "winsor_5pct_mean_return": None,
            "exclude_top_bottom_5_mean_return": None,
            "autocorrelation_lag1": None,
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
        "favorable_rate": float((clean > 0).mean()),
        "p01": float(clean.quantile(0.01)),
        "p05": float(clean.quantile(0.05)),
        "p25": float(clean.quantile(0.25)),
        "p75": float(clean.quantile(0.75)),
        "p95": float(clean.quantile(0.95)),
        "p99": float(clean.quantile(0.99)),
        "winsor_1pct_mean_return": float(clean.clip(clean.quantile(0.01), clean.quantile(0.99)).mean()),
        "winsor_5pct_mean_return": float(clean.clip(clean.quantile(0.05), clean.quantile(0.95)).mean()),
        "exclude_top_bottom_5_mean_return": float(trimmed.mean()) if not trimmed.empty else None,
        "autocorrelation_lag1": float(clean.autocorr(lag=1)) if len(clean) > 2 else None,
    }


def build_metrics(events: pd.DataFrame, group_by: Sequence[str] = ()) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for interpretation in ("mean_reversion", "continuation"):
        for horizon in HORIZONS:
            column = f"{interpretation}_return_{horizon}"
            if group_by:
                for keys, subset in events.groupby(list(group_by), dropna=False, sort=True):
                    if not isinstance(keys, tuple):
                        keys = (keys,)
                    record = dict(zip(group_by, keys))
                    record.update({"interpretation": interpretation, "horizon": horizon})
                    record.update(_metric_summary(subset[column], subset["session_date"]))
                    rows.append(record)
            else:
                record = {"interpretation": interpretation, "horizon": horizon}
                record.update(_metric_summary(events[column], events["session_date"]))
                rows.append(record)
    return pd.DataFrame(rows)


def build_outliers(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for interpretation in ("mean_reversion", "continuation"):
        for horizon in HORIZONS:
            column = f"{interpretation}_return_{horizon}"
            available = events.loc[events[column].notna()].sort_values(column)
            for tail, subset in (("worst", available.head(10)), ("best", available.tail(10).iloc[::-1])):
                for rank, row in enumerate(subset.to_dict("records"), start=1):
                    rows.append(
                        {
                            "interpretation": interpretation,
                            "horizon": horizon,
                            "tail": tail,
                            "rank": rank,
                            "event_id": row["event_id"],
                            "session_date": row["session_date"],
                            "direction": row["direction"],
                            "return": row[column],
                            "return_bps": row[column] * 10000,
                        }
                    )
    return pd.DataFrame(rows)


def build_cost_relevance(metrics: pd.DataFrame) -> pd.DataFrame:
    scenarios = {
        "low": {"commission_bps_per_leg": 0.2, "spread_bps_per_leg": 0.5, "slippage_bps_per_leg": 0.5, "delay_bps": 0.5},
        "normal": {"commission_bps_per_leg": 0.5, "spread_bps_per_leg": 1.0, "slippage_bps_per_leg": 1.0, "delay_bps": 1.0},
        "high": {"commission_bps_per_leg": 1.0, "spread_bps_per_leg": 2.0, "slippage_bps_per_leg": 2.0, "delay_bps": 2.0},
    }
    rows = []
    base = metrics.loc[metrics["interpretation"].isin(["mean_reversion", "continuation"])].copy()
    for _, row in base.iterrows():
        mean_bps = None if pd.isna(row["mean_return"]) else float(row["mean_return"]) * 10000
        median_bps = None if pd.isna(row["median_return"]) else float(row["median_return"]) * 10000
        for name, costs in scenarios.items():
            friction = 2 * (
                costs["commission_bps_per_leg"] + costs["spread_bps_per_leg"] + costs["slippage_bps_per_leg"]
            ) + costs["delay_bps"]
            rows.append(
                {
                    "interpretation": row["interpretation"],
                    "horizon": row["horizon"],
                    "scenario": name,
                    **costs,
                    "two_leg_friction_bps": friction,
                    "gross_mean_bps": mean_bps,
                    "gross_median_bps": median_bps,
                    "net_mean_bps": None if mean_bps is None else mean_bps - friction,
                    "net_median_bps": None if median_bps is None else median_bps - friction,
                    "friction_absorbed_mean_pct": None if not mean_bps else abs(friction / mean_bps),
                }
            )
    return pd.DataFrame(rows)


def classify_discovery(events: pd.DataFrame, metrics: pd.DataFrame, by_year: pd.DataFrame, by_direction: pd.DataFrame, costs: pd.DataFrame) -> tuple[str, str, bool]:
    core = metrics.loc[(metrics["interpretation"] == "mean_reversion") & (metrics["horizon"] == "30min")]
    if events.empty or int(core["available_count"].iloc[0]) < 150:
        return "exploratoria_e_insuficiente", "menos de 150 eventos validos", False
    mean_value = float(core["mean_return"].iloc[0])
    median_value = float(core["median_return"].iloc[0])
    if np.sign(mean_value) != np.sign(median_value) or mean_value <= 0:
        return "rechazada", "media y mediana no apoyan mean reversion relativa", False
    yearly = by_year.loc[(by_year["interpretation"] == "mean_reversion") & (by_year["horizon"] == "30min")]
    positive_years = int((yearly["mean_return"].astype(float) > 0).sum())
    directions = by_direction.loc[(by_direction["interpretation"] == "mean_reversion") & (by_direction["horizon"] == "30min")]
    stable_directions = bool((directions["mean_return"].astype(float) > 0).all())
    normal_cost = costs.loc[
        (costs["interpretation"] == "mean_reversion")
        & (costs["horizon"] == "30min")
        & (costs["scenario"] == "normal")
    ]
    survives_cost = bool(float(normal_cost["net_mean_bps"].iloc[0]) > 0) if not normal_cost.empty else False
    winsor_ok = bool(float(core["winsor_5pct_mean_return"].iloc[0]) > 0)
    if positive_years >= 2 and stable_directions and survives_cost and winsor_ok:
        return "candidata_a_validation", "discovery pasa los criterios preregistrados principales", True
    return "exploratoria_e_insuficiente", "hay senal parcial, pero no cumple estabilidad/costos/direcciones", False


def contamination_audit() -> dict[str, Any]:
    return {
        "spreads_qqq_spy_previously_inspected": False,
        "relative_returns_qqq_minus_spy_previously_inspected": False,
        "intraday_betas_previously_inspected": False,
        "divergence_zscores_previously_inspected": False,
        "convergence_or_continuation_previously_inspected": False,
        "conceptual_protocol_mentions": [
            "docs/INTRADAY_HYPOTHESIS_REFINEMENT_PROTOCOL.md mentions HYP-CROSS cross-confirmation/divergence conceptually."
        ],
        "validation_2025_classification": "validation_elegible_with_documented_conceptual_prior",
        "rationale": "Prior research used QQQ and SPY prices in other families, but no prior output found with QQQ/SPY spread, beta, z-score divergence, or relative convergence event study.",
    }


def _hash_paths(paths: Iterable[Path]) -> dict[str, str]:
    return {str(path): sha256_file(path) for path in paths if path.exists() and path.is_file()}


def _serialize(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    for column in data.columns:
        if "timestamp" in column:
            data[column] = pd.to_datetime(data[column], utc=True, errors="coerce").map(
                lambda value: value.isoformat() if pd.notna(value) else ""
            )
    return data


def run_period(period: str, output_dir: Path) -> dict[str, Any]:
    pair, sync, inputs = prepare_pair_data(period)
    features, feature_blocked = add_causal_divergence_features(pair)
    events, event_blocked = detect_events(features)
    blocked = pd.concat([feature_blocked, event_blocked], ignore_index=True)
    metrics = build_metrics(events)
    by_direction = build_metrics(events, ("direction",))
    by_year = build_metrics(events, ("year",))
    by_month = build_metrics(events, ("month",))
    by_time = build_metrics(events, ("hour",))
    outliers = build_outliers(events)
    mfe_mae = events.loc[
        :,
        [
            "event_id",
            "session_date",
            "direction",
            "continuation_mfe",
            "continuation_mae",
            "mean_reversion_mfe",
            "mean_reversion_mae",
            "time_to_convergence_minutes",
        ],
    ].copy() if not events.empty else pd.DataFrame()
    costs = build_cost_relevance(metrics)
    classification, reason, opens_validation = (
        classify_discovery(events, metrics, by_year, by_direction, costs)
        if period == "discovery"
        else ("validation_observed", "validation executed with frozen parameters", False)
    )
    paths = {
        "events": _write_csv(output_dir / "events.csv", _serialize(events)),
        "metrics": _write_csv(output_dir / "metrics.csv", metrics),
        "metrics_by_direction": _write_csv(output_dir / "metrics_by_direction.csv", by_direction),
        "metrics_by_year": _write_csv(output_dir / "metrics_by_year.csv", by_year),
        "metrics_by_month": _write_csv(output_dir / "metrics_by_month.csv", by_month),
        "metrics_by_time_of_day": _write_csv(output_dir / "metrics_by_time_of_day.csv", by_time),
        "outliers": _write_csv(output_dir / "outliers.csv", outliers),
        "mfe_mae": _write_csv(output_dir / "mfe_mae.csv", mfe_mae),
        "cost_relevance": _write_csv(output_dir / "cost_relevance.csv", costs),
        "blocked_events": _write_csv(output_dir / "blocked_events.csv", blocked),
        "sync_diagnostics": _write_csv(output_dir / "sync_diagnostics.csv", sync),
    }
    config = {
        "hypothesis_id": HYPOTHESIS_ID,
        "period": period,
        "classification": classification,
        "classification_reason": reason,
        "opens_validation": opens_validation,
        "preregistration_path": str(PREREGISTRATION_PATH),
        "preregistration_sha256": sha256_file(PREREGISTRATION_PATH),
        "contamination_audit": contamination_audit(),
        "inputs": [item.__dict__ for item in inputs],
        "safety_flags": dict(SAFETY_FLAGS),
        "holdout_2026_opened": False,
    }
    config_path = output_dir / "config.json"
    _write_json(config_path, config)
    paths["config"] = config_path
    manifest_path = output_dir / "run_manifest.json"
    _write_json(
        manifest_path,
        {
            "schema_version": 1,
            "run_id": f"{HYPOTHESIS_ID}__{period}__v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "hypothesis_id": HYPOTHESIS_ID,
            "period": period,
            "event_count": int(len(events)),
            "classification": classification,
            "classification_reason": reason,
            "output_hashes": _hash_paths(paths.values()),
            "validation_2025_eligible": contamination_audit()["validation_2025_classification"],
            "holdout_2026_events": 0,
            "holdout_2026_metrics": 0,
            "holdout_2026_thresholds": 0,
            "safety_flags": dict(SAFETY_FLAGS),
            "broker_connected": False,
            "orders_sent": False,
        },
    )
    paths["run_manifest"] = manifest_path
    return {
        "paths": paths,
        "events": events,
        "metrics": metrics,
        "by_year": by_year,
        "by_direction": by_direction,
        "costs": costs,
        "classification": classification,
        "classification_reason": reason,
        "opens_validation": opens_validation,
    }


def _bps(value: Any) -> str:
    if pd.isna(value):
        return ""
    return f"{float(value) * 10000:.2f}"


def _pct(value: Any) -> str:
    if pd.isna(value):
        return ""
    return f"{float(value) * 100:.1f}%"


def _markdown_table(frame: pd.DataFrame, columns: Sequence[str], limit: int | None = None) -> str:
    data = frame.loc[:, list(columns)].head(limit).copy() if limit else frame.loc[:, list(columns)].copy()
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for _, row in data.iterrows():
        lines.append("| " + " | ".join(str(row[column]) for column in columns) + " |")
    return "\n".join(lines)


def write_report(output_root: Path, discovery: Mapping[str, Any], validation: Mapping[str, Any] | None) -> Path:
    metrics = discovery["metrics"].copy()
    metrics["mean_bps"] = metrics["mean_return"].map(_bps)
    metrics["median_bps"] = metrics["median_return"].map(_bps)
    metrics["favorable"] = metrics["favorable_rate"].map(_pct)
    direction = discovery["by_direction"].copy()
    direction["mean_bps"] = direction["mean_return"].map(_bps)
    direction["median_bps"] = direction["median_return"].map(_bps)
    direction["favorable"] = direction["favorable_rate"].map(_pct)
    yearly = discovery["by_year"].copy()
    yearly["mean_bps"] = yearly["mean_return"].map(_bps)
    yearly["median_bps"] = yearly["median_return"].map(_bps)
    yearly["favorable"] = yearly["favorable_rate"].map(_pct)
    costs = discovery["costs"].copy()
    for column in ("gross_mean_bps", "gross_median_bps", "net_mean_bps", "net_median_bps"):
        costs[column] = costs[column].map(lambda value: "" if pd.isna(value) else f"{float(value):.2f}")
    validation_text = "Validation was not executed because discovery did not pass the preregistered gate."
    if validation is not None:
        validation_text = "Validation 2025 was executed with frozen parameters because discovery passed the gate."
    report = f"""# HYP-REL-01 Intraday Relative Divergence Results

## Reuse Audit

| Componente necesario | Codigo reutilizable | Archivo | Cambio requerido |
| --- | --- | --- | --- |
| OHLCV loading and validation | `load_csv` | `src/data/loader.py` | Reused |
| US equity RTH calendar, holidays, early closes, DST | `EquitySessionCalendar` | `src/data/sessions.py` | Reused |
| 1m to 5m RTH resampling | `resample_rth_1min_to_5min` | `src/research/qqq_s2_s5.py` | Reused |
| Dataset hashes/manifests | `sha256_file` and manifest records | `src/data/dataset_manifest.py` | Reused |
| Event-study style aggregation | mean/median/CI/bootstrap pattern | `src/research/event_study.py`; prior research runners | New relative-return wrapper |
| Reports and manifests | CSV/JSON/Markdown pattern | prior research runners | New HYP-REL-01 runner |

## Contamination Audit

2025 classification: **{contamination_audit()["validation_2025_classification"]}**.

The audit found no prior calculated QQQ/SPY spread, QQQ minus SPY relative return event study, intraday beta, divergence z-score, or relative convergence/continuation result. A protocol document mentioned QQQ/SPY cross-confirmation/divergence conceptually, so the prior is documented, but 2025 remains methodologically eligible if discovery passes.

## Discovery Decision

Classification: **{discovery["classification"]}**.

Reason: {discovery["classification_reason"]}.

{validation_text}

## Discovery Core Metrics

{_markdown_table(metrics, ["interpretation", "horizon", "event_count", "mean_bps", "median_bps", "favorable"], 20)}

## Direction Stability

{_markdown_table(direction.loc[direction["horizon"] == "30min"], ["direction", "interpretation", "event_count", "mean_bps", "median_bps", "favorable"], 20)}

## Year Stability

{_markdown_table(yearly.loc[(yearly["horizon"] == "30min") & (yearly["interpretation"] == "mean_reversion")], ["year", "event_count", "mean_bps", "median_bps", "favorable"], 10)}

## Two-Leg Cost Relevance

{_markdown_table(costs.loc[costs["horizon"] == "30min"], ["interpretation", "scenario", "two_leg_friction_bps", "gross_mean_bps", "gross_median_bps", "net_mean_bps", "net_median_bps"], 20)}

## Holdout 2026

2026 remains closed:

- 0 events of 2026.
- 0 metrics of 2026.
- 0 thresholds calculated with 2026.
- 0 charts with 2026.
- 0 decisions based on 2026.

## Outputs

- `{output_root / "discovery" / "events.csv"}`
- `{output_root / "discovery" / "metrics.csv"}`
- `{output_root / "discovery" / "metrics_by_direction.csv"}`
- `{output_root / "discovery" / "metrics_by_year.csv"}`
- `{output_root / "discovery" / "metrics_by_month.csv"}`
- `{output_root / "discovery" / "metrics_by_time_of_day.csv"}`
- `{output_root / "discovery" / "outliers.csv"}`
- `{output_root / "discovery" / "mfe_mae.csv"}`
- `{output_root / "discovery" / "cost_relevance.csv"}`
- `{output_root / "discovery" / "blocked_events.csv"}`
- `{output_root / "discovery" / "config.json"}`
- `{output_root / "discovery" / "run_manifest.json"}`

## Commands

- `.\\.venv\\Scripts\\python.exe -m unittest discover -s tests`
- `.\\.venv\\Scripts\\python.exe -m src.research.hyp_rel_01 --output-root {output_root}`
- `git diff --check`
- `git status --short`

## Safety

- live_trading=false
- broker_connected=false
- orders_sent=false
- paper_broker_enabled=false
"""
    REPORT_PATH.write_text(report, encoding="utf-8")
    return REPORT_PATH


def run(output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {output_root}")
    prereg = _read_yaml(PREREGISTRATION_PATH)
    if prereg.get("hypothesis_id") != HYPOTHESIS_ID:
        raise ValueError("Invalid HYP-REL-01 preregistration")
    discovery = run_period("discovery", output_root / "discovery")
    validation = None
    if discovery["opens_validation"] and contamination_audit()["validation_2025_classification"].startswith("validation_elegible"):
        validation = run_period("validation", output_root / "validation")
    report = write_report(output_root, discovery, validation)
    return {"discovery": discovery, "validation": validation, "report": report}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run HYP-REL-01 QQQ/SPY intraday divergence event study.")
    parser.add_argument("--output-root", default=str(OUTPUT_ROOT))
    args = parser.parse_args(argv)
    run(Path(args.output_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
