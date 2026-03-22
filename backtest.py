from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Set, Tuple

import numpy as np
import pandas as pd
import requests

from config import AppConfig, ProductionConfig
from database.database import build_strategy_version, db as runtime_db
from position_management import evaluate_position_management
from services.risk_management_service import RiskManagementService
from trading_bot import TradingBot

logger = logging.getLogger(__name__)


LONG_SIGNALS = {"COMPRA", "COMPRA_FRACA"}
SHORT_SIGNALS = {"VENDA", "VENDA_FRACA"}
ACTIONABLE_SIGNALS = LONG_SIGNALS.union(SHORT_SIGNALS)


@dataclass
class Position:
    side: str
    signal: str
    setup_name: str
    strategy_version: Optional[str]
    context_timeframe: Optional[str]
    regime: Optional[str]
    regime_score: float
    trend_state: Optional[str]
    volatility_state: Optional[str]
    context_bias: Optional[str]
    structure_state: Optional[str]
    confirmation_state: Optional[str]
    signal_score: float
    atr: float
    entry_reason: str
    entry_quality: Optional[str]
    entry_score: float
    scenario_score: float
    rejection_reason: Optional[str]
    notes: List[str]
    sample_type: str
    risk_mode: str
    risk_amount: float
    size_reduced: bool
    risk_reason: Optional[str]
    entry_timestamp: pd.Timestamp
    entry_price: float
    quantity: float
    notional: float
    entry_fee: float
    stop_loss_price: Optional[float]
    take_profit_price: Optional[float]
    initial_stop_loss_price: Optional[float]
    initial_take_profit_price: Optional[float]
    break_even_active: bool = False
    trailing_active: bool = False
    protection_level: str = "normal"
    regime_exit_flag: bool = False
    structure_exit_flag: bool = False
    post_pump_protection: bool = False
    mfe_pct: float = 0.0
    mae_pct: float = 0.0
    max_unrealized_rr: float = 0.0
    age_candles: int = 0


