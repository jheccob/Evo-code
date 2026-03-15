import ccxt
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _get_default_db_path() -> str:
    explicit_path = os.getenv("TRADING_BOT_DB_PATH", "").strip()
    if explicit_path:
        return explicit_path

    railway_volume_mount = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    if railway_volume_mount:
        return f"{railway_volume_mount.rstrip('/')}/trading_bot.db"

    return "data/trading_bot.db"

class AppConfig:
    # Trading parameters - Optimized for maximum accuracy
    DEFAULT_SYMBOL = "XLM/USDT"
    DEFAULT_TIMEFRAME = "15m"
    DEFAULT_RSI_PERIOD = 9
    DEFAULT_RSI_MIN = 20
    DEFAULT_RSI_MAX = 80

    DEFAULT_EXCHANGE = "bybit"
    BRAZIL_SUPPORTED_EXCHANGES = ["bybit", "okx", "kucoin", "mexc"]

    MIN_SIGNAL_CONFIDENCE = 55
    HIGH_CONFIDENCE_THRESHOLD = 75
    MIN_VOLUME_RATIO = 1.2
    MIN_ADX_TREND = 18
    MAX_ATR_PCT = 12

    MAX_CANDLES = 1000
    UPDATE_INTERVAL = 90

    DEFAULT_INITIAL_BALANCE = 10000
    MAX_BACKTEST_DAYS = 90

    DB_PATH = _get_default_db_path()
    MAX_SIGNALS_HISTORY = 1000

    CHART_HEIGHT = 800
    MAX_MULTI_SYMBOLS = 10

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
        if asset_class == "crypto":
            return {
                "rsi_period": 14,
                "rsi_oversold": 30,
                "rsi_overbought": 70,
                "min_confidence": 60,
                "min_volume_ratio": 1.3,
                "min_adx": 20,
                "stoch_rsi_extreme": {"low": 15, "high": 85},
                "williams_r_extreme": {"low": -85, "high": -15},
                "bb_squeeze_threshold": 0.12,
                "macd_zero_line_bonus": True,
                "trend_alignment_required": True,
                "volatility_filter": 0.08,
                "time_of_day_filter": True
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
        settings = {
            "1m": {"rsi_oversold": 20, "rsi_overbought": 80, "min_confidence": 85, "min_volume_ratio": 2.5, "volatility_filter": 0.08, "rsi_period": 9},
            "5m": {"rsi_oversold": 28, "rsi_overbought": 72, "min_confidence": 65, "min_volume_ratio": 1.4, "volatility_filter": 0.10, "rsi_period": 9},
            "15m": {"rsi_oversold": 25, "rsi_overbought": 75, "min_confidence": 75, "min_volume_ratio": 1.8, "volatility_filter": 0.06, "rsi_period": 9},
            "1h": {"rsi_oversold": 30, "rsi_overbought": 70, "min_confidence": 70, "min_volume_ratio": 1.5, "volatility_filter": 0.05, "rsi_period": 9},
            "4h": {"rsi_oversold": 35, "rsi_overbought": 65, "min_confidence": 65, "min_volume_ratio": 1.3, "volatility_filter": 0.04, "rsi_period": 9},
            "1d": {"rsi_oversold": 30, "rsi_overbought": 70, "min_confidence": 60, "min_volume_ratio": 1.2, "volatility_filter": 0.03, "rsi_period": 14}
        }
        return settings.get(timeframe, settings["5m"])

    @classmethod
    def get_day_trading_settings(cls, timeframe="5m"):
        day_trading_config = {
            "1m": {"rsi_period": 9, "rsi_oversold": 12, "rsi_overbought": 88, "min_confidence": 88, "min_volume_ratio": 3.0, "volatility_filter": 0.12, "macd_fast": 8, "macd_slow": 17, "macd_signal": 6, "stoch_rsi_extreme": {"low": 10, "high": 90}, "williams_r_extreme": {"low": -90, "high": -10}, "min_adx": 30, "bb_squeeze_threshold": 0.08, "time_filters": {"avoid_lunch": True, "peak_hours_only": True}},
            "5m": {"rsi_period": 14, "rsi_oversold": 20, "rsi_overbought": 80, "min_confidence": 75, "min_volume_ratio": 2.0, "volatility_filter": 0.09, "macd_fast": 9, "macd_slow": 19, "macd_signal": 7, "stoch_rsi_extreme": {"low": 15, "high": 85}, "williams_r_extreme": {"low": -85, "high": -15}, "min_adx": 28, "bb_squeeze_threshold": 0.10, "time_filters": {"avoid_lunch": True, "peak_hours_only": True}},
            "15m": {"rsi_period": 9, "rsi_oversold": 22, "rsi_overbought": 78, "min_confidence": 78, "min_volume_ratio": 1.8, "volatility_filter": 0.07, "macd_fast": 12, "macd_slow": 26, "macd_signal": 9, "stoch_rsi_extreme": {"low": 20, "high": 80}, "williams_r_extreme": {"low": -80, "high": -20}, "min_adx": 25, "bb_squeeze_threshold": 0.09, "time_filters": {"avoid_lunch": False, "peak_hours_only": True}}
        }
        return day_trading_config.get(timeframe, day_trading_config["5m"])


class ExchangeConfig:
    @classmethod
    def normalize_symbol(cls, symbol, market_info=None):
        if ':' in symbol:
            base_symbol = symbol.split(':')[0]
            return {
                'symbol': base_symbol,
                'raw_symbol': symbol,
                'is_future': True,
                'quote': 'USDT'
            }
        else:
            return {
                'symbol': symbol,
                'raw_symbol': symbol,
                'is_future': False,
                'quote': 'USDT' if symbol.endswith('/USDT') else 'USD'
            }

    SUPPORTED_EXCHANGES = {
        'binance': {
            'name': 'Binance WebSocket Público',
            'futures_supported': True,
            'brazil_accessible': True,
            'usdt_pairs': True,
            'requires_credentials': False,
            'description': 'Binance - WebSocket público sem necessidade de credenciais'
        }
    }

    @classmethod
    def get_exchange_instance(cls, exchange_name='binance', testnet=False):
        if exchange_name not in cls.SUPPORTED_EXCHANGES:
            raise ValueError(f"Exchange {exchange_name} não suportado")

        exchange_class = getattr(ccxt, exchange_name)

        config = {
            'enableRateLimit': True,
            'sandbox': testnet,
            'timeout': 30000,
            'headers': {'User-Agent': 'TradingBot-Professional/1.0'}
        }

        if exchange_name == 'binance':
            config.update({
                'rateLimit': 1200,
                'options': {
                    'defaultType': 'future',
                    'adjustForTimeDifference': True,
                    'recvWindow': 10000
                }
            })
            logger.info("✅ Binance WebSocket Público configurado - sem necessidade de credenciais")

        return exchange_class(config)

    @classmethod
    def is_valid_usdt_pair(cls, symbol):
        if not symbol or not isinstance(symbol, str):
            return False

        valid_pairs = {
            "BTC/USDT", "ETH/USDT", "XLM/USDT", "ADA/USDT", "SOL/USDT",
            "DOGE/USDT", "LTC/USDT", "AVAX/USDT", "MATIC/USDT", "DOT/USDT",
            "LINK/USDT", "UNI/USDT", "ATOM/USDT", "FTM/USDT", "NEAR/USDT"
        }

        return symbol in valid_pairs

    @classmethod
    def get_usdt_pairs(cls, exchange_name='okx'):
        try:
            exchange = cls.get_exchange_instance(exchange_name)
            markets = exchange.load_markets()

            pairs = []
            normalized_symbols = set()

            for symbol, market in markets.items():
                if (market.get('active', True) and market.get('type') in ['future', 'swap']):
                    if ':USDT' in symbol or (symbol.endswith('/USDT') and market.get('type') in ['future', 'swap']):
                        normalized = cls.normalize_symbol(symbol, market)
                        if (normalized['symbol'] not in normalized_symbols and cls.is_valid_usdt_pair(normalized['symbol'])):
                            pairs.append(normalized['symbol'])
                            normalized_symbols.add(normalized['symbol'])
                elif (symbol.endswith('/USDT') and market.get('type') == 'spot' and symbol not in normalized_symbols and cls.is_valid_usdt_pair(symbol)):
                    pairs.append(symbol)
                    normalized_symbols.add(symbol)

            return sorted(pairs)
        except Exception as e:
            logger.warning(f"Erro ao carregar pares OKX: {e}")
            return ["BTC/USDT", "ETH/USDT", "XLM/USDT", "ADA/USDT", "SOL/USDT", "DOGE/USDT", "LTC/USDT", "AVAX/USDT"]

    @classmethod
    def get_usdt_pairs_with_metadata(cls, exchange_name='okx'):
        try:
            exchange = cls.get_exchange_instance(exchange_name)
            markets = exchange.load_markets()

            pairs = {}
            normalized_symbols = set()

            for symbol, market in markets.items():
                if exchange_name == 'coinbase':
                    if (symbol.endswith('/USD') and market.get('active', True) and market.get('type') == 'spot'):
                        normalized = cls.normalize_symbol(symbol, market)
                        pairs[normalized['symbol']] = normalized
                        normalized_symbols.add(normalized['symbol'])
                else:
                    if (market.get('active', True) and market.get('type') in ['future', 'swap']):
                        if ':USDT' in symbol or (symbol.endswith('/USDT') and market.get('type') in ['future', 'swap']):
                            normalized = cls.normalize_symbol(symbol, market)
                            if normalized['symbol'] not in normalized_symbols:
                                pairs[normalized['symbol']] = normalized
                                normalized_symbols.add(normalized['symbol'])
                    elif (symbol.endswith('/USDT') and market.get('type') == 'spot' and symbol not in normalized_symbols):
                        normalized = cls.normalize_symbol(symbol, market)
                        pairs[normalized['symbol']] = normalized
                        normalized_symbols.add(normalized['symbol'])

            return pairs
        except Exception as e:
            logger.warning(f"Erro ao carregar pares com metadata: {e}")
            fallback = ["BTC/USDT", "ETH/USDT", "XLM/USDT", "ADA/USDT", "SOL/USDT", "DOGE/USDT", "LTC/USDT", "AVAX/USDT"]
            return {symbol: cls.normalize_symbol(symbol) for symbol in fallback}

    @classmethod
    def get_trading_symbol(cls, display_symbol, exchange_name='okx'):
        pairs_metadata = cls.get_usdt_pairs_with_metadata(exchange_name)
        if display_symbol in pairs_metadata:
            metadata = pairs_metadata[display_symbol]
            return metadata['raw_symbol']
        return display_symbol

    @classmethod
    def test_connection(cls, exchange_name='binance'):
        try:
            import requests
            endpoints_test = [
                {'name': 'Binance API Spot', 'url': 'https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT'},
                {'name': 'Binance API Futures', 'url': 'https://fapi.binance.com/fapi/v1/ticker/price?symbol=BTCUSDT'},
                {'name': 'Binance US (Backup)', 'url': 'https://api.binance.us/api/v3/ticker/price?symbol=BTCUSDT'}
            ]
            working_endpoints = []

            for endpoint in endpoints_test:
                try:
                    response = requests.get(endpoint['url'], timeout=5)
                    if response.status_code == 200:
                        data = response.json()
                        if 'price' in data:
                            price = float(data['price'])
                            working_endpoints.append(f"✅ {endpoint['name']}: ${price:,.2f}")
                    else:
                        working_endpoints.append(f"⚠️ {endpoint['name']}: HTTP {response.status_code}")
                except Exception as e:
                    working_endpoints.append(f"❌ {endpoint['name']}: {str(e)[:30]}...")

            try:
                ws_test_response = requests.get('https://fstream.binance.com', timeout=5)
                ws_status = "✅ WebSocket endpoint disponível" if ws_test_response.status_code == 200 else f"⚠️ WebSocket: HTTP {ws_test_response.status_code}"
                working_endpoints.append(ws_status)
            except Exception:
                working_endpoints.append("❌ WebSocket endpoint não acessível")

            success_count = len([e for e in working_endpoints if e.startswith('✅')])
            if success_count > 0:
                result_msg = f"🌐 WebSocket Público da Binance: {success_count}/{len(endpoints_test)} endpoints funcionando\n"
                result_msg += "\n".join(working_endpoints)
                result_msg += "\n\n📡 Sistema configurado para usar dados públicos sem credenciais!"
                return True, result_msg
            else:
                result_msg = "❌ Nenhum endpoint público da Binance acessível:\n"
                result_msg += "\n".join(working_endpoints)
                return False, result_msg
        except Exception as e:
            return False, f"❌ Erro ao testar WebSocket público: {str(e)}"

    @classmethod
    def get_recommended_for_brazil(cls):
        return 'binance'

    @classmethod
    def get_binance_example_config(cls):
        return """
# === Configuração Binance Futuros ===
# Configure no Replit Secrets (🔒):
# 
# BINANCE_API_KEY = \"sua_api_key_aqui\"
# BINANCE_SECRET = \"seu_api_secret_aqui\"
#
# Exemplo de código:
import ccxt
import os

exchange = ccxt.binance({
    "apiKey": os.getenv('BINANCE_API_KEY'),
    "secret": os.getenv('BINANCE_SECRET'),
    "enableRateLimit": True,
    "options": {
        "defaultType": "future"
    }
})

try:
    markets = exchange.load_markets()
    balance = exchange.fetch_balance()
    print("✅ Binance conectada com sucesso!")
    print(f"Saldo USDT: {balance.get('USDT', {}).get('total', 0)}")
except Exception as e:
    print(f"❌ Erro: {e}")
"""


class TelegramBotConfig:
    MAX_ANALYSES_FREE = 1
    MAX_ANALYSES_PREMIUM = float('inf')
    MAX_ERRORS_PER_WINDOW = 5
    ERROR_WINDOW_SECONDS = 300
    RETRY_ATTEMPTS = 3
    RETRY_DELAY = 1
    AVAILABLE_COMMANDS = [
        "/start", "/help", "/analise", "/status",
        "/premium", "/admin", "/stats", "/users",
        "/upgrade", "/broadcast"
    ]
    SUPPORTED_PAIRS = [
        "BTC/USDT", "ETH/USDT", "XLM/USDT",
        "ADA/USDT", "DOT/USDT", "MATIC/USDT",
        "LINK/USDT", "UNI/USDT", "SOL/USDT"
    ]
    SIGNAL_EMOJIS = {
        "COMPRA": "🟢",
        "VENDA": "🔴",
        "COMPRA_FRACA": "🟡",
        "VENDA_FRACA": "🟠",
        "NEUTRO": "⚪"
    }

    @staticmethod
    def get_bot_token() -> Optional[str]:
        return ProductionConfig.TELEGRAM_BOT_TOKEN

    @staticmethod
    def get_chat_id() -> Optional[str]:
        return ProductionConfig.TELEGRAM_CHAT_ID

    @staticmethod
    def is_valid_pair(symbol: str) -> bool:
        return symbol.upper() in TelegramBotConfig.SUPPORTED_PAIRS

    @staticmethod
    def get_signal_emoji(signal: str) -> str:
        return TelegramBotConfig.SIGNAL_EMOJIS.get(signal, "⚪")


def _parse_admin_users(raw_value: str) -> list[int]:
    admin_users = []
    for user_id in raw_value.split(","):
        user_id = user_id.strip()
        if user_id.isdigit():
            admin_users.append(int(user_id))
    return admin_users or [1035830659]


def _parse_float_env(var_name: str, default: float) -> float:
    raw_value = os.getenv(var_name, "").strip()
    if not raw_value:
        return default

    try:
        return float(raw_value)
    except ValueError:
        logger.warning("Valor invalido para %s. Usando padrao %s", var_name, default)
        return default


class ProductionConfig:
    # Somente variáveis de ambiente (fonte única de verdade)
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    ADMIN_PANEL_PASSWORD = os.getenv("ADMIN_PANEL_PASSWORD", "").strip()
    ENABLE_DASHBOARD_BACKGROUND_BOT = os.getenv("ENABLE_DASHBOARD_BACKGROUND_BOT", "").strip().lower() in {"1", "true", "yes"}
    ENABLE_EDGE_GUARDRAIL = os.getenv("ENABLE_EDGE_GUARDRAIL", "true").strip().lower() in {"1", "true", "yes"}
    ENABLE_AI_SIGNAL_INFLUENCE = os.getenv("ENABLE_AI_SIGNAL_INFLUENCE", "false").strip().lower() in {"1", "true", "yes"}
    ENABLE_RISK_CIRCUIT_BREAKER = os.getenv("ENABLE_RISK_CIRCUIT_BREAKER", "true").strip().lower() in {"1", "true", "yes"}
    REDIS_URL = os.getenv("REDIS_URL", "").strip()
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
    PREMIUM_PRICE_MONTHLY = _parse_float_env("PREMIUM_PRICE_MONTHLY", 19.90)
    MIN_PAPER_TRADES_FOR_EDGE_VALIDATION = int(os.getenv("MIN_PAPER_TRADES_FOR_EDGE_VALIDATION", "30").strip() or "30")
    MIN_PAPER_TRADES_FOR_EDGE_GUARDRAIL = int(os.getenv("MIN_PAPER_TRADES_FOR_EDGE_GUARDRAIL", "30").strip() or "30")
    MIN_BACKTEST_TRADES_FOR_PROMOTION = int(os.getenv("MIN_BACKTEST_TRADES_FOR_PROMOTION", "10").strip() or "10")
    MIN_PROMOTION_PROFIT_FACTOR = _parse_float_env("MIN_PROMOTION_PROFIT_FACTOR", 1.20)
    MAX_PROMOTION_DRAWDOWN = _parse_float_env("MAX_PROMOTION_DRAWDOWN", 20.0)
    PAPER_ACCOUNT_BALANCE = _parse_float_env("PAPER_ACCOUNT_BALANCE", 10000.0)
    RISK_PER_TRADE_PCT = _parse_float_env("RISK_PER_TRADE_PCT", 0.5)
    MAX_OPEN_PAPER_TRADES = int(os.getenv("MAX_OPEN_PAPER_TRADES", "3").strip() or "3")
    MAX_PORTFOLIO_OPEN_RISK_PCT = _parse_float_env("MAX_PORTFOLIO_OPEN_RISK_PCT", 2.0)
    MAX_DAILY_PAPER_LOSS_PCT = _parse_float_env("MAX_DAILY_PAPER_LOSS_PCT", 2.0)
    MAX_CONSECUTIVE_PAPER_LOSSES = int(os.getenv("MAX_CONSECUTIVE_PAPER_LOSSES", "3").strip() or "3")
    DEFAULT_LIVE_STOP_LOSS_PCT = _parse_float_env("DEFAULT_LIVE_STOP_LOSS_PCT", 2.0)
    DEFAULT_LIVE_TAKE_PROFIT_PCT = _parse_float_env("DEFAULT_LIVE_TAKE_PROFIT_PCT", 4.0)

    # Lista separada por vírgula: ADMIN_USERS=123,456
    ADMIN_USERS: list = _parse_admin_users(os.getenv("ADMIN_USERS", "1035830659"))

    @classmethod
    def validate_config(cls) -> bool:
        if not cls.TELEGRAM_BOT_TOKEN:
            logger.error("❌ TELEGRAM_BOT_TOKEN não configurado")
            return False

        if not cls.TELEGRAM_CHAT_ID:
            logger.error("❌ TELEGRAM_CHAT_ID não configurado")
            return False

        if not cls.TELEGRAM_BOT_TOKEN.startswith(("1", "2", "5", "6", "7", "8", "9")):
            logger.error("❌ TELEGRAM_BOT_TOKEN formato inválido")
            return False

        logger.info("✅ Configurações validadas com sucesso")
        return True

    @classmethod
    def validate_polling_runtime_config(cls) -> bool:
        if not cls.TELEGRAM_BOT_TOKEN:
            logger.error("TELEGRAM_BOT_TOKEN nao configurado")
            return False

        if not cls.TELEGRAM_BOT_TOKEN.startswith(("1", "2", "5", "6", "7", "8", "9")):
            logger.error("TELEGRAM_BOT_TOKEN formato invalido")
            return False

        logger.info("Configuracoes do bot 24/7 validadas com sucesso")
        return True

    @classmethod
    def is_admin(cls, user_id: int) -> bool:
        return user_id in cls.ADMIN_USERS

    @classmethod
    def get_telegram_config(cls) -> dict:
        return {
            "bot_token": cls.TELEGRAM_BOT_TOKEN,
            "chat_id": cls.TELEGRAM_CHAT_ID
        }


class TimeFrame5mConfig:
    @staticmethod
    def get_optimized_settings():
        return {
            "rsi_period": 14,
            "rsi_oversold": 15,
            "rsi_overbought": 85,
            "min_confidence": 80,
            "min_volume_ratio": 2.5,
            "min_adx": 30,
            "max_atr_pct": 4,
            "max_bb_width": 0.12,
            "macd_fast": 8,
            "macd_slow": 21,
            "macd_signal": 5,
            "stoch_rsi_oversold": 10,
            "stoch_rsi_overbought": 90,
            "williams_r_oversold": -90,
            "williams_r_overbought": -10,
            "avoid_lunch_break": True,
            "only_peak_hours": True,
            "min_hold_candles": 3,
            "max_trades_per_hour": 2,
            "use_stop_loss": True,
            "stop_loss_pct": 2.0,
            "use_take_profit": True,
            "take_profit_pct": 4.0,
            "avoid_ranging_markets": True,
            "require_trending_market": True,
        }

    @staticmethod
    def get_conservative_5m():
        base = TimeFrame5mConfig.get_optimized_settings()
        return {
            **base,
            "rsi_oversold": 10,
            "rsi_overbought": 90,
            "min_confidence": 85,
            "min_volume_ratio": 3.0,
            "min_adx": 35,
            "max_trades_per_day": 5,
        }

    @staticmethod
    def apply_5m_filters(signal, row, current_hour=None):
        settings = TimeFrame5mConfig.get_optimized_settings()

        if current_hour is not None and settings["only_peak_hours"]:
            if settings["avoid_lunch_break"] and 12 <= current_hour <= 14:
                return "NEUTRO"
            if not (9 <= current_hour <= 11 or 14 <= current_hour <= 16 or 20 <= current_hour <= 22):
                return "NEUTRO"

        if signal in ['COMPRA_FRACA', 'VENDA_FRACA']:
            return "NEUTRO"

        rsi = row.get('rsi', 50)
        volume_ratio = row.get('volume_ratio', 1)
        adx = row.get('adx', 0)

        if signal == 'COMPRA' and rsi > settings["rsi_oversold"]:
            return "NEUTRO"
        if signal == 'VENDA' and rsi < settings["rsi_overbought"]:
            return "NEUTRO"
        if volume_ratio < settings["min_volume_ratio"]:
            return "NEUTRO"
        if adx < settings["min_adx"]:
            return "NEUTRO"

        return signal
