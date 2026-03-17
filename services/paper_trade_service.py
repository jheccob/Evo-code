import logging
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from config import ProductionConfig
from database.database import db as runtime_db

logger = logging.getLogger(__name__)


LONG_SIGNALS = {"COMPRA", "COMPRA_FRACA"}
SHORT_SIGNALS = {"VENDA", "VENDA_FRACA"}
ACTIONABLE_SIGNALS = LONG_SIGNALS | SHORT_SIGNALS


class PaperTradeService:
    def __init__(
        self,
        database=None,
        default_stop_loss_pct: float = 2.0,
        default_take_profit_pct: float = 4.0,
        max_hold_candles: int = 288,
        fee_rate: Optional[float] = None,
        slippage: Optional[float] = None,
    ):
        self.database = database or runtime_db
        self.default_stop_loss_pct = float(default_stop_loss_pct)
        self.default_take_profit_pct = float(default_take_profit_pct)
        self.max_hold_candles = int(max_hold_candles)
        self.fee_rate = float(ProductionConfig.PAPER_FEE_RATE if fee_rate is None else fee_rate)
        self.slippage = float(ProductionConfig.PAPER_SLIPPAGE if slippage is None else slippage)

    def register_signal(
        self,
        symbol: str,
        timeframe: str,
        signal: str,
        entry_price: float,
        entry_timestamp,
        context_timeframe: str = None,
        source: str = "system",
        strategy_version: str = None,
        stop_loss_pct: Optional[float] = None,
        take_profit_pct: Optional[float] = None,
        risk_plan: Optional[Dict] = None,
        setup_name: str = None,
        regime: str = None,
        signal_score: Optional[float] = None,
        atr: Optional[float] = None,
        entry_reason: str = None,
        sample_type: str = "paper",
    ) -> Optional[int]:
        if signal not in ACTIONABLE_SIGNALS:
            return None

        side = self._signal_to_side(signal)
        executed_entry_price = self._apply_slippage(float(entry_price), side=side, is_entry=True, slippage=self.slippage)
        stop_loss_pct = self._normalize_pct(
            self.default_stop_loss_pct if stop_loss_pct is None else stop_loss_pct
        )
        take_profit_pct = self._normalize_pct(
            self.default_take_profit_pct if take_profit_pct is None else take_profit_pct
        )
        timestamp_iso = self._normalize_timestamp(entry_timestamp)
        open_trades = self.database.get_open_paper_trades(symbol=symbol, timeframe=timeframe)

        for trade in open_trades:
            if trade["side"] == side:
                return trade["id"]

            close_result = self._build_close_result(
                trade=trade,
                exit_price=float(entry_price),
                exit_timestamp=timestamp_iso,
                close_reason="SIGNAL_FLIP",
            )
            self.database.close_paper_trade(
                trade_id=trade["id"],
                exit_timestamp=close_result["exit_timestamp"],
                exit_price=close_result["exit_price"],
                outcome=close_result["outcome"],
                close_reason=close_result["close_reason"],
                result_pct=close_result["result_pct"],
            )

        trade_data = {
            "symbol": symbol,
            "timeframe": timeframe,
            "context_timeframe": context_timeframe,
            "setup_name": setup_name or strategy_version,
            "strategy_version": strategy_version,
            "regime": regime,
            "signal_score": 0.0 if pd.isna(signal_score) else (signal_score or 0.0),
            "atr": 0.0 if pd.isna(atr) else (atr or 0.0),
            "sample_type": sample_type,
            "signal": signal,
            "side": side,
            "source": source,
            "entry_timestamp": timestamp_iso,
            "entry_reason": entry_reason or signal,
            "entry_price": executed_entry_price,
            "stop_loss_pct": stop_loss_pct * 100,
            "take_profit_pct": take_profit_pct * 100,
            "fee_rate": self.fee_rate,
            "slippage": self.slippage,
            "stop_loss_price": self._build_stop_loss_price(side, executed_entry_price, stop_loss_pct),
            "take_profit_price": self._build_take_profit_price(side, executed_entry_price, take_profit_pct),
            "planned_risk_pct": (risk_plan or {}).get("risk_per_trade_pct", 0.0),
            "planned_risk_amount": (risk_plan or {}).get("risk_amount", 0.0),
            "planned_position_notional": (risk_plan or {}).get("position_notional", 0.0),
            "planned_quantity": (risk_plan or {}).get("quantity", 0.0),
            "account_reference_balance": (risk_plan or {}).get("account_reference_balance", 0.0),
            "status": "OPEN",
            "outcome": "OPEN",
            "result_pct": 0.0,
        }
        return self.database.create_paper_trade(trade_data)

    def evaluate_open_trades(
        self,
        symbol: str,
        timeframe: str,
        market_data: pd.DataFrame,
    ) -> List[Dict]:
        if market_data is None or market_data.empty:
            return []

        market_data = market_data.sort_index()
        if "is_closed" in market_data.columns:
            closed_market_data = market_data[market_data["is_closed"].fillna(False)]
            if not closed_market_data.empty:
                market_data = closed_market_data

        open_trades = self.database.get_open_paper_trades(symbol=symbol, timeframe=timeframe)
        if not open_trades:
            return []

        closed_trades = []
        for trade in open_trades:
            entry_timestamp = pd.Timestamp(trade["entry_timestamp"])
            candles = market_data.loc[market_data.index > entry_timestamp]
            if candles.empty:
                continue

            close_result = self._evaluate_trade_against_candles(trade, candles)
            if close_result is None:
                continue

            self.database.close_paper_trade(
                trade_id=trade["id"],
                exit_timestamp=close_result["exit_timestamp"],
                exit_price=close_result["exit_price"],
                outcome=close_result["outcome"],
                close_reason=close_result["close_reason"],
                result_pct=close_result["result_pct"],
            )
            closed_trades.append({**trade, **close_result})

        return closed_trades

    def get_summary(self, symbol: str = None, timeframe: str = None) -> Dict:
        return self.database.get_paper_trade_summary(symbol=symbol, timeframe=timeframe)

    def _evaluate_trade_against_candles(self, trade: Dict, candles: pd.DataFrame) -> Optional[Dict]:
        side = trade["side"]
        stop_loss_price = trade.get("stop_loss_price")
        take_profit_price = trade.get("take_profit_price")

        for _, candle in candles.iterrows():
            low_price = float(candle["low"])
            high_price = float(candle["high"])
            exit_timestamp = self._normalize_timestamp(candle.name)

            if side == "long":
                if stop_loss_price is not None and low_price <= float(stop_loss_price):
                    return self._build_close_result(trade, float(stop_loss_price), exit_timestamp, "STOP_LOSS")
                if take_profit_price is not None and high_price >= float(take_profit_price):
                    return self._build_close_result(trade, float(take_profit_price), exit_timestamp, "TAKE_PROFIT")
            else:
                if stop_loss_price is not None and high_price >= float(stop_loss_price):
                    return self._build_close_result(trade, float(stop_loss_price), exit_timestamp, "STOP_LOSS")
                if take_profit_price is not None and low_price <= float(take_profit_price):
                    return self._build_close_result(trade, float(take_profit_price), exit_timestamp, "TAKE_PROFIT")

        if len(candles) >= self.max_hold_candles:
            return self._build_close_result(
                trade,
                float(candles.iloc[-1]["close"]),
                self._normalize_timestamp(candles.index[-1]),
                "TIME_EXIT",
            )

        return None

    def _build_close_result(self, trade: Dict, exit_price: float, exit_timestamp: str, close_reason: str) -> Dict:
        entry_price = float(trade["entry_price"])
        persisted_fee_rate = trade.get("fee_rate")
        fee_rate = self.fee_rate if persisted_fee_rate in (None, 0, 0.0) else float(persisted_fee_rate)
        persisted_slippage = trade.get("slippage")
        slippage = self.slippage if persisted_slippage in (None, 0, 0.0) else float(persisted_slippage)
        exit_price = self._apply_slippage(float(exit_price), side=trade["side"], is_entry=False, slippage=slippage)
        if trade["side"] == "long":
            gross_result_pct = ((exit_price - entry_price) / entry_price) * 100
        else:
            gross_result_pct = ((entry_price - exit_price) / entry_price) * 100

        entry_fee_pct = fee_rate * 100
        exit_fee_pct = ((exit_price / entry_price) * fee_rate * 100) if entry_price > 0 else fee_rate * 100
        result_pct = gross_result_pct - entry_fee_pct - exit_fee_pct

        if result_pct > 0:
            outcome = "WIN"
        elif result_pct < 0:
            outcome = "LOSS"
        else:
            outcome = "FLAT"

        return {
            "exit_timestamp": exit_timestamp,
            "exit_price": round(float(exit_price), 6),
            "outcome": outcome,
            "close_reason": close_reason,
            "exit_reason": close_reason,
            "result_pct": round(float(result_pct), 4),
        }

    def _apply_slippage(self, price: float, side: str, is_entry: bool, slippage: Optional[float] = None) -> float:
        effective_slippage = self.slippage if slippage is None else float(slippage)
        if effective_slippage <= 0:
            return float(price)
        if side == "long":
            return price * (1 + effective_slippage) if is_entry else price * (1 - effective_slippage)
        return price * (1 - effective_slippage) if is_entry else price * (1 + effective_slippage)

    def _signal_to_side(self, signal: str) -> str:
        return "long" if signal in LONG_SIGNALS else "short"

    def _build_stop_loss_price(self, side: str, entry_price: float, stop_loss_pct: float) -> float:
        if stop_loss_pct <= 0:
            return None
        return entry_price * (1 - stop_loss_pct if side == "long" else 1 + stop_loss_pct)

    def _build_take_profit_price(self, side: str, entry_price: float, take_profit_pct: float) -> float:
        if take_profit_pct <= 0:
            return None
        return entry_price * (1 + take_profit_pct if side == "long" else 1 - take_profit_pct)

    def _normalize_pct(self, value: float) -> float:
        raw_value = float(value or 0.0)
        return raw_value / 100 if raw_value > 1 else raw_value

    def _normalize_timestamp(self, value) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, datetime):
            return value.isoformat()
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)
