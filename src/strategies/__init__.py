from .base import Signal, Strategy
from .extreme_mean_reversion import ExtremeMeanReversionStrategy
from .opening_range_breakout import OpeningRangeBreakoutStrategy
from .opening_range_fvg import OpeningRangeFVGStrategy
from .relative_volume_momentum import RelativeVolumeMomentumStrategy
from .trend_day_continuation import TrendDayContinuationStrategy
from .vwap_pullback import VWAPPullbackStrategy


def build_strategies(
    config: dict,
    *,
    asset_class: str = "equity",
    strategy_names: list[str] | tuple[str, ...] | None = None,
) -> list[Strategy]:
    strategy_config = config.get("strategies", {})
    session_timezone = (
        "UTC"
        if asset_class == "crypto"
        else config.get("project", {}).get("timezone", "America/New_York")
    )

    def settings(name: str) -> dict:
        values = dict(strategy_config.get(name, {}))
        values["session_timezone"] = session_timezone
        values["asset_class"] = asset_class
        if name == "opening_range_fvg":
            values["calendar"] = config.get("data", {}).get("calendar", {})
        if name == "opening_range_breakout" and asset_class == "crypto":
            values["session_start"] = "00:00"
            values["candidate_end"] = "23:59"
        return values

    builders = {
        "opening_range_breakout": OpeningRangeBreakoutStrategy,
        "opening_range_fvg": OpeningRangeFVGStrategy,
        "vwap_pullback": VWAPPullbackStrategy,
        "relative_volume_momentum": RelativeVolumeMomentumStrategy,
        "extreme_mean_reversion": ExtremeMeanReversionStrategy,
        "trend_day_continuation": TrendDayContinuationStrategy,
    }
    selected = list(strategy_names) if strategy_names is not None else list(builders)
    unknown = sorted(set(selected).difference(builders))
    if unknown:
        raise ValueError(f"Unknown strategies: {', '.join(unknown)}")
    return [builders[name](settings(name)) for name in selected]


def available_strategy_names() -> tuple[str, ...]:
    return (
        "opening_range_breakout",
        "opening_range_fvg",
        "vwap_pullback",
        "relative_volume_momentum",
        "extreme_mean_reversion",
        "trend_day_continuation",
    )


__all__ = [
    "ExtremeMeanReversionStrategy",
    "OpeningRangeBreakoutStrategy",
    "OpeningRangeFVGStrategy",
    "RelativeVolumeMomentumStrategy",
    "Signal",
    "Strategy",
    "TrendDayContinuationStrategy",
    "VWAPPullbackStrategy",
    "build_strategies",
    "available_strategy_names",
]
