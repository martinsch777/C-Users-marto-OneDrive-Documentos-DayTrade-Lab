from .engine import BacktestEngine, BacktestResult
from .metrics import calculate_metrics, compare_strategies
from .real_data import (
    add_market_context,
    attach_market_context,
    evaluate_replay_candidate,
    intraday_buy_hold_trades,
    invalidate_signals_after_gaps,
    metrics_by_dimension,
    momentum_benchmark_signals,
    out_of_sample_from_signals,
    permissive_psychology_config,
    psychology_impact,
    random_entry_signals,
    walk_forward_yearly_from_signals,
)
from .validation import (
    approval_decision,
    cost_sensitivity,
    out_of_sample_backtest,
    walk_forward_backtest,
)

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "approval_decision",
    "add_market_context",
    "attach_market_context",
    "calculate_metrics",
    "compare_strategies",
    "cost_sensitivity",
    "evaluate_replay_candidate",
    "intraday_buy_hold_trades",
    "invalidate_signals_after_gaps",
    "metrics_by_dimension",
    "momentum_benchmark_signals",
    "out_of_sample_from_signals",
    "permissive_psychology_config",
    "psychology_impact",
    "random_entry_signals",
    "walk_forward_yearly_from_signals",
    "out_of_sample_backtest",
    "walk_forward_backtest",
]
