import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time
import os
from datetime import datetime, timedelta, date
import asyncio
import hmac
import logging

# Importar funções de fuso horário brasileiro
from utils.timezone_utils import now_brazil, format_brazil_time, get_brazil_datetime_naive, BRAZIL_TZ

# Importar banco de dados
from database.database import build_strategy_version, db
from trading_bot import TradingBot
from config import AppConfig, ExchangeConfig, ProductionConfig

# Importar serviço seguro do Telegram
try:
    from services.telegram_service import SecureTelegramService, TELEGRAM_AVAILABLE
except ImportError:
    # Fallback se o módulo não existir
    class SecureTelegramService:
        def __init__(self):
            self._configured = False
        def is_configured(self):
            return False
        def get_config_status(self):
            return {'configured': False}
        def configure(self, bot_token: str, chat_id: str):
            return False, "❌ Telegram não disponível"
        def disable(self):
            pass
        async def test_connection(self):
            return False, "❌ Telegram não disponível"
        async def send_signal_alert(self, symbol: str, signal: str, price: float, rsi: float, macd: float, macd_signal: float):
            return False
        async def send_custom_message(self, message: str):
            return False, "❌ Telegram não disponível"
    TELEGRAM_AVAILABLE = False

try:
    from backtest import BacktestEngine
except ImportError:
    class BacktestEngine:
        def __init__(self):
            self._error = "Modulo backtest nao encontrado"

        def run_backtest(self, *args, **kwargs):
            raise RuntimeError(self._error)

        def run_market_scan(self, *args, **kwargs):
            raise RuntimeError(self._error)

        def optimize_rsi_parameters(self, *args, **kwargs):
            raise RuntimeError(self._error)

        def get_trade_summary_df(self):
            return pd.DataFrame()

from services.paper_trade_service import PaperTradeService
from services.risk_management_service import RiskManagementService

logger = logging.getLogger(__name__)
ACTIONABLE_SIGNALS = {"COMPRA", "VENDA"}
MAX_SIGNAL_DATA_AGE_SECONDS = int(os.getenv("MAX_SIGNAL_DATA_AGE_SECONDS", "180").strip() or "180")


@st.cache_resource
def get_paper_trade_service():
    return PaperTradeService()


@st.cache_resource
def get_risk_management_service():
    return RiskManagementService()


@st.cache_resource
def get_user_manager():
    try:
        from user_manager import UserManager
        return UserManager()
    except ImportError:
        class _FallbackUserManager:
            def get_user_stats(self):
                return {'total_users': 0, 'free_users': 0, 'premium_users': 0, 'active_today': 0}

            def list_users(self, limit):
                return []

            def upgrade_to_premium(self, user_id):
                return False

            def add_admin(self, user_id):
                return False

            def is_admin(self, user_id):
                return False

            def get_user(self, user_id):
                return None

        return _FallbackUserManager()


@st.cache_data(ttl=15, show_spinner=False)
def get_cached_active_strategy_profile(symbol: str, timeframe: str):
    return db.get_active_strategy_profile(symbol=symbol, timeframe=timeframe)


@st.cache_data(ttl=15, show_spinner=False)
def get_cached_edge_monitor_summary(symbol: str, timeframe: str, strategy_version: str | None = None):
    return db.get_edge_monitor_summary(
        symbol=symbol,
        timeframe=timeframe,
        strategy_version=strategy_version,
    )


@st.cache_data(ttl=15, show_spinner=False)
def get_cached_governance_evaluation(
    symbol: str,
    timeframe: str,
    strategy_version: str | None = None,
    current_regime: str | None = None,
):
    return db.evaluate_strategy_governance(
        symbol=symbol,
        timeframe=timeframe,
        strategy_version=strategy_version,
        current_regime=current_regime,
        persist=False,
    )


@st.cache_data(ttl=15, show_spinner=False)
def get_cached_backtest_run_promotion_readiness(run_id: int):
    return db.get_backtest_run_promotion_readiness(run_id)


@st.cache_data(ttl=15, show_spinner=False)
def get_cached_strategy_governance_summary(symbol: str, timeframe: str, active_only: bool = False, limit: int = 10):
    return db.get_strategy_governance_summary(
        symbol=symbol,
        timeframe=timeframe,
        active_only=active_only,
        limit=limit,
    )


@st.cache_data(ttl=15, show_spinner=False)
def get_cached_setup_regime_baselines(symbol: str, timeframe: str, strategy_version: str | None = None):
    return db.get_setup_regime_baselines(
        symbol=symbol,
        timeframe=timeframe,
        strategy_version=strategy_version,
    )


@st.cache_data(ttl=15, show_spinner=False)
def get_cached_alignment_metrics(symbol: str, timeframe: str, strategy_version: str | None = None, limit: int = 5):
    return db.get_alignment_metrics(
        symbol=symbol,
        timeframe=timeframe,
        strategy_version=strategy_version,
        limit=limit,
    )


@st.cache_data(ttl=15, show_spinner=False)
def get_cached_governance_history(symbol: str, timeframe: str, strategy_version: str | None = None, limit: int = 10):
    return db.get_governance_history(
        symbol=symbol,
        timeframe=timeframe,
        strategy_version=strategy_version,
        limit=limit,
    )


@st.cache_data(ttl=15, show_spinner=False)
def get_cached_strategy_evaluations(
    symbol: str,
    timeframe: str,
    strategy_version: str | None = None,
    limit: int = 5,
):
    return db.get_strategy_evaluations(
        symbol=symbol,
        timeframe=timeframe,
        strategy_version=strategy_version,
        limit=limit,
    )


@st.cache_data(ttl=15, show_spinner=False)
def get_cached_strategy_evaluation_overview(
    symbol: str | None = None,
    timeframe: str | None = None,
    limit: int = 10,
):
    return db.get_strategy_evaluation_overview(
        symbol=symbol,
        timeframe=timeframe,
        limit=limit,
    )


def clear_dashboard_data_caches() -> None:
    st.cache_data.clear()


def clear_dashboard_user_session():
    st.session_state.dashboard_user_auth = None
    st.session_state.dashboard_user_login = ""
    st.session_state.dashboard_user_password = ""
    st.session_state.dashboard_user_auth_error = ""


def get_authenticated_dashboard_user():
    auth_payload = st.session_state.get("dashboard_user_auth")
    if not auth_payload:
        return None

    expires_at_raw = auth_payload.get("expires_at")
    if not expires_at_raw:
        clear_dashboard_user_session()
        return None

    try:
        expires_at = datetime.fromisoformat(str(expires_at_raw))
    except ValueError:
        clear_dashboard_user_session()
        return None

    current_time = now_brazil()
    if expires_at <= current_time:
        clear_dashboard_user_session()
        return None

    return auth_payload


def get_or_init_admin_telegram_bot():
    if 'telegram_trading_bot' not in st.session_state:
        try:
            from telegram_bot import TelegramTradingBot
            st.session_state.telegram_trading_bot = TelegramTradingBot(
                auto_configure_from_env=False,
            )
        except Exception as exc:
            logger.warning("Erro ao inicializar telegram_trading_bot do admin: %s", exc)
            st.session_state.telegram_trading_bot = None
    return st.session_state.get("telegram_trading_bot")


def apply_edge_guardrail(signal: str, symbol: str, timeframe: str, strategy_version: str = None):
    """Downgrade actionable signals when live paper performance is degraded."""
    if signal not in ACTIONABLE_SIGNALS or not ProductionConfig.ENABLE_EDGE_GUARDRAIL:
        return signal, None

    try:
        edge_summary = get_cached_edge_monitor_summary(
            symbol=symbol,
            timeframe=timeframe,
            strategy_version=strategy_version,
        )
    except Exception as exc:
        logger.warning("Falha ao consultar edge monitor: %s", exc)
        return signal, None

    if (
        edge_summary.get("status") == "degraded"
        and edge_summary.get("paper_closed_trades", 0) >= ProductionConfig.MIN_PAPER_TRADES_FOR_EDGE_GUARDRAIL
    ):
        return "NEUTRO", edge_summary

    return signal, edge_summary


def apply_risk_guardrail(
    signal: str,
    entry_price: float,
    strategy_settings: dict,
    runtime_allowed: bool = True,
    runtime_block_reason: str = None,
    system_health_ok: bool = True,
    system_health_reason: str = None,
):
    if signal not in ACTIONABLE_SIGNALS:
        return signal, None

    risk_plan = get_risk_management_service().evaluate_risk_engine(
        entry_price=float(entry_price),
        stop_loss_pct=strategy_settings.get("stop_loss_pct", 0.0) or 0.0,
        symbol=strategy_settings.get("symbol"),
        timeframe=strategy_settings.get("timeframe"),
        strategy_version=strategy_settings.get("strategy_version"),
        runtime_allowed=runtime_allowed,
        runtime_block_reason=runtime_block_reason,
        system_health_ok=system_health_ok,
        system_health_reason=system_health_reason,
    )
    if not risk_plan.get("allowed"):
        return "NEUTRO", risk_plan
    return signal, risk_plan


def build_operational_signal_state(
    analytical_signal: str,
    entry_price: float,
    strategy_settings: dict,
    regime_evaluation: dict | None = None,
):
    final_signal = analytical_signal
    edge_summary = None
    risk_plan = None
    governance_summary = None
    operational_runtime_allowed = bool(strategy_settings.get("runtime_allowed", True))
    operational_block_reason = None
    operational_block_source = None
    edge_allowed = True
    edge_block_reason = None
    current_regime = (regime_evaluation or {}).get("regime")
    if (regime_evaluation or {}).get("parabolic"):
        current_regime = "parabolic"

    if operational_runtime_allowed:
        edge_signal, edge_summary = apply_edge_guardrail(
            analytical_signal,
            strategy_settings.get("symbol"),
            strategy_settings.get("timeframe"),
            strategy_version=strategy_settings.get("strategy_version"),
        )
        edge_allowed = edge_signal in ACTIONABLE_SIGNALS or analytical_signal not in ACTIONABLE_SIGNALS
        if edge_summary and edge_signal == "NEUTRO":
            edge_block_reason = edge_summary.get("status_message") or "Edge monitor bloqueou o setup."
        final_signal, risk_plan = apply_risk_guardrail(
            analytical_signal,
            float(entry_price),
            strategy_settings,
            runtime_allowed=True,
            system_health_ok=edge_allowed,
            system_health_reason=edge_block_reason,
        )
        if edge_summary and not edge_allowed:
            operational_block_reason = edge_block_reason
            operational_block_source = "edge_guardrail"
            operational_runtime_allowed = False
        elif risk_plan and not risk_plan.get("allowed"):
            operational_block_reason = (
                risk_plan.get("risk_reason") or risk_plan.get("reason") or "Risco operacional bloqueou a entrada."
            )
            operational_block_source = "risk_guardrail"
            operational_runtime_allowed = False
    else:
        final_signal = "NEUTRO"
        _, risk_plan = apply_risk_guardrail(
            analytical_signal,
            float(entry_price),
            strategy_settings,
            runtime_allowed=False,
            runtime_block_reason=strategy_settings.get("runtime_block_reason", "Runtime bloqueado"),
        )
        operational_block_reason = (
            (risk_plan or {}).get("risk_reason")
            or (risk_plan or {}).get("reason")
            or strategy_settings.get("runtime_block_reason", "Runtime bloqueado")
        )
        operational_block_source = "runtime_governance"

    try:
        governance_summary = get_cached_governance_evaluation(
            symbol=strategy_settings.get("symbol"),
            timeframe=strategy_settings.get("timeframe"),
            strategy_version=strategy_settings.get("strategy_version"),
            current_regime=current_regime,
        )
    except Exception as exc:
        logger.warning("Falha ao avaliar governanca adaptativa: %s", exc)
        governance_summary = None

    if (
        governance_summary
        and analytical_signal in ACTIONABLE_SIGNALS
        and not operational_block_reason
        and governance_summary.get("governance_mode") == "blocked"
    ):
        final_signal = "NEUTRO"
        operational_runtime_allowed = False
        operational_block_reason = governance_summary.get("action_reason") or "Governanca adaptativa bloqueou o setup."
        operational_block_source = "adaptive_governance"
    elif governance_summary and risk_plan and risk_plan.get("allowed") and governance_summary.get("governance_mode") == "reduced":
        risk_plan["governance_mode"] = "reduced"
        risk_plan["governance_reduction_multiplier"] = governance_summary.get("governance_reduction_multiplier", 1.0)
        risk_plan["risk_reason"] = risk_plan.get("risk_reason") or governance_summary.get("action_reason")

    return {
        "final_signal": final_signal,
        "edge_summary": edge_summary,
        "risk_plan": risk_plan,
        "governance_summary": governance_summary,
        "runtime_allowed": operational_runtime_allowed,
        "block_reason": operational_block_reason,
        "block_source": operational_block_source,
    }


def get_effective_strategy_settings(
    symbol: str,
    timeframe: str,
    require_volume: bool = False,
    require_trend: bool = False,
    avoid_ranging: bool = False,
) -> dict:
    active_profile = get_cached_active_strategy_profile(symbol=symbol, timeframe=timeframe)
    trading_bot = st.session_state.get("trading_bot")
    default_context_timeframe = None

    if active_profile:
        runtime_allowed_execution_setups = AppConfig.get_runtime_allowed_execution_setups(
            timeframe,
            active_profile.get("setup_type"),
            active_profile.get("allowed_setup_types"),
            active_profile.get("allowed_market_states"),
        )
        settings = {
            "symbol": symbol,
            "timeframe": timeframe,
            "context_timeframe": active_profile.get("context_timeframe"),
            "rsi_period": active_profile.get("rsi_period"),
            "rsi_min": active_profile.get("rsi_min"),
            "rsi_max": active_profile.get("rsi_max"),
            "stop_loss_pct": active_profile.get("stop_loss_pct") or ProductionConfig.DEFAULT_LIVE_STOP_LOSS_PCT,
            "take_profit_pct": active_profile.get("take_profit_pct") or ProductionConfig.DEFAULT_LIVE_TAKE_PROFIT_PCT,
            "require_volume": bool(active_profile.get("require_volume", False)),
            "require_trend": bool(active_profile.get("require_trend", False)),
            "avoid_ranging": bool(active_profile.get("avoid_ranging", False)),
            "market_state": active_profile.get("market_state"),
            "allowed_market_states": active_profile.get("allowed_market_states") or [],
            "setup_type": active_profile.get("setup_type"),
            "allowed_setup_types": active_profile.get("allowed_setup_types") or [],
            "active_profile": active_profile,
            "source": "active_profile",
            "runtime_allowed": True,
            "runtime_block_reason": "",
            "allowed_execution_setups": runtime_allowed_execution_setups,
        }
    else:
        runtime_allowed_execution_setups = AppConfig.get_runtime_allowed_execution_setups(timeframe)
        runtime_block_reason = ""
        runtime_allowed = True
        runtime_source = "session"
        if ProductionConfig.REQUIRE_ACTIVE_PROFILE_FOR_RUNTIME:
            runtime_allowed = False
            runtime_source = "blocked_no_active_profile"
            runtime_block_reason = (
                "Nenhum setup ativo promovido para este mercado/timeframe. "
                "Runtime bloqueado ate existir perfil ativo."
            )
        settings = {
            "symbol": symbol,
            "timeframe": timeframe,
            "context_timeframe": default_context_timeframe,
            "rsi_period": getattr(trading_bot, "rsi_period", 14) if trading_bot else 14,
            "rsi_min": getattr(trading_bot, "rsi_min", 20) if trading_bot else 20,
            "rsi_max": getattr(trading_bot, "rsi_max", 80) if trading_bot else 80,
            "stop_loss_pct": ProductionConfig.DEFAULT_LIVE_STOP_LOSS_PCT,
            "take_profit_pct": ProductionConfig.DEFAULT_LIVE_TAKE_PROFIT_PCT,
            "require_volume": require_volume,
            "require_trend": require_trend,
            "avoid_ranging": avoid_ranging,
            "market_state": None,
            "allowed_market_states": [],
            "setup_type": None,
            "allowed_setup_types": [],
            "active_profile": None,
            "source": runtime_source,
            "runtime_allowed": runtime_allowed,
            "runtime_block_reason": runtime_block_reason,
            "allowed_execution_setups": runtime_allowed_execution_setups,
        }

    settings["strategy_version"] = build_strategy_version(
        symbol=symbol,
        timeframe=timeframe,
        context_timeframe=settings.get("context_timeframe"),
        rsi_period=settings["rsi_period"],
        rsi_min=settings["rsi_min"],
        rsi_max=settings["rsi_max"],
        stop_loss_pct=settings.get("stop_loss_pct", 0.0) or 0.0,
        take_profit_pct=settings.get("take_profit_pct", 0.0) or 0.0,
        require_volume=settings["require_volume"],
        require_trend=settings["require_trend"],
        avoid_ranging=settings.get("avoid_ranging", False),
    )
    return settings

# Helper function for timestamp comparison
def _compare_timestamps(ts1, ts2):
    """
    Safely compare timestamps, handling timezone-aware/naive differences
    Returns True if ts1 < ts2
    """
    try:
        # Convert both to naive datetime for comparison
        if hasattr(ts1, 'tzinfo') and ts1.tzinfo is not None:
            # If ts1 is timezone-aware, convert to Brazil timezone then make naive
            ts1_naive = ts1.astimezone(BRAZIL_TZ).replace(tzinfo=None) if hasattr(ts1, 'astimezone') else ts1.replace(tzinfo=None)
        else:
            # If ts1 is already naive, use as is
            ts1_naive = ts1

        if hasattr(ts2, 'tzinfo') and ts2.tzinfo is not None:
            # If ts2 is timezone-aware, convert to Brazil timezone then make naive
            ts2_naive = ts2.astimezone(BRAZIL_TZ).replace(tzinfo=None) if hasattr(ts2, 'astimezone') else ts2.replace(tzinfo=None)
        else:
            # If ts2 is already naive, use as is
            ts2_naive = ts2

        return ts1_naive < ts2_naive
    except Exception:
        # If comparison fails, assume it's a new signal
        return True


def _compute_data_age_seconds(last_update, now_reference=None):
    if last_update is None:
        return None
    try:
        now_value = now_reference or get_brazil_datetime_naive()
        if hasattr(last_update, "tzinfo") and last_update.tzinfo is not None:
            last_naive = last_update.astimezone(BRAZIL_TZ).replace(tzinfo=None)
        else:
            last_naive = last_update
        return max((now_value - last_naive).total_seconds(), 0.0)
    except Exception:
        return None


def _is_data_fresh(last_update, max_age_seconds=MAX_SIGNAL_DATA_AGE_SECONDS, now_reference=None):
    age_seconds = _compute_data_age_seconds(last_update, now_reference=now_reference)
    if age_seconds is None:
        return False, None
    return age_seconds <= float(max_age_seconds), age_seconds


def _build_stale_data_operational_state(age_seconds, max_age_seconds=MAX_SIGNAL_DATA_AGE_SECONDS):
    age_label = f"{age_seconds:.0f}s" if age_seconds is not None else "desconhecida"
    reason = (
        f"Dados de mercado desatualizados ({age_label} > {max_age_seconds}s). "
        "Operacao bloqueada ate receber dado recente."
    )
    return {
        "final_signal": "NEUTRO",
        "edge_summary": None,
        "risk_plan": {
            "allowed": False,
            "risk_mode": "blocked",
            "reason": reason,
            "risk_reason": reason,
        },
        "governance_summary": None,
        "runtime_allowed": False,
        "block_reason": reason,
        "block_source": "stale_data",
    }


def build_strategy_evaluation_display_df(evaluations):
    if not evaluations:
        return pd.DataFrame()

    rows = []
    for evaluation in evaluations:
        rows.append(
            {
                "Criado em": evaluation.get("created_at_br"),
                "Simbolo": evaluation.get("symbol"),
                "Timeframe": evaluation.get("timeframe"),
                "Versao": evaluation.get("strategy_version"),
                "Origem": evaluation.get("evaluation_type"),
                "Score": round(float(evaluation.get("quality_score", 0.0) or 0.0), 2),
                "PF Backtest": round(float(evaluation.get("avg_profit_factor", 0.0) or 0.0), 2),
                "PF OOS": round(float(evaluation.get("avg_out_of_sample_profit_factor", 0.0) or 0.0), 2),
                "PF Paper": round(float(evaluation.get("paper_profit_factor", 0.0) or 0.0), 2),
                "Paper Fechados": int(evaluation.get("paper_closed_trades", 0) or 0),
                "Edge": evaluation.get("edge_status"),
                "Governanca": evaluation.get("governance_status"),
            }
        )

    return pd.DataFrame(rows)


def render_backtest_portfolio_section(results, stats, result_symbol, result_timeframe):
    portfolio_values = results.get("portfolio_values") or []
    if not portfolio_values:
        return

    portfolio_df = pd.DataFrame(portfolio_values)
    if portfolio_df.empty or not {"timestamp", "portfolio_value"}.issubset(portfolio_df.columns):
        return

    portfolio_df["timestamp"] = pd.to_datetime(portfolio_df["timestamp"])
    portfolio_df["portfolio_value"] = pd.to_numeric(portfolio_df["portfolio_value"], errors="coerce")
    portfolio_df = (
        portfolio_df
        .dropna(subset=["timestamp", "portfolio_value"])
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    if portfolio_df.empty:
        return

    running_max = portfolio_df["portfolio_value"].cummax()
    portfolio_df["drawdown_pct"] = (
        (running_max - portfolio_df["portfolio_value"]) / running_max.replace(0, np.nan)
    ) * 100
    equity_diagnostics = results.get("equity_diagnostics") or {}

    st.markdown("---")
    st.subheader("📈 Evolução do Portfólio")
    st.caption(
        "Curva do capital ao longo do backtest para visualizar aceleração, devolução de lucro e pontos de estresse."
    )

    fig_portfolio = go.Figure()
    fig_portfolio.add_trace(
        go.Scatter(
            x=portfolio_df["timestamp"],
            y=portfolio_df["portfolio_value"],
            mode="lines",
            name="Portfólio",
            line=dict(color="#0f766e", width=2.5),
        )
    )

    benchmark_values = results.get("benchmark_values") or []
    if benchmark_values:
        benchmark_df = pd.DataFrame(benchmark_values)
        if not benchmark_df.empty and {"timestamp", "benchmark_value"}.issubset(benchmark_df.columns):
            benchmark_df["timestamp"] = pd.to_datetime(benchmark_df["timestamp"])
            benchmark_df["benchmark_value"] = pd.to_numeric(benchmark_df["benchmark_value"], errors="coerce")
            benchmark_df = benchmark_df.dropna(subset=["timestamp", "benchmark_value"]).sort_values("timestamp")
            if not benchmark_df.empty:
                fig_portfolio.add_trace(
                    go.Scatter(
                        x=benchmark_df["timestamp"],
                        y=benchmark_df["benchmark_value"],
                        mode="lines",
                        name="Buy & Hold",
                        line=dict(color="#f59e0b", width=2, dash="dot"),
                    )
                )

    fig_portfolio.add_hline(
        y=stats["initial_balance"],
        line_dash="dash",
        line_color="#6b7280",
        annotation_text="Capital inicial",
    )
    fig_portfolio.update_layout(
        title=f"Evolução do Portfólio - {result_symbol} {result_timeframe}",
        xaxis_title="Data",
        yaxis_title="Valor do portfólio ($)",
        height=430,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=10, r=10, t=60, b=10),
    )
    st.plotly_chart(fig_portfolio, width="stretch")

    drawdown_col1, drawdown_col2, drawdown_col3, drawdown_col4 = st.columns(4)
    with drawdown_col1:
        st.metric("Drawdown Médio", f"{float(equity_diagnostics.get('average_drawdown_pct', 0.0) or 0.0):.2f}%")
    with drawdown_col2:
        st.metric("Recuperação Máx.", int(equity_diagnostics.get("max_recovery_periods", 0) or 0))
    with drawdown_col3:
        st.metric("Payoff Ratio", f"{float(stats.get('payoff_ratio', 0.0) or 0.0):.2f}")
    with drawdown_col4:
        st.metric("Giveback no Topo", f"{float(equity_diagnostics.get('profit_giveback_pct', 0.0) or 0.0):.2f}%")

    fig_drawdown = go.Figure()
    fig_drawdown.add_trace(
        go.Scatter(
            x=portfolio_df["timestamp"],
            y=portfolio_df["drawdown_pct"].fillna(0.0),
            mode="lines",
            name="Drawdown %",
            line=dict(color="#dc2626", width=2),
            fill="tozeroy",
            fillcolor="rgba(220, 38, 38, 0.12)",
        )
    )
    fig_drawdown.update_layout(
        title=f"Curva de Drawdown - {result_symbol} {result_timeframe}",
        xaxis_title="Data",
        yaxis_title="Drawdown %",
        height=280,
        margin=dict(l=10, r=10, t=50, b=10),
    )
    st.plotly_chart(fig_drawdown, width="stretch")


def _get_realtime_chart_snapshot(symbol, timeframe, fallback_data, limit=200):
    trading_bot = st.session_state.get("trading_bot")
    if trading_bot is None:
        return fallback_data, None

    try:
        stream_client = trading_bot._get_realtime_stream_client(symbol=symbol, timeframe=timeframe)
        chart_data = stream_client.get_market_data(
            limit=limit,
            timeout=2.0,
            include_current_candle=True,
        )
        return chart_data, stream_client.get_current_status()
    except Exception as exc:
        logger.warning(
            "Falha ao obter snapshot realtime do grafico %s %s: %s",
            symbol,
            timeframe,
            exc,
        )
        return fallback_data, None


@st.fragment(run_every=2)
def render_live_market_chart(symbol, timeframe, fallback_data):
    chart_limit = 200
    if fallback_data is not None and not fallback_data.empty:
        chart_limit = max(len(fallback_data.index), 200)

    chart_data, stream_status = _get_realtime_chart_snapshot(
        symbol=symbol,
        timeframe=timeframe,
        fallback_data=fallback_data,
        limit=chart_limit,
    )

    if chart_data is None or chart_data.empty:
        st.warning("Grafico realtime indisponivel no momento.")
        return

    fig = make_subplots(
        rows=1, cols=1,
        shared_xaxes=True,
        subplot_titles=("Preço",),
    )

    fig.add_trace(
        go.Candlestick(
            x=chart_data.index,
            open=chart_data["open"],
            high=chart_data["high"],
            low=chart_data["low"],
            close=chart_data["close"],
            name="Preço",
        ),
        row=1, col=1
    )

    chart_signals = pd.DataFrame(st.session_state.signals_history) if st.session_state.signals_history else pd.DataFrame()
    if not chart_signals.empty:
        chart_signals = chart_signals.copy()
        chart_signals["timestamp"] = pd.to_datetime(chart_signals["timestamp"], errors="coerce")
        chart_signals = chart_signals.dropna(subset=["timestamp"])
        if "timeframe" not in chart_signals.columns:
            chart_signals["timeframe"] = timeframe
        for signal_column in ["candidate_signal", "approved_signal", "blocked_signal", "block_reason"]:
            if signal_column not in chart_signals.columns:
                chart_signals[signal_column] = None
        chart_signals = chart_signals[
            (chart_signals["symbol"] == symbol)
            & (chart_signals["timeframe"] == timeframe)
        ]

        def _add_signal_trace(signal_df, expected_signal, marker_symbol, marker_color, marker_size, name, blocked=False):
            filtered = signal_df[signal_df["signal_value"] == expected_signal]
            if filtered.empty:
                return
            hover_text = (
                filtered.get("block_reason", pd.Series([""] * len(filtered))).fillna("-")
                if blocked else
                filtered.get("candidate_signal", pd.Series([""] * len(filtered))).fillna("-")
            )
            fig.add_trace(
                go.Scatter(
                    x=filtered["timestamp"],
                    y=filtered["price"],
                    mode="markers",
                    marker=dict(symbol=marker_symbol, size=marker_size, color=marker_color),
                    name=name,
                    text=hover_text,
                    hovertemplate="%{x}<br>Preco %{y:.6f}<br>%{text}<extra></extra>",
                    showlegend=True,
                ),
                row=1, col=1
            )

        candidate_markers = chart_signals[
            chart_signals["candidate_signal"].isin(list(ACTIONABLE_SIGNALS))
        ].copy()
        if not candidate_markers.empty:
            candidate_markers["signal_value"] = candidate_markers["candidate_signal"]
            _add_signal_trace(candidate_markers, "COMPRA", "triangle-up-open", "rgba(0, 160, 0, 0.7)", 15, "Candidato Compra")
            _add_signal_trace(candidate_markers, "VENDA", "triangle-down-open", "rgba(190, 0, 0, 0.7)", 15, "Candidato Venda")

        approved_markers = chart_signals[
            chart_signals["approved_signal"].isin(list(ACTIONABLE_SIGNALS))
        ].copy()
        if not approved_markers.empty:
            approved_markers["signal_value"] = approved_markers["approved_signal"]
            _add_signal_trace(approved_markers, "COMPRA", "triangle-up", "green", 18, "Aprovado Compra")
            _add_signal_trace(approved_markers, "VENDA", "triangle-down", "red", 18, "Aprovado Venda")

        blocked_markers = chart_signals[
            chart_signals["blocked_signal"].isin(list(ACTIONABLE_SIGNALS))
        ].copy()
        if not blocked_markers.empty:
            blocked_markers["signal_value"] = blocked_markers["blocked_signal"]
            _add_signal_trace(blocked_markers, "COMPRA", "x", "orange", 13, "Bloqueado Compra", blocked=True)
            _add_signal_trace(blocked_markers, "VENDA", "x", "orange", 13, "Bloqueado Venda", blocked=True)

    if "is_closed" in chart_data.columns and not bool(chart_data["is_closed"].iloc[-1]):
        current_row = chart_data.iloc[-1]
        fig.add_annotation(
            x=chart_data.index[-1],
            y=float(current_row["close"]),
            text="Tempo real",
            showarrow=True,
            arrowhead=1,
            ax=35,
            ay=-35,
            bgcolor="rgba(15, 118, 110, 0.15)",
        )

    fig.update_layout(
        title=f"{symbol} - {timeframe}",
        height=520,
        xaxis_rangeslider_visible=False,
        showlegend=True,
    )
    fig.update_yaxes(title_text="Preço ($)", row=1, col=1)

    st.plotly_chart(fig, width="stretch")

    if stream_status and stream_status.get("connected"):
        provider = stream_status.get("provider") or "stream"
        message_age = stream_status.get("last_message_age_sec")
        age_label = f"{message_age}s" if message_age is not None else "agora"
        mode_label = "inclui vela em formação" if "is_closed" in chart_data.columns and not bool(chart_data["is_closed"].iloc[-1]) else "somente candles fechados"
        st.caption(f"Mercado em tempo real via {provider} | ultima mensagem ha {age_label} | {mode_label}.")
    else:
        st.caption("Grafico exibido com snapshot fallback; stream realtime nao confirmou conexao neste ciclo.")


