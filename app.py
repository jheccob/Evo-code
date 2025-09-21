import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import time
import json
import os
from datetime import datetime, timedelta
import asyncio
import threading

# Importar funções de fuso horário brasileiro
from utils.timezone_utils import now_brazil, format_brazil_time, get_brazil_datetime_naive, BRAZIL_TZ

# Importar banco de dados
from database.database import db
from trading_bot import TradingBot
from indicators import TechnicalIndicators

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

# Initialize session state
if 'trading_bot' not in st.session_state:
    st.session_state.trading_bot = TradingBot()

if 'telegram_bot' not in st.session_state:
    st.session_state.telegram_bot = SecureTelegramService()
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

# Sidebar configuration
st.sidebar.title("🔧 Configurações")

# Multi-symbol monitoring
st.sidebar.subheader("📊 Pares de Moedas")
enable_multi_symbol = st.sidebar.checkbox("🔀 Monitoramento Múltiplo", value=False)

if enable_multi_symbol:
    # Multi-symbol selection - Updated for Coinbase Pro
    available_pairs = ["XLM-USD", "BTC-USD", "ETH-USD", "ADA-USD", "DOT-USD", "MATIC-USD", 
                       "LINK-USD", "UNI-USD", "SOL-USD", "AVAX-USD"]
    selected_symbols = st.sidebar.multiselect(
        "Selecionar pares para monitorar:",
        available_pairs,
        default=["XLM-USD", "BTC-USD", "ETH-USD"]
    )
    
    if not selected_symbols:
        st.sidebar.warning("⚠️ Selecione pelo menos um par")
        selected_symbols = ["XLM-USD"]
    
    # For multi-symbol mode, use the first selected as primary
    symbol = selected_symbols[0] if selected_symbols else "XLM-USD"
    
else:
    # Single symbol selection - Updated for Coinbase Pro
    symbol = st.sidebar.selectbox(
        "Par de Trading",
        ["XLM-USD", "BTC-USD", "ETH-USD", "ADA-USD", "DOT-USD", "MATIC-USD"],
        index=0
    )
    selected_symbols = [symbol]

# Timeframe selection - Coinbase supported timeframes
timeframe = st.sidebar.selectbox(
    "Timeframe",
    ["1m", "5m", "15m", "1h", "6h", "1d"],
    index=1
)

# RSI Parameters
st.sidebar.subheader("📊 Parâmetros RSI")
rsi_period = st.sidebar.slider("Período RSI", 5, 50, 9)
rsi_min = st.sidebar.slider("RSI Mínimo (Compra)", 10, 40, 20)
rsi_max = st.sidebar.slider("RSI Máximo (Venda)", 60, 90, 80)

# Auto refresh toggle
auto_refresh = st.sidebar.checkbox("🔄 Atualização Automática", value=True)
st.session_state.auto_refresh = auto_refresh

# Manual refresh button
if st.sidebar.button("🔄 Atualizar Agora"):
    st.session_state.last_update = None
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

# Update bot configuration
st.session_state.trading_bot.update_config(
    symbol=symbol,
    timeframe=timeframe,
    rsi_period=rsi_period,
    rsi_min=rsi_min,
    rsi_max=rsi_max
)

# Main dashboard
st.title("📈 Trading Signals Dashboard")

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

# Import futures trading
try:
    from futures_trading import FuturesTrading
    FUTURES_AVAILABLE = True
except ImportError:
    FUTURES_AVAILABLE = False

# Initialize futures trading if available
if 'futures_trading' not in st.session_state and FUTURES_AVAILABLE:
    st.session_state.futures_trading = FuturesTrading()

# Create tabs for different sections
tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 Análise em Tempo Real", "🚀 Mercado Futuro", "🔬 Backtesting", "⚙️ Exportar Dados", "👑 Admin Panel"])