class BacktestEngine:
    def __init__(self, trading_bot: Optional[TradingBot] = None, database=None):
        self.trading_bot = trading_bot or TradingBot(allow_simulated_data=False)
        self.database = database or runtime_db
        self.risk_management_service = RiskManagementService(database=self.database)
        self._trade_history: List[Dict] = []
        self._portfolio_history: List[Dict] = []
        self._signal_audit_log: List[Dict] = []

    def _build_empty_signal_pipeline_stats(self) -> Dict[str, object]:
        return {
            "candidate_count": 0,
            "approved_count": 0,
            "blocked_count": 0,
            "approval_rate_pct": 0.0,
            "block_reason_counts": {},
            "regime_counts": {},
            "structure_state_counts": {},
            "confirmation_state_counts": {},
            "entry_quality_counts": {},
            "setup_type_counts": {},
            "setup_type_approved_counts": {},
            "setup_type_blocked_counts": {},
        }

    def _build_empty_risk_engine_stats(self) -> Dict[str, object]:
        return {
            "risk_blocked_count": 0,
            "reduced_size_count": 0,
            "risk_block_reason_counts": {},
            "risk_mode_counts": {},
            "performance_by_risk_mode": {},
        }

    def _build_empty_signal_audit_stats(self) -> Dict[str, object]:
        return {
            "candidate_count": 0,
            "approved_count": 0,
            "blocked_count": 0,
            "approval_rate_pct": 0.0,
            "block_reason_counts": {},
            "approval_by_regime": {},
        }

    @staticmethod
    def _normalize_setup_allowlist(allowed_execution_setups: Optional[Iterable[str]]) -> Optional[Set[str]]:
        if allowed_execution_setups is None:
            return None
        normalized = {
            str(item or "").strip().lower()
            for item in allowed_execution_setups
            if str(item or "").strip()
        }
        return normalized or None

    def _apply_setup_execution_policy(
        self,
        signal_pipeline: Dict[str, object],
        allowed_execution_setups: Optional[Set[str]],
    ) -> Dict[str, object]:
        if not allowed_execution_setups:
            return signal_pipeline

        candidate_signal = str(signal_pipeline.get("candidate_signal") or "NEUTRO")
        if candidate_signal not in ACTIONABLE_SIGNALS:
            return signal_pipeline

        entry_evaluation = signal_pipeline.get("entry_quality_evaluation") or {}
        trade_decision = signal_pipeline.get("trade_decision") or {}
        setup_type = str(
            entry_evaluation.get("setup_type")
            or trade_decision.get("setup_type")
            or ""
        ).strip().lower()
        if not setup_type or setup_type in allowed_execution_setups:
            return signal_pipeline

        blocked_pipeline = dict(signal_pipeline)
        block_reason = (
            f"Setup {setup_type} em modo pesquisa; execucao bloqueada "
            "pela policy de setups permitidos."
        )
        blocked_pipeline["approved_signal"] = None
        blocked_pipeline["blocked_signal"] = candidate_signal
        blocked_pipeline["analytical_signal"] = "NEUTRO"
        blocked_pipeline["block_reason"] = block_reason
        blocked_pipeline["block_source"] = "setup_execution_policy"

        updated_trade_decision = dict(trade_decision) if isinstance(trade_decision, dict) else {}
        updated_trade_decision.update(
            {
                "action": "wait",
                "entry_reason": None,
                "block_reason": block_reason,
                "setup_type": setup_type,
            }
        )
        blocked_pipeline["trade_decision"] = updated_trade_decision

        updated_hard_block = dict(blocked_pipeline.get("hard_block_evaluation") or {})
        updated_hard_block.update(
            {
                "hard_block": True,
                "block_reason": block_reason,
                "block_source": "setup_execution_policy",
                "notes": [block_reason],
            }
        )
        blocked_pipeline["hard_block_evaluation"] = updated_hard_block
        return blocked_pipeline

    def _increment_count(self, counts: Dict[str, int], key: Optional[str]) -> None:
        normalized_key = str(key or "").strip()
        if not normalized_key:
            return
        counts[normalized_key] = counts.get(normalized_key, 0) + 1

    def _record_signal_pipeline_stats(self, stats: Dict[str, object], pipeline: Dict[str, object]) -> None:
        candidate_signal = str(pipeline.get("candidate_signal") or "NEUTRO")
        if candidate_signal not in ACTIONABLE_SIGNALS:
            return

        stats["candidate_count"] = int(stats.get("candidate_count", 0) or 0) + 1

        approved_signal = str(pipeline.get("approved_signal") or "")
        if approved_signal in ACTIONABLE_SIGNALS:
            stats["approved_count"] = int(stats.get("approved_count", 0) or 0) + 1

        blocked_signal = str(pipeline.get("blocked_signal") or "")
        if blocked_signal in ACTIONABLE_SIGNALS:
            stats["blocked_count"] = int(stats.get("blocked_count", 0) or 0) + 1
            self._increment_count(stats["block_reason_counts"], pipeline.get("block_reason"))

        structure_state = (pipeline.get("structure_evaluation") or {}).get("structure_state")
        regime = (pipeline.get("regime_evaluation") or {}).get("regime")
        confirmation_state = (pipeline.get("confirmation_evaluation") or {}).get("confirmation_state")
        entry_evaluation = pipeline.get("entry_quality_evaluation") or {}
        entry_quality = TradingBot._normalize_entry_quality_label(entry_evaluation.get("entry_quality"))
        setup_type = entry_evaluation.get("setup_type")

        self._increment_count(stats["regime_counts"], regime)
        self._increment_count(stats["structure_state_counts"], structure_state)
        self._increment_count(stats["confirmation_state_counts"], confirmation_state)
        self._increment_count(stats["entry_quality_counts"], entry_quality)
        self._increment_count(stats["setup_type_counts"], setup_type)
        if approved_signal in ACTIONABLE_SIGNALS:
            self._increment_count(stats["setup_type_approved_counts"], setup_type)
        if blocked_signal in ACTIONABLE_SIGNALS:
            self._increment_count(stats["setup_type_blocked_counts"], setup_type)

    def _finalize_signal_pipeline_stats(self, stats: Dict[str, object]) -> Dict[str, object]:
        finalized = dict(stats)
        candidate_count = int(finalized.get("candidate_count", 0) or 0)
        approved_count = int(finalized.get("approved_count", 0) or 0)
        finalized["approval_rate_pct"] = round((approved_count / candidate_count) * 100, 2) if candidate_count else 0.0
        setup_type_counts = finalized.get("setup_type_counts") or {}
        setup_type_approved_counts = finalized.get("setup_type_approved_counts") or {}
        setup_type_blocked_counts = finalized.get("setup_type_blocked_counts") or {}
        finalized["setup_type_approval_rates"] = {
            setup_type: round((int(setup_type_approved_counts.get(setup_type, 0) or 0) / count) * 100, 2)
            for setup_type, count in setup_type_counts.items()
            if int(count or 0) > 0
        }
        finalized["setup_type_block_rates"] = {
            setup_type: round((int(setup_type_blocked_counts.get(setup_type, 0) or 0) / count) * 100, 2)
            for setup_type, count in setup_type_counts.items()
            if int(count or 0) > 0
        }
        return finalized

    def _record_risk_block(self, stats: Dict[str, object], risk_plan: Optional[Dict[str, object]]) -> None:
        if not isinstance(risk_plan, dict) or risk_plan.get("allowed", True):
            return
        stats["risk_blocked_count"] = int(stats.get("risk_blocked_count", 0) or 0) + 1
        self._increment_count(stats["risk_block_reason_counts"], risk_plan.get("risk_reason") or risk_plan.get("reason"))

    def _record_risk_trade(self, stats: Dict[str, object], risk_plan: Optional[Dict[str, object]]) -> None:
        if not isinstance(risk_plan, dict):
            return
        risk_mode = str(risk_plan.get("risk_mode") or "normal")
        self._increment_count(stats["risk_mode_counts"], risk_mode)
        if bool(risk_plan.get("size_reduced", False)):
            stats["reduced_size_count"] = int(stats.get("reduced_size_count", 0) or 0) + 1

    def _finalize_risk_engine_stats(
        self,
        stats: Dict[str, object],
        trades: List[Dict[str, object]],
    ) -> Dict[str, object]:
        finalized = dict(stats)
        performance_by_mode: Dict[str, Dict[str, object]] = {}
        for trade in trades:
            risk_mode = str(trade.get("risk_mode") or "normal")
            bucket = performance_by_mode.setdefault(
                risk_mode,
                {"trades": 0, "net_profit": 0.0, "wins": 0, "losses": 0},
            )
            bucket["trades"] += 1
            bucket["net_profit"] += float(trade.get("profit_loss", 0.0) or 0.0)
            pnl_pct = float(trade.get("profit_loss_pct", 0.0) or 0.0)
            if pnl_pct > 0:
                bucket["wins"] += 1
            elif pnl_pct < 0:
                bucket["losses"] += 1

        for mode, bucket in performance_by_mode.items():
            trades_count = int(bucket["trades"] or 0)
            bucket["net_profit"] = round(float(bucket["net_profit"] or 0.0), 4)
            bucket["win_rate"] = round((int(bucket["wins"] or 0) / trades_count) * 100, 2) if trades_count else 0.0

        finalized["performance_by_risk_mode"] = performance_by_mode
        return finalized

    def _build_signal_audit_entry(
        self,
        symbol: str,
        timeframe: str,
        strategy_version: Optional[str],
        timestamp: pd.Timestamp,
        signal_pipeline: Dict[str, object],
        risk_plan: Optional[Dict[str, object]] = None,
    ) -> Optional[Dict[str, object]]:
        candidate_signal = str(signal_pipeline.get("candidate_signal") or "NEUTRO")
        if candidate_signal not in ACTIONABLE_SIGNALS:
            return None

        context_evaluation = signal_pipeline.get("context_evaluation") or {}
        regime_evaluation = signal_pipeline.get("regime_evaluation") or {}
        structure_evaluation = signal_pipeline.get("structure_evaluation") or {}
        confirmation_evaluation = signal_pipeline.get("confirmation_evaluation") or {}
        entry_evaluation = signal_pipeline.get("entry_quality_evaluation") or {}
        scenario_evaluation = signal_pipeline.get("scenario_evaluation") or {}

        approved_signal = signal_pipeline.get("approved_signal")
        blocked_signal = signal_pipeline.get("blocked_signal")
        block_reason = signal_pipeline.get("block_reason")
        risk_mode = "not_evaluated"
        if isinstance(risk_plan, dict):
            risk_mode = str(risk_plan.get("risk_mode") or "normal")
            if not risk_plan.get("allowed", True):
                approved_signal = None
                blocked_signal = approved_signal or candidate_signal
                block_reason = risk_plan.get("risk_reason") or risk_plan.get("reason")

        notes: List[str] = []
        for note in (regime_evaluation.get("notes") or [])[:1]:
            notes.append(str(note))
        for note in (structure_evaluation.get("notes") or [])[:1]:
            notes.append(str(note))
        for note in (confirmation_evaluation.get("notes") or [])[:1]:
            notes.append(str(note))
        for note in (entry_evaluation.get("notes") or [])[:1]:
            notes.append(str(note))
        if isinstance(risk_plan, dict):
            notes.extend([str(note) for note in (risk_plan.get("notes") or [])[:1]])

        return {
            "timestamp": pd.Timestamp(timestamp).isoformat(),
            "symbol": symbol,
            "timeframe": timeframe,
            "strategy_version": strategy_version,
            "candidate_signal": candidate_signal,
            "approved_signal": approved_signal if approved_signal in ACTIONABLE_SIGNALS else None,
            "blocked_signal": blocked_signal if blocked_signal in ACTIONABLE_SIGNALS else None,
            "block_reason": block_reason,
            "regime": regime_evaluation.get("regime"),
            "regime_score": float(regime_evaluation.get("regime_score", 0.0) or 0.0),
            "trend_state": regime_evaluation.get("trend_state"),
            "volatility_state": regime_evaluation.get("volatility_state"),
            "context_bias": context_evaluation.get("market_bias"),
            "structure_state": structure_evaluation.get("structure_state"),
            "confirmation_state": confirmation_evaluation.get("confirmation_state"),
            "entry_quality": entry_evaluation.get("entry_quality"),
            "entry_score": float(entry_evaluation.get("entry_score", 0.0) or 0.0),
            "scenario_score": float(scenario_evaluation.get("scenario_score", 0.0) or 0.0),
            "setup_type": entry_evaluation.get("setup_type"),
            "risk_mode": risk_mode,
            "notes": notes,
        }

    def _build_signal_audit_summary(self, signal_audit_log: List[Dict[str, object]]) -> Dict[str, object]:
        stats = self._build_empty_signal_audit_stats()
        if not signal_audit_log:
            return stats

        approval_by_regime: Dict[str, Dict[str, int]] = {}
        for row in signal_audit_log:
            candidate_signal = str(row.get("candidate_signal") or "NEUTRO")
            if candidate_signal not in ACTIONABLE_SIGNALS:
                continue
            stats["candidate_count"] = int(stats.get("candidate_count", 0) or 0) + 1
            approved = str(row.get("approved_signal") or "") in ACTIONABLE_SIGNALS
            blocked = str(row.get("blocked_signal") or "") in ACTIONABLE_SIGNALS
            if approved:
                stats["approved_count"] = int(stats.get("approved_count", 0) or 0) + 1
            if blocked:
                stats["blocked_count"] = int(stats.get("blocked_count", 0) or 0) + 1
                self._increment_count(stats["block_reason_counts"], row.get("block_reason"))

            regime = str(row.get("regime") or "unknown")
            regime_bucket = approval_by_regime.setdefault(regime, {"candidate_count": 0, "approved_count": 0})
            regime_bucket["candidate_count"] += 1
            if approved:
                regime_bucket["approved_count"] += 1

        candidate_count = int(stats.get("candidate_count", 0) or 0)
        approved_count = int(stats.get("approved_count", 0) or 0)
        stats["approval_rate_pct"] = round((approved_count / candidate_count) * 100, 2) if candidate_count else 0.0
        stats["approval_by_regime"] = {
            regime: {
                **bucket,
                "approval_rate_pct": round((bucket["approved_count"] / bucket["candidate_count"]) * 100, 2)
                if bucket["candidate_count"]
                else 0.0,
            }
            for regime, bucket in approval_by_regime.items()
        }
        return stats

    def _normalize_signal_pipeline(self, pipeline: Optional[Dict[str, object]], fallback_signal: str = "NEUTRO") -> Dict[str, object]:
        raw_pipeline = pipeline if isinstance(pipeline, dict) else {}
        analytical_signal = str(
            raw_pipeline.get("analytical_signal")
            or raw_pipeline.get("signal")
            or fallback_signal
            or "NEUTRO"
        )
        approved_signal = raw_pipeline.get("approved_signal")
        blocked_signal = raw_pipeline.get("blocked_signal")
        candidate_signal = raw_pipeline.get("candidate_signal")
        synthetic_pipeline = not raw_pipeline and analytical_signal in ACTIONABLE_SIGNALS

        if candidate_signal not in ACTIONABLE_SIGNALS:
            if approved_signal in ACTIONABLE_SIGNALS:
                candidate_signal = approved_signal
            elif blocked_signal in ACTIONABLE_SIGNALS:
                candidate_signal = blocked_signal
            elif analytical_signal in ACTIONABLE_SIGNALS:
                candidate_signal = analytical_signal
            else:
                candidate_signal = "NEUTRO"

        if synthetic_pipeline:
            approved_signal = analytical_signal
            blocked_signal = None

        return {
            "candidate_signal": candidate_signal,
            "approved_signal": approved_signal if approved_signal in ACTIONABLE_SIGNALS else None,
            "blocked_signal": blocked_signal if blocked_signal in ACTIONABLE_SIGNALS else None,
            "analytical_signal": analytical_signal,
            "block_reason": raw_pipeline.get("block_reason"),
            "block_source": raw_pipeline.get("block_source"),
            "context_evaluation": raw_pipeline.get("context_evaluation"),
            "regime_evaluation": raw_pipeline.get("regime_evaluation"),
            "structure_evaluation": raw_pipeline.get("structure_evaluation"),
            "confirmation_evaluation": raw_pipeline.get("confirmation_evaluation"),
            "entry_quality_evaluation": raw_pipeline.get("entry_quality_evaluation"),
            "scenario_evaluation": raw_pipeline.get("scenario_evaluation"),
            "trade_decision": raw_pipeline.get("trade_decision"),
            "hard_block_evaluation": raw_pipeline.get("hard_block_evaluation"),
        }

    def run_backtest(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        initial_balance: int = 10_000,
        rsi_period: int = 14,
        rsi_min: int = 20,
        rsi_max: int = 80,
        stop_loss_pct: float = 0.0,
        take_profit_pct: float = 0.0,
        fee_rate: float = 0.001,
        slippage: float = 0.0005,
        position_size_pct: float = 1.0,
        require_volume: bool = False,
        require_trend: bool = False,
        avoid_ranging: bool = False,
        context_timeframe: Optional[str] = None,
        validation_split_pct: float = 0.0,
        walk_forward_windows: int = 0,
        persist_result: bool = True,
        allowed_execution_setups: Optional[Iterable[str]] = None,
    ) -> Dict:
        if start_date >= end_date:
            raise ValueError("Data inicial deve ser anterior a data final")

        self._trade_history = []
        self._portfolio_history = []
        self._signal_audit_log = []

        normalized_stop_loss = self._normalize_strategy_pct(stop_loss_pct)
        normalized_take_profit = self._normalize_strategy_pct(take_profit_pct)
        normalized_position_size = min(max(self._normalize_position_size(position_size_pct), 0.0), 1.0)
        normalized_validation_split = min(max(self._normalize_ratio(validation_split_pct), 0.0), 0.5)
        normalized_walk_forward_windows = max(int(walk_forward_windows or 0), 0)
        resolved_context_timeframe = context_timeframe or AppConfig.get_context_timeframe(timeframe)
        strategy_version = build_strategy_version(
            symbol=symbol,
            timeframe=timeframe,
            context_timeframe=resolved_context_timeframe,
            rsi_period=rsi_period,
            rsi_min=rsi_min,
            rsi_max=rsi_max,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            require_volume=require_volume,
            require_trend=require_trend,
            avoid_ranging=avoid_ranging,
        )

        self.trading_bot.update_config(
            symbol=symbol,
            timeframe=timeframe,
            rsi_period=rsi_period,
            rsi_min=rsi_min,
            rsi_max=rsi_max,
        )

        warmup_candles = max(210, rsi_period + 5)
        lookback_start = pd.Timestamp(start_date) - pd.to_timedelta(
            self._timeframe_to_milliseconds(timeframe) * warmup_candles,
            unit="ms",
        )

        raw_df = self._fetch_historical_ohlcv(symbol, timeframe, lookback_start.to_pydatetime(), end_date)
        if raw_df.empty:
            raise ValueError("Dados insuficientes para backtest")
        raw_context_df = None
        if resolved_context_timeframe:
            context_lookback_start = pd.Timestamp(start_date) - pd.to_timedelta(
                self._timeframe_to_milliseconds(resolved_context_timeframe) * warmup_candles,
                unit="ms",
            )
            raw_context_df = self._fetch_historical_ohlcv(
                symbol,
                resolved_context_timeframe,
                context_lookback_start.to_pydatetime(),
                end_date,
            )

        return self._run_backtest_with_preloaded_df(
            df=raw_df,
            context_df=raw_context_df,
            symbol=symbol,
            timeframe=timeframe,
            context_timeframe=resolved_context_timeframe,
            start_date=start_date,
            end_date=end_date,
            initial_balance=float(initial_balance),
            rsi_period=rsi_period,
            rsi_min=rsi_min,
            rsi_max=rsi_max,
            strategy_version=strategy_version,
            raw_stop_loss_pct=stop_loss_pct,
            raw_take_profit_pct=take_profit_pct,
            stop_loss_pct=normalized_stop_loss,
            take_profit_pct=normalized_take_profit,
            fee_rate=fee_rate,
            slippage=slippage,
            position_size_pct=normalized_position_size,
            require_volume=require_volume,
            require_trend=require_trend,
            avoid_ranging=avoid_ranging,
            validation_split_pct=normalized_validation_split,
            walk_forward_windows=normalized_walk_forward_windows,
            persist_result=persist_result,
            allowed_execution_setups=self._normalize_setup_allowlist(allowed_execution_setups),
        )

    def run_backtest_from_dataframe(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        initial_balance: int = 10_000,
        rsi_period: int = 14,
        rsi_min: int = 20,
        rsi_max: int = 80,
        stop_loss_pct: float = 0.0,
        take_profit_pct: float = 0.0,
        fee_rate: float = 0.001,
        slippage: float = 0.0005,
        position_size_pct: float = 1.0,
        require_volume: bool = False,
        require_trend: bool = False,
        avoid_ranging: bool = False,
        context_df: Optional[pd.DataFrame] = None,
        context_timeframe: Optional[str] = None,
        validation_split_pct: float = 0.0,
        walk_forward_windows: int = 0,
        persist_result: bool = False,
        allowed_execution_setups: Optional[Iterable[str]] = None,
    ) -> Dict:
        if df is None or df.empty:
            raise ValueError("DataFrame historico vazio para backtest")

        if not isinstance(df.index, pd.DatetimeIndex):
            if "timestamp" not in df.columns:
                raise ValueError("DataFrame historico precisa de DatetimeIndex ou coluna timestamp")
            df = df.copy()
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df.set_index("timestamp", inplace=True)

        normalized_stop_loss = self._normalize_strategy_pct(stop_loss_pct)
        normalized_take_profit = self._normalize_strategy_pct(take_profit_pct)
        normalized_position_size = min(max(self._normalize_position_size(position_size_pct), 0.0), 1.0)
        normalized_validation_split = min(max(self._normalize_ratio(validation_split_pct), 0.0), 0.5)
        normalized_walk_forward_windows = max(int(walk_forward_windows or 0), 0)
        resolved_context_timeframe = context_timeframe or AppConfig.get_context_timeframe(timeframe)
        strategy_version = build_strategy_version(
            symbol=symbol,
            timeframe=timeframe,
            context_timeframe=resolved_context_timeframe,
            rsi_period=rsi_period,
            rsi_min=rsi_min,
            rsi_max=rsi_max,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            require_volume=require_volume,
            require_trend=require_trend,
            avoid_ranging=avoid_ranging,
        )

        self.trading_bot.update_config(
            symbol=symbol,
            timeframe=timeframe,
            rsi_period=rsi_period,
            rsi_min=rsi_min,
            rsi_max=rsi_max,
        )

        resolved_start_date = start_date or pd.Timestamp(df.index.min()).to_pydatetime()
        resolved_end_date = end_date or pd.Timestamp(df.index.max()).to_pydatetime()

        return self._run_backtest_with_preloaded_df(
            df=df.copy(),
            context_df=None if context_df is None else context_df.copy(),
            symbol=symbol,
            timeframe=timeframe,
            context_timeframe=resolved_context_timeframe,
            start_date=resolved_start_date,
            end_date=resolved_end_date,
            initial_balance=float(initial_balance),
            rsi_period=rsi_period,
            rsi_min=rsi_min,
            rsi_max=rsi_max,
            strategy_version=strategy_version,
            raw_stop_loss_pct=stop_loss_pct,
            raw_take_profit_pct=take_profit_pct,
            stop_loss_pct=normalized_stop_loss,
            take_profit_pct=normalized_take_profit,
            fee_rate=fee_rate,
            slippage=slippage,
            position_size_pct=normalized_position_size,
            require_volume=require_volume,
            require_trend=require_trend,
            avoid_ranging=avoid_ranging,
            validation_split_pct=normalized_validation_split,
            walk_forward_windows=normalized_walk_forward_windows,
            persist_result=persist_result,
            allowed_execution_setups=self._normalize_setup_allowlist(allowed_execution_setups),
        )

    def run_market_scan(
        self,
        symbols: List[str],
        timeframes: List[str],
        **backtest_kwargs,
    ) -> Dict:
        unique_symbols = list(dict.fromkeys(symbol for symbol in symbols if symbol))
        unique_timeframes = list(dict.fromkeys(timeframe for timeframe in timeframes if timeframe))

        if not unique_symbols:
            raise ValueError("Selecione ao menos um simbolo para o scan")
        if not unique_timeframes:
            raise ValueError("Selecione ao menos um timeframe para o scan")

        rows: List[Dict] = []
        failed_runs: List[Dict] = []
        best_result: Optional[Dict] = None

        for symbol in unique_symbols:
            for timeframe in unique_timeframes:
                try:
                    result = self.run_backtest(symbol=symbol, timeframe=timeframe, **backtest_kwargs)
                    row = self._build_market_scan_row(result)
                    rows.append(row)

                    if best_result is None or self._market_scan_sort_key(row) > self._market_scan_sort_key(best_result["row"]):
                        best_result = {"row": row, "result": result}
                except Exception as exc:
                    failed_runs.append(
                        {
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "error": str(exc),
                        }
                    )

        rows.sort(key=self._market_scan_sort_key, reverse=True)

        return {
            "rows": rows,
            "best": best_result["row"] if best_result else None,
            "best_result": best_result["result"] if best_result else None,
            "failed_runs": failed_runs,
            "summary": {
                "requested_runs": len(unique_symbols) * len(unique_timeframes),
                "completed_runs": len(rows),
                "failed_runs": len(failed_runs),
                "oos_passed_runs": sum(1 for row in rows if row["oos_passed"]),
                "walk_forward_passed_runs": sum(1 for row in rows if row["walk_forward_passed"]),
                "profitable_runs": sum(1 for row in rows if row["total_return_pct"] > 0),
                "best_quality_score": rows[0]["quality_score"] if rows else 0.0,
            },
        }

    def optimize_rsi_parameters(
        self,
        symbol: str,
        timeframe: str,
        rsi_min_range: Tuple[int, int],
        rsi_max_range: Tuple[int, int],
        max_tests: int,
        optimization_metric: str,
        **backtest_kwargs,
    ) -> Dict:
        parameter_candidates = self._build_rsi_parameter_candidates(
            rsi_min_range=rsi_min_range,
            rsi_max_range=rsi_max_range,
            max_tests=max_tests,
        )
        if not parameter_candidates:
            raise ValueError("Nao foi possivel gerar combinacoes validas de RSI")

        rows: List[Dict] = []
        failed_runs: List[Dict] = []
        best_result: Optional[Dict] = None

        for rsi_min, rsi_max in parameter_candidates:
            try:
                result = self.run_backtest(
                    symbol=symbol,
                    timeframe=timeframe,
                    rsi_min=rsi_min,
                    rsi_max=rsi_max,
                    **backtest_kwargs,
                )
                row = self._build_optimization_row(
                    result=result,
                    optimization_metric=optimization_metric,
                    metric_value=self._extract_optimization_metric(result, optimization_metric),
                )
                rows.append(row)

                if best_result is None or self._optimization_sort_key(row) > self._optimization_sort_key(best_result["row"]):
                    best_result = {"row": row, "result": result}
            except Exception as exc:
                failed_runs.append(
                    {
                        "rsi_min": rsi_min,
                        "rsi_max": rsi_max,
                        "error": str(exc),
                    }
                )

        rows.sort(key=self._optimization_sort_key, reverse=True)

        return {
            "rows": rows,
            "best": best_result["row"] if best_result else None,
            "best_result": best_result["result"] if best_result else None,
            "failed_runs": failed_runs,
            "summary": {
                "requested_tests": len(parameter_candidates),
                "completed_tests": len(rows),
                "failed_tests": len(failed_runs),
                "passed_candidates": sum(1 for row in rows if row["robust_candidate"]),
                "best_quality_score": rows[0]["quality_score"] if rows else 0.0,
                "optimization_metric": optimization_metric,
            },
        }

    def get_trade_summary_df(self) -> pd.DataFrame:
        if not self._trade_history:
            return pd.DataFrame(
                columns=["timestamp", "entry_price", "price", "profit_loss_pct", "profit_loss", "signal"]
            )

        summary = pd.DataFrame(self._trade_history)
        summary = summary[["timestamp", "entry_price", "price", "profit_loss_pct", "profit_loss", "signal"]]
        summary["timestamp"] = pd.to_datetime(summary["timestamp"])
        return summary

    def _run_backtest_with_preloaded_df(
        self,
        df: pd.DataFrame,
        context_df: Optional[pd.DataFrame],
        symbol: str,
        timeframe: str,
        context_timeframe: Optional[str],
        start_date: datetime,
        end_date: datetime,
        initial_balance: float,
        rsi_period: int,
        rsi_min: int,
        rsi_max: int,
        strategy_version: str,
        raw_stop_loss_pct: float,
        raw_take_profit_pct: float,
        stop_loss_pct: float,
        take_profit_pct: float,
        fee_rate: float,
        slippage: float,
        position_size_pct: float,
        require_volume: bool,
        require_trend: bool,
        avoid_ranging: bool,
        validation_split_pct: float,
        walk_forward_windows: int,
        persist_result: bool,
        allowed_execution_setups: Optional[Set[str]],
    ) -> Dict:
        df = self.trading_bot.calculate_indicators(df.copy())
        resolved_context_df = None
        if context_df is not None and not context_df.empty:
            resolved_context_df = self.trading_bot.calculate_indicators(context_df.copy())
        warmup_candles = max(210, int(rsi_period) + 5)
        if len(df) <= warmup_candles + 1:
            raise ValueError("Dados insuficientes para backtest")

        benchmark_history = self._build_benchmark_history(
            df=df,
            start_date=start_date,
            end_date=end_date,
            initial_balance=float(initial_balance),
            warmup_candles=warmup_candles,
        )

        self._trade_history, self._portfolio_history, final_balance, signal_pipeline_stats, risk_engine_stats, self._signal_audit_log = self._run_simulation(
            symbol=symbol,
            df=df,
            context_df=resolved_context_df,
            timeframe=timeframe,
            context_timeframe=context_timeframe,
            start_date=start_date,
            end_date=end_date,
            initial_balance=float(initial_balance),
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            fee_rate=fee_rate,
            slippage=slippage,
            position_size_pct=position_size_pct,
            require_volume=require_volume,
            require_trend=require_trend,
            avoid_ranging=avoid_ranging,
            strategy_version=strategy_version,
            setup_name=strategy_version,
            sample_type="backtest",
            allowed_execution_setups=allowed_execution_setups,
        )

        stats = self._build_stats(
            initial_balance=float(initial_balance),
            final_balance=float(final_balance),
            timeframe=timeframe,
            trade_history=self._trade_history,
            portfolio_history=self._portfolio_history,
        )
        results = {
            "meta": {
                "symbol": symbol,
                "timeframe": timeframe,
                "context_timeframe": context_timeframe,
                "strategy_version": strategy_version,
                "start_date": pd.Timestamp(start_date).isoformat(),
                "end_date": pd.Timestamp(end_date).isoformat(),
                "rsi_period": rsi_period,
                "rsi_min": rsi_min,
                "rsi_max": rsi_max,
            },
            "stats": stats,
            "trades": list(self._trade_history),
            "trade_autopsy": list(self._trade_history),
            "portfolio_values": list(self._portfolio_history),
            "benchmark_values": benchmark_history,
            "regime_summary": stats.get("regime_breakdown", []),
            "setup_type_summary": stats.get("setup_type_breakdown", []),
            "exit_type_summary": stats.get("exit_type_breakdown", []),
            "entry_quality_summary": stats.get("entry_quality_breakdown", []),
            "risk_mode_summary": stats.get("risk_mode_breakdown", []),
            "time_analytics": {
                "hour_of_day_breakdown": stats.get("hour_of_day_breakdown", []),
                "day_of_week_breakdown": stats.get("day_of_week_breakdown", []),
                "holding_time_breakdown": stats.get("holding_time_breakdown", []),
            },
            "equity_diagnostics": stats.get("equity_diagnostics", {}),
            "position_management_summary": {
                "break_even_activated_count": stats.get("break_even_activated_count", 0),
                "trailing_activated_count": stats.get("trailing_activated_count", 0),
                "post_pump_protection_count": stats.get("post_pump_protection_count", 0),
                "structure_exit_count": stats.get("structure_exit_count", 0),
                "regime_exit_count": stats.get("regime_exit_count", 0),
                "avg_mfe_pct": stats.get("avg_mfe_pct", 0.0),
                "avg_mae_pct": stats.get("avg_mae_pct", 0.0),
            },
            "signal_pipeline_stats": signal_pipeline_stats,
            "risk_engine_summary": risk_engine_stats,
            "signal_audit_summary": self._build_signal_audit_summary(self._signal_audit_log),
            "signal_audit": list(self._signal_audit_log),
        }
        results.update(signal_pipeline_stats)
        results.update(
            {
                "risk_blocked_count": int(risk_engine_stats.get("risk_blocked_count", 0) or 0),
                "reduced_size_count": int(risk_engine_stats.get("reduced_size_count", 0) or 0),
            }
        )
        validation = self._build_validation_results(
            symbol=symbol,
            df=df,
            context_df=resolved_context_df,
            timeframe=timeframe,
            context_timeframe=context_timeframe,
            start_date=start_date,
            end_date=end_date,
            initial_balance=float(initial_balance),
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            fee_rate=fee_rate,
            slippage=slippage,
            position_size_pct=position_size_pct,
            require_volume=require_volume,
            require_trend=require_trend,
            avoid_ranging=avoid_ranging,
            validation_split_pct=validation_split_pct,
            allowed_execution_setups=allowed_execution_setups,
        )
        if validation is not None:
            results["validation"] = validation
        walk_forward = self._build_walk_forward_results(
            symbol=symbol,
            df=df,
            context_df=resolved_context_df,
            timeframe=timeframe,
            context_timeframe=context_timeframe,
            start_date=start_date,
            end_date=end_date,
            initial_balance=float(initial_balance),
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            fee_rate=fee_rate,
            slippage=slippage,
            position_size_pct=position_size_pct,
            require_volume=require_volume,
            require_trend=require_trend,
            avoid_ranging=avoid_ranging,
            walk_forward_windows=walk_forward_windows,
            allowed_execution_setups=allowed_execution_setups,
        )
        if walk_forward is not None:
            results["walk_forward"] = walk_forward

        objective_check = self._build_objective_setup_check(
            stats=stats,
            validation=validation,
            walk_forward=walk_forward,
            signal_pipeline_stats=signal_pipeline_stats,
            risk_engine_summary=risk_engine_stats,
            setup_type_summary=results.get("setup_type_summary") or [],
        )
        results["objective_check"] = objective_check

        if persist_result:
            results["saved_run_id"] = self._persist_backtest_run(
                symbol=symbol,
                timeframe=timeframe,
                context_timeframe=context_timeframe,
                start_date=start_date,
                end_date=end_date,
                stats=stats,
                rsi_period=rsi_period,
                rsi_min=rsi_min,
                rsi_max=rsi_max,
                strategy_version=strategy_version,
                stop_loss_pct=raw_stop_loss_pct,
                take_profit_pct=raw_take_profit_pct,
                fee_rate=fee_rate,
                slippage=slippage,
                position_size_pct=position_size_pct,
                require_volume=require_volume,
                require_trend=require_trend,
                avoid_ranging=avoid_ranging,
                validation=validation,
                walk_forward=walk_forward,
            )
        return results

    def _build_rsi_parameter_candidates(
        self,
        rsi_min_range: Tuple[int, int],
        rsi_max_range: Tuple[int, int],
        max_tests: int,
    ) -> List[Tuple[int, int]]:
        min_start, min_end = sorted(int(value) for value in rsi_min_range)
        max_start, max_end = sorted(int(value) for value in rsi_max_range)
        max_tests = max(int(max_tests or 0), 1)

        min_points = max(2, min(6, int(np.ceil(np.sqrt(max_tests)))))
        max_points = max(2, min(6, int(np.ceil(max_tests / min_points))))

        min_values = sorted({int(round(value)) for value in np.linspace(min_start, min_end, num=min_points)})
        max_values = sorted({int(round(value)) for value in np.linspace(max_start, max_end, num=max_points)})

        candidates = [
            (rsi_min, rsi_max)
            for rsi_min in min_values
            for rsi_max in max_values
            if rsi_min + 10 <= rsi_max
        ]

        if len(candidates) <= max_tests:
            return candidates

        selected_indexes = np.linspace(0, len(candidates) - 1, num=max_tests, dtype=int)
        return [candidates[index] for index in selected_indexes]

    def _build_market_scan_row(self, result: Dict) -> Dict:
        meta = result.get("meta", {})
        stats = result.get("stats", {})
        validation = result.get("validation") or {}
        out_of_sample_stats = (validation.get("out_of_sample") or {}).get("stats", {})
        walk_forward = result.get("walk_forward") or {}

        quality_score = self._calculate_market_quality_score(
            stats=stats,
            out_of_sample_stats=out_of_sample_stats,
            validation=validation,
            walk_forward=walk_forward,
        )

        return {
            "symbol": meta.get("symbol"),
            "timeframe": meta.get("timeframe"),
            "context_timeframe": meta.get("context_timeframe"),
            "total_return_pct": round(float(stats.get("total_return_pct", 0.0)), 2),
            "profit_factor": round(float(stats.get("profit_factor", 0.0)), 2),
            "expectancy_pct": round(float(stats.get("expectancy_pct", 0.0)), 2),
            "win_rate": round(float(stats.get("win_rate", 0.0)), 2),
            "total_trades": int(stats.get("total_trades", 0)),
            "max_drawdown": round(float(stats.get("max_drawdown", 0.0)), 2),
            "oos_return_pct": round(float(out_of_sample_stats.get("total_return_pct", 0.0)), 2),
            "oos_profit_factor": round(float(out_of_sample_stats.get("profit_factor", 0.0)), 2),
            "oos_expectancy_pct": round(float(out_of_sample_stats.get("expectancy_pct", 0.0)), 2),
            "oos_trades": int(out_of_sample_stats.get("total_trades", 0)),
            "oos_passed": bool(validation.get("oos_passed", False)),
            "walk_forward_pass_rate_pct": round(float(walk_forward.get("pass_rate_pct", 0.0)), 2),
            "walk_forward_avg_oos_return_pct": round(float(walk_forward.get("avg_oos_return_pct", 0.0)), 2),
            "walk_forward_avg_oos_profit_factor": round(float(walk_forward.get("avg_oos_profit_factor", 0.0)), 2),
            "walk_forward_passed": bool(walk_forward.get("overall_passed", False)),
            "quality_score": quality_score,
            "saved_run_id": result.get("saved_run_id"),
        }

    def _build_optimization_row(self, result: Dict, optimization_metric: str, metric_value: float) -> Dict:
        row = self._build_market_scan_row(result)
        meta = result.get("meta", {})
        validation = result.get("validation") or {}
        walk_forward = result.get("walk_forward") or {}
        robust_candidate = bool(validation.get("oos_passed", False)) and (
            not walk_forward or bool(walk_forward.get("overall_passed", False))
        )

        row.update(
            {
                "optimization_metric": optimization_metric,
                "metric_value": round(float(metric_value), 4),
                "rsi_min": int(meta.get("rsi_min", 0)),
                "rsi_max": int(meta.get("rsi_max", 0)),
                "robust_candidate": robust_candidate,
            }
        )
        return row

    def _calculate_market_quality_score(
        self,
        stats: Dict,
        out_of_sample_stats: Dict,
        validation: Dict,
        walk_forward: Dict,
    ) -> float:
        score = 0.0
        profit_factor = float(stats.get("profit_factor", 0.0))
        expectancy_pct = float(stats.get("expectancy_pct", 0.0))
        total_return_pct = float(stats.get("total_return_pct", 0.0))
        max_drawdown = float(stats.get("max_drawdown", 0.0))
        total_trades = int(stats.get("total_trades", 0))

        oos_profit_factor = float(out_of_sample_stats.get("profit_factor", 0.0))
        oos_return_pct = float(out_of_sample_stats.get("total_return_pct", 0.0))
        walk_forward_pass_rate = float(walk_forward.get("pass_rate_pct", 0.0))

        score += min(max(profit_factor - 1.0, 0.0), 1.5) * 16
        score += min(max(expectancy_pct, 0.0), 5.0) * 4
        score += min(max(total_return_pct, 0.0), 20.0) * 0.8
        score += min(max(oos_profit_factor - 1.0, 0.0), 1.2) * 18
        score += min(max(oos_return_pct, 0.0), 20.0) * 1.2
        score += min(max(walk_forward_pass_rate, 0.0), 100.0) * 0.18

        if validation.get("oos_passed"):
            score += 8
        if walk_forward.get("overall_passed"):
            score += 8

        if total_trades < 5:
            score -= 12
        elif total_trades < 10:
            score -= 6

        score -= min(max(max_drawdown, 0.0), 30.0) * 1.1

        return round(min(100.0, max(0.0, score)), 2)

    def _build_objective_setup_check(
        self,
        stats: Dict[str, object],
        validation: Optional[Dict[str, object]],
        walk_forward: Optional[Dict[str, object]],
        signal_pipeline_stats: Optional[Dict[str, object]],
        risk_engine_summary: Optional[Dict[str, object]],
        setup_type_summary: Optional[List[Dict[str, object]]],
    ) -> Dict[str, object]:
        checks: List[Dict[str, object]] = []
        blockers: List[str] = []
        warnings: List[str] = []

        def _as_float(value: object, default: float = 0.0) -> float:
            try:
                return float(value if value is not None else default)
            except (TypeError, ValueError):
                return float(default)

        def _as_int(value: object, default: int = 0) -> int:
            try:
                return int(value if value is not None else default)
            except (TypeError, ValueError):
                return int(default)

        def _add_check(
            name: str,
            value: object,
            target: str,
            passed: bool,
            weight: float,
            hard: bool = False,
            fail_message: Optional[str] = None,
        ) -> None:
            checks.append(
                {
                    "name": name,
                    "value": value,
                    "target": target,
                    "passed": bool(passed),
                    "weight": float(weight),
                    "hard": bool(hard),
                }
            )
            if not passed:
                if hard and fail_message:
                    blockers.append(str(fail_message))
                elif fail_message:
                    warnings.append(str(fail_message))

        total_trades = _as_int(stats.get("total_trades", 0))
        total_return_pct = _as_float(stats.get("total_return_pct", 0.0))
        profit_factor = _as_float(stats.get("profit_factor", 0.0))
        expectancy_pct = _as_float(stats.get("expectancy_pct", 0.0))
        max_drawdown = _as_float(stats.get("max_drawdown", 0.0))
        approval_rate_pct = _as_float((signal_pipeline_stats or {}).get("approval_rate_pct", 0.0))
        candidate_count = _as_int((signal_pipeline_stats or {}).get("candidate_count", 0))
        risk_blocked_count = _as_int((risk_engine_summary or {}).get("risk_blocked_count", 0))

        _add_check(
            name="Amostra de trades",
            value=total_trades,
            target=">= 120",
            passed=total_trades >= 120,
            weight=15.0,
            hard=True,
            fail_message="Amostra insuficiente para declarar robustez.",
        )
        _add_check(
            name="Retorno total",
            value=round(total_return_pct, 2),
            target="> 0%",
            passed=total_return_pct > 0.0,
            weight=15.0,
            hard=True,
            fail_message="Retorno total negativo ou nulo.",
        )
        _add_check(
            name="Profit factor",
            value=round(profit_factor, 2),
            target=">= 1.15",
            passed=profit_factor >= 1.15,
            weight=15.0,
            hard=True,
            fail_message="Profit factor abaixo do mínimo de robustez.",
        )
        _add_check(
            name="Expectancy",
            value=round(expectancy_pct, 3),
            target=">= 0.03%",
            passed=expectancy_pct >= 0.03,
            weight=8.0,
            hard=False,
            fail_message="Expectancy ainda fraca para consistência de longo prazo.",
        )
        _add_check(
            name="Drawdown máximo",
            value=round(max_drawdown, 2),
            target="<= 18%",
            passed=max_drawdown <= 18.0,
            weight=10.0,
            hard=True,
            fail_message="Drawdown acima do limite objetivo.",
        )
        _add_check(
            name="Taxa de aprovação",
            value=round(approval_rate_pct, 2),
            target="8% a 45%",
            passed=8.0 <= approval_rate_pct <= 45.0 if candidate_count > 0 else False,
            weight=5.0,
            hard=False,
            fail_message="Pipeline de sinais desbalanceado (aprovação muito baixa/alta).",
        )
        risk_block_rate = (risk_blocked_count / candidate_count * 100.0) if candidate_count > 0 else 0.0
        _add_check(
            name="Bloqueio por risco",
            value=round(risk_block_rate, 2),
            target="<= 75%",
            passed=risk_block_rate <= 75.0,
            weight=4.0,
            hard=False,
            fail_message="Risk engine está bloqueando sinais em excesso.",
        )

        out_stats = ((validation or {}).get("out_of_sample") or {}).get("stats", {}) if validation else {}
        oos_trades = _as_int(out_stats.get("total_trades", 0))
        has_validation_window = bool(validation)
        if has_validation_window:
            oos_return_pct = _as_float(out_stats.get("total_return_pct", 0.0))
            oos_pf = _as_float(out_stats.get("profit_factor", 0.0))
            oos_expectancy = _as_float(out_stats.get("expectancy_pct", 0.0))
            oos_passed_flag = bool((validation or {}).get("oos_passed", False))

            _add_check(
                name="OOS amostra",
                value=oos_trades,
                target=">= 30",
                passed=oos_trades >= 30,
                weight=6.0,
                hard=True,
                fail_message="Amostra OOS insuficiente para validação de sobrevivência.",
            )
            _add_check(
                name="OOS retorno",
                value=round(oos_return_pct, 2),
                target="> 0%",
                passed=oos_return_pct > 0.0,
                weight=8.0,
                hard=True,
                fail_message="OOS sem retorno positivo.",
            )
            _add_check(
                name="OOS PF",
                value=round(oos_pf, 2),
                target=">= 1.05",
                passed=oos_pf >= 1.05,
                weight=8.0,
                hard=True,
                fail_message="OOS profit factor abaixo do mínimo.",
            )
            _add_check(
                name="OOS expectancy",
                value=round(oos_expectancy, 3),
                target=">= 0%",
                passed=oos_expectancy >= 0.0,
                weight=4.0,
                hard=False,
                fail_message="Expectancy OOS negativa.",
            )
            _add_check(
                name="Flag OOS",
                value=oos_passed_flag,
                target="True",
                passed=oos_passed_flag,
                weight=4.0,
                hard=False,
                fail_message="Validação OOS não passou no critério atual.",
            )
        else:
            warnings.append("Sem validação OOS nesta execução.")

        has_walk_forward = bool(walk_forward and _as_int((walk_forward or {}).get("total_windows", 0)) > 0)
        if has_walk_forward:
            wf_pass_rate = _as_float((walk_forward or {}).get("pass_rate_pct", 0.0))
            wf_pf = _as_float((walk_forward or {}).get("avg_oos_profit_factor", 0.0))
            wf_return = _as_float((walk_forward or {}).get("avg_oos_return_pct", 0.0))
            wf_passed = bool((walk_forward or {}).get("overall_passed", False))

            _add_check(
                name="WF pass rate",
                value=round(wf_pass_rate, 2),
                target=">= 55%",
                passed=wf_pass_rate >= 55.0,
                weight=6.0,
                hard=True,
                fail_message="Walk-forward inconsistente.",
            )
            _add_check(
                name="WF OOS PF médio",
                value=round(wf_pf, 2),
                target=">= 1.0",
                passed=wf_pf >= 1.0,
                weight=5.0,
                hard=False,
                fail_message="Walk-forward com PF médio fraco.",
            )
            _add_check(
                name="WF OOS retorno médio",
                value=round(wf_return, 2),
                target=">= 0%",
                passed=wf_return >= 0.0,
                weight=5.0,
                hard=False,
                fail_message="Walk-forward com retorno médio negativo.",
            )
            _add_check(
                name="Flag WF",
                value=wf_passed,
                target="True",
                passed=wf_passed,
                weight=3.0,
                hard=False,
                fail_message="Critério final de walk-forward não aprovado.",
            )
        else:
            warnings.append("Sem walk-forward nesta execução.")

        setup_candidates: List[Dict[str, object]] = []
        for row in (setup_type_summary or []):
            setup_name = str(row.get("setup_type") or row.get("setup_name") or "unknown")
            setup_trades = _as_int(row.get("total_trades", 0))
            setup_pf = _as_float(row.get("profit_factor", 0.0))
            setup_wr = _as_float(row.get("win_rate", 0.0))
            setup_net = _as_float(row.get("net_profit", 0.0))
            setup_score = (
                min(max(setup_pf - 1.0, 0.0), 1.5) * 35.0
                + min(max(setup_wr, 0.0), 100.0) * 0.25
                + (10.0 if setup_net > 0 else -6.0)
                + min(setup_trades, 120) * 0.10
            )
            setup_candidates.append(
                {
                    "setup_type": setup_name,
                    "total_trades": setup_trades,
                    "profit_factor": round(setup_pf, 2),
                    "win_rate": round(setup_wr, 2),
                    "net_profit": round(setup_net, 2),
                    "setup_score": round(max(setup_score, 0.0), 2),
                }
            )
        setup_candidates.sort(key=lambda item: item.get("setup_score", 0.0), reverse=True)
        recommended_setup = setup_candidates[0]["setup_type"] if setup_candidates else None
        if setup_candidates:
            best_setup = setup_candidates[0]
            if best_setup.get("profit_factor", 0.0) < 1.0:
                warnings.append("Nenhum setup com PF >= 1.0 na amostra atual.")
            if _as_int(best_setup.get("total_trades", 0)) < 30:
                warnings.append("Setup líder ainda tem amostra pequena.")

        weighted_total = sum(float(item.get("weight", 0.0) or 0.0) for item in checks)
        weighted_pass = sum(
            float(item.get("weight", 0.0) or 0.0)
            for item in checks
            if bool(item.get("passed"))
        )
        objective_score = round((weighted_pass / weighted_total) * 100.0, 2) if weighted_total > 0 else 0.0

        if blockers:
            status = "blocked"
        elif objective_score >= 75.0:
            status = "approved"
        else:
            status = "candidate"

        if objective_score >= 85.0:
            grade = "A"
        elif objective_score >= 70.0:
            grade = "B"
        elif objective_score >= 55.0:
            grade = "C"
        else:
            grade = "D"

        next_actions: List[str] = []
        if any("Amostra insuficiente" in blocker for blocker in blockers):
            next_actions.append("Aumentar amostra de trades antes de promover o setup.")
        if any("Profit factor" in blocker for blocker in blockers) or any("Retorno total" in blocker for blocker in blockers):
            next_actions.append("Recalibrar entrada/saída (RR, filtros de contexto e quality gates).")
        if any("OOS" in blocker for blocker in blockers):
            next_actions.append("Priorizar robustez OOS antes de qualquer ativação operacional.")
        if any("Walk-forward" in blocker for blocker in blockers):
            next_actions.append("Ajustar lógica para manter consistência entre janelas temporais.")
        if recommended_setup:
            next_actions.append(f"Focar iterações no setup com maior score atual: {recommended_setup}.")

        if not next_actions:
            next_actions.append("Manter monitoramento e repetir validação após nova janela de dados.")

        return {
            "status": status,
            "objective_score": objective_score,
            "objective_grade": grade,
            "checks": checks,
            "blockers": list(dict.fromkeys(blockers)),
            "warnings": list(dict.fromkeys(warnings)),
            "recommended_setup": recommended_setup,
            "setup_candidates": setup_candidates[:5],
            "next_actions": list(dict.fromkeys(next_actions)),
        }

    def _market_scan_sort_key(self, row: Dict) -> Tuple[float, float, float, float]:
        return (
            float(row.get("quality_score", 0.0)),
            float(row.get("oos_profit_factor", 0.0)),
            float(row.get("walk_forward_pass_rate_pct", 0.0)),
            float(row.get("total_return_pct", 0.0)),
        )

    def _extract_optimization_metric(self, result: Dict, optimization_metric: str) -> float:
        stats = result.get("stats", {})
        metric_map = {
            "Total Return": float(stats.get("total_return_pct", 0.0)),
            "Sharpe Ratio": float(stats.get("sharpe_ratio", 0.0)),
            "Win Rate": float(stats.get("win_rate", 0.0)),
            "Profit Factor": float(stats.get("profit_factor", 0.0)),
        }
        return metric_map.get(optimization_metric, float(stats.get("total_return_pct", 0.0)))

    def _optimization_sort_key(self, row: Dict) -> Tuple[bool, bool, float, float]:
        return (
            bool(row.get("robust_candidate", False)),
            bool(row.get("oos_passed", False)),
            float(row.get("metric_value", 0.0)),
            float(row.get("quality_score", 0.0)),
        )

    def _normalize_strategy_pct(self, raw_value: float) -> float:
        value = float(raw_value or 0.0)
        return value / 100 if value > 0 else 0.0

    def _normalize_position_size(self, raw_value: float) -> float:
        value = float(raw_value or 0.0)
        return value / 100 if value > 1 else value

    def _normalize_ratio(self, raw_value: float) -> float:
        value = float(raw_value or 0.0)
        return value / 100 if value > 1 else value

    def _timeframe_to_milliseconds(self, timeframe: str) -> int:
        mapping = {
            "1m": 60_000,
            "3m": 180_000,
            "5m": 300_000,
            "15m": 900_000,
            "30m": 1_800_000,
            "1h": 3_600_000,
            "2h": 7_200_000,
            "4h": 14_400_000,
            "6h": 21_600_000,
            "8h": 28_800_000,
            "12h": 43_200_000,
            "1d": 86_400_000,
        }
        if timeframe not in mapping:
            raise ValueError(f"Timeframe nao suportado: {timeframe}")
        return mapping[timeframe]

    def _build_klines_url(self, endpoint: str, symbol: str, timeframe: str, start_ms: int, end_ms: int) -> str:
        return (
            f"{endpoint}?symbol={symbol.replace('/', '')}&interval={timeframe}"
            f"&limit=1000&startTime={start_ms}&endTime={end_ms}"
        )

    def _fetch_historical_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
    ) -> pd.DataFrame:
        start_ms = int(pd.Timestamp(start_date).timestamp() * 1000)
        end_ms = int(pd.Timestamp(end_date).timestamp() * 1000)
        step_ms = self._timeframe_to_milliseconds(timeframe)
        endpoints = [
            "https://fapi.binance.com/fapi/v1/klines",
            "https://api.binance.com/api/v3/klines",
            "https://api.binance.us/api/v3/klines",
        ]

        for endpoint in endpoints:
            cursor = start_ms
            candles: List[List] = []

            try:
                while cursor < end_ms:
                    response = requests.get(
                        self._build_klines_url(endpoint, symbol, timeframe, cursor, end_ms),
                        timeout=20,
                    )
                    response.raise_for_status()
                    batch = response.json()

                    if not batch:
                        break

                    candles.extend(batch)
                    next_cursor = int(batch[-1][0]) + step_ms
                    if next_cursor <= cursor:
                        break
                    cursor = next_cursor

                    if len(batch) < 1000:
                        break

                if candles:
                    return self._candles_to_dataframe(candles)
            except Exception as exc:
                logger.warning("Falha ao buscar klines historicos em %s: %s", endpoint, exc)

        raise ConnectionError("Nao foi possivel obter dados historicos para o backtest")

    def _candles_to_dataframe(self, candles: List[List]) -> pd.DataFrame:
        df = pd.DataFrame(
            [
                [
                    int(candle[0]),
                    float(candle[1]),
                    float(candle[2]),
                    float(candle[3]),
                    float(candle[4]),
                    float(candle[5]),
                ]
                for candle in candles
            ],
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df

    def _build_benchmark_history(
        self,
        df: pd.DataFrame,
        start_date: datetime,
        end_date: datetime,
        initial_balance: float,
        warmup_candles: int,
    ) -> List[Dict[str, object]]:
        start_idx = max(warmup_candles, int(df.index.searchsorted(pd.Timestamp(start_date), side="left")))
        end_idx = min(int(df.index.searchsorted(pd.Timestamp(end_date), side="right")) - 1, len(df) - 1)
        if start_idx >= len(df) or end_idx < start_idx:
            return []

        benchmark_slice = df.iloc[start_idx : end_idx + 1]
        if benchmark_slice.empty:
            return []

        base_close = float(benchmark_slice.iloc[0].get("close", 0.0) or 0.0)
        if base_close <= 0:
            return []

        benchmark_history: List[Dict[str, object]] = []
        for timestamp, row in benchmark_slice.iterrows():
            close_price = float(row.get("close", base_close) or base_close)
            benchmark_value = float(initial_balance) * (close_price / base_close)
            benchmark_history.append(
                {
                    "timestamp": pd.Timestamp(timestamp),
                    "benchmark_value": round(float(benchmark_value), 2),
                    "close": round(close_price, 6),
                }
            )
        return benchmark_history

    def _run_simulation(
        self,
        symbol: str,
        df: pd.DataFrame,
        context_df: Optional[pd.DataFrame],
        timeframe: str,
        context_timeframe: Optional[str],
        start_date: datetime,
        end_date: datetime,
        initial_balance: float,
        stop_loss_pct: float,
        take_profit_pct: float,
        fee_rate: float,
        slippage: float,
        position_size_pct: float,
        require_volume: bool,
        require_trend: bool,
        avoid_ranging: bool,
        strategy_version: Optional[str],
        setup_name: Optional[str],
        sample_type: str,
        allowed_execution_setups: Optional[Set[str]],
    ) -> Tuple[List[Dict], List[Dict], float, Dict[str, object], Dict[str, object], List[Dict[str, object]]]:
        warmup_candles = max(210, int(getattr(self.trading_bot, "rsi_period", 14)) + 5)
        start_idx = max(warmup_candles, int(df.index.searchsorted(pd.Timestamp(start_date), side="left")))
        end_idx = min(int(df.index.searchsorted(pd.Timestamp(end_date), side="right")) - 1, len(df) - 1)
        effective_context_timeframe = context_timeframe if context_df is not None else None
        signal_window_candles = max(320, warmup_candles + 40)
        context_window_candles = max(220, signal_window_candles // 2)

        if start_idx >= len(df) - 1 or end_idx <= start_idx:
            raise ValueError("Dados insuficientes para backtest")

        trade_history: List[Dict] = []
        portfolio_history: List[Dict] = []
        signal_pipeline_stats = self._build_empty_signal_pipeline_stats()
        risk_engine_stats = self._build_empty_risk_engine_stats()
        signal_audit_log: List[Dict[str, object]] = []
        balance = float(initial_balance)
        open_position: Optional[Position] = None

        for idx in range(start_idx, end_idx):
            slice_start = max(0, (idx + 1) - signal_window_candles)
            current_slice = df.iloc[slice_start : idx + 1]
            current_row = current_slice.iloc[-1]
            next_row = df.iloc[idx + 1]
            pending_audit_entry: Optional[Dict[str, object]] = None

            def _queue_audit(entry: Optional[Dict[str, object]]) -> None:
                nonlocal pending_audit_entry
                if entry:
                    pending_audit_entry = entry

            current_context_slice = None
            if context_df is not None and not context_df.empty:
                context_end = int(context_df.index.searchsorted(pd.Timestamp(current_row.name), side="right"))
                if context_end > 0:
                    context_start = max(0, context_end - context_window_candles)
                    current_context_slice = context_df.iloc[context_start:context_end]

            if open_position is not None:
                open_position.age_candles += 1
                self._update_position_excursions(open_position, current_row)
                intrabar_trade = self._close_if_stop_or_take_hit(
                    open_position=open_position,
                    candle=current_row,
                    fee_rate=fee_rate,
                    slippage=slippage,
                )
                if intrabar_trade is not None:
                    balance += intrabar_trade["net_pnl"]
                    trade_history.append(intrabar_trade)
                    open_position = None
                else:
                    management = self._evaluate_position_management(
                        open_position=open_position,
                        current_slice=current_slice,
                        timeframe=timeframe,
                    )
                    open_position.stop_loss_price = management.get("stop_price")
                    open_position.take_profit_price = management.get("take_price")
                    open_position.break_even_active = bool(management.get("break_even_active", open_position.break_even_active))
                    open_position.trailing_active = bool(management.get("trailing_active", open_position.trailing_active))
                    open_position.protection_level = str(management.get("protection_level") or open_position.protection_level)
                    open_position.regime_exit_flag = bool(management.get("regime_exit_flag", False))
                    open_position.structure_exit_flag = bool(management.get("structure_exit_flag", False))
                    open_position.post_pump_protection = bool(
                        management.get("post_pump_protection", open_position.post_pump_protection)
                    )
                    open_position.mfe_pct = max(open_position.mfe_pct, float(management.get("mfe_pct", 0.0) or 0.0))
                    open_position.mae_pct = max(open_position.mae_pct, float(management.get("mae_pct", 0.0) or 0.0))
                    open_position.max_unrealized_rr = max(
                        open_position.max_unrealized_rr,
                        float(management.get("unrealized_rr", 0.0) or 0.0),
                    )
                    management_action = str(management.get("action") or "hold")
                    if management_action == "exit_on_structure_failure":
                        signal_trade = self._close_position(
                            open_position=open_position,
                            raw_exit_price=float(next_row["open"]),
                            exit_timestamp=pd.Timestamp(next_row.name),
                            fee_rate=fee_rate,
                            slippage=slippage,
                            reason="STRUCTURE_FAILURE",
                        )
                        balance += signal_trade["net_pnl"]
                        trade_history.append(signal_trade)
                        open_position = None
                    elif management_action == "exit_on_regime_shift":
                        signal_trade = self._close_position(
                            open_position=open_position,
                            raw_exit_price=float(next_row["open"]),
                            exit_timestamp=pd.Timestamp(next_row.name),
                            fee_rate=fee_rate,
                            slippage=slippage,
                            reason="REGIME_SHIFT",
                        )
                        balance += signal_trade["net_pnl"]
                        trade_history.append(signal_trade)
                        open_position = None

            signal_pipeline = self._evaluate_signal_pipeline_with_optional_context(
                current_slice=current_slice,
                timeframe=timeframe,
                require_volume=require_volume,
                require_trend=require_trend,
                avoid_ranging=avoid_ranging,
                context_df=current_context_slice,
                context_timeframe=effective_context_timeframe,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
            )
            signal_pipeline = self._apply_setup_execution_policy(
                signal_pipeline,
                allowed_execution_setups=allowed_execution_setups,
            )
            self._record_signal_pipeline_stats(signal_pipeline_stats, signal_pipeline)
            signal = str(signal_pipeline.get("analytical_signal") or "NEUTRO")

            if open_position is not None and self._should_force_opposite_exit(
                position_side=open_position.side,
                signal_pipeline=signal_pipeline,
                analytical_signal=signal,
            ):
                signal_trade = self._close_position(
                    open_position=open_position,
                    raw_exit_price=float(next_row["open"]),
                    exit_timestamp=pd.Timestamp(next_row.name),
                    fee_rate=fee_rate,
                    slippage=slippage,
                    reason="OPPOSITE_SIGNAL",
                )
                balance += signal_trade["net_pnl"]
                trade_history.append(signal_trade)
                open_position = None

            if open_position is not None:
                audit_entry = self._build_signal_audit_entry(
                    symbol=symbol,
                    timeframe=timeframe,
                    strategy_version=strategy_version,
                    timestamp=pd.Timestamp(current_row.name),
                    signal_pipeline=signal_pipeline,
                )
                _queue_audit(audit_entry)

            if open_position is None and signal in LONG_SIGNALS.union(SHORT_SIGNALS):
                risk_plan = None
                if stop_loss_pct > 0:
                    portfolio_summary = self._build_backtest_portfolio_summary(open_position)
                    circuit_breaker = self._build_backtest_circuit_breaker_summary(
                        trade_history=trade_history,
                        reference_timestamp=pd.Timestamp(current_row.name),
                        account_balance=initial_balance,
                    )
                    drawdown_summary = self._build_backtest_drawdown_summary(
                        trade_history=trade_history,
                        portfolio_history=portfolio_history,
                        current_balance=balance,
                        initial_balance=initial_balance,
                    )
                    risk_plan = self.risk_management_service.evaluate_risk_engine(
                        entry_price=float(next_row["open"]),
                        stop_loss_pct=stop_loss_pct,
                        symbol=None,
                        timeframe=timeframe,
                        strategy_version=strategy_version,
                        account_balance=balance,
                        portfolio_summary=portfolio_summary,
                        symbol_portfolio_summary=portfolio_summary,
                        circuit_breaker=circuit_breaker,
                        drawdown_summary=drawdown_summary,
                    )
                    if not risk_plan.get("allowed", True):
                        audit_entry = self._build_signal_audit_entry(
                            symbol=symbol,
                            timeframe=timeframe,
                            strategy_version=strategy_version,
                            timestamp=pd.Timestamp(current_row.name),
                            signal_pipeline=signal_pipeline,
                            risk_plan=risk_plan,
                        )
                        _queue_audit(audit_entry)
                        if pending_audit_entry:
                            signal_audit_log.append(pending_audit_entry)
                        self._record_risk_block(risk_engine_stats, risk_plan)
                        portfolio_value = balance
                        portfolio_history.append(
                            {
                                "timestamp": pd.Timestamp(current_row.name),
                                "portfolio_value": round(float(portfolio_value), 2),
                            }
                        )
                        continue

                audit_entry = self._build_signal_audit_entry(
                    symbol=symbol,
                    timeframe=timeframe,
                    strategy_version=strategy_version,
                    timestamp=pd.Timestamp(current_row.name),
                    signal_pipeline=signal_pipeline,
                    risk_plan=risk_plan,
                )
                _queue_audit(audit_entry)

                opened = self._open_position(
                    signal=signal,
                    signal_pipeline=signal_pipeline,
                    risk_plan=risk_plan,
                    current_row=current_row,
                    next_row=next_row,
                    balance=balance,
                    position_size_pct=position_size_pct,
                    fee_rate=fee_rate,
                    slippage=slippage,
                    stop_loss_pct=stop_loss_pct,
                    take_profit_pct=take_profit_pct,
                    strategy_version=strategy_version,
                    context_timeframe=effective_context_timeframe,
                    setup_name=setup_name,
                    sample_type=sample_type,
                )
                if opened is not None:
                    self._record_risk_trade(risk_engine_stats, risk_plan)
                    open_position = opened
                    balance -= open_position.entry_fee
            elif signal in {"NEUTRO", ""}:
                audit_entry = self._build_signal_audit_entry(
                    symbol=symbol,
                    timeframe=timeframe,
                    strategy_version=strategy_version,
                    timestamp=pd.Timestamp(current_row.name),
                    signal_pipeline=signal_pipeline,
                )
                _queue_audit(audit_entry)

            if pending_audit_entry:
                signal_audit_log.append(pending_audit_entry)

            portfolio_value = balance
            if open_position is not None:
                portfolio_value += self._calculate_unrealized_pnl(open_position, float(current_row["close"]))

            portfolio_history.append(
                {
                    "timestamp": pd.Timestamp(current_row.name),
                    "portfolio_value": round(float(portfolio_value), 2),
                }
            )

        final_row = df.iloc[end_idx]
        if open_position is not None:
            closing_trade = self._close_position(
                open_position=open_position,
                raw_exit_price=float(final_row["close"]),
                exit_timestamp=pd.Timestamp(final_row.name),
                fee_rate=fee_rate,
                slippage=slippage,
                reason="END_OF_TEST",
            )
            balance += closing_trade["net_pnl"]
            trade_history.append(closing_trade)

        portfolio_history.append(
            {
                "timestamp": pd.Timestamp(final_row.name),
                "portfolio_value": round(float(balance), 2),
            }
        )
        return (
            trade_history,
            portfolio_history,
            float(balance),
            self._finalize_signal_pipeline_stats(signal_pipeline_stats),
            self._finalize_risk_engine_stats(risk_engine_stats, trade_history),
            signal_audit_log,
        )

    def _check_signal_with_optional_context(
        self,
        current_slice: pd.DataFrame,
        timeframe: str,
        require_volume: bool,
        require_trend: bool,
        avoid_ranging: bool,
        context_df: Optional[pd.DataFrame],
        context_timeframe: Optional[str],
        stop_loss_pct: float,
        take_profit_pct: float,
    ) -> str:
        kwargs = {
            "timeframe": timeframe,
            "require_volume": require_volume,
            "require_trend": require_trend,
            "avoid_ranging": avoid_ranging,
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
        }
        if context_timeframe and context_df is not None:
            kwargs["context_df"] = context_df
            kwargs["context_timeframe"] = context_timeframe

        try:
            return self.trading_bot.check_signal(current_slice, **kwargs)
        except TypeError as exc:
            if "unexpected keyword argument" not in str(exc):
                raise

        kwargs_without_risk = kwargs.copy()
        kwargs_without_risk.pop("stop_loss_pct", None)
        kwargs_without_risk.pop("take_profit_pct", None)
        try:
            return self.trading_bot.check_signal(current_slice, **kwargs_without_risk)
        except TypeError as exc:
            if "unexpected keyword argument" not in str(exc):
                raise

        kwargs_without_context = kwargs_without_risk.copy()
        kwargs_without_context.pop("context_df", None)
        kwargs_without_context.pop("context_timeframe", None)
        return self.trading_bot.check_signal(current_slice, **kwargs_without_context)

    def _evaluate_signal_pipeline_with_optional_context(
        self,
        current_slice: pd.DataFrame,
        timeframe: str,
        require_volume: bool,
        require_trend: bool,
        avoid_ranging: bool,
        context_df: Optional[pd.DataFrame],
        context_timeframe: Optional[str],
        stop_loss_pct: float,
        take_profit_pct: float,
    ) -> Dict[str, object]:
        kwargs = {
            "timeframe": timeframe,
            "require_volume": require_volume,
            "require_trend": require_trend,
            "avoid_ranging": avoid_ranging,
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
        }
        if context_timeframe and context_df is not None:
            kwargs["context_df"] = context_df
            kwargs["context_timeframe"] = context_timeframe

        pipeline_method = getattr(self.trading_bot, "evaluate_signal_pipeline", None)
        if callable(pipeline_method):
            try:
                return self._normalize_signal_pipeline(pipeline_method(current_slice, **kwargs))
            except TypeError as exc:
                if "unexpected keyword argument" not in str(exc):
                    raise

            kwargs_without_risk = kwargs.copy()
            kwargs_without_risk.pop("stop_loss_pct", None)
            kwargs_without_risk.pop("take_profit_pct", None)
            try:
                return self._normalize_signal_pipeline(pipeline_method(current_slice, **kwargs_without_risk))
            except TypeError as exc:
                if "unexpected keyword argument" not in str(exc):
                    raise

            kwargs_without_context = kwargs_without_risk.copy()
            kwargs_without_context.pop("context_df", None)
            kwargs_without_context.pop("context_timeframe", None)
            return self._normalize_signal_pipeline(pipeline_method(current_slice, **kwargs_without_context))

        fallback_signal = self._check_signal_with_optional_context(
            current_slice=current_slice,
            timeframe=timeframe,
            require_volume=require_volume,
            require_trend=require_trend,
            avoid_ranging=avoid_ranging,
            context_df=context_df,
            context_timeframe=context_timeframe,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
        )
        return self._normalize_signal_pipeline(None, fallback_signal=fallback_signal)

    def _build_backtest_portfolio_summary(
        self,
        open_position: Optional[Position],
    ) -> Dict[str, float]:
        if open_position is None:
            return {
                "open_trades": 0,
                "total_open_risk_pct": 0.0,
                "total_open_risk_amount": 0.0,
                "total_open_position_notional": 0.0,
            }

        risk_pct = 0.0
        risk_amount = 0.0
        if open_position.notional > 0 and open_position.initial_stop_loss_price is not None:
            stop_distance = abs(float(open_position.entry_price) - float(open_position.initial_stop_loss_price))
            risk_amount = stop_distance * float(open_position.quantity or 0.0)
            risk_pct = (risk_amount / float(open_position.notional)) * 100.0 if open_position.notional else 0.0
        return {
            "open_trades": 1,
            "total_open_risk_pct": round(risk_pct, 4),
            "total_open_risk_amount": round(risk_amount, 4),
            "total_open_position_notional": round(float(open_position.notional or 0.0), 4),
        }

    def _build_backtest_circuit_breaker_summary(
        self,
        trade_history: List[Dict[str, object]],
        reference_timestamp: pd.Timestamp,
        account_balance: float,
    ) -> Dict[str, object]:
        session_date = pd.Timestamp(reference_timestamp).normalize()
        daily_trades = [
            trade for trade in trade_history
            if pd.Timestamp(trade.get("timestamp")).normalize() == session_date
        ]
        realized_pnl = sum(float(trade.get("profit_loss", 0.0) or 0.0) for trade in daily_trades)
        reference_balance = max(float(account_balance or 0.0), 1.0)
        realized_pnl_pct = (realized_pnl / reference_balance) * 100.0

        consecutive_losses = 0
        for trade in reversed(trade_history):
            pnl_pct = float(trade.get("profit_loss_pct", 0.0) or 0.0)
            if pnl_pct < 0:
                consecutive_losses += 1
                continue
            break

        return {
            "allowed": True,
            "reason": "",
            "status": "healthy",
            "daily_closed_trades": len(daily_trades),
            "daily_realized_pnl": round(realized_pnl, 4),
            "daily_realized_pnl_pct": round(realized_pnl_pct, 4),
            "consecutive_losses": consecutive_losses,
        }

    def _build_backtest_drawdown_summary(
        self,
        trade_history: List[Dict[str, object]],
        portfolio_history: List[Dict[str, object]],
        current_balance: float,
        initial_balance: float,
    ) -> Dict[str, float]:
        history_values = [float(point.get("portfolio_value", 0.0) or 0.0) for point in portfolio_history]
        history_values.append(float(current_balance))
        filtered_values = [value for value in history_values if value > 0]
        if not filtered_values:
            filtered_values = [float(initial_balance or 0.0) or 1.0]

        peak = filtered_values[0]
        current_drawdown_pct = 0.0
        max_drawdown_pct = 0.0
        for value in filtered_values:
            peak = max(peak, value)
            if peak > 0:
                drawdown_pct = max(((peak - value) / peak) * 100.0, 0.0)
                current_drawdown_pct = drawdown_pct
                max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)

        return {
            "closed_trades": len(trade_history),
            "starting_balance": round(float(initial_balance or 0.0), 2),
            "current_equity": round(float(current_balance or 0.0), 2),
            "peak_equity": round(float(peak or 0.0), 2),
            "current_drawdown_pct": round(current_drawdown_pct, 4),
            "max_drawdown_pct": round(max_drawdown_pct, 4),
        }

    def _open_position(
        self,
        signal: str,
        signal_pipeline: Optional[Dict[str, object]],
        risk_plan: Optional[Dict[str, object]],
        current_row: pd.Series,
        next_row: pd.Series,
        balance: float,
        position_size_pct: float,
        fee_rate: float,
        slippage: float,
        stop_loss_pct: float,
        take_profit_pct: float,
        strategy_version: Optional[str],
        context_timeframe: Optional[str],
        setup_name: Optional[str],
        sample_type: str,
    ) -> Optional[Position]:
        if balance <= 0 or position_size_pct <= 0:
            return None

        side = "long" if signal in LONG_SIGNALS else "short"
        raw_entry_price = float(next_row["open"])
        entry_price = self._apply_slippage(raw_entry_price, side=side, is_entry=True, slippage=slippage)
        notional = float((risk_plan or {}).get("position_notional", 0.0) or 0.0)
        quantity = float((risk_plan or {}).get("quantity", 0.0) or 0.0)
        risk_amount = float((risk_plan or {}).get("risk_amount", 0.0) or 0.0)
        risk_mode = str((risk_plan or {}).get("risk_mode") or "normal")
        size_reduced = bool((risk_plan or {}).get("size_reduced", False))
        risk_reason = (risk_plan or {}).get("risk_reason") or (risk_plan or {}).get("reason")
        if notional <= 0 or quantity <= 0:
            notional = balance * position_size_pct
            quantity = notional / entry_price if entry_price > 0 else 0.0
        if quantity <= 0:
            return None

        stop_loss_price = None
        take_profit_price = None
        if stop_loss_pct > 0:
            stop_loss_price = entry_price * (1 - stop_loss_pct if side == "long" else 1 + stop_loss_pct)
        if take_profit_pct > 0:
            take_profit_price = entry_price * (1 + take_profit_pct if side == "long" else 1 - take_profit_pct)

        entry_evaluation = (signal_pipeline or {}).get("entry_quality_evaluation") or {}
        context_evaluation = (signal_pipeline or {}).get("context_evaluation") or {}
        structure_evaluation = (signal_pipeline or {}).get("structure_evaluation") or {}
        confirmation_evaluation = (signal_pipeline or {}).get("confirmation_evaluation") or {}
        scenario_evaluation = (signal_pipeline or {}).get("scenario_evaluation") or {}
        trade_decision = getattr(self.trading_bot, "_last_trade_decision", None)
        setup_name = (
            entry_evaluation.get("setup_type")
            or (trade_decision.get("setup_type") if isinstance(trade_decision, dict) else None)
            or setup_name
            or strategy_version
            or signal
        )
        regime_evaluation = (signal_pipeline or {}).get("regime_evaluation") or {}
        signal_score = (
            entry_evaluation.get("entry_score")
            if entry_evaluation.get("entry_score") is not None
            else trade_decision.get("confidence")
            if isinstance(trade_decision, dict) and trade_decision.get("confidence") is not None
            else current_row.get("signal_confidence", 0.0)
        )
        if pd.isna(signal_score):
            signal_score = 0.0
        atr_value = current_row.get("atr", 0.0)
        if pd.isna(atr_value):
            atr_value = 0.0
        entry_reason = signal
        if isinstance(trade_decision, dict):
            entry_reason = trade_decision.get("entry_reason") or entry_reason
        combined_notes: List[str] = []
        for bucket in (
            regime_evaluation.get("notes") or [],
            structure_evaluation.get("notes") or [],
            confirmation_evaluation.get("notes") or [],
            entry_evaluation.get("notes") or [],
            scenario_evaluation.get("notes") or [],
        ):
            for note in bucket[:1]:
                combined_notes.append(str(note))

        return Position(
            side=side,
            signal=signal,
            setup_name=setup_name,
            strategy_version=strategy_version,
            context_timeframe=context_timeframe,
            regime=regime_evaluation.get("regime") or current_row.get("market_regime"),
            regime_score=float(regime_evaluation.get("regime_score", 0.0) or 0.0),
            trend_state=regime_evaluation.get("trend_state"),
            volatility_state=regime_evaluation.get("volatility_state"),
            context_bias=context_evaluation.get("market_bias"),
            structure_state=structure_evaluation.get("structure_state"),
            confirmation_state=confirmation_evaluation.get("confirmation_state"),
            signal_score=float(signal_score or 0.0),
            atr=float(atr_value or 0.0),
            entry_reason=entry_reason,
            entry_quality=entry_evaluation.get("entry_quality"),
            entry_score=float(entry_evaluation.get("entry_score", 0.0) or 0.0),
            scenario_score=float(scenario_evaluation.get("scenario_score", 0.0) or 0.0),
            rejection_reason=entry_evaluation.get("rejection_reason"),
            notes=combined_notes,
            sample_type=sample_type,
            risk_mode=risk_mode,
            risk_amount=float(risk_amount or 0.0),
            size_reduced=size_reduced,
            risk_reason=risk_reason,
            entry_timestamp=pd.Timestamp(next_row.name),
            entry_price=entry_price,
            quantity=quantity,
            notional=notional,
            entry_fee=notional * fee_rate,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            initial_stop_loss_price=stop_loss_price,
            initial_take_profit_price=take_profit_price,
        )

    def _update_position_excursions(self, open_position: Position, candle: pd.Series) -> None:
        entry_price = float(open_position.entry_price or 0.0)
        if entry_price <= 0:
            return

        high_price = float(candle.get("high", candle.get("close", entry_price)))
        low_price = float(candle.get("low", candle.get("close", entry_price)))
        if open_position.side == "long":
            favorable_move = max(high_price - entry_price, 0.0)
            adverse_move = max(entry_price - low_price, 0.0)
        else:
            favorable_move = max(entry_price - low_price, 0.0)
            adverse_move = max(high_price - entry_price, 0.0)

        open_position.mfe_pct = max(open_position.mfe_pct, (favorable_move / entry_price) * 100.0)
        open_position.mae_pct = max(open_position.mae_pct, (adverse_move / entry_price) * 100.0)
        initial_stop = open_position.initial_stop_loss_price
        if initial_stop is not None:
            initial_risk = abs(float(entry_price) - float(initial_stop))
            if initial_risk > 0:
                open_position.max_unrealized_rr = max(
                    open_position.max_unrealized_rr,
                    favorable_move / initial_risk,
                )

    def _evaluate_position_management(
        self,
        open_position: Position,
        current_slice: pd.DataFrame,
        timeframe: str,
    ) -> Dict[str, object]:
        regime_evaluation = {}
        regime_method = getattr(self.trading_bot, "evaluate_market_regime", None)
        if callable(regime_method):
            try:
                regime_evaluation = regime_method(current_slice, timeframe=timeframe, persist=False)
            except TypeError:
                regime_evaluation = regime_method(current_slice, timeframe=timeframe)
        elif current_slice is not None and not current_slice.empty:
            last_row = current_slice.iloc[-1]
            regime_evaluation = {
                "regime": last_row.get("market_regime", "range"),
                "volatility_state": "normal_volatility",
                "regime_score": 0.0,
                "parabolic": False,
            }

        return evaluate_position_management(
            recent_df=current_slice,
            side=open_position.side,
            entry_price=open_position.entry_price,
            current_stop_price=open_position.stop_loss_price,
            current_take_price=open_position.take_profit_price,
            initial_stop_price=open_position.initial_stop_loss_price,
            initial_take_price=open_position.initial_take_profit_price,
            break_even_active=open_position.break_even_active,
            trailing_active=open_position.trailing_active,
            protection_level=open_position.protection_level,
            regime_evaluation=regime_evaluation,
            mfe_pct=open_position.mfe_pct,
            mae_pct=open_position.mae_pct,
            position_age_candles=open_position.age_candles,
        )

    def _close_if_stop_or_take_hit(
        self,
        open_position: Position,
        candle: pd.Series,
        fee_rate: float,
        slippage: float,
    ) -> Optional[Dict]:
        low_price = float(candle["low"])
        high_price = float(candle["high"])

        if open_position.side == "long":
            stop_hit = open_position.stop_loss_price is not None and low_price <= open_position.stop_loss_price
            take_hit = open_position.take_profit_price is not None and high_price >= open_position.take_profit_price
            if stop_hit:
                return self._close_position(
                    open_position=open_position,
                    raw_exit_price=open_position.stop_loss_price,
                    exit_timestamp=pd.Timestamp(candle.name),
                    fee_rate=fee_rate,
                    slippage=slippage,
                    reason="STOP_LOSS",
                )
            if take_hit:
                return self._close_position(
                    open_position=open_position,
                    raw_exit_price=open_position.take_profit_price,
                    exit_timestamp=pd.Timestamp(candle.name),
                    fee_rate=fee_rate,
                    slippage=slippage,
                    reason="TAKE_PROFIT",
                )
            return None

        stop_hit = open_position.stop_loss_price is not None and high_price >= open_position.stop_loss_price
        take_hit = open_position.take_profit_price is not None and low_price <= open_position.take_profit_price
        if stop_hit:
            return self._close_position(
                open_position=open_position,
                raw_exit_price=open_position.stop_loss_price,
                exit_timestamp=pd.Timestamp(candle.name),
                fee_rate=fee_rate,
                slippage=slippage,
                reason="STOP_LOSS",
            )
        if take_hit:
            return self._close_position(
                open_position=open_position,
                raw_exit_price=open_position.take_profit_price,
                exit_timestamp=pd.Timestamp(candle.name),
                fee_rate=fee_rate,
                slippage=slippage,
                reason="TAKE_PROFIT",
            )
        return None

    def _apply_slippage(self, price: float, side: str, is_entry: bool, slippage: float) -> float:
        if side == "long":
            return price * (1 + slippage) if is_entry else price * (1 - slippage)
        return price * (1 - slippage) if is_entry else price * (1 + slippage)

    def _close_position(
        self,
        open_position: Position,
        raw_exit_price: float,
        exit_timestamp: pd.Timestamp,
        fee_rate: float,
        slippage: float,
        reason: str,
    ) -> Dict:
        exit_price = self._apply_slippage(raw_exit_price, side=open_position.side, is_entry=False, slippage=slippage)
        exit_notional = open_position.quantity * exit_price
        exit_fee = exit_notional * fee_rate

        if open_position.side == "long":
            gross_pnl = open_position.quantity * (exit_price - open_position.entry_price)
        else:
            gross_pnl = open_position.quantity * (open_position.entry_price - exit_price)

        net_pnl = gross_pnl - exit_fee
        total_trade_pnl = gross_pnl - open_position.entry_fee - exit_fee
        profit_loss_pct = (total_trade_pnl / open_position.notional) * 100 if open_position.notional else 0.0
        holding_minutes = max(
            (pd.Timestamp(exit_timestamp) - pd.Timestamp(open_position.entry_timestamp)).total_seconds() / 60.0,
            0.0,
        )
        initial_stop_pct = 0.0
        if open_position.initial_stop_loss_price is not None and open_position.entry_price:
            initial_stop_pct = (
                abs(float(open_position.entry_price) - float(open_position.initial_stop_loss_price))
                / float(open_position.entry_price)
                * 100.0
            )
        rr_realized = (profit_loss_pct / initial_stop_pct) if initial_stop_pct > 0 else 0.0
        profit_given_back_pct = max(float(open_position.mfe_pct or 0.0) - profit_loss_pct, 0.0)

        return {
            "timestamp": exit_timestamp,
            "timestamp_exit": exit_timestamp,
            "entry_timestamp": open_position.entry_timestamp,
            "setup_name": open_position.setup_name,
            "setup_type": open_position.setup_name,
            "strategy_version": open_position.strategy_version,
            "context_timeframe": open_position.context_timeframe,
            "regime": open_position.regime,
            "regime_score": round(float(open_position.regime_score or 0.0), 4),
            "trend_state": open_position.trend_state,
            "volatility_state": open_position.volatility_state,
            "context_bias": open_position.context_bias,
            "structure_state": open_position.structure_state,
            "confirmation_state": open_position.confirmation_state,
            "signal_score": round(float(open_position.signal_score or 0.0), 4),
            "atr": round(float(open_position.atr or 0.0), 6),
            "entry_reason": open_position.entry_reason,
            "entry_quality": open_position.entry_quality,
            "entry_score": round(float(open_position.entry_score or 0.0), 4),
            "scenario_score": round(float(open_position.scenario_score or 0.0), 4),
            "rejection_reason": open_position.rejection_reason,
            "exit_reason": reason,
            "sample_type": open_position.sample_type,
            "initial_stop_price": round(float(open_position.initial_stop_loss_price), 6) if open_position.initial_stop_loss_price is not None else None,
            "initial_take_price": round(float(open_position.initial_take_profit_price), 6) if open_position.initial_take_profit_price is not None else None,
            "final_stop_price": round(float(open_position.stop_loss_price), 6) if open_position.stop_loss_price is not None else None,
            "final_take_price": round(float(open_position.take_profit_price), 6) if open_position.take_profit_price is not None else None,
            "stop_initial": round(float(open_position.initial_stop_loss_price), 6) if open_position.initial_stop_loss_price is not None else None,
            "take_initial": round(float(open_position.initial_take_profit_price), 6) if open_position.initial_take_profit_price is not None else None,
            "stop_final": round(float(open_position.stop_loss_price), 6) if open_position.stop_loss_price is not None else None,
            "take_final": round(float(open_position.take_profit_price), 6) if open_position.take_profit_price is not None else None,
            "break_even_active": int(bool(open_position.break_even_active)),
            "trailing_active": int(bool(open_position.trailing_active)),
            "protection_level": open_position.protection_level,
            "regime_exit_flag": int(bool(open_position.regime_exit_flag)),
            "structure_exit_flag": int(bool(open_position.structure_exit_flag)),
            "post_pump_protection": int(bool(open_position.post_pump_protection)),
            "mfe_pct": round(float(open_position.mfe_pct or 0.0), 4),
            "mae_pct": round(float(open_position.mae_pct or 0.0), 4),
            "max_unrealized_rr": round(float(open_position.max_unrealized_rr or 0.0), 4),
            "risk_mode": open_position.risk_mode,
            "risk_amount": round(float(open_position.risk_amount or 0.0), 4),
            "position_notional": round(float(open_position.notional or 0.0), 4),
            "position_size": round(float(open_position.quantity or 0.0), 6),
            "quantity": round(float(open_position.quantity or 0.0), 6),
            "size_reduced": int(bool(open_position.size_reduced)),
            "risk_reason": open_position.risk_reason,
            "holding_time_minutes": round(float(holding_minutes), 2),
            "holding_candles": int(open_position.age_candles or 0),
            "entry_price": round(open_position.entry_price, 6),
            "price": round(exit_price, 6),
            "pnl_pct": round(profit_loss_pct, 4),
            "pnl_abs": round(total_trade_pnl, 4),
            "profit_loss_pct": round(profit_loss_pct, 4),
            "profit_loss": round(total_trade_pnl, 4),
            "rr_realized": round(float(rr_realized or 0.0), 4),
            "profit_given_back_pct": round(float(profit_given_back_pct or 0.0), 4),
            "regime_shift_during_trade": int(bool(open_position.regime_exit_flag)),
            "signal": open_position.signal,
            "side": open_position.side,
            "reason": reason,
            "net_pnl": round(net_pnl, 4),
            "notes": list(open_position.notes or []),
        }

    def _calculate_unrealized_pnl(self, open_position: Position, mark_price: float) -> float:
        if open_position.side == "long":
            return open_position.quantity * (mark_price - open_position.entry_price)
        return open_position.quantity * (open_position.entry_price - mark_price)

    def _is_opposite_signal(self, position_side: str, signal: str) -> bool:
        if position_side == "long":
            return signal in SHORT_SIGNALS
        return signal in LONG_SIGNALS

    def _should_force_opposite_exit(
        self,
        position_side: str,
        signal_pipeline: Dict[str, object],
        analytical_signal: str,
    ) -> bool:
        # Avoid premature exits from weak opposite signals in noisy regimes.
        opposite_strong_signal = "VENDA" if position_side == "long" else "COMPRA"
        if str(analytical_signal or "") != opposite_strong_signal:
            return False

        decision = signal_pipeline.get("trade_decision") or {}
        scenario = signal_pipeline.get("scenario_evaluation") or {}
        confirmation = signal_pipeline.get("confirmation_evaluation") or {}
        structure = signal_pipeline.get("structure_evaluation") or {}

        confidence = float(decision.get("confidence", 0.0) or 0.0)
        scenario_score = float(scenario.get("scenario_score", 0.0) or 0.0)
        confirmation_state = str(confirmation.get("confirmation_state") or "weak")
        structure_state = str(structure.get("structure_state") or "weak_structure")

        return (
            confidence >= 6.2
            and scenario_score >= 5.8
            and confirmation_state in {"confirmed", "mixed"}
            and structure_state in {"continuation", "pullback", "breakout"}
        )

    def _annualization_factor(self, timeframe: str) -> float:
        candles_per_year = {
            "1m": 525_600,
            "3m": 175_200,
            "5m": 105_120,
            "15m": 35_040,
            "30m": 17_520,
            "1h": 8_760,
            "2h": 4_380,
            "4h": 2_190,
            "6h": 1_460,
            "8h": 1_095,
            "12h": 730,
            "1d": 365,
        }
        return np.sqrt(candles_per_year.get(timeframe, 365))

    def _calculate_validation_split_date(
        self,
        start_date: datetime,
        end_date: datetime,
        validation_split_pct: float,
    ) -> Optional[pd.Timestamp]:
        if validation_split_pct <= 0:
            return None

        total_seconds = (pd.Timestamp(end_date) - pd.Timestamp(start_date)).total_seconds()
        if total_seconds <= 0:
            return None

        in_sample_seconds = total_seconds * (1 - validation_split_pct)
        return pd.Timestamp(start_date) + pd.to_timedelta(in_sample_seconds, unit="s")

    def _build_validation_results(
        self,
        symbol: str,
        df: pd.DataFrame,
        context_df: Optional[pd.DataFrame],
        timeframe: str,
        context_timeframe: Optional[str],
        start_date: datetime,
        end_date: datetime,
        initial_balance: float,
        stop_loss_pct: float,
        take_profit_pct: float,
        fee_rate: float,
        slippage: float,
        position_size_pct: float,
        require_volume: bool,
        require_trend: bool,
        avoid_ranging: bool,
        validation_split_pct: float,
        allowed_execution_setups: Optional[Set[str]],
    ) -> Optional[Dict]:
        split_date = self._calculate_validation_split_date(start_date, end_date, validation_split_pct)
        if split_date is None:
            return None
        out_of_sample_start = split_date + pd.to_timedelta(self._timeframe_to_milliseconds(timeframe), unit="ms")
        if out_of_sample_start >= pd.Timestamp(end_date):
            return None

        try:
            in_sample_trades, in_sample_portfolio, in_sample_balance, in_sample_signal_pipeline, in_sample_risk_engine, in_sample_signal_audit = self._run_simulation(
                symbol=symbol,
                df=df,
                context_df=context_df,
                timeframe=timeframe,
                context_timeframe=context_timeframe,
                start_date=start_date,
                end_date=split_date.to_pydatetime(),
                initial_balance=initial_balance,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
                fee_rate=fee_rate,
                slippage=slippage,
                position_size_pct=position_size_pct,
                require_volume=require_volume,
                require_trend=require_trend,
                avoid_ranging=avoid_ranging,
                strategy_version=None,
                setup_name=None,
                sample_type="in_sample",
                allowed_execution_setups=allowed_execution_setups,
            )
            out_sample_trades, out_sample_portfolio, out_sample_balance, out_sample_signal_pipeline, out_sample_risk_engine, out_sample_signal_audit = self._run_simulation(
                symbol=symbol,
                df=df,
                context_df=context_df,
                timeframe=timeframe,
                context_timeframe=context_timeframe,
                start_date=out_of_sample_start.to_pydatetime(),
                end_date=end_date,
                initial_balance=initial_balance,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
                fee_rate=fee_rate,
                slippage=slippage,
                position_size_pct=position_size_pct,
                require_volume=require_volume,
                require_trend=require_trend,
                avoid_ranging=avoid_ranging,
                strategy_version=None,
                setup_name=None,
                sample_type="out_of_sample",
                allowed_execution_setups=allowed_execution_setups,
            )
        except ValueError:
            logger.info("Periodo insuficiente para validacao fora da amostra; split ignorado")
            return None

        in_sample_stats = self._build_stats(
            initial_balance=initial_balance,
            final_balance=in_sample_balance,
            timeframe=timeframe,
            trade_history=in_sample_trades,
            portfolio_history=in_sample_portfolio,
        )
        out_sample_stats = self._build_stats(
            initial_balance=initial_balance,
            final_balance=out_sample_balance,
            timeframe=timeframe,
            trade_history=out_sample_trades,
            portfolio_history=out_sample_portfolio,
        )

        oos_passed = (
            out_sample_stats["total_trades"] > 0
            and out_sample_stats["total_return_pct"] > 0
            and out_sample_stats["profit_factor"] >= 1.2
        )

        return {
            "split_pct": round(validation_split_pct * 100, 2),
            "split_date": split_date,
            "out_of_sample_start": out_of_sample_start,
            "in_sample": {
                "stats": in_sample_stats,
                "trades": in_sample_trades,
                "portfolio_values": in_sample_portfolio,
                "signal_pipeline_stats": in_sample_signal_pipeline,
                "risk_engine_summary": in_sample_risk_engine,
                "signal_audit_summary": self._build_signal_audit_summary(in_sample_signal_audit),
            },
            "out_of_sample": {
                "stats": out_sample_stats,
                "trades": out_sample_trades,
                "portfolio_values": out_sample_portfolio,
                "signal_pipeline_stats": out_sample_signal_pipeline,
                "risk_engine_summary": out_sample_risk_engine,
                "signal_audit_summary": self._build_signal_audit_summary(out_sample_signal_audit),
            },
            "oos_passed": oos_passed,
        }

    def _build_walk_forward_results(
        self,
        symbol: str,
        df: pd.DataFrame,
        context_df: Optional[pd.DataFrame],
        timeframe: str,
        context_timeframe: Optional[str],
        start_date: datetime,
        end_date: datetime,
        initial_balance: float,
        stop_loss_pct: float,
        take_profit_pct: float,
        fee_rate: float,
        slippage: float,
        position_size_pct: float,
        require_volume: bool,
        require_trend: bool,
        avoid_ranging: bool,
        walk_forward_windows: int,
        allowed_execution_setups: Optional[Set[str]],
    ) -> Optional[Dict]:
        if walk_forward_windows <= 0:
            return None

        total_seconds = (pd.Timestamp(end_date) - pd.Timestamp(start_date)).total_seconds()
        if total_seconds <= 0:
            return None

        window_seconds = total_seconds / (walk_forward_windows + 1)
        timeframe_delta = pd.to_timedelta(self._timeframe_to_milliseconds(timeframe), unit="ms")
        windows = []

        for window_index in range(1, walk_forward_windows + 1):
            in_sample_end = pd.Timestamp(start_date) + pd.to_timedelta(window_seconds * window_index, unit="s")
            out_of_sample_start = in_sample_end + timeframe_delta
            out_of_sample_end = (
                pd.Timestamp(start_date) + pd.to_timedelta(window_seconds * (window_index + 1), unit="s")
                if window_index < walk_forward_windows
                else pd.Timestamp(end_date)
            )
            if out_of_sample_start >= out_of_sample_end:
                continue

            try:
                in_sample_trades, in_sample_portfolio, in_sample_balance, in_sample_signal_pipeline, in_sample_risk_engine, in_sample_signal_audit = self._run_simulation(
                    symbol=symbol,
                    df=df,
                    context_df=context_df,
                    timeframe=timeframe,
                    context_timeframe=context_timeframe,
                    start_date=start_date,
                    end_date=in_sample_end.to_pydatetime(),
                    initial_balance=initial_balance,
                    stop_loss_pct=stop_loss_pct,
                    take_profit_pct=take_profit_pct,
                    fee_rate=fee_rate,
                    slippage=slippage,
                    position_size_pct=position_size_pct,
                    require_volume=require_volume,
                    require_trend=require_trend,
                    avoid_ranging=avoid_ranging,
                    strategy_version=None,
                    setup_name=None,
                    sample_type="walk_forward_in_sample",
                    allowed_execution_setups=allowed_execution_setups,
                )
                out_sample_trades, out_sample_portfolio, out_sample_balance, out_sample_signal_pipeline, out_sample_risk_engine, out_sample_signal_audit = self._run_simulation(
                    symbol=symbol,
                    df=df,
                    context_df=context_df,
                    timeframe=timeframe,
                    context_timeframe=context_timeframe,
                    start_date=out_of_sample_start.to_pydatetime(),
                    end_date=out_of_sample_end.to_pydatetime(),
                    initial_balance=initial_balance,
                    stop_loss_pct=stop_loss_pct,
                    take_profit_pct=take_profit_pct,
                    fee_rate=fee_rate,
                    slippage=slippage,
                    position_size_pct=position_size_pct,
                    require_volume=require_volume,
                    require_trend=require_trend,
                    avoid_ranging=avoid_ranging,
                    strategy_version=None,
                    setup_name=None,
                    sample_type="walk_forward_out_of_sample",
                    allowed_execution_setups=allowed_execution_setups,
                )
            except ValueError:
                logger.info("Janela walk-forward %s ignorada por dados insuficientes", window_index)
                continue

            in_sample_stats = self._build_stats(
                initial_balance=initial_balance,
                final_balance=in_sample_balance,
                timeframe=timeframe,
                trade_history=in_sample_trades,
                portfolio_history=in_sample_portfolio,
            )
            out_sample_stats = self._build_stats(
                initial_balance=initial_balance,
                final_balance=out_sample_balance,
                timeframe=timeframe,
                trade_history=out_sample_trades,
                portfolio_history=out_sample_portfolio,
            )
            passed = (
                out_sample_stats["total_trades"] > 0
                and out_sample_stats["total_return_pct"] > 0
                and out_sample_stats["profit_factor"] >= 1.2
            )
            windows.append(
                {
                    "window_index": window_index,
                    "in_sample_start": pd.Timestamp(start_date),
                    "in_sample_end": in_sample_end,
                    "out_of_sample_start": out_of_sample_start,
                    "out_of_sample_end": out_of_sample_end,
                    "in_sample": {
                        "stats": in_sample_stats,
                        "signal_pipeline_stats": in_sample_signal_pipeline,
                        "risk_engine_summary": in_sample_risk_engine,
                        "signal_audit_summary": self._build_signal_audit_summary(in_sample_signal_audit),
                    },
                    "out_of_sample": {
                        "stats": out_sample_stats,
                        "signal_pipeline_stats": out_sample_signal_pipeline,
                        "risk_engine_summary": out_sample_risk_engine,
                        "signal_audit_summary": self._build_signal_audit_summary(out_sample_signal_audit),
                    },
                    "passed": passed,
                }
            )

        if not windows:
            return None

        total_windows = len(windows)
        passed_windows = sum(1 for window in windows if window["passed"])
        avg_oos_return_pct = float(np.mean([w["out_of_sample"]["stats"]["total_return_pct"] for w in windows]))
        avg_oos_profit_factor = float(np.mean([w["out_of_sample"]["stats"]["profit_factor"] for w in windows]))
        avg_oos_expectancy_pct = float(np.mean([w["out_of_sample"]["stats"]["expectancy_pct"] for w in windows]))
        pass_rate_pct = (passed_windows / total_windows) * 100
        overall_passed = (
            pass_rate_pct >= 60
            and avg_oos_return_pct > 0
            and avg_oos_profit_factor >= 1.2
        )

        return {
            "total_windows": total_windows,
            "passed_windows": passed_windows,
            "pass_rate_pct": round(pass_rate_pct, 2),
            "avg_oos_return_pct": round(avg_oos_return_pct, 2),
            "avg_oos_profit_factor": round(avg_oos_profit_factor, 2),
            "avg_oos_expectancy_pct": round(avg_oos_expectancy_pct, 2),
            "overall_passed": overall_passed,
            "windows": windows,
        }

    def _persist_backtest_run(
        self,
        symbol: str,
        timeframe: str,
        context_timeframe: Optional[str],
        start_date: datetime,
        end_date: datetime,
        stats: Dict,
        rsi_period: int,
        rsi_min: int,
        rsi_max: int,
        strategy_version: str,
        stop_loss_pct: float,
        take_profit_pct: float,
        fee_rate: float,
        slippage: float,
        position_size_pct: float,
        require_volume: bool,
        require_trend: bool,
        avoid_ranging: bool,
        validation: Optional[Dict],
        walk_forward: Optional[Dict],
    ) -> Optional[int]:
        if self.database is None:
            return None

        run_data = {
            "symbol": symbol,
            "timeframe": timeframe,
            "context_timeframe": context_timeframe,
            "strategy_version": strategy_version,
            "start_date": pd.Timestamp(start_date).isoformat(),
            "end_date": pd.Timestamp(end_date).isoformat(),
            "initial_balance": stats["initial_balance"],
            "final_balance": stats["final_balance"],
            "net_profit": stats["net_profit"],
            "total_return_pct": stats["total_return_pct"],
            "total_trades": stats["total_trades"],
            "winning_trades": stats["winning_trades"],
            "losing_trades": stats["losing_trades"],
            "win_rate": stats["win_rate"],
            "max_drawdown": stats["max_drawdown"],
            "sharpe_ratio": stats["sharpe_ratio"],
            "profit_factor": stats["profit_factor"],
            "avg_profit": stats["avg_profit"],
            "avg_loss": stats["avg_loss"],
            "expectancy_pct": stats["expectancy_pct"],
            "rsi_period": rsi_period,
            "rsi_min": rsi_min,
            "rsi_max": rsi_max,
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
            "fee_rate": fee_rate,
            "slippage": slippage,
            "position_size_pct": position_size_pct,
            "require_volume": require_volume,
            "require_trend": require_trend,
            "avoid_ranging": avoid_ranging,
            "validation_split_pct": validation["split_pct"] if validation else 0.0,
            "in_sample_end": validation["split_date"].isoformat() if validation else None,
            "out_of_sample_start": validation["out_of_sample_start"].isoformat() if validation else None,
            "in_sample_return_pct": validation["in_sample"]["stats"]["total_return_pct"] if validation else 0.0,
            "in_sample_profit_factor": validation["in_sample"]["stats"]["profit_factor"] if validation else 0.0,
            "in_sample_win_rate": validation["in_sample"]["stats"]["win_rate"] if validation else 0.0,
            "in_sample_total_trades": validation["in_sample"]["stats"]["total_trades"] if validation else 0,
            "out_of_sample_return_pct": validation["out_of_sample"]["stats"]["total_return_pct"] if validation else 0.0,
            "out_of_sample_profit_factor": validation["out_of_sample"]["stats"]["profit_factor"] if validation else 0.0,
            "out_of_sample_win_rate": validation["out_of_sample"]["stats"]["win_rate"] if validation else 0.0,
            "out_of_sample_total_trades": validation["out_of_sample"]["stats"]["total_trades"] if validation else 0,
            "out_of_sample_expectancy_pct": validation["out_of_sample"]["stats"]["expectancy_pct"] if validation else 0.0,
            "out_of_sample_passed": validation["oos_passed"] if validation else False,
            "walk_forward_windows": walk_forward["total_windows"] if walk_forward else 0,
            "walk_forward_passed": walk_forward["overall_passed"] if walk_forward else False,
            "walk_forward_pass_rate_pct": walk_forward["pass_rate_pct"] if walk_forward else 0.0,
            "walk_forward_avg_oos_return_pct": walk_forward["avg_oos_return_pct"] if walk_forward else 0.0,
            "walk_forward_avg_oos_profit_factor": walk_forward["avg_oos_profit_factor"] if walk_forward else 0.0,
            "walk_forward_avg_oos_expectancy_pct": walk_forward["avg_oos_expectancy_pct"] if walk_forward else 0.0,
        }

        try:
            return self.database.save_backtest_result(
                run_data,
                self._trade_history,
                trade_analytics=self._trade_history,
                signal_audit=self._signal_audit_log,
            )
        except Exception as exc:
            logger.warning("Falha ao persistir resultado do backtest: %s", exc)
            return None

    def _build_group_breakdown(
        self,
        trade_df: pd.DataFrame,
        group_column: str,
        key_name: str,
    ) -> List[Dict[str, object]]:
        if trade_df.empty or group_column not in trade_df.columns:
            return []

        grouped = trade_df.groupby(trade_df[group_column].fillna("unknown"))
        breakdown = []
        for group_name, group in grouped:
            group_total = len(group)
            group_wins = int((group["profit_loss"] > 0).sum())
            group_losses = int((group["profit_loss"] <= 0).sum())
            group_gross_profit = float(group.loc[group["profit_loss"] > 0, "profit_loss"].sum())
            group_gross_loss = float(group.loc[group["profit_loss"] < 0, "profit_loss"].sum())
            group_profit_factor = (
                group_gross_profit / abs(group_gross_loss)
                if group_gross_loss < 0
                else (group_gross_profit if group_gross_profit > 0 else 0.0)
            )
            breakdown.append(
                {
                    key_name: group_name,
                    "total_trades": group_total,
                    "win_rate": round((group_wins / group_total) * 100, 2) if group_total else 0.0,
                    "profit_factor": round(float(group_profit_factor), 2),
                    "net_profit": round(float(group["profit_loss"].sum()), 2),
                    "total_result_pct": round(float(group["profit_loss_pct"].sum()), 2),
                    "avg_result_pct": round(float(group["profit_loss_pct"].mean()), 2) if group_total else 0.0,
                    "winning_trades": group_wins,
                    "losing_trades": group_losses,
                    "avg_mfe_pct": round(float(group["mfe_pct"].mean()), 2) if "mfe_pct" in group.columns else 0.0,
                    "avg_mae_pct": round(float(group["mae_pct"].mean()), 2) if "mae_pct" in group.columns else 0.0,
                }
            )
        breakdown.sort(key=lambda item: item["total_trades"], reverse=True)
        return breakdown

    def _build_time_breakdowns(self, trade_df: pd.DataFrame) -> Dict[str, List[Dict[str, object]]]:
        if trade_df.empty or "entry_timestamp" not in trade_df.columns:
            return {"hour_of_day_breakdown": [], "day_of_week_breakdown": [], "holding_time_breakdown": []}

        df = trade_df.copy()
        df["entry_timestamp"] = pd.to_datetime(df["entry_timestamp"], errors="coerce")
        df["hour_of_day"] = df["entry_timestamp"].dt.hour.fillna(-1).astype(int)
        df["day_of_week"] = df["entry_timestamp"].dt.day_name().fillna("Unknown")
        holding_minutes = df.get("holding_time_minutes", pd.Series([0.0] * len(df)))
        df["holding_bucket"] = pd.cut(
            holding_minutes.astype(float),
            bins=[-0.01, 60, 240, 720, float("inf")],
            labels=["<=1h", "1h-4h", "4h-12h", ">12h"],
        ).astype(str)
        return {
            "hour_of_day_breakdown": self._build_group_breakdown(df, "hour_of_day", "hour_of_day"),
            "day_of_week_breakdown": self._build_group_breakdown(df, "day_of_week", "day_of_week"),
            "holding_time_breakdown": self._build_group_breakdown(df, "holding_bucket", "holding_bucket"),
        }

    def _build_equity_diagnostics(self, portfolio_df: pd.DataFrame, initial_balance: float) -> Dict[str, object]:
        if portfolio_df.empty or "portfolio_value" not in portfolio_df.columns:
            return {
                "gross_profit": 0.0,
                "gross_loss": 0.0,
                "average_win": 0.0,
                "average_loss": 0.0,
                "payoff_ratio": 0.0,
                "average_drawdown_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "max_recovery_periods": 0,
                "profit_giveback_pct": 0.0,
            }

        portfolio_series = portfolio_df["portfolio_value"].astype(float).reset_index(drop=True)
        running_max = portfolio_series.cummax()
        drawdowns = ((running_max - portfolio_series) / running_max.replace(0, np.nan)) * 100
        drawdowns = drawdowns.fillna(0.0)

        profit_curve = portfolio_series - float(initial_balance or 0.0)
        running_profit_peak = profit_curve.cummax()
        giveback_pct = np.where(
            running_profit_peak > 0,
            ((running_profit_peak - profit_curve) / running_profit_peak) * 100.0,
            0.0,
        )

        max_recovery_periods = 0
        current_recovery = 0
        last_peak = portfolio_series.iloc[0]
        for value in portfolio_series:
            if value >= last_peak:
                last_peak = value
                current_recovery = 0
            else:
                current_recovery += 1
                max_recovery_periods = max(max_recovery_periods, current_recovery)

        return {
            "average_drawdown_pct": round(float(drawdowns[drawdowns > 0].mean()) if (drawdowns > 0).any() else 0.0, 2),
            "max_drawdown_pct": round(float(drawdowns.max()), 2),
            "max_recovery_periods": int(max_recovery_periods),
            "profit_giveback_pct": round(float(np.max(giveback_pct)) if len(giveback_pct) else 0.0, 2),
        }

    def _build_stats(
        self,
        initial_balance: float,
        final_balance: float,
        timeframe: str,
        trade_history: Optional[List[Dict]] = None,
        portfolio_history: Optional[List[Dict]] = None,
    ) -> Dict:
        trade_df = pd.DataFrame(trade_history if trade_history is not None else self._trade_history)
        portfolio_df = pd.DataFrame(portfolio_history if portfolio_history is not None else self._portfolio_history)

        total_trades = len(trade_df)
        winning_trades = int((trade_df["profit_loss"] > 0).sum()) if total_trades else 0
        losing_trades = int((trade_df["profit_loss"] <= 0).sum()) if total_trades else 0
        win_rate = (winning_trades / total_trades * 100) if total_trades else 0.0

        net_profit = final_balance - initial_balance
        total_return_pct = ((final_balance - initial_balance) / initial_balance * 100) if initial_balance else 0.0

        if not portfolio_df.empty:
            portfolio_series = portfolio_df["portfolio_value"].astype(float)
            running_max = portfolio_series.cummax()
            drawdowns = ((running_max - portfolio_series) / running_max.replace(0, np.nan)) * 100
            max_drawdown = float(drawdowns.fillna(0).max())

            returns = portfolio_series.pct_change().dropna()
            if returns.empty or returns.std() == 0:
                sharpe_ratio = 0.0
            else:
                sharpe_ratio = float((returns.mean() / returns.std()) * self._annualization_factor(timeframe))
        else:
            max_drawdown = 0.0
            sharpe_ratio = 0.0

        if total_trades:
            gross_profit = float(trade_df.loc[trade_df["profit_loss"] > 0, "profit_loss"].sum())
            gross_loss = float(trade_df.loc[trade_df["profit_loss"] < 0, "profit_loss"].sum())
            profit_factor = gross_profit / abs(gross_loss) if gross_loss < 0 else (gross_profit if gross_profit > 0 else 0.0)
            avg_profit = float(trade_df.loc[trade_df["profit_loss"] > 0, "profit_loss_pct"].mean()) if winning_trades else 0.0
            avg_loss = abs(float(trade_df.loc[trade_df["profit_loss"] < 0, "profit_loss_pct"].mean())) if losing_trades else 0.0
            win_rate_fraction = winning_trades / total_trades
            expectancy_pct = (win_rate_fraction * avg_profit) - ((1 - win_rate_fraction) * avg_loss)
            avg_win_abs = float(trade_df.loc[trade_df["profit_loss"] > 0, "profit_loss"].mean()) if winning_trades else 0.0
            avg_loss_abs = abs(float(trade_df.loc[trade_df["profit_loss"] < 0, "profit_loss"].mean())) if losing_trades else 0.0
            payoff_ratio = (avg_win_abs / avg_loss_abs) if avg_loss_abs > 0 else (avg_win_abs if avg_win_abs > 0 else 0.0)
        else:
            gross_profit = 0.0
            gross_loss = 0.0
            profit_factor = 0.0
            avg_profit = 0.0
            avg_loss = 0.0
            expectancy_pct = 0.0
            avg_win_abs = 0.0
            avg_loss_abs = 0.0
            payoff_ratio = 0.0

        regime_breakdown = self._build_group_breakdown(trade_df, "regime", "regime")
        setup_type_breakdown = self._build_group_breakdown(trade_df, "setup_name", "setup_type")
        exit_type_breakdown = self._build_group_breakdown(trade_df.rename(columns={"exit_reason": "exit_reason_group"}), "exit_reason_group", "exit_reason")
        entry_quality_breakdown = self._build_group_breakdown(trade_df, "entry_quality", "entry_quality")
        risk_mode_breakdown = self._build_group_breakdown(trade_df, "risk_mode", "risk_mode")

        exit_reason_counts = {}
        if total_trades:
            exit_reasons = trade_df.get("exit_reason", trade_df.get("reason"))
            if exit_reasons is not None:
                exit_reason_counts = {
                    str(reason): int(count)
                    for reason, count in exit_reasons.fillna("UNKNOWN").value_counts().items()
                }

        break_even_activated_count = int(trade_df["break_even_active"].fillna(0).astype(int).sum()) if total_trades and "break_even_active" in trade_df.columns else 0
        trailing_activated_count = int(trade_df["trailing_active"].fillna(0).astype(int).sum()) if total_trades and "trailing_active" in trade_df.columns else 0
        post_pump_protection_count = int(trade_df["post_pump_protection"].fillna(0).astype(int).sum()) if total_trades and "post_pump_protection" in trade_df.columns else 0
        structure_exit_count = int((trade_df.get("exit_reason", pd.Series(dtype=str)) == "STRUCTURE_FAILURE").sum()) if total_trades else 0
        regime_exit_count = int((trade_df.get("exit_reason", pd.Series(dtype=str)) == "REGIME_SHIFT").sum()) if total_trades else 0
        avg_mfe_pct = round(float(trade_df["mfe_pct"].mean()), 2) if total_trades and "mfe_pct" in trade_df.columns else 0.0
        avg_mae_pct = round(float(trade_df["mae_pct"].mean()), 2) if total_trades and "mae_pct" in trade_df.columns else 0.0
        avg_rr_realized = round(float(trade_df["rr_realized"].mean()), 2) if total_trades and "rr_realized" in trade_df.columns else 0.0
        avg_profit_given_back_pct = (
            round(float(trade_df["profit_given_back_pct"].mean()), 2)
            if total_trades and "profit_given_back_pct" in trade_df.columns
            else 0.0
        )
        max_consecutive_wins = 0
        max_consecutive_losses = 0
        current_wins = 0
        current_losses = 0
        for pnl in trade_df.get("profit_loss", pd.Series(dtype=float)).tolist():
            if pnl > 0:
                current_wins += 1
                current_losses = 0
            elif pnl < 0:
                current_losses += 1
                current_wins = 0
            else:
                current_wins = 0
                current_losses = 0
            max_consecutive_wins = max(max_consecutive_wins, current_wins)
            max_consecutive_losses = max(max_consecutive_losses, current_losses)
        time_breakdowns = self._build_time_breakdowns(trade_df)
        equity_diagnostics = self._build_equity_diagnostics(portfolio_df, initial_balance)

        return {
            "initial_balance": round(initial_balance, 2),
            "final_balance": round(final_balance, 2),
            "net_profit": round(net_profit, 2),
            "total_return_pct": round(total_return_pct, 2),
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": round(win_rate, 2),
            "max_drawdown": round(max_drawdown, 2),
            "sharpe_ratio": round(sharpe_ratio, 2),
            "profit_factor": round(float(profit_factor), 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(abs(gross_loss), 2),
            "avg_profit": round(avg_profit, 2),
            "avg_loss": round(avg_loss, 2),
            "average_win_abs": round(avg_win_abs, 2),
            "average_loss_abs": round(avg_loss_abs, 2),
            "payoff_ratio": round(float(payoff_ratio), 2),
            "expectancy_pct": round(expectancy_pct, 2),
            "regime_breakdown": regime_breakdown,
            "setup_type_breakdown": setup_type_breakdown,
            "exit_reason_counts": exit_reason_counts,
            "exit_type_breakdown": exit_type_breakdown,
            "entry_quality_breakdown": entry_quality_breakdown,
            "risk_mode_breakdown": risk_mode_breakdown,
            "break_even_activated_count": break_even_activated_count,
            "trailing_activated_count": trailing_activated_count,
            "post_pump_protection_count": post_pump_protection_count,
            "structure_exit_count": structure_exit_count,
            "regime_exit_count": regime_exit_count,
            "avg_mfe_pct": avg_mfe_pct,
            "avg_mae_pct": avg_mae_pct,
            "avg_rr_realized": avg_rr_realized,
            "avg_profit_given_back_pct": avg_profit_given_back_pct,
            "max_consecutive_wins": max_consecutive_wins,
            "max_consecutive_losses": max_consecutive_losses,
            **time_breakdowns,
            "equity_diagnostics": equity_diagnostics,
        }
