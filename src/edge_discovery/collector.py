from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


PUBLIC_BASE = "https://fapi.binance.com"
ALLOWED_PATHS = {
    "/fapi/v1/depth",
    "/fapi/v1/aggTrades",
    "/fapi/v1/openInterest",
    "/fapi/v1/premiumIndex",
}


class ForwardMarketCollector:
    """Public-data collector with deliberately no trading/account surface."""

    def __init__(
        self,
        root: str | Path = "data/forward_collector",
        *,
        transport=None,
    ) -> None:
        self.root = Path(root)
        self.transport = transport or self._get_json

    @staticmethod
    def _get_json(url: str) -> Any:
        request = Request(url, headers={"User-Agent": "DayTrade-Lab-Collector/1.0"})
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))

    def _public_get(self, path: str, params: dict[str, Any]) -> Any:
        if path not in ALLOWED_PATHS:
            raise ValueError(f"Collector endpoint is not allowlisted: {path}")
        return self.transport(f"{PUBLIC_BASE}{path}?{urlencode(params)}")

    @staticmethod
    def _append_csv(path: Path, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(records).to_csv(
            path,
            mode="a",
            header=not path.exists(),
            index=False,
        )

    def collect_once(self, symbols: tuple[str, ...]) -> pd.DataFrame:
        collected_at = datetime.now(timezone.utc).isoformat()
        status: list[dict[str, Any]] = []
        for symbol in symbols:
            try:
                depth = self._public_get(
                    "/fapi/v1/depth", {"symbol": symbol, "limit": 20}
                )
                trades = self._public_get(
                    "/fapi/v1/aggTrades", {"symbol": symbol, "limit": 100}
                )
                oi = self._public_get("/fapi/v1/openInterest", {"symbol": symbol})
                premium = self._public_get(
                    "/fapi/v1/premiumIndex", {"symbol": symbol}
                )
                bids = [(float(price), float(size)) for price, size in depth["bids"]]
                asks = [(float(price), float(size)) for price, size in depth["asks"]]
                best_bid, best_ask = bids[0][0], asks[0][0]
                mid = (best_bid + best_ask) / 2
                bid_depth = sum(price * size for price, size in bids)
                ask_depth = sum(price * size for price, size in asks)
                self._append_csv(
                    self.root / "orderbook_snapshots.csv",
                    [
                        {
                            "collected_at_utc": collected_at,
                            "symbol": symbol,
                            "last_update_id": depth.get("lastUpdateId"),
                            "best_bid": best_bid,
                            "best_ask": best_ask,
                            "spread_bps": (best_ask - best_bid) / mid * 10_000,
                            "bid_depth_quote_top20": bid_depth,
                            "ask_depth_quote_top20": ask_depth,
                            "imbalance_top20": (
                                (bid_depth - ask_depth) / (bid_depth + ask_depth)
                                if bid_depth + ask_depth > 0
                                else 0.0
                            ),
                        }
                    ],
                )
                trade_rows = []
                for trade in trades:
                    trade_rows.append(
                        {
                            "collected_at_utc": collected_at,
                            "symbol": symbol,
                            "trade_time_utc": pd.to_datetime(
                                trade["T"], unit="ms", utc=True
                            ).isoformat(),
                            "aggregate_trade_id": trade["a"],
                            "price": float(trade["p"]),
                            "quantity": float(trade["q"]),
                            "buyer_is_maker": bool(trade["m"]),
                            "aggressor_side": (
                                "sell" if bool(trade["m"]) else "buy"
                            ),
                        }
                    )
                self._append_csv(self.root / "recent_trades.csv", trade_rows)
                self._append_csv(
                    self.root / "funding_open_interest.csv",
                    [
                        {
                            "collected_at_utc": collected_at,
                            "symbol": symbol,
                            "open_interest": float(oi["openInterest"]),
                            "oi_engine_time_utc": pd.to_datetime(
                                oi["time"], unit="ms", utc=True
                            ).isoformat(),
                            "mark_price": float(premium["markPrice"]),
                            "index_price": float(premium["indexPrice"]),
                            "last_funding_rate": float(
                                premium["lastFundingRate"]
                            ),
                            "next_funding_time_utc": pd.to_datetime(
                                premium["nextFundingTime"], unit="ms", utc=True
                            ).isoformat(),
                        }
                    ],
                )
                status.append(
                    {
                        "collected_at_utc": collected_at,
                        "symbol": symbol,
                        "status": "collected",
                        "orderbook": True,
                        "recent_trades": len(trade_rows),
                        "open_interest": True,
                        "funding": True,
                        "liquidations": False,
                        "orders_sent": False,
                        "broker_connected": False,
                        "error": "",
                    }
                )
            except Exception as exc:
                status.append(
                    {
                        "collected_at_utc": collected_at,
                        "symbol": symbol,
                        "status": "error",
                        "orderbook": False,
                        "recent_trades": 0,
                        "open_interest": False,
                        "funding": False,
                        "liquidations": False,
                        "orders_sent": False,
                        "broker_connected": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        result = pd.DataFrame(status)
        self._append_csv(self.root / "collector_status_history.csv", status)
        return result

    def record_liquidation_events(
        self,
        payload: dict[str, Any],
        *,
        provider: str,
    ) -> int:
        records: list[dict[str, Any]] = []
        collected_at = datetime.now(timezone.utc).isoformat()
        if provider == "bybit":
            for event in payload.get("data", []):
                records.append(
                    {
                        "collected_at_utc": collected_at,
                        "provider": provider,
                        "event_time_utc": pd.to_datetime(
                            event["T"], unit="ms", utc=True
                        ).isoformat(),
                        "symbol": event["s"],
                        "liquidated_position_side": event["S"],
                        "quantity": float(event["v"]),
                        "bankruptcy_price": float(event["p"]),
                    }
                )
        elif provider == "binance":
            event = payload.get("o", payload)
            records.append(
                {
                    "collected_at_utc": collected_at,
                    "provider": provider,
                    "event_time_utc": pd.to_datetime(
                        event["T"], unit="ms", utc=True
                    ).isoformat(),
                    "symbol": event["s"],
                    "liquidated_position_side": event["S"],
                    "quantity": float(event["q"]),
                    "bankruptcy_price": float(event.get("ap", event["p"])),
                }
            )
        else:
            raise ValueError(f"Unsupported liquidation provider: {provider}")
        self._append_csv(self.root / "liquidation_events.csv", records)
        return len(records)
