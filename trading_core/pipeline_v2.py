from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from config import ProductionConfig


ACTIONABLE_SIGNALS = {"COMPRA", "VENDA"}

EVO_LONG_SETUP = "ema_rsi_resume_long"
EVO_SHORT_SETUP = "ema_rsi_resume_short"
EVO_LONG_STATE = "ema_rsi_resume_bull"
EVO_SHORT_STATE = "ema_rsi_resume_bear"
EVO_LONG_SLOPE_LOOKBACK = 5
EVO_SHORT_SLOPE_LOOKBACK = 5
EVO_LONG_ATR_FLOOR_PCT = 0.10
EVO_SHORT_ATR_FLOOR_PCT = 0.10
EVO_DEFAULT_BUY_RSI_SIGNAL = 54.0
EVO_DEFAULT_SELL_RSI_SIGNAL = 47.0
EVO_LONG_REQUIRE_EMA200_ALIGNMENT = True
EVO_LONG_REQUIRE_FULL_EMA_STACK = True
EVO_LONG_REQUIRE_POSITIVE_MACD = True
EVO_SHORT_REQUIRE_EMA200_ALIGNMENT = True
EVO_SHORT_REQUIRE_NEGATIVE_MACD = True
EVO_SHORT_MIN_ADX = 18.0


def _reset_runtime(bot) -> None:
    bot._last_context_evaluation = None
    bot._last_regime_evaluation = None
    bot._last_price_structure_evaluation = None
    bot._last_confirmation_evaluation = None
    bot._last_entry_quality_evaluation = None
    bot._last_scenario_evaluation = None
    bot._last_market_state_evaluation = None
    bot._last_trade_decision = None
    bot._last_candidate_signal = "NEUTRO"
    bot._last_signal_pipeline = None
    bot._last_hard_block_evaluation = {
        "hard_block": False,
        "block_reason": None,
        "block_source": None,
        "notes": [],
    }


def _build_wait_market_state(
    reason: str,
    market_bias: str = "neutral",
    market_state: str = "neutral_chop",
) -> Dict[str, object]:
    return {
        "market_bias": market_bias,
        "market_state": market_state,
        "execution_mode": "standby",
        "action": "wait",
        "confidence": 0.0,
        "is_tradeable": False,
        "block_reason": None,
        "reason": reason,
        "legacy_setup_type": None,
    }


def _set_block(bot, reason: str, source: str, market_bias: str = "neutral") -> str:
    cleaned_reason = str(reason or "").strip() or "Leitura bloqueada."
    bot._last_hard_block_evaluation = {
        "hard_block": True,
        "block_reason": cleaned_reason,
        "block_source": source,
        "notes": [cleaned_reason],
    }
    bot._last_trade_decision = {
        "action": "wait",
        "confidence": 0.0,
        "market_bias": market_bias,
        "market_state": "blocked",
        "execution_mode": "standby",
        "setup_type": None,
        "entry_reason": None,
        "block_reason": cleaned_reason,
        "invalid_if": None,
    }
    bot._last_market_state_evaluation = {
        "market_bias": market_bias,
        "market_state": "blocked",
        "execution_mode": "standby",
        "action": "wait",
        "confidence": 0.0,
        "is_tradeable": False,
        "block_reason": cleaned_reason,
        "reason": cleaned_reason,
        "legacy_setup_type": None,
    }
    return "NEUTRO"


def _prefer_closed_candles(bot, df: Optional[pd.DataFrame]) -> pd.DataFrame:
    working_df = bot._prefer_closed_candles(df)
    if working_df is None:
        return pd.DataFrame()
    return working_df.sort_index().copy()


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _slope_pct(series: pd.Series, lookback: int = 4) -> float:
    clean_series = series.dropna()
    if len(clean_series) <= lookback:
        return 0.0
    start_value = _safe_float(clean_series.iloc[-(lookback + 1)], 0.0)
    end_value = _safe_float(clean_series.iloc[-1], 0.0)
    if start_value == 0:
        return 0.0
    return ((end_value - start_value) / abs(start_value)) * 100.0


