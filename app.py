import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import time
import json
from datetime import datetime, timedelta
import asyncio
import threading

# Importar funções de fuso horário brasileiro
from utils.timezone_utils import now_brazil, format_brazil_time, get_brazil_datetime_naive

# Importar banco de dados
from database.database import db
from trading_bot import TradingBot
from indicators import TechnicalIndicators

# Importar serviço seguro do Telegram
try:
    from services.telegram_service import SecureTelegramService, TELEGRAM_AVAILABLE
except ImportError:
    TELEGRAM_AVAILABLE = False
    
    # Classe dummy para compatibilidade
    class SecureTelegramService:
        def __init__(self):
            self.enabled = False
        def configure(self, *args): return False, "Telegram não disponível"
        def is_configured(self): return False
        async def test_connection(self): return False, "Not available"
        async def send_signal_alert(self, *args): return False, "Not available"
        async def send_custom_message(self, *args): return False, "Not available"
        def get_config_status(self): return {'available': False, 'configured': False}

from backtest import BacktestEngine

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
        default=["XLM/USDT", "BTC/USDT", "ETH/USDT"]
    )
    
    if not selected_symbols:
        st.sidebar.warning("⚠️ Selecione pelo menos um par")
        selected_symbols = ["XLM/USDT"]
    
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

