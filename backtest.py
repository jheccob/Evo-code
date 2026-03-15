from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

from database.database import build_strategy_version, db as runtime_db
from trading_bot import TradingBot

logger = logging.getLogger(__name__)


LONG_SIGNALS = {"COMPRA", "COMPRA_FRACA"}
SHORT_SIGNALS = {"VENDA", "VENDA_FRACA"}


@dataclass
class Position:
    side: str
    signal: str
    entry_timestamp: pd.Timestamp
    entry_price: float
    quantity: float
    notional: float
    entry_fee: float
    stop_loss_price: Optional[float]
    take_profit_price: Optional[float]


class BacktestEngine:
    def __init__(self, trading_bot: Optional[TradingBot] = None, database=None):
        self.trading_bot = trading_bot or TradingBot(allow_simulated_data=False)
        self.database = database or runtime_db
        self._trade_history: List[Dict] = []
        self._portfolio_history: List[Dict] = []

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
        validation_split_pct: float = 0.0,
        walk_forward_windows: int = 0,
        persist_result: bool = True,
    ) -> Dict:
        if start_date >= end_date:
            raise ValueError("Data inicial deve ser anterior a data final")

        self._trade_history = []
        self._portfolio_history = []

        normalized_stop_loss = self._normalize_strategy_pct(stop_loss_pct)
        normalized_take_profit = self._normalize_strategy_pct(take_profit_pct)
        normalized_position_size = min(max(self._normalize_position_size(position_size_pct), 0.0), 1.0)
        normalized_validation_split = min(max(self._normalize_ratio(validation_split_pct), 0.0), 0.5)
        normalized_walk_forward_windows = max(int(walk_forward_windows or 0), 0)
        strategy_version = build_strategy_version(
            symbol=symbol,
            timeframe=timeframe,
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

        return self._run_backtest_with_preloaded_df(
            df=raw_df,
            symbol=symbol,
            timeframe=timeframe,
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
        validation_split_pct: float = 0.0,
        walk_forward_windows: int = 0,
        persist_result: bool = False,
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
        strategy_version = build_strategy_version(
            symbol=symbol,
            timeframe=timeframe,
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
            symbol=symbol,
            timeframe=timeframe,
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
        symbol: str,
        timeframe: str,
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
    ) -> Dict:
        df = self.trading_bot.calculate_indicators(df.copy())
        warmup_candles = max(210, int(rsi_period) + 5)
        if len(df) <= warmup_candles + 1:
            raise ValueError("Dados insuficientes para backtest")

        self._trade_history, self._portfolio_history, final_balance = self._run_simulation(
            df=df,
            timeframe=timeframe,
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
                "strategy_version": strategy_version,
                "start_date": pd.Timestamp(start_date).isoformat(),
                "end_date": pd.Timestamp(end_date).isoformat(),
                "rsi_period": rsi_period,
                "rsi_min": rsi_min,
                "rsi_max": rsi_max,
            },
            "stats": stats,
            "trades": list(self._trade_history),
            "portfolio_values": list(self._portfolio_history),
        }
        validation = self._build_validation_results(
            df=df,
            timeframe=timeframe,
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
        )
        if validation is not None:
            results["validation"] = validation
        walk_forward = self._build_walk_forward_results(
            df=df,
            timeframe=timeframe,
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
        )
        if walk_forward is not None:
            results["walk_forward"] = walk_forward
        if persist_result:
            results["saved_run_id"] = self._persist_backtest_run(
                symbol=symbol,
                timeframe=timeframe,
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

    def _run_simulation(
        self,
        df: pd.DataFrame,
        timeframe: str,
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
    ) -> Tuple[List[Dict], List[Dict], float]:
        warmup_candles = max(210, int(getattr(self.trading_bot, "rsi_period", 14)) + 5)
        start_idx = max(warmup_candles, int(df.index.searchsorted(pd.Timestamp(start_date), side="left")))
        end_idx = min(int(df.index.searchsorted(pd.Timestamp(end_date), side="right")) - 1, len(df) - 1)

        if start_idx >= len(df) - 1 or end_idx <= start_idx:
            raise ValueError("Dados insuficientes para backtest")

        trade_history: List[Dict] = []
        portfolio_history: List[Dict] = []
        balance = float(initial_balance)
        open_position: Optional[Position] = None

        for idx in range(start_idx, end_idx):
            current_slice = df.iloc[: idx + 1]
            current_row = current_slice.iloc[-1]
            next_row = df.iloc[idx + 1]

            if open_position is not None:
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

            signal = self.trading_bot.check_signal(
                current_slice,
                timeframe=timeframe,
                require_volume=require_volume,
                require_trend=require_trend,
                avoid_ranging=avoid_ranging,
            )

            if open_position is not None and self._is_opposite_signal(open_position.side, signal):
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

            if open_position is None and signal in LONG_SIGNALS.union(SHORT_SIGNALS):
                opened = self._open_position(
                    signal=signal,
                    next_row=next_row,
                    balance=balance,
                    position_size_pct=position_size_pct,
                    fee_rate=fee_rate,
                    slippage=slippage,
                    stop_loss_pct=stop_loss_pct,
                    take_profit_pct=take_profit_pct,
                )
                if opened is not None:
                    open_position = opened
                    balance -= open_position.entry_fee

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
        return trade_history, portfolio_history, float(balance)

    def _open_position(
        self,
        signal: str,
        next_row: pd.Series,
        balance: float,
        position_size_pct: float,
        fee_rate: float,
        slippage: float,
        stop_loss_pct: float,
        take_profit_pct: float,
    ) -> Optional[Position]:
        if balance <= 0 or position_size_pct <= 0:
            return None

        side = "long" if signal in LONG_SIGNALS else "short"
        raw_entry_price = float(next_row["open"])
        entry_price = self._apply_slippage(raw_entry_price, side=side, is_entry=True, slippage=slippage)
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

        return Position(
            side=side,
            signal=signal,
            entry_timestamp=pd.Timestamp(next_row.name),
            entry_price=entry_price,
            quantity=quantity,
            notional=notional,
            entry_fee=notional * fee_rate,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
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

        return {
            "timestamp": exit_timestamp,
            "entry_timestamp": open_position.entry_timestamp,
            "entry_price": round(open_position.entry_price, 6),
            "price": round(exit_price, 6),
            "profit_loss_pct": round(profit_loss_pct, 4),
            "profit_loss": round(total_trade_pnl, 4),
            "signal": open_position.signal,
            "side": open_position.side,
            "reason": reason,
            "net_pnl": round(net_pnl, 4),
        }

    def _calculate_unrealized_pnl(self, open_position: Position, mark_price: float) -> float:
        if open_position.side == "long":
            return open_position.quantity * (mark_price - open_position.entry_price)
        return open_position.quantity * (open_position.entry_price - mark_price)

    def _is_opposite_signal(self, position_side: str, signal: str) -> bool:
        if position_side == "long":
            return signal in SHORT_SIGNALS
        return signal in LONG_SIGNALS

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
        df: pd.DataFrame,
        timeframe: str,
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
    ) -> Optional[Dict]:
        split_date = self._calculate_validation_split_date(start_date, end_date, validation_split_pct)
        if split_date is None:
            return None
        out_of_sample_start = split_date + pd.to_timedelta(self._timeframe_to_milliseconds(timeframe), unit="ms")
        if out_of_sample_start >= pd.Timestamp(end_date):
            return None

        try:
            in_sample_trades, in_sample_portfolio, in_sample_balance = self._run_simulation(
                df=df,
                timeframe=timeframe,
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
            )
            out_sample_trades, out_sample_portfolio, out_sample_balance = self._run_simulation(
                df=df,
                timeframe=timeframe,
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
            },
            "out_of_sample": {
                "stats": out_sample_stats,
                "trades": out_sample_trades,
                "portfolio_values": out_sample_portfolio,
            },
            "oos_passed": oos_passed,
        }

    def _build_walk_forward_results(
        self,
        df: pd.DataFrame,
        timeframe: str,
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
                in_sample_trades, in_sample_portfolio, in_sample_balance = self._run_simulation(
                    df=df,
                    timeframe=timeframe,
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
                )
                out_sample_trades, out_sample_portfolio, out_sample_balance = self._run_simulation(
                    df=df,
                    timeframe=timeframe,
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
                    "in_sample": {"stats": in_sample_stats},
                    "out_of_sample": {"stats": out_sample_stats},
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
            return self.database.save_backtest_result(run_data, self._trade_history)
        except Exception as exc:
            logger.warning("Falha ao persistir resultado do backtest: %s", exc)
            return None

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
        else:
            profit_factor = 0.0
            avg_profit = 0.0
            avg_loss = 0.0
            expectancy_pct = 0.0

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
            "avg_profit": round(avg_profit, 2),
            "avg_loss": round(avg_loss, 2),
            "expectancy_pct": round(expectancy_pct, 2),
        }
