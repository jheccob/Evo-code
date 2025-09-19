import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
import os
from indicators import TechnicalIndicators

class TradingBot:
    def __init__(self):
        self.exchange = ccxt.coinbase({
            'enableRateLimit': True,
            'sandbox': False,
            'rateLimit': 1000,
        })
        self.symbol = "XLM-USD"
        self.timeframe = "5m"
        self.rsi_period = 9
        self.rsi_min = 20
        self.rsi_max = 80
        self.indicators = TechnicalIndicators()
        
    def update_config(self, symbol=None, timeframe=None, rsi_period=None, rsi_min=None, rsi_max=None):
        """Update bot configuration parameters"""
        if symbol:
            self.symbol = symbol
        if timeframe:
            self.timeframe = timeframe
        if rsi_period:
            self.rsi_period = rsi_period
        if rsi_min:
            self.rsi_min = rsi_min
        if rsi_max:
            self.rsi_max = rsi_max
    
    def get_market_data(self, limit=200):
        """Fetch OHLCV data from exchange"""
        try:
            # Format symbol for Coinbase Pro
            formatted_symbol = self.format_symbol_for_coinbase(self.symbol)
            
            # Fetch raw OHLCV data
            ohlcv = self.exchange.fetch_ohlcv(formatted_symbol, self.timeframe, limit=limit)
            
            if not ohlcv:
                raise Exception("No data received from exchange")
            
            # Convert to DataFrame
            df = pd.DataFrame(ohlcv)
            df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
            
            # Convert timestamp to datetime
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            # Calculate technical indicators
            df = self.calculate_indicators(df)
            
            return df
            
        except Exception as e:
            print(f"Error fetching market data for {self.symbol}: {e}")
            raise e
    
    def calculate_indicators(self, df):
        """Calculate technical indicators for the dataframe"""
        # Calculate RSI
        df['rsi'] = self.indicators.calculate_rsi(df['close'], self.rsi_period)
        
        # Calculate multiple moving averages for trend analysis (21, 50, 200)
        smas = self.indicators.calculate_multiple_sma(df['close'], periods=[21, 50, 200])
        df['sma_21'] = smas['sma_21']
        df['sma_50'] = smas['sma_50'] 
        df['sma_200'] = smas['sma_200']
        
        # Calculate additional SMAs for completeness
        df['sma_20'] = df['close'].rolling(window=20).mean()
        
        # Calculate volume moving average
        df['volume_ma'] = df['volume'].rolling(window=20).mean()
        
        # Calculate MACD
        macd_data = self.indicators.calculate_macd(df['close'])
        df['macd'] = macd_data['macd']
        df['macd_signal'] = macd_data['signal'] 
        df['macd_histogram'] = macd_data['histogram']
        
        # Analyze trend strength using multiple SMAs
        df['trend_analysis'] = ''
        if len(df) >= 200:  # Ensure we have enough data for SMA 200
            trend_data = self.indicators.analyze_trend_strength(
                df['close'], df['sma_21'], df['sma_50'], df['sma_200']
            )
            df.loc[df.index[-1], 'trend_analysis'] = trend_data['trend']
            df.loc[df.index[-1], 'trend_strength'] = trend_data['strength']
        
        # Generate signals with improved logic
        df['signal'] = df.apply(self._generate_improved_signal, axis=1)
        
        return df
    
    def _generate_improved_signal(self, row):
        """Generate improved trading signal based on RSI, MACD, and moving averages"""
        if pd.isna(row['rsi']) or pd.isna(row['macd']) or pd.isna(row['macd_signal']):
            return "NEUTRO"
        
        # Check if we have SMA data
        if pd.isna(row.get('sma_21')) or pd.isna(row.get('sma_50')):
            # Fallback to basic signals if SMAs not available
            return self._generate_basic_signal(row)
        
        # RSI signals
        rsi_oversold = row['rsi'] < self.rsi_min
        rsi_overbought = row['rsi'] > self.rsi_max
        rsi_neutral = self.rsi_min <= row['rsi'] <= self.rsi_max
        
        # MACD signals
        macd_bullish = row['macd'] > row['macd_signal'] and row['macd_histogram'] > 0
        macd_bearish = row['macd'] < row['macd_signal'] and row['macd_histogram'] < 0
        
        # Moving Average trends (short vs medium term)
        price_above_sma21 = row['close'] > row['sma_21']
        sma21_above_sma50 = row['sma_21'] > row['sma_50']
        
        # Long term trend (if SMA 200 available)
        long_term_bullish = True
        if not pd.isna(row.get('sma_200')):
            long_term_bullish = row['sma_50'] > row['sma_200']
        
        # Volume confirmation (if available)
        volume_confirmation = True
        if not pd.isna(row.get('volume_ma')):
            volume_confirmation = row['volume'] > row['volume_ma'] * 1.2
        
        # Strong BUY conditions - multiple confirmations
        if (rsi_oversold and macd_bullish and price_above_sma21 and 
            sma21_above_sma50 and long_term_bullish and volume_confirmation):
            return "COMPRA"
        
        # Strong SELL conditions
        elif (rsi_overbought and macd_bearish and not price_above_sma21 and 
              not sma21_above_sma50):
            return "VENDA"
        
        # Medium strength signals
        elif (rsi_oversold and (macd_bullish or price_above_sma21)):
            return "COMPRA_FRACA"
        elif (rsi_overbought and (macd_bearish or not price_above_sma21)):
            return "VENDA_FRACA"
        
        # MACD only signals (weaker)
        elif macd_bullish and price_above_sma21 and sma21_above_sma50:
            return "COMPRA_FRACA"
        elif macd_bearish and not price_above_sma21:
            return "VENDA_FRACA"
            
        else:
            return "NEUTRO"

    def _generate_basic_signal(self, row):
        """Basic signal generation for when SMAs are not available"""
        # RSI signals
        rsi_bullish = row['rsi'] < self.rsi_min
        rsi_bearish = row['rsi'] > self.rsi_max
        
        # MACD signals
        macd_bullish = row['macd'] > row['macd_signal'] and row['macd_histogram'] > 0
        macd_bearish = row['macd'] < row['macd_signal'] and row['macd_histogram'] < 0
        
        # Combined signals - both indicators need to agree for strong signal
        if rsi_bullish and macd_bullish:
            return "COMPRA"
        elif rsi_bearish and macd_bearish:
            return "VENDA"
        elif rsi_bullish or macd_bullish:
            return "COMPRA_FRACA"
        elif rsi_bearish or macd_bearish:
            return "VENDA_FRACA"
        else:
            return "NEUTRO"
    
    def check_signal(self, df):
        """Check the current trading signal"""
        if df is None or df.empty:
            return "NEUTRO"
        
        last_row = df.iloc[-1]
        return self._generate_improved_signal(last_row)
    
    def get_market_summary(self, df):
        """Get market summary statistics"""
        if df is None or df.empty:
            return None
        
        last_candle = df.iloc[-1]
        
        # Calculate price change
        price_change = last_candle['close'] - last_candle['open']
        price_change_pct = (price_change / last_candle['open']) * 100
        
        # Calculate 24h high/low (approximation using available data)
        high_24h = df['high'].tail(288).max() if len(df) >= 288 else df['high'].max()  # 288 = 24h in 5min candles
        low_24h = df['low'].tail(288).min() if len(df) >= 288 else df['low'].min()
        
        return {
            'current_price': last_candle['close'],
            'price_change': price_change,
            'price_change_pct': price_change_pct,
            'high_24h': high_24h,
            'low_24h': low_24h,
            'volume': last_candle['volume'],
            'rsi': last_candle['rsi'],
            'signal': self.check_signal(df)
        }
    
    def validate_symbol(self, symbol):
        """Validate if symbol exists on the exchange"""
        try:
            markets = self.exchange.load_markets()
            # Convert format: BTC/USDT -> BTC-USD
            if '/' in symbol:
                symbol = symbol.replace('/USDT', '-USD').replace('/BTC', '-BTC')
            return symbol in markets
        except:
            return False

    def format_symbol_for_coinbase(self, symbol):
        """Convert symbol format for Coinbase Pro"""
        if '/' in symbol:
            return symbol.replace('/USDT', '-USD').replace('/BTC', '-BTC').replace('/', '-')
        return symbol