with tab1:
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
                    'Sinal': signal,
                    'Variação': f"{((last_candle['close'] - last_candle['open']) / last_candle['open'] * 100):.2f}%"
                })
                
        except Exception as e:
            overview_data.append({
                'Par': sym,
                'Preço': 'Erro',
                'RSI': 'N/A',
                'MACD': 'N/A', 
                'Sinal': 'ERRO',
                'Variação': 'N/A'
            })
    
    # Trim signals history to last 50 across all symbols
    if len(st.session_state.signals_history) > 50:
        st.session_state.signals_history = st.session_state.signals_history[-50:]
    
    if overview_data:
        overview_df = pd.DataFrame(overview_data)
        
        # Style the dataframe
        def style_signals(val):
            if val == 'COMPRA':
                return 'background-color: #90EE90'
            elif val == 'VENDA':
                return 'background-color: #FFB6C1'
            elif val == 'COMPRA_FRACA':
                return 'background-color: #FFFF99'
            elif val == 'VENDA_FRACA':
                return 'background-color: #FFD4A3'
            return ''
        
        styled_df = overview_df.style.map(style_signals, subset=['Sinal'])
        st.dataframe(styled_df, width='stretch', hide_index=True)
    
    st.markdown("---")
    
    st.subheader(f"📈 Análise Detalhada - {symbol}")

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

