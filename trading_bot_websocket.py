from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from typing import Dict, Optional

import pandas as pd
import requests
from websockets.sync.client import connect

logger = logging.getLogger(__name__)


TIMEFRAME_TO_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}

TIMEFRAME_TO_BYBIT = {
    "1m": "1",
    "3m": "3",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "2h": "120",
    "4h": "240",
    "6h": "360",
    "12h": "720",
    "1d": "D",
}


class StreamlinedTradingBot:
    """Real-only kline stream with provider failover and closed-candle snapshots."""

    def __init__(self, symbol: str, timeframe: str, max_candles: int = 1000):
        self.symbol = self._normalize_symbol(symbol)
        self.timeframe = timeframe
        self.max_candles = max(int(max_candles), 250)
        self.last_price = 0.0
        self.current_signal = "STREAMING"
        self.current_provider = None
        self.last_error = None
        self.last_message_at = 0.0

        self._candles: "OrderedDict[pd.Timestamp, Dict]" = OrderedDict()
        self._current_candle: Optional[Dict] = None
        self._lock = threading.Lock()
        self._ready_event = threading.Event()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name=f"market-stream-{self.symbol}-{self.timeframe}",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2)

    def get_current_status(self) -> Dict:
        with self._lock:
            candles_count = len(self._candles)
            last_closed_ts = next(reversed(self._candles)) if self._candles else None

        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "provider": self.current_provider,
            "connected": self._thread.is_alive() and self._ready_event.is_set(),
            "candles": candles_count,
            "last_price": self.last_price,
            "last_message_age_sec": round(max(0.0, time.time() - self.last_message_at), 2)
            if self.last_message_at
            else None,
            "last_closed_timestamp": last_closed_ts.isoformat() if last_closed_ts is not None else None,
            "last_error": self.last_error,
        }

    def get_market_data(self, limit: int = 200, timeout: float = 20.0) -> pd.DataFrame:
        if not self._ready_event.wait(timeout=timeout):
            raise ConnectionError(
                f"Stream real nao ficou pronto para {self.symbol} {self.timeframe} dentro de {timeout:.0f}s"
            )

        with self._lock:
            rows = list(self._candles.values())[-limit:]

        if not rows:
            raise ConnectionError(f"Nenhum candle fechado disponivel para {self.symbol} {self.timeframe}")

        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        df["is_closed"] = True
        return df

    def _run(self):
        providers = ("binance_futures", "bybit_linear")
        provider_index = 0
        consecutive_failures = 0

        while not self._stop_event.is_set():
            provider = providers[provider_index % len(providers)]
            try:
                self._seed_from_rest(provider)
                self.current_provider = provider
                self.last_error = None
                consecutive_failures = 0
                self._stream_provider(provider)
            except Exception as exc:
                consecutive_failures += 1
                self.last_error = str(exc)
                logger.warning(
                    "Falha no stream %s para %s %s: %s",
                    provider,
                    self.symbol,
                    self.timeframe,
                    exc,
                )
                provider_index += 1
                time.sleep(min(2 * consecutive_failures, 10))

    def _stream_provider(self, provider: str):
        if provider == "binance_futures":
            self._stream_binance_futures()
            return
        if provider == "bybit_linear":
            self._stream_bybit_linear()
            return
        raise ValueError(f"Provider nao suportado: {provider}")

    def _stream_binance_futures(self):
        stream_symbol = self.symbol.lower()
        ws_url = f"wss://fstream.binance.com/ws/{stream_symbol}@kline_{self.timeframe}"

        with connect(ws_url, open_timeout=10, ping_interval=20, ping_timeout=20, close_timeout=5) as websocket:
            while not self._stop_event.is_set():
                payload = json.loads(websocket.recv(timeout=30))
                candle = self._parse_binance_message(payload)
                if candle is None:
                    continue
                self._ingest_candle(candle)

    def _stream_bybit_linear(self):
        interval = TIMEFRAME_TO_BYBIT[self.timeframe]
        topic = f"kline.{interval}.{self.symbol}"

        with connect(
            "wss://stream.bybit.com/v5/public/linear",
            open_timeout=10,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
        ) as websocket:
            websocket.send(json.dumps({"op": "subscribe", "args": [topic]}))

            while not self._stop_event.is_set():
                payload = json.loads(websocket.recv(timeout=30))
                candle = self._parse_bybit_message(payload)
                if candle is None:
                    continue
                self._ingest_candle(candle)

    def _seed_from_rest(self, provider: str):
        if provider == "binance_futures":
            candles = self._fetch_binance_rest()
        elif provider == "bybit_linear":
            candles = self._fetch_bybit_rest()
        else:
            raise ValueError(f"Provider nao suportado: {provider}")

        if candles.empty:
            raise ConnectionError(f"REST seed vazio para {provider}")

        with self._lock:
            self._candles.clear()
            for timestamp, row in candles.iterrows():
                candle = {
                    "timestamp": int(timestamp.timestamp() * 1000),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                }
                self._candles[timestamp] = candle
            self._trim_candles_locked()
            self.last_price = float(candles.iloc[-1]["close"])
            self.last_message_at = time.time()

        self._ready_event.set()

    def _fetch_binance_rest(self) -> pd.DataFrame:
        response = requests.get(
            "https://fapi.binance.com/fapi/v1/klines",
            params={
                "symbol": self.symbol,
                "interval": self.timeframe,
                "limit": min(self.max_candles, 1000),
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        records = [
            {
                "timestamp": int(item[0]),
                "open": float(item[1]),
                "high": float(item[2]),
                "low": float(item[3]),
                "close": float(item[4]),
                "volume": float(item[5]),
            }
            for item in payload
        ]
        return self._records_to_dataframe(records)

    def _fetch_bybit_rest(self) -> pd.DataFrame:
        response = requests.get(
            "https://api.bybit.com/v5/market/kline",
            params={
                "category": "linear",
                "symbol": self.symbol,
                "interval": TIMEFRAME_TO_BYBIT[self.timeframe],
                "limit": min(self.max_candles, 1000),
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("result", {}).get("list", [])
        records = [
            {
                "timestamp": int(item[0]),
                "open": float(item[1]),
                "high": float(item[2]),
                "low": float(item[3]),
                "close": float(item[4]),
                "volume": float(item[5]),
            }
            for item in rows
        ]
        return self._records_to_dataframe(records)

    def _records_to_dataframe(self, records) -> pd.DataFrame:
        if not records:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        df = pd.DataFrame(records).drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
        now_ms = int(time.time() * 1000)
        step_ms = TIMEFRAME_TO_MS[self.timeframe]
        df = df[df["timestamp"] + step_ms <= now_ms]
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df

    def _parse_binance_message(self, payload: Dict) -> Optional[Dict]:
        if "data" in payload:
            payload = payload["data"]
        kline = payload.get("k")
        if not kline:
            return None
        return {
            "timestamp": int(kline["t"]),
            "open": float(kline["o"]),
            "high": float(kline["h"]),
            "low": float(kline["l"]),
            "close": float(kline["c"]),
            "volume": float(kline["v"]),
            "is_closed": bool(kline.get("x")),
        }

    def _parse_bybit_message(self, payload: Dict) -> Optional[Dict]:
        if payload.get("op") in {"pong", "subscribe"}:
            return None
        data = payload.get("data")
        if not data:
            return None

        candle = data[0] if isinstance(data, list) else data
        return {
            "timestamp": int(candle["start"]),
            "open": float(candle["open"]),
            "high": float(candle["high"]),
            "low": float(candle["low"]),
            "close": float(candle["close"]),
            "volume": float(candle.get("volume", 0.0)),
            "is_closed": bool(candle.get("confirm")),
        }

    def _ingest_candle(self, candle: Dict):
        timestamp = pd.to_datetime(int(candle["timestamp"]), unit="ms")
        with self._lock:
            self.last_price = float(candle["close"])
            self.last_message_at = time.time()

            if candle.get("is_closed"):
                candle_to_store = {
                    "timestamp": int(candle["timestamp"]),
                    "open": float(candle["open"]),
                    "high": float(candle["high"]),
                    "low": float(candle["low"]),
                    "close": float(candle["close"]),
                    "volume": float(candle["volume"]),
                }
                self._candles[timestamp] = candle_to_store
                self._candles.move_to_end(timestamp)
                self._trim_candles_locked()
                self._current_candle = None
                self._ready_event.set()
            else:
                self._current_candle = candle

    def _trim_candles_locked(self):
        while len(self._candles) > self.max_candles:
            self._candles.popitem(last=False)

    def _normalize_symbol(self, symbol: str) -> str:
        if not symbol:
            raise ValueError("Simbolo vazio para stream real")
        return symbol.replace("/", "").replace(":USDT", "").upper()
