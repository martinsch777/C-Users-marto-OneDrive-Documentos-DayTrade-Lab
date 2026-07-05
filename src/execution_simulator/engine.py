from __future__ import annotations

from dataclasses import dataclass
import weakref

import pandas as pd

from src.data.sessions import EquitySessionCalendar

from .models import EntryPreview, ExecutionRequest, TradeResult


_FRAME_POSITION_CACHE: dict[
    int,
    tuple[weakref.ReferenceType[pd.DataFrame], dict[pd.Timestamp, int]],
] = {}


@dataclass
class _ExitFill:
    quantity: float
    reference_price: float
    execution_price: float
    timestamp: pd.Timestamp
    reason: str


class ExecutionSimulator:
    """Bar-based, deliberately conservative execution model."""

    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        self.spread_bps = float(config.get("spread_bps", 2.0))
        self.slippage_bps = float(config.get("slippage_bps", 1.5))
        self.commission_bps = float(config.get("commission_bps", 1.0))
        self.minimum_commission = float(config.get("minimum_commission", 0.0))
        self.latency_bars = int(config.get("latency_bars", 0))
        self.limit_expiry_bars = int(config.get("limit_expiry_bars", 3))
        self.max_volume_participation = float(
            config.get("max_volume_participation", 0.02)
        )
        self.allow_partial_fills = bool(config.get("allow_partial_fills", True))
        self.same_bar_policy = str(config.get("same_bar_policy", "stop_first"))
        self.force_flat_before_session_end = bool(
            config.get("force_flat_before_session_end", False)
        )
        self.enforce_session_entry = bool(
            config.get(
                "enforce_session_entry",
                self.force_flat_before_session_end,
            )
        )
        self.session_exit_buffer_minutes = int(
            config.get("session_exit_buffer_minutes", 0)
        )
        if self.session_exit_buffer_minutes < 0:
            raise ValueError("session_exit_buffer_minutes cannot be negative")
        self.session_calendar = EquitySessionCalendar.from_config(
            config.get("calendar", {}),
            timezone=str(config.get("session_timezone", "America/New_York")),
            regular_open=str(config.get("session_start", "09:30")),
            regular_close=str(config.get("session_end", "16:00")),
        )
        self._cached_frame_identity: tuple[int, int] | None = None
        self._timestamp_positions: dict[pd.Timestamp, int] = {}
        if self.same_bar_policy != "stop_first":
            raise ValueError("Only conservative same_bar_policy='stop_first' is supported")

    def _session_exit_position(
        self,
        frame: pd.DataFrame,
        entry_position: int,
    ) -> int | None:
        entry_timestamp = frame.iloc[entry_position]["timestamp"]
        local_entry = entry_timestamp.tz_convert(self.session_calendar.timezone)
        session_close = self.session_calendar.session_close(local_entry.date())
        if session_close is None:
            return None
        cutoff = pd.Timestamp.combine(
            local_entry.date(),
            session_close,
        ).tz_localize(self.session_calendar.timezone) - pd.Timedelta(
            self.session_exit_buffer_minutes,
            unit="min",
        )
        last_position: int | None = None
        for position in range(entry_position, len(frame)):
            local_timestamp = frame.iloc[position]["timestamp"].tz_convert(
                self.session_calendar.timezone
            )
            if local_timestamp.date() != local_entry.date():
                break
            if local_timestamp >= cutoff:
                break
            if self.session_calendar.contains(frame.iloc[position]["timestamp"]):
                last_position = position
        return last_position

    def _commission(self, price: float, quantity: float) -> float:
        variable = price * quantity * self.commission_bps / 10_000
        return max(variable, self.minimum_commission) if quantity > 0 else 0.0

    def _market_price(self, reference: float, action: str) -> float:
        adverse_bps = self.spread_bps / 2 + self.slippage_bps
        direction = 1 if action == "buy" else -1
        return reference * (1 + direction * adverse_bps / 10_000)

    def _capacity(self, volume: float, requested: float) -> float:
        capacity = max(0.0, volume * self.max_volume_participation)
        if requested <= capacity:
            return requested
        if self.allow_partial_fills:
            return capacity
        return 0.0

    def _locate_signal(self, frame: pd.DataFrame, timestamp: pd.Timestamp) -> int:
        identity = (id(frame), len(frame))
        if identity != self._cached_frame_identity:
            cached = _FRAME_POSITION_CACHE.get(id(frame))
            if cached is not None and cached[0]() is frame:
                self._timestamp_positions = cached[1]
            else:
                self._timestamp_positions = {
                    value: position
                    for position, value in enumerate(frame["timestamp"].tolist())
                }
                frame_id = id(frame)

                def remove_cache(_reference, key=frame_id):
                    _FRAME_POSITION_CACHE.pop(key, None)

                _FRAME_POSITION_CACHE[frame_id] = (
                    weakref.ref(frame, remove_cache),
                    self._timestamp_positions,
                )
            self._cached_frame_identity = identity
        if timestamp not in self._timestamp_positions:
            raise ValueError("Signal timestamp is not present in execution data")
        return self._timestamp_positions[timestamp]

    def _entry_bar_is_valid(
        self,
        signal_timestamp: pd.Timestamp,
        fill_timestamp: pd.Timestamp,
    ) -> bool:
        if not self.enforce_session_entry:
            return True
        local_signal = signal_timestamp.tz_convert(
            self.session_calendar.timezone
        )
        local_fill = fill_timestamp.tz_convert(
            self.session_calendar.timezone
        )
        return (
            local_signal.date() == local_fill.date()
            and self.session_calendar.contains(signal_timestamp)
            and self.session_calendar.contains(fill_timestamp)
        )

    def preview_entry(
        self,
        frame: pd.DataFrame,
        request: ExecutionRequest,
    ) -> EntryPreview:
        signal_position = self._locate_signal(frame, request.signal_timestamp)
        first_position = signal_position + 1 + self.latency_bars
        if first_position >= len(frame):
            return EntryPreview(status="NO_FILL", exit_reason="NO_FILL")
        first_timestamp = frame.iloc[first_position]["timestamp"]
        if not self._entry_bar_is_valid(
            request.signal_timestamp,
            first_timestamp,
        ):
            return EntryPreview(
                status="CANCELLED",
                exit_reason="CANCELLED_NEXT_BAR_NOT_SAME_SESSION",
            )
        if request.order_type == "market":
            row = frame.iloc[first_position]
            action = "buy" if request.side == "long" else "sell"
            price = self._market_price(float(row["open"]), action)
            return EntryPreview(
                status="READY",
                position=first_position,
                timestamp=row["timestamp"],
                price=price,
            )
        if request.limit_price is None:
            raise ValueError("A limit order requires limit_price")
        final_position = min(
            first_position + self.limit_expiry_bars,
            len(frame),
        )
        for position in range(first_position, final_position):
            row = frame.iloc[position]
            if not self._entry_bar_is_valid(
                request.signal_timestamp,
                row["timestamp"],
            ):
                return EntryPreview(
                    status="CANCELLED",
                    exit_reason="CANCELLED_NEXT_BAR_NOT_SAME_SESSION",
                )
            touched = (
                row["low"] <= request.limit_price
                if request.side == "long"
                else row["high"] >= request.limit_price
            )
            if not touched:
                continue
            return EntryPreview(
                status="READY",
                position=position,
                timestamp=row["timestamp"],
                price=float(request.limit_price),
            )
        return EntryPreview(status="NO_FILL", exit_reason="NO_FILL")

    @staticmethod
    def _touches(
        row: pd.Series,
        side: str,
        stop: float,
        target: float | None,
    ) -> tuple[bool, bool]:
        if side == "long":
            return row["low"] <= stop, target is not None and row["high"] >= target
        return row["high"] >= stop, target is not None and row["low"] <= target

    def simulate(
        self,
        frame: pd.DataFrame,
        request: ExecutionRequest,
        *,
        entry_preview: EntryPreview | None = None,
    ) -> TradeResult:
        if request.quantity <= 0:
            raise ValueError("Quantity must be positive")
        if not 0 < request.partial_exit_fraction <= 1:
            raise ValueError("partial_exit_fraction must be in (0, 1]")
        preview = entry_preview or self.preview_entry(frame, request)
        if preview.status != "READY" or preview.position is None:
            return TradeResult(
                status=preview.status,
                side=request.side,
                requested_quantity=request.quantity,
                exit_reason=preview.exit_reason,
            )
        entry_position = preview.position
        entry_price = preview.price
        entry_row = frame.iloc[entry_position]
        quantity = self._capacity(
            float(entry_row["volume"]),
            request.quantity,
        )
        if quantity <= 0:
            return TradeResult(
                status="NO_FILL",
                side=request.side,
                requested_quantity=request.quantity,
                exit_reason="NO_FILL",
            )
        session_exit_position: int | None = None
        if self.force_flat_before_session_end:
            session_exit_position = self._session_exit_position(frame, entry_position)
            if session_exit_position is None or session_exit_position < entry_position:
                return TradeResult(
                    status="NO_FILL",
                    side=request.side,
                    requested_quantity=request.quantity,
                    exit_reason="NO_FILL_OUTSIDE_SESSION",
                )
        partial_fill = quantity + 1e-12 < request.quantity
        stop = float(request.stop_loss)
        target: float | None = float(request.take_profit)
        if request.side == "long" and not stop < entry_price < target:
            return TradeResult(
                status="INVALID_LEVELS",
                side=request.side,
                requested_quantity=request.quantity,
                filled_quantity=quantity,
                entry_timestamp=entry_row["timestamp"],
                entry_price=entry_price,
                exit_reason="INVALID_LEVELS_AFTER_EXECUTION_COSTS",
                partial_fill=partial_fill,
            )
        if request.side == "short" and not target < entry_price < stop:
            return TradeResult(
                status="INVALID_LEVELS",
                side=request.side,
                requested_quantity=request.quantity,
                filled_quantity=quantity,
                entry_timestamp=entry_row["timestamp"],
                entry_price=entry_price,
                exit_reason="INVALID_LEVELS_AFTER_EXECUTION_COSTS",
                partial_fill=partial_fill,
            )

        remaining = quantity
        exits: list[_ExitFill] = []
        partial_exit = False
        favorable_extreme = entry_price
        final_scan_position = (
            session_exit_position
            if session_exit_position is not None
            else len(frame) - 1
        )
        for position in range(entry_position, final_scan_position + 1):
            row = frame.iloc[position]
            stop_touched, target_touched = self._touches(row, request.side, stop, target)

            # A limit can fill after a favorable excursion in its entry bar. Ignoring
            # target-only touches on that bar prevents look-ahead in event ordering.
            if (
                request.order_type == "limit"
                and position == entry_position
                and target_touched
                and not stop_touched
            ):
                target_touched = False

            if stop_touched:
                action = "sell" if request.side == "long" else "buy"
                execution = self._market_price(stop, action)
                reason = (
                    "STOP_FIRST_AMBIGUOUS_BAR"
                    if target_touched
                    else "STOP_LOSS"
                )
                exits.append(
                    _ExitFill(
                        remaining,
                        stop,
                        execution,
                        row["timestamp"],
                        reason,
                    )
                )
                remaining = 0.0
                break

            if target_touched and target is not None:
                exit_quantity = (
                    remaining * request.partial_exit_fraction
                    if request.partial_exit_fraction < 1 and not partial_exit
                    else remaining
                )
                action = "sell" if request.side == "long" else "buy"
                execution = self._market_price(target, action)
                exits.append(
                    _ExitFill(
                        exit_quantity,
                        target,
                        execution,
                        row["timestamp"],
                        "TAKE_PROFIT",
                    )
                )
                remaining -= exit_quantity
                if remaining <= 1e-12:
                    remaining = 0.0
                    break
                partial_exit = True
                target = None
                stop = entry_price

            if request.trailing_stop_pct is not None and remaining > 0:
                trail = float(request.trailing_stop_pct)
                if request.side == "long":
                    favorable_extreme = max(favorable_extreme, float(row["high"]))
                    stop = max(stop, favorable_extreme * (1 - trail))
                else:
                    favorable_extreme = min(favorable_extreme, float(row["low"]))
                    stop = min(stop, favorable_extreme * (1 + trail))

        if remaining > 0:
            last_position = (
                session_exit_position
                if session_exit_position is not None
                else len(frame) - 1
            )
            last = frame.iloc[last_position]
            action = "sell" if request.side == "long" else "buy"
            reference = float(last["close"])
            exits.append(
                _ExitFill(
                    remaining,
                    reference,
                    self._market_price(reference, action),
                    last["timestamp"],
                    (
                        "FORCED_SESSION_CLOSE"
                        if session_exit_position is not None
                        else "END_OF_DATA"
                    ),
                )
            )

        exit_notional = sum(item.execution_price * item.quantity for item in exits)
        exit_price = exit_notional / quantity
        direction = 1 if request.side == "long" else -1
        gross_pnl = sum(
            direction * (item.execution_price - entry_price) * item.quantity
            for item in exits
        )
        commission = self._commission(entry_price, quantity) + sum(
            self._commission(item.execution_price, item.quantity) for item in exits
        )
        spread_cost = (
            entry_price * quantity
            + sum(item.reference_price * item.quantity for item in exits)
        ) * (self.spread_bps / 2) / 10_000
        slippage_cost = (
            entry_price * quantity
            + sum(item.reference_price * item.quantity for item in exits)
        ) * self.slippage_bps / 10_000
        reason = exits[-1].reason
        if partial_exit:
            reason = f"PARTIAL_TARGET_THEN_{reason}"
        return TradeResult(
            status="FILLED",
            side=request.side,
            requested_quantity=request.quantity,
            filled_quantity=quantity,
            entry_timestamp=entry_row["timestamp"],
            exit_timestamp=exits[-1].timestamp,
            entry_price=entry_price,
            exit_price=exit_price,
            gross_pnl=gross_pnl,
            commission=commission,
            spread_cost=spread_cost,
            slippage_cost=slippage_cost,
            net_pnl=gross_pnl - commission,
            exit_reason=reason,
            partial_fill=partial_fill,
            partial_exit=partial_exit,
            bars_held=max(
                1,
                self._locate_signal(frame, exits[-1].timestamp) - entry_position + 1,
            ),
        )
