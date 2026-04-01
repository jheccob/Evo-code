from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable, Optional

import numpy as np
import pandas as pd

from trading_core.constants import (
    MARKET_DATA_CACHE_TTL_SECONDS,
    MAX_MARKET_DATA_CACHE_ITEMS,
    MAX_STREAM_CLIENTS,
    STREAM_CLIENT_STALE_SECONDS,
)

logger = logging.getLogger(__name__)


def build_stream_key(symbol: str, timeframe: str) -> str:
    return f"{symbol}_{timeframe}"


def extract_stream_client(entry):
    if isinstance(entry, dict):
        return entry.get("client")
    return entry


def build_market_data_signature(df: Optional[pd.DataFrame]):
    if df is None or df.empty:
        return ("empty", 0, None, None, None)

    last_row = df.iloc[-1]
    last_index = pd.Timestamp(df.index[-1]).value
    return (
        len(df),
        int(last_index),
        float(last_row.get("close", np.nan)),
        float(last_row.get("volume", np.nan)),
        bool(last_row.get("is_closed", True)),
    )


def track_stream_client(bot, stream_key: str, client):
    bot._stream_clients[stream_key] = {
        "client": client,
        "last_accessed": datetime.now(),
    }


def invalidate_market_data_cache(bot, symbol: str, timeframe: str):
    if not hasattr(bot, "_cache_data"):
        bot._cache_data = {}

    cache_prefix = f"{symbol}_{timeframe}_"
    keys_to_delete = [key for key in bot._cache_data if key.startswith(cache_prefix)]
    for key in keys_to_delete:
        del bot._cache_data[key]


def stop_stream_client(bot, stream_key: str):
    if not hasattr(bot, "_stream_clients"):
        bot._stream_clients = {}

    entry = bot._stream_clients.pop(stream_key, None)
    client = extract_stream_client(entry)
    if client is None:
        return

    try:
        client.stop()
    except Exception as exc:
        logger.warning("Falha ao parar stream client %s: %s", stream_key, exc)


def cleanup_stream_clients(
    bot,
    keep_keys: Optional[Iterable[str]] = None,
    stale_after_seconds: int = STREAM_CLIENT_STALE_SECONDS,
    max_clients: int = MAX_STREAM_CLIENTS,
):
    if not hasattr(bot, "_stream_clients"):
        bot._stream_clients = {}

    keep_keys = set(keep_keys or ())
    now = datetime.now()
    normalized_clients = {}

    for stream_key, entry in list(bot._stream_clients.items()):
        client = extract_stream_client(entry)
        if client is None:
            continue

        last_accessed = now
        if isinstance(entry, dict) and isinstance(entry.get("last_accessed"), datetime):
            last_accessed = entry["last_accessed"]

        normalized_clients[stream_key] = {
            "client": client,
            "last_accessed": last_accessed,
        }

    bot._stream_clients = normalized_clients

    stale_keys = [
        stream_key
        for stream_key, entry in bot._stream_clients.items()
        if stream_key not in keep_keys
        and (now - entry["last_accessed"]).total_seconds() > stale_after_seconds
    ]
    for stream_key in stale_keys:
        stop_stream_client(bot, stream_key)

    removable_keys = [
        (stream_key, entry["last_accessed"])
        for stream_key, entry in bot._stream_clients.items()
        if stream_key not in keep_keys
    ]
    removable_keys.sort(key=lambda item: item[1])

    overflow = max(0, len(bot._stream_clients) - max_clients)
    for stream_key, _ in removable_keys[:overflow]:
        stop_stream_client(bot, stream_key)


def reset_stream_client(bot, symbol: Optional[str] = None, timeframe: Optional[str] = None):
    symbol = symbol or bot.symbol
    timeframe = timeframe or bot.timeframe
    stream_key = build_stream_key(symbol, timeframe)
    stop_stream_client(bot, stream_key)
    invalidate_market_data_cache(bot, symbol, timeframe)


def get_realtime_stream_client(bot, symbol: Optional[str] = None, timeframe: Optional[str] = None):
    from trading_bot_websocket import StreamlinedTradingBot

    symbol = symbol or bot.symbol
    timeframe = timeframe or bot.timeframe
    stream_key = build_stream_key(symbol, timeframe)
    if not hasattr(bot, "_stream_clients"):
        bot._stream_clients = {}

    cleanup_stream_clients(bot, keep_keys={stream_key})

    client = extract_stream_client(bot._stream_clients.get(stream_key))
    if client is None:
        client = StreamlinedTradingBot(symbol, timeframe)
    track_stream_client(bot, stream_key, client)
    return client


