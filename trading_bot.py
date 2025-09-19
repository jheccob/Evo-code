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
        """Calculate comprehensive technical indicators for the dataframe"""
        # Basic indicators
        df['rsi'] = self.indicators.calculate_rsi(df['close'], self.rsi_period)
        
        # Multiple moving averages for trend analysis
        smas = self.indicators.calculate_multiple_sma(df['close'], periods=[21, 50, 200])
        df['sma_21'] = smas['sma_21']
        df['sma_50'] = smas['sma_50'] 
        df['sma_200'] = smas['sma_200']
        df['sma_20'] = df['close'].rolling(window=20).mean()
        
        # MACD
        macd_data = self.indicators.calculate_macd(df['close'])
        df['macd'] = macd_data['macd']
        df['macd_signal'] = macd_data['signal'] 
        df['macd_histogram'] = macd_data['histogram']
        
        # Advanced volatility indicators
        df['atr'] = self.indicators.calculate_atr(df['high'], df['low'], df['close'])
        
        # Stochastic RSI for better overbought/oversold detection
        stoch_rsi = self.indicators.calculate_stochastic_rsi(df['rsi'])
        df['stoch_rsi_k'] = stoch_rsi['stoch_rsi_k']
        df['stoch_rsi_d'] = stoch_rsi['stoch_rsi_d']
        
        # ADX for trend strength
        adx_data = self.indicators.calculate_adx(df['high'], df['low'], df['close'])
        df['adx'] = adx_data['adx']
        df['di_plus'] = adx_data['di_plus']
        df['di_minus'] = adx_data['di_minus']
        
        # Williams %R
        df['williams_r'] = self.indicators.calculate_williams_r(df['high'], df['low'], df['close'])
        
        # Bollinger Bands for volatility
        bb = self.indicators.calculate_bollinger_bands(df['close'])
        df['bb_upper'] = bb['upper']
        df['bb_middle'] = bb['middle']
        df['bb_lower'] = bb['lower']
        df['bb_width'] = (bb['upper'] - bb['lower']) / bb['middle']
        
        # Volume analysis
        df['volume_ma'] = df['volume'].rolling(window=20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma']
        
        # Market regime detection
        df['market_regime'] = 'trending'  # Default
        if len(df) >= 50:
            for i in range(49, len(df)):
                regime = self.indicators.detect_market_regime(
                    df['close'].iloc[max(0, i-20):i+1], 
                    df['volume'].iloc[max(0, i-20):i+1],
                    df['atr'].iloc[max(0, i-20):i+1], 
                    df['adx'].iloc[max(0, i-20):i+1]
                )
                df.iloc[i, df.columns.get_loc('market_regime')] = regime
        
        # Trend analysis
        df['trend_analysis'] = ''
        df['trend_strength'] = 0
        if len(df) >= 200:
            for i in range(199, len(df)):
                if not pd.isna(df['sma_200'].iloc[i]):
                    trend_data = self.indicators.analyze_trend_strength(
                        df['close'].iloc[i:i+1], 
                        df['sma_21'].iloc[i:i+1], 
                        df['sma_50'].iloc[i:i+1], 
                        df['sma_200'].iloc[i:i+1]
                    )
                    df.iloc[i, df.columns.get_loc('trend_analysis')] = trend_data['trend']
                    df.iloc[i, df.columns.get_loc('trend_strength')] = trend_data['strength']
        
        # Generate advanced signals
        df['signal'] = df.apply(self._generate_advanced_signal, axis=1)
        df['signal_confidence'] = df.apply(self._calculate_signal_confidence, axis=1)
        
        return df
    
    def _generate_advanced_signal(self, row):
        """Generate advanced trading signal with multiple confirmations and filters"""
        # Skip if basic indicators are missing
        if pd.isna(row['rsi']) or pd.isna(row['macd']) or pd.isna(row['macd_signal']):
            return "NEUTRO"
        
        # Market regime filter - avoid trading in ranging markets
        market_regime = row.get('market_regime', 'trending')
        if market_regime == 'ranging':
            return "NEUTRO"  # No signals in ranging markets
        
        # ADX filter - only trade in trending markets
        adx = row.get('adx', 0)
        if not pd.isna(adx) and adx < 20:
            return "NEUTRO"  # Weak trend, avoid trading
        
        # Volatility filter - avoid extremely volatile periods
        bb_width = row.get('bb_width', 0)
        if not pd.isna(bb_width):
            bb_width_ma = row.get('bb_width', 0)  # Simplified check
            if bb_width > bb_width_ma * 2:  # Extreme volatility
                return "NEUTRO"
        
        # Primary indicators
        rsi = row['rsi']
        stoch_rsi_k = row.get('stoch_rsi_k', 50)
        williams_r = row.get('williams_r', -50)
        macd_histogram = row['macd_histogram']
        
        # Trend indicators
        price_above_sma21 = row['close'] > row.get('sma_21', row['close'])
        sma21_above_sma50 = row.get('sma_21', 0) > row.get('sma_50', 0)
        long_term_bullish = row.get('sma_50', 0) > row.get('sma_200', 0) if not pd.isna(row.get('sma_200')) else True
        
        # Volume confirmation
        volume_ratio = row.get('volume_ratio', 1)
        strong_volume = volume_ratio > 1.3
        
        # Bollinger Bands position
        bb_upper = row.get('bb_upper', row['close'])
        bb_lower = row.get('bb_lower', row['close'])
        near_bb_lower = row['close'] < (bb_lower * 1.02)
        near_bb_upper = row['close'] > (bb_upper * 0.98)
        
        # Score-based system
        bullish_score = 0
        bearish_score = 0
        
        # RSI scoring (optimized for crypto: 30/70 levels)
        if rsi < 30:
            bullish_score += 3
        elif rsi < 40:
            bullish_score += 2
        elif rsi > 70:
            bearish_score += 3
        elif rsi > 60:
            bearish_score += 2
        
        # Stochastic RSI scoring (better for crypto)
        if not pd.isna(stoch_rsi_k):
            if stoch_rsi_k < 20:
                bullish_score += 2
            elif stoch_rsi_k > 80:
                bearish_score += 2
        
        # Williams %R scoring
        if not pd.isna(williams_r):
            if williams_r < -80:
                bullish_score += 2
            elif williams_r > -20:
                bearish_score += 2
        
        # MACD scoring
        if macd_histogram > 0:
            bullish_score += 2
        elif macd_histogram < 0:
            bearish_score += 2
        
        # Trend alignment scoring
        if price_above_sma21 and sma21_above_sma50 and long_term_bullish:
            bullish_score += 3
        elif not price_above_sma21 and not sma21_above_sma50:
            bearish_score += 3
        
        # Volume confirmation
        if strong_volume:
            if bullish_score > bearish_score:
                bullish_score += 1
            elif bearish_score > bullish_score:
                bearish_score += 1
        
        # Bollinger Bands bounces
        if near_bb_lower and bullish_score > 0:
            bullish_score += 1
        elif near_bb_upper and bearish_score > 0:
            bearish_score += 1
        
        # ADX trend strength bonus
        if not pd.isna(adx):
            if adx > 30:
                if bullish_score > bearish_score:
                    bullish_score += 1
                elif bearish_score > bullish_score:
                    bearish_score += 1
        
        # Generate signal based on scores
        if bullish_score >= 8 and bullish_score > bearish_score + 3:
            return "COMPRA"
        elif bearish_score >= 8 and bearish_score > bullish_score + 3:
            return "VENDA"
        elif bullish_score >= 5 and bullish_score > bearish_score + 1:
            return "COMPRA_FRACA"
        elif bearish_score >= 5 and bearish_score > bullish_score + 1:
            return "VENDA_FRACA"
        else:
            return "NEUTRO"

    def _calculate_signal_confidence(self, row):
        """Calculate confidence score for the signal"""
        indicators_dict = {
            'rsi': row['rsi'],
            'macd': row['macd'],
            'macd_signal': row['macd_signal'],
            'macd_histogram': row['macd_histogram'],
            'trend_analysis': row.get('trend_analysis', 'LATERAL'),
            'adx': row.get('adx', 0),
            'stoch_rsi_k': row.get('stoch_rsi_k', 50),
            'volume_ratio': row.get('volume_ratio', 1),
            'market_regime': row.get('market_regime', 'trending')
        }
        
        return self.indicators.calculate_signal_confidence(indicators_dict)

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
        """Check the current trading signal with confidence score"""
        if df is None or df.empty:
            return "NEUTRO"
        
        last_row = df.iloc[-1]
        signal = self._generate_advanced_signal(last_row)
        confidence = self._calculate_signal_confidence(last_row)
        
        # Filter out low confidence signals
        if confidence < 60:
            return "NEUTRO"
        
        return signal
    
    def get_signal_with_confidence(self, df):
        """Get signal with confidence score"""
        if df is None or df.empty:
            return {"signal": "NEUTRO", "confidence": 0}
        
        last_row = df.iloc[-1]
        signal = self._generate_advanced_signal(last_row)
        confidence = self._calculate_signal_confidence(last_row)
        
        return {"signal": signal, "confidence": confidence}
    
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
