
class AppConfig:
    # Trading parameters
    DEFAULT_SYMBOL = "XLM-USD"
    DEFAULT_TIMEFRAME = "5m"
    DEFAULT_RSI_PERIOD = 9
    DEFAULT_RSI_MIN = 20
    DEFAULT_RSI_MAX = 80
    
    # API limits
    MAX_CANDLES = 1000
    UPDATE_INTERVAL = 60  # seconds
    
    # Signal confidence thresholds
    MIN_SIGNAL_CONFIDENCE = 60
    HIGH_CONFIDENCE_THRESHOLD = 80
    
    # Backtest settings
    DEFAULT_INITIAL_BALANCE = 10000
    MAX_BACKTEST_DAYS = 90
    
    # Database settings
    DB_PATH = "data/trading_bot.db"
    MAX_SIGNALS_HISTORY = 1000
    
    # UI settings
    CHART_HEIGHT = 800
    MAX_MULTI_SYMBOLS = 10
    
    @classmethod
    def get_supported_pairs(cls):
        return ["XLM-USD", "BTC-USD", "ETH-USD", "ADA-USD", "DOT-USD", 
                "MATIC-USD", "LINK-USD", "UNI-USD", "SOL-USD", "AVAX-USD"]
    
    @classmethod
    def get_supported_timeframes(cls):
        return ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
