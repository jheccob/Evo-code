import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import time
import json
import os
from datetime import datetime, timedelta, date
import asyncio
import threading

# Importar funções de fuso horário brasileiro
from utils.timezone_utils import now_brazil, format_brazil_time, get_brazil_datetime_naive, BRAZIL_TZ

# Importar banco de dados
from database.database import db
from trading_bot import TradingBot
from indicators import TechnicalIndicators
from config.exchange_config import ExchangeConfig

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

from backtest import BacktestEngine

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

# Configure page
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
from config.exchange_config import ExchangeConfig

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

# Initialize Telegram Trading Bot for /start command functionality
if 'telegram_trading_bot_started' not in st.session_state:
    try:
        # Import and start telegram bot in background
        import start_telegram_bot
        st.session_state.telegram_trading_bot_started = True
        print("🚀 Bot Telegram inicializado em background")
    except Exception as e:
        print(f"⚠️ Erro ao inicializar bot Telegram: {e}")
        st.session_state.telegram_trading_bot_started = False
    # Configuração será carregada automaticamente no __init__

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

# Continue with sidebar configuration

# Test WebSocket connection
if st.sidebar.button("🧪 Testar WebSocket Binance"):
    with st.spinner("Testando WebSocket público da Binance Futures..."):
        try:
            from config.exchange_config import ExchangeConfig
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
st.sidebar.subheader("📊 Pares de Moedas")
enable_multi_symbol = st.sidebar.checkbox("🔀 Monitoramento Múltiplo", value=False)

if enable_multi_symbol:
    # Pares USDT disponíveis na Binance via WebSocket
    available_pairs = ["BTC/USDT", "ETH/USDT", "ADA/USDT", "SOL/USDT", "XRP/USDT",
                      "DOGE/USDT", "LTC/USDT", "AVAX/USDT", "MATIC/USDT", "DOT/USDT", 
                      "LINK/USDT", "UNI/USDT", "ATOM/USDT", "FTM/USDT", "NEAR/USDT"]

    selected_symbols = st.sidebar.multiselect(
        "Selecionar pares para monitorar:",
        available_pairs,
        default=["XLM/USDT", "BTC/USDT", "ETH/USDT"]
    )

    if not selected_symbols:
        st.sidebar.warning("⚠️ Selecione pelo menos um par")
        selected_symbols = ["XLM-USDT"]

    # For multi-symbol mode, use the first selected as primary
    symbol = selected_symbols[0] if selected_symbols else "XLM-USDT"

else:
    # Pares USDT populares na Binance
    symbol_options = ["BTC/USDT", "ETH/USDT", "ADA/USDT", "SOL/USDT", "XRP/USDT", 
                     "DOGE/USDT", "LTC/USDT", "AVAX/USDT", "MATIC/USDT", "DOT/USDT"]

    symbol = st.sidebar.selectbox(
        "Par de Trading",
        symbol_options,
        index=0
    )
    selected_symbols = [symbol]

# Timeframe selection - Coinbase supported timeframes
timeframe = st.sidebar.selectbox(
    "Timeframe",
    ["1m", "5m", "15m", "1h", "6h", "1d"],
    index=1
)

# RSI Parameters - Otimizado para máxima acurácia
st.sidebar.subheader("📊 Parâmetros RSI (Otimizados)")
rsi_period = st.sidebar.slider("Período RSI", 5, 50, 14, help="14 períodos é o padrão mais testado")
rsi_min = st.sidebar.slider("RSI Mínimo (Compra)", 10, 40, 25, help="25 reduz falsos sinais")
rsi_max = st.sidebar.slider("RSI Máximo (Venda)", 60, 90, 75, help="75 aumenta precisão")

# Configurações Avançadas para Day Trading
with st.sidebar.expander("📈 Day Trading Otimizado", expanded=True):
    st.markdown("**⚡ Configurações para Day Trader**")

    # Modo Day Trading
    day_trading_mode = st.checkbox("🚀 Modo Day Trading", value=True, help="Configurações otimizadas para operações rápidas")

    if day_trading_mode:
        from config.app_config import AppConfig
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
        from config.app_config import AppConfig
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

    require_volume = st.checkbox("Exigir Volume Alto", value=True, help="Volume 80%+ acima da média")
    require_trend = st.checkbox("Exigir Tendência Clara", value=True, help="ADX > 28")
    avoid_ranging = st.checkbox("Evitar Mercados Laterais", value=True, help="Filtro anti-ranging")

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
            st.sidebar.success("✅ Telegram configurado via Replit Secrets!")
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
        st.sidebar.info("🔧 Configure seu bot do Telegram:")

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

            submitted = st.form_submit_button("💾 Salvar Configuração")

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

# Update bot configuration - SEMPRE usar configurações do dashboard
print(f"=== CONFIGURAÇÕES APLICADAS AO BOT ===")
print(f"Símbolo: {symbol}")
print(f"Timeframe: {timeframe}")
print(f"RSI Período: {rsi_period}")
print(f"RSI Mínimo (Compra): {rsi_min}")
print(f"RSI Máximo (Venda): {rsi_max}")
print(f"Day Trading Mode: {day_trading_mode}")
# Remove unused crypto_optimized reference
# if 'crypto_optimized' in locals():
#     print(f"Crypto Otimizado: {crypto_optimized}")
print("=====================================")

