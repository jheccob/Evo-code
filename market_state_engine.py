from __future__ import annotations

from typing import Dict, Iterable, Optional


EVO_LONG_SETUP = "ema_rsi_resume_long"
EVO_SHORT_SETUP = "ema_rsi_resume_short"
EVO_LONG_STATE = "ema_rsi_resume_bull"
EVO_SHORT_STATE = "ema_rsi_resume_bear"

ACTIVE_SETUPS = (EVO_LONG_SETUP, EVO_SHORT_SETUP)
ACTIVE_MARKET_STATES = (EVO_LONG_STATE, EVO_SHORT_STATE)

LEGACY_GENERIC_SETUPS = {
    "pullback_trend",
    "continuation_breakout",
    "reversal_controlled",
}
LEGACY_GENERIC_MARKET_STATES = {
    "trend_pullback",
    "trend_continuation",
    "breakout_expansion",
    "range_rotation",
    "reversal_transition",
    "directional_probe",
}

MARKET_STATE_TO_SETUP = {
    EVO_LONG_STATE: EVO_LONG_SETUP,
    EVO_SHORT_STATE: EVO_SHORT_SETUP,
}
SETUP_TO_MARKET_STATES = {
    EVO_LONG_SETUP: [EVO_LONG_STATE],
    EVO_SHORT_SETUP: [EVO_SHORT_STATE],
}
TRADEABLE_MARKET_STATES = set(ACTIVE_MARKET_STATES)


def _normalize_text(value: Optional[object]) -> str:
    return str(value or "").strip().lower()


def normalize_setup_selection(value: Optional[object]) -> list[str]:
    normalized = _normalize_text(value)
    if not normalized:
        return []
    if normalized in SETUP_TO_MARKET_STATES:
        return [normalized]
    mapped_setup = MARKET_STATE_TO_SETUP.get(normalized)
    if mapped_setup:
        return [mapped_setup]
    if normalized in LEGACY_GENERIC_SETUPS or normalized in LEGACY_GENERIC_MARKET_STATES:
        return list(ACTIVE_SETUPS)
    return []


def normalize_setup_collection(values: Optional[Iterable[object]]) -> list[str]:
    normalized: list[str] = []
    for value in values or []:
        for setup_name in normalize_setup_selection(value):
            if setup_name not in normalized:
                normalized.append(setup_name)
    return normalized


def market_states_to_setup_allowlist(market_states: Optional[Iterable[object]]) -> list[str]:
    normalized: list[str] = []
    for market_state in market_states or []:
        normalized_state = _normalize_text(market_state)
        mapped_setup = MARKET_STATE_TO_SETUP.get(normalized_state)
        if mapped_setup and mapped_setup not in normalized:
            normalized.append(mapped_setup)
            continue
        for setup_name in normalize_setup_selection(normalized_state):
            if setup_name not in normalized:
                normalized.append(setup_name)
    return normalized


def setup_types_to_market_state_allowlist(setup_types: Optional[Iterable[object]]) -> list[str]:
    normalized: list[str] = []
    for setup_type in normalize_setup_collection(setup_types):
        for market_state in SETUP_TO_MARKET_STATES.get(setup_type, []):
            if market_state not in normalized:
                normalized.append(market_state)
    return normalized