# Status indicators for main symbol
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

    # Display current metrics
    with col1:
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
        if st.session_state.telegram_bot.is_configured():
            st.metric(
                label="📱 Telegram",
                value="🟢 Ativo",
                delta="Notificações ON"
            )
        else:
            st.metric(
                label="🕒 Última Atualização",
                value=format_brazil_time(st.session_state.last_update, "%H:%M:%S") if st.session_state.last_update else "---",
                delta=None
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
        **RSI:** {last_candle['rsi']:.2f}  
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
                st.warning("Nenhum dado válido encontrado após limpeza")
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

    else:
        if show_source == "Sessão Atual":
            st.info("Nenhum sinal gerado ainda na sessão atual. Os sinais aparecerão aqui quando as condições forem atendidas.")
        else:
            st.info("📋 Nenhum sinal encontrado no banco de dados.")

        # Auto-refresh mechanism - throttled for performance  
        if auto_refresh:
            # Only refresh every 30 seconds to reduce API calls
            if st.session_state.last_update is None or (get_brazil_datetime_naive() - st.session_state.last_update).total_seconds() > 30:
                time.sleep(1)
                st.rerun()
            else:
                time.sleep(1)
                # Just rerun UI without data refresh
                st.rerun()

# Futures Trading Tab
with tab2:
    st.subheader("🚀 Trading de Mercado Futuro")
    st.markdown("Trade com alavancagem, posições long/short e gerenciamento avançado de risco")
    
    if not FUTURES_AVAILABLE:
        st.error("❌ Módulo de futuros não disponível. Verifique a instalação.")
        st.info("💡 O módulo futures_trading.py deve estar no diretório raiz")
    else:
        # Futures configuration
        st.markdown("### ⚙️ Configurações de Futuros")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            futures_leverage = st.selectbox(
                "Alavancagem",
                [1, 2, 3, 5, 10, 20, 25, 50],
                index=3,  # 5x default
                help="Multiplicador de posição. Maior alavancagem = maior risco"
            )
            
            position_size = st.slider(
                "Tamanho da Posição (%)",
                min_value=1,
                max_value=50,
                value=10,
                help="Porcentagem do saldo para cada trade"
            )
        
        with col2:
            stop_loss_pct = st.slider(
                "Stop Loss (%)",
                min_value=0.5,
                max_value=10.0,
                value=2.0,
                step=0.1,
                help="Porcentagem de perda máxima por trade"
            )
            
            take_profit_pct = st.slider(
                "Take Profit (%)",
                min_value=1.0,
                max_value=20.0,
                value=4.0,
                step=0.1,
                help="Porcentagem de lucro alvo por trade"
            )
        
        with col3:
            max_positions = st.number_input(
                "Máx. Posições Simultâneas",
                min_value=1,
                max_value=10,
                value=3,
                help="Número máximo de posições abertas ao mesmo tempo"
            )
            
            dry_run = st.checkbox(
                "Modo Simulação",
                value=True,
                help="Ativado: apenas simula. Desativado: executa trades reais"
            )
        
        # Update futures bot configuration
        if st.session_state.futures_trading:
            st.session_state.futures_trading.leverage = futures_leverage
            st.session_state.futures_trading.position_size_pct = position_size / 100
            st.session_state.futures_trading.stop_loss_pct = stop_loss_pct / 100
            st.session_state.futures_trading.take_profit_pct = take_profit_pct / 100
            st.session_state.futures_trading.max_positions = max_positions
        
        st.markdown("---")
        
        # Account Information
        st.markdown("### 💰 Informações da Conta")
        
        if dry_run:
            # Simulated account for demo
            st.info("📊 **CONTA SIMULADA**")
            account_info = {
                'total_balance': 10000.00,
                'available_balance': 8500.00,
                'used_balance': 1500.00,
                'unrealized_pnl': 125.50,
                'margin_ratio': 0.15
            }
        else:
            account_info = st.session_state.futures_trading.get_account_balance() if st.session_state.futures_trading else None
        
        if account_info:
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric(
                    "💰 Saldo Total",
                    f"${account_info['total_balance']:,.2f}",
                    delta=f"PnL: ${account_info['unrealized_pnl']:+,.2f}"
                )
            
            with col2:
                st.metric(
                    "✅ Disponível",
                    f"${account_info['available_balance']:,.2f}"
                )
            
            with col3:
                st.metric(
                    "📊 Em Uso",
                    f"${account_info['used_balance']:,.2f}"
                )
            
            with col4:
                margin_color = "normal" if account_info['margin_ratio'] < 0.8 else "inverse"
                st.metric(
                    "⚠️ Margem",
                    f"{account_info['margin_ratio']*100:.1f}%"
                )
        
        st.markdown("---")
        
        # Signal Generation and Trading
        st.markdown("### 🎯 Sinais para Futures")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            if st.session_state.current_data is not None and st.session_state.futures_trading:
                # Generate futures signal
                futures_signal = st.session_state.futures_trading.generate_futures_signal(
                    st.session_state.current_data,
                    account_info['available_balance'] if account_info else 10000
                )
                
                # Display signal information
                signal = futures_signal['signal']
                confidence = futures_signal['confidence']
                
                if signal != "NEUTRO":
                    signal_color = "success" if signal in ['COMPRA', 'COMPRA_FRACA'] else "error"
                    
                    if signal_color == "success":
                        st.success(f"""
                        🟢 **SINAL DE {signal.replace('_', ' ')}** (Confiança: {confidence:.1f}%)
                        
                        **Estratégia LONG:**
                        - Entrada: ${futures_signal['entry_price']:.6f}
                        - Stop Loss: ${futures_signal['stop_loss']:.6f} (-{stop_loss_pct:.1f}%)
                        - Take Profit: ${futures_signal['take_profit']:.6f} (+{take_profit_pct:.1f}%)
                        - Quantidade: {futures_signal['quantity']:.6f}
                        - Alavancagem: {futures_leverage}x
                        """)
                    else:
                        st.error(f"""
                        🔴 **SINAL DE {signal.replace('_', ' ')}** (Confiança: {confidence:.1f}%)
                        
                        **Estratégia SHORT:**
                        - Entrada: ${futures_signal['entry_price']:.6f}
                        - Stop Loss: ${futures_signal['stop_loss']:.6f} (+{stop_loss_pct:.1f}%)
                        - Take Profit: ${futures_signal['take_profit']:.6f} (-{take_profit_pct:.1f}%)
                        - Quantidade: {futures_signal['quantity']:.6f}
                        - Alavancagem: {futures_leverage}x
                        """)
                        
                    # Calculate potential profit/loss
                    potential_loss = account_info['available_balance'] * (position_size/100) if account_info else 1000
                    potential_profit = potential_loss * 2  # 2:1 risk/reward ratio
                    
                    st.info(f"""
                    📊 **Análise de Risco:**
                    - Risco por Trade: ${potential_loss:.2f}
                    - Potencial Lucro: ${potential_profit:.2f}
                    - Relação R:R: 1:2
                    """)
                    
                else:
                    st.warning("⚪ **SINAL NEUTRO** - Aguardar melhor oportunidade")
            
            else:
                st.info("Aguardando dados de mercado para gerar sinal...")
        
        with col2:
            st.markdown("#### 🎮 Ações")
            
            if st.button("🎯 Executar Trade", disabled=(not st.session_state.current_data or signal == "NEUTRO")):
                if st.session_state.futures_trading and st.session_state.current_data:
                    with st.spinner("Executando trade..."):
                        result = st.session_state.futures_trading.execute_futures_trade(
                            futures_signal, 
                            dry_run=dry_run
                        )
                    
                    if result["success"]:
                        st.success("✅ Trade executado com sucesso!")
                        st.json(result["details"])
                    else:
                        st.error(f"❌ {result['message']}")
            
            if st.button("📊 Atualizar Sinal"):
                st.rerun()
            
            # Quick actions
            st.markdown("#### ⚡ Ações Rápidas")
            if st.button("🛑 Fechar Todas as Posições"):
                st.warning("Funcionalidade disponível apenas com API configurada")
        
        st.markdown("---")
        
        # Open Positions
        st.markdown("### 📈 Posições Abertas")
        
        if dry_run:
            # Simulated positions for demo
            demo_positions = [
                {
                    'symbol': 'BTCUSDT',
                    'side': 'long',
                    'size': 0.1,
                    'entry_price': 43250.00,
                    'mark_price': 43580.50,
                    'unrealized_pnl': 33.05,
                    'margin': 865.00,
                    'leverage': 5
                }
            ]
            
            if demo_positions:
                positions_df = pd.DataFrame(demo_positions)
                positions_df.columns = ['Símbolo', 'Lado', 'Tamanho', 'Preço Entrada', 'Preço Atual', 'PnL', 'Margem', 'Alavancagem']
                st.dataframe(positions_df, use_container_width=True)
            else:
                st.info("📭 Nenhuma posição aberta")
        else:
            open_positions = st.session_state.futures_trading.get_open_positions() if st.session_state.futures_trading else []
            
            if open_positions:
                st.dataframe(pd.DataFrame(open_positions), use_container_width=True)
            else:
                st.info("📭 Nenhuma posição aberta")
        
        # Trading Tips
        st.markdown("---")
        st.markdown("### 💡 Dicas para Mercado Futuro")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.info("""
            **✅ Boas Práticas:**
            - Sempre use stop loss
            - Não arrisque mais que 2-5% por trade
            - Gerencie suas posições ativamente
            - Monitore funding rates
            - Use alavancagem com moderação
            """)
        
        with col2:
            st.warning("""
            **⚠️ Cuidados:**
            - Alavancagem alta = risco alto
            - Funding rates podem impactar lucros
            - Liquidação pode ocorrer rapidamente
            - Mercado futuro é 24/7
            - Volatilidade é maior que spot
            """)

# Backtesting Tab  
with tab3:
    st.subheader("🔬 Sistema de Backtesting")
    st.markdown("Teste suas estratégias com dados históricos para validar sua eficácia")
    
    # Configurações do Backtest
    st.markdown("### ⚙️ Configurações do Backtest")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**📈 Parâmetros do Mercado**")
        
        # Convert symbol format for backtest
        bt_symbol = st.selectbox(
            "Par para Backtest:",
            ["XLM-USD", "BTC-USD", "ETH-USD", "ADA-USD", "DOT-USD", "MATIC-USD"],
            help="Selecione o par de criptomoedas para testar",
            key="bt_symbol"
        )
        
        bt_timeframe = st.selectbox(
            "Timeframe:",
            ["5m", "15m", "30m", "1h", "4h"],
            index=1,
            help="Intervalo de tempo dos candles",
            key="bt_timeframe"
        )
        
        # Date selection with better defaults
        from datetime import date
        max_date = date.today()
        default_start = max_date - timedelta(days=30)
        
        bt_start_date = st.date_input(
            "📅 Data Inicial", 
            value=default_start,
            max_value=max_date,
            help="Data de início do período de teste",
            key="bt_start_date"
        )
        bt_end_date = st.date_input(
            "📅 Data Final", 
            value=max_date,
            max_value=max_date,
            help="Data de fim do período de teste",
            key="bt_end_date"
        )
    
    with col2:
        st.markdown("**💰 Parâmetros de Trading**")
        
        bt_initial_balance = st.number_input(
            "Saldo Inicial ($)", 
            min_value=100.0, 
            max_value=100000.0, 
            value=10000.0,
            step=1000.0,
            help="Capital inicial para simulação",
            key="bt_initial_balance"
        )
        
        bt_rsi_period = st.slider(
            "RSI Período", 
            5, 50, 14,
            help="Período para cálculo do RSI",
            key="bt_rsi_period"
        )
        
        bt_rsi_min = st.slider(
            "RSI Mínimo (Sinal de Compra)", 
            10, 40, 20,
            help="Nível de sobrevenda do RSI",
            key="bt_rsi_min"
        )
        
        bt_rsi_max = st.slider(
            "RSI Máximo (Sinal de Venda)", 
            60, 90, 80,
            help="Nível de sobrecompra do RSI",
            key="bt_rsi_max"
        )
    
    # Validation and execution
    st.markdown("---")
    
    # Validation checks
    date_valid = bt_start_date < bt_end_date
    period_days = (bt_end_date - bt_start_date).days
    
    if not date_valid:
        st.error("❌ Data inicial deve ser anterior à data final")
    elif period_days > 90:
        st.warning("⚠️ Período muito longo pode causar problemas de API. Recomendado: máximo 90 dias")
    elif period_days < 1:
        st.error("❌ Período muito curto. Mínimo: 1 dia")
    
    # Execution button
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        bt_execute = st.button(
            "🚀 Executar Backtest", 
            disabled=not date_valid or period_days < 1,
            help="Iniciar simulação com os parâmetros configurados",
            use_container_width=True,
            key="bt_execute"
        )
    
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
        
        # Performance interpretation
        st.markdown("**🎯 Interpretação dos Resultados**")
        if stats['total_return_pct'] > 20:
            st.success("🚀 **Excelente Performance!** A estratégia demonstrou retornos muito bons.")
        elif stats['total_return_pct'] > 5:
            st.success("✅ **Boa Performance!** A estratégia teve resultados positivos.")
        elif stats['total_return_pct'] > 0:
            st.warning("⚠️ **Performance Moderada.** A estratégia teve ganhos pequenos.")
        else:
            st.error("❌ **Performance Negativa.** A estratégia resultou em perdas.")
            
        # Additional insights
        if stats['win_rate'] < 40:
            st.warning("⚠️ Taxa de acerto baixa. Considere ajustar os parâmetros.")
        if stats['max_drawdown'] > 20:
            st.warning("⚠️ Drawdown alto. A estratégia pode ser muito arriscada.")
        
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
        
        # Clear results button
        st.markdown("---")
        if st.button("🗑️ Limpar Resultados", key="clear_backtest_results"):
            st.session_state.backtest_results = None
            st.rerun()
    
    else:
        # Help section when no results
        st.markdown("---")
        st.info("ℹ️ **Como usar o Backtesting:**\n\n"
                "1. **Selecione o par** e timeframe desejado\n"
                "2. **Configure o período** de teste (recomendado: 7-30 dias)\n" 
                "3. **Ajuste os parâmetros** de RSI conforme sua estratégia\n"
                "4. **Execute o backtest** e analise os resultados\n\n"
                "💡 **Dica:** Comece com períodos menores para testes mais rápidos")

# Export Data Tab
with tab4:
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
with tab5:
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
