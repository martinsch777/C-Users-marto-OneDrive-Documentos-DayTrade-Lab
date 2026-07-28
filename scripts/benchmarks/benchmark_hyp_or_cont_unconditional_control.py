from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.research.hyp_or_cont_event_01 import (
    attach_incremental_returns,
    compute_unconditional_control,
    compute_unconditional_control_reference,
)


def _ts(value: str) -> pd.Timestamp:
    return pd.Timestamp(value, tz="America/New_York").tz_convert("UTC")


def _bar(value: str, open_: float, high: float, low: float, close: float) -> dict:
    return {
        "timestamp": _ts(value),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": 1000,
    }


def _synthetic_inputs(*, sessions: int) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    path_rows: list[dict] = []
    for symbol, base_price in (("QQQ", 100.0), ("SPY", 200.0)):
        rows: list[dict] = []
        for session_number in range(sessions):
            day = pd.Timestamp("2024-01-02") + pd.offsets.Day(session_number)
            date = day.strftime("%Y-%m-%d")
            for bar_number, minute in enumerate(range(9 * 60 + 30, 16 * 60, 5)):
                hour = minute // 60
                minute_of_hour = minute % 60
                price = base_price + session_number * 0.11 + bar_number * 0.013
                rows.append(
                    _bar(
                        f"{date} {hour:02d}:{minute_of_hour:02d}",
                        price,
                        price + 0.2,
                        price - 0.2,
                        price + 0.04,
                    )
                )
            for orientation in ("continuation_long", "continuation_short"):
                for horizon in ("15min", "30min", "60min", "session_close"):
                    path_rows.append(
                        {
                            "symbol": symbol,
                            "session_date": date,
                            "executable_timestamp": _ts(f"{date} 10:00"),
                            "direction_orientation": orientation,
                            "year": 2024,
                            "executable_timestamp_hour_bucket": "10:00",
                            "horizon": horizon,
                            "event_return": 0.001 if orientation == "continuation_long" else -0.001,
                        }
                    )
        frames[symbol] = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
    return frames, pd.DataFrame(path_rows)


def _time_call(func, *args):
    start = time.perf_counter()
    result = func(*args)
    return result, time.perf_counter() - start


def _memory_mb(frames: dict[str, pd.DataFrame], paths: pd.DataFrame) -> float:
    total = paths.memory_usage(index=True, deep=True).sum()
    total += sum(frame.memory_usage(index=True, deep=True).sum() for frame in frames.values())
    return float(total) / (1024.0 * 1024.0)


def run_benchmark() -> dict:
    results = []
    for sessions in (8, 16):
        frames, paths = _synthetic_inputs(sessions=sessions)
        reference, reference_seconds = _time_call(compute_unconditional_control_reference, frames, paths)
        optimized, optimized_seconds = _time_call(compute_unconditional_control, frames, paths)
        reference_incremental = attach_incremental_returns(paths, reference)
        optimized_incremental = attach_incremental_returns(paths, optimized)
        max_abs_delta = float(
            (reference_incremental["incremental_return"] - optimized_incremental["incremental_return"]).abs().max()
        )
        results.append(
            {
                "sessions": sessions,
                "path_rows": int(len(paths)),
                "reference_seconds": round(reference_seconds, 6),
                "optimized_seconds": round(optimized_seconds, 6),
                "speedup": round(reference_seconds / optimized_seconds, 3) if optimized_seconds else None,
                "memory_mb": round(_memory_mb(frames, paths), 3),
                "max_abs_incremental_delta": max_abs_delta,
            }
        )
    if len(results) == 2:
        results[1]["optimized_growth_vs_half_sessions"] = round(
            results[1]["optimized_seconds"] / results[0]["optimized_seconds"], 3
        )
        results[1]["reference_growth_vs_half_sessions"] = round(
            results[1]["reference_seconds"] / results[0]["reference_seconds"], 3
        )
    return {"benchmark": "HYP-OR-CONT-EVENT-01 unconditional_control", "results": results}


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), indent=2, sort_keys=True))
