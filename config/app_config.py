
class AppConfig:
    # Trading parameters - Optimized for maximum accuracy
    DEFAULT_SYMBOL = "XLM/USDT"
    DEFAULT_TIMEFRAME = "15m"  # Changed from 5m for better signal quality
    DEFAULT_RSI_PERIOD = 9     # RSI mais sensível para detecção precoce
    DEFAULT_RSI_MIN = 20       # Mais agressivo com RSI 9
    DEFAULT_RSI_MAX = 80       # Mais agressivo com RSI 9
    
    # Exchange configuration for Brazil
    DEFAULT_EXCHANGE = "bybit"  # Recommended for Brazil
    BRAZIL_SUPPORTED_EXCHANGES = ["bybit", "okx", "kucoin", "mexc"]
    
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
        return ["XLM/USDT", "BTC/USDT", "ETH/USDT", "ADA/USDT", "DOT/USDT", 
                "MATIC/USDT", "LINK/USDT", "UNI/USDT", "SOL/USDT", "AVAX/USDT"]
    
    @classmethod
    def get_supported_timeframes(cls):
        return ["5m", "15m", "30m", "1h", "4h", "1d"]
    
    @classmethod
    def get_optimized_settings(cls, asset_class="crypto"):
        """Get optimized settings for different asset classes"""
        if asset_class == "crypto":
            return {
                "rsi_period": 14,
                "rsi_oversold": 25,  # Mais restritivo para crypto (era 30)
                "rsi_overbought": 75,  # Mais restritivo para crypto (era 70)
                "min_confidence": 75,  # Alta confiança para reduzir falsos sinais
                "min_volume_ratio": 1.8,  # Volume 80% acima da média
                "min_adx": 28,  # Tendência forte obrigatória
                "stoch_rsi_extreme": {"low": 15, "high": 85},  # StochRSI extremos
                "williams_r_extreme": {"low": -85, "high": -15},  # Williams %R extremos
                "bb_squeeze_threshold": 0.12,  # Bollinger Bands squeeze
                "macd_zero_line_bonus": True,  # Bonus para MACD acima/abaixo de zero
                "trend_alignment_required": True,  # Exigir alinhamento de tendência
                "volatility_filter": 0.08,  # ATR máximo 8% do preço
                "time_of_day_filter": True  # Filtro por horário de maior liquidez
            }
        elif asset_class == "forex":
            return {
                "rsi_period": 21,
                "rsi_oversold": 30,
                "rsi_overbought": 70,
                "min_confidence": 70,
                "min_volume_ratio": 1.3,
                "min_adx": 25,
                "stoch_rsi_extreme": {"low": 20, "high": 80},
                "williams_r_extreme": {"low": -80, "high": -20},
                "bb_squeeze_threshold": 0.15,
                "macd_zero_line_bonus": False,
                "trend_alignment_required": False,
                "volatility_filter": 0.05,
                "time_of_day_filter": True
            }
        else:
            return cls.get_optimized_settings("crypto")
    
    @classmethod
    def get_crypto_timeframe_settings(cls, timeframe="5m"):
        """Configurações otimizadas para RSI 9 - mais sensível mas com filtros rigorosos"""
        settings = {
            "1m": {
                "rsi_oversold": 15,  # Extremos para RSI 9
                "rsi_overbought": 85,
                "min_confidence": 85,  # Mais restritivo com RSI sensível
                "min_volume_ratio": 2.5,  # Volume muito alto obrigatório
                "volatility_filter": 0.10,
                "rsi_period": 9
            },
            "5m": {
                "rsi_oversold": 20,  # Mais agressivo com RSI 9
                "rsi_overbought": 80,
                "min_confidence": 80,  # Confiança alta
                "min_volume_ratio": 2.0,  # Volume alto
                "volatility_filter": 0.08,
                "rsi_period": 9
            },
            "15m": {
                "rsi_oversold": 25,  # Balanceado para RSI 9
                "rsi_overbought": 75,
                "min_confidence": 75,
                "min_volume_ratio": 1.8,
                "volatility_filter": 0.06,
                "rsi_period": 9
            },
            "1h": {
                "rsi_oversold": 30,  # RSI 9 em timeframe maior
                "rsi_overbought": 70,
                "min_confidence": 70,
                "min_volume_ratio": 1.5,
                "volatility_filter": 0.05,
                "rsi_period": 9
            },
            "4h": {
                "rsi_oversold": 35,  # Conservador em timeframes longos
                "rsi_overbought": 65,
                "min_confidence": 65,
                "min_volume_ratio": 1.3,
                "volatility_filter": 0.04,
                "rsi_period": 9
            },
            "1d": {
                "rsi_oversold": 30,  # RSI 14 para daily (mais estável)
                "rsi_overbought": 70,
                "min_confidence": 60,
                "min_volume_ratio": 1.2,
                "volatility_filter": 0.03,
                "rsi_period": 14  # Daily usa RSI 14
            }
        }
        return settings.get(timeframe, settings["5m"])