def _ensure_indicator_columns(bot, df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    indicator_engine = getattr(bot, "indicators", None)

    if "ema_9" not in df.columns:
        df["ema_9"] = df["close"].ewm(span=9, adjust=False).mean()
    if "ema_21" not in df.columns:
        df["ema_21"] = df["close"].ewm(span=21, adjust=False).mean()
    if "ema_50" not in df.columns:
        df["ema_50"] = df["close"].ewm(span=50, adjust=False).mean()
    if "ema_200" not in df.columns:
        df["ema_200"] = df["close"].ewm(span=200, adjust=False).mean()
    if "rsi" not in df.columns:
        if indicator_engine is not None:
            df["rsi"] = indicator_engine.calculate_rsi(df["close"], getattr(bot, "rsi_period", 14))
        else:
            delta = df["close"].diff()
            gain = delta.clip(lower=0.0)
            loss = -delta.clip(upper=0.0)
            window = max(int(getattr(bot, "rsi_period", 14) or 14), 2)
            avg_gain = gain.rolling(window=window, min_periods=2).mean()
            avg_loss = loss.rolling(window=window, min_periods=2).mean()
            rs = avg_gain / avg_loss.replace(0.0, np.nan)
            df["rsi"] = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)
    if "macd" not in df.columns or "macd_signal" not in df.columns or "macd_histogram" not in df.columns:
        if indicator_engine is not None:
            macd_data = indicator_engine.calculate_macd(df["close"])
            df["macd"] = macd_data["macd"]
            df["macd_signal"] = macd_data["signal"]
            df["macd_histogram"] = macd_data["histogram"]
        else:
            ema_fast = df["close"].ewm(span=12, adjust=False).mean()
            ema_slow = df["close"].ewm(span=26, adjust=False).mean()
            df["macd"] = ema_fast - ema_slow
            df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
            df["macd_histogram"] = df["macd"] - df["macd_signal"]
    if "atr" not in df.columns:
        if indicator_engine is not None:
            df["atr"] = indicator_engine.calculate_atr(df["high"], df["low"], df["close"])
        else:
            prev_close = df["close"].shift(1)
            true_range = pd.concat(
                [
                    (df["high"] - df["low"]).abs(),
                    (df["high"] - prev_close).abs(),
                    (df["low"] - prev_close).abs(),
                ],
                axis=1,
            ).max(axis=1)
            df["atr"] = true_range.rolling(window=14, min_periods=1).mean()
    if "adx" not in df.columns or "di_plus" not in df.columns or "di_minus" not in df.columns:
        if indicator_engine is not None:
            adx_data = indicator_engine.calculate_adx(df["high"], df["low"], df["close"])
            df["adx"] = adx_data["adx"]
            df["di_plus"] = adx_data["di_plus"]
            df["di_minus"] = adx_data["di_minus"]
        else:
            up_move = df["high"].diff()
            down_move = -df["low"].diff()
            df["di_plus"] = up_move.clip(lower=0.0).rolling(window=14, min_periods=1).mean().fillna(0.0)
            df["di_minus"] = down_move.clip(lower=0.0).rolling(window=14, min_periods=1).mean().fillna(0.0)
            directional_gap = (df["di_plus"] - df["di_minus"]).abs()
            directional_base = (df["di_plus"] + df["di_minus"]).replace(0.0, np.nan)
            df["adx"] = ((directional_gap / directional_base) * 100.0).fillna(0.0)
    if "volume_ratio" not in df.columns:
        volume_ma = df["volume"].rolling(window=20, min_periods=5).mean()
        df["volume_ratio"] = df["volume"] / volume_ma.replace(0, np.nan)
    if "prev_close" not in df.columns:
        df["prev_close"] = df["close"].shift(1)
    if "prev_rsi" not in df.columns:
        df["prev_rsi"] = df["rsi"].shift(1)
    return df


