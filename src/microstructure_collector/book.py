from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OrderBookState:
    symbol: str
    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)
    last_sequence: int | None = None
    gap_count: int = 0

    @staticmethod
    def _apply(side: dict[float, float], updates) -> None:
        for raw_price, raw_size in updates:
            price, size = float(raw_price), float(raw_size)
            if size == 0:
                side.pop(price, None)
            else:
                side[price] = size

    def update(self, event: dict) -> bool:
        sequence = int(event.get("sequence", 0))
        is_snapshot = event.get("message_type") == "snapshot"
        gap = (
            not is_snapshot
            and self.last_sequence is not None
            and sequence > self.last_sequence + 1
        )
        if gap:
            self.gap_count += 1
        if is_snapshot:
            self.bids.clear()
            self.asks.clear()
        self._apply(self.bids, event.get("bids", []))
        self._apply(self.asks, event.get("asks", []))
        self.last_sequence = sequence
        return gap

    def metrics(self) -> dict:
        if not self.bids or not self.asks:
            raise ValueError("Both sides of the book are required")
        bid_prices = sorted(self.bids, reverse=True)
        ask_prices = sorted(self.asks)
        best_bid, best_ask = bid_prices[0], ask_prices[0]
        if best_ask <= best_bid:
            raise ValueError("Crossed or locked order book")
        mid = (best_bid + best_ask) / 2
        result = {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid_price": mid,
            "spread_bps": (best_ask - best_bid) / mid * 10_000,
        }
        for levels in (5, 10, 25, 50):
            bid_depth = sum(
                price * self.bids[price] for price in bid_prices[:levels]
            )
            ask_depth = sum(
                price * self.asks[price] for price in ask_prices[:levels]
            )
            total = bid_depth + ask_depth
            result[f"bid_depth_quote_l{levels}"] = bid_depth
            result[f"ask_depth_quote_l{levels}"] = ask_depth
            result[f"imbalance_l{levels}"] = (
                (bid_depth - ask_depth) / total if total > 0 else 0.0
            )
        return result
