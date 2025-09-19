import pandas as pd
import numpy as np

class TechnicalIndicators:
    """Class containing various technical indicator calculations"""
    
    def calculate_rsi(self, prices, period=14):
        """
        Calculate Relative Strength Index (RSI)
        
        Args:
            prices: Series of prices (typically closing prices)
            period: RSI calculation period (default 14)
        
        Returns:
            Series with RSI values
        """
        if len(prices) < period + 1:
            return pd.Series([np.nan] * len(prices), index=prices.index)
        
        delta = prices.diff()
        
        # Separate gains and losses
        gains = delta.where(delta > 0, 0)
        losses = -delta.where(delta < 0, 0)
        
        # Calculate average gains and losses
        avg_gains = gains.rolling(window=period).mean()
        avg_losses = losses.rolling(window=period).mean()
        
        # Calculate RS and RSI
        rs = avg_gains / avg_losses
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def calculate_sma(self, prices, period):
        """
        Calculate Simple Moving Average
        
        Args:
            prices: Series of prices
            period: Moving average period
        
        Returns:
            Series with SMA values
        """
        return prices.rolling(window=period).mean()
    
    def calculate_ema(self, prices, period):
        """
        Calculate Exponential Moving Average
        
        Args:
            prices: Series of prices
            period: EMA period
        
        Returns:
            Series with EMA values
        """
        return prices.ewm(span=period, adjust=False).mean()
    
    def calculate_bollinger_bands(self, prices, period=20, std_dev=2):
        """
        Calculate Bollinger Bands
        
        Args:
            prices: Series of prices
            period: Moving average period
            std_dev: Standard deviation multiplier
        
        Returns:
            Dictionary with upper, middle, and lower bands
        """
        sma = self.calculate_sma(prices, period)
        std = prices.rolling(window=period).std()
        
        upper_band = sma + (std * std_dev)
        lower_band = sma - (std * std_dev)
        
        return {
            'upper': upper_band,
            'middle': sma,
            'lower': lower_band
        }
    
    def calculate_macd(self, prices, fast_period=12, slow_period=26, signal_period=9):
        """
        Calculate MACD (Moving Average Convergence Divergence)
        
        Args:
            prices: Series of prices
            fast_period: Fast EMA period
            slow_period: Slow EMA period
            signal_period: Signal line EMA period
        
        Returns:
            Dictionary with MACD line, signal line, and histogram
        """
        ema_fast = self.calculate_ema(prices, fast_period)
        ema_slow = self.calculate_ema(prices, slow_period)
        
        macd_line = ema_fast - ema_slow
        signal_line = self.calculate_ema(macd_line, signal_period)
        histogram = macd_line - signal_line
        
        return {
            'macd': macd_line,
            'signal': signal_line,
            'histogram': histogram
        }

    def calculate_multiple_sma(self, prices, periods=[21, 50, 200]):
        """
        Calculate multiple Simple Moving Averages for trend analysis
        
        Args:
            prices: Series of prices
            periods: List of periods for SMAs
        
        Returns:
            Dictionary with SMA values for each period
        """
        smas = {}
        for period in periods:
            smas[f'sma_{period}'] = self.calculate_sma(prices, period)
        return smas

    def analyze_trend_strength(self, prices, sma_21, sma_50, sma_200):
        """
        Analyze trend strength using multiple moving averages
        
        Args:
            prices: Current price series
            sma_21, sma_50, sma_200: Moving averages
        
        Returns:
            Dictionary with trend analysis
        """
        current_price = prices.iloc[-1] if len(prices) > 0 else 0
        
        # Check trend direction
        uptrend = (sma_21.iloc[-1] > sma_50.iloc[-1] > sma_200.iloc[-1])
        downtrend = (sma_21.iloc[-1] < sma_50.iloc[-1] < sma_200.iloc[-1])
        
        # Price position relative to SMAs
        above_all = current_price > sma_21.iloc[-1] > sma_50.iloc[-1] > sma_200.iloc[-1]
        below_all = current_price < sma_21.iloc[-1] < sma_50.iloc[-1] < sma_200.iloc[-1]
        
        # Calculate trend strength (0-100)
        if uptrend and above_all:
            strength = 85
            trend = "FORTE_ALTA"
        elif uptrend and current_price > sma_21.iloc[-1]:
            strength = 70
            trend = "ALTA"
        elif downtrend and below_all:
            strength = 85
            trend = "FORTE_BAIXA"
        elif downtrend and current_price < sma_21.iloc[-1]:
            strength = 70
            trend = "BAIXA"
        else:
            strength = 30
            trend = "LATERAL"
        
        return {
            'trend': trend,
            'strength': strength,
            'uptrend': uptrend,
            'downtrend': downtrend,
            'above_all_sma': above_all,
            'below_all_sma': below_all
        }
    
    def calculate_stochastic(self, high, low, close, k_period=14, d_period=3):
        """
        Calculate Stochastic Oscillator
        
        Args:
            high: Series of high prices
            low: Series of low prices
            close: Series of closing prices
            k_period: %K period
            d_period: %D period
        
        Returns:
            Dictionary with %K and %D values
        """
        lowest_low = low.rolling(window=k_period).min()
        highest_high = high.rolling(window=k_period).max()
        
        k_percent = 100 * ((close - lowest_low) / (highest_high - lowest_low))
        d_percent = k_percent.rolling(window=d_period).mean()
        
        return {
            'k_percent': k_percent,
            'd_percent': d_percent
        }
    
    def calculate_atr(self, high, low, close, period=14):
        """
        Calculate Average True Range (ATR)
        
        Args:
            high: Series of high prices
            low: Series of low prices
            close: Series of closing prices
            period: ATR period
        
        Returns:
            Series with ATR values
        """
        # True Range calculation
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        
        return atr
    
    def calculate_williams_r(self, high, low, close, period=14):
        """
        Calculate Williams %R
        
        Args:
            high: Series of high prices
            low: Series of low prices
            close: Series of closing prices
            period: Williams %R period
        
        Returns:
            Series with Williams %R values
        """
        highest_high = high.rolling(window=period).max()
        lowest_low = low.rolling(window=period).min()
        
        williams_r = -100 * ((highest_high - close) / (highest_high - lowest_low))
        
        return williams_r
    
    def calculate_roc(self, prices, period=12):
        """
        Calculate Rate of Change (ROC)
        
        Args:
            prices: Series of prices
            period: ROC period
        
        Returns:
            Series with ROC values
        """
        roc = ((prices - prices.shift(period)) / prices.shift(period)) * 100
        return roc
