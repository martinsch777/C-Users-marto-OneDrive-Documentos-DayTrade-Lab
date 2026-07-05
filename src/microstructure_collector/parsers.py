from __future__ import annotations

from typing import Any


def parse_bybit_message(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("op") in {"subscribe", "pong"} or "topic" not in payload:
        return []
    topic = str(payload["topic"])
    received_ts = int(payload.get("ts", 0))
    topic_symbol = topic.rsplit(".", 1)[-1]
    if topic.startswith("orderbook."):
        data = payload.get("data", {})
        return [
            {
                "kind": "orderbook",
                "topic": topic,
                "symbol": data.get("s", topic_symbol),
                "message_type": payload.get("type", ""),
                "exchange_timestamp_ms": received_ts,
                "update_id": int(data.get("u", 0)),
                "sequence": int(data.get("seq", 0)),
                "bids": data.get("b", []),
                "asks": data.get("a", []),
            }
        ]
    if topic.startswith("publicTrade."):
        return [
            {
                "kind": "trade",
                "topic": topic,
                "symbol": event["s"],
                "exchange_timestamp_ms": int(event["T"]),
                "trade_id": str(event.get("i", "")),
                "side": event["S"].lower(),
                "price": float(event["p"]),
                "size": float(event["v"]),
                "tick_direction": event.get("L", ""),
            }
            for event in payload.get("data", [])
        ]
    if topic.startswith("tickers."):
        data = payload.get("data", {})
        return [
            {
                "kind": "ticker",
                "topic": topic,
                "symbol": data.get("symbol", topic_symbol),
                "exchange_timestamp_ms": received_ts,
                "best_bid": float(data["bid1Price"])
                if data.get("bid1Price")
                else None,
                "best_ask": float(data["ask1Price"])
                if data.get("ask1Price")
                else None,
                "mark_price": float(data["markPrice"])
                if data.get("markPrice")
                else None,
                "index_price": float(data["indexPrice"])
                if data.get("indexPrice")
                else None,
                "funding_rate": float(data["fundingRate"])
                if data.get("fundingRate")
                else None,
                "open_interest": float(data["openInterest"])
                if data.get("openInterest")
                else None,
            }
        ]
    if topic.startswith("allLiquidation."):
        return [
            {
                "kind": "liquidation",
                "topic": topic,
                "symbol": event["s"],
                "exchange_timestamp_ms": int(event["T"]),
                "liquidated_position_side": event["S"].lower(),
                "size": float(event["v"]),
                "bankruptcy_price": float(event["p"]),
            }
            for event in payload.get("data", [])
        ]
    if topic.startswith("kline."):
        return [
            {
                "kind": "kline",
                "topic": topic,
                # Bybit's public kline payload doesn't include symbol in data.
                # The symbol is the final component of kline.{interval}.{symbol}.
                "symbol": event.get("symbol", topic_symbol),
                "exchange_timestamp_ms": received_ts,
                "start_ms": int(event["start"]),
                "end_ms": int(event["end"]),
                "interval": str(event["interval"]),
                "open": float(event["open"]),
                "high": float(event["high"]),
                "low": float(event["low"]),
                "close": float(event["close"]),
                "volume": float(event["volume"]),
                "confirmed": bool(event.get("confirm", False)),
            }
            for event in payload.get("data", [])
        ]
    return []