class MarketStateEngine:
    @staticmethod
    def _build_blocked_state(reason: str, context_result: Optional[Dict[str, object]]) -> Dict[str, object]:
        market_bias = str((context_result or {}).get("market_bias") or (context_result or {}).get("bias") or "neutral")
        return {
            "market_bias": market_bias if market_bias in {"bullish", "bearish"} else "neutral",
            "market_state": "blocked",
            "execution_mode": "standby",
            "action": "wait",
            "confidence": 0.0,
            "is_tradeable": False,
            "location": None,
            "regime": None,
            "volatility_state": None,
            "structure_state": None,
            "scenario_score": 0.0,
            "minimum_scenario_score": 0.0,
            "objective_passed": False,
            "objective_quality": "bad",
            "rr_estimate": 0.0,
            "legacy_setup_type": None,
            "reason": reason,
            "block_reason": reason,
            "notes": [reason],
            "blockers": [reason],
        }

    def evaluate(
        self,
        context_result: Optional[Dict[str, object]],
        regime_result: Optional[Dict[str, object]],
        structure_result: Optional[Dict[str, object]],
        confirmation_result: Optional[Dict[str, object]],
        entry_result: Optional[Dict[str, object]],
        scenario_score_result: Optional[Dict[str, object]],
        hard_block_result: Optional[Dict[str, object]] = None,
        risk_result: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        if hard_block_result and hard_block_result.get("hard_block"):
            reason = str(hard_block_result.get("block_reason") or "Bloqueio duro do pipeline.")
            return self._build_blocked_state(reason, context_result)
        if risk_result and not risk_result.get("allowed", True):
            reason = str(risk_result.get("reason") or "Risco operacional bloqueado.")
            return self._build_blocked_state(reason, context_result)

        market_bias = str(
            (context_result or {}).get("market_bias")
            or (context_result or {}).get("bias")
            or (regime_result or {}).get("market_bias")
            or "neutral"
        ).strip().lower()
        normalized_setups = normalize_setup_selection((entry_result or {}).get("setup_type"))
        setup_type = normalized_setups[0] if normalized_setups else None
        rr_estimate = float((entry_result or {}).get("rr_estimate", 0.0) or 0.0)
        scenario_score = float((scenario_score_result or {}).get("scenario_score", 0.0) or 0.0)
        entry_score = float((entry_result or {}).get("entry_score", 0.0) or 0.0)
        confidence = round(max(entry_score, scenario_score, 0.0), 2)
        structure_state = (structure_result or {}).get("structure_state")
        volatility_state = (regime_result or {}).get("volatility_state")
        regime = (regime_result or {}).get("regime")
        price_location = (structure_result or {}).get("price_location")
        reason = str((entry_result or {}).get("entry_reason") or (entry_result or {}).get("rejection_reason") or "").strip()

        if setup_type == EVO_LONG_SETUP:
            return {
                "market_bias": "bullish",
                "market_state": EVO_LONG_STATE,
                "execution_mode": "ema_rsi_resume",
                "action": "buy",
                "confidence": confidence,
                "is_tradeable": True,
                "location": price_location,
                "regime": regime,
                "volatility_state": volatility_state,
                "structure_state": structure_state,
                "scenario_score": round(scenario_score, 2),
                "minimum_scenario_score": 6.0,
                "objective_passed": True,
                "objective_quality": str((entry_result or {}).get("entry_quality") or "acceptable"),
                "rr_estimate": round(rr_estimate, 2),
                "legacy_setup_type": EVO_LONG_SETUP,
                "reason": reason or "Motor EMA/RSI confirmou retomada compradora.",
                "block_reason": None,
                "notes": ["motor EMA/RSI comprador ativo"],
                "blockers": [],
            }

        if setup_type == EVO_SHORT_SETUP:
            return {
                "market_bias": "bearish",
                "market_state": EVO_SHORT_STATE,
                "execution_mode": "ema_rsi_resume",
                "action": "sell",
                "confidence": confidence,
                "is_tradeable": True,
                "location": price_location,
                "regime": regime,
                "volatility_state": volatility_state,
                "structure_state": structure_state,
                "scenario_score": round(scenario_score, 2),
                "minimum_scenario_score": 6.0,
                "objective_passed": True,
                "objective_quality": str((entry_result or {}).get("entry_quality") or "acceptable"),
                "rr_estimate": round(rr_estimate, 2),
                "legacy_setup_type": EVO_SHORT_SETUP,
                "reason": reason or "Motor EMA/RSI confirmou retomada vendedora.",
                "block_reason": None,
                "notes": ["motor EMA/RSI vendedor ativo"],
                "blockers": [],
            }

        neutral_reason = reason or "Motor EMA/RSI sem gatilho operacional neste candle."
        return {
            "market_bias": market_bias if market_bias in {"bullish", "bearish"} else "neutral",
            "market_state": "neutral_chop",
            "execution_mode": "standby",
            "action": "wait",
            "confidence": confidence,
            "is_tradeable": False,
            "location": price_location,
            "regime": regime,
            "volatility_state": volatility_state,
            "structure_state": structure_state,
            "scenario_score": round(scenario_score, 2),
            "minimum_scenario_score": 6.0,
            "objective_passed": False,
            "objective_quality": str((entry_result or {}).get("entry_quality") or "bad"),
            "rr_estimate": round(rr_estimate, 2),
            "legacy_setup_type": None,
            "reason": neutral_reason,
            "block_reason": neutral_reason,
            "notes": [neutral_reason],
            "blockers": [neutral_reason],
        }
