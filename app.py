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
from trading_bot import TradingBot
from indicators import TechnicalIndicators
from telegram_bot import TelegramNotifier

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
    st.session_state.telegram_bot = TelegramNotifier()

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

# Sidebar configuration
st.sidebar.title("🔧 Configurações")

# Multi-symbol monitoring
st.sidebar.subheader("📊 Pares de Moedas")
enable_multi_symbol = st.sidebar.checkbox("🔀 Monitoramento Múltiplo", value=False)

if enable_multi_symbol:
    # Multi-symbol selection
    available_pairs = ["XLM/USDT", "BTC/USDT", "ETH/USDT", "ADA/USDT", "DOT/USDT", "MATIC/USDT", 
                       "LINK/USDT", "UNI/USDT", "SOL/USDT", "AVAX/USDT"]
    selected_symbols = st.sidebar.multiselect(
        "Selecionar pares para monitorar:",
        available_pairs,
        default=["XLM/USDT", "BTC/USDT", "ETH/USDT"]
    )
    
    if not selected_symbols:
        st.sidebar.warning("⚠️ Selecione pelo menos um par")
        selected_symbols = ["XLM/USDT"]
    
    # For multi-symbol mode, use the first selected as primary
    symbol = selected_symbols[0] if selected_symbols else "XLM/USDT"
    
else:
    # Single symbol selection
    symbol = st.sidebar.selectbox(
        "Par de Trading",
        ["XLM/USDT", "BTC/USDT", "ETH/USDT", "ADA/USDT", "DOT/USDT", "MATIC/USDT"],
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
st.sidebar.subheader("📱 Telegram Alerts")

telegram_enabled = st.sidebar.checkbox(
    "🔔 Ativar notificações Telegram", 
    value=st.session_state.telegram_notifications
)

if telegram_enabled:
    telegram_token = st.sidebar.text_input(
        "🤖 Bot Token", 
        type="password",
        placeholder="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        help="Obtenha um token criando um bot via @BotFather"
    )
    
    telegram_chat_id = st.sidebar.text_input(
        "💬 Chat ID",
        placeholder="-1001234567890 ou 123456789",
        help="ID do chat onde receber alertas"
    )
    
    if telegram_token and telegram_chat_id:
        if st.sidebar.button("✅ Configurar Telegram"):
            success = st.session_state.telegram_bot.configure(telegram_token, telegram_chat_id)
            if success:
                st.session_state.telegram_notifications = True
                # Test connection
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    success, message = loop.run_until_complete(
                        st.session_state.telegram_bot.test_connection()
                    )
                    if success:
                        st.sidebar.success("✅ Telegram configurado com sucesso!")
                    else:
                        st.sidebar.error(f"❌ Erro: {message}")
                except Exception as e:
                    st.sidebar.error(f"❌ Erro ao testar conexão: {str(e)}")
            else:
                st.sidebar.error("❌ Erro na configuração do Telegram")
    
    if st.session_state.telegram_bot.is_configured():
        st.sidebar.success("🟢 Telegram ativo")
        if st.sidebar.button("📤 Teste de Mensagem"):
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                success, message = loop.run_until_complete(
                    st.session_state.telegram_bot.send_custom_message("📊 Teste do bot de trading!")
                )
                if success:
                    st.sidebar.success("✅ Mensagem enviada!")
                else:
                    st.sidebar.error(f"❌ {message}")
            except Exception as e:
                st.sidebar.error(f"❌ Erro: {str(e)}")
else:
    st.session_state.telegram_notifications = False

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
st.markdown("---")

# Multi-Symbol Overview (if enabled) - with caching and performance optimization
if enable_multi_symbol and len(selected_symbols) > 1:
    st.subheader("🔀 Overview - Múltiplos Pares")
    
    # Initialize multi-symbol last signals tracking
    if 'multi_symbol_signals' not in st.session_state:
        st.session_state.multi_symbol_signals = {}
    
    # Create overview table for all selected symbols
    overview_data = []
    current_time = datetime.now()
    
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
        
        styled_df = overview_df.style.applymap(style_signals, subset=['Sinal'])
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
    
    st.markdown("---")
    
    st.subheader(f"📈 Análise Detalhada - {symbol}")

# Status indicators for main symbol
col1, col2, col3, col4, col5 = st.columns(5)

# Check if we need to update data
should_update = (
    st.session_state.last_update is None or 
    (datetime.now() - st.session_state.last_update).total_seconds() > 60
)

if should_update:
    try:
        with st.spinner('Carregando dados...'):
            data = st.session_state.trading_bot.get_market_data()
            if data is not None:
                st.session_state.current_data = data
                st.session_state.last_update = datetime.now()
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
        st.session_state.signals_history[-1]['timestamp'] < datetime.now() - timedelta(minutes=5)
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
        
        st.session_state.signals_history.append({
            'timestamp': datetime.now(),
            'symbol': symbol,
            'price': last_candle['close'],
            'rsi': last_candle['rsi'],
            'macd': last_candle['macd'],
            'macd_signal': last_candle['macd_signal'],
            'signal': signal
        })
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
        st.metric(
            label="🕒 Última Atualização",
            value=st.session_state.last_update.strftime("%H:%M:%S") if st.session_state.last_update else "---",
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

if st.session_state.signals_history:
    # Convert to DataFrame
    signals_df = pd.DataFrame(st.session_state.signals_history)
    signals_df['timestamp'] = pd.to_datetime(signals_df['timestamp'])
    signals_df = signals_df.sort_values('timestamp', ascending=False)
    
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
        
    # Rename columns
    if 'macd' in display_df.columns and 'macd_signal' in display_df.columns:
        display_df.columns = ['Data/Hora', 'Par', 'Preço', 'RSI', 'MACD', 'MACD Signal', 'Sinal']
    else:
        display_df.columns = ['Data/Hora', 'Par', 'Preço', 'RSI', 'Sinal']
    
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True
    )
    
    # Clear history button
    if st.button("🗑️ Limpar Histórico"):
        st.session_state.signals_history = []
        st.rerun()
else:
    st.info("Nenhum sinal gerado ainda. Os sinais aparecerão aqui quando as condições forem atendidas.")

# Auto-refresh mechanism - throttled for performance  
if auto_refresh:
    # Only refresh every 30 seconds to reduce API calls
    if st.session_state.last_update is None or (datetime.now() - st.session_state.last_update).total_seconds() > 30:
        time.sleep(1)
        st.rerun()
    else:
        time.sleep(1)
        # Just rerun UI without data refresh
        st.rerun()

# Footer
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: gray;'>
Trading Signals Dashboard - Desenvolvido com Streamlit | ⚠️ Este sistema é apenas para fins educacionais
</div>
""", unsafe_allow_html=True)
