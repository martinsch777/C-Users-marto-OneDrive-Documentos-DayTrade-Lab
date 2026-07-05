from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo

import pandas as pd

from src.risk import BlockReason, Decision, TradingState
from src.strategies import Signal


@dataclass(frozen=True)
class GuardContext:
    attempted_stop_move_away: bool = False
    attempted_size_increase_after_loss: bool = False
    manual_fomo_flag: bool = False


class PsychologyGuard:
    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        self.allowed_setups = set(config.get("allowed_setups", []))
        self.loss_cooldown_minutes = int(config.get("loss_cooldown_minutes", 30))
        self.window_start = time.fromisoformat(
            str(config.get("trading_window_start", "09:35"))
        )
        self.window_end = time.fromisoformat(
            str(config.get("trading_window_end", "15:30"))
        )
        self.max_trades_per_hour = int(config.get("max_trades_per_hour", 2))
        self.block_fomo = bool(config.get("block_fomo", True))
        self.block_unfavorable_regime = bool(
            config.get("block_unfavorable_regime", True)
        )

    def evaluate(
        self,
        signal: Signal,
        state: TradingState,
        context: GuardContext | None = None,
    ) -> Decision:
        context = context or GuardContext()
        if signal.strategy not in self.allowed_setups:
            return Decision(
                False,
                BlockReason.NO_VALID_SETUP.value,
                f"Setup '{signal.strategy}' is not allowed",
            )
        local = signal.timestamp.tz_convert(ZoneInfo("America/New_York"))
        local_clock = local.time().replace(tzinfo=None)
        if not self.window_start <= local_clock <= self.window_end:
            return Decision(
                False,
                BlockReason.OUTSIDE_TRADING_WINDOW.value,
                "Signal falls outside the allowed trading window",
            )
        if state.last_loss_timestamp is not None:
            elapsed = signal.timestamp - state.last_loss_timestamp
            if pd.Timedelta(0) <= elapsed < pd.Timedelta(
                minutes=self.loss_cooldown_minutes
            ):
                return Decision(
                    False,
                    BlockReason.AFTER_LOSS_COOLDOWN.value,
                    "Loss cooldown has not elapsed",
                )
        one_hour_ago = signal.timestamp - pd.Timedelta(hours=1)
        recent = sum(
            one_hour_ago < timestamp <= signal.timestamp
            for timestamp in state.trade_timestamps
        )
        if recent >= self.max_trades_per_hour:
            return Decision(
                False,
                BlockReason.OVERTRADING.value,
                "Hourly trade frequency limit reached",
            )
        if context.attempted_stop_move_away:
            return Decision(
                False,
                BlockReason.STOP_MOVED_AWAY.value,
                "Moving a protective stop farther away is forbidden",
            )
        if context.attempted_size_increase_after_loss:
            return Decision(
                False,
                BlockReason.SIZE_INCREASED_AFTER_LOSS.value,
                "Increasing size immediately after a loss is forbidden",
            )
        if self.block_fomo and (signal.fomo_flag or context.manual_fomo_flag):
            return Decision(
                False,
                BlockReason.FOMO.value,
                "Entry is flagged as extended or FOMO-driven",
            )
        if self.block_unfavorable_regime and signal.metadata.get(
            "unfavorable_regime", False
        ):
            return Decision(
                False,
                BlockReason.UNFAVORABLE_REGIME.value,
                str(
                    signal.metadata.get(
                        "regime_block_details",
                        "Signal conflicts with its pre-registered market regime",
                    )
                ),
            )
        return Decision(True)
