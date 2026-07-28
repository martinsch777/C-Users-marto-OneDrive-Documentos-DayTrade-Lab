from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.research.hyp_or_cont_event_01 import (
    aggregate_incremental_metrics_reference,
    compute_aggregation_and_bootstrap_outputs,
)


def _synthetic_path_metrics(*, sessions: int) -> pd.DataFrame:
    rows: list[dict] = []
    for session_number in range(sessions):
        day = pd.Timestamp("2024-01-02") + pd.offsets.Day(session_number)
        date = day.strftime("%Y-%m-%d")
        for symbol in ("QQQ",):
            symbol_offset = 0.0002 if symbol == "QQQ" else 0.00035
            for orientation in ("continuation_long",):
                orientation_sign = 1.0 if orientation == "continuation_long" else -1.0
                for horizon_index, horizon in enumerate(("30min",)):
                    base_return = symbol_offset + horizon_index * 0.0001 + session_number * 0.00001
                    event_return = base_return * orientation_sign
                    rows.append(
                        {
                            "symbol": symbol,
                            "session_date": date,
                            "executable_timestamp": pd.Timestamp(f"{date} 10:00", tz="America/New_York").tz_convert("UTC"),
                            "direction_orientation": orientation,
                            "year": 2024,
                            "executable_timestamp_hour_bucket": "10:00",
                            "horizon": horizon,
                            "event_return": event_return,
                            "unconditional_return": event_return / 2.0,
                            "incremental_return": event_return / 2.0,
                            "maximum_favorable_excursion": abs(event_return) + 0.002,
                            "maximum_adverse_excursion": -abs(event_return) - 0.001,
                            "baseline_cost_return": 0.0004,
                            "stress_cost_return": 0.0008,
                        }
                    )
    return pd.DataFrame(rows)


def _reference_outputs(path_metrics: pd.DataFrame, *, n_bootstrap: int, seed: int) -> dict:
    incremental = aggregate_incremental_metrics_reference(
        path_metrics,
        group_by=("symbol", "direction_orientation", "horizon"),
        n_bootstrap=n_bootstrap,
        seed=seed,
    )
    by_symbol = aggregate_incremental_metrics_reference(path_metrics, group_by=("symbol",), n_bootstrap=n_bootstrap, seed=seed)
    by_year = aggregate_incremental_metrics_reference(path_metrics, group_by=("year",), n_bootstrap=n_bootstrap, seed=seed)
    return {"incremental_metrics": incremental, "metrics_by_symbol": by_symbol, "metrics_by_year": by_year}


def _time_call(func, *args, **kwargs):
    start = time.perf_counter()
    result = func(*args, **kwargs)
    return result, time.perf_counter() - start


def _max_delta(reference: dict, optimized: dict) -> float:
    deltas: list[float] = []
    for key in ("incremental_metrics", "metrics_by_symbol", "metrics_by_year"):
        left = reference[key].select_dtypes(include=[np.number]).reset_index(drop=True)
        right = optimized[key].select_dtypes(include=[np.number]).reset_index(drop=True)
        deltas.append(float((left - right).abs().max().max()))
    return max(deltas) if deltas else 0.0


def run_benchmark(*, n_bootstrap: int = 500, seed: int = 17) -> dict:
    results = []
    elapsed_total = 0.0
    for sessions in (8, 16, 32):
        if sessions == 32 and elapsed_total > 12.0:
            break
        path_metrics = _synthetic_path_metrics(sessions=sessions)
        reference, reference_seconds = _time_call(_reference_outputs, path_metrics, n_bootstrap=n_bootstrap, seed=seed)
        optimized, optimized_seconds = _time_call(
            compute_aggregation_and_bootstrap_outputs,
            path_metrics,
            n_bootstrap=n_bootstrap,
            seed=seed,
        )
        elapsed_total += reference_seconds + optimized_seconds
        results.append(
            {
                "sessions": sessions,
                "path_rows": int(len(path_metrics)),
                "reference_seconds": round(reference_seconds, 6),
                "optimized_seconds": round(optimized_seconds, 6),
                "speedup": round(reference_seconds / optimized_seconds, 3) if optimized_seconds else None,
                "memory_mb": round(float(path_metrics.memory_usage(index=True, deep=True).sum()) / (1024.0 * 1024.0), 3),
                "max_abs_numeric_delta": _max_delta(reference, optimized),
            }
        )
    for previous, current in zip(results, results[1:]):
        current["reference_growth_vs_previous"] = round(current["reference_seconds"] / previous["reference_seconds"], 3)
        current["optimized_growth_vs_previous"] = round(current["optimized_seconds"] / previous["optimized_seconds"], 3)
    return {
        "benchmark": "HYP-OR-CONT-EVENT-01 aggregations_and_bootstrap",
        "bootstrap_grouped_by": "session_date",
        "n_bootstrap": n_bootstrap,
        "seed": seed,
        "results": results,
    }


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), indent=2, sort_keys=True))