def _resolve_resume_thresholds(bot) -> tuple[float, float]:
    buy_threshold = float(getattr(bot, "rsi_min", EVO_DEFAULT_BUY_RSI_SIGNAL) or EVO_DEFAULT_BUY_RSI_SIGNAL)
    sell_threshold = float(getattr(bot, "rsi_max", EVO_DEFAULT_SELL_RSI_SIGNAL) or EVO_DEFAULT_SELL_RSI_SIGNAL)
    return buy_threshold, sell_threshold


def _build_resume_regime_evaluation(df: pd.DataFrame, timeframe: Optional[str]) -> Dict[str, object]:
    last_row = df.iloc[-1]
    close_price = _safe_float(last_row.get("close"))
    atr_value = _safe_float(last_row.get("atr"))
    atr_pct = (atr_value / close_price * 100.0) if close_price > 0 else 0.0
    ema_fast = _safe_float(last_row.get("ema_9"))
    ema_slow = _safe_float(last_row.get("ema_21"))
    ema_trend = _safe_float(last_row.get("ema_50"))
    slope_base_long = _safe_float(df["ema_21"].iloc[-(EVO_LONG_SLOPE_LOOKBACK + 1)])
    slope_base_short = _safe_float(df["ema_21"].iloc[-(EVO_SHORT_SLOPE_LOOKBACK + 1)])
    trend_up = ema_fast > ema_slow > ema_trend and ema_slow > slope_base_long
    trend_down = ema_fast < ema_slow < ema_trend and ema_slow < slope_base_short
    market_bias = "bullish" if trend_up else "bearish" if trend_down else "neutral"
    regime = "trend_bull" if trend_up else "trend_bear" if trend_down else "range"
    slope_pct = _slope_pct(df["ema_21"], lookback=4)
    regime_score = 7.2 if regime != "range" else 3.2
    if atr_pct >= (EVO_LONG_ATR_FLOOR_PCT if trend_up else EVO_SHORT_ATR_FLOOR_PCT if trend_down else 0.0):
        regime_score += 0.3
    regime_score += min(abs(slope_pct), 0.30) * 3.0
    regime_score = min(max(regime_score, 0.0), 8.8)
    return {
        "timeframe": timeframe,
        "regime": regime,
        "regime_score": round(float(regime_score), 2),
        "market_bias": market_bias,
        "adx": round(float(_safe_float(last_row.get("adx"))), 2),
        "atr_pct": round(float(atr_pct), 4),
        "ema_distance_pct": round(float(abs(close_price - ema_slow) / close_price * 100.0), 4) if close_price > 0 else 0.0,
        "ema_slope": round(float(slope_pct), 4),
        "volatility_state": "normal_volatility" if atr_pct > 0 else "low_volatility",
        "trend_state": regime,
        "parabolic": False,
        "legacy_regime": "trending" if regime != "range" else "ranging",
        "price_above_ema_200": bool(close_price >= _safe_float(last_row.get("ema_200"))) if close_price > 0 else False,
        "is_tradeable": regime != "range",
        "has_minimum_history": True,
        "notes": [
            f"EMA9 {ema_fast:.2f}",
            f"EMA21 {ema_slow:.2f}",
            f"EMA50 {ema_trend:.2f}",
            f"ATR% {atr_pct:.2f}",
        ],
        "reason": f"Motor EMA/RSI em {regime}",
    }