def get_market_data(bot, limit=200, symbol: Optional[str] = None, timeframe: Optional[str] = None):
    symbol = symbol or bot.symbol
    timeframe = timeframe or bot.timeframe
    cache_key = (
        f"{symbol}_{timeframe}_{limit}_"
        f"rsi{bot.rsi_period}_{bot.rsi_min}_{bot.rsi_max}"
    )
    current_time = datetime.now()
    cached_item = None

    if not hasattr(bot, "_cache_data"):
        bot._cache_data = {}
    if cache_key in bot._cache_data:
        cached_item = bot._cache_data[cache_key]
        cache_age = (current_time - cached_item["timestamp"]).total_seconds()
        if cache_age < MARKET_DATA_CACHE_TTL_SECONDS:
            return cached_item["data"]

    df = None
    realtime_error = None
    rest_error = None
    try:
        logger.info("Conectando ao stream real de mercado para %s %s", symbol, timeframe)
        df = get_realtime_stream_client(bot, symbol=symbol, timeframe=timeframe).get_market_data(
            limit=limit,
            timeout=20,
        )
    except Exception as exc:
        realtime_error = exc
        logger.warning("Falha ao obter dados pelo stream real: %s", exc)

    if df is None:
        logger.warning("Stream indisponivel; tentando REST real")
        try:
            df = bot._fetch_public_ohlcv(limit=limit, symbol=symbol, timeframe=timeframe)
            df["is_closed"] = True
        except Exception as exc:
            rest_error = exc
            logger.warning("Fallback REST real tambem indisponivel: %s", exc)

        if df is None:
            raise ConnectionError(
                "Nao foi possivel obter dados reais de mercado via stream nem via REST"
            ) from (rest_error or realtime_error)

    data_signature = build_market_data_signature(df)
    if cached_item and cached_item.get("data_signature") == data_signature:
        cached_item["timestamp"] = current_time
        return cached_item["data"]

    df = bot.calculate_indicators(df)
    bot._cache_data[cache_key] = {
        "data": df.copy(),
        "timestamp": current_time,
        "data_signature": data_signature,
    }

    if len(bot._cache_data) > MAX_MARKET_DATA_CACHE_ITEMS:
        oldest_key = min(bot._cache_data.keys(), key=lambda key: bot._cache_data[key]["timestamp"])
        del bot._cache_data[oldest_key]

    return df


def calculate_indicators(bot, df):
    logger.debug("Calculando RSI com periodo %s", bot.rsi_period)
    df["rsi"] = bot.indicators.calculate_rsi(df["close"], bot.rsi_period)

    current_rsi = df["rsi"].iloc[-1] if not df["rsi"].empty else None
    if current_rsi is not None and not pd.isna(current_rsi):
        logger.debug(
            "RSI atual: %.2f (Min: %s, Max: %s)",
            current_rsi,
            bot.rsi_min,
            bot.rsi_max,
        )
    else:
        logger.warning("RSI nao calculado ou invalido")

    smas = bot.indicators.calculate_multiple_sma(df["close"], periods=[21, 50, 200])
    df["sma_21"] = smas["sma_21"]
    df["sma_50"] = smas["sma_50"]
    df["sma_200"] = smas["sma_200"]
    df["sma_20"] = df["close"].rolling(window=20).mean()
    df["ema_9"] = df["close"].ewm(span=9, adjust=False).mean()
    df["ema_21"] = df["close"].ewm(span=21, adjust=False).mean()
    df["ema_50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema_200"] = df["close"].ewm(span=200, adjust=False).mean()

    macd_data = bot.indicators.calculate_macd(df["close"])
    df["macd"] = macd_data["macd"]
    df["macd_signal"] = macd_data["signal"]
    df["macd_histogram"] = macd_data["histogram"]
    df["prev_macd_histogram"] = df["macd_histogram"].shift(1)

    df["atr"] = bot.indicators.calculate_atr(df["high"], df["low"], df["close"])

    stoch_rsi = bot.indicators.calculate_stochastic_rsi(df["rsi"])
    df["stoch_rsi_k"] = stoch_rsi["stoch_rsi_k"]
    df["stoch_rsi_d"] = stoch_rsi["stoch_rsi_d"]

    adx_data = bot.indicators.calculate_adx(df["high"], df["low"], df["close"])
    df["adx"] = adx_data["adx"]
    df["di_plus"] = adx_data["di_plus"]
    df["di_minus"] = adx_data["di_minus"]

    df["williams_r"] = bot.indicators.calculate_williams_r(df["high"], df["low"], df["close"])

    bb = bot.indicators.calculate_bollinger_bands(df["close"])
    df["bb_upper"] = bb["upper"]
    df["bb_middle"] = bb["middle"]
    df["bb_lower"] = bb["lower"]
    df["bb_width"] = (bb["upper"] - bb["lower"]) / bb["middle"]

    df["volume_ma"] = df["volume"].rolling(window=20).mean()
    df["volume_ratio"] = df["volume"] / df["volume_ma"]
    df["prev_close"] = df["close"].shift(1)
    df["prev_rsi"] = df["rsi"].shift(1)

    df["market_regime"] = "trending"
    if len(df) >= 50:
        for i in range(49, len(df)):
            regime = bot.indicators.detect_market_regime(
                df["close"].iloc[max(0, i - 20):i + 1],
                df["volume"].iloc[max(0, i - 20):i + 1],
                df["atr"].iloc[max(0, i - 20):i + 1],
                df["adx"].iloc[max(0, i - 20):i + 1],
                di_plus=df["di_plus"].iloc[max(0, i - 20):i + 1],
                di_minus=df["di_minus"].iloc[max(0, i - 20):i + 1],
            )
            df.iloc[i, df.columns.get_loc("market_regime")] = regime

    df["trend_analysis"] = ""
    df["trend_strength"] = 0
    if len(df) >= 200:
        for i in range(199, len(df)):
            if not pd.isna(df["sma_200"].iloc[i]):
                trend_data = bot.indicators.analyze_trend_strength(
                    df["close"].iloc[i:i + 1],
                    df["sma_21"].iloc[i:i + 1],
                    df["sma_50"].iloc[i:i + 1],
                    df["sma_200"].iloc[i:i + 1],
                )
                df.iloc[i, df.columns.get_loc("trend_analysis")] = trend_data["trend"]
                df.iloc[i, df.columns.get_loc("trend_strength")] = trend_data["strength"]

    return df
