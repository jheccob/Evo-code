from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from config import ProductionConfig


def _prefer_closed_candles(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None:
        return pd.DataFrame()
    working_df = df.copy()
    if "is_closed" in working_df.columns:
        closed_df = working_df[working_df["is_closed"].fillna(False)]
        if not closed_df.empty:
            working_df = closed_df
    return working_df.sort_index()


def _safe_float(value: Optional[float], default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _apply_stop_precedence(current: Optional[float], candidate: Optional[float], side: str) -> Optional[float]:
    if candidate is None:
        return current
    if current is None:
        return candidate
    return max(current, candidate) if side == "long" else min(current, candidate)


def _build_trailing_candidate(close_price: float, atr_value: float, side: str, multiplier: float) -> Optional[float]:
    if atr_value <= 0 or multiplier <= 0:
        return None
    if side == "long":
        return close_price - (atr_value * multiplier)
    return close_price + (atr_value * multiplier)


def build_position_management_preview(
    stop_loss_pct: float,
    take_profit_pct: float,
    regime_evaluation: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    regime_evaluation = regime_evaluation or {}
    volatility_state = str(regime_evaluation.get("volatility_state") or "normal_volatility")
    parabolic = bool(regime_evaluation.get("parabolic", False))
    protection_mode = "normal"
    trailing_multiplier = ProductionConfig.TRAILING_ATR_MULTIPLIER
    if parabolic:
        protection_mode = "aggressive"
        trailing_multiplier = ProductionConfig.PARABOLIC_TRAILING_ATR_MULTIPLIER
    elif volatility_state == "high_volatility":
        protection_mode = "aggressive"
        trailing_multiplier = ProductionConfig.HIGH_VOL_TRAILING_ATR_MULTIPLIER
    elif volatility_state == "low_volatility":
        protection_mode = "conservative"

    return {
        "initial_stop_pct": round(float(stop_loss_pct or 0.0), 2),
        "initial_take_pct": round(float(take_profit_pct or 0.0), 2),
        "break_even_trigger_r": round(float(ProductionConfig.BREAK_EVEN_TRIGGER_R), 2),
        "trailing_trigger_r": round(float(ProductionConfig.TRAILING_TRIGGER_R), 2),
        "trailing_atr_multiplier": round(float(trailing_multiplier), 2),
        "protection_mode": protection_mode,
    }


def evaluate_position_management(
    recent_df: Optional[pd.DataFrame],
    side: str,
    entry_price: float,
    current_stop_price: Optional[float],
    current_take_price: Optional[float],
    initial_stop_price: Optional[float],
    initial_take_price: Optional[float],
    break_even_active: bool = False,
    trailing_active: bool = False,
    protection_level: str = "normal",
    regime_evaluation: Optional[Dict[str, object]] = None,
    mfe_pct: float = 0.0,
    mae_pct: float = 0.0,
    position_age_candles: int = 0,
) -> Dict[str, object]:
    regime_evaluation = regime_evaluation or {}
    evaluation = {
        "action": "hold",
        "action_reason": None,
        "stop_price": current_stop_price,
        "take_price": current_take_price,
        "trailing_active": bool(trailing_active),
        "break_even_active": bool(break_even_active),
        "protection_level": protection_level or "normal",
        "unrealized_rr": 0.0,
        "regime_exit_flag": False,
        "structure_exit_flag": False,
        "post_pump_protection": False,
        "mfe_pct": round(float(max(mfe_pct, 0.0)), 4),
        "mae_pct": round(float(max(mae_pct, 0.0)), 4),
        "notes": [],
    }

    if not ProductionConfig.ENABLE_DYNAMIC_POSITION_MANAGEMENT:
        evaluation["action_reason"] = "Gestao dinamica desabilitada por configuracao."
        return evaluation

    working_df = _prefer_closed_candles(recent_df)
    if working_df.empty:
        evaluation["action_reason"] = "Sem candles fechados para gerir a posicao."
        return evaluation

    last_row = working_df.iloc[-1]
    previous_row = working_df.iloc[-2] if len(working_df) > 1 else None
    close_price = _safe_float(last_row.get("close"))
    open_price = _safe_float(last_row.get("open"), close_price)
    high_price = _safe_float(last_row.get("high"), close_price)
    low_price = _safe_float(last_row.get("low"), close_price)
    atr_value = _safe_float(last_row.get("atr"))
    ema_21 = _safe_float(last_row.get("ema_21", last_row.get("sma_21")), close_price)
    previous_close = _safe_float(previous_row.get("close"), close_price) if previous_row is not None else close_price
    previous_open = _safe_float(previous_row.get("open"), previous_close) if previous_row is not None else previous_close

    if close_price <= 0 or initial_stop_price in (None, 0) or entry_price <= 0:
        evaluation["action_reason"] = "Risco inicial insuficiente para gerir a posicao."
        return evaluation

    initial_risk = abs(float(entry_price) - float(initial_stop_price))
    if initial_risk <= 0:
        evaluation["action_reason"] = "Risco inicial insuficiente para gerir a posicao."
        return evaluation

    favorable_move = max(high_price - entry_price, 0.0) if side == "long" else max(entry_price - low_price, 0.0)
    adverse_move = max(entry_price - low_price, 0.0) if side == "long" else max(high_price - entry_price, 0.0)
    close_move = (close_price - entry_price) if side == "long" else (entry_price - close_price)
    unrealized_rr = favorable_move / initial_risk if initial_risk > 0 else 0.0
    close_rr = close_move / initial_risk if initial_risk > 0 else 0.0

    evaluation["unrealized_rr"] = round(float(max(unrealized_rr, 0.0)), 4)
    evaluation["mfe_pct"] = round(float(max(mfe_pct, (favorable_move / entry_price) * 100.0)), 4)
    evaluation["mae_pct"] = round(float(max(mae_pct, (adverse_move / entry_price) * 100.0)), 4)
    progressed_rr = max(close_rr, evaluation["unrealized_rr"])

    regime = str(regime_evaluation.get("regime") or "range")
    regime_score = _safe_float(regime_evaluation.get("regime_score"))
    volatility_state = str(regime_evaluation.get("volatility_state") or "normal_volatility")
    parabolic = bool(regime_evaluation.get("parabolic", False))
    ema_distance_pct = abs(_safe_float(regime_evaluation.get("ema_distance_pct"), 0.0))

    candle_range = max(high_price - low_price, 1e-9)
    body_size = abs(close_price - open_price)
    body_share = body_size / candle_range
    upper_wick = high_price - max(open_price, close_price)
    lower_wick = min(open_price, close_price) - low_price
    adverse_wick_share = (lower_wick / candle_range) if side == "short" else (upper_wick / candle_range)
    adverse_directional_close = close_price < open_price if side == "long" else close_price > open_price
    prior_adverse_directional_close = previous_close < previous_open if side == "long" else previous_close > previous_open
    strong_opposite_candle = adverse_directional_close and body_share >= 0.55 and adverse_wick_share <= 0.35

    notes = evaluation["notes"]
    stop_price = current_stop_price
    take_price = current_take_price
    protection_level_value = evaluation["protection_level"]

    break_even_ready = (
        position_age_candles >= 1
        and not evaluation["break_even_active"]
        and close_rr >= ProductionConfig.BREAK_EVEN_TRIGGER_R
    )
    if break_even_ready:
        stop_price = _apply_stop_precedence(stop_price, float(entry_price), side)
        evaluation["break_even_active"] = True
        evaluation["action"] = "move_stop_to_break_even"
        evaluation["action_reason"] = "Trade atingiu 1R e moveu o stop para break-even."
        protection_level_value = "break_even"
        notes.append("break-even ativado em 1R")

    trailing_multiplier = ProductionConfig.TRAILING_ATR_MULTIPLIER
    if regime in {"trend_bull", "trend_bear"} and regime_score >= 7.0:
        trailing_multiplier = max(trailing_multiplier, 2.0)
    if volatility_state == "high_volatility":
        trailing_multiplier = min(trailing_multiplier, ProductionConfig.HIGH_VOL_TRAILING_ATR_MULTIPLIER)
    if parabolic:
        trailing_multiplier = min(trailing_multiplier, ProductionConfig.PARABOLIC_TRAILING_ATR_MULTIPLIER)

    consecutive_impulse = 0
    recent_rows = working_df.tail(min(3, len(working_df)))
    for _, row in recent_rows.iterrows():
        row_open = _safe_float(row.get("open"))
        row_close = _safe_float(row.get("close"))
        row_high = _safe_float(row.get("high"))
        row_low = _safe_float(row.get("low"))
        row_range = max(row_high - row_low, 1e-9)
        row_body_share = abs(row_close - row_open) / row_range
        if side == "long" and row_close > row_open and row_body_share >= 0.55:
            consecutive_impulse += 1
        elif side == "short" and row_close < row_open and row_body_share >= 0.55:
            consecutive_impulse += 1

    post_pump_protection = (
        parabolic
        or volatility_state == "high_volatility"
        or ema_distance_pct >= 2.8
        or consecutive_impulse >= 2
    )
    if post_pump_protection:
        evaluation["post_pump_protection"] = True
        protection_level_value = "aggressive"
        notes.append("protecao extra por expansao/parabolico")
        if close_rr >= max(1.25, ProductionConfig.BREAK_EVEN_TRIGGER_R):
            trail_candidate = _build_trailing_candidate(
                close_price=close_price,
                atr_value=atr_value,
                side=side,
                multiplier=min(trailing_multiplier, ProductionConfig.HIGH_VOL_TRAILING_ATR_MULTIPLIER),
            )
            tightened_stop = _apply_stop_precedence(stop_price, trail_candidate, side)
            if tightened_stop != stop_price:
                stop_price = tightened_stop
                evaluation["trailing_active"] = True
                evaluation["action"] = "activate_trailing" if not trailing_active else "tighten_stop"
                evaluation["action_reason"] = "Projecao estendida ativou protecao agressiva por volatilidade."

    trailing_ready = close_rr >= ProductionConfig.TRAILING_TRIGGER_R
    if trailing_ready and atr_value > 0:
        trail_candidate = _build_trailing_candidate(
            close_price=close_price,
            atr_value=atr_value,
            side=side,
            multiplier=trailing_multiplier,
        )
        tightened_stop = _apply_stop_precedence(stop_price, trail_candidate, side)
        if tightened_stop != stop_price:
            stop_price = tightened_stop
            evaluation["trailing_active"] = True
            evaluation["action"] = "activate_trailing" if not trailing_active else "tighten_stop"
            evaluation["action_reason"] = "Trade evoluiu para 2R e ativou trailing por ATR."
            protection_level_value = "trailing"
            notes.append(f"trailing ATR ativo ({trailing_multiplier:.2f}x)")

    cross_ema_against = (close_price < ema_21) if side == "long" else (close_price > ema_21)
    weakening_closes = (
        close_price < previous_close if side == "long" else close_price > previous_close
    ) and prior_adverse_directional_close
    if progressed_rr >= ProductionConfig.STRUCTURE_EXIT_MIN_R and (
        (cross_ema_against and strong_opposite_candle) or (strong_opposite_candle and weakening_closes)
    ):
        evaluation["action"] = "exit_on_structure_failure"
        evaluation["action_reason"] = "Estrutura deteriorou apos o trade avancar."
        evaluation["structure_exit_flag"] = True
        protection_level_value = "structure_exit"
        notes.append("saida por falha estrutural")

    regime_shift_against = (
        side == "long" and regime == "trend_bear" and regime_score >= 7.0
    ) or (
        side == "short" and regime == "trend_bull" and regime_score >= 7.0
    )
    if progressed_rr >= 0.5 and regime_shift_against:
        evaluation["action"] = "exit_on_regime_shift"
        evaluation["action_reason"] = "Regime mudou fortemente contra a direcao do trade."
        evaluation["regime_exit_flag"] = True
        protection_level_value = "regime_exit"
        notes.append("saida por regime contrario forte")

    evaluation["stop_price"] = stop_price
    evaluation["take_price"] = take_price
    evaluation["protection_level"] = protection_level_value
    if evaluation["action_reason"] is None:
        evaluation["action_reason"] = "Posicao mantida com gestao normal."
    evaluation["notes"] = list(dict.fromkeys(str(note) for note in notes if note))
    return evaluation