def _analyze_resume_signal(
    df: pd.DataFrame,
    buy_threshold: float,
    sell_threshold: float,
) -> Dict[str, object]:
    min_rows = max(50 + EVO_SHORT_SLOPE_LOOKBACK, 16)
    if len(df) < min_rows:
        return {
            "signal": "NEUTRO",
            "side": None,
            "reason": "Sem candles suficientes para o motor EMA/RSI.",
            "market_bias": "neutral",
            "atr_pct": 0.0,
            "confirmation_state": "weak",
            "price_location": "mid_range",
            "entry_score": 0.0,
            "scenario_score": 0.0,
            "setup_type": None,
            "market_state": "neutral_chop",
            "structure_state": "flat",
            "entry_quality": "bad",
        }

    last_row = df.iloc[-1]
    previous_row = df.iloc[-2]
    close_price = _safe_float(last_row.get("close"))
    ema_fast = _safe_float(last_row.get("ema_9"))
    ema_slow = _safe_float(last_row.get("ema_21"))
    ema_trend = _safe_float(last_row.get("ema_50"))
    ema_200 = _safe_float(last_row.get("ema_200"))
    rsi = _safe_float(last_row.get("rsi"), 50.0)
    previous_rsi = _safe_float(last_row.get("prev_rsi"), _safe_float(previous_row.get("rsi"), rsi))
    atr_value = _safe_float(last_row.get("atr"), 0.0)
    atr_pct = (atr_value / close_price * 100.0) if close_price > 0 else 0.0
    macd_histogram = _safe_float(last_row.get("macd_histogram"), 0.0)
    adx_value = _safe_float(last_row.get("adx"), 0.0)
    slope_base_long = _safe_float(df["ema_21"].iloc[-(EVO_LONG_SLOPE_LOOKBACK + 1)])
    slope_base_short = _safe_float(df["ema_21"].iloc[-(EVO_SHORT_SLOPE_LOOKBACK + 1)])

    trend_up = ema_fast > ema_slow > ema_trend and ema_slow > slope_base_long
    trend_down = ema_fast < ema_slow < ema_trend and ema_slow < slope_base_short
    rsi_cross_up = rsi > buy_threshold and previous_rsi <= buy_threshold
    rsi_cross_down = rsi < sell_threshold and previous_rsi >= sell_threshold

    if trend_up and EVO_LONG_REQUIRE_EMA200_ALIGNMENT and not (close_price > ema_200 and ema_slow > ema_200):
        return {
            "signal": "NEUTRO",
            "side": None,
            "reason": "Tendencia de alta curta, mas sem alinhamento acima da EMA200.",
            "market_bias": "bullish",
            "atr_pct": atr_pct,
            "confirmation_state": "waiting",
            "price_location": "trend_zone",
            "entry_score": 0.0,
            "scenario_score": 0.0,
            "setup_type": None,
            "market_state": "transition",
            "structure_state": "trend_resume_wait",
            "entry_quality": "acceptable",
        }
    if trend_up and EVO_LONG_REQUIRE_FULL_EMA_STACK and not (ema_trend > ema_200):
        return {
            "signal": "NEUTRO",
            "side": None,
            "reason": "Tendencia de alta curta, mas sem empilhamento completo acima da EMA200.",
            "market_bias": "bullish",
            "atr_pct": atr_pct,
            "confirmation_state": "waiting",
            "price_location": "trend_zone",
            "entry_score": 0.0,
            "scenario_score": 0.0,
            "setup_type": None,
            "market_state": "transition",
            "structure_state": "trend_resume_wait",
            "entry_quality": "acceptable",
        }
    if trend_up and EVO_LONG_REQUIRE_POSITIVE_MACD and macd_histogram <= 0:
        return {
            "signal": "NEUTRO",
            "side": None,
            "reason": "Tendencia de alta curta, mas sem confirmacao positiva de MACD.",
            "market_bias": "bullish",
            "atr_pct": atr_pct,
            "confirmation_state": "waiting",
            "price_location": "trend_zone",
            "entry_score": 0.0,
            "scenario_score": 0.0,
            "setup_type": None,
            "market_state": "transition",
            "structure_state": "trend_resume_wait",
            "entry_quality": "acceptable",
        }
    if trend_down and EVO_SHORT_REQUIRE_EMA200_ALIGNMENT and not (close_price < ema_200 and ema_slow < ema_200 and ema_trend < ema_200):
        return {
            "signal": "NEUTRO",
            "side": None,
            "reason": "Tendencia de baixa curta, mas sem alinhamento abaixo da EMA200.",
            "market_bias": "bearish",
            "atr_pct": atr_pct,
            "confirmation_state": "waiting",
            "price_location": "trend_zone",
            "entry_score": 0.0,
            "scenario_score": 0.0,
            "setup_type": None,
            "market_state": "transition",
            "structure_state": "trend_resume_wait",
            "entry_quality": "acceptable",
        }
    if trend_down and EVO_SHORT_REQUIRE_NEGATIVE_MACD and macd_histogram >= 0:
        return {
            "signal": "NEUTRO",
            "side": None,
            "reason": "Tendencia de baixa curta, mas sem confirmacao negativa de MACD.",
            "market_bias": "bearish",
            "atr_pct": atr_pct,
            "confirmation_state": "waiting",
            "price_location": "trend_zone",
            "entry_score": 0.0,
            "scenario_score": 0.0,
            "setup_type": None,
            "market_state": "transition",
            "structure_state": "trend_resume_wait",
            "entry_quality": "acceptable",
        }
    if trend_down and adx_value < EVO_SHORT_MIN_ADX:
        return {
            "signal": "NEUTRO",
            "side": None,
            "reason": "Tendencia de baixa curta, mas ADX ainda fraco para venda.",
            "market_bias": "bearish",
            "atr_pct": atr_pct,
            "confirmation_state": "waiting",
            "price_location": "trend_zone",
            "entry_score": 0.0,
            "scenario_score": 0.0,
            "setup_type": None,
            "market_state": "transition",
            "structure_state": "trend_resume_wait",
            "entry_quality": "acceptable",
        }
    if trend_up and atr_pct < EVO_LONG_ATR_FLOOR_PCT:
        return {
            "signal": "NEUTRO",
            "side": None,
            "reason": "Tendencia de alta, mas volatilidade fraca para compra.",
            "market_bias": "bullish",
            "atr_pct": atr_pct,
            "confirmation_state": "waiting",
            "price_location": "trend_zone",
            "entry_score": 0.0,
            "scenario_score": 0.0,
            "setup_type": None,
            "market_state": "transition",
            "structure_state": "trend_resume_wait",
            "entry_quality": "acceptable",
        }
    if trend_down and atr_pct < EVO_SHORT_ATR_FLOOR_PCT:
        return {
            "signal": "NEUTRO",
            "side": None,
            "reason": "Tendencia de baixa, mas volatilidade fraca para venda.",
            "market_bias": "bearish",
            "atr_pct": atr_pct,
            "confirmation_state": "waiting",
            "price_location": "trend_zone",
            "entry_score": 0.0,
            "scenario_score": 0.0,
            "setup_type": None,
            "market_state": "transition",
            "structure_state": "trend_resume_wait",
            "entry_quality": "acceptable",
        }
    if trend_up and rsi_cross_up:
        if close_price <= ema_fast:
            return {
                "signal": "NEUTRO",
                "side": None,
                "reason": "Gatilho comprador sem confirmacao acima da EMA curta.",
                "market_bias": "bullish",
                "atr_pct": atr_pct,
                "confirmation_state": "mixed",
                "price_location": "trend_zone",
                "entry_score": 0.0,
                "scenario_score": 0.0,
                "setup_type": None,
                "market_state": "transition",
                "structure_state": "trend_resume_wait",
                "entry_quality": "acceptable",
            }
        return {
            "signal": "COMPRA",
            "side": "long",
            "reason": "retomada compradora dentro da tendencia de alta",
            "market_bias": "bullish",
            "atr_pct": atr_pct,
            "confirmation_state": "confirmed",
            "price_location": "above_ema_fast",
            "entry_score": 7.8,
            "scenario_score": 7.6,
            "setup_type": EVO_LONG_SETUP,
            "market_state": EVO_LONG_STATE,
            "structure_state": "trend_resume",
            "entry_quality": "strong",
        }
    if trend_down and rsi_cross_down:
        if close_price >= ema_fast:
            return {
                "signal": "NEUTRO",
                "side": None,
                "reason": "Gatilho vendedor sem confirmacao abaixo da EMA curta.",
                "market_bias": "bearish",
                "atr_pct": atr_pct,
                "confirmation_state": "mixed",
                "price_location": "trend_zone",
                "entry_score": 0.0,
                "scenario_score": 0.0,
                "setup_type": None,
                "market_state": "transition",
                "structure_state": "trend_resume_wait",
                "entry_quality": "acceptable",
            }
        return {
            "signal": "VENDA",
            "side": "short",
            "reason": "retomada vendedora dentro da tendencia de baixa",
            "market_bias": "bearish",
            "atr_pct": atr_pct,
            "confirmation_state": "confirmed",
            "price_location": "below_ema_fast",
            "entry_score": 7.6,
            "scenario_score": 7.4,
            "setup_type": EVO_SHORT_SETUP,
            "market_state": EVO_SHORT_STATE,
            "structure_state": "trend_resume",
            "entry_quality": "strong",
        }
    if trend_up:
        return {
            "signal": "NEUTRO",
            "side": None,
            "reason": "Tendencia de alta sem novo cruzamento de RSI.",
            "market_bias": "bullish",
            "atr_pct": atr_pct,
            "confirmation_state": "waiting",
            "price_location": "trend_zone",
            "entry_score": 0.0,
            "scenario_score": 0.0,
            "setup_type": None,
            "market_state": "transition",
            "structure_state": "trend_resume_wait",
            "entry_quality": "acceptable",
        }
    if trend_down:
        return {
            "signal": "NEUTRO",
            "side": None,
            "reason": "Tendencia de baixa sem novo cruzamento de RSI.",
            "market_bias": "bearish",
            "atr_pct": atr_pct,
            "confirmation_state": "waiting",
            "price_location": "trend_zone",
            "entry_score": 0.0,
            "scenario_score": 0.0,
            "setup_type": None,
            "market_state": "transition",
            "structure_state": "trend_resume_wait",
            "entry_quality": "acceptable",
        }
    return {
        "signal": "NEUTRO",
        "side": None,
        "reason": "mercado sem alinhamento de tendencia",
        "market_bias": "neutral",
        "atr_pct": atr_pct,
        "confirmation_state": "weak",
        "price_location": "mid_range",
        "entry_score": 0.0,
        "scenario_score": 0.0,
        "setup_type": None,
        "market_state": "neutral_chop",
        "structure_state": "flat",
        "entry_quality": "bad",
    }


