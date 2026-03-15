import logging
from typing import Dict, Optional

from config import ProductionConfig
from database.database import db as runtime_db

logger = logging.getLogger(__name__)


class RiskManagementService:
    def __init__(self, database=None):
        self.database = database or runtime_db

    def build_trade_plan(
        self,
        entry_price: float,
        stop_loss_pct: float,
        symbol: str = None,
        timeframe: str = None,
        strategy_version: str = None,
        account_balance: Optional[float] = None,
        risk_per_trade_pct: Optional[float] = None,
        max_open_trades: Optional[int] = None,
        max_portfolio_open_risk_pct: Optional[float] = None,
    ) -> Dict:
        resolved_account_balance = float(account_balance or ProductionConfig.PAPER_ACCOUNT_BALANCE)
        resolved_risk_per_trade_pct = float(risk_per_trade_pct or ProductionConfig.RISK_PER_TRADE_PCT)
        resolved_max_open_trades = int(max_open_trades or ProductionConfig.MAX_OPEN_PAPER_TRADES)
        resolved_max_portfolio_open_risk_pct = float(
            max_portfolio_open_risk_pct or ProductionConfig.MAX_PORTFOLIO_OPEN_RISK_PCT
        )

        normalized_stop_loss_pct = self._normalize_pct(stop_loss_pct)
        portfolio_summary = self.database.get_open_portfolio_risk_summary()
        open_trades = int(portfolio_summary.get("open_trades", 0) or 0)
        total_open_risk_pct = float(portfolio_summary.get("total_open_risk_pct", 0.0) or 0.0)

        if entry_price <= 0:
            return self._blocked_plan(
                "Preco de entrada invalido para calcular o plano de risco.",
                portfolio_summary,
            )

        if normalized_stop_loss_pct <= 0:
            return self._blocked_plan(
                "Setup sem stop loss valido. Operacao bloqueada por risco.",
                portfolio_summary,
            )

        if open_trades >= resolved_max_open_trades:
            return self._blocked_plan(
                f"Limite de trades abertos atingido ({open_trades}/{resolved_max_open_trades}).",
                portfolio_summary,
            )

        if total_open_risk_pct + resolved_risk_per_trade_pct > resolved_max_portfolio_open_risk_pct:
            return self._blocked_plan(
                "Risco aberto do portfolio acima do limite permitido.",
                portfolio_summary,
            )

        risk_amount = resolved_account_balance * (resolved_risk_per_trade_pct / 100)
        position_notional = risk_amount / normalized_stop_loss_pct
        quantity = position_notional / float(entry_price)
        stop_loss_price = entry_price * (1 - normalized_stop_loss_pct)

        return {
            "allowed": True,
            "reason": "",
            "symbol": symbol,
            "timeframe": timeframe,
            "strategy_version": strategy_version,
            "account_reference_balance": round(resolved_account_balance, 2),
            "risk_per_trade_pct": round(resolved_risk_per_trade_pct, 4),
            "risk_amount": round(risk_amount, 2),
            "stop_loss_pct": round(normalized_stop_loss_pct * 100, 4),
            "stop_loss_price": round(stop_loss_price, 6),
            "position_notional": round(position_notional, 2),
            "quantity": round(quantity, 6),
            "portfolio_open_trades": open_trades,
            "portfolio_open_risk_pct": round(total_open_risk_pct, 4),
            "max_open_trades": resolved_max_open_trades,
            "max_portfolio_open_risk_pct": round(resolved_max_portfolio_open_risk_pct, 4),
        }

    def get_portfolio_risk_summary(self) -> Dict:
        summary = self.database.get_open_portfolio_risk_summary()
        return {
            "open_trades": int(summary.get("open_trades", 0) or 0),
            "total_open_risk_pct": round(float(summary.get("total_open_risk_pct", 0.0) or 0.0), 4),
            "total_open_risk_amount": round(float(summary.get("total_open_risk_amount", 0.0) or 0.0), 2),
            "total_open_position_notional": round(
                float(summary.get("total_open_position_notional", 0.0) or 0.0),
                2,
            ),
            "max_open_trades": ProductionConfig.MAX_OPEN_PAPER_TRADES,
            "max_portfolio_open_risk_pct": ProductionConfig.MAX_PORTFOLIO_OPEN_RISK_PCT,
        }

    def _blocked_plan(self, reason: str, portfolio_summary: Dict) -> Dict:
        return {
            "allowed": False,
            "reason": reason,
            "portfolio_open_trades": int(portfolio_summary.get("open_trades", 0) or 0),
            "portfolio_open_risk_pct": round(float(portfolio_summary.get("total_open_risk_pct", 0.0) or 0.0), 4),
            "max_open_trades": ProductionConfig.MAX_OPEN_PAPER_TRADES,
            "max_portfolio_open_risk_pct": ProductionConfig.MAX_PORTFOLIO_OPEN_RISK_PCT,
        }

    def _normalize_pct(self, value: Optional[float]) -> float:
        raw_value = float(value or 0.0)
        return raw_value / 100 if raw_value > 1 else raw_value
