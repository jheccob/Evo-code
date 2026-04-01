from __future__ import annotations

from typing import Dict, Iterable, Optional

from market_state_engine import normalize_setup_collection
from trading_core.constants import ACTIONABLE_SIGNALS


def clear_hard_block(bot) -> None:
    bot._last_hard_block_evaluation = {
        "hard_block": False,
        "block_reason": None,
        "block_source": None,
        "notes": [],
    }


def finalize_signal_pipeline(bot, analytical_signal: str) -> Dict[str, object]:
    candidate_signal = str(getattr(bot, "_last_candidate_signal", "NEUTRO") or "NEUTRO")
    approved_signal = analytical_signal if analytical_signal in ACTIONABLE_SIGNALS else None
    blocked_signal = candidate_signal if candidate_signal in ACTIONABLE_SIGNALS and approved_signal is None else None

    hard_block = getattr(bot, "_last_hard_block_evaluation", None) or {}
    trade_decision = getattr(bot, "_last_trade_decision", None) or {}
    block_reason = trade_decision.get("block_reason") or hard_block.get("block_reason")
    block_source = hard_block.get("block_source")

    pipeline = {
        "candidate_signal": candidate_signal,
        "approved_signal": approved_signal,
        "blocked_signal": blocked_signal,
        "analytical_signal": analytical_signal,
        "block_reason": block_reason,
        "block_source": block_source,
        "context_evaluation": getattr(bot, "_last_context_evaluation", None),
        "regime_evaluation": getattr(bot, "_last_regime_evaluation", None),
        "structure_evaluation": getattr(bot, "_last_price_structure_evaluation", None),
        "confirmation_evaluation": getattr(bot, "_last_confirmation_evaluation", None),
        "entry_quality_evaluation": getattr(bot, "_last_entry_quality_evaluation", None),
        "scenario_evaluation": getattr(bot, "_last_scenario_evaluation", None),
        "market_state_evaluation": getattr(bot, "_last_market_state_evaluation", None),
        "trade_decision": getattr(bot, "_last_trade_decision", None),
        "hard_block_evaluation": getattr(bot, "_last_hard_block_evaluation", None),
    }
    bot._last_signal_pipeline = pipeline
    return pipeline


def set_hard_block(
    bot,
    block_reason: str,
    block_source: str = "signal_engine",
) -> str:
    cleaned_reason = str(block_reason or "").strip()
    bot._last_hard_block_evaluation = {
        "hard_block": True,
        "block_reason": cleaned_reason,
        "block_source": block_source,
        "notes": [cleaned_reason] if cleaned_reason else [],
    }
    bot._last_trade_decision = {
        "action": "wait",
        "confidence": 0.0,
        "market_bias": "neutral",
        "setup_type": None,
        "entry_reason": None,
        "block_reason": cleaned_reason or None,
        "invalid_if": None,
    }
    bot._last_market_state_evaluation = {
        "market_bias": "neutral",
        "market_state": "blocked",
        "execution_mode": "standby",
        "action": "wait",
        "confidence": 0.0,
        "is_tradeable": False,
        "block_reason": cleaned_reason or None,
        "reason": cleaned_reason or "Leitura interrompida por bloqueio duro.",
        "legacy_setup_type": None,
    }
    finalize_signal_pipeline(bot, "NEUTRO")
    return "NEUTRO"


def normalize_setup_allowlist(
    allowed_execution_setups: Optional[Iterable[str]],
) -> Optional[set[str]]:
    if allowed_execution_setups is None:
        return None
    normalized = set(normalize_setup_collection(allowed_execution_setups))
    return normalized or None


def apply_runtime_setup_execution_policy(
    bot,
    analytical_signal: str,
    allowed_execution_setups: Optional[Iterable[str]] = None,
) -> str:
    normalized_allowlist = normalize_setup_allowlist(allowed_execution_setups)
    if not normalized_allowlist:
        return analytical_signal
    if analytical_signal not in ACTIONABLE_SIGNALS:
        return analytical_signal

    entry_evaluation = getattr(bot, "_last_entry_quality_evaluation", None) or {}
    trade_decision = getattr(bot, "_last_trade_decision", None) or {}
    setup_type = str(
        entry_evaluation.get("setup_type")
        or trade_decision.get("setup_type")
        or ""
    ).strip().lower()
    if not setup_type or setup_type in normalized_allowlist:
        return analytical_signal

    allowed_label = ", ".join(sorted(normalized_allowlist))
    block_reason = (
        f"Setup {setup_type} bloqueado pela policy de runtime "
        f"(permitidos: {allowed_label})."
    )
    bot._last_hard_block_evaluation = {
        "hard_block": True,
        "block_reason": block_reason,
        "block_source": "setup_execution_policy",
        "notes": [block_reason],
    }
    updated_trade_decision = dict(trade_decision) if isinstance(trade_decision, dict) else {}
    updated_trade_decision.update(
        {
            "action": "wait",
            "entry_reason": None,
            "block_reason": block_reason,
            "setup_type": setup_type,
        }
    )
    bot._last_trade_decision = updated_trade_decision
    bot._last_market_state_evaluation = {
        "market_bias": updated_trade_decision.get("market_bias") or "neutral",
        "market_state": "blocked",
        "execution_mode": "standby",
        "action": "wait",
        "confidence": float(updated_trade_decision.get("confidence", 0.0) or 0.0),
        "is_tradeable": False,
        "block_reason": block_reason,
        "reason": block_reason,
        "legacy_setup_type": setup_type,
    }
    return "NEUTRO"


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
