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

        gains = delta.clip(lower=0)
        losses = -delta.clip(upper=0)

        # Wilder smoothing keeps RSI more stable than a plain rolling average.
        avg_gains = gains.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        avg_losses = losses.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

        rs = avg_gains / avg_losses.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))

        flat_mask = (avg_gains == 0) & (avg_losses == 0)
        rsi = rsi.where(~flat_mask, 50.0)
        rsi = rsi.where(avg_losses != 0, 100.0)
        rsi = rsi.where(avg_gains != 0, 0.0)
        rsi = rsi.where(~flat_mask, 50.0)

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

    def calculate_stochastic_rsi(self, rsi, period=14, smooth_k=3, smooth_d=3):
        """Calculate Stochastic RSI for better oversold/overbought detection"""
        rsi_min = rsi.rolling(window=period).min()
        rsi_max = rsi.rolling(window=period).max()
        
        # Calculate %K
        denominator = (rsi_max - rsi_min).replace(0, np.nan)
        stoch_rsi_k = ((rsi - rsi_min) / denominator) * 100
        
        # Smooth %K to get %D
        stoch_rsi_k_smooth = stoch_rsi_k.rolling(window=smooth_k).mean()
        stoch_rsi_d = stoch_rsi_k_smooth.rolling(window=smooth_d).mean()
        
        return {
            'stoch_rsi_k': stoch_rsi_k_smooth,
            'stoch_rsi_d': stoch_rsi_d
        }

    def calculate_adx(self, high, low, close, period=14):
        """Calculate ADX (Average Directional Index) for trend strength"""
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        up_move = high.diff()
        down_move = -low.diff()
        dm_plus = pd.Series(
            np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
            index=close.index,
        )
        dm_minus = pd.Series(
            np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
            index=close.index,
        )

        tr_smooth = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        dm_plus_smooth = dm_plus.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        dm_minus_smooth = dm_minus.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

        di_plus = 100 * (dm_plus_smooth / tr_smooth.replace(0, np.nan))
        di_minus = 100 * (dm_minus_smooth / tr_smooth.replace(0, np.nan))

        dx_denominator = (di_plus + di_minus).replace(0, np.nan)
        dx = (abs(di_plus - di_minus) / dx_denominator) * 100
        adx = dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        
        return {
            'adx': adx,
            'di_plus': di_plus,
            'di_minus': di_minus
        }

    def detect_market_regime(self, close, volume, atr, adx, period=20, di_plus=None, di_minus=None):
        """
        Detect market regime: Trending, Ranging, or Volatile
        Returns: 'trending', 'ranging', 'volatile'
        """
        window = min(max(period, 10), len(close))
        if window < 10:
            return 'ranging'

        bb = self.calculate_bollinger_bands(close, period, 2)
        bb_width = (bb['upper'] - bb['lower']) / bb['middle']
        bb_width_mean = bb_width.rolling(window, min_periods=max(5, window // 2)).mean()
        bb_squeeze = bb_width < (bb_width_mean * 0.85)

        atr_pct = atr / close.replace(0, np.nan)
        atr_pct_mean = atr_pct.rolling(window, min_periods=max(5, window // 2)).mean()

        volume_mean = volume.rolling(window, min_periods=max(5, window // 2)).mean()
        volume_ratio = volume / volume_mean.replace(0, np.nan)

        slope_window = max(5, min(window // 2, len(close) - 1))
        sma_fast = close.rolling(slope_window, min_periods=slope_window).mean()
        if len(sma_fast.dropna()) >= slope_window:
            slope_pct = abs((sma_fast.iloc[-1] - sma_fast.iloc[-slope_window]) / close.iloc[-1])
        else:
            slope_pct = 0.0

        adx_last = float(adx.iloc[-1]) if len(adx) and not pd.isna(adx.iloc[-1]) else 0.0
        bb_width_last = float(bb_width.iloc[-1]) if len(bb_width) and not pd.isna(bb_width.iloc[-1]) else 0.0
        bb_width_mean_last = float(bb_width_mean.iloc[-1]) if len(bb_width_mean) and not pd.isna(bb_width_mean.iloc[-1]) else bb_width_last
        atr_pct_last = float(atr_pct.iloc[-1]) if len(atr_pct) and not pd.isna(atr_pct.iloc[-1]) else 0.0
        atr_pct_mean_last = float(atr_pct_mean.iloc[-1]) if len(atr_pct_mean) and not pd.isna(atr_pct_mean.iloc[-1]) else atr_pct_last
        volume_ratio_last = float(volume_ratio.iloc[-1]) if len(volume_ratio) and not pd.isna(volume_ratio.iloc[-1]) else 1.0
        bb_squeeze_last = bool(bb_squeeze.iloc[-1]) if len(bb_squeeze) and not pd.isna(bb_squeeze.iloc[-1]) else False

        directional_spread = 0.0
        if di_plus is not None and di_minus is not None and len(di_plus) and len(di_minus):
            di_plus_last = float(di_plus.iloc[-1]) if not pd.isna(di_plus.iloc[-1]) else 0.0
            di_minus_last = float(di_minus.iloc[-1]) if not pd.isna(di_minus.iloc[-1]) else 0.0
            directional_spread = abs(di_plus_last - di_minus_last)

        if (
            atr_pct_last > max(atr_pct_mean_last * 1.35, 0.025)
            or bb_width_last > max(bb_width_mean_last * 1.35, 0.18)
        ):
            return 'volatile'

        if (
            adx_last < 22
            and directional_spread < 8
            and (bb_squeeze_last or slope_pct < 0.0025)
            and volume_ratio_last < 1.15
        ):
            return 'ranging'

        if (
            adx_last >= 26
            and directional_spread >= 8
            and slope_pct >= 0.003
            and not bb_squeeze_last
            and volume_ratio_last >= 0.95
        ):
            return 'trending'

        if bb_squeeze_last or slope_pct < 0.0015:
            return 'ranging'

        return 'volatile' if adx_last < 24 else 'trending'

    def calculate_signal_confidence(self, indicators_dict):
        """
        Calculate optimized confidence score for maximum accuracy (0-100)
        """
        confidence = 0
        max_confidence = 100
        
        # Enhanced RSI confirmation (25 points)
        rsi = indicators_dict.get('rsi', 50)
        if rsi < 20 or rsi > 80:  # Extreme levels
            confidence += 25
        elif rsi < 25 or rsi > 75:  # Strong levels
            confidence += 20
        elif rsi < 35 or rsi > 65:  # Medium levels
            confidence += 12
        elif rsi < 45 or rsi > 55:  # Mild bias
            confidence += 5
        
        # Enhanced MACD confirmation (25 points)
        macd = indicators_dict.get('macd', 0)
        macd_signal = indicators_dict.get('macd_signal', 0)
        macd_histogram = indicators_dict.get('macd_histogram', 0)
        
        macd_aligned = (macd > macd_signal and macd_histogram > 0) or (macd < macd_signal and macd_histogram < 0)
        if macd_aligned:
            confidence += 15
            
            # Momentum strengthening
            prev_histogram = indicators_dict.get('prev_macd_histogram', 0)
            if abs(macd_histogram) > abs(prev_histogram):
                confidence += 5
            
            # Zero line cross bonus
            if (macd > 0 and macd_signal > 0) or (macd < 0 and macd_signal < 0):
                confidence += 5
        
        # Enhanced trend alignment (25 points)
        trend = indicators_dict.get('trend_analysis', 'LATERAL')
        trend_strength = indicators_dict.get('trend_strength', 0)
        
        if trend in ['FORTE_ALTA', 'FORTE_BAIXA']:
            confidence += 25
        elif trend in ['ALTA', 'BAIXA']:
            confidence += 18
        elif trend_strength > 70:
            confidence += 12
        elif trend_strength > 50:
            confidence += 8
        
        # Enhanced ADX trend strength (15 points)
        adx = indicators_dict.get('adx', 0)
        if adx > 40:  # Very strong trend
            confidence += 15
        elif adx > 30:  # Strong trend
            confidence += 12
        elif adx > 25:  # Medium trend
            confidence += 8
        elif adx > 20:  # Weak trend
            confidence += 4
        
        # Multi-oscillator confirmation (10 points)
        oscillator_consensus = 0
        
        # Stochastic RSI
        stoch_rsi_k = indicators_dict.get('stoch_rsi_k', 50)
        if stoch_rsi_k < 15 or stoch_rsi_k > 85:
            oscillator_consensus += 1
        elif stoch_rsi_k < 25 or stoch_rsi_k > 75:
            oscillator_consensus += 0.5
        
        # Williams %R
        williams_r = indicators_dict.get('williams_r', -50)
        if williams_r < -85 or williams_r > -15:
            oscillator_consensus += 1
        elif williams_r < -75 or williams_r > -25:
            oscillator_consensus += 0.5
        
        # Apply oscillator bonus
        if oscillator_consensus >= 1.5:
            confidence += 10
        elif oscillator_consensus >= 1:
            confidence += 7
        elif oscillator_consensus >= 0.5:
            confidence += 4
        
        # Enhanced volume confirmation (15 points)
        volume_ratio = indicators_dict.get('volume_ratio', 1)
        if volume_ratio > 2.5:  # Exceptional volume
            confidence += 15
        elif volume_ratio > 2.0:  # Very high volume
            confidence += 12
        elif volume_ratio > 1.5:  # High volume
            confidence += 9
        elif volume_ratio > 1.2:  # Above average volume
            confidence += 5
        elif volume_ratio < 0.8:  # Low volume penalty
            confidence -= 5
        
        # Market structure bonus/penalty
        market_regime = indicators_dict.get('market_regime', 'trending')
        if market_regime == 'trending':
            confidence += 5
        elif market_regime == 'ranging':
            confidence = max(0, confidence - 12)
            confidence *= 0.45
        elif market_regime == 'volatile':
            confidence = max(0, confidence - 8)
            confidence *= 0.65

        if adx < 18:
            confidence -= 8
        elif adx < 22:
            confidence -= 4

        if volume_ratio < 1.0:
            confidence -= 4
        
        # Time of day filter (if available)
        # Peak trading hours tend to have better signal reliability
        hour = indicators_dict.get('hour', 12)
        if 8 <= hour <= 16 or 20 <= hour <= 23:  # Peak trading hours
            confidence += 3
        
        # Divergence detection bonus
        price_rsi_divergence = indicators_dict.get('price_rsi_divergence', False)
        if price_rsi_divergence:
            confidence += 8
        
        # Multiple timeframe alignment bonus
        higher_tf_aligned = indicators_dict.get('higher_timeframe_aligned', False)
        if higher_tf_aligned:
            confidence += 10
        
        # Apply final constraints
        confidence = max(0, confidence)  # Ensure non-negative
        confidence = min(confidence, max_confidence)
        
        if confidence < 45:
            confidence *= 0.75
        
        return int(confidence)
    
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