st.session_state.trading_bot.update_config(
    symbol=symbol,
    timeframe=timeframe,
    rsi_period=rsi_period,
    rsi_min=rsi_min,
    rsi_max=rsi_max
)

# Verificar se a configuração foi aplicada corretamente
bot_config = st.session_state.trading_bot
print(f"VERIFICAÇÃO - Bot configurado com:")
print(f"  RSI Período: {bot_config.rsi_period}")
print(f"  RSI Min: {bot_config.rsi_min}")
print(f"  RSI Max: {bot_config.rsi_max}")
print(f"  Símbolo: {bot_config.symbol}")
print(f"  Timeframe: {bot_config.timeframe}")

# Main dashboard
st.title("📈 Trading Signals Dashboard")

# Status do WebSocket Binance
st.success("✅ **Binance WebSocket Público Ativo** - Dados em tempo real sem credenciais")
st.info("📡 Conectado via WebSocket público da Binance Futures - Sem limites de API")

# Import user manager for admin features  
try:
    from user_manager import UserManager
    USER_MANAGER_AVAILABLE = True
except ImportError:
    # Fallback para UserManager
    class UserManager:
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
    USER_MANAGER_AVAILABLE = False

# Initialize user manager
if 'user_manager' not in st.session_state:
    st.session_state.user_manager = UserManager()

# Telegram trading bot disabled for now due to import issues
# if 'telegram_trading_bot' not in st.session_state:
#     st.session_state.telegram_trading_bot = TelegramTradingBot()

# Initialize session state for multi-symbol data
if 'multi_symbol_data' not in st.session_state:
    st.session_state.multi_symbol_data = {}

# Import WebSocket trading bot
try:
    from trading_bot_websocket import StreamlinedTradingBot
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False

# Import futures trading
try:
    from futures_trading import FuturesTrading
    FUTURES_AVAILABLE = True
except ImportError:
    FUTURES_AVAILABLE = False

# Initialize futures trading if available (with error handling)
if 'futures_trading' not in st.session_state:
    if FUTURES_AVAILABLE:
        try:
            st.session_state.futures_trading = FuturesTrading()
        except Exception as e:
            st.sidebar.warning(f"⚠️ Futures trading não disponível: {str(e)}")
            FUTURES_AVAILABLE = False
    else:
        st.session_state.futures_trading = None

# Create tabs for different sections
tab1, tab2, tab3, tab4, tab5 = st.tabs(["📡 WebSocket Binance", "🚀 Análise Mercado Futuro", "🔬 Backtesting", "⚙️ Exportar Dados", "👑 Admin Panel"])

# Nova aba para WebSocket Binance Futures
with tab1:
    st.subheader("📡 Binance Futures WebSocket - Dados em Tempo Real")
    st.markdown("**Análise otimizada com streaming de dados em tempo real da Binance**")
    
    if WEBSOCKET_AVAILABLE:
        # Usar apenas WebSocket público da Binance Futures
        st.success("✅ **WebSocket Público Binance Futures** - Dados em tempo real sem credenciais")
        st.info("🔹 **Modo Público:** Sinais gerados a partir de dados de mercado em tempo real")
            
        # Configurações WebSocket
        col1, col2, col3 = st.columns(3)
        
        with col1:
            ws_symbol = st.selectbox(
                "🪙 Símbolo Binance",
                ["BTCUSDT", "ETHUSDT", "ADAUSDT", "SOLUSDT", "DOTUSDT", "XLMUSDT"],
                index=0,
                help="Símbolo para análise em tempo real"
            )
            
        with col2:
            ws_timeframe = st.selectbox(
                "⏰ Timeframe",
                ["1m", "3m", "5m", "15m", "30m", "1h"],
                index=2,
                help="Intervalo de tempo para análise"
            )
            
        with col3:
            ws_active = st.checkbox(
                "🔄 Ativar WebSocket",
                value=False,
                help="Iniciar streaming de dados em tempo real"
            )
        
        # Status do WebSocket
        if 'ws_bot' not in st.session_state:
            st.session_state.ws_bot = None
            st.session_state.ws_data = None
            st.session_state.ws_signals = []
            
        # Controles WebSocket
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("🚀 Iniciar WebSocket", disabled=ws_active):
                if st.session_state.ws_bot is None and WEBSOCKET_AVAILABLE:
                    try:
                        st.session_state.ws_bot = StreamlinedTradingBot(ws_symbol, ws_timeframe)
                        st.success(f"✅ WebSocket Bot criado para {ws_symbol}")
                    except Exception as e:
                        st.error(f"❌ Erro ao criar bot: {e}")
                else:
                    st.info("ℹ️ Bot já inicializado")
                    
        with col2:
            if st.button("📊 Status Bot"):
                if st.session_state.ws_bot:
                    status = st.session_state.ws_bot.get_current_status()
                    st.json(status)
                else:
                    st.warning("⚠️ Bot não inicializado")
                    
        with col3:
            if st.button("🛑 Parar WebSocket"):
                if st.session_state.ws_bot:
                    st.session_state.ws_bot.stop()
                    st.session_state.ws_bot = None
                    st.success("✅ WebSocket parado")
        
        # Área de dados em tempo real com loop de 60 segundos
        if ws_active and st.session_state.ws_bot:
            st.markdown("---")
            st.subheader("📈 Dados em Tempo Real - Loop 60 Segundos")
            
            # Status do loop
            st.success("⏰ **Sistema funcionando a cada 60 segundos** - Dados atualizados automaticamente")
            
            # Próxima atualização
            import time
            next_update = int(time.time()) % 60
            seconds_remaining = 60 - next_update
            st.info(f"🔄 Próxima atualização em: **{seconds_remaining} segundos**")
            
            # Placeholder para dados
            data_placeholder = st.empty()
            signal_placeholder = st.empty()
            
            # Dados do bot (se disponível)
            if hasattr(st.session_state.ws_bot, 'current_signal'):
                with data_placeholder.container():
                    col1, col2, col3, col4 = st.columns(4)
                    
                    with col1:
                        price = getattr(st.session_state.ws_bot, 'last_price', 0)
                        st.metric(
                            label="💰 Preço Atual",
                            value=f"${price:.4f}",
                            delta="Atualizado"
                        )
                        
                    with col2:
                        st.metric(
                            label="📊 RSI",
                            value="Calculando...",
                            delta="A cada 60s"
                        )
                        
                    with col3:
                        st.metric(
                            label="📈 MACD",
                            value="Calculando...",
                            delta="A cada 60s"
                        )
                        
                    with col4:
                        signal = getattr(st.session_state.ws_bot, 'current_signal', 'INICIANDO')
                        st.metric(
                            label="🎯 Sinal",
                            value=signal,
                            delta="60s loop"
                        )
                
                with signal_placeholder.container():
                    st.success("✅ **Bot ativo com loop de 60 segundos** - Análises automáticas usando WebSocket público")
            else:
                with signal_placeholder.container():
                    st.info("🔄 Iniciando bot com loop de 60 segundos...")
                
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

