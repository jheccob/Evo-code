import importlib
import os
import logging
from typing import Iterable, Optional
from market_state_engine import market_states_to_setup_allowlist, normalize_setup_collection

logger = logging.getLogger(__name__)


def _load_ccxt():
    return importlib.import_module("ccxt")


def _get_default_db_path() -> str:
    explicit_path = os.getenv("TRADING_BOT_DB_PATH", "").strip()
    if explicit_path:
        return explicit_path

    railway_volume_mount = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    if railway_volume_mount:
        return f"{railway_volume_mount.rstrip('/')}/trading_bot.db"

    return "data/trading_bot.db"

class AppConfig:
    # Trading parameters - single-setup mode for robust OOS validation
    SINGLE_SETUP_MODE = True
    PRIMARY_SYMBOL = "BTC/USDT"
    PRIMARY_TIMEFRAME = "15m"
    PRIMARY_CONTEXT_TIMEFRAME = "1h"
    DEFAULT_BACKTEST_PRESET = "Perfil Global Base (15m)"
    DEFAULT_BACKTEST_WINDOW_DAYS = 30
    DEFAULT_BACKTEST_PRESET_SUMMARY = (
        "Perfil global base: 15m + contexto 1h, motor EMA/RSI nos dois lados, "
        "risco balanceado e validacao temporal ligada. Use como baseline transversal."
    )
    DEFAULT_BACKTEST_PRESET_NOTE = (
        "Preset global base do motor EMA/RSI. Ele serve como ponto de partida compartilhado; "
        "a promocao real continua dependendo de validacao por familia."
    )
    VALIDATED_BACKTEST_SUMMARY = DEFAULT_BACKTEST_PRESET_SUMMARY
    DEFAULT_SYMBOL = PRIMARY_SYMBOL
    DEFAULT_TIMEFRAME = PRIMARY_TIMEFRAME
    DEFAULT_RSI_PERIOD = 14
    DEFAULT_RSI_MIN = 54
    DEFAULT_RSI_MAX = 47

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
    SIMPLE_TREND_SIGNAL_MODE = True
    ENABLE_PARAMETER_OPTIMIZATION = False
    ENABLE_MARKET_SCAN = False
    MULTI_TIMEFRAME_CONTEXT_MAP = {
        "5m": "15m",
        "15m": "1h",
        "30m": "4h",
        "1h": "4h",
        "4h": "1d",
    }
    BACKTEST_SETUP_FOCUS_LABELS = {
        "ema_rsi_resume_long": "EMA/RSI Long",
        "ema_rsi_resume_short": "EMA/RSI Short",
    }
    SYMBOL_PROFILE_FAMILIES = {
        "BTC/USDT": "majors",
        "ETH/USDT": "majors",
        "SOL/USDT": "trend_alts",
        "AVAX/USDT": "trend_alts",
        "LINK/USDT": "trend_alts",
        "ADA/USDT": "broad_alts",
        "DOT/USDT": "broad_alts",
        "MATIC/USDT": "broad_alts",
        "UNI/USDT": "broad_alts",
        "XLM/USDT": "broad_alts",
    }
    SYMBOL_PROFILE_FAMILY_LABELS = {
        "majors": "Majors",
        "trend_alts": "Trend Alts",
        "broad_alts": "Broad Alts",
        "global": "Global",
    }
    BACKTEST_FAMILY_PROFILE_OVERRIDES = {
        "global": {
            "label": "Global",
            "description": "Usa o perfil global base sem ajustes adicionais.",
            "overrides": {},
        },
        "majors": {
            "label": "Majors",
            "description": "BTC e ETH tendem a aceitar o baseline global com menos atrito estrutural.",
            "overrides": {},
        },
        "trend_alts": {
            "label": "Trend Alts",
            "description": "Altcoins de impulso costumam responder melhor com filtro estrutural extra.",
            "overrides": {
                "bt_enable_trend_filter": True,
                "bt_enable_avoid_ranging": True,
                "bt_stop_loss_pct": 0.9,
                "bt_take_profit_pct": 2.0,
            },
        },
        "broad_alts": {
            "label": "Broad Alts",
            "description": "Altcoins mais irregulares pedem filtros extras e risco um pouco mais disciplinado.",
            "overrides": {
                "bt_enable_volume_filter": True,
                "bt_enable_trend_filter": True,
                "bt_enable_avoid_ranging": True,
                "bt_risk_profile": "conservative",
                "bt_stop_loss_pct": 1.0,
                "bt_take_profit_pct": 2.0,
            },
        },
    }
    BACKTEST_RUNTIME_OVERRIDE_KEY_MAP = {
        "bt_enable_volume_filter": "require_volume",
        "bt_enable_trend_filter": "require_trend",
        "bt_enable_avoid_ranging": "avoid_ranging",
        "bt_stop_loss_pct": "stop_loss_pct",
        "bt_take_profit_pct": "take_profit_pct",
    }
    GLOBAL_VALIDATION_SYMBOLS = (
        "BTC/USDT",
        "ETH/USDT",
        "SOL/USDT",
        "AVAX/USDT",
        "LINK/USDT",
        "ADA/USDT",
        "DOT/USDT",
        "MATIC/USDT",
        "UNI/USDT",
        "XLM/USDT",
    )
    GLOBAL_VALIDATION_HORIZONS_DAYS = (30, 90, 180, 365)

    @classmethod
    def get_supported_pairs(cls):
        supported_pairs = [
            cls.PRIMARY_SYMBOL,
            "ETH/USDT",
            "XLM/USDT",
            "ADA/USDT",
            "DOT/USDT",
            "MATIC/USDT",
            "LINK/USDT",
            "UNI/USDT",
            "SOL/USDT",
            "AVAX/USDT",
        ]
        return list(dict.fromkeys(pair for pair in supported_pairs if pair))

    @classmethod
    def get_supported_timeframes(cls):
        if cls.SINGLE_SETUP_MODE:
            ordered = [cls.PRIMARY_TIMEFRAME, cls.PRIMARY_CONTEXT_TIMEFRAME]
            return list(dict.fromkeys(timeframe for timeframe in ordered if timeframe))
        return ["5m", "15m", "30m", "1h", "4h", "1d"]

    @classmethod
    def get_context_timeframe(cls, timeframe: Optional[str]) -> Optional[str]:
        if not timeframe:
            return None
        context_timeframe = cls.MULTI_TIMEFRAME_CONTEXT_MAP.get(timeframe)
        if not context_timeframe or context_timeframe == timeframe:
            return None
        return context_timeframe

    @classmethod
    def get_backtest_setup_focus_labels(cls) -> dict[str, str]:
        return dict(cls.BACKTEST_SETUP_FOCUS_LABELS)

    @classmethod
    def get_market_reading_family_configs(cls) -> dict[str, dict[str, object]]:
        setup_focus_labels = cls.get_backtest_setup_focus_labels()
        return {
            "all_states": {
                "label": "Ambos os lados",
                "description": "Opera compra e venda com o motor mecanico EMA/RSI.",
                "allowed_setups": list(setup_focus_labels.keys()),
            },
            "long_only": {
                "label": "Somente compra",
                "description": "Limita o motor mecanico ao lado comprador.",
                "allowed_setups": ["ema_rsi_resume_long"],
            },
            "short_only": {
                "label": "Somente venda",
                "description": "Limita o motor mecanico ao lado vendedor.",
                "allowed_setups": ["ema_rsi_resume_short"],
            },
        }

    @classmethod
    def get_risk_profile_configs(cls) -> dict[str, dict[str, object]]:
        return {
            "manual": {
                "label": "Manual",
                "description": "Mantem SL/TP exatamente como voce definir.",
            },
            "conservative": {
                "label": "Conservador",
                "description": "Menor frequencia e alvo mais estavel.",
                "stop_loss_pct": 1.0,
                "take_profit_pct": 2.0,
            },
            "balanced": {
                "label": "Balanceado",
                "description": "Relacao risco/retorno padrao para operar continuamente.",
                "stop_loss_pct": 0.8,
                "take_profit_pct": 1.8,
            },
            "aggressive": {
                "label": "Agressivo",
                "description": "Stop mais curto e alvo mais longo para throughput maior.",
                "stop_loss_pct": 0.7,
                "take_profit_pct": 2.2,
            },
        }

    @classmethod
    def get_backtest_setup_presets(cls) -> dict[str, Optional[dict[str, object]]]:
        setup_focus_labels = cls.get_backtest_setup_focus_labels()
        return {
            "Manual": None,
            "Leitura Conservadora (1h)": {
                "bt_timeframe": "1h",
                "bt_context_mode": "same_timeframe",
                "bt_market_family": "all_states",
                "bt_setup_focus": list(setup_focus_labels.keys()),
                "bt_risk_profile": "conservative",
                "bt_rsi_period": 14,
                "bt_rsi_min": 50,
                "bt_rsi_max": 50,
                "bt_enable_volume_filter": True,
                "bt_enable_trend_filter": True,
                "bt_enable_avoid_ranging": True,
                "bt_stop_loss_pct": 1.5,
                "bt_take_profit_pct": 3.0,
                "bt_enable_oos_validation": True,
                "bt_validation_split_pct": 30,
                "bt_enable_walk_forward": True,
                "bt_walk_forward_windows": 3,
            },
            cls.DEFAULT_BACKTEST_PRESET: {
                "bt_timeframe": "15m",
                "bt_context_mode": cls.PRIMARY_CONTEXT_TIMEFRAME,
                "bt_market_family": "all_states",
                "bt_setup_focus": list(setup_focus_labels.keys()),
                "bt_risk_profile": "balanced",
                "bt_rsi_period": 14,
                "bt_rsi_min": 54,
                "bt_rsi_max": 47,
                "bt_enable_volume_filter": False,
                "bt_enable_trend_filter": False,
                "bt_enable_avoid_ranging": False,
                "bt_stop_loss_pct": 0.8,
                "bt_take_profit_pct": 1.8,
                "bt_enable_oos_validation": True,
                "bt_validation_split_pct": 30,
                "bt_enable_walk_forward": True,
                "bt_walk_forward_windows": 3,
            },
            "Leitura Ativa (15m)": {
                "bt_timeframe": "15m",
                "bt_context_mode": "same_timeframe",
                "bt_market_family": "all_states",
                "bt_setup_focus": list(setup_focus_labels.keys()),
                "bt_risk_profile": "aggressive",
                "bt_rsi_period": 14,
                "bt_rsi_min": 54,
                "bt_rsi_max": 46,
                "bt_enable_volume_filter": False,
                "bt_enable_trend_filter": True,
                "bt_enable_avoid_ranging": True,
                "bt_stop_loss_pct": 0.7,
                "bt_take_profit_pct": 2.2,
                "bt_enable_oos_validation": True,
                "bt_validation_split_pct": 30,
                "bt_enable_walk_forward": True,
                "bt_walk_forward_windows": 3,
            },
        }

    @classmethod
    def get_backtest_preset_notes(cls) -> dict[str, str]:
        return {
            "Manual": "Sem sobrescrever os campos atuais.",
            "Leitura Conservadora (1h)": "Prioriza leitura limpa e menor ruido operacional.",
            cls.DEFAULT_BACKTEST_PRESET: cls.DEFAULT_BACKTEST_PRESET_NOTE,
            "Leitura Ativa (15m)": "Busca mais fluxo operacional, aceitando mais ruido e variacao.",
        }

    @classmethod
    def get_backtest_family_profile_overlays(cls) -> dict[str, dict[str, object]]:
        overlays: dict[str, dict[str, object]] = {}
        for family_key, payload in cls.BACKTEST_FAMILY_PROFILE_OVERRIDES.items():
            overlays[family_key] = {
                "label": payload.get("label"),
                "description": payload.get("description"),
                "overrides": dict(payload.get("overrides") or {}),
            }
        return overlays

    @classmethod
    def get_symbol_profile_family(cls, symbol: Optional[str]) -> str:
        normalized_symbol = str(symbol or "").strip().upper()
        return cls.SYMBOL_PROFILE_FAMILIES.get(normalized_symbol, "global")

    @classmethod
    def get_symbol_profile_family_label(cls, symbol: Optional[str]) -> str:
        family_key = cls.get_symbol_profile_family(symbol)
        return cls.SYMBOL_PROFILE_FAMILY_LABELS.get(family_key, "Global")

    @classmethod
    def get_backtest_family_profile(cls, symbol: Optional[str]) -> dict[str, object]:
        family_key = cls.get_symbol_profile_family(symbol)
        overlays = cls.get_backtest_family_profile_overlays()
        payload = overlays.get(family_key) or overlays["global"]
        return {
            "family_key": family_key,
            "label": payload.get("label") or cls.get_symbol_profile_family_label(symbol),
            "description": payload.get("description") or "",
            "overrides": dict(payload.get("overrides") or {}),
        }

    @classmethod
    def get_backtest_family_runtime_overrides(cls, symbol: Optional[str]) -> dict[str, object]:
        overlay_updates = cls.get_backtest_family_profile(symbol).get("overrides") or {}
        runtime_overrides: dict[str, object] = {}
        for session_key, runtime_key in cls.BACKTEST_RUNTIME_OVERRIDE_KEY_MAP.items():
            if session_key in overlay_updates:
                runtime_overrides[runtime_key] = overlay_updates[session_key]
        return runtime_overrides

    @classmethod
    def get_backtest_preset_updates(
        cls,
        preset_name: str,
        symbol: Optional[str] = None,
        include_family_overlay: bool = False,
    ) -> dict[str, object]:
        preset_updates = dict(cls.get_backtest_setup_presets().get(preset_name) or {})
        if include_family_overlay:
            family_profile = cls.get_backtest_family_profile(symbol)
            preset_updates.update(family_profile.get("overrides") or {})
        return preset_updates

    @classmethod
    def get_global_validation_symbols(cls) -> list[str]:
        supported_pairs = set(cls.get_supported_pairs())
        return [
            symbol
            for symbol in cls.GLOBAL_VALIDATION_SYMBOLS
            if symbol in supported_pairs
        ]

    @classmethod
    def get_global_validation_horizons(cls) -> list[int]:
        return sorted({int(days) for days in cls.GLOBAL_VALIDATION_HORIZONS_DAYS if int(days) > 0})

    @classmethod
    def get_runtime_allowed_execution_setups(
        cls,
        timeframe: Optional[str],
        promoted_setup_type: Optional[str] = None,
        promoted_setup_types: Optional[Iterable[str]] = None,
        promoted_market_states: Optional[Iterable[str]] = None,
    ) -> Optional[list[str]]:
        raw_allowlist = os.getenv("RUNTIME_ALLOWED_EXECUTION_SETUPS", "").strip()
        if raw_allowlist:
            parsed = [item.strip().lower() for item in raw_allowlist.split(",") if item.strip()]
            normalized = normalize_setup_collection(parsed)
            return normalized or None

        derived_from_market_states = market_states_to_setup_allowlist(promoted_market_states)
        if derived_from_market_states:
            return derived_from_market_states

        normalized_setups = normalize_setup_collection(promoted_setup_types)
        if normalized_setups:
            return normalized_setups

        normalized_setup = normalize_setup_collection([promoted_setup_type])
        if normalized_setup:
            return normalized_setup
        return None

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
            "15m": {"rsi_oversold": 52, "rsi_overbought": 47, "min_confidence": 68, "min_volume_ratio": 1.0, "volatility_filter": 0.06, "rsi_period": 14},
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
            "15m": {"rsi_period": 14, "rsi_oversold": 52, "rsi_overbought": 47, "min_confidence": 68, "min_volume_ratio": 1.0, "volatility_filter": 0.07, "macd_fast": 12, "macd_slow": 26, "macd_signal": 9, "stoch_rsi_extreme": {"low": 20, "high": 80}, "williams_r_extreme": {"low": -80, "high": -20}, "min_adx": 20, "bb_squeeze_threshold": 0.09, "time_filters": {"avoid_lunch": False, "peak_hours_only": True}}
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

        ccxt = _load_ccxt()
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
    return admin_users


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
    ENABLE_TELEGRAM_SIGNAL_SCANNER = os.getenv("ENABLE_TELEGRAM_SIGNAL_SCANNER", "true").strip().lower() in {"1", "true", "yes"}
    TELEGRAM_SIGNAL_SCAN_INTERVAL_SECONDS = max(15, int(os.getenv("TELEGRAM_SIGNAL_SCAN_INTERVAL_SECONDS", "60").strip() or "60"))
    TELEGRAM_SIGNAL_SCAN_TIMEFRAME = os.getenv("TELEGRAM_SIGNAL_SCAN_TIMEFRAME", AppConfig.PRIMARY_TIMEFRAME).strip() or AppConfig.PRIMARY_TIMEFRAME
    TELEGRAM_SIGNAL_SCAN_SYMBOLS = os.getenv("TELEGRAM_SIGNAL_SCAN_SYMBOLS", "").strip()
    TELEGRAM_SIGNAL_QUEUE_BATCH_SIZE = max(1, int(os.getenv("TELEGRAM_SIGNAL_QUEUE_BATCH_SIZE", "25").strip() or "25"))
    ADMIN_PANEL_PASSWORD = os.getenv("ADMIN_PANEL_PASSWORD", "").strip()
    ENABLE_DASHBOARD_BACKGROUND_BOT = os.getenv("ENABLE_DASHBOARD_BACKGROUND_BOT", "").strip().lower() in {"1", "true", "yes"}
    ENABLE_EDGE_GUARDRAIL = os.getenv("ENABLE_EDGE_GUARDRAIL", "true").strip().lower() in {"1", "true", "yes"}
    ENABLE_AI_SIGNAL_INFLUENCE = os.getenv("ENABLE_AI_SIGNAL_INFLUENCE", "false").strip().lower() in {"1", "true", "yes"}
    ENABLE_RISK_CIRCUIT_BREAKER = os.getenv("ENABLE_RISK_CIRCUIT_BREAKER", "true").strip().lower() in {"1", "true", "yes"}
    ENABLE_LIVE_EXECUTION = os.getenv("ENABLE_LIVE_EXECUTION", "false").strip().lower() in {"1", "true", "yes"}
    ENABLE_MULTIUSER_RUNTIME = os.getenv("ENABLE_MULTIUSER_RUNTIME", "false").strip().lower() in {"1", "true", "yes"}
    ENABLE_MULTIUSER_AUTO_ORDER_EXECUTION = os.getenv(
        "ENABLE_MULTIUSER_AUTO_ORDER_EXECUTION",
        "false",
    ).strip().lower() in {"1", "true", "yes"}
    REQUIRE_MULTIUSER_VALID_TOKEN = os.getenv("REQUIRE_MULTIUSER_VALID_TOKEN", "true").strip().lower() in {"1", "true", "yes"}
    REQUIRE_MULTIUSER_VALID_PERMISSIONS = os.getenv("REQUIRE_MULTIUSER_VALID_PERMISSIONS", "true").strip().lower() in {"1", "true", "yes"}
    REQUIRE_MULTIUSER_RECONCILIATION_OK = os.getenv("REQUIRE_MULTIUSER_RECONCILIATION_OK", "true").strip().lower() in {"1", "true", "yes"}
    DASHBOARD_USER_SESSION_TIMEOUT_HOURS = max(
        1,
        int(os.getenv("DASHBOARD_USER_SESSION_TIMEOUT_HOURS", "12").strip() or "12"),
    )
    DASHBOARD_MIN_PASSWORD_LENGTH = max(
        10,
        int(os.getenv("DASHBOARD_MIN_PASSWORD_LENGTH", "10").strip() or "10"),
    )
    CREDENTIAL_ENCRYPTION_KEY = os.getenv("CREDENTIAL_ENCRYPTION_KEY", "").strip()
    REQUIRE_APPROVED_GOVERNANCE_FOR_LIVE = os.getenv("REQUIRE_APPROVED_GOVERNANCE_FOR_LIVE", "true").strip().lower() in {"1", "true", "yes"}
    REDIS_URL = os.getenv("REDIS_URL", "").strip()
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
    PUBLIC_APP_URL = os.getenv("PUBLIC_APP_URL", "").strip().rstrip("/")
    STRIPE_SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL", "").strip() or (
        f"{PUBLIC_APP_URL}/success" if PUBLIC_APP_URL else ""
    )
    STRIPE_CANCEL_URL = os.getenv("STRIPE_CANCEL_URL", "").strip() or (
        f"{PUBLIC_APP_URL}/cancel" if PUBLIC_APP_URL else ""
    )
    PREMIUM_PRICE_MONTHLY = _parse_float_env("PREMIUM_PRICE_MONTHLY", 19.90)
    MIN_PAPER_TRADES_FOR_EDGE_VALIDATION = int(os.getenv("MIN_PAPER_TRADES_FOR_EDGE_VALIDATION", "30").strip() or "30")
    MIN_PAPER_TRADES_FOR_EDGE_GUARDRAIL = int(os.getenv("MIN_PAPER_TRADES_FOR_EDGE_GUARDRAIL", "30").strip() or "30")
    MIN_BACKTEST_TRADES_FOR_PROMOTION = int(os.getenv("MIN_BACKTEST_TRADES_FOR_PROMOTION", "50").strip() or "50")
    MIN_PROMOTION_SETUP_TRADES = int(
        os.getenv("MIN_PROMOTION_SETUP_TRADES", str(MIN_BACKTEST_TRADES_FOR_PROMOTION)).strip()
        or str(MIN_BACKTEST_TRADES_FOR_PROMOTION)
    )
    MIN_PROMOTION_PERIOD_DAYS = int(os.getenv("MIN_PROMOTION_PERIOD_DAYS", "30").strip() or "30")
    MIN_PROMOTION_PROFIT_FACTOR = _parse_float_env("MIN_PROMOTION_PROFIT_FACTOR", 1.20)
    MIN_PROMOTION_EXPECTANCY_PCT = _parse_float_env("MIN_PROMOTION_EXPECTANCY_PCT", 0.03)
    MIN_PROMOTION_OOS_TRADES = int(os.getenv("MIN_PROMOTION_OOS_TRADES", "15").strip() or "15")
    MIN_PROMOTION_OOS_PROFIT_FACTOR = _parse_float_env("MIN_PROMOTION_OOS_PROFIT_FACTOR", 1.10)
    MIN_PROMOTION_OOS_EXPECTANCY_PCT = _parse_float_env("MIN_PROMOTION_OOS_EXPECTANCY_PCT", 0.0)
    MAX_PROMOTION_DRAWDOWN = _parse_float_env("MAX_PROMOTION_DRAWDOWN", 18.0)
    PAPER_ACCOUNT_BALANCE = _parse_float_env("PAPER_ACCOUNT_BALANCE", 10000.0)
    RISK_PER_TRADE_PCT = _parse_float_env("RISK_PER_TRADE_PCT", 0.5)
    MAX_OPEN_PAPER_TRADES = int(os.getenv("MAX_OPEN_PAPER_TRADES", "3").strip() or "3")
    MAX_OPEN_PAPER_TRADES_PER_SYMBOL = int(os.getenv("MAX_OPEN_PAPER_TRADES_PER_SYMBOL", "1").strip() or "1")
    MAX_PORTFOLIO_OPEN_RISK_PCT = _parse_float_env("MAX_PORTFOLIO_OPEN_RISK_PCT", 2.0)
    MAX_DAILY_PAPER_LOSS_PCT = _parse_float_env("MAX_DAILY_PAPER_LOSS_PCT", 2.0)
    MAX_CONSECUTIVE_PAPER_LOSSES = int(os.getenv("MAX_CONSECUTIVE_PAPER_LOSSES", "5").strip() or "5")
    RISK_STREAK_REDUCTION_THRESHOLD = int(os.getenv("RISK_STREAK_REDUCTION_THRESHOLD", "3").strip() or "3")
    RISK_DRAWDOWN_WARNING_PCT = _parse_float_env("RISK_DRAWDOWN_WARNING_PCT", 5.0)
    RISK_DRAWDOWN_BLOCK_PCT = _parse_float_env("RISK_DRAWDOWN_BLOCK_PCT", 10.0)
    RISK_REDUCED_MODE_MULTIPLIER = _parse_float_env("RISK_REDUCED_MODE_MULTIPLIER", 0.5)
    MIN_LIVE_QUALITY_SCORE = _parse_float_env("MIN_LIVE_QUALITY_SCORE", 60.0)
    BINANCE_FUTURES_TESTNET = os.getenv("BINANCE_FUTURES_TESTNET", "true").strip().lower() in {"1", "true", "yes"}
    BINANCE_FUTURES_ENTRY_RESPONSE_TYPE = (
        os.getenv("BINANCE_FUTURES_ENTRY_RESPONSE_TYPE", "RESULT").strip().upper() or "RESULT"
    )
    BINANCE_FUTURES_WORKING_TYPE = os.getenv("BINANCE_FUTURES_WORKING_TYPE", "MARK_PRICE").strip().upper() or "MARK_PRICE"
    BINANCE_FUTURES_PRICE_PROTECT = os.getenv("BINANCE_FUTURES_PRICE_PROTECT", "true").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    BINANCE_FUTURES_REQUIRE_PROTECTION = os.getenv(
        "BINANCE_FUTURES_REQUIRE_PROTECTION",
        "true",
    ).strip().lower() in {"1", "true", "yes"}
    BINANCE_FUTURES_RECONCILIATION_FETCH_LIMIT = max(
        5,
        int(os.getenv("BINANCE_FUTURES_RECONCILIATION_FETCH_LIMIT", "20").strip() or "20"),
    )
    BINANCE_USER_STREAM_KEEPALIVE_SECONDS = max(
        300,
        int(os.getenv("BINANCE_USER_STREAM_KEEPALIVE_SECONDS", "1800").strip() or "1800"),
    )
    BINANCE_USER_STREAM_RECONNECT_SECONDS = max(
        3600,
        int(os.getenv("BINANCE_USER_STREAM_RECONNECT_SECONDS", "82800").strip() or "82800"),
    )
    BINANCE_USER_STREAM_MAINNET_WS_URL = (
        os.getenv("BINANCE_USER_STREAM_MAINNET_WS_URL", "wss://fstream.binance.com/ws").strip().rstrip("/")
    )
    BINANCE_USER_STREAM_TESTNET_WS_URL = (
        os.getenv("BINANCE_USER_STREAM_TESTNET_WS_URL", "wss://stream.binancefuture.com/ws").strip().rstrip("/")
    )
    BINANCE_FUTURES_RUNTIME_STATE_PATH = (
        os.getenv("BINANCE_FUTURES_RUNTIME_STATE_PATH", "data/binance_futures_runtime_state.json").strip()
        or "data/binance_futures_runtime_state.json"
    )
    BINANCE_RUNTIME_AUTO_RECOVER_PROTECTION = os.getenv(
        "BINANCE_RUNTIME_AUTO_RECOVER_PROTECTION",
        "true",
    ).strip().lower() in {"1", "true", "yes"}
    BINANCE_RUNTIME_RECOVERY_COOLDOWN_SECONDS = max(
        1,
        int(os.getenv("BINANCE_RUNTIME_RECOVERY_COOLDOWN_SECONDS", "5").strip() or "5"),
    )
    PAPER_FEE_RATE = _parse_float_env("PAPER_FEE_RATE", 0.001)
    PAPER_SLIPPAGE = _parse_float_env("PAPER_SLIPPAGE", 0.0005)
    REQUIRE_ACTIVE_PROFILE_FOR_RUNTIME = os.getenv("REQUIRE_ACTIVE_PROFILE_FOR_RUNTIME", "true").strip().lower() in {"1", "true", "yes"}
    DEFAULT_LIVE_STOP_LOSS_PCT = _parse_float_env("DEFAULT_LIVE_STOP_LOSS_PCT", 0.8)
    DEFAULT_LIVE_TAKE_PROFIT_PCT = _parse_float_env("DEFAULT_LIVE_TAKE_PROFIT_PCT", 1.8)
    ENABLE_DYNAMIC_POSITION_MANAGEMENT = os.getenv("ENABLE_DYNAMIC_POSITION_MANAGEMENT", "true").strip().lower() in {"1", "true", "yes"}
    BREAK_EVEN_TRIGGER_R = _parse_float_env("BREAK_EVEN_TRIGGER_R", 1.0)
    TRAILING_TRIGGER_R = _parse_float_env("TRAILING_TRIGGER_R", 2.0)
    TRAILING_ATR_MULTIPLIER = _parse_float_env("TRAILING_ATR_MULTIPLIER", 1.8)
    HIGH_VOL_TRAILING_ATR_MULTIPLIER = _parse_float_env("HIGH_VOL_TRAILING_ATR_MULTIPLIER", 1.4)
    PARABOLIC_TRAILING_ATR_MULTIPLIER = _parse_float_env("PARABOLIC_TRAILING_ATR_MULTIPLIER", 1.2)
    STRUCTURE_EXIT_MIN_R = _parse_float_env("STRUCTURE_EXIT_MIN_R", 0.8)
    CONTINUATION_FAST_MANAGEMENT_ENABLED = os.getenv("CONTINUATION_FAST_MANAGEMENT_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
    LOWER_TIMEFRAME_CONTINUATION_BREAK_EVEN_TRIGGER_R = _parse_float_env("LOWER_TIMEFRAME_CONTINUATION_BREAK_EVEN_TRIGGER_R", 0.75)
    LOWER_TIMEFRAME_CONTINUATION_TRAILING_TRIGGER_R = _parse_float_env("LOWER_TIMEFRAME_CONTINUATION_TRAILING_TRIGGER_R", 1.25)
    LOWER_TIMEFRAME_CONTINUATION_TIME_STOP_CANDLES = int(
        os.getenv("LOWER_TIMEFRAME_CONTINUATION_TIME_STOP_CANDLES", "18").strip() or "18"
    )
    LOWER_TIMEFRAME_CONTINUATION_TIME_STOP_MAX_CLOSE_R = _parse_float_env(
        "LOWER_TIMEFRAME_CONTINUATION_TIME_STOP_MAX_CLOSE_R",
        0.35,
    )
    MIN_WALK_FORWARD_PASS_RATE_PCT = _parse_float_env("MIN_WALK_FORWARD_PASS_RATE_PCT", 60.0)
    MIN_WALK_FORWARD_OOS_PROFIT_FACTOR = _parse_float_env("MIN_WALK_FORWARD_OOS_PROFIT_FACTOR", 1.10)
    MAX_STATISTICAL_PROFIT_FACTOR = _parse_float_env("MAX_STATISTICAL_PROFIT_FACTOR", 5.0)
    GOVERNANCE_LOOKBACK_DAYS = int(os.getenv("GOVERNANCE_LOOKBACK_DAYS", "90").strip() or "90")
    GOVERNANCE_LOOKBACK_TRADES = int(os.getenv("GOVERNANCE_LOOKBACK_TRADES", "30").strip() or "30")
    GOVERNANCE_MIN_REGIME_TRADES = int(os.getenv("GOVERNANCE_MIN_REGIME_TRADES", "6").strip() or "6")
    GOVERNANCE_MIN_ALIGNMENT_TRADES = int(os.getenv("GOVERNANCE_MIN_ALIGNMENT_TRADES", "8").strip() or "8")
    GOVERNANCE_APPROVED_PF = _parse_float_env("GOVERNANCE_APPROVED_PF", MIN_PROMOTION_PROFIT_FACTOR)
    GOVERNANCE_REDUCED_PF = _parse_float_env("GOVERNANCE_REDUCED_PF", 1.0)
    GOVERNANCE_MIN_EXPECTANCY_PCT = _parse_float_env("GOVERNANCE_MIN_EXPECTANCY_PCT", 0.0)
    GOVERNANCE_ALIGNMENT_WARNING_PF_MULTIPLIER = _parse_float_env("GOVERNANCE_ALIGNMENT_WARNING_PF_MULTIPLIER", 0.85)
    GOVERNANCE_ALIGNMENT_BROKEN_PF_MULTIPLIER = _parse_float_env("GOVERNANCE_ALIGNMENT_BROKEN_PF_MULTIPLIER", 0.70)
    GOVERNANCE_ALIGNMENT_WARNING_EXPECTANCY_MULTIPLIER = _parse_float_env("GOVERNANCE_ALIGNMENT_WARNING_EXPECTANCY_MULTIPLIER", 0.75)
    GOVERNANCE_ALIGNMENT_BROKEN_EXPECTANCY_MULTIPLIER = _parse_float_env("GOVERNANCE_ALIGNMENT_BROKEN_EXPECTANCY_MULTIPLIER", 0.45)
    GOVERNANCE_ALIGNMENT_WARNING_WINRATE_GAP = _parse_float_env("GOVERNANCE_ALIGNMENT_WARNING_WINRATE_GAP", 8.0)
    GOVERNANCE_ALIGNMENT_BROKEN_WINRATE_GAP = _parse_float_env("GOVERNANCE_ALIGNMENT_BROKEN_WINRATE_GAP", 15.0)
    GOVERNANCE_REDUCED_SIZE_MULTIPLIER = _parse_float_env("GOVERNANCE_REDUCED_SIZE_MULTIPLIER", 0.75)
    GOVERNANCE_MAX_PROFIT_GIVEBACK_WARNING_PCT = _parse_float_env("GOVERNANCE_MAX_PROFIT_GIVEBACK_WARNING_PCT", 55.0)
    GOVERNANCE_MAX_PROFIT_GIVEBACK_BLOCK_PCT = _parse_float_env("GOVERNANCE_MAX_PROFIT_GIVEBACK_BLOCK_PCT", 75.0)

    # Lista separada por vírgula: ADMIN_USERS=123,456
    ADMIN_USERS: list = _parse_admin_users(os.getenv("ADMIN_USERS", ""))

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
