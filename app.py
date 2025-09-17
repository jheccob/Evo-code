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

if 'signals_history' not in st.session_state:
    st.session_state.signals_history = []

if 'last_update' not in st.session_state:
    st.session_state.last_update = None

if 'auto_refresh' not in st.session_state:
    st.session_state.auto_refresh = True

if 'current_data' not in st.session_state:
    st.session_state.current_data = None

# Sidebar configuration
st.sidebar.title("🔧 Configurações")

# Trading pair selection
symbol = st.sidebar.selectbox(
    "Par de Trading",
    ["XLM/USDT", "BTC/USDT", "ETH/USDT", "ADA/USDT", "DOT/USDT", "MATIC/USDT"],
    index=0
)

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

# Status indicators
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

if st.session_state.current_data is not None:
    data = st.session_state.current_data
    last_candle = data.iloc[-1]
    
    # Calculate signal
    signal = st.session_state.trading_bot.check_signal(data)
    
    # Add signal to history if it's a new signal
    if signal not in ["NEUTRO"] and (
        not st.session_state.signals_history or 
        st.session_state.signals_history[-1]['signal'] != signal or
        st.session_state.signals_history[-1]['timestamp'] < datetime.now() - timedelta(minutes=5)
    ):
        st.session_state.signals_history.append({
            'timestamp': datetime.now(),
            'symbol': symbol,
            'price': last_candle['close'],
            'rsi': last_candle['rsi'],
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

    if not buy_signals.empty:
        # Strong buy signals (larger markers)
        strong_buys = buy_signals[buy_signals['signal'] == 'COMPRA']
        weak_buys = buy_signals[buy_signals['signal'] == 'COMPRA_FRACA']
        
        if not strong_buys.empty:
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
        
        if not weak_buys.empty:
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

    if not sell_signals.empty:
        # Strong sell signals (larger markers)
        strong_sells = sell_signals[sell_signals['signal'] == 'VENDA']
        weak_sells = sell_signals[sell_signals['signal'] == 'VENDA_FRACA']
        
        if not strong_sells.empty:
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
        
        if not weak_sells.empty:
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
    fig.add_hline(y=0, line_dash="dot", line_color="gray", row=3)

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
    
    # Rename columns
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

# Auto-refresh mechanism
if auto_refresh:
    time.sleep(1)
    st.rerun()

# Footer
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: gray;'>
Trading Signals Dashboard - Desenvolvido com Streamlit | ⚠️ Este sistema é apenas para fins educacionais
</div>
""", unsafe_allow_html=True)
