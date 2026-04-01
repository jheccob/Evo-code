from __future__ import annotations

from typing import Dict, Iterable, Optional

import numpy as np
import pandas as pd

from trading_core import pipeline_v2
from trading_core.constants import ACTIONABLE_SIGNALS, TREND_STRUCTURE_STATES


def evaluate_signal_pipeline(
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
    allowed_execution_setups: Optional[Iterable[str]] = None,
) -> Dict[str, object]:
    analytical_signal = bot.check_signal(
        df,
        min_confidence=min_confidence,
        require_volume=require_volume,
        require_trend=require_trend,
        avoid_ranging=avoid_ranging,
        crypto_optimized=crypto_optimized,
        timeframe=timeframe,
        day_trading_mode=day_trading_mode,
        context_df=context_df,
        context_timeframe=context_timeframe,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
    )
    analytical_signal = bot._apply_runtime_setup_execution_policy(
        analytical_signal,
        allowed_execution_setups=allowed_execution_setups,
    )
    return bot._finalize_signal_pipeline(analytical_signal)


def make_trade_decision(
    bot,
    context_result: Optional[Dict[str, object]],
    structure_result: Optional[Dict[str, object]],
    confirmation_result: Optional[Dict[str, object]],
    entry_result: Optional[Dict[str, object]],
    hard_block_result: Optional[Dict[str, object]],
    scenario_score_result: Optional[Dict[str, object]],
    risk_result: Optional[Dict[str, object]] = None,
    regime_result: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    market_state_evaluation = bot.evaluate_market_state(
        context_result=context_result,
        regime_result=regime_result,
        structure_result=structure_result,
        confirmation_result=confirmation_result,
        entry_result=entry_result,
        scenario_score_result=scenario_score_result,
        hard_block_result=hard_block_result,
        risk_result=risk_result,
    )

    market_bias = str(market_state_evaluation.get("market_bias") or "neutral")
    structure_state = str((structure_result or {}).get("structure_state") or "").strip().lower()
    setup_type = (
        (entry_result or {}).get("setup_type")
        or (
            structure_state
            if structure_state in {"pullback", "continuation"}
            else market_state_evaluation.get("legacy_setup_type")
        )
    )
    block_reason = market_state_evaluation.get("block_reason")
    confidence = float(market_state_evaluation.get("confidence", 0.0) or 0.0)
    action = str(market_state_evaluation.get("action") or "wait").lower()
    market_state = str(market_state_evaluation.get("market_state") or "neutral_chop")
    execution_mode = str(market_state_evaluation.get("execution_mode") or "standby")

    if action == "wait" or block_reason:
        decision = {
            "action": "wait",
            "confidence": confidence,
            "market_bias": market_bias,
            "market_state": market_state,
            "execution_mode": execution_mode,
            "setup_type": setup_type,
            "entry_reason": None,
            "block_reason": str(
                block_reason or market_state_evaluation.get("reason") or "Leitura sem edge operacional."
            ),
            "invalid_if": None,
        }
        bot._last_trade_decision = decision
        return decision

    decision = {
        "action": action,
        "confidence": confidence,
        "market_bias": market_bias,
        "market_state": market_state,
        "execution_mode": execution_mode,
        "setup_type": setup_type,
        "entry_reason": market_state_evaluation.get("reason"),
        "block_reason": None,
        "invalid_if": f"invalidar a leitura {market_state} no timeframe atual",
    }
    bot._last_trade_decision = decision
    return decision


def generate_advanced_signal(bot, row):
    if pd.isna(row["rsi"]) or pd.isna(row["macd"]) or pd.isna(row["macd_signal"]):
        return "NEUTRO"

    timeframe = getattr(bot, "timeframe", "5m")
    if timeframe == "5m":
        market_regime = row.get("market_regime", "trending")
        if market_regime == "ranging":
            return "NEUTRO"

        adx = row.get("adx", 0)
        if not pd.isna(adx) and adx < 25:
            return "NEUTRO"

        bb_width = row.get("bb_width", 0)
        atr = row.get("atr", 0)
        if not pd.isna(bb_width) and not pd.isna(atr):
            if bb_width > 0.15 or atr > row.get("close", 1) * 0.05:
                return "NEUTRO"
    else:
        market_regime = row.get("market_regime", "trending")
        adx = row.get("adx", 0)
        if not pd.isna(adx) and adx < 18:
            return "NEUTRO"

        bb_width = row.get("bb_width", 0)
        atr = row.get("atr", 0)
        if not pd.isna(bb_width) and not pd.isna(atr):
            if bb_width > 0.25 or atr > row.get("close", 1) * 0.08:
                return "NEUTRO"

    rsi = row["rsi"]
    stoch_rsi_k = row.get("stoch_rsi_k", 50)
    williams_r = row.get("williams_r", -50)
    macd = row["macd"]
    macd_signal = row["macd_signal"]
    macd_histogram = row["macd_histogram"]

    price = row["close"]
    sma_21 = row.get("sma_21", price)
    sma_50 = row.get("sma_50", price)
    sma_200 = row.get("sma_200", price)

    price_above_sma21 = price > sma_21
    sma21_above_sma50 = sma_21 > sma_50 if not pd.isna(sma_50) else True
    sma50_above_sma200 = sma_50 > sma_200 if not pd.isna(sma_200) else True

    volume_ratio = row.get("volume_ratio", 1)
    strong_volume = volume_ratio > 1.5
    exceptional_volume = volume_ratio > 2.0

    bb_upper = row.get("bb_upper", price)
    bb_lower = row.get("bb_lower", price)
    bb_position = (price - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5

    bullish_score = 0
    bearish_score = 0
    confidence_multiplier = 1.0

    rsi_oversold_threshold = bot.rsi_min if hasattr(bot, "rsi_min") else 20
    rsi_overbought_threshold = bot.rsi_max if hasattr(bot, "rsi_max") else 80
    if timeframe == "5m":
        confidence_multiplier = 1.2

    oversold_extreme = rsi_oversold_threshold - 5
    oversold_moderate = rsi_oversold_threshold + 8
    overbought_moderate = rsi_overbought_threshold - 8
    overbought_extreme = rsi_overbought_threshold + 5

    if rsi <= oversold_extreme:
        bullish_score += 5
        confidence_multiplier += 0.3
    elif rsi <= rsi_oversold_threshold:
        bullish_score += 4
        confidence_multiplier += 0.2
    elif rsi <= oversold_moderate:
        bullish_score += 2
    elif rsi >= overbought_extreme:
        bearish_score += 5
        confidence_multiplier += 0.3
    elif rsi >= rsi_overbought_threshold:
        bearish_score += 4
        confidence_multiplier += 0.2
    elif rsi >= overbought_moderate:
        bearish_score += 2

    if not pd.isna(stoch_rsi_k):
        if stoch_rsi_k < 15:
            bullish_score += 3
            confidence_multiplier += 0.1
        elif stoch_rsi_k < 25:
            bullish_score += 2
        elif stoch_rsi_k > 85:
            bearish_score += 3
            confidence_multiplier += 0.1
        elif stoch_rsi_k > 75:
            bearish_score += 2

    if not pd.isna(williams_r):
        if williams_r < -85:
            bullish_score += 3
        elif williams_r < -75:
            bullish_score += 2
        elif williams_r > -15:
            bearish_score += 3
        elif williams_r > -25:
            bearish_score += 2

    macd_bullish = macd > macd_signal and macd_histogram > 0
    macd_bearish = macd < macd_signal and macd_histogram < 0
    macd_strengthening = abs(macd_histogram) > abs(row.get("prev_macd_histogram", 0))

    if macd_bullish:
        bullish_score += 3 if macd_strengthening else 2
        if macd > 0:
            bullish_score += 1
    elif macd_bearish:
        bearish_score += 3 if macd_strengthening else 2
        if macd < 0:
            bearish_score += 1

    if price_above_sma21 and sma21_above_sma50 and sma50_above_sma200:
        bullish_score += 5
    elif not price_above_sma21 and not sma21_above_sma50 and not sma50_above_sma200:
        bearish_score += 5
    elif price_above_sma21 and sma21_above_sma50:
        bullish_score += 3
    elif not price_above_sma21 and not sma21_above_sma50:
        bearish_score += 3

    if exceptional_volume:
        if bullish_score > bearish_score:
            bullish_score += 3
            confidence_multiplier += 0.15
        elif bearish_score > bullish_score:
            bearish_score += 3
            confidence_multiplier += 0.15
    elif strong_volume:
        if bullish_score > bearish_score:
            bullish_score += 2
        elif bearish_score > bullish_score:
            bearish_score += 2

    if bb_position < 0.1 and bullish_score > 0:
        bullish_score += 2
    elif bb_position > 0.9 and bearish_score > 0:
        bearish_score += 2
    elif bb_position < 0.3 and macd_bullish:
        bullish_score += 1
    elif bb_position > 0.7 and macd_bearish:
        bearish_score += 1

    adx = row.get("adx", 0)
    if not pd.isna(adx):
        if adx > 40:
            trend_bonus = 3
            confidence_multiplier += 0.2
        elif adx > 30:
            trend_bonus = 2
            confidence_multiplier += 0.1
        else:
            trend_bonus = 1

        if bullish_score > bearish_score:
            bullish_score += trend_bonus
        elif bearish_score > bullish_score:
            bearish_score += trend_bonus

    price_momentum = price - row.get("prev_close", price)
    if not pd.isna(price_momentum) and price_momentum != 0:
        rsi_momentum = rsi - row.get("prev_rsi", rsi)
        if price_momentum > 0 and rsi_momentum < 0:
            bearish_score += 2
        elif price_momentum < 0 and rsi_momentum > 0:
            bullish_score += 2

    bullish_score = int(bullish_score * confidence_multiplier)
    bearish_score = int(bearish_score * confidence_multiplier)

    if timeframe == "5m":
        min_strong_signal = 8
        min_difference = 3
    else:
        min_strong_signal = 6
        min_difference = 2

    if bullish_score >= min_strong_signal + 3 and bullish_score > bearish_score + min_difference + 2:
        return "COMPRA"
    if bearish_score >= min_strong_signal + 3 and bearish_score > bullish_score + min_difference + 2:
        return "VENDA"
    if bullish_score >= min_strong_signal and bullish_score > bearish_score + min_difference:
        return "COMPRA"
    if bearish_score >= min_strong_signal and bearish_score > bullish_score + min_difference:
        return "VENDA"

    return "NEUTRO"


def calculate_signal_confidence(bot, row):
    indicators_dict = {
        "rsi": row["rsi"],
        "macd": row["macd"],
        "macd_signal": row["macd_signal"],
        "macd_histogram": row["macd_histogram"],
        "prev_macd_histogram": row.get("prev_macd_histogram", 0),
        "trend_analysis": row.get("trend_analysis", "LATERAL"),
        "trend_strength": row.get("trend_strength", 0),
        "adx": row.get("adx", 0),
        "stoch_rsi_k": row.get("stoch_rsi_k", 50),
        "williams_r": row.get("williams_r", -50),
        "volume_ratio": row.get("volume_ratio", 1),
        "market_regime": row.get("market_regime", "trending"),
        "hour": getattr(row.name, "hour", 12),
    }
    return bot.indicators.calculate_signal_confidence(indicators_dict)


def get_effective_min_confidence(bot, min_confidence: float, timeframe: Optional[str]) -> float:
    current_timeframe = timeframe or bot.timeframe or "5m"
    if current_timeframe == "5m":
        return float(max(68, min_confidence - 1))
    if current_timeframe == "15m":
        return float(max(66, min_confidence - 1))
    if current_timeframe == "30m":
        return float(max(58, min_confidence - 10))
    if current_timeframe == "1h":
        return float(max(56, min_confidence - 12))
    return float(max(62, min_confidence - 1))


def relax_low_confidence_signal(
    signal: str,
    confidence: float,
    effective_min_confidence: float,
    timeframe: Optional[str],
) -> Optional[str]:
    current_timeframe = timeframe or "5m"
    actionable_signals = {"COMPRA", "VENDA"}
    if signal not in actionable_signals:
        return None
    if current_timeframe not in {"30m", "1h"}:
        return None
    if confidence >= effective_min_confidence:
        return signal
    if confidence >= effective_min_confidence - 6.0:
        return signal
    return None


def calculate_advanced_score(bot, row, signal=None):
    if row is None or row.empty:
        return 0.0

    signal = signal or "NEUTRO"
    if signal.startswith("COMPRA"):
        signal_side = "bullish"
    elif signal.startswith("VENDA"):
        signal_side = "bearish"
    else:
        return 0.0

    scores = []

    rsi = row.get("rsi", 50)
    if not np.isnan(rsi):
        if signal_side == "bullish":
            if rsi < 20:
                scores.append(0.95)
            elif rsi < 30:
                scores.append(0.78)
            elif rsi < 38:
                scores.append(0.60)
            elif rsi > 80:
                scores.append(0.05)
            elif rsi > 70:
                scores.append(0.18)
            else:
                scores.append(0.45)
        else:
            if rsi > 80:
                scores.append(0.95)
            elif rsi > 70:
                scores.append(0.78)
            elif rsi > 62:
                scores.append(0.60)
            elif rsi < 20:
                scores.append(0.05)
            elif rsi < 30:
                scores.append(0.18)
            else:
                scores.append(0.45)

    macd = row.get("macd", 0)
    macd_signal = row.get("macd_signal", 0)
    macd_hist = row.get("macd_histogram", 0)
    if not np.isnan(macd) and not np.isnan(macd_signal):
        bullish_alignment = macd > macd_signal and macd_hist > 0
        bearish_alignment = macd < macd_signal and macd_hist < 0
        if (signal_side == "bullish" and bullish_alignment) or (signal_side == "bearish" and bearish_alignment):
            scores.append(0.85)
        elif (signal_side == "bullish" and bearish_alignment) or (signal_side == "bearish" and bullish_alignment):
            scores.append(0.15)
        else:
            scores.append(0.45)

    adx = row.get("adx", 0)
    if not np.isnan(adx):
        if adx > 40:
            scores.append(0.85)
        elif adx > 25:
            scores.append(0.65)
        else:
            scores.append(0.35)

    price = row.get("close", np.nan)
    sma_21 = row.get("sma_21", np.nan)
    sma_50 = row.get("sma_50", np.nan)
    if not np.isnan(price) and not np.isnan(sma_21):
        bullish_trend = price >= sma_21 and (np.isnan(sma_50) or sma_21 >= sma_50)
        bearish_trend = price <= sma_21 and (np.isnan(sma_50) or sma_21 <= sma_50)
        if signal_side == "bullish":
            scores.append(0.82 if bullish_trend else 0.22)
        else:
            scores.append(0.82 if bearish_trend else 0.22)

    di_plus = row.get("di_plus", np.nan)
    di_minus = row.get("di_minus", np.nan)
    if not np.isnan(di_plus) and not np.isnan(di_minus):
        if signal_side == "bullish":
            scores.append(0.78 if di_plus > di_minus else 0.20)
        else:
            scores.append(0.78 if di_minus > di_plus else 0.20)

    vol_ratio = row.get("volume_ratio", 1.0)
    if not np.isnan(vol_ratio):
        if vol_ratio > 2.0:
            scores.append(0.85)
        elif vol_ratio > 1.3:
            scores.append(0.65)
        else:
            scores.append(0.30)

    market_regime = row.get("market_regime", "trending")
    if market_regime == "trending":
        scores.append(0.75)
    elif market_regime == "ranging":
        scores.append(0.20)
    elif market_regime == "volatile":
        scores.append(0.25)
    else:
        scores.append(0.5)

    bb_width = row.get("bb_width", np.nan)
    if not np.isnan(bb_width):
        if bb_width > 0.18:
            scores.append(0.20)
        elif bb_width > 0.10:
            scores.append(0.45)
        else:
            scores.append(0.72)

    if not scores:
        return 0.0

    final_score = float(np.mean(scores))
    return min(1.0, max(0.0, final_score))


def generate_basic_signal(bot, row):
    rsi_bullish = row["rsi"] < bot.rsi_min
    rsi_bearish = row["rsi"] > bot.rsi_max
    macd_bullish = row["macd"] > row["macd_signal"] and row["macd_histogram"] > 0
    macd_bearish = row["macd"] < row["macd_signal"] and row["macd_histogram"] < 0

    if rsi_bullish and macd_bullish:
        return "COMPRA"
    if rsi_bearish and macd_bearish:
        return "VENDA"
    return "NEUTRO"


def passes_signal_structure_guardrail(
    bot,
    row,
    signal: str,
    timeframe: str,
    structure_evaluation: Optional[Dict[str, object]] = None,
) -> bool:
    if signal not in ACTIONABLE_SIGNALS or row is None:
        return True

    open_price = row.get("open", np.nan)
    high_price = row.get("high", np.nan)
    low_price = row.get("low", np.nan)
    close_price = row.get("close", np.nan)
    if any(pd.isna(value) for value in (open_price, high_price, low_price, close_price)):
        return True

    candle_range = float(high_price) - float(low_price)
    if candle_range <= 0:
        return False

    timeframe = timeframe or bot.timeframe or "5m"
    body_size = abs(float(close_price) - float(open_price))
    body_share = body_size / candle_range
    close_location = (float(close_price) - float(low_price)) / candle_range
    is_short_term = timeframe in {"5m", "15m"}
    structure_state = str((structure_evaluation or {}).get("structure_state") or "")
    structure_quality = float((structure_evaluation or {}).get("structure_quality", 0.0) or 0.0)
    price_location = str((structure_evaluation or {}).get("price_location") or "mid_range")
    supportive_structure = structure_state in TREND_STRUCTURE_STATES and structure_quality >= 5.0

    body_share_floor = 0.25 if is_short_term else 0.12
    if supportive_structure and not is_short_term:
        body_share_floor = 0.09
    if body_share < body_share_floor:
        return False

    atr_value = row.get("atr", np.nan)
    if not pd.isna(atr_value) and float(atr_value) > 0:
        min_body_vs_atr = 0.18 if is_short_term else 0.06
        if supportive_structure and not is_short_term:
            min_body_vs_atr = 0.04
        if body_size / float(atr_value) < min_body_vs_atr:
            return False

    sma_21 = row.get("sma_21", np.nan)
    max_distance_from_sma_atr = 2.4 if is_short_term else 3.6
    if supportive_structure and not is_short_term:
        max_distance_from_sma_atr = 4.2
    range_vs_atr = candle_range / float(atr_value) if not pd.isna(atr_value) and float(atr_value) > 0 else 1.0
    adverse_wick = (
        float(high_price) - max(float(open_price), float(close_price))
        if signal.startswith("COMPRA")
        else min(float(open_price), float(close_price)) - float(low_price)
    )
    adverse_wick_share = adverse_wick / candle_range if candle_range > 0 else 1.0

    if signal.startswith("COMPRA"):
        allow_soft_close = (
            not is_short_term
            and supportive_structure
            and price_location in {"trend_zone", "support", "resistance"}
            and close_location >= 0.34
            and body_share >= max(body_share_floor, 0.10)
        )
        if float(close_price) <= float(open_price) and not allow_soft_close:
            return False
        min_close_location = 0.58 if is_short_term else 0.40
        if supportive_structure and not is_short_term:
            min_close_location = 0.34
        if close_location < min_close_location:
            return False
        max_adverse_wick = 0.82 if is_short_term else 0.78
        if supportive_structure and not is_short_term:
            max_adverse_wick = 0.84
        if adverse_wick_share > max_adverse_wick:
            return False
        if (
            not pd.isna(sma_21)
            and not pd.isna(atr_value)
            and float(atr_value) > 0
            and (float(close_price) - float(sma_21)) / float(atr_value) > max_distance_from_sma_atr
        ):
            return False
        max_range_vs_atr = 4.2 if is_short_term else 4.8
        if supportive_structure and not is_short_term:
            max_range_vs_atr = 5.4
        if range_vs_atr > max_range_vs_atr and body_share < (0.42 if is_short_term else 0.28):
            return False
        return True

    allow_soft_close = (
        not is_short_term
        and supportive_structure
        and price_location in {"trend_zone", "support", "resistance"}
        and close_location <= 0.66
        and body_share >= max(body_share_floor, 0.10)
    )
    if float(close_price) >= float(open_price) and not allow_soft_close:
        return False
    max_close_location = 0.42 if is_short_term else 0.60
    if supportive_structure and not is_short_term:
        max_close_location = 0.66
    if close_location > max_close_location:
        return False
    max_adverse_wick = 0.82 if is_short_term else 0.78
    if supportive_structure and not is_short_term:
        max_adverse_wick = 0.84
    if adverse_wick_share > max_adverse_wick:
        return False
    if (
        not pd.isna(sma_21)
        and not pd.isna(atr_value)
        and float(atr_value) > 0
        and (float(sma_21) - float(close_price)) / float(atr_value) > max_distance_from_sma_atr
    ):
        return False
    max_range_vs_atr = 4.2 if is_short_term else 4.8
    if supportive_structure and not is_short_term:
        max_range_vs_atr = 5.4
    if range_vs_atr > max_range_vs_atr and body_share < (0.42 if is_short_term else 0.28):
        return False
    return True


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
    return pipeline_v2.check_signal(
        bot,
        df,
        min_confidence=min_confidence,
        require_volume=require_volume,
        require_trend=require_trend,
        avoid_ranging=avoid_ranging,
        crypto_optimized=crypto_optimized,
        timeframe=timeframe,
        day_trading_mode=day_trading_mode,
        context_df=context_df,
        context_timeframe=context_timeframe,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
    )


def generate_trend_signal(bot, row, rsi_min: float, rsi_max: float) -> str:
    di_plus = row.get("di_plus", 0)
    di_minus = row.get("di_minus", 0)
    macd_hist = row.get("macd_histogram", row.get("macd", 0) - row.get("macd_signal", 0))
    rsi = row.get("rsi", 50)
    adx = row.get("adx", 0)

    if pd.isna(di_plus) or pd.isna(di_minus) or pd.isna(macd_hist) or pd.isna(rsi) or pd.isna(adx):
        return "NEUTRO"
    if adx < 25:
        return "NEUTRO"

    if di_plus > di_minus and macd_hist > 0 and rsi <= rsi_max:
        return "COMPRA"
    if di_minus > di_plus and macd_hist < 0 and rsi >= rsi_min:
        return "VENDA"
    return "NEUTRO"


def get_signal_with_confidence(bot, df):
    return pipeline_v2.get_signal_with_confidence(bot, df)