def render_multiuser_workspace_tab():
    workspace_user = get_authenticated_dashboard_user()
    st.subheader("👤 Meu Workspace")
    st.caption("Área isolada por usuário para contas, risco, credenciais e monitoramento operacional.")

    if not workspace_user:
        st.info("Faça login na barra lateral para acessar seu workspace multiusuário.")
        st.markdown(
            """
            Este espaço foi preparado para o modelo multiusuário:
            - cada usuário enxerga apenas as próprias contas
            - credenciais ficam protegidas no vault
            - risco, permissões e governança são acompanhados por conta
            """
        )
        return

    user_id = int(workspace_user["user_id"])
    user_label = (
        workspace_user.get("first_name")
        or workspace_user.get("username")
        or workspace_user.get("login_name")
        or str(user_id)
    )
    st.success(f"Sessão ativa: {user_label} | User ID {user_id}")
    if workspace_user.get("require_password_change"):
        st.warning("Sua conta exige troca de senha antes de uso recorrente. Atualize abaixo.")

    workspace_accounts = db.get_user_workspace_accounts(user_id=user_id, limit=100)

    summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)
    with summary_col1:
        st.metric("Contas", len(workspace_accounts))
    with summary_col2:
        st.metric("Live Habilitado", sum(1 for item in workspace_accounts if bool(item.get("live_enabled"))))
    with summary_col3:
        st.metric("Paper Habilitado", sum(1 for item in workspace_accounts if bool(item.get("paper_enabled"))))
    with summary_col4:
        st.metric("Risk Profiles Válidos", sum(1 for item in workspace_accounts if bool(item.get("risk_profile_valid"))))

    if workspace_accounts:
        account_lookup = {
            f"{row.get('account_alias') or row.get('account_id')} | {row.get('exchange')} | {row.get('account_id')}": row
            for row in workspace_accounts
        }
        selected_account_label = st.selectbox(
            "Selecionar Conta",
            options=list(account_lookup.keys()),
            key="workspace_account_selector",
        )
        selected_account = account_lookup[selected_account_label]
        selected_account_id = str(selected_account["account_id"])
        selected_exchange = str(selected_account.get("exchange") or "")
        try:
            execution_context = db.build_account_execution_context(
                user_id=user_id,
                account_id=selected_account_id,
                exchange=selected_exchange,
            )
        except Exception:
            risk_profile_fallback = db.get_user_risk_profile(user_id=user_id, account_id=selected_account_id) or {}
            credential_fallback = db.get_user_exchange_credential(
                user_id=user_id,
                account_id=selected_account_id,
                exchange=selected_exchange,
                include_encrypted=False,
            ) or {}
            governance_fallback = db.get_user_governance_state(
                user_id=user_id,
                account_id=selected_account_id,
                exchange=selected_exchange,
            ) or {}
            execution_context = {
                "user_id": user_id,
                "account_id": selected_account_id,
                "account_alias": selected_account.get("account_alias") or selected_account_id,
                "exchange_name": selected_exchange,
                "api_key_ref": credential_fallback.get("api_key_ref"),
                "token_ref": credential_fallback.get("token_ref"),
                "live_enabled": bool(selected_account.get("live_enabled")),
                "paper_enabled": bool(selected_account.get("paper_enabled")),
                "governance_status": governance_fallback.get("governance_status") or "unknown",
                "governance_mode": governance_fallback.get("governance_mode") or "blocked",
                "governance_blocked": bool(governance_fallback.get("blocked", False)),
                "governance_block_reason": governance_fallback.get("block_reason"),
                "risk_profile": risk_profile_fallback,
                "allowed_symbols": selected_account.get("allowed_symbols") or [],
                "allowed_timeframes": selected_account.get("allowed_timeframes") or [],
                "capital_base": float(selected_account.get("capital_base", 0.0) or 0.0),
                "risk_mode": selected_account.get("risk_mode") or "normal",
                "notes": selected_account.get("notes"),
                "permission_status": credential_fallback.get("permission_status") or selected_account.get("permission_status") or "unknown",
                "token_status": credential_fallback.get("token_status") or selected_account.get("token_status") or "unknown",
                "reconciliation_status": credential_fallback.get("reconciliation_status") or selected_account.get("reconciliation_status") or "unknown",
            }

        st.markdown("### Estado da Conta")
        account_col1, account_col2, account_col3, account_col4, account_col5 = st.columns(5)
        with account_col1:
            st.metric("Status", selected_account.get("status", "-"))
        with account_col2:
            st.metric("Live", "ON" if bool(selected_account.get("live_enabled")) else "OFF")
        with account_col3:
            st.metric("Paper", "ON" if bool(selected_account.get("paper_enabled")) else "OFF")
        with account_col4:
            st.metric("Governança", execution_context.get("governance_status", "-"))
        with account_col5:
            st.metric("Modo de Risco", execution_context.get("risk_mode", selected_account.get("risk_mode", "-")))

        ops_col1, ops_col2, ops_col3, ops_col4 = st.columns(4)
        with ops_col1:
            st.metric("Capital Base", f"${float(selected_account.get('capital_base', 0.0) or 0.0):,.2f}")
        with ops_col2:
            st.metric("Posições Abertas", int(selected_account.get("open_positions", 0) or 0))
        with ops_col3:
            st.metric("Ordens Pendentes", int(selected_account.get("pending_orders", 0) or 0))
        with ops_col4:
            st.metric("Credencial", "OK" if execution_context.get("api_key_ref") else "PENDENTE")

        st.caption(
            f"Símbolos permitidos: {', '.join(execution_context.get('allowed_symbols', [])) or '-'} | "
            f"Timeframes permitidos: {', '.join(execution_context.get('allowed_timeframes', [])) or '-'} | "
            f"Permissões: {execution_context.get('permission_status', 'unknown')} | "
            f"Token: {execution_context.get('token_status', 'unknown')} | "
            f"Reconciliação: {execution_context.get('reconciliation_status', 'unknown')}"
        )
        if execution_context.get("governance_block_reason"):
            st.warning(f"Bloqueio operacional: {execution_context.get('governance_block_reason')}")

        detail_tab1, detail_tab2, detail_tab3, detail_tab4 = st.tabs(
            ["⚙️ Conta", "🛡️ Risco", "🔑 Credenciais", "📜 Eventos"]
        )

        with detail_tab1:
            with st.form(f"workspace_account_form_{selected_account_id}"):
                acc_col1, acc_col2, acc_col3 = st.columns(3)
                with acc_col1:
                    account_alias = st.text_input(
                        "Alias",
                        value=str(selected_account.get("account_alias") or selected_account_id),
                        key=f"workspace_alias_{selected_account_id}",
                    )
                    account_status = st.selectbox(
                        "Status",
                        options=["active", "disabled"],
                        index=0 if str(selected_account.get("status") or "active").lower() == "active" else 1,
                        key=f"workspace_status_{selected_account_id}",
                    )
                with acc_col2:
                    live_enabled = st.checkbox(
                        "Live Enabled",
                        value=bool(selected_account.get("live_enabled")),
                        key=f"workspace_live_{selected_account_id}",
                    )
                    paper_enabled = st.checkbox(
                        "Paper Enabled",
                        value=bool(selected_account.get("paper_enabled")),
                        key=f"workspace_paper_{selected_account_id}",
                    )
                with acc_col3:
                    capital_base = st.number_input(
                        "Capital Base",
                        min_value=0.0,
                        value=float(selected_account.get("capital_base", 0.0) or 0.0),
                        step=100.0,
                        key=f"workspace_capital_{selected_account_id}",
                    )
                    risk_mode = st.selectbox(
                        "Risk Mode",
                        options=["normal", "reduced", "blocked"],
                        index=["normal", "reduced", "blocked"].index(
                            str(selected_account.get("risk_mode") or "normal")
                            if str(selected_account.get("risk_mode") or "normal") in {"normal", "reduced", "blocked"}
                            else "normal"
                        ),
                        key=f"workspace_risk_mode_{selected_account_id}",
                    )

                allowed_symbols_raw = st.text_input(
                    "Símbolos Permitidos",
                    value=",".join(execution_context.get("allowed_symbols", [])),
                    key=f"workspace_symbols_{selected_account_id}",
                )
                allowed_timeframes = st.multiselect(
                    "Timeframes Permitidos",
                    options=["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
                    default=execution_context.get("allowed_timeframes", []),
                    key=f"workspace_timeframes_{selected_account_id}",
                )
                account_notes = st.text_area(
                    "Notas da Conta",
                    value=str(selected_account.get("notes") or ""),
                    key=f"workspace_notes_{selected_account_id}",
                )

                if st.form_submit_button("Salvar Conta"):
                    db.upsert_user_account(
                        {
                            "user_id": user_id,
                            "account_id": selected_account_id,
                            "account_alias": account_alias.strip() or selected_account_id,
                            "exchange": selected_exchange,
                            "status": account_status,
                            "live_enabled": bool(live_enabled),
                            "paper_enabled": bool(paper_enabled),
                            "capital_base": float(capital_base),
                            "risk_mode": risk_mode,
                            "allowed_symbols": [item.strip() for item in allowed_symbols_raw.split(",") if item.strip()],
                            "allowed_timeframes": list(allowed_timeframes),
                            "notes": account_notes,
                        }
                    )
                    st.success("Conta atualizada com sucesso.")
                    st.rerun()

            with st.expander("Adicionar Nova Conta", expanded=False):
                with st.form(f"workspace_new_account_form_{user_id}"):
                    new_col1, new_col2, new_col3 = st.columns(3)
                    with new_col1:
                        new_account_id = st.text_input("Novo Account ID", key=f"workspace_new_account_id_{user_id}")
                        new_account_alias = st.text_input("Alias da Nova Conta", key=f"workspace_new_account_alias_{user_id}")
                    with new_col2:
                        new_exchange = st.selectbox(
                            "Exchange",
                            options=AppConfig.BRAZIL_SUPPORTED_EXCHANGES or ["binance"],
                            key=f"workspace_new_exchange_{user_id}",
                        )
                        new_status = st.selectbox(
                            "Status da Conta",
                            options=["active", "disabled"],
                            key=f"workspace_new_status_{user_id}",
                        )
                    with new_col3:
                        new_capital_base = st.number_input(
                            "Capital Base Inicial",
                            min_value=0.0,
                            value=10000.0,
                            step=100.0,
                            key=f"workspace_new_capital_{user_id}",
                        )
                        new_live_enabled = st.checkbox("Live Enabled", value=False, key=f"workspace_new_live_{user_id}")
                        new_paper_enabled = st.checkbox("Paper Enabled", value=True, key=f"workspace_new_paper_{user_id}")

                    new_symbols = st.text_input(
                        "Símbolos Permitidos",
                        value="BTC/USDT,ETH/USDT",
                        key=f"workspace_new_symbols_{user_id}",
                    )
                    new_timeframes = st.multiselect(
                        "Timeframes Permitidos",
                        options=["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
                        default=["15m", "1h"],
                        key=f"workspace_new_timeframes_{user_id}",
                    )
                    new_notes = st.text_area("Notas", key=f"workspace_new_notes_{user_id}")

                    if st.form_submit_button("Adicionar Conta"):
                        if not str(new_account_id).strip():
                            st.error("Informe um account_id válido.")
                        else:
                            db.upsert_user_account(
                                {
                                    "user_id": user_id,
                                    "account_id": str(new_account_id).strip(),
                                    "account_alias": str(new_account_alias or new_account_id).strip(),
                                    "exchange": new_exchange,
                                    "status": new_status,
                                    "live_enabled": bool(new_live_enabled),
                                    "paper_enabled": bool(new_paper_enabled),
                                    "capital_base": float(new_capital_base),
                                    "risk_mode": "normal",
                                    "allowed_symbols": [item.strip() for item in str(new_symbols).split(",") if item.strip()],
                                    "allowed_timeframes": list(new_timeframes),
                                    "notes": new_notes,
                                }
                            )
                            st.success("Nova conta criada com sucesso.")
                            st.rerun()

        with detail_tab2:
            risk_profile = execution_context.get("risk_profile") or {}
            with st.form(f"workspace_risk_form_{selected_account_id}"):
                risk_col1, risk_col2, risk_col3 = st.columns(3)
                with risk_col1:
                    max_risk_per_trade = st.number_input(
                        "Risco por Trade %",
                        min_value=0.0,
                        value=float(risk_profile.get("max_risk_per_trade", 0.5) or 0.5),
                        step=0.1,
                        key=f"workspace_risk_trade_{selected_account_id}",
                    )
                    max_daily_loss = st.number_input(
                        "Loss Diário %",
                        min_value=0.0,
                        value=float(risk_profile.get("max_daily_loss", 2.0) or 2.0),
                        step=0.1,
                        key=f"workspace_daily_loss_{selected_account_id}",
                    )
                with risk_col2:
                    max_drawdown = st.number_input(
                        "Drawdown Máx %",
                        min_value=0.0,
                        value=float(risk_profile.get("max_drawdown", 10.0) or 10.0),
                        step=0.5,
                        key=f"workspace_drawdown_{selected_account_id}",
                    )
                    max_portfolio_open_risk_pct = st.number_input(
                        "Risco Aberto Máx %",
                        min_value=0.0,
                        value=float(risk_profile.get("max_portfolio_open_risk_pct", 2.0) or 2.0),
                        step=0.1,
                        key=f"workspace_open_risk_{selected_account_id}",
                    )
                with risk_col3:
                    allowed_position_count = st.number_input(
                        "Máx Posições",
                        min_value=0,
                        value=int(risk_profile.get("allowed_position_count", 3) or 3),
                        step=1,
                        key=f"workspace_positions_{selected_account_id}",
                    )
                    leverage_cap = st.number_input(
                        "Leverage Cap",
                        min_value=0.0,
                        value=float(risk_profile.get("leverage_cap", 5.0) or 5.0),
                        step=0.5,
                        key=f"workspace_leverage_{selected_account_id}",
                    )

                preferred_symbols = st.text_input(
                    "Símbolos Preferidos",
                    value=",".join(risk_profile.get("preferred_symbols", execution_context.get("allowed_symbols", []))),
                    key=f"workspace_pref_symbols_{selected_account_id}",
                )
                risk_mode_profile = st.selectbox(
                    "Modo do Perfil",
                    options=["normal", "reduced", "blocked"],
                    index=["normal", "reduced", "blocked"].index(
                        str(risk_profile.get("risk_mode") or "normal")
                        if str(risk_profile.get("risk_mode") or "normal") in {"normal", "reduced", "blocked"}
                        else "normal"
                    ),
                    key=f"workspace_profile_mode_{selected_account_id}",
                )
                risk_is_valid = st.checkbox(
                    "Perfil Válido",
                    value=bool(risk_profile.get("is_valid", True)),
                    key=f"workspace_profile_valid_{selected_account_id}",
                )
                risk_live_enabled = st.checkbox(
                    "Live liberado no risco",
                    value=bool(risk_profile.get("live_enabled", True)),
                    key=f"workspace_risk_live_{selected_account_id}",
                )
                risk_paper_enabled = st.checkbox(
                    "Paper liberado no risco",
                    value=bool(risk_profile.get("paper_enabled", True)),
                    key=f"workspace_risk_paper_{selected_account_id}",
                )

                if st.form_submit_button("Salvar Perfil de Risco"):
                    db.upsert_user_risk_profile(
                        {
                            "user_id": user_id,
                            "account_id": selected_account_id,
                            "max_risk_per_trade": float(max_risk_per_trade),
                            "max_daily_loss": float(max_daily_loss),
                            "max_drawdown": float(max_drawdown),
                            "max_portfolio_open_risk_pct": float(max_portfolio_open_risk_pct),
                            "allowed_position_count": int(allowed_position_count),
                            "preferred_symbols": [item.strip() for item in preferred_symbols.split(",") if item.strip()],
                            "leverage_cap": float(leverage_cap),
                            "risk_mode": risk_mode_profile,
                            "is_valid": bool(risk_is_valid),
                            "live_enabled": bool(risk_live_enabled),
                            "paper_enabled": bool(risk_paper_enabled),
                        }
                    )
                    st.success("Perfil de risco atualizado com sucesso.")
                    st.rerun()

        with detail_tab3:
            vault = None
            vault_error = ""
            try:
                from services.credential_vault import CredentialVault

                vault = CredentialVault(strict=False)
            except Exception as exc:
                vault_error = str(exc)

            if vault_error:
                st.error(f"Vault indisponível: {vault_error}")
            elif not vault or not vault.is_configured():
                st.warning("Configure CREDENTIAL_ENCRYPTION_KEY para liberar o armazenamento seguro das credenciais.")
            else:
                st.success(
                    f"Credencial atual: {execution_context.get('api_key_ref') or 'não cadastrada'} | "
                    f"Token ref: {execution_context.get('token_ref') or 'não cadastrado'}"
                )
                with st.form(f"workspace_credentials_form_{selected_account_id}"):
                    credential_alias = st.text_input(
                        "Alias da Credencial",
                        value=str(selected_account.get("account_alias") or selected_account_id),
                        key=f"workspace_cred_alias_{selected_account_id}",
                    )
                    api_key = st.text_input("API Key", type="password", key=f"workspace_api_key_{selected_account_id}")
                    api_secret = st.text_input("API Secret", type="password", key=f"workspace_api_secret_{selected_account_id}")
                    credential_notes = st.text_area("Notas da Credencial", key=f"workspace_cred_notes_{selected_account_id}")

                    if st.form_submit_button("Salvar Credenciais"):
                        if not api_key or not api_secret:
                            st.error("Informe API Key e API Secret para atualizar as credenciais.")
                        else:
                            vault.store_exchange_credentials(
                                db,
                                user_id=user_id,
                                account_id=selected_account_id,
                                exchange=selected_exchange,
                                api_key=api_key,
                                api_secret=api_secret,
                                credential_alias=credential_alias,
                                permissions_read=True,
                                permissions_trade=True,
                                permissions_withdraw=False,
                                permission_status=selected_account.get("permission_status", "unknown"),
                                token_status=selected_account.get("token_status", "unknown"),
                                reconciliation_status=selected_account.get("reconciliation_status", "unknown"),
                                notes=credential_notes,
                            )
                            st.success("Credenciais atualizadas com criptografia.")
                            st.rerun()

        with detail_tab4:
            events = db.get_user_execution_events(user_id=user_id, account_id=selected_account_id, limit=20)
            positions = db.get_user_live_positions(user_id=user_id, account_id=selected_account_id)
            orders = db.get_user_live_orders(user_id=user_id, account_id=selected_account_id)

            if positions:
                st.caption("Posições Live")
                st.dataframe(pd.DataFrame(positions), width="stretch", hide_index=True)
            else:
                st.info("Nenhuma posição live registrada para esta conta.")

            if orders:
                st.caption("Ordens Live")
                st.dataframe(pd.DataFrame(orders), width="stretch", hide_index=True)
            else:
                st.info("Nenhuma ordem live pendente para esta conta.")

            if events:
                events_df = pd.DataFrame(events)
                st.caption("Eventos Operacionais Recentes")
                st.dataframe(events_df, width="stretch", hide_index=True)
            else:
                st.info("Nenhum evento operacional recente para esta conta.")
    else:
        st.info("Nenhuma conta cadastrada para este usuário. Use o admin panel ou a abertura inicial de conta para começar.")

    st.markdown("---")
    st.subheader("🔒 Segurança da Sessão")
    with st.form(f"workspace_password_change_{user_id}"):
        pwd_col1, pwd_col2, pwd_col3 = st.columns(3)
        with pwd_col1:
            current_password = st.text_input("Senha Atual", type="password", key=f"workspace_current_password_{user_id}")
        with pwd_col2:
            new_password = st.text_input("Nova Senha", type="password", key=f"workspace_new_password_{user_id}")
        with pwd_col3:
            confirm_password = st.text_input("Confirmar Nova Senha", type="password", key=f"workspace_confirm_password_{user_id}")

        if st.form_submit_button("Atualizar Senha"):
            if new_password != confirm_password:
                st.error("A confirmação da nova senha não confere.")
            else:
                changed = db.change_dashboard_user_password(
                    user_id=user_id,
                    current_password=current_password,
                    new_password=new_password,
                )
                if changed:
                    refreshed_auth = dict(workspace_user)
                    refreshed_auth["require_password_change"] = False
                    st.session_state.dashboard_user_auth = refreshed_auth
                    st.success("Senha atualizada com sucesso.")
                else:
                    st.error("Não foi possível atualizar a senha. Verifique a senha atual.")

# Configure page

def main():
    st.set_page_config(
        page_title="Trading Signals Dashboard",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # Incluir JavaScript para refresh suave
    st.markdown("""
    <script>
    // Auto-refresh suave sem recarregar página
    let refreshTimer = null;

    function smoothRefresh() {
        // Mostrar indicador de carregamento sutil
        const indicator = document.createElement('div');
        indicator.innerHTML = '🔄 Atualizando...';
        indicator.style.position = 'fixed';
        indicator.style.top = '10px';
        indicator.style.right = '10px';
        indicator.style.background = '#f0f8ff';
        indicator.style.padding = '5px 10px';
        indicator.style.borderRadius = '5px';
        indicator.style.fontSize = '12px';
        indicator.style.zIndex = '9999';
        indicator.style.opacity = '0.8';
        document.body.appendChild(indicator);
        
        // Remover indicador após 2 segundos
        setTimeout(() => {
            if (indicator.parentNode) {
                indicator.parentNode.removeChild(indicator);
            }
        }, 2000);
    }

    // Configurar refresh automático mais suave
    if (typeof window.streamlitAutoRefresh === 'undefined') {
        window.streamlitAutoRefresh = true;
        
        // Refresh a cada 45 segundos
        setInterval(() => {
            if (!document.hidden) {
                smoothRefresh();
                // Triggerar atualização suave do Streamlit
                window.parent.postMessage({
                    type: 'streamlit:componentReady',
                    data: { refresh: true }
                }, '*');
            }
        }, 45000);
    }
    </script>
    """, unsafe_allow_html=True)

    # Sidebar configuration - Move this section before session state initialization
    st.sidebar.title("🔧 Configurações")

    # Exchange selection
    st.sidebar.subheader("🌎 Exchange")

    # Usar sempre Binance WebSocket público
    selected_exchange = 'binance'
    st.sidebar.success("✅ **Binance WebSocket Público** - Funcionando sem credenciais")
    st.sidebar.info("📡 Dados em tempo real via WebSocket público da Binance Futures")
    st.sidebar.info("🔹 Sem limite de requisições API - Dados streaming 24/7")

    # Initialize session state com cache inteligente
    if 'trading_bot' not in st.session_state:
        st.session_state.trading_bot = TradingBot()

    # Cache inteligente para evitar reloads desnecessários
    if 'data_cache' not in st.session_state:
        st.session_state.data_cache = {}
        
    if 'smooth_update' not in st.session_state:
        st.session_state.smooth_update = True

    # Update exchange if changed
    if 'current_exchange' not in st.session_state or st.session_state.current_exchange != selected_exchange:
        try:
            st.session_state.trading_bot.exchange_name = selected_exchange
            st.session_state.trading_bot.exchange = ExchangeConfig.get_exchange_instance(selected_exchange, testnet=False)
            st.session_state.current_exchange = selected_exchange
            # Clear cached data when exchange changes
            st.session_state.current_data = None
            st.session_state.last_update = None
            if 'multi_symbol_data' in st.session_state:
                st.session_state.multi_symbol_data = {}
        except Exception as e:
            st.sidebar.error(f"Erro ao configurar {selected_exchange}: {str(e)}")

    if 'telegram_bot' not in st.session_state:
        st.session_state.telegram_bot = SecureTelegramService()

    # Dashboard nao deve iniciar polling do bot 24/7. Esse processo deve rodar separado em nuvem.
    if 'telegram_trading_bot_started' not in st.session_state:
        if ProductionConfig.ENABLE_DASHBOARD_BACKGROUND_BOT:
            logger.warning("ENABLE_DASHBOARD_BACKGROUND_BOT foi definido, mas o modo recomendado e executar o bot por start_telegram_bot.py")
        st.session_state.telegram_trading_bot_started = False

    if 'signals_history' not in st.session_state:
        st.session_state.signals_history = []

    if 'last_update' not in st.session_state:
        st.session_state.last_update = None

    if 'auto_refresh' not in st.session_state:
        st.session_state.auto_refresh = True

    if 'current_data' not in st.session_state:
        st.session_state.current_data = None

    if 'telegram_notifications' not in st.session_state:
        st.session_state.telegram_notifications = False

    if 'backtest_engine' not in st.session_state:
        st.session_state.backtest_engine = BacktestEngine()

    if 'backtest_results' not in st.session_state:
        st.session_state.backtest_results = None

    if 'backtest_scan_results' not in st.session_state:
        st.session_state.backtest_scan_results = None

    if 'backtest_optimization_results' not in st.session_state:
        st.session_state.backtest_optimization_results = None

    if 'dashboard_user_auth' not in st.session_state:
        st.session_state.dashboard_user_auth = None
    if 'dashboard_user_login' not in st.session_state:
        st.session_state.dashboard_user_login = ""
    if 'dashboard_user_password' not in st.session_state:
        st.session_state.dashboard_user_password = ""
    if 'dashboard_user_auth_error' not in st.session_state:
        st.session_state.dashboard_user_auth_error = ""

    st.sidebar.markdown("---")
    st.sidebar.subheader("👤 Workspace Multiusuário")
    dashboard_user = get_authenticated_dashboard_user()
    if dashboard_user:
        dashboard_user_label = (
            dashboard_user.get("first_name")
            or dashboard_user.get("username")
            or dashboard_user.get("login_name")
            or str(dashboard_user.get("user_id"))
        )
        expires_at_label = str(dashboard_user.get("expires_at") or "")
        st.sidebar.success(f"Sessão ativa: {dashboard_user_label}")
        if expires_at_label:
            st.sidebar.caption(f"Sessão válida até: {expires_at_label}")
        if dashboard_user.get("require_password_change"):
            st.sidebar.warning("Troque sua senha no workspace antes de operar regularmente.")
        if st.sidebar.button("Sair do Workspace", key="dashboard_user_logout"):
            clear_dashboard_user_session()
            st.rerun()
    else:
        with st.sidebar.form("dashboard_user_login_form"):
            st.text_input("Login do Workspace", key="dashboard_user_login")
            st.text_input("Senha do Workspace", type="password", key="dashboard_user_password")
            if st.form_submit_button("Entrar no Workspace"):
                authenticated_user = db.authenticate_dashboard_user(
                    login_name=st.session_state.get("dashboard_user_login"),
                    password=st.session_state.get("dashboard_user_password"),
                )
                if authenticated_user:
                    authenticated_user["expires_at"] = (
                        now_brazil() + timedelta(hours=ProductionConfig.DASHBOARD_USER_SESSION_TIMEOUT_HOURS)
                    ).isoformat()
                    st.session_state.dashboard_user_auth = authenticated_user
                    st.session_state.dashboard_user_password = ""
                    st.session_state.dashboard_user_auth_error = ""
                    st.rerun()
                else:
                    st.session_state.dashboard_user_auth_error = "❌ Login ou senha inválidos."
        if st.session_state.get("dashboard_user_auth_error"):
            st.sidebar.error(st.session_state.dashboard_user_auth_error)
        st.sidebar.caption(
            "Acesso isolado por usuário. Cada conta enxerga apenas risco, credenciais e eventos próprios."
        )

    # Continue with sidebar configuration

    # Test WebSocket connection
    if st.sidebar.button("🧪 Testar WebSocket Binance"):
        with st.spinner("Testando WebSocket público da Binance Futures..."):
            try:
                success, message = ExchangeConfig.test_connection('binance')
                
                if success:
                    st.sidebar.success("✅ WebSocket Público da Binance funcionando!")
                    with st.sidebar.expander("📊 Detalhes da Conexão"):
                        st.text(message)
                else:
                    st.sidebar.error("❌ Problema com WebSocket público")
                    with st.sidebar.expander("🔍 Detalhes do Erro"):
                        st.text(message)
                        
            except Exception as e:
                st.sidebar.error(f"❌ Erro: {str(e)}")

    # Diagnóstico WebSocket
    if st.sidebar.button("🔍 Diagnóstico WebSocket"):
        with st.spinner("Executando diagnóstico WebSocket..."):
            st.sidebar.markdown("**🔍 Relatório WebSocket:**")

            # Teste 1: Internet
            try:
                import requests
                response = requests.get("https://httpbin.org/ip", timeout=5)
                st.sidebar.success("✅ Conexão com internet OK")
            except:
                st.sidebar.error("❌ Sem conexão com internet")

            # Teste 2: Binance API
            try:
                import requests
                response = requests.get("https://api.binance.com/api/v3/ping", timeout=5)
                st.sidebar.success("✅ Binance API acessível")
            except:
                st.sidebar.error("❌ Problema com Binance API")

            # Teste 3: WebSocket endpoint
            try:
                import requests
                response = requests.get("https://fstream.binance.com", timeout=5)
                st.sidebar.success("✅ WebSocket Binance Futures disponível")
            except Exception as e:
                st.sidebar.error(f"❌ WebSocket: {str(e)[:50]}...")

    # Multi-symbol monitoring
    st.sidebar.subheader("📊 Configuração de Pares")

    # Pares USDT disponíveis na Binance via WebSocket
    available_pairs = AppConfig.get_supported_pairs()
    supported_timeframes = AppConfig.get_supported_timeframes()

    # Escolha do modo de operação
    if AppConfig.SINGLE_SETUP_MODE:
        enable_multi_symbol = False
        symbol = st.sidebar.selectbox(
            "📈 Par para análise:",
            available_pairs,
            index=available_pairs.index(AppConfig.DEFAULT_SYMBOL) if AppConfig.DEFAULT_SYMBOL in available_pairs else 0,
            help="O perfil global continua fixo, mas a auditoria analitica pode ser feita em outros pares.",
            key="single_setup_symbol",
        )
        selected_symbols = [symbol]
        symbol_family_label = AppConfig.get_symbol_profile_family_label(symbol)
        st.sidebar.info(
            "\n".join(
                [
                    f"Perfil base: {AppConfig.DEFAULT_BACKTEST_PRESET}",
                    f"Janela base: {AppConfig.DEFAULT_TIMEFRAME} + contexto {AppConfig.PRIMARY_CONTEXT_TIMEFRAME}",
                    f"Familia observada: {symbol_family_label}",
                    f"Analisando: {symbol}",
                ]
            )
        )
    else:
        trading_mode = st.sidebar.radio(
            "Modo de Análise:",
            ["Par Único", "Múltiplos Pares"],
            help="Escolha analisar um par ou monitorar vários simultaneamente"
        )

        if trading_mode == "Múltiplos Pares":
            enable_multi_symbol = True
            selected_symbols = st.sidebar.multiselect(
                "📊 Selecionar pares para monitorar:",
                available_pairs,
                default=available_pairs[:3] if len(available_pairs) >= 3 else available_pairs,
                help="Escolha até 10 pares para análise simultânea"
            )

            if not selected_symbols:
                st.sidebar.warning("⚠️ Selecione pelo menos um par")
                selected_symbols = [available_pairs[0]]

            symbol = selected_symbols[0]

        else:
            enable_multi_symbol = False
            symbol = st.sidebar.selectbox(
                "📈 Par Principal de Trading:",
                available_pairs,
                index=available_pairs.index(AppConfig.DEFAULT_SYMBOL) if AppConfig.DEFAULT_SYMBOL in available_pairs else 0,
                help="Par principal para análise detalhada"
            )
            selected_symbols = [symbol]

    st.sidebar.success(f"✅ Par ativo: {symbol}")
    st.sidebar.info(f"🔄 WebSocket conectará automaticamente ao {symbol.replace('/', '')}")

    # Timeframe selection
    timeframe_default = AppConfig.DEFAULT_TIMEFRAME if AppConfig.DEFAULT_TIMEFRAME in supported_timeframes else supported_timeframes[0]
    timeframe = st.sidebar.selectbox(
        "Timeframe",
        supported_timeframes,
        index=supported_timeframes.index(timeframe_default),
        disabled=AppConfig.SINGLE_SETUP_MODE
    )

    # RSI Parameters - Otimizado para máxima acurácia
    st.sidebar.subheader("📊 Gatilhos RSI do Motor EMA/RSI")
    rsi_period = st.sidebar.slider("Período RSI", 5, 50, AppConfig.DEFAULT_RSI_PERIOD, help="14 períodos é o padrão mais testado")
    rsi_min = st.sidebar.slider("RSI Gatilho Compra", 45, 60, AppConfig.DEFAULT_RSI_MIN, help="RSI precisa cruzar acima deste nivel para compra")
    rsi_max = st.sidebar.slider("RSI Gatilho Venda", 40, 55, AppConfig.DEFAULT_RSI_MAX, help="RSI precisa cruzar abaixo deste nivel para venda")

    # Configurações Avançadas para Day Trading
    with st.sidebar.expander("📈 Day Trading Otimizado", expanded=True):
        st.markdown("**⚡ Configurações para Day Trader**")

        # Modo Day Trading
        day_trading_supported = timeframe in {"1m", "5m", "15m"} and not AppConfig.SINGLE_SETUP_MODE
        day_trading_mode = st.checkbox(
            "🚀 Modo Day Trading",
            value=False,
            disabled=not day_trading_supported,
            help="Configurações otimizadas para operações rápidas"
        )
        if not day_trading_supported:
            st.caption("Modo day trading indisponivel para o timeframe ou setup atual.")

        if day_trading_mode:
            day_settings = AppConfig.get_day_trading_settings(timeframe)

            st.success(f"✅ **Day Trading {timeframe}**: RSI {day_settings['rsi_oversold']}-{day_settings['rsi_overbought']}")
            st.info(f"⚡ Confiança: {day_settings['min_confidence']}% | Volume: {day_settings['min_volume_ratio']}x")

            # Aplicar configurações de day trading
            rsi_min = day_settings['rsi_oversold']
            rsi_max = day_settings['rsi_overbought']
            min_confidence = day_settings['min_confidence']

            # Configurações específicas por timeframe
            if timeframe == "1m":
                st.warning("⚡ **SCALPING MODE** - Apenas para traders experientes")
            elif timeframe == "5m":
                st.success("🎯 **Configuração IDEAL para Day Trading**")

        else:
            # Aplicar configurações automáticas baseadas no timeframe
            crypto_settings = AppConfig.get_crypto_timeframe_settings(timeframe)
            st.info(f"📊 **Auto-Config {timeframe}**: RSI {crypto_settings['rsi_oversold']}-{crypto_settings['rsi_overbought']}, Confiança {crypto_settings['min_confidence']}%")

    # Configurações Avançadas Gerais
    with st.sidebar.expander("⚙️ Configurações Avançadas", expanded=False):

        # Permitir override manual (só se day trading mode estiver desabilitado)
        if not day_trading_mode:
            use_auto_config = st.checkbox("🤖 Usar Configuração Automática", value=True, help="Configuração otimizada para crypto + timeframe")

            if use_auto_config:
                crypto_settings = AppConfig.get_crypto_timeframe_settings(timeframe)
                min_confidence = crypto_settings['min_confidence']
                rsi_min = crypto_settings['rsi_oversold']
                rsi_max = crypto_settings['rsi_overbought']
                st.success(f"✅ Auto: RSI {rsi_min}-{rsi_max}, Confiança {min_confidence}%")
            else:
                st.markdown("**Filtros de Qualidade de Sinal**")
                min_confidence = st.slider("Confiança Mínima (%)", 50, 90, 70, help="Apenas sinais com alta confiança")
        else:
            # Day Trading mode já configurou tudo
            st.markdown("**✅ Day Trading: Configurações Otimizadas Ativas**")

        require_volume = st.checkbox("Exigir Volume Alto", value=False, help="Volume 80%+ acima da média")
        require_trend = st.checkbox("Exigir Tendência Clara", value=False, help="ADX > 28")
        avoid_ranging = st.checkbox("Evitar Mercados Laterais", value=False, help="Filtro anti-ranging")

        # Filtros adicionais - ajustados para day trading
        if day_trading_mode:
            st.markdown("**⚡ Filtros Day Trading**")
            filter_extreme_volatility = st.checkbox("Filtrar Volatilidade Extrema", value=True, help="Evitar ATR > 12% para day trading")
            require_stoch_confirmation = st.checkbox("Exigir StochRSI Extremo", value=True, help="StochRSI < 15 ou > 85")
            peak_hours_only = st.checkbox("Apenas Horários de Pico", value=True, help="9-11h, 14-16h, 20-22h BRT")
            avoid_lunch_time = st.checkbox("Evitar Horário Almoço", value=True, help="12-14h tem menos volume")

            # Alertas específicos para day trading
            st.markdown("**🎯 Alertas Day Trading**")
            alert_volume_spike = st.checkbox("Alertar Picos de Volume", value=True, help="Volume > 3x média")
            alert_breakout = st.checkbox("Alertar Breakouts", value=True, help="Rompimento de Bollinger Bands")

        else:
            st.markdown("**🚀 Filtros Especiais Crypto**")
            filter_extreme_volatility = st.checkbox("Filtrar Volatilidade Extrema", value=True, help="Evitar ATR > 8%")
            require_stoch_confirmation = st.checkbox("Exigir Confirmação StochRSI", value=True, help="StochRSI em extremos")
            peak_hours_only = st.checkbox("Apenas Horários de Pico", value=False, help="8-16h e 20-23h BRT")

    # Auto refresh toggle
    auto_refresh = st.sidebar.checkbox("🔄 Atualização Automática", value=True)
    st.session_state.auto_refresh = auto_refresh

    # Manual refresh button - atualização suave
    if st.sidebar.button("🔄 Atualizar Agora"):
        with st.spinner('🔄 Atualizando dados...'):
            try:
                # Limpar cache de dados
                st.session_state.last_update = None
                st.session_state.current_data = None
                
                # Buscar novos dados
                new_data = st.session_state.trading_bot.get_market_data()
                if new_data is not None:
                    st.session_state.current_data = new_data
                    st.session_state.last_update = get_brazil_datetime_naive()
                    
                st.success("✅ Dados atualizados!")
                # Usar st.rerun para refresh mais suave
                st.rerun()
            except:
                # Fallback para rerun normal se experimental_rerun não funcionar
                st.rerun()

    # Telegram Configuration Section
    st.sidebar.markdown("---")
    # Interface segura de configuração do Telegram
    st.sidebar.subheader("📱 Configuração Telegram")

    if TELEGRAM_AVAILABLE:
        # Status da configuração
        config_status = st.session_state.telegram_bot.get_config_status()

        # Verificar se está configurado via Secrets
        has_secrets = bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))

        if config_status['configured'] or has_secrets:
            if has_secrets:
                st.sidebar.success("✅ Telegram configurado via variaveis de ambiente!")
            else:
                st.sidebar.success("✅ Telegram configurado!")

            # Opções para usuário configurado
            col1, col2 = st.sidebar.columns(2)
            with col1:
                if st.sidebar.button("🧪 Testar"):
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        success, msg = loop.run_until_complete(
                            st.session_state.telegram_bot.test_connection()
                        )
                        if success:
                            st.sidebar.success(msg)
                        else:
                            st.sidebar.error(msg)
                    except Exception as e:
                        st.sidebar.error(f"❌ Erro no teste: {str(e)}")

            with col2:
                if st.sidebar.button("🗑️ Remover"):
                    st.session_state.telegram_bot.disable()
                    st.rerun()

            # Checkbox para ativar notificações
            telegram_enabled = st.sidebar.checkbox(
                "Ativar notificações automáticas",
                value=True,
                help="Enviar sinais automaticamente via Telegram"
            )
            st.session_state.telegram_notifications = telegram_enabled

        else:
            # Interface de configuração
            st.sidebar.info("🔧 Configure seu bot do Telegram para esta sessao:")

            with st.sidebar.form("telegram_config"):
                st.markdown("""
                **Como obter suas credenciais:**
                1. **Token do Bot:** Fale com @BotFather no Telegram
                2. **Chat ID:** Envie /start para @userinfobot
                """)

                bot_token = st.text_input(
                    "🤖 Token do Bot:",
                    type="password",
                    help="Obtido do @BotFather",
                    placeholder="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
                )

                chat_id = st.text_input(
                    "💬 Chat ID:",
                    help="Seu ID de chat pessoal",
                    placeholder="123456789"
                )

                st.caption("Esses dados valem apenas nesta sessao do dashboard. Para persistir, use TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no ambiente.")

                submitted = st.form_submit_button("Aplicar nesta sessao")

                if submitted:
                    if bot_token and chat_id:
                        success, message = st.session_state.telegram_bot.configure(bot_token, chat_id)
                        if success:
                            st.sidebar.success(message)
                            st.rerun()
                        else:
                            st.sidebar.error(message)
                    else:
                        st.sidebar.warning("⚠️ Preencha todos os campos!")

            telegram_enabled = False
            st.session_state.telegram_notifications = False
    else:
        st.sidebar.error("⚠️ Biblioteca Telegram não disponível")
        st.sidebar.info("Execute: pip install python-telegram-bot")
        telegram_enabled = False
        st.session_state.telegram_notifications = False

    # Telegram configuration completed - previous duplicate code removed

    # Update bot configuration apenas se necessário
    config_changed = st.session_state.trading_bot.update_config(
        symbol=symbol,
        timeframe=timeframe,
        rsi_period=rsi_period,
        rsi_min=rsi_min,
        rsi_max=rsi_max
    )

    # Só mostrar logs se a configuração mudou
    if config_changed:
        logger.info(
            "Configuracao do bot atualizada: %s %s RSI(%s) %s-%s",
            symbol,
            timeframe,
            rsi_period,
            rsi_min,
            rsi_max
        )

    live_strategy_settings = get_effective_strategy_settings(
        symbol,
        timeframe,
        require_volume=require_volume,
        require_trend=require_trend,
    )
    active_live_profile = live_strategy_settings.get("active_profile")
    if active_live_profile:
        st.session_state.trading_bot.update_config(
            symbol=symbol,
            timeframe=timeframe,
            rsi_period=live_strategy_settings["rsi_period"],
            rsi_min=live_strategy_settings["rsi_min"],
            rsi_max=live_strategy_settings["rsi_max"],
        )

    # Main dashboard
    st.title("📈 Trading Signals Dashboard")

    # Status do WebSocket Binance removido para interface mais limpa

    # Initialize session state for multi-symbol data
    if 'multi_symbol_data' not in st.session_state:
        st.session_state.multi_symbol_data = {}

    # Import WebSocket trading bot
    try:
        from trading_bot_websocket import StreamlinedTradingBot
        WEBSOCKET_AVAILABLE = True
    except ImportError:
        WEBSOCKET_AVAILABLE = False

    # Futures trading nao e usado na dashboard atual.
    FUTURES_AVAILABLE = False

    # Initialize futures trading if available (with error handling)
    if 'futures_trading' not in st.session_state:
        if FUTURES_AVAILABLE:
            try:
                st.session_state.futures_trading = FuturesTrading()
            except Exception as e:
                st.sidebar.warning(f"⚠️ Futures trading não disponível: {str(e)}")
                st.session_state.futures_trading = None
                FUTURES_AVAILABLE = False
        else:
            st.session_state.futures_trading = None

    dashboard_sections = [
        ("workspace", "👤 Meu Workspace"),
        ("websocket", "📡 WebSocket Binance"),
        ("futures", "🚀 Análise Mercado Futuro"),
        ("backtest", "🔬 Backtesting"),
        ("export", "⚙️ Exportar Dados"),
        ("admin", "👑 Admin Panel"),
    ]
    dashboard_section_labels = [label for _, label in dashboard_sections]
    dashboard_section_by_label = {label: section_id for section_id, label in dashboard_sections}
    default_dashboard_section = str(st.session_state.get("default_tab") or "backtest").strip().lower()
    default_dashboard_index = next(
        (index for index, (section_id, _) in enumerate(dashboard_sections) if section_id == default_dashboard_section),
        3,
    )

    selected_dashboard_label = st.radio(
        "Seção da Dashboard",
        dashboard_section_labels,
        index=default_dashboard_index,
        horizontal=True,
        key="dashboard_main_section",
        label_visibility="collapsed",
    )
    active_dashboard_section = dashboard_section_by_label[selected_dashboard_label]
    st.session_state.default_tab = active_dashboard_section

    if active_dashboard_section == "workspace":
        render_multiuser_workspace_tab()

    # Nova aba para WebSocket Binance Futures
    if active_dashboard_section == "websocket":
        st.subheader("📡 Binance Futures WebSocket - Dados em Tempo Real")
        st.markdown("**Análise otimizada com streaming de dados em tempo real da Binance**")
        
        if WEBSOCKET_AVAILABLE:
            # Interface limpa do WebSocket
                
            # Auto-conectar WebSocket baseado na configuração da sidebar
            st.success(f"📊 **Auto-Conectado:** {symbol} | **Timeframe:** {timeframe}")
            st.info("🚀 *WebSocket conecta automaticamente com as configurações da sidebar*")
            
            # Configurações WebSocket usando o stream compartilhado do TradingBot
            ws_display_symbol = symbol.replace('/', '')  # BTC/USDT -> BTCUSDT
            ws_timeframe = timeframe
            ws_key = f"{symbol}_{ws_timeframe}"
            stream_client = None
            stream_status = None

            if 'ws_auto_connected' not in st.session_state:
                st.session_state.ws_auto_connected = False
            if 'ws_current_key' not in st.session_state:
                st.session_state.ws_current_key = None

            try:
                stream_client = st.session_state.trading_bot._get_realtime_stream_client(
                    symbol=symbol,
                    timeframe=ws_timeframe,
                )
                stream_status = stream_client.get_current_status()
                st.session_state.ws_auto_connected = True
                if st.session_state.get('ws_current_key') != ws_key:
                    st.session_state.ws_current_key = ws_key
                    st.success(f"✅ Stream compartilhado pronto para {ws_display_symbol}")
            except Exception as e:
                st.session_state.ws_auto_connected = False
                stream_client = None
                stream_status = None
                st.error(f"❌ Erro ao inicializar stream compartilhado: {e}")
            
            # Status e controles do WebSocket
            col1, col2, col3 = st.columns(3)
            
            with col1:
                if stream_status and stream_status.get("connected"):
                    st.success("🟢 **Conectado**")
                    if enable_multi_symbol:
                        st.info(f"📊 Modo: {len(selected_symbols)} pares")
                    else:
                        st.info(f"📈 Foco: {symbol}")
                elif stream_client:
                    st.warning("🟡 **Conectando**")
                else:
                    st.error("🔴 **Desconectado**")
                        
            with col2:
                if st.button("📊 Status Detalhado"):
                    if stream_client:
                        try:
                            status = stream_client.get_current_status()
                            st.json(status)
                        except:
                            st.info("📊 Bot ativo - Status em tempo real")
                    else:
                        st.warning("⚠️ Bot não inicializado")
                        
            with col3:
                if st.button("🔄 Reconectar"):
                    try:
                        st.session_state.trading_bot.reset_stream_client(
                            symbol=symbol,
                            timeframe=ws_timeframe,
                        )
                        stream_client = st.session_state.trading_bot._get_realtime_stream_client(
                            symbol=symbol,
                            timeframe=ws_timeframe,
                        )
                        stream_status = stream_client.get_current_status()
                        st.session_state.ws_auto_connected = True
                        st.session_state.ws_current_key = ws_key
                        st.success("✅ WebSocket reconectado")
                    except Exception as e:
                        st.session_state.ws_auto_connected = False
                        st.error(f"❌ Erro na reconexão: {e}")
            
            # Área de dados em tempo real 
            if stream_client:
                st.markdown("---")
                st.subheader("📈 Dados em Tempo Real - Streaming WebSocket")
                
                # Status do streaming
                st.success("🔗 **WebSocket ativo** - Dados atualizados automaticamente")
                
                # Informações de conexão
                st.info(f"📡 Streaming para {ws_display_symbol} no timeframe {ws_timeframe}")
                
                # Métricas em tempo real
                col1, col2, col3, col4 = st.columns(4)
                market_data = st.session_state.get("current_data")
                latest_market_row = None
                if isinstance(market_data, pd.DataFrame) and not market_data.empty:
                    latest_market_row = market_data.iloc[-1]
                
                with col1:
                    try:
                        price = float((stream_status or {}).get("last_price") or 0)
                        if price <= 0 and latest_market_row is not None:
                            price = float(latest_market_row.get("close", 0) or 0)
                        if price > 0:
                            st.metric(
                                label="💰 Preço",
                                value=f"${price:.6f}",
                                delta="WebSocket"
                            )
                        else:
                            st.metric(
                                label="💰 Preço",
                                value="Conectando...",
                                delta="Aguarde"
                            )
                    except:
                        st.metric(
                            label="💰 Preço",
                            value="Carregando...",
                            delta="WebSocket"
                        )
                        
                with col2:
                    rsi_value = None
                    if latest_market_row is not None:
                        rsi_value = latest_market_row.get("rsi")
                    st.metric(
                        label="📊 RSI",
                        value=f"{float(rsi_value):.2f}" if pd.notna(rsi_value) else "Aguardando",
                        delta="Indicadores"
                    )
                    
                with col3:
                    macd_value = None
                    if latest_market_row is not None:
                        macd_value = latest_market_row.get("macd")
                    st.metric(
                        label="📈 MACD",
                        value=f"{float(macd_value):.4f}" if pd.notna(macd_value) else "Aguardando",
                        delta="Indicadores"
                    )
                    
                with col4:
                    try:
                        signal = "AGUARDANDO"
                        if latest_market_row is not None:
                            signal = latest_market_row.get("signal") or signal
                        elif stream_status and stream_status.get("connected"):
                            signal = "STREAMING"
                        st.metric(
                            label="🎯 Sinal",
                            value=signal,
                            delta="Compartilhado"
                        )
                    except:
                        st.metric(
                            label="🎯 Sinal",
                            value="CONECTANDO",
                            delta="WebSocket"
                        )
                
                st.success("✅ **Stream compartilhado ativo** - UI e analise usam a mesma conexao")
                    
            # Informações sobre dados públicos
            with st.expander("ℹ️ Sobre WebSocket Público Binance Futures", expanded=False):
                st.markdown("""
                **🔗 Conexão WebSocket Pública:**
                
                ✅ **Sem credenciais necessárias**
                - Dados de preço em tempo real
                - Volume e estatísticas 24h
                - Candlesticks (klines) ao vivo
                
                📊 **Análise Técnica:**
                - RSI, MACD, Bollinger Bands
                - Médias móveis (SMA, EMA)
                - Sinais de compra/venda automáticos
                
                ⚡ **Vantagens:**
                - Loop automático a cada 60 segundos
                - Sem limite de rate API  
                - Dados em tempo real
                - Totalmente gratuito
                
                ⏰ **Funcionamento:**
                - Análise executada automaticamente a cada 1 minuto
                - Sinais gerados com base em dados públicos
                - Indicadores calculados em tempo real
                """)
                
            # Área de logs WebSocket
            with st.expander("📋 Logs WebSocket", expanded=False):
                if 'ws_logs' not in st.session_state:
                    st.session_state.ws_logs = []
                    
                if st.session_state.ws_logs:
                    for log in st.session_state.ws_logs[-10:]:  # Últimos 10 logs
                        st.text(log)
                else:
                    st.text("Nenhum log disponível")
                    
        else:
            st.error("❌ **WebSocket não disponível** - Módulo não carregado")
            st.info("Verifique se todas as dependências estão instaladas")

    # Continuar com as abas existentes...

    # Set default tab to Backtesting if requested
    if 'default_tab' not in st.session_state:
        st.session_state.default_tab = 'backtest'

    if active_dashboard_section == "futures":
        st.subheader("🚀 Trading de Mercado Futuro")
        st.markdown("**Trade com alavancagem, posições long/short e gerenciamento avançado de risco**")
        st.info(
            "Escopo desta aba: análise operacional em tempo real (preço, contexto, sinais e risco). "
            "Não usa curva histórica de backtest para decisão."
        )

        # Warning banner
        st.warning("⚠️ **ATENÇÃO:** Mercado futuro envolve alto risco. Nunca arrisque mais do que pode perder!")

        # Configurações específicas de futuros na sidebar expandida
        st.sidebar.markdown("---")
        st.sidebar.subheader("🚀 Configurações Futuros")

        futures_leverage = st.sidebar.selectbox(
            "Alavancagem",
            [1, 2, 3, 5, 10, 20, 25, 50],
            index=3,
            help="Multiplicador de posição"
        )

        futures_mode = st.sidebar.selectbox(
            "Modo de Trading",
            ["Cross Margin", "Isolated Margin"],
            help="Cross: usa todo saldo | Isolated: limita risco por posição"
        )

        risk_level = st.sidebar.selectbox(
            "Nível de Risco",
            ["Conservador", "Moderado", "Agressivo"],
            index=1
        )

        # Tabs dentro da análise de futuros
        futures_tab1, futures_tab2, futures_tab3 = st.tabs([
            "🎯 Sinais & Análise", "⚖️ Calculadoras", "📊 Cenários Teóricos"
        ])

    # Tab 1: Análise e Sinais para Futuros
        with futures_tab1:
            st.markdown("### 🎯 Análise Técnica para Futuros")

            # Multi-Symbol Overview (if enabled) - with caching and performance optimization
            if enable_multi_symbol and len(selected_symbols) > 1:
                st.subheader("🔀 Overview - Múltiplos Pares")

            # Initialize multi-symbol last signals tracking
            if 'multi_symbol_signals' not in st.session_state:
                st.session_state.multi_symbol_signals = {}

            # Create overview table for all selected symbols
            overview_data = []
            current_time = now_brazil()

            for sym in selected_symbols:
                # Initialize variables at the start of each iteration
                analytical_signal = "NEUTRO"
                last_candle = None
                sym_data = None
                signal_pipeline = None
                operational_state = None
                data_last_update = None

                try:
                    symbol_strategy_settings = get_effective_strategy_settings(
                        sym,
                        timeframe,
                        require_volume=require_volume,
                        require_trend=require_trend,
                        avoid_ranging=avoid_ranging,
                    )

                    # Check if we have cached data for this symbol that's less than 60 seconds old
                    cache_key = f"{sym}_{timeframe}_{symbol_strategy_settings['strategy_version']}"
                    should_refresh = True
                    cached_data = None
                    cache_age = 0

                    if cache_key in st.session_state.multi_symbol_data:
                        cached_data = st.session_state.multi_symbol_data[cache_key]
                        cache_age = (current_time - cached_data['last_update']).total_seconds()
                        # Cache mais agressivo para reduzir API calls
                        cache_timeout = 30 if len(selected_symbols) > 5 else 60
                        if cached_data['last_update'] and cache_age < cache_timeout:
                            should_refresh = False
                            sym_data = cached_data['data']
                            analytical_signal = cached_data.get('analytical_signal', "NEUTRO")
                            last_candle = cached_data['last_candle']
                            signal_pipeline = cached_data.get('signal_pipeline')
                            operational_state = cached_data.get('operational_state')
                            data_last_update = cached_data.get('last_update')

                    if should_refresh:
                        # Mostrar progresso para símbolos múltiplos
                        with st.spinner(f'📡 Atualizando {sym}...'):
                            try:
                                # Use shared trading bot instance
                                st.session_state.trading_bot.update_config(
                                    symbol=sym,
                                    timeframe=timeframe,
                                    rsi_period=symbol_strategy_settings["rsi_period"],
                                    rsi_min=symbol_strategy_settings["rsi_min"],
                                    rsi_max=symbol_strategy_settings["rsi_max"],
                                )
                                sym_data = st.session_state.trading_bot.get_market_data(limit=200)

                                if sym_data is not None and not sym_data.empty:
                                    last_candle = sym_data.iloc[-1]
                                    signal_pipeline = st.session_state.trading_bot.evaluate_signal_pipeline(
                                        sym_data,
                                        min_confidence=min_confidence,
                                        timeframe=timeframe,
                                        require_volume=symbol_strategy_settings["require_volume"],
                                        require_trend=symbol_strategy_settings["require_trend"],
                                        avoid_ranging=symbol_strategy_settings.get("avoid_ranging", avoid_ranging),
                                        day_trading_mode=day_trading_mode,
                                        context_timeframe=symbol_strategy_settings.get("context_timeframe"),
                                        stop_loss_pct=symbol_strategy_settings.get("stop_loss_pct"),
                                        take_profit_pct=symbol_strategy_settings.get("take_profit_pct"),
                                        allowed_execution_setups=symbol_strategy_settings.get("allowed_execution_setups"),
                                    )
                                    analytical_signal = signal_pipeline["analytical_signal"]
                                    data_last_update = current_time

                                    # Cache the data com timestamp
                                    st.session_state.multi_symbol_data[cache_key] = {
                                        'data': sym_data,
                                        'analytical_signal': analytical_signal,
                                        'last_candle': last_candle,
                                        'last_update': data_last_update,
                                        'signal_pipeline': signal_pipeline,
                                        'operational_state': operational_state,
                                    }
                                else:
                                    continue
                            except Exception as e:
                                st.warning(f"⚠️ Erro ao atualizar {sym}: {str(e)}")
                                continue

                    # Skip if we don't have valid data
                    if last_candle is None:
                        continue

                    is_data_fresh, data_age_seconds = _is_data_fresh(
                        data_last_update,
                        max_age_seconds=MAX_SIGNAL_DATA_AGE_SECONDS,
                        now_reference=current_time,
                    )
                    if not is_data_fresh:
                        operational_state = _build_stale_data_operational_state(
                            data_age_seconds,
                            max_age_seconds=MAX_SIGNAL_DATA_AGE_SECONDS,
                        )
                    elif operational_state is None:
                        operational_state = build_operational_signal_state(
                            analytical_signal,
                            float(last_candle['close']),
                            symbol_strategy_settings,
                            regime_evaluation=(signal_pipeline or {}).get("regime_evaluation"),
                        )

                    if cache_key in st.session_state.multi_symbol_data:
                        st.session_state.multi_symbol_data[cache_key]['operational_state'] = operational_state

                    candidate_signal = (signal_pipeline or {}).get("candidate_signal", "NEUTRO")
                    approved_signal = (signal_pipeline or {}).get("approved_signal")
                    blocked_signal = (signal_pipeline or {}).get("blocked_signal")
                    analytical_block_reason = (signal_pipeline or {}).get("block_reason")
                    operational_signal = (operational_state or {}).get("final_signal", "NEUTRO")

                    # Check for new signals to send alerts
                    if (operational_signal not in ["NEUTRO"] and 
                        st.session_state.telegram_notifications and 
                        st.session_state.telegram_bot.is_configured()):

                        # Check if this is a new signal for this symbol
                        last_signal_key = f"{sym}_last_signal"
                        if (last_signal_key not in st.session_state.multi_symbol_signals or 
                            st.session_state.multi_symbol_signals[last_signal_key]['signal'] != operational_signal or
                            (current_time - st.session_state.multi_symbol_signals[last_signal_key]['timestamp']).total_seconds() > 300):

                            # Send alert for this symbol
                            try:
                                loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(loop)
                                loop.run_until_complete(
                                    st.session_state.telegram_bot.send_signal_alert(
                                        symbol=sym,
                                        signal=operational_signal,
                                        price=last_candle['close'],
                                        rsi=last_candle['rsi'],
                                        macd=last_candle['macd'],
                                        macd_signal=last_candle['macd_signal']
                                    )
                                )

                                # Update last signal tracking
                                st.session_state.multi_symbol_signals[last_signal_key] = {
                                    'signal': operational_signal,
                                    'timestamp': current_time
                                }
                            except Exception as e:
                                pass  # Silent fail for overview performance

                    history_signature = (
                        candidate_signal,
                        approved_signal or "NEUTRO",
                        blocked_signal or "-",
                        operational_signal,
                        analytical_block_reason or "-",
                        (operational_state or {}).get("block_reason") or "-",
                    )
                    should_record_history = (
                        candidate_signal in ACTIONABLE_SIGNALS
                        or approved_signal in ACTIONABLE_SIGNALS
                        or blocked_signal in ACTIONABLE_SIGNALS
                    )
                    if should_record_history:
                        previous_entry = st.session_state.signals_history[-1] if st.session_state.signals_history else None
                        previous_signature = None
                        if previous_entry and previous_entry.get('symbol') == sym and previous_entry.get('timeframe') == timeframe:
                            previous_signature = (
                                previous_entry.get('candidate_signal', 'NEUTRO'),
                                previous_entry.get('approved_signal') or "NEUTRO",
                                previous_entry.get('blocked_signal') or "-",
                                previous_entry.get('operational_signal', previous_entry.get('signal', 'NEUTRO')),
                                previous_entry.get('block_reason') or "-",
                                previous_entry.get('operational_block_reason') or "-",
                            )
                        if (
                            previous_signature != history_signature
                            or not previous_entry
                            or _compare_timestamps(previous_entry['timestamp'], current_time - timedelta(minutes=5))
                        ):
                            st.session_state.signals_history.append({
                                'timestamp': current_time,
                                'symbol': sym,
                                'timeframe': timeframe,
                                'price': last_candle['close'],
                                'rsi': last_candle['rsi'],
                                'macd': last_candle['macd'],
                                'macd_signal': last_candle['macd_signal'],
                                'signal': operational_signal,
                                'candidate_signal': candidate_signal,
                                'approved_signal': approved_signal,
                                'blocked_signal': blocked_signal,
                                'block_reason': analytical_block_reason,
                                'block_source': (signal_pipeline or {}).get("block_source"),
                                'operational_signal': operational_signal,
                                'operational_block_reason': (operational_state or {}).get("block_reason"),
                            })

                    # Only add to overview if we have valid data
                    if last_candle is not None:
                        overview_data.append({
                            'Par': sym,
                            'Preço': f"${last_candle['close']:.6f}",
                            'RSI': f"{last_candle['rsi']:.2f}",
                            'MACD': f"{last_candle['macd']:.4f}",
                            'Candidato': candidate_signal,
                            'Aprovado': approved_signal or "NEUTRO",
                            'Bloqueado': blocked_signal or "-",
                            'Motivo Bloqueio': analytical_block_reason or "-",
                            'Sinal Operacional': operational_signal,
                            'Long Score': 'N/A',
                            'Short Score': 'N/A',
                            'Variação': f"{((last_candle['close'] - last_candle['open']) / last_candle['open'] * 100):.2f}%"
                        })

                except Exception as e:
                    overview_data.append({
                        'Par': sym,
                        'Preço': 'Erro',
                        'RSI': 'N/A',
                        'MACD': 'N/A', 
                        'Candidato': 'ERRO',
                        'Aprovado': 'ERRO',
                        'Bloqueado': '-',
                        'Motivo Bloqueio': str(e),
                        'Sinal Operacional': 'ERRO',
                        'Long Score': 'N/A',
                        'Short Score': 'N/A',
                        'Variação': 'N/A'
                    })

            # Trim signals history to last 50 across all symbols
            if len(st.session_state.signals_history) > 50:
                st.session_state.signals_history = st.session_state.signals_history[-50:]

            if overview_data:
                overview_df = pd.DataFrame(overview_data)

                # Style the dataframe
                def style_futures_signals(val):
                    if isinstance(val, str):
                        if val == 'COMPRA':
                            return 'background-color: #90EE90'
                        elif val == 'VENDA':
                            return 'background-color: #FFB6C1'
                    elif isinstance(val, (int, float)):
                        if val >= 70:
                            return 'background-color: #90EE90'
                        elif val >= 50:
                            return 'background-color: #FFFF99'
                        elif val <= 30:
                            return 'background-color: #FFB6C1'
                    return ''

                styled_df = overview_df.style.map(style_futures_signals)
                st.dataframe(styled_df, width='stretch', hide_index=True)

            st.markdown("---")

            # Usar símbolo configurado centralmente
            futures_symbol = symbol  # Usar o símbolo já configurado na sidebar
            
            st.subheader(f"📈 Análise Detalhada de Futuros - {futures_symbol}")
            st.success(f"✅ **Configuração Ativa:** {futures_symbol} | {timeframe} | RSI({rsi_period}) {rsi_min}-{rsi_max}")
            st.info("💡 *Configurações centralizadas na barra lateral* ⬅️")

    # Helper function para calcular scores de futuros
    def _calculate_futures_score(last_candle, position_type):
        """Calcular score específico para posições LONG/SHORT em futuros"""
        try:
            score = 0

            # RSI scoring
            rsi = last_candle.get('rsi', 50)
            if position_type == 'LONG':
                if rsi < 30: score += 30
                elif rsi < 40: score += 20
                elif rsi > 70: score -= 20
            else:  # SHORT
                if rsi > 70: score += 30
                elif rsi > 60: score += 20
                elif rsi < 30: score -= 20

            # MACD scoring
            macd = last_candle.get('macd', 0)
            macd_signal = last_candle.get('macd_signal', 0)

            if position_type == 'LONG':
                if macd > macd_signal: score += 25
                if last_candle.get('macd_histogram', 0) > 0: score += 15
            else:  # SHORT
                if macd < macd_signal: score += 25
                if last_candle.get('macd_histogram', 0) < 0: score += 15

            # Volume scoring
            volume_ratio = last_candle.get('volume_ratio', 1)
            if volume_ratio > 1.5: score += 15
            elif volume_ratio > 1.2: score += 10

            # Trend scoring (simplified)
            sma_21 = last_candle.get('sma_21', last_candle['close'])
            if position_type == 'LONG':
                if last_candle['close'] > sma_21: score += 15
            else:  # SHORT
                if last_candle['close'] < sma_21: score += 15

            return min(max(score, 0), 100)  # Normalize to 0-100

        except Exception:
            return 0

    # Telegram Configuration Card (if not configured)
    has_secrets_main = bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))
    if not st.session_state.telegram_bot.is_configured() and not has_secrets_main:
        with st.expander("📱 Configurar Notificações Telegram", expanded=False):
            st.markdown("Configure o bot do Telegram para receber alertas de sinais em tempo real!")

            col1, col2 = st.columns(2)

            with col1:
                telegram_token_main = st.text_input(
                    "🤖 Token do Bot",
                    type="password",
                    placeholder="1234567890:ABC-def_GhIjKlMnOpQrStUvWxYz",
                    help="1. Acesse @BotFather no Telegram\n2. Digite /newbot\n3. Siga as instruções\n4. Cole o token aqui",
                    key="telegram_token_main"
                )

            with col2:
                telegram_chat_id_main = st.text_input(
                    "💬 Chat ID",
                    placeholder="-1001234567890 ou 123456789",
                    help="1. Adicione @userinfobot ao seu chat\n2. Digite /start\n3. Cole o Chat ID aqui",
                    key="telegram_chat_id_main"
                )

            col1, col2, col3 = st.columns([1, 1, 2])

            with col1:
                if st.button("✅ Configurar", key="config_telegram_main"):
                    if telegram_token_main and telegram_chat_id_main:
                        success, message = st.session_state.telegram_bot.configure(
                            telegram_token_main,
                            telegram_chat_id_main
                        )
                        if success:
                            st.session_state.telegram_notifications = True
                            try:
                                loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(loop)
                                success, message = loop.run_until_complete(
                                    st.session_state.telegram_bot.test_connection()
                                )
                                if success:
                                    st.success("✅ Telegram configurado com sucesso!")
                                    st.rerun()
                                else:
                                    st.error(f"❌ Erro: {message}")
                            except Exception as e:
                                st.error(f"❌ Erro ao testar: {str(e)}")
                        else:
                            st.error(f"❌ {message}")
                    else:
                        st.warning("⚠️ Preencha ambos os campos")

            with col2:
                if telegram_token_main and telegram_chat_id_main:
                    if st.button("📤 Testar", key="test_telegram_main"):
                        temp_bot = st.session_state.telegram_bot
                        success, message = temp_bot.configure(
                            telegram_token_main,
                            telegram_chat_id_main
                        )
                        if success:
                            try:
                                loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(loop)
                                success, message = loop.run_until_complete(
                                    temp_bot.send_custom_message("🧪 Teste do bot de trading!")
                                )
                                if success:
                                    st.success("✅ Mensagem enviada!")
                                else:
                                    st.error(f"❌ {message}")
                            except Exception as e:
                                st.error(f"❌ Erro: {str(e)}")
                        else:
                            st.error(f"❌ {message}")

            with col3:
                st.info("💡 **Como configurar:**\n1. Crie um bot no @BotFather\n2. Obtenha seu Chat ID no @userinfobot\n3. Configure aqui")

    # Status indicators for main symbol - usando containers para atualização suave
    status_container = st.container()
    with status_container:
        col1, col2, col3, col4, col5 = st.columns(5)

    # Check if we need to update data
    should_update = (
        st.session_state.last_update is None or 
        (get_brazil_datetime_naive() - st.session_state.last_update).total_seconds() > 60
    )

    if should_update:
        try:
            with st.spinner('Carregando dados...'):
                data = st.session_state.trading_bot.get_market_data()
                if data is not None:
                    st.session_state.current_data = data
                    st.session_state.last_update = get_brazil_datetime_naive()
        except Exception as e:
            st.error(f"Erro ao carregar dados: {str(e)}")

    # Store multi-symbol data (already initialized above)

    if st.session_state.current_data is not None:
        data = st.session_state.current_data
        last_candle = data.iloc[-1]
        data_is_fresh, data_age_seconds = _is_data_fresh(
            st.session_state.last_update,
            max_age_seconds=MAX_SIGNAL_DATA_AGE_SECONDS,
        )
        guardrail_edge_summary = None
        risk_plan = None
        live_strategy_settings = get_effective_strategy_settings(
            symbol,
            timeframe,
            require_volume=require_volume,
            require_trend=require_trend,
            avoid_ranging=avoid_ranging,
        )
        runtime_strategy_version = live_strategy_settings["strategy_version"]
        guardrail_edge_summary = None
        context_evaluation = None
        regime_evaluation = None
        structure_evaluation = None
        confirmation_evaluation = None
        entry_quality_evaluation = None
        hard_block_evaluation = None
        signal_pipeline = st.session_state.trading_bot.evaluate_signal_pipeline(
            data,
            min_confidence=min_confidence,
            timeframe=timeframe,
            require_volume=live_strategy_settings["require_volume"],
            require_trend=live_strategy_settings["require_trend"],
            avoid_ranging=live_strategy_settings.get("avoid_ranging", avoid_ranging),
            day_trading_mode=day_trading_mode,
            context_timeframe=live_strategy_settings.get("context_timeframe"),
            stop_loss_pct=live_strategy_settings.get("stop_loss_pct"),
            take_profit_pct=live_strategy_settings.get("take_profit_pct"),
            allowed_execution_setups=live_strategy_settings.get("allowed_execution_setups"),
        )
        candidate_signal = signal_pipeline["candidate_signal"]
        analytical_signal = signal_pipeline["analytical_signal"]
        approved_signal = signal_pipeline.get("approved_signal")
        blocked_signal = signal_pipeline.get("blocked_signal")
        analytical_block_reason = signal_pipeline.get("block_reason")
        context_evaluation = signal_pipeline.get("context_evaluation")
        regime_evaluation = signal_pipeline.get("regime_evaluation")
        structure_evaluation = signal_pipeline.get("structure_evaluation")
        confirmation_evaluation = signal_pipeline.get("confirmation_evaluation")
        entry_quality_evaluation = signal_pipeline.get("entry_quality_evaluation")
        scenario_evaluation = signal_pipeline.get("scenario_evaluation")
        trade_decision = signal_pipeline.get("trade_decision")
        hard_block_evaluation = signal_pipeline.get("hard_block_evaluation")

        if data_is_fresh:
            operational_state = build_operational_signal_state(
                analytical_signal,
                float(last_candle['close']),
                live_strategy_settings,
                regime_evaluation=regime_evaluation,
            )
        else:
            operational_state = _build_stale_data_operational_state(
                data_age_seconds,
                max_age_seconds=MAX_SIGNAL_DATA_AGE_SECONDS,
            )

        signal = operational_state["final_signal"]
        guardrail_edge_summary = operational_state["edge_summary"]
        risk_plan = operational_state["risk_plan"]
        governance_summary = operational_state.get("governance_summary")
        operational_block_reason = operational_state["block_reason"]
        operational_block_source = operational_state["block_source"]
        risk_guardrail_blocked = bool(risk_plan and not risk_plan.get("allowed"))
        entry_reason = analytical_signal
        if analytical_signal != "NEUTRO":
            reason_parts = [analytical_signal]
            if context_evaluation:
                reason_parts.append(
                    f"ctx:{context_evaluation.get('market_bias', 'neutral')}/{context_evaluation.get('regime', '-')}"
                )
            if regime_evaluation:
                reason_parts.append(
                    f"regime:{regime_evaluation.get('regime', '-')}/{regime_evaluation.get('volatility_state', '-')}"
                )
            if structure_evaluation:
                reason_parts.append(
                    f"struct:{structure_evaluation.get('structure_state', '-')}/{structure_evaluation.get('price_location', '-')}"
                )
            if confirmation_evaluation:
                reason_parts.append(
                    f"confirm:{confirmation_evaluation.get('confirmation_state', '-')}/{confirmation_evaluation.get('confirmation_score', 0):.1f}"
                )
            if entry_quality_evaluation:
                reason_parts.append(
                    f"entry:{entry_quality_evaluation.get('setup_type') or '-'}"
                    f"/{entry_quality_evaluation.get('entry_quality', '-')}"
                    f"/s{float(entry_quality_evaluation.get('entry_score', 0) or 0):.1f}"
                )
            if scenario_evaluation:
                reason_parts.append(
                    f"scenario:{scenario_evaluation.get('scenario_grade', '-')}/{scenario_evaluation.get('scenario_score', 0):.2f}"
                )
            entry_reason = " | ".join(reason_parts)

        try:
            get_paper_trade_service().evaluate_open_trades(symbol=symbol, timeframe=timeframe, market_data=data)
        except Exception as e:
            logger.warning("Falha ao avaliar paper trades do dashboard: %s", e)

        # Store data for multi-symbol monitoring
        st.session_state.multi_symbol_data[symbol] = {
            'data': data,
            'analytical_signal': analytical_signal,
            'last_candle': last_candle,
            'last_update': st.session_state.last_update,
            'edge_summary': guardrail_edge_summary,
            'risk_plan': risk_plan,
            'governance_summary': governance_summary,
            'signal_pipeline': signal_pipeline,
            'operational_state': operational_state,
            'context_evaluation': context_evaluation,
            'regime_evaluation': regime_evaluation,
            'structure_evaluation': structure_evaluation,
            'confirmation_evaluation': confirmation_evaluation,
            'entry_quality_evaluation': entry_quality_evaluation,
            'hard_block_evaluation': hard_block_evaluation,
        }

        history_signature = (
            candidate_signal,
            approved_signal or "NEUTRO",
            blocked_signal or "-",
            signal,
            analytical_block_reason or "-",
            operational_block_reason or "-",
        )
        previous_entry = st.session_state.signals_history[-1] if st.session_state.signals_history else None
        previous_signature = None
        if previous_entry and previous_entry.get('symbol') == symbol and previous_entry.get('timeframe') == timeframe:
            previous_signature = (
                previous_entry.get('candidate_signal', 'NEUTRO'),
                previous_entry.get('approved_signal') or "NEUTRO",
                previous_entry.get('blocked_signal') or "-",
                previous_entry.get('operational_signal', previous_entry.get('signal', 'NEUTRO')),
                previous_entry.get('block_reason') or "-",
                previous_entry.get('operational_block_reason') or "-",
            )

        # Add signal to history if it's a new analytical event
        if (
            candidate_signal in ACTIONABLE_SIGNALS
            or approved_signal in ACTIONABLE_SIGNALS
            or blocked_signal in ACTIONABLE_SIGNALS
        ) and (
            previous_signature != history_signature or
            not previous_entry or
            _compare_timestamps(st.session_state.signals_history[-1]['timestamp'], get_brazil_datetime_naive() - timedelta(minutes=5))
        ):
            # Send Telegram notification if enabled
            if st.session_state.telegram_notifications and st.session_state.telegram_bot.is_configured():
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(
                        st.session_state.telegram_bot.send_signal_alert(
                            symbol=symbol,
                            signal=signal,
                            price=last_candle['close'],
                            rsi=last_candle['rsi'],
                            macd=last_candle['macd'],
                            macd_signal=last_candle['macd_signal']
                        )
                    )
                except Exception as e:
                    st.sidebar.warning(f"⚠️ Erro ao enviar alerta: {str(e)}")

            # Criar dados do sinal para salvar
            signal_data = {
                'timestamp': get_brazil_datetime_naive(),
                'symbol': symbol,
                'timeframe': timeframe,
                'price': last_candle['close'],
                'rsi': last_candle['rsi'],
                'macd': last_candle['macd'],
                'macd_signal': last_candle['macd_signal'],
                'signal': signal,
                'candidate_signal': candidate_signal,
                'approved_signal': approved_signal,
                'blocked_signal': blocked_signal,
                'block_reason': analytical_block_reason,
                'block_source': (hard_block_evaluation or {}).get("block_source"),
                'operational_signal': signal,
                'operational_block_reason': operational_block_reason,
                'context_timeframe': live_strategy_settings.get("context_timeframe"),
                'strategy_version': runtime_strategy_version,
                'regime': (regime_evaluation or {}).get("regime"),
                'macd_value': last_candle['macd'],
                'signal_strength': abs(last_candle['rsi'] - 50) / 50,  # Força do sinal baseada no RSI
                'volume': last_candle.get('volume', 0)
            }

            # Salvar no banco de dados
            try:
                db.save_trading_signal(signal_data)
            except Exception as e:
                st.error(f"Erro ao salvar sinal no banco: {str(e)}")

            try:
                if risk_plan and risk_plan.get("allowed"):
                    fallback_signal_score = last_candle.get("signal_confidence")
                    if fallback_signal_score is None or pd.isna(fallback_signal_score):
                        fallback_signal_score = st.session_state.trading_bot.get_signal_with_confidence(data).get(
                            "confidence",
                            0.0,
                        )
                    get_paper_trade_service().register_signal(
                        symbol=symbol,
                        timeframe=timeframe,
                        signal=signal,
                        entry_price=float(last_candle['close']),
                        entry_timestamp=signal_data['timestamp'],
                        context_timeframe=live_strategy_settings.get("context_timeframe"),
                        source="dashboard",
                        strategy_version=runtime_strategy_version,
                        stop_loss_pct=live_strategy_settings.get("stop_loss_pct"),
                        take_profit_pct=live_strategy_settings.get("take_profit_pct"),
                        risk_plan=risk_plan,
                        setup_name=(entry_quality_evaluation or {}).get("setup_type") or runtime_strategy_version,
                        regime=(regime_evaluation or {}).get("regime") or last_candle.get("market_regime"),
                        signal_score=(entry_quality_evaluation or {}).get("entry_score", fallback_signal_score),
                        atr=last_candle.get("atr", 0.0),
                        entry_reason=entry_reason,
                        entry_quality=(entry_quality_evaluation or {}).get("entry_quality"),
                        rejection_reason=(entry_quality_evaluation or {}).get("rejection_reason"),
                        sample_type="paper",
                    )
            except Exception as e:
                logger.warning("Falha ao registrar paper trade do dashboard: %s", e)

            # Manter no histórico da sessão também
            st.session_state.signals_history.append(signal_data)

            # Keep only last 50 signals
            if len(st.session_state.signals_history) > 50:
                st.session_state.signals_history = st.session_state.signals_history[-50:]

        # Display current metrics - com containers para atualização suave
        with col1:
            price_container = st.empty()
            with price_container.container():
                st.metric(
                    label="💰 Preço Atual",
                    value=f"${last_candle['close']:.6f}",
                    delta=f"{((last_candle['close'] - last_candle['open']) / last_candle['open'] * 100):.2f}%"
                )

        with col2:
            rsi_color = "normal"
            if last_candle['rsi'] > rsi_max:
                rsi_color = "inverse"
            elif last_candle['rsi'] < rsi_min:
                rsi_color = "inverse"

            st.metric(
                label="📊 RSI",
                value=f"{last_candle['rsi']:.2f}",
                delta=None
            )

        with col3:
            signal_emoji = {
                "COMPRA": "🟢", "VENDA": "🔴", "NEUTRO": "⚪"
            }
            st.metric(
                label="🚨 Sinal Operacional",
                value=f"{signal_emoji.get(signal, '⚪')} {signal.replace('_', ' ')}",
                delta=None
            )

        with col4:
            if not pd.isna(last_candle['macd']) and not pd.isna(last_candle['macd_signal']):
                macd_trend = "📈" if last_candle['macd'] > last_candle['macd_signal'] else "📉"
                st.metric(
                    label="📊 MACD",
                    value=f"{macd_trend} {last_candle['macd']:.4f}",
                    delta=f"Signal: {last_candle['macd_signal']:.4f}"
                )
            else:
                st.metric(
                    label="📊 MACD",
                    value="Calculando...",
                    delta=None
                )

        with col5:
            # Status dinâmico com indicador de cache otimizado
            current_time_now = get_brazil_datetime_naive()
            if st.session_state.last_update:
                seconds_since_update = (current_time_now - st.session_state.last_update).total_seconds()
                
                if seconds_since_update < 60:
                    status_color = "🟢"
                    status_text = "Cache Ativo"
                    delta_text = f"Há {int(seconds_since_update)}s"
                elif seconds_since_update < 90:
                    status_color = "🟡"
                    status_text = "Aguardando"
                    delta_text = f"Há {int(seconds_since_update)}s"
                else:
                    status_color = "🔵"
                    status_text = "Atualizando"
                    delta_text = "Em breve..."
            else:
                status_color = "⚪"
                status_text = "Iniciando"
                delta_text = "..."
            
            st.metric(
                label="📡 Status",
                value=f"{status_color} {status_text}",
                delta=delta_text
            )

        st.subheader("📈 Gráfico de Mercado")
        render_live_market_chart(symbol=symbol, timeframe=timeframe, fallback_data=data)

        # Current Analysis
        st.subheader("🔍 Análise Atual")

        if (
            guardrail_edge_summary
            and guardrail_edge_summary.get("status") == "degraded"
            and guardrail_edge_summary.get("paper_closed_trades", 0) >= ProductionConfig.MIN_PAPER_TRADES_FOR_EDGE_GUARDRAIL
        ):
            st.warning(
                "Guardrail ativo: setup degradado no paper trade. "
                "O sinal foi bloqueado ate recuperar edge live."
            )

        if risk_plan:
            if risk_plan.get("allowed"):
                st.info(
                    f"Plano de risco ({risk_plan.get('risk_mode', 'normal')}): arriscar "
                    f"{risk_plan.get('risk_per_trade_pct', 0):.2f}% "
                    f"(${risk_plan.get('risk_amount', 0):.2f}) | "
                    f"Posicao ${risk_plan.get('position_notional', 0):.2f} | "
                    f"Qtd {risk_plan.get('quantity', 0):.6f}"
                )
            else:
                st.warning(f"Risk guardrail: {risk_plan.get('risk_reason') or risk_plan.get('reason')}")

            if operational_block_source == "stale_data":
                st.warning(
                    f"Bloqueio por stale data: ultimo update ha "
                    f"{(data_age_seconds or 0):.0f}s (limite {MAX_SIGNAL_DATA_AGE_SECONDS}s)."
                )

            portfolio_risk_summary = get_risk_management_service().get_portfolio_risk_summary()
            st.caption(
                f"Portfolio paper: {portfolio_risk_summary.get('open_trades', 0)} trades abertos | "
                f"Risco aberto {portfolio_risk_summary.get('total_open_risk_pct', 0):.2f}% | "
                f"Notional ${portfolio_risk_summary.get('total_open_position_notional', 0):.2f} | "
                f"Drawdown {portfolio_risk_summary.get('current_drawdown_pct', 0):.2f}% | "
                f"Losing streak {portfolio_risk_summary.get('consecutive_losses', 0)} | "
                f"Modo {portfolio_risk_summary.get('risk_mode', 'normal')}"
            )
            if not portfolio_risk_summary.get("circuit_breaker_allowed", True):
                st.error(
                    f"Circuit breaker: {portfolio_risk_summary.get('circuit_breaker_reason')} | "
                    f"PnL diário {portfolio_risk_summary.get('daily_realized_pnl_pct', 0):.2f}% | "
                    f"Losses consecutivos {portfolio_risk_summary.get('consecutive_losses', 0)}"
                )
            else:
                st.caption(
                    f"PnL diário paper: {portfolio_risk_summary.get('daily_realized_pnl_pct', 0):.2f}% | "
                    f"Losses consecutivos: {portfolio_risk_summary.get('consecutive_losses', 0)}"
                )

        analysis_col1, analysis_col2 = st.columns(2)

        with analysis_col1:
            st.info(f"""
            **Par:** {symbol}  
            **Timeframe:** {timeframe}  
            **Preço Atual:** ${last_candle['close']:.6f}  
            **RSI({st.session_state.trading_bot.rsi_period}):** {last_candle['rsi']:.2f}  
            **MACD:** {last_candle['macd']:.4f}  
            **MACD Signal:** {last_candle['macd_signal']:.4f}  
            **Volume:** {last_candle['volume']:,.0f}  
            **Volume MA:** {last_candle['volume_ma']:,.0f}
            """)
            st.caption(
                f"Candidato: {candidate_signal} | "
                f"Aprovado: {approved_signal or 'NEUTRO'} | "
                f"Bloqueado: {blocked_signal or '-'}"
            )
            st.caption(
                f"Status operacional: {'liberado' if operational_state.get('runtime_allowed') and not operational_block_reason else 'bloqueado'} | "
                f"Sinal operacional: {signal} | "
                f"Motivo operacional: {operational_block_reason or '-'}"
            )
            if governance_summary:
                st.caption(
                    f"Governanca adaptativa: {governance_summary.get('governance_status', 'research')} | "
                    f"Modo {governance_summary.get('governance_mode', 'blocked')} | "
                    f"Alinhamento {governance_summary.get('alignment_status', 'insufficient')} | "
                    f"Regime atual {governance_summary.get('current_regime') or '-'} "
                    f"({governance_summary.get('current_regime_status', 'unknown')})"
                )
                if governance_summary.get("allowed_regimes") or governance_summary.get("blocked_regimes"):
                    st.caption(
                        f"Regimes aprovados: {', '.join(governance_summary.get('allowed_regimes', [])) or '-'} | "
                        f"Regimes reduzidos: {', '.join(governance_summary.get('reduced_regimes', [])) or '-'} | "
                        f"Regimes bloqueados: {', '.join(governance_summary.get('blocked_regimes', [])) or '-'}"
                    )
                if governance_summary.get("action_reason"):
                    if governance_summary.get("governance_mode") == "blocked":
                        st.warning(f"Governanca: {governance_summary.get('action_reason')}")
                    elif governance_summary.get("governance_mode") == "reduced":
                        st.info(f"Governanca reduzida: {governance_summary.get('action_reason')}")
            if context_evaluation:
                st.caption(
                    f"Contexto: {context_evaluation.get('market_bias', 'neutral')} | "
                    f"{context_evaluation.get('regime', '-')} | "
                    f"Forca {context_evaluation.get('context_strength', 0):.2f}/10"
                )
            if regime_evaluation:
                st.caption(
                    f"Regime atual: {regime_evaluation.get('regime', 'range')} | "
                    f"{regime_evaluation.get('volatility_state', 'normal_volatility')} | "
                    f"Forca {regime_evaluation.get('regime_score', 0):.2f}/10 | "
                    f"ADX {regime_evaluation.get('adx', 0):.2f} | "
                    f"ATR% {regime_evaluation.get('atr_pct', 0):.2f} | "
                    f"Trend {regime_evaluation.get('trend_state', 'range')} | "
                    f"Parabolico {regime_evaluation.get('parabolic', False)}"
                )
            if structure_evaluation:
                st.caption(
                    f"Estrutura: {structure_evaluation.get('structure_state', 'weak_structure')} | "
                    f"{structure_evaluation.get('price_location', 'mid_range')} | "
                    f"Qualidade {structure_evaluation.get('structure_quality', 0):.2f}/10"
                )
            if confirmation_evaluation:
                conflicts_preview = ", ".join(confirmation_evaluation.get("conflicts", [])[:2]) or "sem conflitos relevantes"
                st.caption(
                    f"Confirmacao: {confirmation_evaluation.get('confirmation_state', 'weak')} | "
                    f"Score {confirmation_evaluation.get('confirmation_score', 0):.2f}/10 | "
                    f"Conflitos: {conflicts_preview}"
                )
            if entry_quality_evaluation:
                st.caption(
                    f"Entrada: {entry_quality_evaluation.get('entry_quality', 'bad')} | "
                    f"Setup {entry_quality_evaluation.get('setup_type') or '-'} | "
                    f"Score {float(entry_quality_evaluation.get('entry_score', 0) or 0):.2f}/10 | "
                    f"RSI {entry_quality_evaluation.get('rsi_state', 'neutral')} | "
                    f"Candle {entry_quality_evaluation.get('candle_quality', 'bad')} | "
                    f"Momentum {entry_quality_evaluation.get('momentum_state', 'weak')} | "
                    f"RR {entry_quality_evaluation.get('rr_estimate', 0):.2f} | "
                    f"Rejeicao {entry_quality_evaluation.get('rejection_reason') or '-'}"
                )
            if scenario_evaluation:
                st.caption(
                    f"Cenario: {scenario_evaluation.get('scenario_score', 0):.2f}/10 | "
                    f"Grade {scenario_evaluation.get('scenario_grade', 'D')}"
                )
            if trade_decision:
                st.caption(
                    f"Decisao analitica: {trade_decision.get('action', 'wait')} | "
                    f"Confianca {trade_decision.get('confidence', 0):.2f}/10 | "
                    f"Motivo: {trade_decision.get('entry_reason') or trade_decision.get('block_reason') or '-'}"
                )
            if hard_block_evaluation and hard_block_evaluation.get("hard_block"):
                st.error(
                    f"Hard block analitico: {hard_block_evaluation.get('block_reason')} "
                    f"({hard_block_evaluation.get('block_source', 'signal_engine')})"
                )

        with analysis_col2:
            if approved_signal == "COMPRA":
                st.success(f"""
                🟢 **SINAL ANALITICO APROVADO - COMPRA FORTE**  
                RSI cruzou acima de {rsi_min} com tendencia alinhada nas EMAs.  
                Considere entrada em posição de compra.
                """)
            elif approved_signal == "VENDA":
                st.error(f"""
                🔴 **SINAL ANALITICO APROVADO - VENDA FORTE**  
                RSI cruzou abaixo de {rsi_max} com tendencia alinhada nas EMAs.  
                Considere saída da posição ou entrada em venda.
                """)
            elif blocked_signal in ACTIONABLE_SIGNALS:
                st.warning(f"""
                ⚠️ **SINAL BLOQUEADO**  
                Candidato detectado: {blocked_signal}.  
                Motivo: {analytical_block_reason or '-'}.
                """)
            else:
                st.warning("""
                ⚪ **SINAL NEUTRO**  
                Indicadores em zona neutra.  
                Aguardar melhor oportunidade.
                """)

    # Signals History
    st.subheader("📋 Histórico de Sinais")

    # Opções de exibição do histórico
    col1, col2 = st.columns(2)
    with col1:
        show_source = st.radio(
            "Fonte dos dados:",
            ["Sessão Atual", "Banco de Dados (Persistente)"],
            help="Escolha se quer ver apenas sinais da sessão atual ou todo o histórico salvo"
        )

    with col2:
        if show_source == "Banco de Dados (Persistente)":
            limit_signals = st.number_input("Quantidade de sinais:", min_value=10, max_value=1000, value=100)
        else:
            limit_signals = len(st.session_state.signals_history) if st.session_state.signals_history else 0

    # Carregar dados conforme seleção
    if show_source == "Banco de Dados (Persistente)":
        try:
            # Carregar sinais do banco de dados
            db_signals = db.get_recent_signals(limit=limit_signals)
            if db_signals:
                signals_df = pd.DataFrame(db_signals)
                # Converter timestamp para datetime se necessário
                if 'created_at_br' in signals_df.columns:
                    signals_df['timestamp'] = pd.to_datetime(signals_df['created_at_br'], format='%d/%m/%Y %H:%M:%S', errors='coerce')
                signals_df = signals_df.sort_values('timestamp', ascending=False)

                # Renomear colunas do banco para compatibilidade
                column_mapping = {
                    'signal_type': 'signal',
                    'created_at_br': 'timestamp'
                }
                signals_df = signals_df.rename(columns=column_mapping)
            else:
                signals_df = None
                st.info("📋 Nenhum sinal encontrado no banco de dados.")
        except Exception as e:
            st.error(f"❌ Erro ao carregar dados do banco: {str(e)}")
            signals_df = None
    else:
        # Usar dados da sessão atual
        if st.session_state.signals_history:
            signals_df = pd.DataFrame(st.session_state.signals_history)
            signals_df['timestamp'] = pd.to_datetime(signals_df['timestamp'])
            signals_df = signals_df.sort_values('timestamp', ascending=False)
        else:
            signals_df = None

    if signals_df is not None and len(signals_df) > 0:

        # Format for display
        try:
            display_df = signals_df.copy()

            # Remove duplicate columns if any
            display_df = display_df.loc[:, ~display_df.columns.duplicated()]

            # Ensure we have the required columns
            required_cols = ['timestamp', 'symbol', 'price', 'rsi', 'signal']
            missing_cols = [col for col in required_cols if col not in display_df.columns]

            if missing_cols:
                st.error(f"Colunas ausentes nos dados: {missing_cols}")
                display_df = None
            else:
                # Converter para datetime se necessário, depois formatar
                if not pd.api.types.is_datetime64_any_dtype(display_df['timestamp']):
                    display_df['timestamp'] = pd.to_datetime(display_df['timestamp'], errors='coerce')

                # Remove rows with invalid timestamps
                display_df = display_df.dropna(subset=['timestamp'])

                if len(display_df) == 0:
                    st.warning("Não foi possível exibir os dados do histórico devido a problemas na formatação.")
                    display_df = None
                else:
                    display_df['timestamp'] = display_df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
                    display_df['price'] = display_df['price'].apply(lambda x: f"${x:.6f}" if pd.notna(x) else "N/A")
                    display_df['rsi'] = display_df['rsi'].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "N/A")

                    # Add MACD columns if they exist
                    if 'macd' in display_df.columns:
                        display_df['macd'] = display_df['macd'].apply(lambda x: f"{x:.4f}" if pd.notna(x) else "N/A")
                    if 'macd_signal' in display_df.columns:
                        display_df['macd_signal'] = display_df['macd_signal'].apply(lambda x: f"{x:.4f}" if pd.notna(x) else "N/A")

                    # Rename columns baseado nas colunas disponíveis
                    column_map = {
                        'timestamp': 'Data/Hora',
                        'symbol': 'Par', 
                        'timeframe': 'Timeframe',
                        'price': 'Preço',
                        'rsi': 'RSI',
                        'macd': 'MACD',
                        'macd_signal': 'MACD Signal',
                        'signal': 'Sinal',
                        'signal_type': 'Sinal',
                        'candidate_signal': 'Candidato',
                        'approved_signal': 'Aprovado',
                        'blocked_signal': 'Bloqueado',
                        'block_reason': 'Motivo Bloqueio',
                        'operational_signal': 'Sinal Operacional',
                        'operational_block_reason': 'Motivo Operacional',
                    }

                    # Renomear apenas as colunas que existem
                    display_df = display_df.rename(columns=column_map)

                    # Selecionar apenas as colunas que queremos mostrar
                    available_columns = []
                    for col in [
                        'Data/Hora', 'Par', 'Timeframe', 'Preço', 'RSI', 'MACD', 'MACD Signal',
                        'Candidato', 'Aprovado', 'Bloqueado', 'Motivo Bloqueio',
                        'Sinal Operacional', 'Motivo Operacional', 'Sinal'
                    ]:
                        if col in display_df.columns:
                            available_columns.append(col)

                    display_df = display_df[available_columns]

        except Exception as e:
            st.error(f"Erro ao processar dados do histórico: {str(e)}")
            display_df = None

        if display_df is not None and len(display_df) > 0:
            st.dataframe(
                display_df,
                width='stretch',
                hide_index=True
            )
        else:
            st.warning("Não foi possível exibir os dados do histórico devido a problemas na formatação.")

        # Clear history button
        col1, col2 = st.columns(2)
        with col1:
            if show_source == "Sessão Atual" and st.button("🗑️ Limpar Histórico"):
                st.session_state.signals_history = []
                st.rerun()

        with col2:
            if show_source == "Banco de Dados (Persistente)":
                # Exibir estatísticas do banco
                try:
                    stats = db.get_statistics()
                    runtime_strategy_version = get_effective_strategy_settings(
                        symbol,
                        timeframe,
                        require_volume=require_volume,
                        require_trend=require_trend,
                    )["strategy_version"]
                    paper_summary = get_paper_trade_service().get_summary(symbol=symbol, timeframe=timeframe)
                    edge_summary = get_cached_edge_monitor_summary(
                        symbol=symbol,
                        timeframe=timeframe,
                        strategy_version=runtime_strategy_version,
                    )
                    st.caption(
                        f"Paper trades {symbol} {timeframe}: "
                        f"{paper_summary.get('closed_trades', 0)} fechados | "
                        f"Win rate {paper_summary.get('win_rate', 0):.1f}% | "
                        f"Resultado acumulado {paper_summary.get('total_result_pct', 0):.2f}%"
                    )
                    edge_status = edge_summary.get('status')
                    edge_message = (
                        f"Edge monitor {symbol} {timeframe}: {edge_summary.get('status_message')} "
                        f"| Baseline PF {edge_summary.get('baseline_profit_factor', 0):.2f} "
                        f"vs Paper PF {edge_summary.get('paper_profit_factor', 0):.2f}"
                    )
                    if edge_status == "aligned":
                        st.success(edge_message)
                    elif edge_status in {"degraded", "watchlist"}:
                        st.warning(edge_message)
                    else:
                        st.info(edge_message)
                    st.info(f"📊 Estatísticas: {stats['total_signals']} sinais total | {stats['signals_24h']} últimas 24h")
                except Exception as e:
                    st.warning(f"⚠️ Erro ao carregar estatísticas: {str(e)}")

    # Auto-refresh mechanism otimizado - cache inteligente
    if auto_refresh:
        # Cache mais agressivo para melhor performance
        current_time_check = get_brazil_datetime_naive()
        
        # Usar cache de 90 segundos para reduzir chamadas API
        cache_timeout = 90  # Aumentado de 30 para 90 segundos
        
        should_update_data = (
            st.session_state.last_update is None or 
            (current_time_check - st.session_state.last_update).total_seconds() > cache_timeout
        )
        
        if should_update_data:
            # Mostrar que está atualizando
            with st.spinner('🔄 Atualizando dados do mercado...'):
                try:
                    # Buscar novos dados apenas quando necessário
                    new_data = st.session_state.trading_bot.get_market_data()
                    if new_data is not None:
                        st.session_state.current_data = new_data
                        st.session_state.last_update = current_time_check
                        st.success("✅ Dados atualizados!")
                    else:
                        st.warning("⚠️ Não foi possível atualizar os dados")
                        
                except Exception as e:
                    st.error(f"❌ Erro na atualização: {str(e)}")

    # Tab 2: Calculadoras
            with futures_tab2:
                st.markdown("### ⚖️ Calculadoras de Trading")

                calc_tab1, calc_tab2, calc_tab3 = st.tabs([
                    "🧮 Calculadora de Posição", "💀 Preço de Liquidação", "💰 P&L Simulador"
                ])

                with calc_tab1:
                    st.markdown("#### 🧮 Calculadora de Tamanho da Posição")

                    col1, col2 = st.columns(2)

                    with col1:
                        account_balance = st.number_input("Saldo da Conta ($)", value=10000.0, min_value=100.0)
                        risk_percent = st.slider("Risco por Trade (%)", 1, 10, 3)
                        leverage_calc = st.selectbox("Alavancagem Calc", [1, 2, 3, 5, 10, 20, 25, 50], index=3)
                        entry_price = st.number_input("Preço de Entrada ($)", value=float(st.session_state.current_data.iloc[-1]['close']) if st.session_state.current_data is not None else 1.0)

                    with col2:
                        # Cálculos
                        risk_amount = account_balance * (risk_percent / 100)
                        position_size_usdt = risk_amount * leverage_calc
                        quantity = position_size_usdt / entry_price
                        margin_required = position_size_usdt / leverage_calc

                        st.metric("💰 Valor Arriscado", f"${risk_amount:.2f}")
                        st.metric("📊 Tamanho da Posição", f"${position_size_usdt:.2f}")
                        st.metric("🪙 Quantidade", f"{quantity:.6f}")
                        st.metric("🏦 Margem Necessária", f"${margin_required:.2f}")

                with calc_tab2:
                    st.markdown("#### 💀 Calculadora de Preço de Liquidação")

                    col1, col2 = st.columns(2)

                    with col1:
                        entry_price_liq = st.number_input("Preço de Entrada Liq", value=1.0)
                        leverage_liq = st.selectbox("Alavancagem Liq", [1, 2, 3, 5, 10, 20, 25, 50], index=3)
                        position_side = st.radio("Lado da Posição", ["LONG", "SHORT"])

                    with col2:
                        # Calcular liquidação (simplificado)
                        if position_side == "LONG":
                            liquidation_price = entry_price_liq * (1 - (0.9 / leverage_liq))
                            distance = ((entry_price_liq - liquidation_price) / entry_price_liq) * 100
                        else:
                            liquidation_price = entry_price_liq * (1 + (0.9 / leverage_liq))
                            distance = ((liquidation_price - entry_price_liq) / entry_price_liq) * 100

                        st.metric("💀 Preço de Liquidação", f"${liquidation_price:.6f}")
                        st.metric("📏 Distância", f"{distance:.2f}%")

                        if distance < 5:
                            st.error("⚠️ ALTO RISCO DE LIQUIDAÇÃO!")
                        elif distance < 10:
                            st.warning("⚠️ Risco moderado de liquidação")
                        else:
                            st.success("✅ Distância segura da liquidação")

                with calc_tab3:
                    st.markdown("#### 💰 Simulador de Profit & Loss")

                    col1, col2 = st.columns(2)

                    with col1:
                        entry_price_pnl = st.number_input("Preço de Entrada PnL", value=1.0)
                        position_size_pnl = st.number_input("Tamanho da Posição ($)", value=1000.0)
                        leverage_pnl = st.selectbox("Alavancagem PnL", [1, 2, 3, 5, 10, 20, 25, 50], index=3)

                        # Cenários de preço
                        st.markdown("**Cenários de Preço:**")
                        scenario_1 = st.number_input("Cenário 1 ($)", value=entry_price_pnl * 1.02)
                        scenario_2 = st.number_input("Cenário 2 ($)", value=entry_price_pnl * 1.05)
                        scenario_3 = st.number_input("Cenário 3 ($)", value=entry_price_pnl * 0.98)

                    with col2:
                        st.markdown("**Resultados:**")

                        for i, price in enumerate([scenario_1, scenario_2, scenario_3], 1):
                            price_change_pct = ((price - entry_price_pnl) / entry_price_pnl)
                            pnl = position_size_pnl * price_change_pct * leverage_pnl

                            color = "🟢" if pnl > 0 else "🔴"
                            st.write(f"**Cenário {i}:** {color} ${pnl:+.2f} ({price_change_pct * leverage_pnl * 100:+.1f}%)")

            # Tab 3: Cenários teóricos
            with futures_tab3:
                st.markdown("### 📊 Simulador Educacional de Cenários")

                # Mock positions for educational demonstration only
                mock_positions = [
                    {
                        "Par": symbol,
                        "Lado": "LONG",
                        "Tamanho": f"${5000 * futures_leverage:.0f}",
                        "Alavancagem": f"{futures_leverage}x",
                        "Entrada": f"${st.session_state.current_data.iloc[-1]['close']:.6f}" if st.session_state.current_data is not None else "$1.000000",
                        "Atual": f"${st.session_state.current_data.iloc[-1]['close'] * 1.015:.6f}" if st.session_state.current_data is not None else "$1.015000",
                        "PnL": f"+${5000 * futures_leverage * 0.015:.2f}",
                        "PnL %": f"+{futures_leverage * 1.5:.1f}%",
                        "Margem": f"${5000:.0f}",
                        "Liquidação": f"${st.session_state.current_data.iloc[-1]['close'] * (1 - 0.9/futures_leverage):.6f}" if st.session_state.current_data is not None else "$0.900000"
                    }
                ]

                if st.button("🔄 Gerar Cenário Teórico"):
                    positions_df = pd.DataFrame(mock_positions)
                    st.dataframe(positions_df, width="stretch")

                    profit = 5000 * futures_leverage * 0.015
                    profit_pct = futures_leverage * 1.5
                    st.success(f"💰 PnL Total Simulado: +${profit:.2f} (+{profit_pct:.1f}%)")
                    st.info(f"🏦 Margem Total Usada: $5,000 com {futures_mode}")
                    st.warning("⚠️ Isto não representa posição real aberta nem paper trade salvo")
                else:
                    st.info("📭 Clique para gerar um cenário teórico com base na configuração atual")

    # Backtesting Tab - Otimizado para foco em testes
    if active_dashboard_section == "backtest":
        st.header("🔬 Centro de Backtesting Avançado")
        st.info(
            "Escopo desta aba: simulação histórica e validação de estratégia (retorno, drawdown, execução e auditoria). "
            "Não representa sinal operacional ao vivo."
        )
        max_backtest_days = 730
        setup_focus_labels = AppConfig.get_backtest_setup_focus_labels()
        market_reading_family_configs = AppConfig.get_market_reading_family_configs()
        risk_profile_configs = AppConfig.get_risk_profile_configs()
        setup_preset_configs = AppConfig.get_backtest_setup_presets()
        setup_preset_notes = AppConfig.get_backtest_preset_notes()

        def _apply_bt_session_updates(
            updates: dict[str, object],
            preset_name: str | None = None,
            start_days: int | None = None,
        ) -> None:
            for state_key, state_value in updates.items():
                st.session_state[state_key] = list(state_value) if isinstance(state_value, list) else state_value
            if start_days is not None:
                st.session_state.bt_start_date = date.today() - timedelta(days=start_days)
            if preset_name is not None:
                st.session_state.bt_setup_preset = preset_name
                st.session_state.bt_last_setup_preset = preset_name
            if "bt_market_family" in updates:
                st.session_state.bt_last_market_family = updates["bt_market_family"]
            if "bt_risk_profile" in updates:
                st.session_state.bt_last_risk_profile = updates["bt_risk_profile"]

        def _apply_bt_preset(preset_name: str, start_days: int | None = None) -> None:
            preset_updates = AppConfig.get_backtest_preset_updates(preset_name)
            _apply_bt_session_updates(preset_updates, preset_name=preset_name, start_days=start_days)
            st.session_state.bt_family_overlay_key = "global"

        def _apply_bt_family_overlay(symbol_name: str) -> dict[str, object]:
            family_profile = AppConfig.get_backtest_family_profile(symbol_name)
            _apply_bt_preset(
                AppConfig.DEFAULT_BACKTEST_PRESET,
                start_days=AppConfig.DEFAULT_BACKTEST_WINDOW_DAYS,
            )
            overlay_updates = dict(family_profile.get("overrides") or {})
            if overlay_updates:
                _apply_bt_session_updates(overlay_updates)
            st.session_state.bt_family_overlay_key = family_profile.get("family_key", "global")
            return family_profile

        # Quick test presets
        st.markdown("### ⚡ Testes Rápidos")
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            if st.button("🚀 Teste Agressivo", help="RSI 54/46, 7 dias", width="stretch"):
                _apply_bt_preset("Leitura Ativa (15m)", start_days=7)

        with col2:
            if st.button("✅ Perfil Global", help="Aplica o baseline global EMA/RSI para backtest", width="stretch"):
                _apply_bt_preset(
                    AppConfig.DEFAULT_BACKTEST_PRESET,
                    start_days=AppConfig.DEFAULT_BACKTEST_WINDOW_DAYS,
                )

        with col3:
            if st.button("🛡️ Teste Conservador", help="RSI 50/50, 30 dias", width="stretch"):
                _apply_bt_preset("Leitura Conservadora (1h)", start_days=30)

        with col4:
            if st.button("🔄 Reset Padrão", help="Voltar configurações padrão", width="stretch"):
                _apply_bt_preset(
                    AppConfig.DEFAULT_BACKTEST_PRESET,
                    start_days=AppConfig.DEFAULT_BACKTEST_WINDOW_DAYS,
                )

        st.markdown("---")

        default_setup_preset = (
            AppConfig.DEFAULT_BACKTEST_PRESET
            if AppConfig.DEFAULT_BACKTEST_PRESET in setup_preset_configs
            else list(setup_preset_configs.keys())[0]
        )
        default_preset_updates = dict(setup_preset_configs.get(default_setup_preset) or {})

        if "bt_setup_preset" not in st.session_state:
            st.session_state.bt_setup_preset = default_setup_preset
            for state_key, state_value in default_preset_updates.items():
                st.session_state[state_key] = list(state_value) if isinstance(state_value, list) else state_value
            st.session_state.bt_start_date = date.today() - timedelta(days=AppConfig.DEFAULT_BACKTEST_WINDOW_DAYS)
        if "bt_family_overlay_key" not in st.session_state:
            st.session_state.bt_family_overlay_key = "global"
        if "bt_last_setup_preset" not in st.session_state:
            st.session_state.bt_last_setup_preset = st.session_state.bt_setup_preset
        if "bt_market_family" not in st.session_state:
            st.session_state.bt_market_family = default_preset_updates.get("bt_market_family", "all_states")
        if "bt_last_market_family" not in st.session_state:
            st.session_state.bt_last_market_family = st.session_state.bt_market_family
        if "bt_risk_profile" not in st.session_state:
            st.session_state.bt_risk_profile = default_preset_updates.get("bt_risk_profile", "manual")
        if "bt_last_risk_profile" not in st.session_state:
            st.session_state.bt_last_risk_profile = st.session_state.bt_risk_profile

        selected_setup_preset = st.selectbox(
            "Preset Operacional",
            options=list(setup_preset_configs.keys()),
            help="Aplica um conjunto coerente de leitura de mercado, filtros e política de risco.",
            key="bt_setup_preset",
        )
        if st.session_state.bt_last_setup_preset != selected_setup_preset:
            _apply_bt_preset(selected_setup_preset)
        st.caption(setup_preset_notes.get(selected_setup_preset, ""))
        if selected_setup_preset == AppConfig.DEFAULT_BACKTEST_PRESET:
            st.info(AppConfig.DEFAULT_BACKTEST_PRESET_SUMMARY)

        # Main configuration in tabs
        config_tab1, config_tab2, config_tab3 = st.tabs(["📊 Básico", "⚙️ Avançado", "📈 Otimização"])

        with config_tab1:
            col1, col2 = st.columns(2)

            with col1:
                st.markdown("**🎯 Configuração Principal**")
                
                # Usar sempre o símbolo configurado na sidebar
                bt_symbol = symbol
                st.success(f"✅ **Par do Backtest:** {bt_symbol}")
                st.caption(
                    f"Perfil ativo: {selected_setup_preset} | "
                    f"Familia observada: {AppConfig.get_symbol_profile_family_label(bt_symbol)}"
                )
                st.info("💡 *Usando par configurado na sidebar*")
                family_profile = AppConfig.get_backtest_family_profile(bt_symbol)
                family_override_updates = dict(family_profile.get("overrides") or {})
                active_family_overlay_key = str(st.session_state.get("bt_family_overlay_key") or "global")
                if family_override_updates:
                    overlay_summary = []
                    if family_override_updates.get("bt_enable_volume_filter"):
                        overlay_summary.append("volume ON")
                    if family_override_updates.get("bt_enable_trend_filter"):
                        overlay_summary.append("tendencia ON")
                    if family_override_updates.get("bt_enable_avoid_ranging"):
                        overlay_summary.append("anti-ranging ON")
                    if "bt_stop_loss_pct" in family_override_updates:
                        overlay_summary.append(f"SL {family_override_updates['bt_stop_loss_pct']:.1f}%")
                    if "bt_take_profit_pct" in family_override_updates:
                        overlay_summary.append(f"TP {family_override_updates['bt_take_profit_pct']:.1f}%")

                    st.caption(
                        f"Overlay sugerido para {family_profile.get('label')}: {family_profile.get('description')}"
                    )
                    st.caption(
                        "Ajustes sugeridos sobre o perfil global: "
                        + (", ".join(overlay_summary) if overlay_summary else "sem ajustes extras")
                    )

                    overlay_col1, overlay_col2 = st.columns(2)
                    with overlay_col1:
                        if st.button(
                            f"Aplicar Overlay {family_profile.get('label')}",
                            key=f"bt_apply_family_overlay_{family_profile.get('family_key')}",
                            width="stretch",
                        ):
                            _apply_bt_family_overlay(bt_symbol)
                            st.rerun()
                    with overlay_col2:
                        if active_family_overlay_key != "global" and st.button(
                            "Voltar ao Global",
                            key="bt_clear_family_overlay",
                            width="stretch",
                        ):
                            _apply_bt_preset(
                                AppConfig.DEFAULT_BACKTEST_PRESET,
                                start_days=AppConfig.DEFAULT_BACKTEST_WINDOW_DAYS,
                            )
                            st.rerun()
                else:
                    st.caption(
                        "Esta familia usa o baseline global sem overlay adicional recomendado no momento."
                    )

                bt_timeframe = st.selectbox(
                    "Timeframe:",
                    ["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
                    index=2,
                    help="O motor lê o mercado exatamente neste timeframe.",
                    key="bt_timeframe"
                )

                context_timeframe_options = [tf for tf in ["5m", "15m", "30m", "1h", "4h", "1d"] if tf != bt_timeframe]
                context_mode_options = ["same_timeframe", *context_timeframe_options]
                if (
                    "bt_context_mode" not in st.session_state
                    or st.session_state.bt_context_mode not in context_mode_options
                ):
                    st.session_state.bt_context_mode = "same_timeframe"

                bt_context_mode = st.selectbox(
                    "Contexto Operacional:",
                    options=context_mode_options,
                    help="Use o proprio timeframe para leitura pura do mercado. Escolha outro apenas se quiser adicionar um filtro extra manual.",
                    key="bt_context_mode",
                    format_func=lambda value: (
                        f"Mesmo timeframe ({bt_timeframe})"
                        if value == "same_timeframe"
                        else value
                    ),
                )
                bt_context_timeframe = (
                    None
                    if bt_context_mode == "same_timeframe"
                    else bt_context_mode
                )
                if bt_context_timeframe:
                    st.caption(f"Contexto extra manual para este teste: {bt_context_timeframe}")
                else:
                    st.caption(f"Leitura principal no proprio {bt_timeframe}, sem filtro superior implicito.")

                bt_market_family = st.selectbox(
                    "Leitura de Mercado:",
                    options=list(market_reading_family_configs.keys()),
                    help="Define a família de estados de mercado que o backtest vai privilegiar. Internamente isso vira uma compatibilidade de execução, mas a decisão continua sendo por leitura do mercado.",
                    key="bt_market_family",
                    format_func=lambda value: market_reading_family_configs[value]["label"],
                )
                if st.session_state.bt_last_market_family != bt_market_family:
                    st.session_state.bt_setup_focus = list(
                        market_reading_family_configs[bt_market_family]["allowed_setups"]
                    )
                    st.session_state.bt_last_market_family = bt_market_family
                st.caption(market_reading_family_configs[bt_market_family]["description"])

                bt_initial_balance = st.number_input(
                    "Capital Inicial ($)", 
                    min_value=100.0, 
                    max_value=1000000.0, 
                    value=10000.0,
                    step=1000.0,
                    help="Quanto você investiria na estratégia",
                    key="bt_initial_balance"
                )

            with col2:
                st.markdown("**📅 Período de Teste**")

                # Presets de período
                period_preset = st.selectbox(
                    "Período Pré-definido:",
                    [
                        "Personalizado",
                        "Última Semana",
                        "Últimas 2 Semanas",
                        "Último Mês",
                        "Últimos 3 Meses",
                        "Últimos 6 Meses",
                        "Último Ano",
                        "Últimos 2 Anos",
                    ],
                    help="Escolha um período comum ou customize",
                    key="bt_period_preset",
                )

                from datetime import date
                max_date = date.today()

                if period_preset == "Última Semana":
                    default_start = max_date - timedelta(days=7)
                elif period_preset == "Últimas 2 Semanas":
                    default_start = max_date - timedelta(days=14)
                elif period_preset == "Último Mês":
                    default_start = max_date - timedelta(days=30)
                elif period_preset == "Últimos 3 Meses":
                    default_start = max_date - timedelta(days=90)
                elif period_preset == "Últimos 6 Meses":
                    default_start = max_date - timedelta(days=180)
                elif period_preset == "Último Ano":
                    default_start = max_date - timedelta(days=365)
                elif period_preset == "Últimos 2 Anos":
                    default_start = max_date - timedelta(days=max_backtest_days)
                else:
                    default_start = max_date - timedelta(days=30)

                if 'bt_last_period_preset' not in st.session_state:
                    st.session_state.bt_last_period_preset = period_preset

                preset_changed = st.session_state.bt_last_period_preset != period_preset
                if preset_changed and period_preset != "Personalizado":
                    st.session_state.bt_start_date = default_start
                    st.session_state.bt_end_date = max_date
                st.session_state.bt_last_period_preset = period_preset

                bt_start_date = st.date_input(
                    "📅 Data Inicial", 
                    value=getattr(st.session_state, 'bt_start_date', default_start),
                    max_value=max_date,
                    help="Início do backtest",
                    key="bt_start_date"
                )
                bt_end_date = st.date_input(
                    "📅 Data Final", 
                    value=getattr(st.session_state, 'bt_end_date', max_date),
                    max_value=max_date,
                    help="Fim do backtest",
                    key="bt_end_date"
                )

                # Mostrar duração
                if bt_start_date < bt_end_date:
                    duration = (bt_end_date - bt_start_date).days
                    st.info(f"📊 Período: **{duration} dias**")

        with config_tab2:
            col1, col2 = st.columns(2)

            with col1:
                st.markdown("**🎛️ Gatilhos RSI**")

                bt_rsi_period = st.slider(
                    "Período RSI", 
                    5, 50, 
                    getattr(st.session_state, 'bt_rsi_period', AppConfig.DEFAULT_RSI_PERIOD),
                    help="Janela de cálculo do RSI (14 é padrão)",
                    key="bt_rsi_period"
                )

                bt_rsi_min = st.slider(
                    "RSI Gatilho Compra", 
                    45, 60, 
                    getattr(st.session_state, 'bt_rsi_min', AppConfig.DEFAULT_RSI_MIN),
                    help="RSI precisa cruzar acima deste nivel para compra",
                    key="bt_rsi_min"
                )

                bt_rsi_max = st.slider(
                    "RSI Gatilho Venda", 
                    40, 55, 
                    getattr(st.session_state, 'bt_rsi_max', AppConfig.DEFAULT_RSI_MAX),
                    help="RSI precisa cruzar abaixo deste nivel para venda",
                    key="bt_rsi_max"
                )

            with col2:
                st.markdown("**⚡ Configurações de Performance**")

                if "bt_setup_focus" not in st.session_state or not isinstance(st.session_state.bt_setup_focus, list):
                    st.session_state.bt_setup_focus = list(setup_focus_labels.keys())
                if "bt_enable_volume_filter" not in st.session_state:
                    st.session_state.bt_enable_volume_filter = False
                if "bt_enable_trend_filter" not in st.session_state:
                    st.session_state.bt_enable_trend_filter = False
                if "bt_enable_avoid_ranging" not in st.session_state:
                    st.session_state.bt_enable_avoid_ranging = False

                st.info(
                    "A leitura do mercado decide direcao e contexto. SL/TP abaixo definem apenas a politica de risco do usuario."
                )

                enable_volume_filter = st.checkbox(
                    "Filtrar por Volume",
                    help="Apenas trades com volume acima da média",
                    key="bt_enable_volume_filter",
                )

                enable_trend_filter = st.checkbox(
                    "Filtrar por Tendência",
                    help="Usar MACD como filtro adicional",
                    key="bt_enable_trend_filter",
                )

                enable_avoid_ranging = st.checkbox(
                    "Evitar Mercado Lateral",
                    help="Bloqueia trades quando o regime estimado for lateralizado",
                    key="bt_enable_avoid_ranging",
                )

                recommended_stop_loss = 1.0 if bt_timeframe == "1h" else 0.8
                if "bt_stop_loss_pct" not in st.session_state:
                    st.session_state.bt_stop_loss_pct = float(recommended_stop_loss)
                if "bt_take_profit_pct" not in st.session_state:
                    st.session_state.bt_take_profit_pct = 1.8
                if "bt_enable_oos_validation" not in st.session_state:
                    st.session_state.bt_enable_oos_validation = True
                if "bt_validation_split_pct" not in st.session_state:
                    st.session_state.bt_validation_split_pct = 30
                if "bt_risk_profile" not in st.session_state:
                    st.session_state.bt_risk_profile = "manual"

                selected_risk_profile = st.selectbox(
                    "Perfil de Risco do Usuário",
                    options=list(risk_profile_configs.keys()),
                    help="A leitura continua a mesma. Aqui você define como quer transformar essa leitura em risco e alvo.",
                    key="bt_risk_profile",
                    format_func=lambda value: risk_profile_configs[value]["label"],
                )
                if st.session_state.bt_last_risk_profile != selected_risk_profile:
                    risk_profile = risk_profile_configs.get(selected_risk_profile, {})
                    if "stop_loss_pct" in risk_profile:
                        st.session_state.bt_stop_loss_pct = float(risk_profile["stop_loss_pct"])
                    if "take_profit_pct" in risk_profile:
                        st.session_state.bt_take_profit_pct = float(risk_profile["take_profit_pct"])
                    st.session_state.bt_last_risk_profile = selected_risk_profile
                st.caption(risk_profile_configs[selected_risk_profile]["description"])

                stop_loss_pct = st.number_input(
                    "Stop Loss (%)",
                    min_value=0.0,
                    max_value=20.0,
                    step=0.5,
                    help="0 = sem stop loss",
                    key="bt_stop_loss_pct",
                )

                take_profit_pct = st.number_input(
                    "Take Profit (%)",
                    min_value=0.0,
                    max_value=50.0,
                    step=0.5,
                    help="0 = sem take profit",
                    key="bt_take_profit_pct",
                )

                enable_oos_validation = st.checkbox(
                    "Validar Fora da Amostra",
                    help="Reserva a parte final do período para validar a estratégia em dados futuros",
                    key="bt_enable_oos_validation",
                )

                validation_split_pct = st.slider(
                    "Parte Fora da Amostra (%)",
                    10,
                    50,
                    disabled=not enable_oos_validation,
                    help="Percentual final do período reservado para validação temporal",
                    key="bt_validation_split_pct",
                )

                with st.expander("Compatibilidade Legada de Execução", expanded=False):
                    st.caption(
                        "Este bloco existe apenas para pesquisa fina e compatibilidade com a camada legada. O motor principal continua classificando e decidindo por leitura de mercado."
                    )
                    bt_setup_focus = st.multiselect(
                        "Cesta de Setups",
                        options=list(setup_focus_labels.keys()),
                        help="Restrição interna de execução. Use apenas se quiser forçar uma família legada específica.",
                        key="bt_setup_focus",
                        format_func=lambda value: setup_focus_labels[value],
                    )
                    if not bt_setup_focus:
                        st.warning("Selecione ao menos um setup legado para manter a compatibilidade do backtest.")

        with config_tab3:
            st.markdown("**🔍 Otimização de Parâmetros**")

            # Grid search para RSI
            optimization_allowed = AppConfig.ENABLE_PARAMETER_OPTIMIZATION
            enable_optimization = st.checkbox(
                "🚀 Modo Otimização Automática",
                value=False,
                disabled=not optimization_allowed,
                help="Testa múltiplas combinações de RSI automaticamente"
            )
            if not optimization_allowed:
                st.caption("Otimização global desativada para manter um único setup fixo.")

            if enable_optimization:
                col1, col2 = st.columns(2)

                with col1:
                    rsi_min_range = st.slider(
                        "Range RSI Compra",
                        45, 60, (50, 55),
                        help="Faixa para testar o gatilho comprador"
                    )

                    rsi_max_range = st.slider(
                        "Range RSI Venda", 
                        40, 55, (45, 50),
                        help="Faixa para testar o gatilho vendedor"
                    )

                with col2:
                    optimization_metric = st.selectbox(
                        "Métrica de Otimização:",
                        ["Total Return", "Sharpe Ratio", "Win Rate", "Profit Factor"],
                        help="Qual métrica maximizar"
                    )

                    max_tests = st.number_input(
                        "Máximo de Testes:",
                        min_value=5,
                        max_value=50,
                        value=20,
                        help="Limite de combinações para testar"
                    )

            # Comparação de timeframes
            scan_allowed = AppConfig.ENABLE_MARKET_SCAN
            compare_timeframes = st.checkbox(
                "📊 Comparar Timeframes",
                disabled=not scan_allowed,
                help="Testa a mesma estratégia em diferentes timeframes"
            )

            compare_symbols = st.checkbox(
                "🪙 Comparar Pares",
                disabled=not scan_allowed,
                help="Executa o mesmo backtest em múltiplos pares para encontrar onde o edge realmente se sustenta"
            )
            if not scan_allowed:
                st.caption("Scan comparativo desativado: foco em um único mercado e timeframe.")

            supported_scan_timeframes = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
            default_scan_timeframes = list(dict.fromkeys([bt_timeframe, "15m", "1h"]))
            default_scan_timeframes = [tf for tf in default_scan_timeframes if tf in supported_scan_timeframes]
            comparison_timeframes = [bt_timeframe]
            if compare_timeframes:
                comparison_timeframes = st.multiselect(
                    "Timeframes do Scan",
                    options=supported_scan_timeframes,
                    default=default_scan_timeframes or [bt_timeframe],
                    help="Compare a robustez da estratégia em múltiplos timeframes",
                    key="bt_comparison_timeframes",
                )

            supported_scan_symbols = AppConfig.get_supported_pairs()
            default_scan_symbols = list(dict.fromkeys([bt_symbol, "BTC/USDT", "ETH/USDT"]))
            default_scan_symbols = [sym for sym in default_scan_symbols if sym in supported_scan_symbols]
            comparison_symbols = [bt_symbol]
            if compare_symbols:
                comparison_symbols = st.multiselect(
                    "Pares do Scan",
                    options=supported_scan_symbols,
                    default=default_scan_symbols or [bt_symbol],
                    help="Selecione os pares para o scan comparativo",
                    key="bt_comparison_symbols",
                )

            comparison_timeframes = comparison_timeframes or [bt_timeframe]
            comparison_symbols = comparison_symbols or [bt_symbol]
            comparison_combo_count = len(comparison_symbols) * len(comparison_timeframes)
            if compare_timeframes or compare_symbols:
                st.caption(
                    f"Scan configurado: {len(comparison_symbols)} par(es) x "
                    f"{len(comparison_timeframes)} timeframe(s) = {comparison_combo_count} cenário(s)"
                )

            if "bt_enable_walk_forward" not in st.session_state:
                st.session_state.bt_enable_walk_forward = True
            if "bt_walk_forward_windows" not in st.session_state:
                st.session_state.bt_walk_forward_windows = 3

            enable_walk_forward = st.checkbox(
                "🧭 Walk-Forward",
                help="Executa validação sequencial em múltiplas janelas temporais",
                key="bt_enable_walk_forward",
            )

            walk_forward_windows = st.slider(
                "Janelas Walk-Forward",
                2,
                5,
                disabled=not enable_walk_forward,
                help="Quantidade de janelas out-of-sample sequenciais",
                key="bt_walk_forward_windows",
            )

        allowed_execution_setups = list(dict.fromkeys(bt_setup_focus)) or None
        execution_context_timeframe = bt_context_timeframe

        # Validation and execution
        date_valid = bt_start_date < bt_end_date
        period_days = (bt_end_date - bt_start_date).days

        st.markdown("---")
        st.markdown("### Criterios de Aprovacao Real")

        required_trade_velocity = (
            ProductionConfig.MIN_BACKTEST_TRADES_FOR_PROMOTION
            / max(ProductionConfig.MIN_PROMOTION_PERIOD_DAYS, 1)
        )
        risk_reward_ratio = (
            take_profit_pct / stop_loss_pct
            if stop_loss_pct > 0 and take_profit_pct > 0
            else None
        )
        selected_setup_label = ", ".join(
            setup_focus_labels[setup_name]
            for setup_name in (allowed_execution_setups or list(setup_focus_labels.keys()))
            if setup_name in setup_focus_labels
        )
        selected_market_family = market_reading_family_configs.get(
            st.session_state.get("bt_market_family", "all_states"),
            market_reading_family_configs["all_states"],
        )
        selected_risk_profile_label = risk_profile_configs.get(
            st.session_state.get("bt_risk_profile", "manual"),
            risk_profile_configs["manual"],
        )["label"]

        approval_col1, approval_col2 = st.columns(2)
        with approval_col1:
            st.info(
                "\n".join(
                    [
                        f"Leitura em foco: {selected_market_family['label']}",
                        f"Compatibilidade legada: {selected_setup_label}",
                        (
                            f"Contexto operacional: {bt_context_timeframe}"
                            if bt_context_timeframe
                            else f"Contexto operacional: somente {bt_timeframe}"
                        ),
                        f"Meta minima: {ProductionConfig.MIN_BACKTEST_TRADES_FOR_PROMOTION} trades em {ProductionConfig.MIN_PROMOTION_PERIOD_DAYS} dias",
                        f"Meta de throughput: {required_trade_velocity:.2f} trades aprovados/dia",
                    ]
                )
            )
        with approval_col2:
            st.info(
                "\n".join(
                    [
                        f"Perfil de risco: {selected_risk_profile_label}",
                        f"OOS minimo: {ProductionConfig.MIN_PROMOTION_OOS_TRADES} trades | PF >= {ProductionConfig.MIN_PROMOTION_OOS_PROFIT_FACTOR:.2f}",
                        f"Walk-forward minimo: {ProductionConfig.MIN_WALK_FORWARD_PASS_RATE_PCT:.0f}% das janelas",
                        f"Max drawdown: {ProductionConfig.MAX_PROMOTION_DRAWDOWN:.1f}%",
                        (
                            f"RR atual: {risk_reward_ratio:.2f}:1"
                            if risk_reward_ratio is not None
                            else "RR atual: defina SL e TP para medir risco/retorno"
                        ),
                    ]
                )
            )

        if period_days < ProductionConfig.MIN_PROMOTION_PERIOD_DAYS:
            st.warning(
                f"Janela curta: a aprovacao real exige pelo menos {ProductionConfig.MIN_PROMOTION_PERIOD_DAYS} dias de dados."
            )
        if risk_reward_ratio is not None and risk_reward_ratio < 1.5:
            st.warning("RR abaixo de 1.5:1. Com essa relacao, a consistencia fica estatisticamente mais dificil.")

        st.markdown("### 🚀 Executar Testes")

        # Status da configuração
        col1, col2 = st.columns(2)

        with col1:
            if not date_valid:
                st.error("❌ Data inicial deve ser anterior à data final")
            elif period_days > max_backtest_days:
                st.error(f"❌ Período muito longo. Máximo suportado: {max_backtest_days} dias")
            elif period_days > 365:
                st.warning("⚠️ Período longo de sobrevivência. O backtest pode demorar bastante.")
            elif period_days > 90:
                st.warning("⚠️ Período longo pode demorar mais")
            elif period_days < 1:
                st.error("❌ Período muito curto. Mínimo: 1 dia")
            else:
                st.success(f"✅ Configuração válida - {period_days} dias")

        with col2:
            # Estimativa de tempo
            if date_valid and period_days > 0:
                estimated_time = max(5, min(period_days * 0.35, 180))
                st.info(f"⏱️ Tempo estimado: ~{estimated_time:.0f}s")

        # Execution buttons
        col1, col2, col3 = st.columns(3)
        run_optimization = False
        run_market_scan = False

        with col1:
            bt_execute = st.button(
                "🚀 Executar Backtest", 
                disabled=not date_valid or period_days < 1 or period_days > max_backtest_days or not allowed_execution_setups,
                help="Rodar simulação com configurações atuais",
                width="stretch",
                key="bt_execute"
            )

        with col2:
            if enable_optimization and st.button(
                "⚡ Otimização Automática",
                disabled=not date_valid or period_days < 1 or period_days > max_backtest_days or not allowed_execution_setups,
                help="Testar múltiplas combinações automaticamente",
                width="stretch",
                key="bt_optimize"
            ):
                run_optimization = True
                bt_execute = True

        with col3:
            if (compare_timeframes or compare_symbols) and st.button(
                "🧭 Scan Comparativo",
                disabled=not date_valid or period_days < 1 or period_days > max_backtest_days or not allowed_execution_setups,
                help="Testar a estratégia em múltiplos pares e/ou timeframes",
                width="stretch",
                key="bt_compare"
            ):
                run_market_scan = True
                bt_execute = True

        if bt_execute and date_valid:
            with st.spinner("🔄 Executando backtest... Isso pode levar alguns minutos."):
                try:
                    # Convert dates to datetime
                    start_dt = datetime.combine(bt_start_date, datetime.min.time())
                    end_dt = datetime.combine(bt_end_date, datetime.max.time())

                    # Validações adicionais
                    if period_days > max_backtest_days:
                        st.error(f"❌ Período muito longo. Máximo suportado: {max_backtest_days} dias")
                        st.stop()

                    if run_optimization:
                        st.info(
                            f"⚡ Executando otimização RSI para {bt_symbol} {bt_timeframe} "
                            f"em até {int(max_tests)} combinações..."
                        )

                        optimization_results = st.session_state.backtest_engine.optimize_rsi_parameters(
                            symbol=bt_symbol,
                            timeframe=bt_timeframe,
                            rsi_min_range=rsi_min_range,
                            rsi_max_range=rsi_max_range,
                            max_tests=int(max_tests),
                            optimization_metric=optimization_metric,
                            start_date=start_dt,
                            end_date=end_dt,
                            initial_balance=int(bt_initial_balance),
                            rsi_period=bt_rsi_period,
                            context_timeframe=execution_context_timeframe,
                            stop_loss_pct=stop_loss_pct,
                            take_profit_pct=take_profit_pct,
                            require_volume=enable_volume_filter,
                            require_trend=enable_trend_filter,
                            avoid_ranging=enable_avoid_ranging,
                            validation_split_pct=validation_split_pct if enable_oos_validation else 0.0,
                            walk_forward_windows=walk_forward_windows if enable_walk_forward else 0,
                            allowed_execution_setups=allowed_execution_setups,
                        )

                        if optimization_results and optimization_results.get('rows'):
                            st.session_state.backtest_scan_results = None
                            st.session_state.backtest_optimization_results = optimization_results
                            st.session_state.backtest_results = optimization_results.get('best_result')
                            best_optimization = optimization_results.get('best') or {}
                            st.success("✅ Otimização concluída com sucesso!")
                            if best_optimization:
                                st.caption(
                                    f"Melhor configuração: RSI {best_optimization.get('rsi_min')}-"
                                    f"{best_optimization.get('rsi_max')} | "
                                    f"Score {best_optimization.get('quality_score', 0):.1f}"
                                )
                            st.balloons()
                        else:
                            st.error("❌ A otimização não retornou resultados válidos")
                    elif run_market_scan:
                        st.info(
                            f"📊 Executando scan comparativo com {len(comparison_symbols)} par(es) e "
                            f"{len(comparison_timeframes)} timeframe(s)..."
                        )

                        scan_results = st.session_state.backtest_engine.run_market_scan(
                            symbols=comparison_symbols,
                            timeframes=comparison_timeframes,
                            start_date=start_dt,
                            end_date=end_dt,
                            initial_balance=int(bt_initial_balance),
                            rsi_period=bt_rsi_period,
                            rsi_min=bt_rsi_min,
                            rsi_max=bt_rsi_max,
                            context_timeframe=execution_context_timeframe,
                            stop_loss_pct=stop_loss_pct,
                            take_profit_pct=take_profit_pct,
                            require_volume=enable_volume_filter,
                            require_trend=enable_trend_filter,
                            avoid_ranging=enable_avoid_ranging,
                            validation_split_pct=validation_split_pct if enable_oos_validation else 0.0,
                            walk_forward_windows=walk_forward_windows if enable_walk_forward else 0,
                            allowed_execution_setups=allowed_execution_setups,
                        )

                        if scan_results and scan_results.get('rows'):
                            st.session_state.backtest_scan_results = scan_results
                            st.session_state.backtest_optimization_results = None
                            st.session_state.backtest_results = scan_results.get('best_result')
                            best_scan = scan_results.get('best') or {}
                            st.success("✅ Scan comparativo concluído com sucesso!")
                            if best_scan:
                                st.caption(
                                    f"Melhor cenário: {best_scan.get('symbol')} {best_scan.get('timeframe')} "
                                    f"| Score {best_scan.get('quality_score', 0):.1f}"
                                )
                            st.balloons()
                        else:
                            st.error("❌ O scan comparativo não retornou resultados válidos")
                    else:
                        st.info(f"📊 Executando backtest para {bt_symbol} no período de {period_days} dias...")

                        results = st.session_state.backtest_engine.run_backtest(
                            symbol=bt_symbol,
                            timeframe=bt_timeframe,
                            start_date=start_dt,
                            end_date=end_dt,
                            initial_balance=int(bt_initial_balance),
                            rsi_period=bt_rsi_period,
                            rsi_min=bt_rsi_min,
                            rsi_max=bt_rsi_max,
                            context_timeframe=execution_context_timeframe,
                            stop_loss_pct=stop_loss_pct,
                            take_profit_pct=take_profit_pct,
                            require_volume=enable_volume_filter,
                            require_trend=enable_trend_filter,
                            avoid_ranging=enable_avoid_ranging,
                            validation_split_pct=validation_split_pct if enable_oos_validation else 0.0,
                            walk_forward_windows=walk_forward_windows if enable_walk_forward else 0,
                            allowed_execution_setups=allowed_execution_setups,
                        )

                        if results and 'stats' in results:
                            st.session_state.backtest_scan_results = None
                            st.session_state.backtest_optimization_results = None
                            st.session_state.backtest_results = results
                            st.success("✅ Backtest concluído com sucesso!")
                            if results.get('saved_run_id'):
                                st.caption(f"Backtest salvo no banco com ID #{results['saved_run_id']}")
                            st.balloons()
                        else:
                            st.error("❌ Backtest não retornou resultados válidos")

                except Exception as e:
                    error_msg = str(e)
                    st.error(f"❌ Erro durante o backtest: {error_msg}")

                    # Mensagens de ajuda específicas
                    if "Dados insuficientes" in error_msg:
                        st.warning("⚠️ **Solução**: Tente um período maior (mínimo 7 dias) ou um timeframe menor")
                    elif "API" in error_msg or "connection" in error_msg.lower():
                        st.warning("⚠️ **Solução**: Verifique sua conexão com a internet e tente novamente")
                    elif "Rate limit" in error_msg or "limit" in error_msg.lower():
                        st.warning("⚠️ **Solução**: Aguarde alguns minutos antes de tentar novamente")
                    else:
                        st.info("💡 **Dicas**:\n- Tente um período menor\n- Verifique se o par selecionado está disponível\n- Aguarde alguns segundos e tente novamente")

                    # Log do erro para debug
                    with st.expander("🔍 Detalhes técnicos (para debug)"):
                        st.code(error_msg)

        # Display results if available
        if st.session_state.backtest_results:
            results = st.session_state.backtest_results
            stats = results['stats']
            result_meta = results.get('meta', {})
            result_symbol = result_meta.get('symbol', bt_symbol)
            result_timeframe = result_meta.get('timeframe', bt_timeframe)
            result_strategy_version = result_meta.get('strategy_version')
            result_rsi_min = result_meta.get('rsi_min', bt_rsi_min)
            result_rsi_max = result_meta.get('rsi_max', bt_rsi_max)
            scan_results = st.session_state.get('backtest_scan_results')
            optimization_results = st.session_state.get('backtest_optimization_results')

            st.markdown("---")
            st.subheader("📊 Resultados do Backtest")
            st.caption(f"Cenário exibido: {result_symbol} {result_timeframe}")
            if result_strategy_version:
                st.caption(f"Versão da estratégia: {result_strategy_version}")

            market_state_summary = results.get('market_state_summary') or stats.get('market_state_breakdown') or []
            execution_mode_summary = results.get('execution_mode_summary') or stats.get('execution_mode_breakdown') or []
            active_strategy_profile = get_cached_active_strategy_profile(result_symbol, result_timeframe)
            promotion_readiness = None
            if results.get('saved_run_id'):
                promotion_readiness = get_cached_backtest_run_promotion_readiness(results['saved_run_id'])
            strategy_col1, strategy_col2 = st.columns(2)
            with strategy_col1:
                if active_strategy_profile:
                    active_market_states = active_strategy_profile.get('allowed_market_states') or []
                    active_market_state_label = ", ".join(active_market_states) or active_strategy_profile.get('market_state') or "-"
                    st.info(
                        f"Leitura ativa em paper: {active_market_state_label} "
                        f"| {active_strategy_profile.get('strategy_version')} "
                        f"| RSI {active_strategy_profile.get('rsi_min')}-{active_strategy_profile.get('rsi_max')}"
                    )
                else:
                    st.info("Nenhuma leitura ativa em paper para este mercado/timeframe.")
                if promotion_readiness:
                    ready_market_states = promotion_readiness.get("approved_market_states") or []
                    ready_market_state_label = ", ".join(ready_market_states) if ready_market_states else "-"
                    if promotion_readiness.get("ready"):
                        st.success(
                            f"Leitura apta para ativação em paper com base nos critérios mínimos de backtest. "
                            f"Estados aprovados: {ready_market_state_label}"
                        )
                    else:
                        reasons_text = "\n".join(f"- {reason}" for reason in promotion_readiness.get("reasons", []))
                        st.warning(f"Leitura ainda não apta para ativação em paper:\n{reasons_text}")
            with strategy_col2:
                action_col1, action_col2 = st.columns(2)
                with action_col1:
                    if results.get('saved_run_id') and st.button(
                        "🚀 Ativar Leitura em Paper",
                        key=f"promote_setup_{results.get('saved_run_id')}",
                        disabled=bool(promotion_readiness and not promotion_readiness.get("ready")),
                    ):
                        promoted = db.promote_backtest_run(
                            results['saved_run_id'],
                            notes="Ativado em paper via dashboard",
                        )
                        if promoted:
                            clear_dashboard_data_caches()
                            promoted_states = promoted.get('allowed_market_states') or []
                            state_label = ", ".join(promoted_states) or promoted.get('market_state') or "-"
                            st.success(f"Leitura ativa em paper: {state_label} | {promoted.get('strategy_version')}")
                            st.rerun()
                        else:
                            st.error("Não foi possível ativar a leitura atual em paper.")
                with action_col2:
                    if active_strategy_profile and st.button(
                        "⛔ Desligar Ativo",
                        key=f"disable_setup_{active_strategy_profile.get('id')}",
                    ):
                        db.deactivate_strategy_profile(
                            active_strategy_profile['id'],
                            reason="Desativado via dashboard",
                        )
                        clear_dashboard_data_caches()
                        st.warning("Leitura ativa desativada.")
                        st.rerun()

            dominant_market_state = market_state_summary[0] if market_state_summary else {}
            dominant_execution_mode = execution_mode_summary[0] if execution_mode_summary else {}
            objective_check = results.get("objective_check") or {}
            approved_market_states = objective_check.get("approved_market_states") or []
            approved_market_state_label = ", ".join(approved_market_states) if approved_market_states else "-"
            if market_state_summary or objective_check:
                st.markdown("### 🧭 Leitura Operacional")
                market_col1, market_col2, market_col3, market_col4 = st.columns(4)
                with market_col1:
                    st.metric("Estado Dominante", dominant_market_state.get("market_state", "-"))
                with market_col2:
                    st.metric("Estados Aprovados", approved_market_state_label)
                with market_col3:
                    st.metric("Modo Dominante", dominant_execution_mode.get("execution_mode", "-"))
                with market_col4:
                    st.metric(
                        "PF do Estado Líder",
                        f"{float(dominant_market_state.get('profit_factor', 0.0) or 0.0):.2f}",
                    )

                st.caption(
                    "A leitura do mercado mostra o contexto que mais apareceu e o subconjunto que ficou elegível para promoção real."
                )
            if objective_check:
                st.markdown("### 🎯 Checagem Objetiva de Sobrevivência")
                obj_col1, obj_col2, obj_col3, obj_col4 = st.columns(4)
                with obj_col1:
                    st.metric("Status", str(objective_check.get("status", "-")).upper())
                with obj_col2:
                    st.metric("Score", f"{float(objective_check.get('objective_score', 0.0) or 0.0):.2f}")
                with obj_col3:
                    st.metric("Grade", objective_check.get("objective_grade", "-"))
                with obj_col4:
                    st.metric("Estado Foco", objective_check.get("recommended_market_state") or "-")

                status_value = str(objective_check.get("status", "")).lower()
                status_message = (
                    f"Objetivo de robustez: {status_value.upper()} | "
                    f"Score {float(objective_check.get('objective_score', 0.0) or 0.0):.2f} "
                    f"(Grade {objective_check.get('objective_grade', '-')})"
                )
                if status_value == "approved":
                    st.success(status_message)
                elif status_value == "candidate":
                    st.warning(status_message)
                else:
                    st.error(status_message)

                objective_checks = objective_check.get("checks") or []
                if objective_checks:
                    st.dataframe(
                        pd.DataFrame(
                            [
                                {
                                    "Critério": item.get("name"),
                                    "Valor": item.get("value"),
                                    "Meta": item.get("target"),
                                    "Passou": "✅" if item.get("passed") else "❌",
                                    "Peso": item.get("weight"),
                                    "Hard": "sim" if item.get("hard") else "não",
                                }
                                for item in objective_checks
                            ]
                        ),
                        width="stretch",
                        hide_index=True,
                    )

                objective_col1, objective_col2 = st.columns(2)
                with objective_col1:
                    blockers = objective_check.get("blockers") or []
                    if blockers:
                        st.caption("Blockers")
                        st.write("\n".join(f"- {item}" for item in blockers))
                    else:
                        st.caption("Blockers")
                        st.info("Nenhum blocker crítico.")
                with objective_col2:
                    warnings_list = objective_check.get("warnings") or []
                    if warnings_list:
                        st.caption("Warnings")
                        st.write("\n".join(f"- {item}" for item in warnings_list))
                    else:
                        st.caption("Warnings")
                        st.info("Sem alertas adicionais.")

                market_state_candidates = objective_check.get("market_state_candidates") or []
                if market_state_candidates:
                    st.caption("Ranking de Estados de Mercado")
                    st.dataframe(pd.DataFrame(market_state_candidates), width="stretch", hide_index=True)

                setup_candidates = objective_check.get("setup_candidates") or []
                if setup_candidates:
                    with st.expander("Compatibilidade Legada: Ranking de Setup", expanded=False):
                        st.dataframe(pd.DataFrame(setup_candidates), width="stretch", hide_index=True)

                next_actions = objective_check.get("next_actions") or []
                if next_actions:
                    st.caption("Próximas Ações")
                    st.write("\n".join(f"- {item}" for item in next_actions))

            try:
                edge_summary = get_cached_edge_monitor_summary(
                    symbol=result_symbol,
                    timeframe=result_timeframe,
                    strategy_version=result_strategy_version,
                )
                st.markdown("### 📡 Edge Live vs Backtest")
                edge_col1, edge_col2, edge_col3, edge_col4 = st.columns(4)
                with edge_col1:
                    st.metric("Baseline PF", f"{edge_summary.get('baseline_profit_factor', 0):.2f}")
                with edge_col2:
                    st.metric("Paper PF", f"{edge_summary.get('paper_profit_factor', 0):.2f}")
                with edge_col3:
                    st.metric("Paper Trades", edge_summary.get('paper_closed_trades', 0))
                with edge_col4:
                    st.metric("Alinhamento PF", f"{edge_summary.get('profit_factor_alignment_pct', 0):.1f}%")

                edge_message = (
                    f"{edge_summary.get('baseline_source', 'Baseline')} retorno {edge_summary.get('baseline_return_pct', 0):.2f}% "
                    f"| Paper acumulado {edge_summary.get('paper_total_result_pct', 0):.2f}% "
                    f"| {edge_summary.get('status_message')}"
                )
                edge_status = edge_summary.get('status')
                if edge_status == "aligned":
                    st.success(edge_message)
                elif edge_status in {"degraded", "watchlist"}:
                    st.warning(edge_message)
                else:
                    st.info(edge_message)
            except Exception as edge_error:
                st.info(f"Edge monitor indisponivel: {edge_error}")

            try:
                governance_summary = get_cached_strategy_governance_summary(
                    symbol=result_symbol,
                    timeframe=result_timeframe,
                    active_only=False,
                    limit=10,
                )
                governance_counts = governance_summary.get('counts', {})
                governance_profiles = governance_summary.get('profiles', [])

                st.markdown("### 🧭 Governança Operacional")
                gov_col1, gov_col2, gov_col3, gov_col4, gov_col5 = st.columns(5)
                with gov_col1:
                    st.metric("Aprovados", governance_counts.get('approved', 0))
                with gov_col2:
                    st.metric("Observando", governance_counts.get('observing', 0))
                with gov_col3:
                    st.metric("Bloqueados", governance_counts.get('blocked', 0))
                with gov_col4:
                    st.metric("Prontos p/ Paper", governance_counts.get('ready_for_paper', 0))
                with gov_col5:
                    st.metric("Precisam Ajuste", governance_counts.get('needs_work', 0))

                if governance_profiles:
                    governance_df = pd.DataFrame(governance_profiles)
                    governance_df = governance_df[
                        [
                            'strategy_version',
                            'profile_status',
                            'governance_status',
                            'governance_mode',
                            'alignment_status',
                            'paper_closed_trades',
                            'baseline_profit_factor',
                            'paper_profit_factor',
                            'governance_message',
                        ]
                    ].rename(
                        columns={
                            'strategy_version': 'Versao',
                            'profile_status': 'Perfil',
                            'governance_status': 'Status',
                            'governance_mode': 'Modo',
                            'alignment_status': 'Alignment',
                            'paper_closed_trades': 'Paper Trades',
                            'baseline_profit_factor': 'PF Baseline',
                            'paper_profit_factor': 'PF Paper',
                            'governance_message': 'Mensagem',
                        }
                    )
                    st.dataframe(governance_df, width="stretch", hide_index=True)

                adaptive_governance = get_cached_governance_evaluation(
                    symbol=result_symbol,
                    timeframe=result_timeframe,
                    strategy_version=result_strategy_version,
                )
                regime_baselines = get_cached_setup_regime_baselines(
                    symbol=result_symbol,
                    timeframe=result_timeframe,
                    strategy_version=result_strategy_version,
                )
                alignment_history = get_cached_alignment_metrics(
                    symbol=result_symbol,
                    timeframe=result_timeframe,
                    strategy_version=result_strategy_version,
                    limit=5,
                )
                governance_history = get_cached_governance_history(
                    symbol=result_symbol,
                    timeframe=result_timeframe,
                    strategy_version=result_strategy_version,
                    limit=10,
                )

                st.markdown("### Governança Adaptativa")
                adaptive_col1, adaptive_col2, adaptive_col3, adaptive_col4 = st.columns(4)
                with adaptive_col1:
                    st.metric("Status", adaptive_governance.get("governance_status", "-"))
                with adaptive_col2:
                    st.metric("Modo", adaptive_governance.get("governance_mode", "-"))
                with adaptive_col3:
                    st.metric("Alignment", adaptive_governance.get("alignment_status", "-"))
                with adaptive_col4:
                    st.metric("Score", f"{adaptive_governance.get('quality_score', 0):.1f}")

                st.caption(
                    f"Acao: {adaptive_governance.get('action', '-')} | "
                    f"Motivo: {adaptive_governance.get('action_reason', '-')}"
                )
                st.caption(
                    f"Regimes aprovados: {', '.join(adaptive_governance.get('allowed_regimes', [])) or '-'} | "
                    f"Reduzidos: {', '.join(adaptive_governance.get('reduced_regimes', [])) or '-'} | "
                    f"Bloqueados: {', '.join(adaptive_governance.get('blocked_regimes', [])) or '-'}"
                )

                if regime_baselines:
                    regime_df = pd.DataFrame(regime_baselines)[
                        [
                            'regime',
                            'performance_status',
                            'baseline_trade_count',
                            'baseline_profit_factor',
                            'baseline_expectancy_pct',
                            'baseline_win_rate',
                            'total_return_pct',
                        ]
                    ].rename(
                        columns={
                            'regime': 'Regime',
                            'performance_status': 'Status',
                            'baseline_trade_count': 'Trades',
                            'baseline_profit_factor': 'PF',
                            'baseline_expectancy_pct': 'Expectancy %',
                            'baseline_win_rate': 'Win Rate %',
                            'total_return_pct': 'Retorno %',
                        }
                    )
                    st.dataframe(regime_df, width="stretch", hide_index=True)

                if alignment_history:
                    alignment_df = pd.DataFrame(alignment_history)[
                        [
                            'regime',
                            'alignment_status',
                            'paper_trade_count',
                            'paper_profit_factor',
                            'paper_pf_alignment_pct',
                            'live_trade_count',
                            'live_pf_alignment_pct',
                            'created_at',
                        ]
                    ].rename(
                        columns={
                            'regime': 'Regime',
                            'alignment_status': 'Status',
                            'paper_trade_count': 'Paper Trades',
                            'paper_profit_factor': 'PF Paper',
                            'paper_pf_alignment_pct': 'PF Paper %',
                            'live_trade_count': 'Live Trades',
                            'live_pf_alignment_pct': 'PF Live %',
                            'created_at': 'Snapshot',
                        }
                    )
                    st.dataframe(alignment_df, width="stretch", hide_index=True)

                if governance_history:
                    governance_history_df = pd.DataFrame(governance_history)[
                        [
                            'regime',
                            'previous_status',
                            'governance_status',
                            'governance_mode',
                            'alignment_status',
                            'action_reason',
                            'created_at',
                        ]
                    ].rename(
                        columns={
                            'regime': 'Regime',
                            'previous_status': 'Status Anterior',
                            'governance_status': 'Status Atual',
                            'governance_mode': 'Modo',
                            'alignment_status': 'Alignment',
                            'action_reason': 'Motivo',
                            'created_at': 'Quando',
                        }
                    )
                    st.dataframe(governance_history_df, width="stretch", hide_index=True)
            except Exception as governance_error:
                st.info(f"Governança operacional indisponível: {governance_error}")

            try:
                recent_strategy_evaluations = get_cached_strategy_evaluations(
                    symbol=result_symbol,
                    timeframe=result_timeframe,
                    strategy_version=result_strategy_version,
                    limit=5,
                )
                if not recent_strategy_evaluations:
                    recent_strategy_evaluations = get_cached_strategy_evaluations(
                        symbol=result_symbol,
                        timeframe=result_timeframe,
                        limit=5,
                    )
                evaluation_overview = get_cached_strategy_evaluation_overview(
                    symbol=result_symbol,
                    timeframe=result_timeframe,
                    limit=10,
                )

                st.markdown("### Strategy Evaluations")
                latest_evaluation = recent_strategy_evaluations[0] if recent_strategy_evaluations else None
                if latest_evaluation:
                    eval_col1, eval_col2, eval_col3, eval_col4 = st.columns(4)
                    with eval_col1:
                        st.metric("Score Atual", f"{latest_evaluation.get('quality_score', 0):.1f}")
                    with eval_col2:
                        st.metric("Origem", latest_evaluation.get("evaluation_type", "-"))
                    with eval_col3:
                        st.metric("Edge", latest_evaluation.get("edge_status", "-"))
                    with eval_col4:
                        st.metric("Governanca", latest_evaluation.get("governance_status", "-"))

                    st.caption(
                        f"Snapshot mais recente: {latest_evaluation.get('created_at_br', '-')}"
                        f" | PF Backtest {latest_evaluation.get('avg_profit_factor', 0):.2f}"
                        f" | PF OOS {latest_evaluation.get('avg_out_of_sample_profit_factor', 0):.2f}"
                        f" | PF Paper {latest_evaluation.get('paper_profit_factor', 0):.2f}"
                    )
                    st.dataframe(
                        build_strategy_evaluation_display_df(recent_strategy_evaluations),
                        width="stretch",
                        hide_index=True,
                    )
                else:
                    st.info("Ainda nao existem snapshots em strategy_evaluations para este mercado/timeframe.")

                overview_counts = evaluation_overview.get("governance_counts", {})
                edge_counts = evaluation_overview.get("edge_counts", {})
                overview_col1, overview_col2, overview_col3, overview_col4 = st.columns(4)
                with overview_col1:
                    st.metric("Setups Monitorados", evaluation_overview.get("total_strategies", 0))
                with overview_col2:
                    st.metric("Aprovados", overview_counts.get("approved", 0))
                with overview_col3:
                    st.metric("Bloqueados", overview_counts.get("blocked", 0))
                with overview_col4:
                    st.metric("Edge Degradado", edge_counts.get("degraded", 0))

                if evaluation_overview.get("rows"):
                    st.caption("Ultimo snapshot por estrategia neste mercado/timeframe.")
                    st.dataframe(
                        build_strategy_evaluation_display_df(evaluation_overview["rows"]),
                        width="stretch",
                        hide_index=True,
                    )
            except Exception as evaluation_error:
                st.info(f"Strategy evaluations indisponiveis: {evaluation_error}")

            if optimization_results and optimization_results.get('rows'):
                optimization_summary = optimization_results.get('summary', {})
                best_optimization = optimization_results.get('best') or {}

                st.markdown("### ⚡ Ranking de Otimização")
                opt_col1, opt_col2, opt_col3, opt_col4 = st.columns(4)
                with opt_col1:
                    st.metric("Testes", optimization_summary.get('completed_tests', 0))
                with opt_col2:
                    st.metric("Candidatos Robustos", optimization_summary.get('passed_candidates', 0))
                with opt_col3:
                    st.metric("Melhor Score", f"{optimization_summary.get('best_quality_score', 0):.1f}")
                with opt_col4:
                    st.metric("Métrica", optimization_summary.get('optimization_metric', '-'))

                if best_optimization:
                    st.info(
                        f"Melhor configuração: RSI {best_optimization.get('rsi_min')}-{best_optimization.get('rsi_max')} | "
                        f"Score {best_optimization.get('quality_score', 0):.1f} | "
                        f"OOS PF {best_optimization.get('oos_profit_factor', 0):.2f} | "
                        f"WF Pass Rate {best_optimization.get('walk_forward_pass_rate_pct', 0):.1f}%"
                    )

                optimization_df = pd.DataFrame(optimization_results['rows'])
                optimization_df = optimization_df[
                    [
                        'rsi_min',
                        'rsi_max',
                        'metric_value',
                        'quality_score',
                        'total_return_pct',
                        'profit_factor',
                        'oos_return_pct',
                        'oos_profit_factor',
                        'walk_forward_pass_rate_pct',
                        'robust_candidate',
                    ]
                ]
                optimization_df.columns = [
                    'RSI Min',
                    'RSI Max',
                    'Métrica',
                    'Score',
                    'Retorno %',
                    'PF',
                    'OOS %',
                    'OOS PF',
                    'WF Pass Rate %',
                    'Robusto',
                ]
                st.dataframe(optimization_df, width='stretch', hide_index=True)

                if optimization_results.get('failed_runs'):
                    with st.expander("Falhas da Otimização"):
                        st.dataframe(pd.DataFrame(optimization_results['failed_runs']), width='stretch', hide_index=True)

                st.caption("O detalhamento abaixo corresponde à melhor configuração de RSI encontrada.")

            if scan_results and scan_results.get('rows'):
                scan_summary = scan_results.get('summary', {})
                best_scan = scan_results.get('best') or {}

                st.markdown("### 🧭 Ranking Comparativo")
                scan_col1, scan_col2, scan_col3, scan_col4 = st.columns(4)
                with scan_col1:
                    st.metric("Cenários", scan_summary.get('completed_runs', 0))
                with scan_col2:
                    st.metric("OOS Aprovados", scan_summary.get('oos_passed_runs', 0))
                with scan_col3:
                    st.metric("WF Aprovados", scan_summary.get('walk_forward_passed_runs', 0))
                with scan_col4:
                    st.metric("Melhor Score", f"{scan_summary.get('best_quality_score', 0):.1f}")

                if best_scan:
                    st.info(
                        f"Melhor combinação: {best_scan.get('symbol')} {best_scan.get('timeframe')} | "
                        f"Score {best_scan.get('quality_score', 0):.1f} | "
                        f"OOS PF {best_scan.get('oos_profit_factor', 0):.2f} | "
                        f"WF Pass Rate {best_scan.get('walk_forward_pass_rate_pct', 0):.1f}%"
                    )

                scan_df = pd.DataFrame(scan_results['rows'])
                scan_df = scan_df[
                    [
                        'symbol',
                        'timeframe',
                        'quality_score',
                        'total_return_pct',
                        'profit_factor',
                        'oos_return_pct',
                        'oos_profit_factor',
                        'walk_forward_pass_rate_pct',
                        'max_drawdown',
                        'total_trades',
                    ]
                ]
                scan_df.columns = [
                    'Símbolo',
                    'Timeframe',
                    'Score',
                    'Retorno %',
                    'PF',
                    'OOS %',
                    'OOS PF',
                    'WF Pass Rate %',
                    'Drawdown %',
                    'Trades',
                ]
                st.dataframe(scan_df, width='stretch', hide_index=True)

                if scan_results.get('failed_runs'):
                    with st.expander("Falhas do Scan"):
                        st.dataframe(pd.DataFrame(scan_results['failed_runs']), width='stretch', hide_index=True)

                st.caption("O detalhamento abaixo corresponde ao melhor cenário encontrado no scan.")

            # Performance Overview
            col1, col2, col3, col4 = st.columns(4)

            # Color coding for metrics
            return_color = "normal" if stats['total_return_pct'] >= 0 else "inverse"
            winrate_color = "normal" if stats['win_rate'] >= 50 else "inverse"

            with col1:
                st.metric(
                    "💰 Retorno Total", 
                    f"{stats['total_return_pct']:.2f}%",
                    delta=f"${stats['final_balance'] - stats['initial_balance']:,.2f}"
                )
            with col2:
                st.metric("🔢 Total de Trades", stats['total_trades'])
            with col3:
                st.metric("🎯 Taxa de Acerto", f"{stats['win_rate']:.1f}%")
            with col4:
                st.metric("📉 Max Drawdown", f"-{stats['max_drawdown']:.2f}%")

            # Additional metrics row
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("📈 Sharpe Ratio", f"{stats['sharpe_ratio']:.2f}")
            with col2:
                st.metric("💹 Profit Factor", f"{stats.get('profit_factor', 0):.2f}")
            with col3:
                st.metric("✅ Trades Vencedores", stats['winning_trades'])
            with col4:
                st.metric("❌ Trades Perdedores", stats['losing_trades'])

            render_backtest_portfolio_section(
                results=results,
                stats=stats,
                result_symbol=result_symbol,
                result_timeframe=result_timeframe,
            )

            signal_pipeline_stats = results.get('signal_pipeline_stats') or {
                'candidate_count': results.get('candidate_count', 0),
                'approved_count': results.get('approved_count', 0),
                'blocked_count': results.get('blocked_count', 0),
                'approval_rate_pct': results.get('approval_rate_pct', 0.0),
                'block_reason_counts': results.get('block_reason_counts', {}),
                'regime_counts': results.get('regime_counts', {}),
                'structure_state_counts': results.get('structure_state_counts', {}),
                'confirmation_state_counts': results.get('confirmation_state_counts', {}),
                'entry_quality_counts': results.get('entry_quality_counts', {}),
                'market_state_counts': results.get('market_state_counts', {}),
                'market_state_approved_counts': results.get('market_state_approved_counts', {}),
                'market_state_blocked_counts': results.get('market_state_blocked_counts', {}),
                'execution_mode_counts': results.get('execution_mode_counts', {}),
                'setup_type_counts': results.get('setup_type_counts', {}),
                'setup_type_approved_counts': results.get('setup_type_approved_counts', {}),
                'setup_type_blocked_counts': results.get('setup_type_blocked_counts', {}),
                'setup_type_approval_rates': results.get('setup_type_approval_rates', {}),
                'setup_type_block_rates': results.get('setup_type_block_rates', {}),
            }

            st.markdown("---")
            st.subheader("🧠 Pipeline de Sinais")

            pipeline_col1, pipeline_col2, pipeline_col3, pipeline_col4 = st.columns(4)
            with pipeline_col1:
                st.metric("Candidatos", int(signal_pipeline_stats.get('candidate_count', 0) or 0))
            with pipeline_col2:
                st.metric("Aprovados", int(signal_pipeline_stats.get('approved_count', 0) or 0))
            with pipeline_col3:
                st.metric("Bloqueados", int(signal_pipeline_stats.get('blocked_count', 0) or 0))
            with pipeline_col4:
                st.metric("Taxa de Aprovação", f"{float(signal_pipeline_stats.get('approval_rate_pct', 0.0) or 0.0):.2f}%")

            breakdown_col1, breakdown_col2, breakdown_col3 = st.columns(3)
            with breakdown_col1:
                st.caption("Motivos de Bloqueio")
                block_reason_counts = signal_pipeline_stats.get('block_reason_counts') or {}
                if block_reason_counts:
                    st.dataframe(
                        pd.DataFrame(
                            [{"Motivo": reason, "Qtd": count} for reason, count in block_reason_counts.items()]
                        ),
                        width="stretch",
                        hide_index=True,
                    )
                else:
                    st.info("Nenhum bloqueio registrado neste backtest.")
            with breakdown_col2:
                st.caption("Estrutura / Confirmação")
                structure_state_counts = signal_pipeline_stats.get('structure_state_counts') or {}
                confirmation_state_counts = signal_pipeline_stats.get('confirmation_state_counts') or {}
                if structure_state_counts or confirmation_state_counts:
                    structure_rows = [
                        {"Tipo": "Estrutura", "Estado": state, "Qtd": count}
                        for state, count in structure_state_counts.items()
                    ]
                    confirmation_rows = [
                        {"Tipo": "Confirmação", "Estado": state, "Qtd": count}
                        for state, count in confirmation_state_counts.items()
                    ]
                    st.dataframe(
                        pd.DataFrame(structure_rows + confirmation_rows),
                        width="stretch",
                        hide_index=True,
                    )
                else:
                    st.info("Sem estados estruturais agregados para exibir.")
            with breakdown_col3:
                st.caption("Qualidade da Entrada")
                entry_quality_counts = signal_pipeline_stats.get('entry_quality_counts') or {}
                if entry_quality_counts:
                    st.dataframe(
                        pd.DataFrame(
                            [{"Qualidade": quality, "Qtd": count} for quality, count in entry_quality_counts.items()]
                        ),
                        width="stretch",
                        hide_index=True,
                    )
                else:
                    st.info("Sem estatísticas de entrada para exibir.")

            risk_engine_summary = results.get('risk_engine_summary') or {}
            if risk_engine_summary:
                st.caption("Risk Engine")
                risk_col1, risk_col2, risk_col3 = st.columns(3)
                with risk_col1:
                    st.metric("Bloqueados por Risco", int(risk_engine_summary.get('risk_blocked_count', 0) or 0))
                with risk_col2:
                    st.metric("Size Reduzida", int(risk_engine_summary.get('reduced_size_count', 0) or 0))
                with risk_col3:
                    st.metric("Modos de Risco", len(risk_engine_summary.get('risk_mode_counts') or {}))

                risk_breakdown_col1, risk_breakdown_col2 = st.columns(2)
                with risk_breakdown_col1:
                    st.caption("Motivos de Bloqueio por Risco")
                    risk_block_reason_counts = risk_engine_summary.get('risk_block_reason_counts') or {}
                    if risk_block_reason_counts:
                        st.dataframe(
                            pd.DataFrame(
                                [{"Motivo": reason, "Qtd": count} for reason, count in risk_block_reason_counts.items()]
                            ),
                            width="stretch",
                            hide_index=True,
                        )
                    else:
                        st.info("Nenhum sinal foi bloqueado pela risk engine neste backtest.")
                with risk_breakdown_col2:
                    st.caption("Performance por Risk Mode")
                    performance_by_risk_mode = risk_engine_summary.get('performance_by_risk_mode') or {}
                    if performance_by_risk_mode:
                        st.dataframe(
                            pd.DataFrame(
                                [
                                    {
                                        "Risk Mode": mode,
                                        "Trades": metrics.get('trades', 0),
                                        "Net Profit": metrics.get('net_profit', 0.0),
                                        "Wins": metrics.get('wins', 0),
                                        "Losses": metrics.get('losses', 0),
                                        "Win Rate %": metrics.get('win_rate', 0.0),
                                    }
                                    for mode, metrics in performance_by_risk_mode.items()
                                ]
                            ),
                            width="stretch",
                            hide_index=True,
                        )
                    else:
                        st.info("Sem trades suficientes para agregar por risk mode.")

            regime_summary = results.get('regime_summary') or stats.get('regime_breakdown') or []
            market_state_summary = results.get('market_state_summary') or stats.get('market_state_breakdown') or []
            execution_mode_summary = results.get('execution_mode_summary') or stats.get('execution_mode_breakdown') or []
            setup_type_summary = results.get('setup_type_summary') or stats.get('setup_type_breakdown') or []
            regime_counts = signal_pipeline_stats.get('regime_counts') or {}
            market_state_counts = signal_pipeline_stats.get('market_state_counts') or {}
            market_state_approved_counts = signal_pipeline_stats.get('market_state_approved_counts') or {}
            market_state_blocked_counts = signal_pipeline_stats.get('market_state_blocked_counts') or {}
            execution_mode_counts = signal_pipeline_stats.get('execution_mode_counts') or {}
            setup_type_counts = signal_pipeline_stats.get('setup_type_counts') or {}
            setup_type_approved_counts = signal_pipeline_stats.get('setup_type_approved_counts') or {}
            setup_type_blocked_counts = signal_pipeline_stats.get('setup_type_blocked_counts') or {}
            setup_type_approval_rates = signal_pipeline_stats.get('setup_type_approval_rates') or {}
            setup_type_block_rates = signal_pipeline_stats.get('setup_type_block_rates') or {}
            if regime_counts:
                st.caption("Regimes Detectados no Pipeline")
                st.dataframe(
                    pd.DataFrame(
                        [{"Regime": regime, "Qtd": count} for regime, count in regime_counts.items()]
                    ),
                    width="stretch",
                    hide_index=True,
                )
            if regime_summary:
                st.caption("Performance por Regime")
                st.dataframe(
                    pd.DataFrame(regime_summary),
                    width="stretch",
                    hide_index=True,
                )
            if market_state_counts:
                st.caption("Entradas por Estado de Mercado")
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Estado": market_state,
                                "Candidatos": count,
                                "Aprovados": int(market_state_approved_counts.get(market_state, 0) or 0),
                                "Bloqueados": int(market_state_blocked_counts.get(market_state, 0) or 0),
                            }
                            for market_state, count in market_state_counts.items()
                        ]
                    ),
                    width="stretch",
                    hide_index=True,
                )
            if market_state_summary:
                st.caption("Performance por Estado de Mercado")
                st.dataframe(
                    pd.DataFrame(market_state_summary),
                    width="stretch",
                    hide_index=True,
                )
            if execution_mode_counts:
                st.caption("Execução por Modo Operacional")
                st.dataframe(
                    pd.DataFrame(
                        [
                            {"Modo": execution_mode, "Qtd": count}
                            for execution_mode, count in execution_mode_counts.items()
                        ]
                    ),
                    width="stretch",
                    hide_index=True,
                )
            if execution_mode_summary:
                st.caption("Performance por Modo Operacional")
                st.dataframe(
                    pd.DataFrame(execution_mode_summary),
                    width="stretch",
                    hide_index=True,
                )
            if setup_type_counts or setup_type_summary:
                with st.expander("Compatibilidade Legada: Analytics por Setup", expanded=False):
                    if setup_type_counts:
                        st.caption("Entradas por Tipo de Setup (Legado)")
                        st.dataframe(
                            pd.DataFrame(
                                [
                                    {
                                        "Setup": setup_type,
                                        "Candidatos": count,
                                        "Aprovados": int(setup_type_approved_counts.get(setup_type, 0) or 0),
                                        "Bloqueados": int(setup_type_blocked_counts.get(setup_type, 0) or 0),
                                        "Taxa de Aprovação %": float(setup_type_approval_rates.get(setup_type, 0.0) or 0.0),
                                        "Taxa de Bloqueio %": float(setup_type_block_rates.get(setup_type, 0.0) or 0.0),
                                    }
                                    for setup_type, count in setup_type_counts.items()
                                ]
                            ),
                            width="stretch",
                            hide_index=True,
                        )
                    if setup_type_summary:
                        st.caption("Performance por Tipo de Setup (Legado)")
                        st.dataframe(
                            pd.DataFrame(setup_type_summary),
                            width="stretch",
                            hide_index=True,
                        )

            position_management_summary = results.get('position_management_summary') or {}
            exit_type_summary = results.get('exit_type_summary') or stats.get('exit_type_breakdown') or []
            entry_quality_summary = results.get('entry_quality_summary') or stats.get('entry_quality_breakdown') or []
            risk_mode_summary = results.get('risk_mode_summary') or stats.get('risk_mode_breakdown') or []
            signal_audit_summary = results.get('signal_audit_summary') or {}
            if position_management_summary or exit_type_summary:
                st.markdown("---")
                st.subheader("🛡️ Gestão da Posição")

                mgmt_col1, mgmt_col2, mgmt_col3, mgmt_col4 = st.columns(4)
                with mgmt_col1:
                    st.metric("Break-even", int(position_management_summary.get('break_even_activated_count', 0) or 0))
                with mgmt_col2:
                    st.metric("Trailing", int(position_management_summary.get('trailing_activated_count', 0) or 0))
                with mgmt_col3:
                    st.metric("Proteção Pós-Pump", int(position_management_summary.get('post_pump_protection_count', 0) or 0))
                with mgmt_col4:
                    st.metric(
                        "MFE / MAE Médio",
                        f"{float(position_management_summary.get('avg_mfe_pct', 0.0) or 0.0):.2f}% / "
                        f"{float(position_management_summary.get('avg_mae_pct', 0.0) or 0.0):.2f}%"
                    )

                exit_counts = stats.get('exit_reason_counts') or {}
                if exit_counts:
                    exit_rows = [{"Saída": reason, "Qtd": count} for reason, count in exit_counts.items()]
                    st.caption("Saídas por Tipo")
                    st.dataframe(pd.DataFrame(exit_rows), width="stretch", hide_index=True)

                if exit_type_summary:
                    st.caption("Performance por Tipo de Saída")
                    st.dataframe(pd.DataFrame(exit_type_summary), width="stretch", hide_index=True)

            if entry_quality_summary or risk_mode_summary or signal_audit_summary:
                st.markdown("---")
                st.subheader("🧬 Analytics Agregados")

                analytics_col1, analytics_col2, analytics_col3, analytics_col4 = st.columns(4)
                with analytics_col1:
                    st.metric("Approval Rate", f"{float(signal_audit_summary.get('approval_rate_pct', 0.0) or 0.0):.2f}%")
                with analytics_col2:
                    st.metric("MFE Médio", f"{float(stats.get('avg_mfe_pct', 0.0) or 0.0):.2f}%")
                with analytics_col3:
                    st.metric("MAE Médio", f"{float(stats.get('avg_mae_pct', 0.0) or 0.0):.2f}%")
                with analytics_col4:
                    st.metric("Lucro Devolvido", f"{float(stats.get('avg_profit_given_back_pct', 0.0) or 0.0):.2f}%")

                analytics_breakdown_col1, analytics_breakdown_col2, analytics_breakdown_col3 = st.columns(3)
                with analytics_breakdown_col1:
                    if entry_quality_summary:
                        st.caption("Performance por Entry Quality")
                        st.dataframe(pd.DataFrame(entry_quality_summary), width="stretch", hide_index=True)
                with analytics_breakdown_col2:
                    if risk_mode_summary:
                        st.caption("Performance por Risk Mode")
                        st.dataframe(pd.DataFrame(risk_mode_summary), width="stretch", hide_index=True)
                with analytics_breakdown_col3:
                    approval_by_regime = signal_audit_summary.get('approval_by_regime') or {}
                    if approval_by_regime:
                        st.caption("Aprovação por Regime")
                        st.dataframe(
                            pd.DataFrame(
                                [
                                    {
                                        "Regime": regime,
                                        "Candidatos": payload.get('candidate_count', 0),
                                        "Aprovados": payload.get('approved_count', 0),
                                        "Taxa %": payload.get('approval_rate_pct', 0.0),
                                    }
                                    for regime, payload in approval_by_regime.items()
                                ]
                            ),
                            width="stretch",
                            hide_index=True,
                        )

                block_reason_counts = signal_audit_summary.get('block_reason_counts') or {}
                time_analytics = results.get('time_analytics') or {}
                hour_of_day_breakdown = time_analytics.get('hour_of_day_breakdown') or []
                day_of_week_breakdown = time_analytics.get('day_of_week_breakdown') or []
                holding_time_breakdown = time_analytics.get('holding_time_breakdown') or []
                if block_reason_counts or hour_of_day_breakdown or day_of_week_breakdown or holding_time_breakdown:
                    analytics_time_col1, analytics_time_col2, analytics_time_col3 = st.columns(3)
                    with analytics_time_col1:
                        if block_reason_counts:
                            st.caption("Top Block Reasons")
                            st.dataframe(
                                pd.DataFrame(
                                    [{"Motivo": reason, "Qtd": count} for reason, count in block_reason_counts.items()]
                                ),
                                width="stretch",
                                hide_index=True,
                            )
                    with analytics_time_col2:
                        if hour_of_day_breakdown or day_of_week_breakdown:
                            st.caption("Performance por Hora / Dia")
                            time_rows = [
                                {
                                    "Tipo": "Hora",
                                    "Bucket": row.get('hour_of_day'),
                                    "Trades": row.get('total_trades', 0),
                                    "Retorno %": row.get('total_return_pct', 0.0),
                                    "Win Rate %": row.get('win_rate', 0.0),
                                }
                                for row in hour_of_day_breakdown
                            ]
                            time_rows.extend(
                                [
                                    {
                                        "Tipo": "Dia",
                                        "Bucket": row.get('day_of_week'),
                                        "Trades": row.get('total_trades', 0),
                                        "Retorno %": row.get('total_return_pct', 0.0),
                                        "Win Rate %": row.get('win_rate', 0.0),
                                    }
                                    for row in day_of_week_breakdown
                                ]
                            )
                            st.dataframe(pd.DataFrame(time_rows), width="stretch", hide_index=True)
                    with analytics_time_col3:
                        if holding_time_breakdown:
                            st.caption("Holding Time Buckets")
                            st.dataframe(pd.DataFrame(holding_time_breakdown), width="stretch", hide_index=True)

            if results.get('validation'):
                validation = results['validation']
                in_sample_stats = validation['in_sample']['stats']
                out_of_sample_stats = validation['out_of_sample']['stats']

                st.markdown("---")
                st.subheader("🧪 Validação Fora da Amostra")
                st.caption(
                    f"Split temporal: {100 - validation['split_pct']:.0f}% in-sample / "
                    f"{validation['split_pct']:.0f}% out-of-sample até {pd.Timestamp(validation['split_date']).strftime('%d/%m/%Y %H:%M')}"
                )

                val_col1, val_col2, val_col3, val_col4 = st.columns(4)
                with val_col1:
                    st.metric("IS Retorno", f"{in_sample_stats['total_return_pct']:.2f}%")
                with val_col2:
                    st.metric("OOS Retorno", f"{out_of_sample_stats['total_return_pct']:.2f}%")
                with val_col3:
                    st.metric("OOS Profit Factor", f"{out_of_sample_stats['profit_factor']:.2f}")
                with val_col4:
                    st.metric("OOS Expectancy", f"{out_of_sample_stats['expectancy_pct']:.2f}%")

                val_col1, val_col2, val_col3 = st.columns(3)
                with val_col1:
                    st.metric("IS Trades", in_sample_stats['total_trades'])
                with val_col2:
                    st.metric("OOS Trades", out_of_sample_stats['total_trades'])
                with val_col3:
                    st.metric("OOS Win Rate", f"{out_of_sample_stats['win_rate']:.1f}%")

                if validation.get('oos_passed'):
                    st.success(
                        f"✅ OOS aprovado: {ProductionConfig.MIN_PROMOTION_OOS_TRADES}+ trades, "
                        f"retorno > 0 e profit factor >= {ProductionConfig.MIN_PROMOTION_OOS_PROFIT_FACTOR:.2f}"
                    )
                else:
                    st.warning("⚠️ OOS fraco: a estratégia ainda não provou edge suficiente fora da amostra")

            if results.get('walk_forward'):
                walk_forward = results['walk_forward']

                st.markdown("---")
                st.subheader("🧭 Walk-Forward")

                wf_col1, wf_col2, wf_col3, wf_col4 = st.columns(4)
                with wf_col1:
                    st.metric("Janelas", walk_forward['total_windows'])
                with wf_col2:
                    st.metric("Pass Rate", f"{walk_forward['pass_rate_pct']:.1f}%")
                with wf_col3:
                    st.metric("WF Avg OOS", f"{walk_forward['avg_oos_return_pct']:.2f}%")
                with wf_col4:
                    st.metric("WF Avg PF", f"{walk_forward['avg_oos_profit_factor']:.2f}")

                wf_col1, wf_col2 = st.columns(2)
                with wf_col1:
                    st.metric("WF Avg Expectancy", f"{walk_forward['avg_oos_expectancy_pct']:.2f}%")
                with wf_col2:
                    st.metric("Janelas Aprovadas", f"{walk_forward['passed_windows']}/{walk_forward['total_windows']}")

                if walk_forward.get('overall_passed'):
                    st.success("✅ Walk-forward consistente: a maioria das janelas OOS manteve edge")
                else:
                    st.warning("⚠️ Walk-forward inconsistente: o edge ainda não se sustenta bem entre janelas")

                walk_forward_rows = []
                for window in walk_forward['windows']:
                    walk_forward_rows.append({
                        'Janela': window['window_index'],
                        'IS Fim': pd.Timestamp(window['in_sample_end']).strftime('%d/%m/%Y %H:%M'),
                        'OOS Início': pd.Timestamp(window['out_of_sample_start']).strftime('%d/%m/%Y %H:%M'),
                        'OOS Fim': pd.Timestamp(window['out_of_sample_end']).strftime('%d/%m/%Y %H:%M'),
                        'OOS Retorno %': window['out_of_sample']['stats']['total_return_pct'],
                        'OOS Profit Factor': window['out_of_sample']['stats']['profit_factor'],
                        'OOS Expectancy %': window['out_of_sample']['stats']['expectancy_pct'],
                        'Aprovada': 'Sim' if window['passed'] else 'Não',
                    })

                st.dataframe(pd.DataFrame(walk_forward_rows), width='stretch', hide_index=True)

            # Detailed Performance Analysis
            st.markdown("---")
            st.subheader("📈 Análise Detalhada de Performance")

            col1, col2 = st.columns(2)

            with col1:
                # Financial metrics
                st.markdown("**💰 Métricas Financeiras**")
                profit_loss = stats['final_balance'] - stats['initial_balance']
                profit_color = "🟢" if profit_loss >= 0 else "🔴"

                st.info(f"""
                **Saldo Inicial:** ${stats['initial_balance']:,.2f}  
                **Saldo Final:** ${stats['final_balance']:,.2f}  
                **Lucro/Prejuízo:** {profit_color} ${profit_loss:,.2f}  
                **Retorno Percentual:** {stats['total_return_pct']:.2f}%  
                **Sharpe Ratio:** {stats['sharpe_ratio']:.2f}
                """)

            with col2:
                # Trading metrics
                st.markdown("**📊 Métricas de Trading**")
                avg_profit_color = "🟢" if stats['avg_profit'] > 0 else "🟡"
                avg_loss_color = "🔴" if stats['avg_loss'] > 0 else "🟡"

                st.info(f"""
                **Trades Vencedores:** {stats['winning_trades']} ({stats['win_rate']:.1f}%)  
                **Trades Perdedores:** {stats['losing_trades']} ({100-stats['win_rate']:.1f}%)  
                **Lucro Médio:** {avg_profit_color} {stats['avg_profit']:.2f}%  
                **Perda Média:** {avg_loss_color} {stats['avg_loss']:.2f}%  
                **Máximo Drawdown:** {stats['max_drawdown']:.2f}%
                """)

            # Performance interpretation with scoring
            st.markdown("**🎯 Análise Inteligente dos Resultados**")

            # Calculate overall score
            score = 0
            max_score = 100

            # Return score (40 points max)
            if stats['total_return_pct'] > 50:
                score += 40
            elif stats['total_return_pct'] > 20:
                score += 30
            elif stats['total_return_pct'] > 10:
                score += 20
            elif stats['total_return_pct'] > 0:
                score += 10

            # Win rate score (25 points max)
            if stats['win_rate'] > 70:
                score += 25
            elif stats['win_rate'] > 60:
                score += 20
            elif stats['win_rate'] > 50:
                score += 15
            elif stats['win_rate'] > 40:
                score += 10

            # Drawdown score (20 points max)
            if stats['max_drawdown'] < 5:
                score += 20
            elif stats['max_drawdown'] < 10:
                score += 15
            elif stats['max_drawdown'] < 15:
                score += 10
            elif stats['max_drawdown'] < 25:
                score += 5

            # Sharpe ratio score (15 points max)
            if stats['sharpe_ratio'] > 2:
                score += 15
            elif stats['sharpe_ratio'] > 1:
                score += 10
            elif stats['sharpe_ratio'] > 0.5:
                score += 5

            # Display score and interpretation
            score_pct = (score / max_score) * 100

            if score_pct >= 80:
                st.success(f"🏆 **ESTRATÉGIA EXCELENTE** - Score: {score_pct:.0f}/100")
                st.success("✅ Esta estratégia demonstra alta qualidade e pode ser considerada para trading real!")
            elif score_pct >= 60:
                st.success(f"🎯 **BOA ESTRATÉGIA** - Score: {score_pct:.0f}/100")
                st.info("💡 Estratégia promissora, considere ajustes finos nos parâmetros.")
            elif score_pct >= 40:
                st.warning(f"⚠️ **ESTRATÉGIA MÉDIA** - Score: {score_pct:.0f}/100")
                st.warning("🔧 Precisa de otimização. Teste diferentes parâmetros de RSI.")
            else:
                st.error(f"❌ **ESTRATÉGIA FRACA** - Score: {score_pct:.0f}/100")
                st.error("🚫 Não recomendada para trading real. Revise completamente a abordagem.")

            # Specific recommendations
            st.markdown("**🎯 Recomendações Específicas:**")
            recommendations = []

            if stats['total_return_pct'] < 0:
                recommendations.append("📉 **Retorno negativo**: Considere inverter a lógica ou usar timeframe maior")

            if stats['win_rate'] < 50:
                recommendations.append("🎯 **Taxa de acerto baixa**: Teste RSI mais restritivo (ex: 15-85)")

            if stats['max_drawdown'] > 20:
                recommendations.append("⚠️ **Alto risco**: Implemente stop-loss ou reduza tamanho das posições")

            if stats['total_trades'] < 10:
                recommendations.append("📊 **Poucos trades**: Use timeframe menor ou período maior")

            if stats['sharpe_ratio'] < 0.5:
                recommendations.append("📈 **Baixo Sharpe**: Estratégia inconsistente, revise parâmetros")

            if stats.get('profit_factor', 0) < 1.2:
                recommendations.append("💰 **Profit Factor baixo**: Ajuste take-profit ou melhore timing de entrada")

            if not recommendations:
                recommendations.append("🏆 **Excelente trabalho!** Esta estratégia está bem calibrada.")

            for i, rec in enumerate(recommendations, 1):
                st.markdown(f"{i}. {rec}")

            # Quick optimization suggestions
            st.markdown("**⚡ Testes Rápidos Sugeridos:**")
            opt_col1, opt_col2 = st.columns(2)

            with opt_col1:
                if st.button("🔧 RSI Mais Restritivo", help="RSI 54/46"):
                    st.session_state.bt_rsi_min = 54
                    st.session_state.bt_rsi_max = 46
                    st.rerun()

                if st.button("📈 Timeframe Maior", help="Mudar para timeframe superior"):
                    current_tf = st.session_state.get('bt_timeframe', '15m')
                    tf_hierarchy = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
                    if current_tf in tf_hierarchy:
                        current_idx = tf_hierarchy.index(current_tf)
                        if current_idx < len(tf_hierarchy) - 1:
                            st.session_state.bt_timeframe = tf_hierarchy[current_idx + 1]
                            st.rerun()

            with opt_col2:
                if st.button("✅ Perfil Global", help="Reaplicar o baseline global EMA/RSI"):
                    _apply_bt_preset(
                        AppConfig.DEFAULT_BACKTEST_PRESET,
                        start_days=AppConfig.DEFAULT_BACKTEST_WINDOW_DAYS,
                    )
                    st.rerun()

                if st.button("🔄 Período Maior", help="Dobrar período de teste"):
                    current_days = (st.session_state.bt_end_date - st.session_state.bt_start_date).days
                    new_start = st.session_state.bt_end_date - timedelta(days=min(current_days * 2, max_backtest_days))
                    st.session_state.bt_start_date = new_start
                    st.rerun()

            # Trade history table
            if results['trades']:
                st.markdown("---")
                st.subheader("📋 Histórico de Trades")

                trade_df = st.session_state.backtest_engine.get_trade_summary_df()
                if not trade_df.empty:
                    # Format trade data for display
                    trade_df_display = trade_df.copy()
                    trade_df_display['timestamp'] = trade_df_display['timestamp'].dt.strftime('%d/%m/%Y %H:%M')
                    trade_df_display['entry_price'] = trade_df_display['entry_price'].apply(lambda x: f"${x:.6f}")
                    trade_df_display['price'] = trade_df_display['price'].apply(lambda x: f"${x:.6f}")
                    trade_df_display['profit_loss_pct'] = trade_df_display['profit_loss_pct'].apply(lambda x: f"{x:.2f}%")
                    trade_df_display['profit_loss'] = trade_df_display['profit_loss'].apply(lambda x: f"${x:.2f}")

                    # Rename columns
                    trade_df_display.columns = [
                        'Data/Hora', 'Preço Entrada', 'Preço Saída', 
                        'Retorno %', 'Lucro/Perda $', 'Sinal'
                    ]

                    # Show last 20 trades by default
                    display_limit = min(20, len(trade_df_display))
                    st.info(f"📊 Mostrando os últimos {display_limit} trades de {len(trade_df_display)} total")

                    st.dataframe(
                        trade_df_display.tail(display_limit), 
                        width='stretch', 
                        hide_index=True
                    )

                    # Summary of all trades
                    if len(trade_df_display) > display_limit:
                        if st.button(f"📋 Ver todos os {len(trade_df_display)} trades", key="show_all_trades"):
                            st.dataframe(trade_df_display, width='stretch', hide_index=True)

            if results.get('trade_autopsy'):
                st.markdown("---")
                st.subheader("🧪 Trade Autópsia")

                autopsy_df = pd.DataFrame(results['trade_autopsy'])
                if not autopsy_df.empty:
                    filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
                    with filter_col1:
                        regime_filter = st.multiselect(
                            "Regime",
                            sorted(str(x) for x in autopsy_df['regime'].dropna().unique().tolist()),
                            default=[],
                            key="autopsy_regime_filter",
                        )
                    with filter_col2:
                        setup_filter = st.multiselect(
                            "Setup",
                            sorted(str(x) for x in autopsy_df['setup_name'].dropna().unique().tolist()),
                            default=[],
                            key="autopsy_setup_filter",
                        )
                    with filter_col3:
                        exit_filter = st.multiselect(
                            "Saída",
                            sorted(str(x) for x in autopsy_df['exit_reason'].dropna().unique().tolist()),
                            default=[],
                            key="autopsy_exit_filter",
                        )
                    with filter_col4:
                        risk_filter = st.multiselect(
                            "Risk Mode",
                            sorted(str(x) for x in autopsy_df['risk_mode'].dropna().unique().tolist()),
                            default=[],
                            key="autopsy_risk_filter",
                        )

                    filtered_autopsy = autopsy_df.copy()
                    if regime_filter:
                        filtered_autopsy = filtered_autopsy[filtered_autopsy['regime'].astype(str).isin(regime_filter)]
                    if setup_filter:
                        filtered_autopsy = filtered_autopsy[filtered_autopsy['setup_name'].astype(str).isin(setup_filter)]
                    if exit_filter:
                        filtered_autopsy = filtered_autopsy[filtered_autopsy['exit_reason'].astype(str).isin(exit_filter)]
                    if risk_filter:
                        filtered_autopsy = filtered_autopsy[filtered_autopsy['risk_mode'].astype(str).isin(risk_filter)]

                    visible_columns = [
                        'entry_timestamp', 'timestamp', 'setup_name', 'regime', 'structure_state',
                        'confirmation_state', 'entry_quality', 'entry_score', 'risk_mode',
                        'exit_reason', 'profit_loss_pct', 'profit_loss', 'mfe_pct', 'mae_pct',
                        'rr_realized', 'profit_given_back_pct', 'holding_time_minutes'
                    ]
                    available_columns = [column for column in visible_columns if column in filtered_autopsy.columns]
                    st.dataframe(filtered_autopsy[available_columns], width='stretch', hide_index=True)

            if results.get('signal_audit'):
                st.markdown("---")
                st.subheader("🚧 Block Analytics")
                signal_audit_df = pd.DataFrame(results['signal_audit'])
                if not signal_audit_df.empty:
                    timeline_df = signal_audit_df.copy()
                    timeline_df['timestamp'] = pd.to_datetime(timeline_df.get('timestamp'), errors='coerce')
                    timeline_df = timeline_df.dropna(subset=['timestamp']).sort_values('timestamp')
                    actionable_signals = {'COMPRA', 'VENDA'}
                    if not timeline_df.empty:
                        candidate_col = (
                            timeline_df['candidate_signal']
                            if 'candidate_signal' in timeline_df.columns
                            else pd.Series('', index=timeline_df.index, dtype='object')
                        )
                        approved_col = (
                            timeline_df['approved_signal']
                            if 'approved_signal' in timeline_df.columns
                            else pd.Series('', index=timeline_df.index, dtype='object')
                        )
                        blocked_col = (
                            timeline_df['blocked_signal']
                            if 'blocked_signal' in timeline_df.columns
                            else pd.Series('', index=timeline_df.index, dtype='object')
                        )
                        scenario_col = (
                            timeline_df['scenario_score']
                            if 'scenario_score' in timeline_df.columns
                            else pd.Series(pd.NA, index=timeline_df.index, dtype='object')
                        )

                        timeline_df['candidate_flag'] = candidate_col.isin(actionable_signals).astype(int)
                        timeline_df['approved_flag'] = approved_col.isin(actionable_signals).astype(int)
                        timeline_df['blocked_flag'] = blocked_col.isin(actionable_signals).astype(int)
                        timeline_df['scenario_score'] = pd.to_numeric(scenario_col, errors='coerce')

                        if len(timeline_df) > 2000:
                            timeline_freq = '1D'
                        elif len(timeline_df) > 800:
                            timeline_freq = '6H'
                        else:
                            timeline_freq = '1H'

                        execution_timeline = (
                            timeline_df.set_index('timestamp')
                            .resample(timeline_freq)
                            .agg(
                                candidate_count=('candidate_flag', 'sum'),
                                approved_count=('approved_flag', 'sum'),
                                blocked_count=('blocked_flag', 'sum'),
                                avg_scenario_score=('scenario_score', 'mean'),
                            )
                            .reset_index()
                        )
                        execution_timeline['approval_rate_pct'] = (
                            (
                                execution_timeline['approved_count']
                                / execution_timeline['candidate_count'].replace({0: pd.NA})
                            ) * 100.0
                        ).fillna(0.0)

                        fig_execution = make_subplots(
                            rows=1,
                            cols=1,
                            specs=[[{"secondary_y": True}]],
                        )
                        fig_execution.add_trace(
                            go.Bar(
                                x=execution_timeline['timestamp'],
                                y=execution_timeline['approved_count'],
                                name='Aprovados',
                                marker_color='#2ca02c',
                                opacity=0.75,
                            ),
                            row=1,
                            col=1,
                            secondary_y=False,
                        )
                        fig_execution.add_trace(
                            go.Bar(
                                x=execution_timeline['timestamp'],
                                y=execution_timeline['blocked_count'],
                                name='Bloqueados',
                                marker_color='#d62728',
                                opacity=0.65,
                            ),
                            row=1,
                            col=1,
                            secondary_y=False,
                        )
                        fig_execution.add_trace(
                            go.Scatter(
                                x=execution_timeline['timestamp'],
                                y=execution_timeline['approval_rate_pct'],
                                mode='lines',
                                name='Taxa Aprovação %',
                                line=dict(color='#9467bd', width=2),
                            ),
                            row=1,
                            col=1,
                            secondary_y=True,
                        )
                        fig_execution.add_trace(
                            go.Scatter(
                                x=execution_timeline['timestamp'],
                                y=execution_timeline['avg_scenario_score'],
                                mode='lines',
                                name='Cenário Médio',
                                line=dict(color='#17becf', width=1.6, dash='dash'),
                            ),
                            row=1,
                            col=1,
                            secondary_y=True,
                        )

                        fig_execution.update_layout(
                            barmode='stack',
                            title=f"Timeline de Sinais (Backtest) - {result_symbol} {result_timeframe}",
                            height=420,
                            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0),
                            margin=dict(l=30, r=30, t=70, b=30),
                        )
                        fig_execution.update_yaxes(title_text="Sinais", row=1, col=1, secondary_y=False)
                        fig_execution.update_yaxes(title_text="Taxa / Score", row=1, col=1, secondary_y=True)

                        st.plotly_chart(fig_execution, width='stretch')
                        st.caption(f"Agregação temporal automática: {timeline_freq} | foco em aprovação/bloqueio e qualidade de sinais.")

                    preview_columns = [
                        'timestamp', 'candidate_signal', 'approved_signal', 'blocked_signal',
                        'block_reason', 'regime', 'structure_state', 'confirmation_state',
                        'entry_quality', 'entry_score', 'scenario_score', 'risk_mode'
                    ]
                    available_preview_columns = [column for column in preview_columns if column in signal_audit_df.columns]
                    st.dataframe(signal_audit_df[available_preview_columns].tail(50), width='stretch', hide_index=True)

            # Test comparison and history
            st.markdown("---")
            st.subheader("📊 Histórico de Testes")

            # Initialize test history
            if 'backtest_history' not in st.session_state:
                st.session_state.backtest_history = []

            # Save current result to history
            if st.button("💾 Salvar Teste Atual", key="save_current_test"):
                test_record = {
                    'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M'),
                    'symbol': result_symbol,
                    'timeframe': result_timeframe,
                    'strategy_version': result_strategy_version,
                    'period_days': period_days,
                    'rsi_min': result_rsi_min,
                    'rsi_max': result_rsi_max,
                    'return_pct': stats['total_return_pct'],
                    'win_rate': stats['win_rate'],
                    'total_trades': stats['total_trades'],
                    'max_drawdown': stats['max_drawdown'],
                    'sharpe_ratio': stats['sharpe_ratio'],
                    'score': score_pct
                }
                st.session_state.backtest_history.append(test_record)
                st.success("✅ Teste salvo no histórico!")

            # Display test history
            if st.session_state.backtest_history:
                history_df = pd.DataFrame(st.session_state.backtest_history)

                # Style the dataframe
                def style_history(val):
                    if isinstance(val, (int, float)):
                        if val > 0:
                            return 'color: green'
                        elif val < 0:
                            return 'color: red'
                    return ''

                # Show last 10 tests
                display_history = history_df.tail(10).copy()
                display_history = display_history.round(2)

                st.dataframe(
                    display_history.style.applymap(style_history, subset=['return_pct']),
                    width="stretch",
                    hide_index=True
                )

                # Best test highlight
                if len(history_df) > 0:
                    best_test = history_df.loc[history_df['score'].idxmax()]
                    st.success(f"🏆 **Melhor Teste**: {best_test['symbol']} {best_test['timeframe']} - Score: {best_test['score']:.0f} - Retorno: {best_test['return_pct']:.2f}%")

            # Action buttons
            col1, col2, col3 = st.columns(3)

            with col1:
                if st.button("🗑️ Limpar Resultados", key="clear_backtest_results"):
                    st.session_state.backtest_results = None
                    st.session_state.backtest_scan_results = None
                    st.session_state.backtest_optimization_results = None
                    st.rerun()

            with col2:
                if st.button("📋 Limpar Histórico", key="clear_history"):
                    st.session_state.backtest_history = []
                    st.rerun()

            with col3:
                if st.session_state.backtest_history:
                    history_csv = pd.DataFrame(st.session_state.backtest_history).to_csv(index=False)
                    st.download_button(
                        "💾 Exportar Histórico",
                        data=history_csv,
                        file_name=f"backtest_history_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                        mime="text/csv"
                    )

        else:
            # Enhanced help section when no results
            st.markdown("---")
            st.markdown("### 📚 Guia de Backtesting")

            # Quick start guide in columns
            guide_col1, guide_col2 = st.columns(2)

            with guide_col1:
                st.markdown("""
                **🚀 Como Começar:**

                1. **Escolha um par** (ex: BTC-USD para volatilidade)
                2. **Selecione timeframe** (15m é bom para iniciantes)
                3. **Configure período** (comece com 1-2 semanas)
                4. **Ajuste gatilhos RSI** (52/47 é o padrão mecânico)
                5. **Execute e analise**

                **💡 Dicas de Performance:**
                - Timeframes menores = mais trades
                - RSI restritivo = menos trades, mais precisão
                - Períodos maiores = resultados mais confiáveis
                """)

            with guide_col2:
                st.markdown("""
                **🎯 Métricas Importantes:**

                - **Total Return**: Quanto ganhou/perdeu
                - **Win Rate**: % de trades vencedores
                - **Max Drawdown**: Maior perda consecutiva
                - **Sharpe Ratio**: Retorno vs risco
                - **Score**: Avaliação geral (0-100)

                **⚠️ Interpretação:**
                - Score > 80: Estratégia excelente
                - Score 60-80: Boa estratégia
                - Score < 40: Precisa melhorar
                """)

            # Sample configurations
            st.markdown("**🔧 Configurações Populares:**")

            sample_col1, sample_col2, sample_col3 = st.columns(3)

            with sample_col1:
                st.info("""
                **🔥 Scalping Agressivo**
                - Timeframe: 5m
                - RSI: 54/46
                - Período: 1 semana
                - Para: traders ativos
                """)

            with sample_col2:
                st.info("""
                **⚖️ Swing Trading**
                - Timeframe: 1h
                - RSI: 52/47
                - Período: 1 mês
                - Para: trading moderado
                """)

            with sample_col3:
                st.info("""
                **🛡️ Posição Longa**
                - Timeframe: 4h
                - RSI: 50/50
                - Período: 3 meses
                - Para: investidores
                """)

    # Export Data Tab
    if active_dashboard_section == "export":
        st.subheader("⚙️ Exportar Dados")
        st.markdown("Exporte dados e sinais para análise externa")

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("### 📊 Dados Atuais")
            if st.session_state.current_data is not None:
                if st.button("💾 Exportar Dados OHLCV (CSV)"):
                    csv_data = st.session_state.current_data.to_csv()
                    st.download_button(
                        label="⬇️ Download CSV",
                        data=csv_data,
                        file_name=f"{symbol}_{timeframe}_{format_brazil_time(fmt='%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv"
                    )
            else:
                st.info("Nenhum dado disponível para exportar")

        with col2:
            st.markdown("### 🚨 Histórico de Sinais")
            if st.session_state.signals_history:
                if st.button("💾 Exportar Sinais (CSV)"):
                    signals_df = pd.DataFrame(st.session_state.signals_history)
                    csv_data = signals_df.to_csv(index=False)
                    st.download_button(
                        label="⬇️ Download CSV",
                        data=csv_data,
                        file_name=f"sinais_{format_brazil_time(fmt='%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv"
                    )
            else:
                st.info("Nenhum sinal disponível para exportar")

        # Backtest results export
        if st.session_state.backtest_results:
            st.markdown("---")
            st.markdown("### 🔬 Resultados de Backtest")
            col1, col2 = st.columns(2)

            with col1:
                if st.button("💾 Exportar Trades do Backtest"):
                    trade_df = st.session_state.backtest_engine.get_trade_summary_df()
                    if not trade_df.empty:
                        csv_data = trade_df.to_csv(index=False)
                        st.download_button(
                            label="⬇️ Download Trades CSV",
                            data=csv_data,
                            file_name=f"backtest_trades_{format_brazil_time(fmt='%Y%m%d_%H%M%S')}.csv",
                            mime="text/csv"
                        )

            with col2:
                if st.button("💾 Exportar Portfolio do Backtest"):
                    portfolio_df = pd.DataFrame(st.session_state.backtest_results['portfolio_values'])
                    csv_data = portfolio_df.to_csv(index=False)
                    st.download_button(
                        label="⬇️ Download Portfolio CSV",
                        data=csv_data,
                        file_name=f"backtest_portfolio_{format_brazil_time(fmt='%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv"
                    )

    # Admin Panel Tab
    if active_dashboard_section == "admin":
        st.subheader("👑 Painel Administrativo")

        # Admin authentication
        configured_admin_password = ProductionConfig.ADMIN_PANEL_PASSWORD
        if "admin_authenticated" not in st.session_state:
            st.session_state.admin_authenticated = False
        if "admin_auth_error" not in st.session_state:
            st.session_state.admin_auth_error = ""

        if not configured_admin_password:
            st.warning("⚠️ Configure ADMIN_PANEL_PASSWORD para liberar o painel admin.")
        else:
            auth_col1, auth_col2 = st.columns([4, 1])
            with auth_col1:
                if not st.session_state.admin_authenticated:
                    st.text_input("🔐 Senha de Admin", type="password", key="admin_pass")
            with auth_col2:
                if st.session_state.admin_authenticated:
                    if st.button("🔒 Sair", key="admin_logout"):
                        st.session_state.admin_authenticated = False
                        st.session_state.admin_auth_error = ""
                        st.session_state.admin_pass = ""
                        st.rerun()
                else:
                    if st.button("🔓 Entrar", key="admin_login"):
                        provided_password = str(st.session_state.get("admin_pass") or "")
                        if hmac.compare_digest(provided_password, configured_admin_password):
                            st.session_state.admin_authenticated = True
                            st.session_state.admin_auth_error = ""
                            st.session_state.admin_pass = ""
                            st.rerun()
                        else:
                            st.session_state.admin_auth_error = "❌ Senha incorreta"

            if st.session_state.admin_authenticated:
                st.success("✅ Sessão administrativa autenticada.")
            elif st.session_state.admin_auth_error:
                st.error(st.session_state.admin_auth_error)
            else:
                st.info("🔐 Digite a senha de administrador para acessar o painel")

        if st.session_state.get("admin_authenticated") and configured_admin_password:
            st.success("✅ Acesso autorizado!")

            user_manager = get_user_manager()
            admin_telegram_bot = get_or_init_admin_telegram_bot()

            # Admin stats
            stats = user_manager.get_user_stats()

            col1, col2, col3, col4 = st.columns(4)

            with col1:
                st.metric("👥 Total Usuários", stats['total_users'])
            with col2:
                st.metric("🆓 Usuários Free", stats['free_users'])
            with col3:
                st.metric("💎 Usuários Premium", stats['premium_users'])
            with col4:
                st.metric("🔥 Ativos Hoje", stats['active_today'])

            st.markdown("---")
            st.subheader("🧩 Runtime Multiuser")
            multiuser_summary = db.get_multiuser_dashboard_summary()
            mu_col1, mu_col2, mu_col3, mu_col4, mu_col5 = st.columns(5)
            with mu_col1:
                st.metric("Contas Ativas", int(multiuser_summary.get("active_accounts", 0) or 0))
            with mu_col2:
                st.metric("Somente Paper", int(multiuser_summary.get("paper_accounts", 0) or 0))
            with mu_col3:
                st.metric("Bloqueadas", int(multiuser_summary.get("blocked_accounts", 0) or 0))
            with mu_col4:
                st.metric("Erro Operacional", int(multiuser_summary.get("operational_error_accounts", 0) or 0))
            with mu_col5:
                st.metric("Mismatch", int(multiuser_summary.get("mismatch_accounts", 0) or 0))

            st.markdown("---")
            st.subheader("🔐 Segurança Multiuser")
            vault = None
            vault_error = ""
            try:
                from services.credential_vault import CredentialVault

                vault = CredentialVault(strict=False)
            except Exception as exc:
                vault_error = str(exc)

            sec_col1, sec_col2, sec_col3, sec_col4, sec_col5 = st.columns(5)
            with sec_col1:
                st.metric("Runtime", "ON" if ProductionConfig.ENABLE_MULTIUSER_RUNTIME else "OFF")
            with sec_col2:
                st.metric("Auto Exec", "ON" if ProductionConfig.ENABLE_MULTIUSER_AUTO_ORDER_EXECUTION else "OFF")
            with sec_col3:
                st.metric("Vault", "OK" if vault and vault.is_configured() else "PENDENTE")
            with sec_col4:
                st.metric("Token Guard", "ON" if ProductionConfig.REQUIRE_MULTIUSER_VALID_TOKEN else "OFF")
            with sec_col5:
                permission_stack = (
                    ProductionConfig.REQUIRE_MULTIUSER_VALID_PERMISSIONS
                    and ProductionConfig.REQUIRE_MULTIUSER_RECONCILIATION_OK
                )
                st.metric("Perm/Recon", "ON" if permission_stack else "OFF")

            if vault_error:
                st.error(f"Vault indisponível: {vault_error}")
            elif not vault or not vault.is_configured():
                st.warning("Configure CREDENTIAL_ENCRYPTION_KEY para armazenar credenciais de exchange com segurança.")
            else:
                st.success("Credenciais multiuser serão persistidas criptografadas com Fernet.")

            st.subheader("👤 Acesso da Dashboard")
            dashboard_access_rows = db.list_dashboard_user_access(limit=200)
            if dashboard_access_rows:
                access_df = pd.DataFrame(dashboard_access_rows)[
                    [
                        "user_id",
                        "login_name",
                        "is_active",
                        "require_password_change",
                        "telegram_username",
                        "telegram_first_name",
                        "telegram_plan",
                        "account_count",
                        "last_login_at",
                    ]
                ].rename(
                    columns={
                        "user_id": "User ID",
                        "login_name": "Login",
                        "is_active": "Ativo",
                        "require_password_change": "Troca Senha",
                        "telegram_username": "Telegram Username",
                        "telegram_first_name": "Nome",
                        "telegram_plan": "Plano",
                        "account_count": "Contas",
                        "last_login_at": "Último Login",
                    }
                )
                st.dataframe(access_df, width="stretch", hide_index=True)
            else:
                st.info("Nenhum acesso de usuário da dashboard provisionado ainda.")

            with st.form("dashboard_user_access_form"):
                access_col1, access_col2, access_col3 = st.columns(3)
                with access_col1:
                    dashboard_access_user_id = st.number_input("User ID (Dashboard)", min_value=1, step=1, key="dashboard_access_user_id")
                    dashboard_access_login = st.text_input("Login da Dashboard", key="dashboard_access_login")
                with access_col2:
                    dashboard_access_password = st.text_input("Senha Inicial", type="password", key="dashboard_access_password")
                    dashboard_access_active = st.checkbox("Acesso Ativo", value=True, key="dashboard_access_active")
                with access_col3:
                    dashboard_force_password_change = st.checkbox(
                        "Forçar Troca de Senha",
                        value=True,
                        key="dashboard_force_password_change",
                    )
                    dashboard_access_notes = st.text_area("Notas do Acesso", key="dashboard_access_notes")

                if st.form_submit_button("Salvar Acesso da Dashboard"):
                    try:
                        db.upsert_dashboard_user_access(
                            {
                                "user_id": int(dashboard_access_user_id),
                                "login_name": str(dashboard_access_login).strip(),
                                "password": str(dashboard_access_password),
                                "is_active": bool(dashboard_access_active),
                                "require_password_change": bool(dashboard_force_password_change),
                                "notes": dashboard_access_notes,
                            }
                        )
                        st.success("Acesso da dashboard salvo com sucesso.")
                        st.rerun()
                    except Exception as access_error:
                        st.error(f"Falha ao salvar acesso da dashboard: {access_error}")

            st.subheader("🏦 Contas Multiuser")
            account_overview = db.get_multiuser_account_overview(limit=200)
            if account_overview:
                account_df = pd.DataFrame(account_overview)
                st.dataframe(account_df, width="stretch", hide_index=True)
            else:
                st.info("Nenhuma conta multiuser cadastrada.")

            st.subheader("🧾 Onboarding de Conta")
            with st.form("multiuser_account_form"):
                acc_col1, acc_col2, acc_col3 = st.columns(3)
                with acc_col1:
                    mu_user_id = st.number_input("User ID", min_value=1, step=1, key="mu_user_id")
                    mu_account_id = st.text_input("Account ID", key="mu_account_id")
                    mu_account_alias = st.text_input("Alias", key="mu_account_alias")
                with acc_col2:
                    mu_exchange = st.selectbox(
                        "Exchange",
                        options=AppConfig.BRAZIL_SUPPORTED_EXCHANGES or ["binance"],
                        key="mu_exchange",
                    )
                    mu_status = st.selectbox("Status", options=["active", "disabled"], key="mu_status")
                    mu_capital_base = st.number_input("Capital Base", min_value=0.0, value=10000.0, step=100.0, key="mu_capital_base")
                with acc_col3:
                    mu_live_enabled = st.checkbox("Live Enabled", value=True, key="mu_live_enabled")
                    mu_paper_enabled = st.checkbox("Paper Enabled", value=True, key="mu_paper_enabled")
                    mu_risk_mode = st.selectbox("Risk Mode", options=["normal", "reduced", "blocked"], key="mu_risk_mode")

                mu_allowed_symbols = st.text_input(
                    "Símbolos Permitidos",
                    value="BTC/USDT,ETH/USDT",
                    help="Lista separada por vírgula.",
                    key="mu_allowed_symbols",
                )
                mu_allowed_timeframes = st.multiselect(
                    "Timeframes Permitidos",
                    options=["5m", "15m", "30m", "1h", "4h", "1d"],
                    default=["15m", "1h"],
                    key="mu_allowed_timeframes",
                )
                mu_account_notes = st.text_area("Notas da Conta", key="mu_account_notes")
                if st.form_submit_button("Salvar Conta Multiuser"):
                    db.upsert_user_account(
                        {
                            "user_id": int(mu_user_id),
                            "account_id": str(mu_account_id).strip(),
                            "account_alias": str(mu_account_alias or mu_account_id).strip(),
                            "exchange": mu_exchange,
                            "status": mu_status,
                            "live_enabled": bool(mu_live_enabled),
                            "paper_enabled": bool(mu_paper_enabled),
                            "capital_base": float(mu_capital_base),
                            "risk_mode": mu_risk_mode,
                            "allowed_symbols": [item.strip() for item in str(mu_allowed_symbols).split(",") if item.strip()],
                            "allowed_timeframes": list(mu_allowed_timeframes),
                            "notes": mu_account_notes,
                        }
                    )
                    st.success("Conta multiuser salva com sucesso.")

            st.subheader("🛡️ Perfil de Risco")
            with st.form("multiuser_risk_profile_form"):
                risk_col1, risk_col2, risk_col3 = st.columns(3)
                with risk_col1:
                    risk_user_id = st.number_input("User ID (Risco)", min_value=1, step=1, key="risk_user_id")
                    risk_account_id = st.text_input("Account ID (Risco)", key="risk_account_id")
                    risk_mode_profile = st.selectbox("Modo", options=["normal", "reduced", "blocked"], key="risk_mode_profile")
                with risk_col2:
                    max_risk_per_trade = st.number_input("Risco por Trade %", min_value=0.0, value=0.5, step=0.1, key="max_risk_per_trade")
                    max_daily_loss = st.number_input("Loss Diário %", min_value=0.0, value=2.0, step=0.1, key="max_daily_loss")
                    max_drawdown = st.number_input("Drawdown Máx %", min_value=0.0, value=10.0, step=0.5, key="max_drawdown")
                with risk_col3:
                    max_portfolio_open_risk_pct = st.number_input(
                        "Risco Aberto Máx %",
                        min_value=0.0,
                        value=2.0,
                        step=0.1,
                        key="max_portfolio_open_risk_pct",
                    )
                    allowed_position_count = st.number_input("Máx Posições", min_value=0, value=3, step=1, key="allowed_position_count")
                    leverage_cap = st.number_input("Leverage Cap", min_value=0.0, value=5.0, step=0.5, key="leverage_cap")

                preferred_symbols = st.text_input(
                    "Símbolos Preferidos",
                    value="BTC/USDT,ETH/USDT",
                    help="Lista separada por vírgula.",
                    key="preferred_symbols",
                )
                risk_is_valid = st.checkbox("Risk Profile Válido", value=True, key="risk_is_valid")
                risk_live_enabled = st.checkbox("Live liberado no risco", value=True, key="risk_live_enabled")
                risk_paper_enabled = st.checkbox("Paper liberado no risco", value=True, key="risk_paper_enabled")
                if st.form_submit_button("Salvar Perfil de Risco"):
                    db.upsert_user_risk_profile(
                        {
                            "user_id": int(risk_user_id),
                            "account_id": str(risk_account_id).strip(),
                            "max_risk_per_trade": float(max_risk_per_trade),
                            "max_daily_loss": float(max_daily_loss),
                            "max_drawdown": float(max_drawdown),
                            "max_portfolio_open_risk_pct": float(max_portfolio_open_risk_pct),
                            "allowed_position_count": int(allowed_position_count),
                            "preferred_symbols": [item.strip() for item in str(preferred_symbols).split(",") if item.strip()],
                            "leverage_cap": float(leverage_cap),
                            "risk_mode": risk_mode_profile,
                            "is_valid": bool(risk_is_valid),
                            "live_enabled": bool(risk_live_enabled),
                            "paper_enabled": bool(risk_paper_enabled),
                        }
                    )
                    st.success("Perfil de risco salvo com sucesso.")

            st.subheader("🔑 Credenciais Criptografadas")
            if vault and vault.is_configured():
                with st.form("multiuser_credentials_form"):
                    cred_col1, cred_col2, cred_col3 = st.columns(3)
                    with cred_col1:
                        cred_user_id = st.number_input("User ID (Credencial)", min_value=1, step=1, key="cred_user_id")
                        cred_account_id = st.text_input("Account ID (Credencial)", key="cred_account_id")
                        cred_exchange = st.selectbox(
                            "Exchange (Credencial)",
                            options=AppConfig.BRAZIL_SUPPORTED_EXCHANGES or ["binance"],
                            key="cred_exchange",
                        )
                    with cred_col2:
                        cred_alias = st.text_input("Alias da Credencial", key="cred_alias")
                        permission_status = st.selectbox("Permission Status", options=["valid", "unknown", "blocked"], key="permission_status")
                        token_status = st.selectbox("Token Status", options=["valid", "unknown", "expired"], key="token_status")
                    with cred_col3:
                        reconciliation_status = st.selectbox("Reconciliation", options=["ok", "unknown", "broken"], key="reconciliation_status")
                        permissions_trade = st.checkbox("Permissão de Trade", value=True, key="permissions_trade")
                        permissions_withdraw = st.checkbox("Permissão de Saque", value=False, key="permissions_withdraw")

                    api_key = st.text_input("API Key", type="password", key="cred_api_key")
                    api_secret = st.text_input("API Secret", type="password", key="cred_api_secret")
                    credential_notes = st.text_area("Notas da Credencial", key="credential_notes")
                    if st.form_submit_button("Salvar Credenciais com Vault"):
                        if api_key and api_secret and cred_account_id:
                            vault.store_exchange_credentials(
                                db,
                                user_id=int(cred_user_id),
                                account_id=str(cred_account_id).strip(),
                                exchange=str(cred_exchange).strip(),
                                api_key=api_key,
                                api_secret=api_secret,
                                credential_alias=cred_alias,
                                permissions_read=True,
                                permissions_trade=bool(permissions_trade),
                                permissions_withdraw=bool(permissions_withdraw),
                                permission_status=permission_status,
                                token_status=token_status,
                                reconciliation_status=reconciliation_status,
                                notes=credential_notes,
                            )
                            st.success("Credenciais armazenadas com criptografia.")
                        else:
                            st.error("Informe account_id, api_key e api_secret para salvar as credenciais.")
            else:
                st.info("Configure o vault para liberar o cadastro seguro de credenciais.")

            # User management
            st.markdown("---")
            st.subheader("👥 Gerenciamento de Usuários")

            # List users
            users = user_manager.list_users(50)
            if users:
                users_df = pd.DataFrame(users)

                # Format datetime columns
                if 'joined' in users_df.columns:
                    users_df['joined'] = pd.to_datetime(users_df['joined']).dt.strftime('%d/%m/%Y')
                if 'last_analysis' in users_df.columns:
                    users_df['last_analysis'] = users_df['last_analysis'].fillna('Nunca')
                    users_df.loc[users_df['last_analysis'] != 'Nunca', 'last_analysis'] = pd.to_datetime(users_df.loc[users_df['last_analysis'] != 'Nunca', 'last_analysis']).dt.strftime('%d/%m/%Y %H:%M')

                st.dataframe(users_df, width='stretch', hide_index=True)

            st.markdown("---")
            st.subheader("Strategy Evaluations")

            evaluation_overview = get_cached_strategy_evaluation_overview(limit=25)
            governance_counts = evaluation_overview.get("governance_counts", {})
            edge_counts = evaluation_overview.get("edge_counts", {})

            eval_col1, eval_col2, eval_col3, eval_col4 = st.columns(4)
            with eval_col1:
                st.metric("Setups com Snapshot", evaluation_overview.get("total_strategies", 0))
            with eval_col2:
                st.metric("Aprovados", governance_counts.get("approved", 0))
            with eval_col3:
                st.metric("Bloqueados", governance_counts.get("blocked", 0))
            with eval_col4:
                st.metric("Edge Degradado", edge_counts.get("degraded", 0))

            if evaluation_overview.get("rows"):
                st.dataframe(
                    build_strategy_evaluation_display_df(evaluation_overview["rows"]),
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.info("Nenhum snapshot encontrado em strategy_evaluations.")

            # User actions
            st.markdown("---")
            st.subheader("🔧 Ações de Usuário")

            col1, col2 = st.columns(2)

            with col1:
                user_id_upgrade = st.number_input("ID do Usuário para Upgrade", min_value=1, key="upgrade_user")
                if st.button("💎 Promover para Premium"):
                    if user_manager.upgrade_to_premium(int(user_id_upgrade)):
                        st.success(f"✅ Usuário {user_id_upgrade} promovido para Premium!")
                    else:
                        st.error("❌ Usuário não encontrado")

            with col2:
                new_admin_id = st.number_input("ID do Novo Admin", min_value=1, key="new_admin")
                if st.button("👑 Adicionar Admin"):
                    user_manager.add_admin(int(new_admin_id))
                    st.success(f"✅ Usuário {new_admin_id} adicionado como Admin!")

            # Telegram Bot Configuration
            st.markdown("---")
            st.subheader("🤖 Configuração do Bot Telegram")
            bot_token_admin = st.text_input(
                "Token do Bot Telegram",
                type="password",
                help="Token para o bot interativo do Telegram",
                key="bot_token_admin"
            )

            col1, col2 = st.columns(2)

            with col1:
                if st.button("🚀 Configurar Bot") and bot_token_admin:
                    if admin_telegram_bot and admin_telegram_bot.configure(bot_token_admin):
                        st.success("✅ Bot Telegram configurado com sucesso!")
                        st.info("💡 O bot agora está pronto para receber comandos dos usuários!")
                    else:
                        st.error("❌ Erro na configuração do bot")

            with col2:
                if st.button("📤 Testar Bot") and admin_telegram_bot and admin_telegram_bot.is_configured():
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        success, message = loop.run_until_complete(
                            admin_telegram_bot.test_connection()
                        )
                        if success:
                            st.success(f"✅ {message}")
                        else:
                            st.error(f"❌ {message}")
                    except Exception as e:
                        st.error(f"❌ Erro: {str(e)}")

            # Bot status
            if admin_telegram_bot and admin_telegram_bot.is_configured():
                st.success("🟢 Bot Telegram está ativo e pronto para uso!")
                st.info("💬 Os usuários podem usar comandos como /analise BTC/USDT")
            elif admin_telegram_bot is None:
                st.warning("🟡 Bot Telegram admin não pôde ser inicializado neste ambiente")
            else:
                st.warning("🟡 Bot Telegram não configurado")

            # Broadcast message
            st.markdown("---")
            st.subheader("📢 Enviar Comunicado")

            broadcast_msg = st.text_area("Mensagem para todos os usuários", key="broadcast_msg")
            if st.button("📤 Enviar para Todos") and broadcast_msg:
                st.info("Funcionalidade de broadcast disponível via comando /broadcast no Telegram")

        elif configured_admin_password:
            st.info("🔐 Digite a senha de administrador para acessar o painel")

    # Footer
    st.markdown("---")
    st.markdown("""
    <div style='text-align: center; color: gray;'>
    Trading Signals Dashboard - Desenvolvido com Streamlit | ⚠️ Este sistema é apenas para fins educacionais
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