def _build_resume_context_evaluation(
    bot,
    context_df: Optional[pd.DataFrame],
    buy_threshold: float,
    sell_threshold: float,
) -> Optional[Dict[str, object]]:
    if context_df is None or context_df.empty:
        return None
    working_df = _ensure_indicator_columns(bot, _prefer_closed_candles(bot, context_df))
    analysis = _analyze_resume_signal(working_df, buy_threshold=buy_threshold, sell_threshold=sell_threshold)
    market_bias = analysis["market_bias"]
    return {
        "market_bias": market_bias,
        "bias": market_bias,
        "context_strength": 7.5 if market_bias in {"bullish", "bearish"} else 3.0,
        "is_tradeable": market_bias in {"bullish", "bearish"},
        "reason": analysis["reason"],
    }


def _set_resume_pipeline_state(
    bot,
    working_df: pd.DataFrame,
    analysis: Dict[str, object],
    context_evaluation: Optional[Dict[str, object]],
    timeframe: Optional[str],
    stop_loss_pct: Optional[float],
    take_profit_pct: Optional[float],
) -> None:
    rr_estimate = 0.0
    if float(stop_loss_pct or 0.0) > 0 and float(take_profit_pct or 0.0) > 0:
        rr_estimate = float(take_profit_pct) / float(stop_loss_pct)
    elif float(ProductionConfig.DEFAULT_LIVE_STOP_LOSS_PCT or 0.0) > 0:
        rr_estimate = float(ProductionConfig.DEFAULT_LIVE_TAKE_PROFIT_PCT) / float(ProductionConfig.DEFAULT_LIVE_STOP_LOSS_PCT)

    bot._last_context_evaluation = context_evaluation or {
        "market_bias": analysis["market_bias"],
        "bias": analysis["market_bias"],
        "context_strength": 6.0 if analysis["market_bias"] in {"bullish", "bearish"} else 3.0,
        "is_tradeable": analysis["market_bias"] in {"bullish", "bearish"},
        "reason": "Sem contexto superior; usando a leitura do timeframe principal.",
    }
    bot._last_regime_evaluation = _build_resume_regime_evaluation(working_df, timeframe=timeframe)
    bot._last_price_structure_evaluation = {
        "structure_state": analysis["structure_state"],
        "structure_quality": 7.0 if analysis["signal"] in ACTIONABLE_SIGNALS else 4.0,
        "price_location": analysis["price_location"],
        "notes": [analysis["reason"]],
        "breakout_pressure": False,
        "breakout_pressure_side": "",
        "trend_bias": analysis["market_bias"],
    }
    bot._last_confirmation_evaluation = {
        "confirmation_state": analysis["confirmation_state"],
        "notes": [analysis["reason"]],
        "hypothesis_side": analysis["market_bias"] if analysis["market_bias"] in {"bullish", "bearish"} else None,
    }
    bot._last_entry_quality_evaluation = {
        "entry_quality": analysis["entry_quality"],
        "entry_score": float(analysis["entry_score"]),
        "objective_passed": analysis["signal"] in ACTIONABLE_SIGNALS,
        "objective_quality": analysis["entry_quality"],
        "setup_type": analysis["setup_type"],
        "rr_estimate": round(float(rr_estimate), 2),
        "rejection_reason": None if analysis["signal"] in ACTIONABLE_SIGNALS else analysis["reason"],
        "notes": [analysis["reason"]],
        "minimum_scenario_score": 6.0,
        "entry_reason": analysis["reason"],
    }
    bot._last_scenario_evaluation = {
        "scenario_score": float(analysis["scenario_score"]),
        "scenario_grade": "A" if analysis["scenario_score"] >= 7.5 else "B" if analysis["scenario_score"] >= 6.5 else "C",
        "pullback_intensity": "not_applicable",
        "pullback_score": 0.0,
        "notes": [analysis["reason"]],
        "has_minimum_history": True,
    }