with tab2:
    st.subheader("🚀 Trading de Mercado Futuro")
    st.markdown("**Trade com alavancagem, posições long/short e gerenciamento avançado de risco**")

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
        "🎯 Sinais & Análise", "⚖️ Calculadoras", "📊 Posições Simuladas"
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
            signal = "NEUTRO"
            last_candle = None
            sym_data = None

            try:
                # Check if we have cached data for this symbol that's less than 60 seconds old
                cache_key = f"{sym}_{timeframe}"
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
                        signal = cached_data['signal']
                        last_candle = cached_data['last_candle']

                if should_refresh:
                    # Use shared trading bot instance
                    st.session_state.trading_bot.update_config(symbol=sym, timeframe=timeframe, rsi_period=rsi_period, rsi_min=rsi_min, rsi_max=rsi_max)
                    sym_data = st.session_state.trading_bot.get_market_data(limit=200)

                    if sym_data is not None and not sym_data.empty:
                        last_candle = sym_data.iloc[-1]
                        signal = st.session_state.trading_bot.check_signal(sym_data)

                        # Cache the data
                        st.session_state.multi_symbol_data[cache_key] = {
                            'data': sym_data,
                            'signal': signal,
                            'last_candle': last_candle,
                            'last_update': current_time
                        }
                    else:
                        continue

                # Skip if we don't have valid data
                if last_candle is None:
                    continue

                # Check for new signals to send alerts
                if (signal not in ["NEUTRO"] and 
                    st.session_state.telegram_notifications and 
                    st.session_state.telegram_bot.is_configured()):

                    # Check if this is a new signal for this symbol
                    last_signal_key = f"{sym}_last_signal"
                    if (last_signal_key not in st.session_state.multi_symbol_signals or 
                        st.session_state.multi_symbol_signals[last_signal_key]['signal'] != signal or
                        (current_time - st.session_state.multi_symbol_signals[last_signal_key]['timestamp']).total_seconds() > 300):

                        # Send alert for this symbol
                        try:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            loop.run_until_complete(
                                st.session_state.telegram_bot.send_signal_alert(
                                    symbol=sym,
                                    signal=signal,
                                    price=last_candle['close'],
                                    rsi=last_candle['rsi'],
                                    macd=last_candle['macd'],
                                    macd_signal=last_candle['macd_signal']
                                )
                            )

                            # Update last signal tracking
                            st.session_state.multi_symbol_signals[last_signal_key] = {
                                'signal': signal,
                                'timestamp': current_time
                            }
                        except Exception as e:
                            pass  # Silent fail for overview performance

                    # Add to signals history
                    st.session_state.signals_history.append({
                        'timestamp': current_time,
                        'symbol': sym,
                        'price': last_candle['close'],
                        'rsi': last_candle['rsi'],
                        'macd': last_candle['macd'],
                        'macd_signal': last_candle['macd_signal'],
                        'signal': signal
                    })

                # Only add to overview if we have valid data
                if last_candle is not None:
                    overview_data.append({
                        'Par': sym,
                        'Preço': f"${last_candle['close']:.6f}",
                        'RSI': f"{last_candle['rsi']:.2f}",
                        'MACD': f"{last_candle['macd']:.4f}",
                        'Sinal Spot': signal,
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
                    'Sinal Spot': 'ERRO',
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
                    elif val == 'COMPRA_FRACA':
                        return 'background-color: #FFFF99'
                    elif val == 'VENDA_FRACA':
                        return 'background-color: #FFD4A3'
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

        st.subheader(f"📈 Análise Detalhada de Futuros - {symbol}")

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
                    success = st.session_state.telegram_bot.configure(telegram_token_main, telegram_chat_id_main)
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
                        st.error("❌ Erro na configuração")
                else:
                    st.warning("⚠️ Preencha ambos os campos")

        with col2:
            if telegram_token_main and telegram_chat_id_main:
                if st.button("📤 Testar", key="test_telegram_main"):
                    temp_bot = st.session_state.telegram_bot
                    if temp_bot.configure(telegram_token_main, telegram_chat_id_main):
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

    # Calculate signal
    signal = st.session_state.trading_bot.check_signal(data)

    # Store data for multi-symbol monitoring
    st.session_state.multi_symbol_data[symbol] = {
        'data': data,
        'signal': signal,
        'last_candle': last_candle,
        'last_update': st.session_state.last_update
    }

    # Add signal to history if it's a new signal
    if signal not in ["NEUTRO"] and (
        not st.session_state.signals_history or 
        st.session_state.signals_history[-1]['signal'] != signal or
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
            'price': last_candle['close'],
            'rsi': last_candle['rsi'],
            'macd': last_candle['macd'],
            'macd_signal': last_candle['macd_signal'],
            'signal': signal,
            'timeframe': timeframe,
            'macd_value': last_candle['macd'],
            'signal_strength': abs(last_candle['rsi'] - 50) / 50,  # Força do sinal baseada no RSI
            'volume': last_candle.get('volume', 0)
        }

        # Salvar no banco de dados
        try:
            db.save_trading_signal(signal_data)
        except Exception as e:
            st.error(f"Erro ao salvar sinal no banco: {str(e)}")

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
            "COMPRA": "🟢", "VENDA": "🔴", "NEUTRO": "⚪",
            "COMPRA_FRACA": "🟡", "VENDA_FRACA": "🟠"
        }
        st.metric(
            label="🚨 Sinal",
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
        # Status dinâmico com indicador de conexão
        current_time_now = get_brazil_datetime_naive()
        if st.session_state.last_update:
            seconds_since_update = (current_time_now - st.session_state.last_update).total_seconds()
            
            if seconds_since_update < 30:
                status_color = "🟢"
                status_text = "Conectado"
                delta_text = f"Há {int(seconds_since_update)}s"
            elif seconds_since_update < 60:
                status_color = "🟡"
                status_text = "Atualizando"
                delta_text = f"Há {int(seconds_since_update)}s"
            else:
                status_color = "🔴"
                status_text = "Reconectando"
                delta_text = f"Há {int(seconds_since_update//60)}min"
        else:
            status_color = "⚪"
            status_text = "Iniciando"
            delta_text = "..."
        
        st.metric(
            label="📡 Status",
            value=f"{status_color} {status_text}",
            delta=delta_text
        )

    # Price, RSI and MACD Charts
    st.subheader("📈 Gráficos")

    # Create subplots with 3 rows now
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        subplot_titles=('Preço', 'RSI', 'MACD'),
        row_heights=[0.5, 0.25, 0.25]
    )

    # Candlestick chart
    fig.add_trace(
        go.Candlestick(
            x=data.index,
            open=data['open'],
            high=data['high'],
            low=data['low'],
            close=data['close'],
            name="Preço"
        ),
        row=1, col=1
    )

    # RSI chart
    fig.add_trace(
        go.Scatter(
            x=data.index,
            y=data['rsi'],
            mode='lines',
            name='RSI',
            line=dict(color='purple', width=2)
        ),
        row=2, col=1
    )

    # RSI threshold lines
    fig.add_shape(
        type="line", xref="x2", yref="y2",
        x0=0, x1=1, y0=rsi_max, y1=rsi_max,
        line=dict(color="red", width=2, dash="dash")
    )
    fig.add_shape(
        type="line", xref="x2", yref="y2", 
        x0=0, x1=1, y0=rsi_min, y1=rsi_min,
        line=dict(color="green", width=2, dash="dash")
    )
    fig.add_shape(
        type="line", xref="x2", yref="y2",
        x0=0, x1=1, y0=50, y1=50,
        line=dict(color="gray", width=1, dash="dot")
    )

    # Add signal markers
    buy_signals = data[data['signal'].isin(['COMPRA', 'COMPRA_FRACA'])]
    sell_signals = data[data['signal'].isin(['VENDA', 'VENDA_FRACA'])]

    if len(buy_signals) > 0:
        # Strong buy signals (larger markers)
        strong_buys = buy_signals[buy_signals['signal'] == 'COMPRA']
        weak_buys = buy_signals[buy_signals['signal'] == 'COMPRA_FRACA']

        if len(strong_buys) > 0:
            fig.add_trace(
                go.Scatter(
                    x=strong_buys.index if hasattr(strong_buys, 'index') else list(range(len(strong_buys))),
                    y=strong_buys['close'],
                    mode='markers',
                    marker=dict(symbol='triangle-up', size=20, color='green'),
                    name='Compra Forte',
                    showlegend=True
                ),
                row=1, col=1
            )

        if len(weak_buys) > 0:
            fig.add_trace(
                go.Scatter(
                    x=weak_buys.index if hasattr(weak_buys, 'index') else list(range(len(weak_buys))),
                    y=weak_buys['close'],
                    mode='markers',
                    marker=dict(symbol='triangle-up', size=12, color='lightgreen', opacity=0.7),
                    name='Compra Fraca',
                    showlegend=True
                ),
                row=1, col=1
            )

    if len(sell_signals) > 0:
        # Strong sell signals (larger markers)
        strong_sells = sell_signals[sell_signals['signal'] == 'VENDA']
        weak_sells = sell_signals[sell_signals['signal'] == 'VENDA_FRACA']

        if len(strong_sells) > 0:
            fig.add_trace(
                go.Scatter(
                    x=strong_sells.index if hasattr(strong_sells, 'index') else list(range(len(strong_sells))),
                    y=strong_sells['close'],
                    mode='markers',
                    marker=dict(symbol='triangle-down', size=20, color='red'),
                    name='Venda Forte',
                    showlegend=True
                ),
                row=1, col=1
            )

        if len(weak_sells) > 0:
            fig.add_trace(
                go.Scatter(
                    x=weak_sells.index if hasattr(weak_sells, 'index') else list(range(len(weak_sells))),
                    y=weak_sells['close'],
                    mode='markers',
                    marker=dict(symbol='triangle-down', size=12, color='lightcoral', opacity=0.7),
                    name='Venda Fraca',
                    showlegend=True
                ),
                row=1, col=1
            )

    # MACD chart
    fig.add_trace(
        go.Scatter(
            x=data.index,
            y=data['macd'],
            mode='lines',
            name='MACD',
            line=dict(color='blue', width=2)
        ),
        row=3, col=1
    )

    fig.add_trace(
        go.Scatter(
            x=data.index,
            y=data['macd_signal'],
            mode='lines',
            name='Signal',
            line=dict(color='orange', width=2)
        ),
        row=3, col=1
    )

    fig.add_trace(
        go.Bar(
            x=data.index,
            y=data['macd_histogram'],
            name='Histogram',
            marker_color=['green' if x >= 0 else 'red' for x in data['macd_histogram']]
        ),
        row=3, col=1
    )

    # Add MACD zero line
    fig.add_shape(
        type="line", xref="x3", yref="y3",
        x0=0, x1=1, y0=0, y1=0,
        line=dict(color="gray", width=1, dash="dot")
    )

    # Update layout
    fig.update_layout(
        title=f'{symbol} - {timeframe}',
        height=800,
        xaxis_rangeslider_visible=False,
        showlegend=True
    )

    fig.update_yaxes(title_text="Preço ($)", row=1, col=1)
    fig.update_yaxes(title_text="RSI", range=[0, 100], row=2, col=1)
    fig.update_yaxes(title_text="MACD", row=3, col=1)

    st.plotly_chart(fig, use_container_width=True)

    # Current Analysis
    st.subheader("🔍 Análise Atual")

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

    with analysis_col2:
        if signal == "COMPRA":
            st.success(f"""
            🟢 **SINAL DE COMPRA FORTE**  
            RSI abaixo de {rsi_min} e MACD bullish convergem para alta.  
            Considere entrada em posição de compra.
            """)
        elif signal == "VENDA":
            st.error(f"""
            🔴 **SINAL DE VENDA FORTE**  
            RSI acima de {rsi_max} e MACD bearish convergem para baixa.  
            Considere saída da posição ou entrada em venda.
            """)
        elif signal == "COMPRA_FRACA":
            st.info(f"""
            🟡 **SINAL DE COMPRA FRACA**  
            Apenas um indicador favorável à compra.  
            Aguarde confirmação ou entrada parcial.
            """)
        elif signal == "VENDA_FRACA":
            st.info(f"""
            🟠 **SINAL DE VENDA FRACA**  
            Apenas um indicador favorável à venda.  
            Aguarde confirmação ou saída parcial.
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
                    'price': 'Preço',
                    'rsi': 'RSI',
                    'macd': 'MACD',
                    'macd_signal': 'MACD Signal',
                    'signal': 'Sinal',
                    'signal_type': 'Sinal'
                }

                # Renomear apenas as colunas que existem
                display_df = display_df.rename(columns=column_map)

                # Selecionar apenas as colunas que queremos mostrar
                available_columns = []
                for col in ['Data/Hora', 'Par', 'Preço', 'RSI', 'MACD', 'MACD Signal', 'Sinal']:
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
                st.info(f"📊 Estatísticas: {stats['total_signals']} sinais total | {stats['signals_24h']} últimas 24h")
            except Exception as e:
                st.warning(f"⚠️ Erro ao carregar estatísticas: {str(e)}")

# Auto-refresh mechanism - suave sem recarregar página completa
if auto_refresh:
    # Criar placeholders para atualização suave
    if 'data_placeholder' not in st.session_state:
        st.session_state.data_placeholder = None
    if 'metrics_placeholder' not in st.session_state:
        st.session_state.metrics_placeholder = None
    
    # Verificar se precisa atualizar (a cada 30 segundos para ser mais responsivo)
    current_time_check = get_brazil_datetime_naive()
    should_update_data = (
        st.session_state.last_update is None or 
        (current_time_check - st.session_state.last_update).total_seconds() > 30
    )
    
    if should_update_data:
        # Atualizar apenas os dados, sem recarregar a página
        try:
            new_data = st.session_state.trading_bot.get_market_data()
            if new_data is not None:
                st.session_state.current_data = new_data
                st.session_state.last_update = current_time_check
                
                # Forçar atualização suave apenas dos componentes necessários
                st.rerun()
                
        except Exception as e:
            # Em caso de erro, não quebrar a página
            pass
    
    # Auto-refresh a cada 10 segundos (apenas checagem, não recarregamento)
    if st.session_state.auto_refresh:
        time.sleep(1)  # Intervalo menor para interface mais responsiva

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

        # Tab 3: Posições (simuladas)
        with futures_tab3:
            st.markdown("### 📊 Gerenciamento de Posições Simuladas")

            # Mock positions for demonstration
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

            if st.button("🔄 Simular Posições"):
                positions_df = pd.DataFrame(mock_positions)
                st.dataframe(positions_df, use_container_width=True)

                profit = 5000 * futures_leverage * 0.015
                profit_pct = futures_leverage * 1.5
                st.success(f"💰 PnL Total Simulado: +${profit:.2f} (+{profit_pct:.1f}%)")
                st.info(f"🏦 Margem Total Usada: $5,000 com {futures_mode}")
                st.warning("⚠️ Esta é apenas uma simulação para fins educacionais")
            else:
                st.info("📭 Clique para ver posições simuladas com base na configuração atual")

# Backtesting Tab - Otimizado para foco em testes
with tab2:
    st.header("🔬 Centro de Backtesting Avançado")

    # Quick test presets
    st.markdown("### ⚡ Testes Rápidos")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if st.button("🚀 Teste Agressivo", help="RSI 15-85, 7 dias", use_container_width=True):
            st.session_state.bt_rsi_min = 15
            st.session_state.bt_rsi_max = 85
            st.session_state.bt_start_date = date.today() - timedelta(days=7)

    with col2:
        if st.button("⚖️ Teste Balanceado", help="RSI 25-75, 14 dias", use_container_width=True):
            st.session_state.bt_rsi_min = 25
            st.session_state.bt_rsi_max = 75
            st.session_state.bt_start_date = date.today() - timedelta(days=14)

    with col3:
        if st.button("🛡️ Teste Conservador", help="RSI 30-70, 30 dias", use_container_width=True):
            st.session_state.bt_rsi_min = 30
            st.session_state.bt_rsi_max = 70
            st.session_state.bt_start_date = date.today() - timedelta(days=30)

    with col4:
        if st.button("🔄 Reset Padrão", help="Voltar configurações padrão", use_container_width=True):
            st.session_state.bt_rsi_min = 20
            st.session_state.bt_rsi_max = 80
            st.session_state.bt_start_date = date.today() - timedelta(days=30)

    st.markdown("---")

    # Main configuration in tabs
    config_tab1, config_tab2, config_tab3 = st.tabs(["📊 Básico", "⚙️ Avançado", "📈 Otimização"])

    with config_tab1:
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("**🎯 Configuração Principal**")

            bt_symbol = st.selectbox(
                "Par de Trading:",
                ["BTC/USDT", "ETH/USDT", "XLM/USDT", "ADA/USDT", "SOL/USDT", "DOGE/USDT", "LTC/USDT", "AVAX/USDT"],
                index=0,
                help="Par de criptomoedas para testar",
                key="bt_symbol"
            )

            bt_timeframe = st.selectbox(
                "Timeframe:",
                ["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
                index=2,
                help="Intervalo dos candles - timeframes menores = mais sinais",
                key="bt_timeframe"
            )

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
                ["Personalizado", "Última Semana", "Últimas 2 Semanas", "Último Mês", "Últimos 3 Meses"],
                help="Escolha um período comum ou customize"
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
            else:
                default_start = max_date - timedelta(days=30)

            bt_start_date = st.date_input(
                "📅 Data Inicial", 
                value=getattr(st.session_state, 'bt_start_date', default_start),
                max_value=max_date,
                help="Início do backtest",
                key="bt_start_date"
            )
            bt_end_date = st.date_input(
                "📅 Data Final", 
                value=max_date,
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
            st.markdown("**🎛️ Indicadores RSI**")

            bt_rsi_period = st.slider(
                "Período RSI", 
                5, 50, 
                getattr(st.session_state, 'bt_rsi_period', 14),
                help="Janela de cálculo do RSI (14 é padrão)",
                key="bt_rsi_period"
            )

            bt_rsi_min = st.slider(
                "RSI Compra (Sobrevenda)", 
                10, 40, 
                getattr(st.session_state, 'bt_rsi_min', 20),
                help="Nível para sinal de compra",
                key="bt_rsi_min"
            )

            bt_rsi_max = st.slider(
                "RSI Venda (Sobrecompra)", 
                60, 90, 
                getattr(st.session_state, 'bt_rsi_max', 80),
                help="Nível para sinal de venda",
                key="bt_rsi_max"
            )

        with col2:
            st.markdown("**⚡ Configurações de Performance**")

            # Opções de filtragem de sinais
            enable_volume_filter = st.checkbox(
                "Filtrar por Volume",
                value=False,
                help="Apenas trades com volume acima da média"
            )

            enable_trend_filter = st.checkbox(
                "Filtrar por Tendência",
                value=False,
                help="Usar MACD como filtro adicional"
            )

            stop_loss_pct = st.number_input(
                "Stop Loss (%)",
                min_value=0.0,
                max_value=20.0,
                value=0.0,
                step=0.5,
                help="0 = sem stop loss"
            )

            take_profit_pct = st.number_input(
                "Take Profit (%)",
                min_value=0.0,
                max_value=50.0,
                value=0.0,
                step=0.5,
                help="0 = sem take profit"
            )

    with config_tab3:
        st.markdown("**🔍 Otimização de Parâmetros**")

        # Grid search para RSI
        enable_optimization = st.checkbox(
            "🚀 Modo Otimização Automática",
            help="Testa múltiplas combinações de RSI automaticamente"
        )

        if enable_optimization:
            col1, col2 = st.columns(2)

            with col1:
                rsi_min_range = st.slider(
                    "Range RSI Mínimo",
                    10, 40, (15, 30),
                    help="Faixa para testar RSI mínimo"
                )

                rsi_max_range = st.slider(
                    "Range RSI Máximo", 
                    60, 90, (70, 85),
                    help="Faixa para testar RSI máximo"
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
        compare_timeframes = st.checkbox(
            "📊 Comparar Timeframes",
            help="Testa a mesma estratégia em diferentes timeframes"
        )

    # Validation and execution
    st.markdown("---")
    st.markdown("### 🚀 Executar Testes")

    # Validation checks
    date_valid = bt_start_date < bt_end_date
    period_days = (bt_end_date - bt_start_date).days

    # Status da configuração
    col1, col2 = st.columns(2)

    with col1:
        if not date_valid:
            st.error("❌ Data inicial deve ser anterior à data final")
        elif period_days > 90:
            st.warning("⚠️ Período longo pode demorar mais")
        elif period_days < 1:
            st.error("❌ Período muito curto. Mínimo: 1 dia")
        else:
            st.success(f"✅ Configuração válida - {period_days} dias")

    with col2:
        # Estimativa de tempo
        if date_valid and period_days > 0:
            estimated_time = max(5, min(period_days * 0.5, 60))
            st.info(f"⏱️ Tempo estimado: ~{estimated_time:.0f}s")

    # Execution buttons
    col1, col2, col3 = st.columns(3)

    with col1:
        bt_execute = st.button(
            "🚀 Executar Backtest", 
            disabled=not date_valid or period_days < 1,
            help="Rodar simulação com configurações atuais",
            use_container_width=True,
            key="bt_execute"
        )

    with col2:
        if enable_optimization and st.button(
            "⚡ Otimização Automática",
            disabled=not date_valid or period_days < 1,
            help="Testar múltiplas combinações automaticamente",
            use_container_width=True,
            key="bt_optimize"
        ):
            # Trigger optimization mode
            st.session_state.run_optimization = True
            bt_execute = True

    with col3:
        if compare_timeframes and st.button(
            "📊 Comparar Timeframes",
            disabled=not date_valid or period_days < 1,
            help="Testar em múltiplos timeframes",
            use_container_width=True,
            key="bt_compare"
        ):
            # Trigger comparison mode
            st.session_state.run_comparison = True
            bt_execute = True

    if bt_execute and date_valid:
        with st.spinner("🔄 Executando backtest... Isso pode levar alguns minutos."):
            try:
                # Convert dates to datetime
                start_dt = datetime.combine(bt_start_date, datetime.min.time())
                end_dt = datetime.combine(bt_end_date, datetime.max.time())

                # Validações adicionais
                if period_days > 365:
                    st.error("❌ Período muito longo. Máximo recomendado: 1 ano")
                    st.stop()

                # Execute backtest
                st.info(f"📊 Executando backtest para {bt_symbol} no período de {period_days} dias...")

                results = st.session_state.backtest_engine.run_backtest(
                    symbol=bt_symbol,
                    timeframe=bt_timeframe,
                    start_date=start_dt,
                    end_date=end_dt,
                    initial_balance=int(bt_initial_balance),
                    rsi_period=bt_rsi_period,
                    rsi_min=bt_rsi_min,
                    rsi_max=bt_rsi_max
                )

                if results and 'stats' in results:
                    st.session_state.backtest_results = results
                    st.success("✅ Backtest concluído com sucesso!")
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

        st.markdown("---")
        st.subheader("📊 Resultados do Backtest")

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
            if st.button("🔧 RSI Mais Restritivo", help="RSI 15-85"):
                st.session_state.bt_rsi_min = 15
                st.session_state.bt_rsi_max = 85
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
            if st.button("⚖️ RSI Balanceado", help="RSI 25-75"):
                st.session_state.bt_rsi_min = 25
                st.session_state.bt_rsi_max = 75
                st.rerun()

            if st.button("🔄 Período Maior", help="Dobrar período de teste"):
                current_days = (st.session_state.bt_end_date - st.session_state.bt_start_date).days
                new_start = st.session_state.bt_end_date - timedelta(days=min(current_days * 2, 90))
                st.session_state.bt_start_date = new_start
                st.rerun()

        # Portfolio evolution chart
        if results.get('portfolio_values'):
            st.markdown("---")
            st.subheader("📈 Evolução do Portfolio")

            portfolio_df = pd.DataFrame(results['portfolio_values'])
            portfolio_df['timestamp'] = pd.to_datetime(portfolio_df['timestamp'])

            fig_portfolio = go.Figure()
            fig_portfolio.add_trace(go.Scatter(
                x=portfolio_df['timestamp'],
                y=portfolio_df['portfolio_value'],
                mode='lines',
                name='Valor do Portfolio',
                line=dict(color='blue', width=2)
            ))

            # Add initial balance line
            fig_portfolio.add_hline(
                y=stats['initial_balance'], 
                line_dash="dash", 
                line_color="gray",
                annotation_text="Saldo Inicial"
            )

            fig_portfolio.update_layout(
                title=f"Evolução do Portfolio - {bt_symbol}",
                xaxis_title="Data",
                yaxis_title="Valor do Portfolio ($)",
                height=400
            )

            st.plotly_chart(fig_portfolio, use_container_width=True)

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
                'symbol': bt_symbol,
                'timeframe': bt_timeframe,
                'period_days': period_days,
                'rsi_min': bt_rsi_min,
                'rsi_max': bt_rsi_max,
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
                use_container_width=True,
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
            4. **Ajuste RSI** (20-80 é conservador)
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
            - RSI: 15-85
            - Período: 1 semana
            - Para: traders ativos
            """)

        with sample_col2:
            st.info("""
            **⚖️ Swing Trading**
            - Timeframe: 1h
            - RSI: 25-75
            - Período: 1 mês
            - Para: trading moderado
            """)

        with sample_col3:
            st.info("""
            **🛡️ Posição Longa**
            - Timeframe: 4h
            - RSI: 30-70
            - Período: 3 meses
            - Para: investidores
            """)

# Export Data Tab
with tab3:
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
with tab4:
    st.subheader("👑 Painel Administrativo")

    # Admin authentication
    admin_password = st.text_input("🔐 Senha de Admin", type="password", key="admin_pass")

    if admin_password == "admin123":  # Change this password
        st.success("✅ Acesso autorizado!")

        # Admin stats
        stats = st.session_state.user_manager.get_user_stats()

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("👥 Total Usuários", stats['total_users'])
        with col2:
            st.metric("🆓 Usuários Free", stats['free_users'])
        with col3:
            st.metric("💎 Usuários Premium", stats['premium_users'])
        with col4:
            st.metric("🔥 Ativos Hoje", stats['active_today'])

        # User management
        st.markdown("---")
        st.subheader("👥 Gerenciamento de Usuários")

        # List users
        users = st.session_state.user_manager.list_users(50)
        if users:
            users_df = pd.DataFrame(users)

            # Format datetime columns
            if 'joined' in users_df.columns:
                users_df['joined'] = pd.to_datetime(users_df['joined']).dt.strftime('%d/%m/%Y')
            if 'last_analysis' in users_df.columns:
                users_df['last_analysis'] = users_df['last_analysis'].fillna('Nunca')
                users_df.loc[users_df['last_analysis'] != 'Nunca', 'last_analysis'] = pd.to_datetime(users_df.loc[users_df['last_analysis'] != 'Nunca', 'last_analysis']).dt.strftime('%d/%m/%Y %H:%M')

            st.dataframe(users_df, width='stretch', hide_index=True)

        # User actions
        st.markdown("---")
        st.subheader("🔧 Ações de Usuário")

        col1, col2 = st.columns(2)

        with col1:
            user_id_upgrade = st.number_input("ID do Usuário para Upgrade", min_value=1, key="upgrade_user")
            if st.button("💎 Promover para Premium"):
                if st.session_state.user_manager.upgrade_to_premium(int(user_id_upgrade)):
                    st.success(f"✅ Usuário {user_id_upgrade} promovido para Premium!")
                else:
                    st.error("❌ Usuário não encontrado")

        with col2:
            new_admin_id = st.number_input("ID do Novo Admin", min_value=1, key="new_admin")
            if st.button("👑 Adicionar Admin"):
                st.session_state.user_manager.add_admin(int(new_admin_id))
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
                if st.session_state.telegram_trading_bot.configure(bot_token_admin):
                    st.success("✅ Bot Telegram configurado com sucesso!")
                    st.info("💡 O bot agora está pronto para receber comandos dos usuários!")
                else:
                    st.error("❌ Erro na configuração do bot")

        with col2:
            if st.button("📤 Testar Bot") and st.session_state.telegram_trading_bot.is_configured():
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    success, message = loop.run_until_complete(
                        st.session_state.telegram_trading_bot.test_connection()
                    )
                    if success:
                        st.success(f"✅ {message}")
                    else:
                        st.error(f"❌ {message}")
                except Exception as e:
                    st.error(f"❌ Erro: {str(e)}")

        # Bot status
        if st.session_state.telegram_trading_bot.is_configured():
            st.success("🟢 Bot Telegram está ativo e pronto para uso!")
            st.info("💬 Os usuários podem usar comandos como /analise BTC/USDT")
        else:
            st.warning("🟡 Bot Telegram não configurado")

        # Broadcast message
        st.markdown("---")
        st.subheader("📢 Enviar Comunicado")

        broadcast_msg = st.text_area("Mensagem para todos os usuários", key="broadcast_msg")
        if st.button("📤 Enviar para Todos") and broadcast_msg:
            st.info("Funcionalidade de broadcast disponível via comando /broadcast no Telegram")

    elif admin_password:
        st.error("❌ Senha incorreta")
    else:
        st.info("🔐 Digite a senha de administrador para acessar o painel")

# Footer
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: gray;'>
Trading Signals Dashboard - Desenvolvido com Streamlit | ⚠️ Este sistema é apenas para fins educacionais
</div>
""", unsafe_allow_html=True)