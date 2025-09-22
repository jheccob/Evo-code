
class AppConfig:
    # Trading parameters - Optimized for maximum accuracy
    DEFAULT_SYMBOL = "XLM-USD"
    DEFAULT_TIMEFRAME = "15m"  # Changed from 5m for better signal quality
    DEFAULT_RSI_PERIOD = 14    # Changed from 9 to standard 14
    DEFAULT_RSI_MIN = 25       # Changed from 20 for fewer false signals
    DEFAULT_RSI_MAX = 75       # Changed from 80 for better precision
    
    # Enhanced signal quality filters
    MIN_SIGNAL_CONFIDENCE = 70  # Increased from 60
    HIGH_CONFIDENCE_THRESHOLD = 85  # Increased from 80
    MIN_VOLUME_RATIO = 1.5     # Minimum volume for signals
    MIN_ADX_TREND = 25         # Minimum ADX for trend confirmation
    MAX_ATR_PCT = 8           # Maximum ATR% for volatility filter
    
    # API limits
    MAX_CANDLES = 1000
    UPDATE_INTERVAL = 60  # seconds
    
    # Backtest settings
    DEFAULT_INITIAL_BALANCE = 10000
    MAX_BACKTEST_DAYS = 90
    
    # Database settings
    DB_PATH = "data/trading_bot.db"
    MAX_SIGNALS_HISTORY = 1000
    
    # UI settings
    CHART_HEIGHT = 800
    MAX_MULTI_SYMBOLS = 10
    
    # Optimized indicator periods
    MACD_FAST = 12
    MACD_SLOW = 26
    MACD_SIGNAL = 9
    BB_PERIOD = 20
    BB_STD = 2
    ADX_PERIOD = 14
    STOCH_RSI_PERIOD = 14
    WILLIAMS_R_PERIOD = 14
    
    @classmethod
    def get_supported_pairs(cls):
        return ["XLM-USD", "BTC-USD", "ETH-USD", "ADA-USD", "DOT-USD", 
                "MATIC-USD", "LINK-USD", "UNI-USD", "SOL-USD", "AVAX-USD"]
    
    @classmethod
    def get_supported_timeframes(cls):
        return ["5m", "15m", "30m", "1h", "4h", "1d"]
    
    @classmethod
    def get_optimized_settings(cls, asset_class="crypto"):
        """Get optimized settings for different asset classes"""
        if asset_class == "crypto":
            return {
                "rsi_period": 14,
                "rsi_oversold": 25,
                "rsi_overbought": 75,
                "min_confidence": 75,
                "min_volume_ratio": 1.8,
                "min_adx": 28
            }
        elif asset_class == "forex":
            return {
                "rsi_period": 21,
                "rsi_oversold": 30,
                "rsi_overbought": 70,
                "min_confidence": 70,
                "min_volume_ratio": 1.3,
                "min_adx": 25
            }
        else:
            return cls.get_optimized_settings("crypto")