# Timeframe selection
timeframe = st.sidebar.selectbox(
    "Timeframe",
    ["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
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
    
    if config_status['configured']:
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
from user_manager import UserManager
# TelegramTradingBot disabled for now due to import issues

# Initialize user manager
if 'user_manager' not in st.session_state:
    st.session_state.user_manager = UserManager()

# Telegram trading bot disabled for now due to import issues
# if 'telegram_trading_bot' not in st.session_state:
#     st.session_state.telegram_trading_bot = TelegramTradingBot()

# Create tabs for different sections
tab1, tab2, tab3, tab4 = st.tabs(["📊 Análise em Tempo Real", "🔬 Backtesting", "⚙️ Exportar Dados", "👑 Admin Panel"])

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
        try:
            # Check if we have cached data for this symbol that's less than 60 seconds old
            cache_key = f"{sym}_{timeframe}"
            should_refresh = True
            
            if cache_key in st.session_state.multi_symbol_data:
                cached_data = st.session_state.multi_symbol_data[cache_key]
                if cached_data['last_update'] and (current_time - cached_data['last_update']).total_seconds() < 60:
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
if not st.session_state.telegram_bot.is_configured():
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

# Store multi-symbol data
if 'multi_symbol_data' not in st.session_state:
    st.session_state.multi_symbol_data = {}

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
        st.session_state.signals_history[-1]['timestamp'] < get_brazil_datetime_naive() - timedelta(minutes=5)
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
            'signal_strength': abs(last_candle['rsi'] - 50) / 50  # Força do sinal baseada no RSI
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
                    x=strong_buys.index,
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
                    x=weak_buys.index,
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
                    x=strong_sells.index,
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
                    x=weak_sells.index,
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
    display_df = signals_df.copy()
    display_df['timestamp'] = display_df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
    display_df['price'] = display_df['price'].apply(lambda x: f"${x:.6f}")
    display_df['rsi'] = display_df['rsi'].apply(lambda x: f"{x:.2f}")
    
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
    
    st.dataframe(
        display_df,
        width='stretch',
        hide_index=True
    )
    
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

# Backtesting Tab
with tab2:
    st.subheader("🔬 Sistema de Backtesting")
    st.markdown("Teste suas estratégias com dados históricos")
    
    col1, col2 = st.columns(2)
    
    with col1:
        bt_symbol = st.selectbox(
            "Par para Backtest:",
            ["XLM/USDT", "BTC/USDT", "ETH/USDT", "ADA/USDT", "DOT/USDT", "MATIC/USDT"]
        )
        
        bt_timeframe = st.selectbox(
            "Timeframe:",
            ["5m", "15m", "30m", "1h", "4h"],
            index=0
        )
        
        # Date selection
        from datetime import date
        end_date = st.date_input("Data Final", value=date.today())
        start_date = st.date_input("Data Inicial", value=date.today() - timedelta(days=30))
    
    with col2:
        bt_initial_balance = st.number_input("Saldo Inicial ($)", min_value=100, max_value=100000, value=10000)
        bt_rsi_period = st.slider("RSI Período", 5, 50, rsi_period)
        bt_rsi_min = st.slider("RSI Mín (Compra)", 10, 40, rsi_min)
        bt_rsi_max = st.slider("RSI Máx (Venda)", 60, 90, rsi_max)
    
    if st.button("🚀 Executar Backtest"):
        if start_date >= end_date:
            st.error("❌ Data inicial deve ser anterior à data final")
        else:
            with st.spinner("Executando backtest..."):
                try:
                    # Convert dates to datetime
                    start_dt = datetime.combine(start_date, datetime.min.time())
                    end_dt = datetime.combine(end_date, datetime.max.time())
                    
                    results = st.session_state.backtest_engine.run_backtest(
                        symbol=bt_symbol,
                        timeframe=bt_timeframe,
                        start_date=start_dt,
                        end_date=end_dt,
                        initial_balance=bt_initial_balance,
                        rsi_period=bt_rsi_period,
                        rsi_min=bt_rsi_min,
                        rsi_max=bt_rsi_max
                    )
                    st.session_state.backtest_results = results
                    st.success("✅ Backtest concluído!")
                    
                except Exception as e:
                    st.error(f"❌ Erro no backtest: {str(e)}")
    
    # Display results if available
    if st.session_state.backtest_results:
        results = st.session_state.backtest_results
        stats = results['stats']
        
        st.markdown("---")
        st.subheader("📊 Resultados do Backtest")
        
        # Display key metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Retorno Total", f"{stats['total_return_pct']:.2f}%")
        with col2:
            st.metric("Total de Trades", stats['total_trades'])
        with col3:
            st.metric("Taxa de Acerto", f"{stats['win_rate']:.1f}%")
        with col4:
            st.metric("Max Drawdown", f"{stats['max_drawdown']:.2f}%")
        
        # Detailed stats
        st.subheader("📈 Estatísticas Detalhadas")
        col1, col2 = st.columns(2)
        
        with col1:
            st.info(f"""
            **Saldo Inicial:** ${stats['initial_balance']:,.2f}  
            **Saldo Final:** ${stats['final_balance']:,.2f}  
            **Retorno Total:** {stats['total_return_pct']:.2f}%  
            **Sharpe Ratio:** {stats['sharpe_ratio']:.2f}  
            """)
        
        with col2:
            st.info(f"""
            **Trades Vencedores:** {stats['winning_trades']}  
            **Trades Perdedores:** {stats['losing_trades']}  
            **Lucro Médio:** {stats['avg_profit']:.2f}%  
            **Perda Média:** {stats['avg_loss']:.2f}%  
            """)
        
        # Trade history
        if results['trades']:
            st.subheader("📋 Histórico de Trades")
            trade_df = st.session_state.backtest_engine.get_trade_summary_df()
            if not trade_df.empty:
                trade_df_display = trade_df.copy()
                trade_df_display['timestamp'] = trade_df_display['timestamp'].dt.strftime('%Y-%m-%d %H:%M')
                trade_df_display['entry_price'] = trade_df_display['entry_price'].apply(lambda x: f"${x:.6f}")
                trade_df_display['price'] = trade_df_display['price'].apply(lambda x: f"${x:.6f}")
                trade_df_display['profit_loss_pct'] = trade_df_display['profit_loss_pct'].apply(lambda x: f"{x:.2f}%")
                trade_df_display['profit_loss'] = trade_df_display['profit_loss'].apply(lambda x: f"${x:.2f}")
                
                trade_df_display.columns = ['Data/Hora', 'Preço Entrada', 'Preço Saída', 'Retorno %', 'Lucro/Perda $', 'Sinal']
                
                st.dataframe(trade_df_display, width='stretch', hide_index=True)

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