def check_signal(
    bot,
    df,
    min_confidence=60,
    require_volume=True,
    require_trend=False,
    avoid_ranging=False,
    crypto_optimized=True,
    timeframe="5m",
    day_trading_mode=False,
    context_df=None,
    context_timeframe: Optional[str] = None,
    stop_loss_pct: Optional[float] = None,
    take_profit_pct: Optional[float] = None,
):
    del crypto_optimized, day_trading_mode, context_timeframe

    _reset_runtime(bot)
    working_df = _prefer_closed_candles(bot, df)
    if working_df.empty:
        return _set_block(bot, "Sem candles suficientes para o motor EMA/RSI.", "market_data")
    if avoid_ranging:
        raw_market_regime = str(working_df.iloc[-1].get("market_regime") or "").strip().lower()
        if raw_market_regime in {"ranging", "range", "neutral_chop"}:
            return _set_block(bot, "Mercado lateral demais para o motor EMA/RSI.", "market_regime")

    working_df = _ensure_indicator_columns(bot, working_df)
    if len(working_df) < max(50 + EVO_SHORT_SLOPE_LOOKBACK, 16):
        return _set_block(bot, "Sem candles suficientes para o motor EMA/RSI.", "market_data")

    buy_threshold, sell_threshold = _resolve_resume_thresholds(bot)
    analysis = _analyze_resume_signal(working_df, buy_threshold=buy_threshold, sell_threshold=sell_threshold)
    context_evaluation = _build_resume_context_evaluation(
        bot,
        context_df=context_df,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
    )
    _set_resume_pipeline_state(
        bot,
        working_df=working_df,
        analysis=analysis,
        context_evaluation=context_evaluation,
        timeframe=timeframe,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
    )

    if avoid_ranging and analysis["market_bias"] == "neutral":
        return _set_block(bot, "Mercado sem alinhamento de tendencia para o motor EMA/RSI.", "market_regime")

    if analysis["signal"] not in ACTIONABLE_SIGNALS:
        bot._last_market_state_evaluation = _build_wait_market_state(
            analysis["reason"],
            market_bias=analysis["market_bias"],
            market_state="neutral_chop" if analysis["market_bias"] == "neutral" else "transition",
        )
        bot._last_trade_decision = {
            "action": "wait",
            "confidence": 0.0,
            "market_bias": analysis["market_bias"],
            "market_state": bot._last_market_state_evaluation["market_state"],
            "execution_mode": "standby",
            "setup_type": None,
            "entry_reason": None,
            "block_reason": None,
            "invalid_if": None,
        }
        return "NEUTRO"

    bot._last_candidate_signal = analysis["signal"]
    context_bias = (context_evaluation or {}).get("market_bias")
    if context_bias in {"bullish", "bearish"} and context_bias != analysis["market_bias"]:
        return _set_block(bot, "Timeframe superior em vies oposto ao gatilho atual.", "higher_timeframe_context", market_bias=analysis["market_bias"])

    last_row = working_df.iloc[-1]
    volume_ratio = _safe_float(last_row.get("volume_ratio"), 1.0)
    if require_volume and volume_ratio < 0.85:
        return _set_block(bot, "Volume abaixo do piso minimo para validar o gatilho mecanico.", "volume_floor", market_bias=analysis["market_bias"])

    if require_trend and analysis["market_bias"] == "neutral":
        return _set_block(bot, "Leitura sem tendencia definida para operar.", "trend_alignment", market_bias=analysis["market_bias"])

    effective_score = max(
        _safe_float(bot._last_entry_quality_evaluation.get("entry_score"), 0.0),
        _safe_float(bot._last_scenario_evaluation.get("scenario_score"), 0.0),
    )
    if effective_score * 10.0 < float(min_confidence or 60.0):
        return _set_block(
            bot,
            f"Confianca abaixo do minimo operacional ({effective_score * 10.0:.1f}% < {float(min_confidence or 60.0):.1f}%).",
            "setup_score",
            market_bias=analysis["market_bias"],
        )

    action = "buy" if analysis["signal"] == "COMPRA" else "sell"
    bot._last_market_state_evaluation = {
        "market_bias": analysis["market_bias"],
        "market_state": analysis["market_state"],
        "execution_mode": "ema_rsi_resume",
        "action": action,
        "confidence": effective_score,
        "is_tradeable": True,
        "block_reason": None,
        "reason": analysis["reason"],
        "legacy_setup_type": analysis["setup_type"],
    }
    bot._last_trade_decision = {
        "action": action,
        "confidence": effective_score,
        "market_bias": analysis["market_bias"],
        "market_state": analysis["market_state"],
        "execution_mode": "ema_rsi_resume",
        "setup_type": analysis["setup_type"],
        "entry_reason": analysis["reason"],
        "block_reason": None,
        "invalid_if": "perder o alinhamento das EMAs ou falhar o fechamento a favor do gatilho",
    }
    return analysis["signal"]


def get_signal_with_confidence(bot, df):
    analytical_signal = check_signal(
        bot,
        df,
        min_confidence=55,
        require_volume=False,
        require_trend=False,
        avoid_ranging=False,
        timeframe=getattr(bot, "timeframe", "15m"),
    )
    decision = getattr(bot, "_last_trade_decision", None) or {}
    return {
        "signal": analytical_signal,
        "confidence": float(decision.get("confidence", 0.0) or 0.0),
    }
