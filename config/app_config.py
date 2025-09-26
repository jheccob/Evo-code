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

    # Enhanced signal quality filters - REDUZIDOS para capturar mais oportunidades
    MIN_SIGNAL_CONFIDENCE = 55  # Reduzido de 70 para 55
    HIGH_CONFIDENCE_THRESHOLD = 75  # Reduzido de 85 para 75
    MIN_VOLUME_RATIO = 1.2     # Reduzido de 1.5 para 1.2
    MIN_ADX_TREND = 18         # Reduzido de 25 para 18
    MAX_ATR_PCT = 12          # Aumentado de 8 para 12 (permite mais volatilidade)

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
                "rsi_oversold": 30,  # Menos restritivo - de 25 para 30
                "rsi_overbought": 70,  # Menos restritivo - de 75 para 70
                "min_confidence": 60,  # Reduzido de 75 para 60
                "min_volume_ratio": 1.3,  # Reduzido de 1.8 para 1.3
                "min_adx": 20,  # Reduzido de 28 para 20
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
                "rsi_oversold": 20,  # RSI 9 otimizado
                "rsi_overbought": 80,
                "min_confidence": 85,
                "min_volume_ratio": 2.5,
                "volatility_filter": 0.08,
                "rsi_period": 9
            },
            "5m": {
                "rsi_oversold": 28,  # Menos restritivo - de 22 para 28
                "rsi_overbought": 72,  # Menos restritivo - de 78 para 72
                "min_confidence": 65,  # Reduzido de 80 para 65
                "min_volume_ratio": 1.4,  # Reduzido de 2.0 para 1.4
                "volatility_filter": 0.10,  # Aumentado para permitir mais volatilidade
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

    @classmethod
    def get_day_trading_settings(cls, timeframe="5m"):
        """Configurações otimizadas especificamente para Day Trading"""
        day_trading_config = {
            "1m": {
                "rsi_period": 9,        # RSI ultra-sensível
                "rsi_oversold": 12,     # Extremamente oversold
                "rsi_overbought": 88,   # Extremamente overbought
                "min_confidence": 88,   # Confiança muito alta
                "min_volume_ratio": 3.0, # Volume excepcional obrigatório
                "volatility_filter": 0.12, # Filtro de volatilidade agressivo
                "macd_fast": 8,         # MACD mais rápido
                "macd_slow": 17,
                "macd_signal": 6,
                "stoch_rsi_extreme": {"low": 10, "high": 90},
                "williams_r_extreme": {"low": -90, "high": -10},
                "min_adx": 30,          # Tendência muito forte
                "bb_squeeze_threshold": 0.08,
                "time_filters": {
                    "avoid_lunch": True,  # Evitar 12h-14h
                    "peak_hours_only": True, # 9h-11h, 14h-16h, 20h-22h
                }
            },
            "5m": {
                "rsi_period": 9,        # RSI sensível para day trading
                "rsi_oversold": 25,     # Menos agressivo - de 18 para 25
                "rsi_overbought": 75,   # Menos agressivo - de 82 para 75
                "min_confidence": 70,   # Reduzido de 82 para 70
                "min_volume_ratio": 1.5, # Reduzido de 2.2 para 1.5
                "volatility_filter": 0.09,
                "macd_fast": 9,         # MACD otimizado para day trading
                "macd_slow": 19,
                "macd_signal": 7,
                "stoch_rsi_extreme": {"low": 15, "high": 85},
                "williams_r_extreme": {"low": -85, "high": -15},
                "min_adx": 28,
                "bb_squeeze_threshold": 0.10,
                "time_filters": {
                    "avoid_lunch": True,
                    "peak_hours_only": True,
                }
            },
            "15m": {
                "rsi_period": 9,        # Mantém RSI 9 para consistência
                "rsi_oversold": 22,     # Menos agressivo em TF maior
                "rsi_overbought": 78,
                "min_confidence": 78,
                "min_volume_ratio": 1.8,
                "volatility_filter": 0.07,
                "macd_fast": 12,        # MACD padrão para 15m
                "macd_slow": 26,
                "macd_signal": 9,
                "stoch_rsi_extreme": {"low": 20, "high": 80},
                "williams_r_extreme": {"low": -80, "high": -20},
                "min_adx": 25,
                "bb_squeeze_threshold": 0.12,
                "time_filters": {
                    "avoid_lunch": False,  # 15m pode operar no almoço
                    "peak_hours_only": False,
                }
            }
        }
        return day_trading_config.get(timeframe, day_trading_config["5m"])

    @classmethod
    def get_scalping_settings(cls):
        """Configurações extremas para scalping (1m)"""
        return {
            "timeframe": "1m",
            "rsi_period": 7,            # RSI ultra-rápido
            "rsi_oversold": 10,         # Extremos absolutos
            "rsi_overbought": 90,
            "min_confidence": 92,       # Confiança máxima
            "min_volume_ratio": 4.0,    # Volume excepcional
            "volatility_filter": 0.15,  # Filtro muito agressivo
            "max_trades_per_hour": 12,  # Limitar trades por hora
            "min_profit_target": 0.3,   # 0.3% mínimo
            "max_loss_tolerance": 0.2,  # Stop muito apertado
            "require_all_indicators": True, # Todos indicadores devem concordar
            "time_restrictions": {
                "start_hour": 9,
                "end_hour": 16,
                "avoid_news_times": True,
            }
        }