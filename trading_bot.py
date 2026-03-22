import inspect
import pandas as pd
import numpy as np
import logging
from datetime import datetime
from typing import Dict, Optional
from indicators import TechnicalIndicators
from config import AppConfig, ProductionConfig

logger = logging.getLogger(__name__)
ACTIONABLE_SIGNALS = {"COMPRA", "VENDA", "COMPRA_FRACA", "VENDA_FRACA"}
TREND_STRUCTURE_STATES = {"continuation", "continuation_weak_but_valid", "pullback", "breakout"}
CONTINUATION_STRUCTURE_STATES = {"continuation", "continuation_weak_but_valid"}

class TradingBot:
    def __init__(self, allow_simulated_data=False):
        # Usar sempre Binance WebSocket público
        from config import ExchangeConfig
        self.exchange = ExchangeConfig.get_exchange_instance('binance', testnet=False)
        self.exchange_name = 'binance'
        self.symbol = AppConfig.DEFAULT_SYMBOL
        self.timeframe = AppConfig.DEFAULT_TIMEFRAME
        self.rsi_period = AppConfig.DEFAULT_RSI_PERIOD
        self.rsi_min = AppConfig.DEFAULT_RSI_MIN
        self.rsi_max = AppConfig.DEFAULT_RSI_MAX
        self.allow_simulated_data = allow_simulated_data
        self.indicators = TechnicalIndicators()
        self._stream_clients = {}
        self._last_context_evaluation = None
        self._last_regime_evaluation = None
        self._last_price_structure_evaluation = None
        self._last_confirmation_evaluation = None
        self._last_entry_quality_evaluation = None
        self._last_scenario_evaluation = None
        self._last_trade_decision = None
        self._last_hard_block_evaluation = None
        self._last_candidate_signal = "NEUTRO"
        self._last_signal_pipeline = None

        logger.info("🚀 TradingBot inicializado com BINANCE WEBSOCKET PÚBLICO")
        logger.info("📡 Usando dados em tempo real sem necessidade de credenciais")

    @staticmethod
    def _calculate_context_slope(series: pd.Series, lookback: int = 5) -> float:
        if series is None:
            return float("nan")

        clean_series = series.dropna()
        if len(clean_series) < 2:
            return float("nan")

        effective_lookback = min(lookback, len(clean_series) - 1)
        start_value = float(clean_series.iloc[-(effective_lookback + 1)])
        end_value = float(clean_series.iloc[-1])
        if start_value == 0:
            return float("nan")
        return (end_value - start_value) / abs(start_value)

    @staticmethod
    def _normalize_strategy_pct(value: Optional[float], default_pct: float) -> float:
        raw_value = default_pct if value is None else float(value or 0.0)
        return raw_value / 100 if raw_value > 1 else raw_value

    @staticmethod
    def _prefer_closed_candles(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
        if df is None or df.empty:
            return df

        working_df = df
        if "is_closed" in working_df.columns:
            closed_df = working_df[working_df["is_closed"].fillna(False)]
            if not closed_df.empty:
                return closed_df
            if len(working_df) > 1:
                return working_df.iloc[:-1]
        return working_df

    def evaluate_market_regime(
        self,
        df: Optional[pd.DataFrame],
        timeframe: Optional[str] = None,
        as_of_timestamp=None,
        persist: bool = True,
    ) -> Dict[str, object]:
        current_timeframe = timeframe or self.timeframe or "5m"
        evaluation = {
            "timeframe": current_timeframe,
            "regime": "range",
            "regime_score": 0.0,
            "market_bias": "neutral",
            "adx": 0.0,
            "atr_pct": 0.0,
            "ema_distance_pct": 0.0,
            "ema_200_distance_pct": 0.0,
            "ema_slope": 0.0,
            "recent_range_pct": 0.0,
            "volatility_state": "normal_volatility",
            "trend_state": "range",
            "parabolic": False,
            "legacy_regime": "ranging",
            "price_above_ema_200": False,
            "is_tradeable": False,
            "notes": [],
            "reason": "Sem dados suficientes para classificar o regime.",
            "has_minimum_history": False,
            "timestamp": None,
        }
        if df is None or df.empty:
            if persist:
                self._last_regime_evaluation = evaluation
            return evaluation

        working_df = self._prefer_closed_candles(df)
        if as_of_timestamp is not None:
            working_df = working_df.loc[working_df.index <= pd.Timestamp(as_of_timestamp)]
        has_precomputed_regime_inputs = (
            {"adx", "di_plus", "di_minus", "atr"}.issubset(working_df.columns)
            and any(column in working_df.columns for column in ("ema_21", "sma_21"))
            and any(column in working_df.columns for column in ("ema_200", "sma_200"))
        )
        min_history = 8 if has_precomputed_regime_inputs else 30
        if len(working_df) < min_history:
            if persist:
                self._last_regime_evaluation = evaluation
            return evaluation

        regime_df = working_df.copy()
        close_series = regime_df["close"].astype(float)
        high_series = regime_df["high"].astype(float)
        low_series = regime_df["low"].astype(float)

        if "ema_21" not in regime_df.columns:
            if "sma_21" in regime_df.columns:
                regime_df["ema_21"] = regime_df["sma_21"].astype(float)
            else:
                regime_df["ema_21"] = close_series.ewm(span=21, adjust=False).mean()
        if "ema_200" not in regime_df.columns:
            if "sma_200" in regime_df.columns:
                regime_df["ema_200"] = regime_df["sma_200"].astype(float)
            else:
                regime_df["ema_200"] = close_series.ewm(span=200, adjust=False).mean()
        if "atr" not in regime_df.columns:
            regime_df["atr"] = self.indicators.calculate_atr(high_series, low_series, close_series)
        if "adx" not in regime_df.columns or "di_plus" not in regime_df.columns or "di_minus" not in regime_df.columns:
            adx_data = self.indicators.calculate_adx(high_series, low_series, close_series)
            regime_df["adx"] = adx_data["adx"]
            regime_df["di_plus"] = adx_data["di_plus"]
            regime_df["di_minus"] = adx_data["di_minus"]

        recent_window = regime_df.tail(min(40, len(regime_df)))
        regime_row = recent_window.iloc[-1]

        close_price = float(regime_row.get("close", 0.0) or 0.0)
        ema_21 = float(regime_row.get("ema_21", 0.0) or 0.0)
        ema_200 = float(regime_row.get("ema_200", 0.0) or 0.0)
        adx = float(regime_row.get("adx", 0.0) or 0.0)
        atr_value = float(regime_row.get("atr", 0.0) or 0.0)
        di_plus = float(regime_row.get("di_plus", 0.0) or 0.0)
        di_minus = float(regime_row.get("di_minus", 0.0) or 0.0)

        atr_pct_series = (recent_window["atr"].astype(float) / recent_window["close"].replace(0, np.nan).astype(float)) * 100.0
        atr_pct_series = atr_pct_series.replace([np.inf, -np.inf], np.nan).dropna()
        atr_pct = float(atr_pct_series.iloc[-1]) if not atr_pct_series.empty else 0.0
        atr_pct_baseline = float(atr_pct_series.tail(min(20, len(atr_pct_series))).median()) if not atr_pct_series.empty else 0.0

        range_window = min(10, len(recent_window))
        recent_range_pct = 0.0
        recent_range_baseline = 0.0
        if range_window >= 3:
            rolling_range_pct = (
                recent_window["high"].rolling(range_window).max()
                - recent_window["low"].rolling(range_window).min()
            ) / recent_window["close"].replace(0, np.nan)
            rolling_range_pct = (rolling_range_pct * 100.0).replace([np.inf, -np.inf], np.nan).dropna()
            if not rolling_range_pct.empty:
                recent_range_pct = float(rolling_range_pct.iloc[-1])
                recent_range_baseline = float(rolling_range_pct.tail(min(12, len(rolling_range_pct))).median())

        ema_21_series = recent_window["ema_21"].astype(float)
        ema_slope_raw = self._calculate_context_slope(ema_21_series, lookback=min(6, max(2, len(ema_21_series) - 1)))
        ema_spread_pct = ((ema_21 - ema_200) / abs(ema_200) * 100.0) if ema_200 else 0.0
        ema_slope_pct = float(ema_spread_pct * 0.25) if pd.isna(ema_slope_raw) else float(ema_slope_raw * 100.0)

        ema_distance_pct = abs(close_price - ema_21) / abs(ema_21) * 100.0 if ema_21 else 0.0
        ema_200_distance_pct = abs(close_price - ema_200) / abs(ema_200) * 100.0 if ema_200 else 0.0
        directional_spread = abs(di_plus - di_minus)
        price_above_ema_200 = bool(ema_200 and close_price >= ema_200)

        high_volatility = bool(
            atr_pct >= 1.2
            or (atr_pct_baseline > 0 and atr_pct >= atr_pct_baseline * 1.15)
            or recent_range_pct >= 4.5
            or (recent_range_baseline > 0 and recent_range_pct >= recent_range_baseline * 1.10)
        )
        low_volatility = bool(
            atr_pct > 0
            and atr_pct <= max(atr_pct_baseline * 0.78 if atr_pct_baseline > 0 else 0.0, 0.35)
            and atr_pct <= 0.7
            and recent_range_pct <= max(recent_range_baseline * 0.85 if recent_range_baseline > 0 else 0.0, 1.8)
        )
        volatility_state = "high_volatility" if high_volatility else "low_volatility" if low_volatility else "normal_volatility"

        trend_bull = bool(
            close_price > ema_200
            and ema_21 > ema_200
            and ema_slope_pct >= 0.18
            and adx >= 22
            and directional_spread >= 6
        )
        trend_bear = bool(
            close_price < ema_200
            and ema_21 < ema_200
            and ema_slope_pct <= -0.18
            and adx >= 22
            and directional_spread >= 6
        )
        is_range = bool(
            adx < 20
            and abs(ema_slope_pct) <= 0.12
            and recent_range_pct <= max(recent_range_baseline * 1.05 if recent_range_baseline > 0 else 0.0, 2.2)
            and ema_distance_pct <= 1.2
            and ema_200_distance_pct <= 2.8
        )

        parabolic = bool(
            not is_range
            and adx >= 30
            and high_volatility
            and ema_distance_pct >= max(atr_pct * 1.9, 3.8)
            and abs(ema_slope_pct) >= 0.55
        )

        if trend_bull and not is_range:
            regime = "trend_bull"
            trend_state = "trend_bull"
            market_bias = "bullish"
        elif trend_bear and not is_range:
            regime = "trend_bear"
            trend_state = "trend_bear"
            market_bias = "bearish"
        else:
            regime = "range"
            trend_state = "range"
            market_bias = "neutral"

        regime_score = 0.0
        regime_score += min(max(adx - 15.0, 0.0), 20.0) * 0.15
        regime_score += min(abs(ema_slope_pct) * 4.0, 2.2)
        regime_score += min(ema_200_distance_pct * 0.35, 1.5)
        regime_score += min(directional_spread * 0.08, 1.5)
        if regime.startswith("trend_"):
            regime_score += 1.4
        elif is_range:
            regime_score += 0.8
        if parabolic:
            regime_score += 0.8
        if high_volatility:
            regime_score += 0.9 if regime != "range" else 0.4
        elif low_volatility:
            regime_score -= 0.6 if regime != "range" else 0.1
        if regime == "range":
            regime_score = min(regime_score, 4.8 if low_volatility else 5.2)

        notes = []
        if regime == "range":
            notes.append("mercado lateral sem deslocamento direcional claro")
        else:
            notes.append(f"mercado em {regime}")
        notes.append(f"ADX {adx:.1f}")
        notes.append(f"ATR% {atr_pct:.2f}")
        notes.append(f"dist EMA21 {ema_distance_pct:.2f}%")
        notes.append(f"slope EMA21 {ema_slope_pct:.2f}%")
        if volatility_state != "normal_volatility":
            notes.append(volatility_state)
        if parabolic:
            notes.append("movimento acelerado/parabolico")

        regime_score = round(float(max(0.0, min(10.0, regime_score))), 2)
        legacy_regime = "volatile" if high_volatility and regime == "range" else "trending" if regime != "range" else "ranging"
        is_tradeable = regime != "range" and market_bias in {"bullish", "bearish"} and regime_score >= 5.0 and not low_volatility

        evaluation.update(
            {
                "regime": regime,
                "regime_score": regime_score,
                "market_bias": market_bias,
                "adx": round(adx, 2),
                "atr_pct": round(atr_pct, 2),
                "ema_distance_pct": round(ema_distance_pct, 2),
                "ema_200_distance_pct": round(ema_200_distance_pct, 2),
                "ema_slope": round(ema_slope_pct, 4),
                "recent_range_pct": round(recent_range_pct, 2),
                "volatility_state": volatility_state,
                "trend_state": trend_state,
                "parabolic": parabolic,
                "legacy_regime": legacy_regime,
                "price_above_ema_200": price_above_ema_200,
                "is_tradeable": is_tradeable,
                "notes": notes,
                "reason": " | ".join(notes[:5]),
                "has_minimum_history": True,
                "timestamp": pd.Timestamp(recent_window.index[-1]).isoformat(),
            }
        )
        if persist:
            self._last_regime_evaluation = evaluation
        return evaluation

    def _clear_hard_block(self):
        self._last_hard_block_evaluation = {
            "hard_block": False,
            "block_reason": None,
            "block_source": None,
            "notes": [],
        }

    def _finalize_signal_pipeline(self, analytical_signal: str) -> Dict[str, object]:
        candidate_signal = str(getattr(self, "_last_candidate_signal", "NEUTRO") or "NEUTRO")
        approved_signal = analytical_signal if analytical_signal in ACTIONABLE_SIGNALS else None
        blocked_signal = candidate_signal if candidate_signal in ACTIONABLE_SIGNALS and approved_signal is None else None

        hard_block = getattr(self, "_last_hard_block_evaluation", None) or {}
        trade_decision = getattr(self, "_last_trade_decision", None) or {}
        block_reason = (
            trade_decision.get("block_reason")
            or hard_block.get("block_reason")
        )
        block_source = hard_block.get("block_source")

        pipeline = {
            "candidate_signal": candidate_signal,
            "approved_signal": approved_signal,
            "blocked_signal": blocked_signal,
            "analytical_signal": analytical_signal,
            "block_reason": block_reason,
            "block_source": block_source,
            "context_evaluation": getattr(self, "_last_context_evaluation", None),
            "regime_evaluation": getattr(self, "_last_regime_evaluation", None),
            "structure_evaluation": getattr(self, "_last_price_structure_evaluation", None),
            "confirmation_evaluation": getattr(self, "_last_confirmation_evaluation", None),
            "entry_quality_evaluation": getattr(self, "_last_entry_quality_evaluation", None),
            "scenario_evaluation": getattr(self, "_last_scenario_evaluation", None),
            "trade_decision": getattr(self, "_last_trade_decision", None),
            "hard_block_evaluation": getattr(self, "_last_hard_block_evaluation", None),
        }
        self._last_signal_pipeline = pipeline
        return pipeline

    def _set_hard_block(self, block_reason: str, block_source: str = "signal_engine") -> str:
        cleaned_reason = str(block_reason or "").strip()
        self._last_hard_block_evaluation = {
            "hard_block": True,
            "block_reason": cleaned_reason,
            "block_source": block_source,
            "notes": [cleaned_reason] if cleaned_reason else [],
        }
        self._last_trade_decision = {
            "action": "wait",
            "confidence": 0.0,
            "market_bias": "neutral",
            "setup_type": None,
            "entry_reason": None,
            "block_reason": cleaned_reason or None,
            "invalid_if": None,
        }
        self._finalize_signal_pipeline("NEUTRO")
        return "NEUTRO"

    def evaluate_signal_pipeline(
        self,
        df,
        min_confidence=60,
        require_volume=True,
        require_trend=False,
        avoid_ranging=False,
        crypto_optimized=True,
        timeframe="5m",
        day_trading_mode=False,
        context_df=None,
        context_timeframe: Optional[str] = None,
        stop_loss_pct: Optional[float] = None,
        take_profit_pct: Optional[float] = None,
    ) -> Dict[str, object]:
        analytical_signal = self.check_signal(
            df,
            min_confidence=min_confidence,
            require_volume=require_volume,
            require_trend=require_trend,
            avoid_ranging=avoid_ranging,
            crypto_optimized=crypto_optimized,
            timeframe=timeframe,
            day_trading_mode=day_trading_mode,
            context_df=context_df,
            context_timeframe=context_timeframe,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
        )
        return self._finalize_signal_pipeline(analytical_signal)

    def update_config(self, symbol=None, timeframe=None, rsi_period=None, rsi_min=None, rsi_max=None):
        """Update bot configuration parameters"""

        # Verificar se alguma configuração realmente mudou
        changed = False

        if symbol and symbol != self.symbol:
            self.symbol = symbol
            changed = True
            logger.info(f"✓ Symbol atualizado para: {self.symbol}")

        if timeframe and timeframe != self.timeframe:
            self.timeframe = timeframe
            changed = True
            logger.info(f"✓ Timeframe atualizado para: {self.timeframe}")

        if rsi_period is not None and rsi_period != self.rsi_period:
            self.rsi_period = rsi_period
            changed = True
            logger.info(f"✓ RSI Period atualizado para: {self.rsi_period}")

        if rsi_min is not None and rsi_min != self.rsi_min:
            self.rsi_min = rsi_min
            changed = True
            logger.info(f"✓ RSI Min atualizado para: {self.rsi_min}")

        if rsi_max is not None and rsi_max != self.rsi_max:
            self.rsi_max = rsi_max
            changed = True
            logger.info(f"✓ RSI Max atualizado para: {self.rsi_max}")

        # Só mostrar configuração final se algo mudou
        if changed:
            logger.info(f"📊 Configuração atualizada: {self.symbol} {self.timeframe} RSI({self.rsi_period}) {self.rsi_min}-{self.rsi_max}")

        return changed

    def _fetch_public_ohlcv(self, limit=200, symbol: Optional[str] = None, timeframe: Optional[str] = None):
        """Fetch OHLCV data from Binance public APIs"""
        import requests

        symbol = symbol or self.symbol
        timeframe = timeframe or self.timeframe
        symbol_formatted = symbol.replace('/', '').replace(':USDT', '')  # BTC/USDT -> BTCUSDT

        timeframe_map = {
            '1m': '1m', '3m': '3m', '5m': '5m', '15m': '15m',
            '30m': '30m', '1h': '1h', '2h': '2h', '4h': '4h',
            '6h': '6h', '8h': '8h', '12h': '12h', '1d': '1d'
        }

        binance_timeframe = timeframe_map.get(timeframe, '5m')

        endpoints = [
            f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol_formatted}&interval={binance_timeframe}&limit={limit}",
            f"https://api.binance.com/api/v3/klines?symbol={symbol_formatted}&interval={binance_timeframe}&limit={limit}",
            f"https://api.binance.us/api/v3/klines?symbol={symbol_formatted}&interval={binance_timeframe}&limit={limit}"
        ]

        for endpoint in endpoints:
            try:
                logger.info(f"🌐 Tentando endpoint: {endpoint}")
                response = requests.get(endpoint, timeout=10)
                response.raise_for_status()
                ohlcv_data = response.json()

                if not ohlcv_data:
                    raise ValueError("Endpoint retornou resposta vazia")

                df_data = []
                for candle in ohlcv_data:
                    df_data.append([
                        int(candle[0]),
                        float(candle[1]),
                        float(candle[2]),
                        float(candle[3]),
                        float(candle[4]),
                        float(candle[5])
                    ])

                df = pd.DataFrame(df_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('timestamp', inplace=True)

                logger.info(f"📊 Dados públicos obtidos: {len(df)} candles")
                return df

            except Exception as e:
                logger.warning(f"⚠️ Falha no endpoint {endpoint} -> {e}")
                continue

        raise ConnectionError("Não foi possível obter dados públicos de nenhum endpoint Binance")

    def _simulate_market_data(self, limit=200):
        logger.info("🎯 Usando dados simulados para demonstração (WebSocket simulado)")
        import random

        base_prices = {
            'BTC/USDT': 65000,
            'ETH/USDT': 3200,
            'ADA/USDT': 0.45,
            'SOL/USDT': 150,
            'DOT/USDT': 8.5,
            'XLM/USDT': 0.12,
            'DOGE/USDT': 0.08,
            'LTC/USDT': 85,
            'AVAX/USDT': 35
        }

        base_price = base_prices.get(self.symbol, 1.0)
        current_dt = datetime.now()

        candles = []
        price = base_price

        for i in range(limit):
            timestamp = current_dt - pd.Timedelta(minutes=(limit - i - 1) * 5)
            change_pct = random.normalvariate(0, 0.5) / 100
            price = price * (1 + change_pct)
            open_price = price
            close_price = price * random.uniform(0.995, 1.005)
            high_price = max(open_price, close_price) * random.uniform(1.001, 1.01)
            low_price = min(open_price, close_price) * random.uniform(0.99, 0.999)
            volume = random.uniform(1000000, 10000000)

            candles.append([timestamp, open_price, high_price, low_price, close_price, volume])

        df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df.set_index('timestamp', inplace=True)

        logger.info(f"📊 Dados simulados criados: {len(df)} candles para {self.symbol}")
        return df

    def _get_realtime_stream_client(self, symbol: Optional[str] = None, timeframe: Optional[str] = None):
        from trading_bot_websocket import StreamlinedTradingBot

        symbol = symbol or self.symbol
        timeframe = timeframe or self.timeframe
        stream_key = f"{symbol}_{timeframe}"
        if not hasattr(self, "_stream_clients"):
            self._stream_clients = {}
        if stream_key not in self._stream_clients:
            self._stream_clients[stream_key] = StreamlinedTradingBot(symbol, timeframe)
        return self._stream_clients[stream_key]

    def get_market_data(self, limit=200, symbol: Optional[str] = None, timeframe: Optional[str] = None):
        """Fetch real-only OHLCV data from websocket buffers using closed candles only."""
        symbol = symbol or self.symbol
        timeframe = timeframe or self.timeframe
        cache_key = (
            f"{symbol}_{timeframe}_{limit}_"
            f"rsi{self.rsi_period}_{self.rsi_min}_{self.rsi_max}"
        )
        current_time = datetime.now()

        if hasattr(self, '_cache_data') and cache_key in self._cache_data:
            cached_item = self._cache_data[cache_key]
            cache_age = (current_time - cached_item['timestamp']).total_seconds()
            if cache_age < 2:
                return cached_item['data']

        df = None
        realtime_error = None
        rest_error = None
        try:
            logger.info("Conectando ao stream real de mercado para %s %s", symbol, timeframe)
            df = self._get_realtime_stream_client(symbol=symbol, timeframe=timeframe).get_market_data(limit=limit, timeout=20)
        except Exception as e:
            realtime_error = e
            logger.warning("Falha ao obter dados pelo stream real: %s", e)

        if df is None:
            logger.warning("Stream indisponivel; tentando REST real")
            try:
                df = self._fetch_public_ohlcv(limit=limit, symbol=symbol, timeframe=timeframe)
                df["is_closed"] = True
            except Exception as exc:
                rest_error = exc
                logger.warning("Fallback REST real tambem indisponivel: %s", exc)

            if df is None and not self.allow_simulated_data:
                raise ConnectionError(
                    "Nao foi possivel obter dados reais de mercado via stream nem via REST"
                ) from (rest_error or realtime_error)

            if df is None:
                logger.warning("Fallback REST tambem indisponivel, utilizando dados simulados")
                df = self._simulate_market_data(limit=limit)
                df["is_closed"] = True

        try:
            df = self.calculate_indicators(df)

            if not hasattr(self, '_cache_data'):
                self._cache_data = {}

            self._cache_data[cache_key] = {'data': df.copy(), 'timestamp': current_time}

            if len(self._cache_data) > 5:
                oldest_key = min(self._cache_data.keys(), key=lambda k: self._cache_data[k]['timestamp'])
                del self._cache_data[oldest_key]

            return df

        except Exception as e:
            logger.error(f"❌ Erro ao calcular indicadores: {e}")
            raise

    def get_context_evaluation(
        self,
        context_df: Optional[pd.DataFrame],
        as_of_timestamp=None,
        context_timeframe: Optional[str] = None,
    ) -> Dict[str, object]:
        evaluation = {
            "timeframe": context_timeframe,
            "bias": "neutral",
            "market_bias": "neutral",
            "strength": 0.0,
            "context_strength": 0.0,
            "regime": "range",
            "volatility_state": "low_volatility",
            "trend_state": "range",
            "is_tradeable": False,
            "timestamp": None,
            "reason": "Sem contexto configurado.",
        }
        if context_df is None or context_df.empty:
            evaluation["reason"] = "Sem dados de contexto."
            self._last_context_evaluation = evaluation
            return evaluation

        working_df = self._prefer_closed_candles(context_df)

        if working_df.empty:
            evaluation["reason"] = "Sem candle fechado no contexto."
            self._last_context_evaluation = evaluation
            return evaluation

        if as_of_timestamp is not None:
            working_df = working_df.loc[working_df.index <= pd.Timestamp(as_of_timestamp)]
        if working_df.empty:
            evaluation["reason"] = "Contexto ainda nao fechou candle util."
            self._last_context_evaluation = evaluation
            return evaluation

        regime_evaluation = self.evaluate_market_regime(
            working_df,
            timeframe=context_timeframe,
            as_of_timestamp=as_of_timestamp,
            persist=False,
        )
        context_strength = float(regime_evaluation.get("regime_score", 0.0) or 0.0)
        reason = str(regime_evaluation.get("reason") or "Sem contexto classificado.")
        evaluation = {
            "timeframe": context_timeframe,
            "bias": regime_evaluation.get("market_bias", "neutral"),
            "market_bias": regime_evaluation.get("market_bias", "neutral"),
            "strength": round(context_strength / 10.0, 2),
            "context_strength": context_strength,
            "regime": regime_evaluation.get("regime", "range"),
            "volatility_state": regime_evaluation.get("volatility_state", "normal_volatility"),
            "trend_state": regime_evaluation.get("trend_state", "range"),
            "regime_score": context_strength,
            "parabolic": bool(regime_evaluation.get("parabolic", False)),
            "is_tradeable": bool(regime_evaluation.get("is_tradeable", False)),
            "atr_pct": regime_evaluation.get("atr_pct"),
            "recent_range_pct": regime_evaluation.get("recent_range_pct"),
            "ema_distance_pct": regime_evaluation.get("ema_distance_pct"),
            "ema_200_distance_pct": regime_evaluation.get("ema_200_distance_pct"),
            "ema_slope": regime_evaluation.get("ema_slope"),
            "price_above_ema_200": regime_evaluation.get("price_above_ema_200"),
            "ma_slopes": {
                "ema_21": regime_evaluation.get("ema_slope"),
            },
            "timestamp": regime_evaluation.get("timestamp"),
            "notes": list(regime_evaluation.get("notes", []) or []),
            "reason": reason,
            "legacy_regime": regime_evaluation.get("legacy_regime", "ranging"),
        }
        self._last_context_evaluation = evaluation
        return evaluation

    def analyze_price_structure(
        self,
        df: Optional[pd.DataFrame],
        market_bias: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> Dict[str, object]:
        evaluation = {
            "timeframe": timeframe or self.timeframe,
            "structure_state": "weak_structure",
            "price_location": "mid_range",
            "structure_quality": 0.0,
            "breakout": False,
            "reversal_risk": False,
            "against_market_bias": False,
            "distance_from_ema_pct": None,
            "notes": [],
            "is_tradeable": False,
            "has_minimum_history": False,
            "timestamp": None,
            "reason": "Sem dados suficientes para avaliar a estrutura.",
        }
        if df is None or df.empty:
            self._last_price_structure_evaluation = evaluation
            return evaluation

        working_df = self._prefer_closed_candles(df)

        if len(working_df) < 6:
            self._last_price_structure_evaluation = evaluation
            return evaluation

        current_timeframe = timeframe or self.timeframe or "5m"
        last_row = working_df.iloc[-1]
        prior_df = working_df.iloc[:-1]
        lookback = min(20, len(prior_df))
        recent_df = prior_df.tail(lookback)

        close_price = last_row.get("close", np.nan)
        open_price = last_row.get("open", np.nan)
        high_price = last_row.get("high", np.nan)
        low_price = last_row.get("low", np.nan)
        sma_21 = last_row.get("sma_21", np.nan)
        sma_50 = last_row.get("sma_50", np.nan)
        atr_value = last_row.get("atr", np.nan)
        volume_ratio = last_row.get("volume_ratio", 1.0)
        market_regime = last_row.get("market_regime", "trending")

        if any(pd.isna(value) for value in (close_price, open_price, high_price, low_price)):
            self._last_price_structure_evaluation = evaluation
            return evaluation

        ema_reference = working_df["close"].ewm(span=21, adjust=False).mean().iloc[-1]
        distance_from_ema_pct = None
        if not pd.isna(ema_reference) and float(ema_reference) != 0:
            distance_from_ema_pct = abs(float(close_price) - float(ema_reference)) / abs(float(ema_reference)) * 100.0

        recent_high = float(recent_df["high"].max()) if not recent_df.empty else float(high_price)
        recent_low = float(recent_df["low"].min()) if not recent_df.empty else float(low_price)
        range_span = max(recent_high - recent_low, 1e-9)
        candle_range = max(float(high_price) - float(low_price), 1e-9)
        body_size = abs(float(close_price) - float(open_price))
        body_share = body_size / candle_range
        close_location = (float(close_price) - float(low_price)) / candle_range
        upper_wick = float(high_price) - max(float(open_price), float(close_price))
        lower_wick = min(float(open_price), float(close_price)) - float(low_price)
        avg_body = prior_df["close"].sub(prior_df["open"]).abs().tail(min(10, len(prior_df))).mean()
        avg_body = float(avg_body) if not pd.isna(avg_body) else body_size

        bullish_stack = (
            not pd.isna(sma_21)
            and not pd.isna(sma_50)
            and float(close_price) >= float(sma_21)
            and float(sma_21) >= float(sma_50)
        )
        bearish_stack = (
            not pd.isna(sma_21)
            and not pd.isna(sma_50)
            and float(close_price) <= float(sma_21)
            and float(sma_21) <= float(sma_50)
        )
        resolved_market_bias = market_bias if market_bias in {"bullish", "bearish"} else "neutral"
        if resolved_market_bias == "neutral":
            if bullish_stack:
                resolved_market_bias = "bullish"
            elif bearish_stack:
                resolved_market_bias = "bearish"

        distance_from_sma_atr = 0.0
        if not pd.isna(atr_value) and float(atr_value) > 0 and not pd.isna(sma_21):
            distance_from_sma_atr = abs(float(close_price) - float(sma_21)) / float(atr_value)

        support_zone_distance = abs(float(close_price) - recent_low) / range_span
        resistance_zone_distance = abs(recent_high - float(close_price)) / range_span

        rejection_multiplier = 1.6 if current_timeframe in {"30m", "1h", "4h"} else 1.4
        rejection_share_floor = 0.26 if current_timeframe in {"30m", "1h", "4h"} else 0.22
        bullish_rejection = lower_wick >= max(body_size * rejection_multiplier, candle_range * rejection_share_floor)
        bearish_rejection = upper_wick >= max(body_size * rejection_multiplier, candle_range * rejection_share_floor)
        bullish_impulse = (
            float(close_price) > float(open_price)
            and body_share >= (0.54 if current_timeframe in {"30m", "1h", "4h"} else 0.58)
            and close_location >= (0.66 if current_timeframe in {"30m", "1h", "4h"} else 0.7)
            and body_size >= max(avg_body * (1.05 if current_timeframe in {"30m", "1h", "4h"} else 1.2), 0.0)
        )
        bearish_impulse = (
            float(close_price) < float(open_price)
            and body_share >= (0.54 if current_timeframe in {"30m", "1h", "4h"} else 0.58)
            and close_location <= (0.34 if current_timeframe in {"30m", "1h", "4h"} else 0.3)
            and body_size >= max(avg_body * (1.05 if current_timeframe in {"30m", "1h", "4h"} else 1.2), 0.0)
        )

        breakout_threshold = 0.15 * float(atr_value) if not pd.isna(atr_value) and float(atr_value) > 0 else range_span * 0.01
        broke_recent_high = float(close_price) > recent_high + breakout_threshold
        broke_recent_low = float(close_price) < recent_low - breakout_threshold

        zone_distance_threshold = 0.15 if current_timeframe in {"5m", "15m"} else 0.10

        if broke_recent_high:
            price_location = "resistance"
        elif broke_recent_low:
            price_location = "support"
        elif distance_from_sma_atr <= (1.25 if current_timeframe in {"5m", "15m"} else 1.55) and (bullish_stack or bearish_stack):
            price_location = "trend_zone"
        elif support_zone_distance <= zone_distance_threshold:
            price_location = "support"
        elif resistance_zone_distance <= zone_distance_threshold:
            price_location = "resistance"
        else:
            price_location = "mid_range"

        recent_close = prior_df["close"].iloc[-1]
        higher_lows = float(low_price) > float(recent_df["low"].tail(min(5, len(recent_df))).min()) if not recent_df.empty else False
        lower_highs = float(high_price) < float(recent_df["high"].tail(min(5, len(recent_df))).max()) if not recent_df.empty else False

        is_pullback = False
        if bullish_stack and not pd.isna(sma_21):
            atr_buffer = float(atr_value) if not pd.isna(atr_value) and float(atr_value) > 0 else 0.0
            pullback_floor = float(sma_21) - (atr_buffer * 1.0)
            touch_threshold = float(sma_21) + (atr_buffer * 0.45)
            recent_relief = prior_df["close"].diff().tail(min(3, len(prior_df))).dropna()
            relief_candles = int((recent_relief <= 0).sum()) if not recent_relief.empty else 0
            is_pullback = (
                float(low_price) <= touch_threshold
                and float(close_price) >= pullback_floor
                and (float(close_price) >= float(open_price) or close_location >= 0.40)
                and (higher_lows or price_location in {"trend_zone", "support"} or relief_candles >= 1)
            )
        elif bearish_stack and not pd.isna(sma_21):
            atr_buffer = float(atr_value) if not pd.isna(atr_value) and float(atr_value) > 0 else 0.0
            pullback_ceiling = float(sma_21) + (atr_buffer * 1.0)
            touch_threshold = float(sma_21) - (atr_buffer * 0.45)
            recent_relief = prior_df["close"].diff().tail(min(3, len(prior_df))).dropna()
            relief_candles = int((recent_relief >= 0).sum()) if not recent_relief.empty else 0
            is_pullback = (
                float(high_price) >= touch_threshold
                and float(close_price) <= pullback_ceiling
                and (float(close_price) <= float(open_price) or close_location <= 0.60)
                and (lower_highs or price_location in {"trend_zone", "resistance"} or relief_candles >= 1)
            )

        losing_structure = False
        if bullish_stack and not pd.isna(sma_21):
            losing_structure = (
                float(close_price) < float(sma_21)
                and float(close_price) < float(recent_close)
                and close_location < 0.45
            )
        elif bearish_stack and not pd.isna(sma_21):
            losing_structure = (
                float(close_price) > float(sma_21)
                and float(close_price) > float(recent_close)
                and close_location > 0.55
            )

        is_stretched = distance_from_sma_atr >= (2.6 if current_timeframe in {"5m", "15m"} else 3.2 if current_timeframe in {"30m", "1h", "4h"} else 2.9)
        continuation_ready = False
        if bullish_stack:
            continuation_ready = (
                float(close_price) >= float(recent_close) - (float(atr_value) * 0.10 if not pd.isna(atr_value) and float(atr_value) > 0 else 0.0)
                and higher_lows
                and body_share >= 0.22
                and close_location >= 0.46
            )
        elif bearish_stack:
            continuation_ready = (
                float(close_price) <= float(recent_close) + (float(atr_value) * 0.10 if not pd.isna(atr_value) and float(atr_value) > 0 else 0.0)
                and lower_highs
                and body_share >= 0.22
                and close_location <= 0.54
            )

        reversal_setup = (
            (losing_structure and not continuation_ready and not is_pullback)
            or (
                is_stretched
                and price_location == "resistance"
                and bullish_stack
                and bearish_rejection
                and not continuation_ready
                and not is_pullback
            )
            or (
                is_stretched
                and price_location == "support"
                and bearish_stack
                and bullish_rejection
                and not continuation_ready
                and not is_pullback
            )
            or (price_location == "resistance" and bearish_rejection and bullish_stack and not continuation_ready)
            or (price_location == "support" and bullish_rejection and bearish_stack and not continuation_ready)
        )

        structure_state = "weak_structure"
        reasons = []
        if (broke_recent_high and bullish_impulse) or (broke_recent_low and bearish_impulse):
            structure_state = "breakout"
            reasons.append("rompimento de maxima/minima com candle de impulso")
        elif is_pullback:
            structure_state = "pullback"
            reasons.append("preco corrigindo para a zona de tendencia")
        elif reversal_setup:
            structure_state = "reversal_risk"
            reasons.append("estrutura mostra risco de reversao")
        elif continuation_ready or (bullish_stack and bullish_impulse) or (bearish_stack and bearish_impulse):
            structure_state = "continuation"
            reasons.append("estrutura de continuidade com impulso")
        elif bullish_stack and price_location in {"trend_zone", "support"} and close_location >= 0.38 and not losing_structure:
            structure_state = "continuation"
            reasons.append("continuidade apos micro pausa")
        elif bearish_stack and price_location in {"trend_zone", "resistance"} and close_location <= 0.62 and not losing_structure:
            structure_state = "continuation"
            reasons.append("continuidade apos micro pausa")
        elif bullish_stack and price_location in {"trend_zone", "support"} and close_location >= 0.28 and body_share >= 0.10:
            structure_state = "continuation_weak_but_valid"
            reasons.append("continuidade fraca, mas valida em contexto de tendencia")
        elif bearish_stack and price_location in {"trend_zone", "resistance"} and close_location <= 0.72 and body_share >= 0.10:
            structure_state = "continuation_weak_but_valid"
            reasons.append("continuidade fraca, mas valida em contexto de tendencia")
        else:
            reasons.append("estrutura fraca ou indefinida")

        structure_quality = 0.0
        if structure_state == "breakout":
            structure_quality += 4.0
        elif structure_state == "continuation":
            structure_quality += 3.4
        elif structure_state == "continuation_weak_but_valid":
            structure_quality += 2.8
        elif structure_state == "pullback":
            structure_quality += 3.2
        elif structure_state == "reversal_risk":
            structure_quality += 1.2
        else:
            structure_quality += 0.8

        if bullish_impulse or bearish_impulse:
            structure_quality += 1.5
        elif bullish_rejection or bearish_rejection:
            structure_quality += 0.8

        if price_location == "trend_zone":
            structure_quality += 1.4
        elif price_location in {"support", "resistance"}:
            structure_quality += 1.0
        else:
            structure_quality += 0.5

        if continuation_ready:
            structure_quality += 0.8

        if not pd.isna(volume_ratio):
            if float(volume_ratio) >= 1.6:
                structure_quality += 1.0
            elif float(volume_ratio) >= 1.2:
                structure_quality += 0.5
            elif float(volume_ratio) >= 1.0 and structure_state in (CONTINUATION_STRUCTURE_STATES | {"pullback"}):
                structure_quality += 0.2
            elif float(volume_ratio) < 0.9:
                structure_quality -= 0.6

        if market_regime == "trending":
            structure_quality += 0.9
        elif market_regime == "ranging":
            structure_quality -= 0.8
        elif market_regime == "volatile":
            structure_quality -= 0.5

        if is_stretched and structure_state != "breakout":
            structure_quality -= 1.5
            reasons.append("preco esticado em relacao a media")
        if losing_structure:
            structure_quality -= 1.2
            reasons.append("preco perdendo estrutura recente")

        breakout = structure_state == "breakout"
        reversal_risk = structure_state == "reversal_risk"
        against_market_bias = False
        if reversal_risk:
            if resolved_market_bias == "bullish":
                against_market_bias = bool(
                    bearish_impulse
                    or bearish_rejection
                    or broke_recent_low
                    or losing_structure
                    or price_location == "resistance"
                )
            elif resolved_market_bias == "bearish":
                against_market_bias = bool(
                    bullish_impulse
                    or bullish_rejection
                    or broke_recent_high
                    or losing_structure
                    or price_location == "support"
                )
            else:
                against_market_bias = True
            if against_market_bias:
                reasons.append(f"estrutura contra vies {resolved_market_bias}")

        structure_quality = round(float(max(0.0, min(10.0, structure_quality))), 2)
        min_tradeable_quality = 5.0 if structure_state == "continuation_weak_but_valid" else 5.2
        is_tradeable = structure_state in TREND_STRUCTURE_STATES and structure_quality >= min_tradeable_quality

        if price_location == "support":
            reasons.append("preco proximo do suporte recente")
        elif price_location == "resistance":
            reasons.append("preco proximo da resistencia recente")
        elif price_location == "trend_zone":
            reasons.append("preco em zona de tendencia")
        else:
            reasons.append("preco no meio do range")

        notes = list(dict.fromkeys(str(reason) for reason in reasons if reason))

        evaluation = {
            "timeframe": current_timeframe,
            "structure_state": structure_state,
            "price_location": price_location,
            "structure_quality": structure_quality,
            "breakout": breakout,
            "reversal_risk": reversal_risk,
            "against_market_bias": against_market_bias,
            "distance_from_ema_pct": None if distance_from_ema_pct is None else round(float(distance_from_ema_pct), 2),
            "notes": notes,
            "is_tradeable": is_tradeable,
            "has_minimum_history": True,
            "timestamp": pd.Timestamp(working_df.index[-1]).isoformat(),
            "recent_high": round(recent_high, 4),
            "recent_low": round(recent_low, 4),
            "support_zone_distance": round(float(support_zone_distance), 4),
            "resistance_zone_distance": round(float(resistance_zone_distance), 4),
            "distance_from_sma21_atr": round(distance_from_sma_atr, 2) if distance_from_sma_atr else 0.0,
            "impulse_candle": bool(bullish_impulse or bearish_impulse),
            "rejection_candle": bool(bullish_rejection or bearish_rejection),
            "reason": " | ".join(notes),
        }
        self._last_price_structure_evaluation = evaluation
        return evaluation

    def get_price_structure_evaluation(
        self,
        df: Optional[pd.DataFrame],
        timeframe: Optional[str] = None,
        market_bias: Optional[str] = None,
    ) -> Dict[str, object]:
        return self.analyze_price_structure(
            df,
            market_bias=market_bias,
            timeframe=timeframe,
        )

    @staticmethod
    def _resolve_confirmation_side(
        signal_hypothesis: Optional[str] = None,
        context_evaluation: Optional[Dict[str, object]] = None,
        last_row: Optional[pd.Series] = None,
    ) -> str:
        if signal_hypothesis:
            if str(signal_hypothesis).startswith("COMPRA"):
                return "bullish"
            if str(signal_hypothesis).startswith("VENDA"):
                return "bearish"

        if context_evaluation:
            context_bias = context_evaluation.get("market_bias") or context_evaluation.get("bias")
            if context_bias in {"bullish", "bearish"}:
                return str(context_bias)

        if last_row is not None:
            close_price = last_row.get("close", np.nan)
            sma_21 = last_row.get("sma_21", np.nan)
            if not pd.isna(close_price) and not pd.isna(sma_21):
                if float(close_price) >= float(sma_21):
                    return "bullish"
                return "bearish"

        return "neutral"

    def analyze_confirmation(
        self,
        df: Optional[pd.DataFrame],
        market_bias: Optional[str] = None,
        structure_state: Optional[str] = None,
    ) -> Dict[str, object]:
        evaluation = {
            "timeframe": self.timeframe,
            "confirmation_score": 0.0,
            "confirmation_state": "weak",
            "hypothesis_side": "neutral",
            "rsi_state": "neutral",
            "macd_state": "neutral",
            "volume_state": "neutral",
            "atr_state": "neutral",
            "conflicts": [],
            "notes": [],
            "supporting_factors": [],
            "has_minimum_history": False,
            "timestamp": None,
            "reason": "Sem dados suficientes para confirmar o cenario.",
        }
        if df is None or df.empty:
            self._last_confirmation_evaluation = evaluation
            return evaluation

        working_df = self._prefer_closed_candles(df)

        if len(working_df) < 5:
            self._last_confirmation_evaluation = evaluation
            return evaluation

        last_row = working_df.iloc[-1]
        prior_df = working_df.iloc[:-1]
        resolved_bias = market_bias if market_bias in {"bullish", "bearish"} else self._resolve_confirmation_side(
            last_row=last_row,
        )

        evaluation["hypothesis_side"] = resolved_bias
        evaluation["timestamp"] = pd.Timestamp(working_df.index[-1]).isoformat()
        evaluation["has_minimum_history"] = True

        if resolved_bias == "neutral":
            evaluation["reason"] = "Sem hipotese direcional clara para confirmar."
            self._last_confirmation_evaluation = evaluation
            return evaluation

        close_price = last_row.get("close", np.nan)
        rsi = last_row.get("rsi", np.nan)
        macd = last_row.get("macd", np.nan)
        macd_signal = last_row.get("macd_signal", np.nan)
        atr_value = last_row.get("atr", np.nan)
        ema_21 = last_row.get("ema_21", last_row.get("sma_21", np.nan))
        ema_50 = last_row.get("ema_50", last_row.get("sma_50", np.nan))
        prev_close = prior_df["close"].iloc[-1] if not prior_df.empty and "close" in prior_df else np.nan

        conflicts = []
        notes = []
        score = 0.0

        if not pd.isna(rsi):
            rsi_value = float(rsi)
            if resolved_bias == "bullish":
                if 50 <= rsi_value <= 68:
                    evaluation["rsi_state"] = "favorable"
                    score += 2.2
                    notes.append("RSI em faixa favoravel para compra")
                elif 46 <= rsi_value < 50 or 68 < rsi_value <= 74:
                    evaluation["rsi_state"] = "acceptable"
                    score += 1.0
                    notes.append("RSI ainda confirma o vies bullish")
                elif rsi_value > 74:
                    evaluation["rsi_state"] = "stretched"
                    conflicts.append("RSI esticado para continuidade bullish")
                else:
                    evaluation["rsi_state"] = "weak"
                    conflicts.append("RSI abaixo da faixa de confirmacao bullish")
            else:
                if 32 <= rsi_value <= 50:
                    evaluation["rsi_state"] = "favorable"
                    score += 2.2
                    notes.append("RSI em faixa favoravel para venda")
                elif 28 <= rsi_value < 32 or 50 < rsi_value <= 56:
                    evaluation["rsi_state"] = "acceptable"
                    score += 1.0
                    notes.append("RSI ainda confirma o vies bearish")
                elif rsi_value < 28:
                    evaluation["rsi_state"] = "stretched"
                    conflicts.append("RSI esticado para continuidade bearish")
                else:
                    evaluation["rsi_state"] = "weak"
                    conflicts.append("RSI acima da faixa de confirmacao bearish")

        if not pd.isna(macd) and not pd.isna(macd_signal):
            macd_value = float(macd)
            macd_signal_value = float(macd_signal)
            macd_gap = abs(macd_value - macd_signal_value)
            if resolved_bias == "bullish":
                if macd_value > macd_signal_value:
                    evaluation["macd_state"] = "aligned"
                    score += 2.3 if macd_gap > 0.02 else 1.5
                    notes.append("MACD acima da linha de sinal")
                elif macd_gap <= 0.02:
                    evaluation["macd_state"] = "flat"
                    score += 0.6
                    notes.append("MACD neutro, sem conflito forte")
                else:
                    evaluation["macd_state"] = "conflict"
                    conflicts.append("MACD conflita com o vies bullish")
            else:
                if macd_value < macd_signal_value:
                    evaluation["macd_state"] = "aligned"
                    score += 2.3 if macd_gap > 0.02 else 1.5
                    notes.append("MACD abaixo da linha de sinal")
                elif macd_gap <= 0.02:
                    evaluation["macd_state"] = "flat"
                    score += 0.6
                    notes.append("MACD neutro, sem conflito forte")
                else:
                    evaluation["macd_state"] = "conflict"
                    conflicts.append("MACD conflita com o vies bearish")

        last_volume = last_row.get("volume", np.nan)
        volume_baseline = float("nan")
        if "volume" in prior_df:
            recent_volume = prior_df["volume"].tail(min(20, len(prior_df))).dropna()
            if not recent_volume.empty:
                volume_baseline = float(recent_volume.mean())
        if not pd.isna(last_volume) and not pd.isna(volume_baseline) and volume_baseline > 0:
            volume_ratio = float(last_volume) / float(volume_baseline)
            if volume_ratio >= 1.05:
                evaluation["volume_state"] = "above_average"
                score += 1.6
                notes.append("Volume acima da media recente")
            elif volume_ratio >= 0.95:
                evaluation["volume_state"] = "average"
                score += 0.6
                notes.append("Volume em linha com a media")
            else:
                evaluation["volume_state"] = "weak"
                conflicts.append("Volume fraco para confirmar o movimento")
        else:
            volume_ratio = last_row.get("volume_ratio", np.nan)
            if not pd.isna(volume_ratio):
                if float(volume_ratio) >= 1.15:
                    evaluation["volume_state"] = "above_average"
                    score += 1.4
                    notes.append("Volume acima da media recente")
                elif float(volume_ratio) >= 0.95:
                    evaluation["volume_state"] = "average"
                    score += 0.5
                else:
                    evaluation["volume_state"] = "weak"
                    conflicts.append("Volume fraco para confirmar o movimento")

        if not pd.isna(atr_value) and not pd.isna(close_price) and float(close_price) > 0:
            atr_pct = float(atr_value) / float(close_price)
            atr_baseline = float("nan")
            if "atr" in prior_df and "close" in prior_df:
                atr_pct_series = prior_df["atr"] / prior_df["close"].replace(0, np.nan)
                clean_atr_pct = atr_pct_series.dropna().tail(min(20, len(atr_pct_series.dropna())))
                if not clean_atr_pct.empty:
                    atr_baseline = float(clean_atr_pct.median())

            if not pd.isna(atr_baseline) and atr_baseline > 0:
                if atr_pct < atr_baseline * 0.65:
                    evaluation["atr_state"] = "compressed"
                    conflicts.append("ATR fraco para confirmar o movimento")
                elif atr_pct > atr_baseline * 2.0:
                    evaluation["atr_state"] = "excessive"
                    conflicts.append("ATR excessivo para confirmar com seguranca")
                else:
                    evaluation["atr_state"] = "healthy"
                    score += 1.5
                    notes.append("ATR em faixa saudavel")
            elif atr_pct >= 0.002:
                evaluation["atr_state"] = "healthy"
                score += 0.8
                notes.append("ATR suficiente para o setup")
            else:
                evaluation["atr_state"] = "compressed"
                conflicts.append("ATR fraco para confirmar o movimento")

        if not pd.isna(close_price) and not pd.isna(ema_21):
            averages_aligned = False
            if resolved_bias == "bullish":
                averages_aligned = float(close_price) >= float(ema_21) and (
                    pd.isna(ema_50) or float(ema_21) >= float(ema_50)
                )
            else:
                averages_aligned = float(close_price) <= float(ema_21) and (
                    pd.isna(ema_50) or float(ema_21) <= float(ema_50)
                )
            if averages_aligned:
                score += 1.6
                notes.append("Medias confirmam o vies")
            else:
                conflicts.append("Medias nao confirmam o vies")

        if not pd.isna(close_price) and not pd.isna(prev_close):
            price_momentum = float(close_price) - float(prev_close)
            if resolved_bias == "bullish" and price_momentum > 0:
                score += 0.8
                notes.append("Preco fechou na direcao do vies")
            elif resolved_bias == "bearish" and price_momentum < 0:
                score += 0.8
                notes.append("Preco fechou na direcao do vies")
            else:
                conflicts.append("Momentum de curto prazo contra o vies")

        if structure_state == "breakout" and evaluation["volume_state"] == "weak":
            conflicts.append("Breakout sem volume de confirmacao")
        if structure_state == "pullback" and evaluation["macd_state"] == "conflict":
            conflicts.append("Pullback sem MACD alinhado para retomada")
        if structure_state == "continuation" and evaluation["atr_state"] == "compressed":
            conflicts.append("Continuacao sem expansao suficiente de ATR")
        if evaluation["volume_state"] == "weak" and evaluation["atr_state"] == "compressed":
            score = min(score, 3.5)
            conflicts.append("Sem volume e expansao suficientes para confirmar o setup")

        score = round(float(max(0.0, min(10.0, score))), 2)
        if score >= 7.0 and len(conflicts) <= 1:
            confirmation_state = "confirmed"
        elif score >= 4.0:
            confirmation_state = "mixed"
        else:
            confirmation_state = "weak"

        notes = list(dict.fromkeys(str(note) for note in notes if note))
        conflicts = list(dict.fromkeys(str(conflict) for conflict in conflicts if conflict))

        evaluation = {
            "timeframe": self.timeframe,
            "confirmation_score": score,
            "confirmation_state": confirmation_state,
            "hypothesis_side": resolved_bias,
            "rsi_state": evaluation["rsi_state"],
            "macd_state": evaluation["macd_state"],
            "volume_state": evaluation["volume_state"],
            "atr_state": evaluation["atr_state"],
            "conflicts": conflicts,
            "notes": notes,
            "supporting_factors": notes,
            "has_minimum_history": True,
            "timestamp": pd.Timestamp(working_df.index[-1]).isoformat(),
            "reason": (
                " | ".join(notes[:2] + conflicts[:2])
                if notes or conflicts
                else "Confirmacao tecnica sem sinais claros."
            ),
        }
        self._last_confirmation_evaluation = evaluation
        return evaluation

    def get_confirmation_evaluation(
        self,
        df: Optional[pd.DataFrame],
        signal_hypothesis: Optional[str] = None,
        timeframe: Optional[str] = None,
        context_evaluation: Optional[Dict[str, object]] = None,
        structure_evaluation: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        working_df = self._prefer_closed_candles(df)
        if working_df is not None and not working_df.empty:
            last_row = working_df.iloc[-1] if not working_df.empty else None
        else:
            last_row = None

        market_bias = self._resolve_confirmation_side(
            signal_hypothesis=signal_hypothesis,
            context_evaluation=context_evaluation,
            last_row=last_row,
        )
        evaluation = self.analyze_confirmation(
            df,
            market_bias=market_bias,
            structure_state=(structure_evaluation or {}).get("structure_state"),
        )
        evaluation["timeframe"] = timeframe or self.timeframe
        evaluation["hypothesis_side"] = market_bias
        self._last_confirmation_evaluation = evaluation
        return evaluation

    def evaluate_contextual_entry(
        self,
        df: Optional[pd.DataFrame],
        market_bias: Optional[str] = None,
        structure_state: Optional[str] = None,
        regime_evaluation: Optional[Dict[str, object]] = None,
        structure_evaluation: Optional[Dict[str, object]] = None,
        signal_hypothesis: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> Dict[str, object]:
        current_timeframe = timeframe or self.timeframe or "5m"
        evaluation = {
            "timeframe": current_timeframe,
            "entry_signal": "wait",
            "entry_quality": "bad",
            "rr_estimate": 0.0,
            "entry_score": 0.0,
            "quality_score": 0.0,
            "setup_type": None,
            "entry_reason": None,
            "rejection_reason": None,
            "rsi_state": "neutral",
            "structure_state": structure_state or "weak_structure",
            "candle_quality": "bad",
            "momentum_state": "weak",
            "late_entry": False,
            "stretched_price": False,
            "entry_in_middle": True,
            "low_volatility": False,
            "dead_range": False,
            "is_tradeable": False,
            "has_minimum_history": False,
            "timestamp": None,
            "stop_distance_pct": 0.0,
            "target_distance_pct": 0.0,
            "reason": "Sem dados suficientes para avaliar a entrada contextual.",
            "notes": [],
            "conflicts": [],
            "price_location": "mid_range",
            "candle_is_acceptable": False,
        }
        if df is None or df.empty:
            self._last_entry_quality_evaluation = evaluation
            return evaluation

        working_df = self._prefer_closed_candles(df.copy())

        if len(working_df) < 6:
            self._last_entry_quality_evaluation = evaluation
            return evaluation

        last_row = working_df.iloc[-1]
        prior_df = working_df.iloc[:-1]
        if prior_df.empty:
            self._last_entry_quality_evaluation = evaluation
            return evaluation

        close_price = last_row.get("close", np.nan)
        open_price = last_row.get("open", np.nan)
        high_price = last_row.get("high", np.nan)
        low_price = last_row.get("low", np.nan)
        atr_value = last_row.get("atr", np.nan)
        ema_21 = last_row.get("ema_21", last_row.get("sma_21", np.nan))
        if any(pd.isna(value) for value in (close_price, open_price, high_price, low_price)):
            self._last_entry_quality_evaluation = evaluation
            return evaluation

        regime_evaluation = regime_evaluation or self.evaluate_market_regime(
            working_df,
            timeframe=current_timeframe,
        )
        regime_name = str((regime_evaluation or {}).get("regime") or "range")
        regime_score = float((regime_evaluation or {}).get("regime_score", 0.0) or 0.0)
        regime_bias = str((regime_evaluation or {}).get("market_bias") or "")
        volatility_state = str((regime_evaluation or {}).get("volatility_state") or "normal_volatility")
        parabolic = bool((regime_evaluation or {}).get("parabolic", False))

        signal_side = market_bias if market_bias in {"bullish", "bearish"} else self._resolve_confirmation_side(
            signal_hypothesis=signal_hypothesis,
            last_row=last_row,
        )
        if signal_side == "neutral" and regime_bias in {"bullish", "bearish"}:
            signal_side = regime_bias
        if signal_side == "neutral":
            evaluation["reason"] = "Sem hipotese direcional clara para avaliar a entrada contextual."
            self._last_entry_quality_evaluation = evaluation
            return evaluation

        structure_evaluation = structure_evaluation or self.get_price_structure_evaluation(
            working_df,
            timeframe=current_timeframe,
            market_bias=signal_side,
        )
        structure_state = structure_state or str(structure_evaluation.get("structure_state", "weak_structure"))
        structure_quality = float(structure_evaluation.get("structure_quality", 0.0) or 0.0)
        price_location = str(structure_evaluation.get("price_location", "mid_range") or "mid_range")
        resistance_zone_distance = float(structure_evaluation.get("resistance_zone_distance", 1.0) or 1.0)
        support_zone_distance = float(structure_evaluation.get("support_zone_distance", 1.0) or 1.0)
        recent_high = structure_evaluation.get("recent_high")
        recent_low = structure_evaluation.get("recent_low")
        distance_from_ema_pct = structure_evaluation.get("distance_from_ema_pct")
        if distance_from_ema_pct is None and not pd.isna(ema_21) and float(ema_21) != 0:
            distance_from_ema_pct = abs(float(close_price) - float(ema_21)) / abs(float(ema_21)) * 100.0
        distance_from_ema_pct = float(distance_from_ema_pct or 0.0)

        candle_range = max(float(high_price) - float(low_price), 1e-9)
        body_size = abs(float(close_price) - float(open_price))
        body_share = body_size / candle_range
        close_location = (float(close_price) - float(low_price)) / candle_range
        upper_wick = float(high_price) - max(float(open_price), float(close_price))
        lower_wick = min(float(open_price), float(close_price)) - float(low_price)
        adverse_wick = upper_wick if signal_side == "bullish" else lower_wick
        adverse_wick_share = adverse_wick / candle_range if candle_range > 0 else 1.0
        avg_body = prior_df["close"].sub(prior_df["open"]).abs().tail(min(8, len(prior_df))).mean()
        avg_body = float(avg_body) if not pd.isna(avg_body) else body_size
        avg_range = prior_df["high"].sub(prior_df["low"]).tail(min(8, len(prior_df))).mean()
        avg_range = float(avg_range) if not pd.isna(avg_range) else candle_range
        atr_pct = (
            float(atr_value) / float(close_price) * 100.0
            if not pd.isna(atr_value) and float(close_price) > 0
            else 0.0
        )
        recent_atr_series = prior_df["atr"].tail(min(12, len(prior_df))) if "atr" in prior_df.columns else pd.Series(dtype=float)
        avg_recent_atr = recent_atr_series.mean() if not recent_atr_series.empty else np.nan
        avg_recent_atr = float(avg_recent_atr) if not pd.isna(avg_recent_atr) else float(atr_value or 0.0)
        volatility_ratio = (
            float(atr_value) / avg_recent_atr
            if not pd.isna(atr_value) and avg_recent_atr and avg_recent_atr > 0
            else 1.0
        )
        stretched_threshold_pct = 2.45 if current_timeframe in {"30m", "1h"} else 2.75 if current_timeframe in {"4h", "1d"} else 2.15
        stretched_by_distance = distance_from_ema_pct >= stretched_threshold_pct
        stretched_by_candle = (
            body_size >= max(avg_body * 2.25, 0.0)
            and candle_range >= max(avg_range * 2.0, 0.0)
        )
        stretched_price = stretched_by_distance or stretched_by_candle

        recent_window = prior_df.tail(min(5, len(prior_df)))
        recent_swing_high = float(recent_window["high"].max()) if not recent_window.empty else recent_high
        recent_swing_low = float(recent_window["low"].min()) if not recent_window.empty else recent_low
        breakout_extension = False
        if signal_side == "bullish" and recent_swing_high is not None and atr_pct > 0:
            breakout_extension = float(close_price) > float(recent_swing_high) + (float(atr_value) * 0.65)
        elif signal_side == "bearish" and recent_swing_low is not None and atr_pct > 0:
            breakout_extension = float(close_price) < float(recent_swing_low) - (float(atr_value) * 0.65)

        candle_is_directional = (
            float(close_price) > float(open_price)
            if signal_side == "bullish"
            else float(close_price) < float(open_price)
        )
        candle_close_is_clean = close_location >= 0.50 if signal_side == "bullish" else close_location <= 0.50
        price_in_middle = price_location == "mid_range"
        low_volatility = volatility_ratio < 0.70
        dead_range = price_in_middle and structure_state not in (TREND_STRUCTURE_STATES | {"reversal_risk"})
        late_entry = breakout_extension and stretched_price

        if candle_range <= 0 or body_share < 0.10:
            candle_quality = "bad"
        elif (
            body_share >= 0.48
            and adverse_wick_share <= 0.40
            and candle_is_directional
            and not stretched_by_candle
        ):
            candle_quality = "strong"
        elif (
            body_share >= 0.26
            and adverse_wick_share <= 0.68
            and volatility_ratio >= 0.70
            and (candle_is_directional or candle_close_is_clean)
        ):
            candle_quality = "acceptable"
        elif (
            structure_state in TREND_STRUCTURE_STATES
            and structure_quality >= 5.4
            and body_share >= 0.20
            and adverse_wick_share <= 0.75
            and volatility_ratio >= 0.65
        ):
            candle_quality = "acceptable"
        else:
            candle_quality = "bad"

        recent_three = working_df.tail(min(3, len(working_df)))
        recent_closes = recent_three["close"].astype(float)
        close_deltas = recent_closes.diff().dropna()
        favorable_closes = int((close_deltas > 0).sum()) if signal_side == "bullish" else int((close_deltas < 0).sum())
        prev_row = prior_df.iloc[-1] if not prior_df.empty else None
        bullish_engulfing = False
        bearish_engulfing = False
        if prev_row is not None:
            prev_open = float(prev_row.get("open", open_price))
            prev_close = float(prev_row.get("close", close_price))
            bullish_engulfing = (
                signal_side == "bullish"
                and prev_close < prev_open
                and float(close_price) >= prev_open
                and float(open_price) <= prev_close
            )
            bearish_engulfing = (
                signal_side == "bearish"
                and prev_close > prev_open
                and float(close_price) <= prev_open
                and float(open_price) >= prev_close
            )
        engulfing_recent = bullish_engulfing or bearish_engulfing
        recent_context = prior_df.tail(min(5, len(prior_df)))
        recent_high_reference = float(recent_context["high"].max()) if not recent_context.empty else float(high_price)
        recent_low_reference = float(recent_context["low"].min()) if not recent_context.empty else float(low_price)
        micro_breakout_recent = (
            signal_side == "bullish" and float(close_price) >= recent_high_reference
        ) or (
            signal_side == "bearish" and float(close_price) <= recent_low_reference
        )
        macd_value = float(last_row.get("macd", 0.0) or 0.0)
        macd_signal = float(last_row.get("macd_signal", 0.0) or 0.0)
        macd_histogram = float(last_row.get("macd_histogram", macd_value - macd_signal) or 0.0)
        recent_volume_ratio = last_row.get("volume_ratio", np.nan)
        if pd.isna(recent_volume_ratio):
            volume_mean = prior_df["volume"].tail(min(20, len(prior_df))).mean() if "volume" in prior_df.columns else np.nan
            recent_volume_ratio = (
                float(last_row.get("volume", 0.0)) / float(volume_mean)
                if volume_mean and not pd.isna(volume_mean)
                else 1.0
            )
        recent_volume_ratio = float(recent_volume_ratio or 0.0)

        if favorable_closes >= 2 and (engulfing_recent or micro_breakout_recent or abs(macd_histogram) > 0):
            momentum_state = "strong"
        elif favorable_closes >= 1 or engulfing_recent or micro_breakout_recent:
            momentum_state = "acceptable"
        else:
            momentum_state = "weak"

        rsi_value = float(last_row.get("rsi", 50.0) or 50.0)
        prev_rsi = float(prior_df.iloc[-1].get("rsi", rsi_value) or rsi_value) if not prior_df.empty else rsi_value
        rsi_delta = rsi_value - prev_rsi
        if signal_side == "bullish":
            if rsi_value <= 40 and rsi_delta > 0:
                rsi_state = "pullback_recovery"
            elif 48 <= rsi_value <= 68:
                rsi_state = "trend_supportive"
            elif 68 < rsi_value <= 75 and momentum_state != "weak":
                rsi_state = "momentum_supportive"
            elif rsi_value > 75:
                rsi_state = "extended"
            elif rsi_value < 30:
                rsi_state = "too_early"
            else:
                rsi_state = "neutral"
        else:
            if rsi_value >= 60 and rsi_delta < 0:
                rsi_state = "pullback_recovery"
            elif 32 <= rsi_value <= 52:
                rsi_state = "trend_supportive"
            elif 25 <= rsi_value < 32 and momentum_state != "weak":
                rsi_state = "momentum_supportive"
            elif rsi_value < 25:
                rsi_state = "extended"
            elif rsi_value > 70:
                rsi_state = "too_early"
            else:
                rsi_state = "neutral"

        reversal_confirmed = structure_state == "reversal_risk" and (
            engulfing_recent or favorable_closes >= 2 or micro_breakout_recent
        )
        aligned_trend_regime = (
            (signal_side == "bullish" and regime_name == "trend_bull")
            or (signal_side == "bearish" and regime_name == "trend_bear")
        )
        strong_trend_regime = aligned_trend_regime and regime_score >= (6.5 if parabolic else 7.0)

        setup_type = None
        if aligned_trend_regime and structure_state == "pullback":
            setup_type = "pullback_trend"
        elif aligned_trend_regime and structure_state in (CONTINUATION_STRUCTURE_STATES | {"breakout"}):
            setup_type = "continuation_breakout"
        elif structure_state == "reversal_risk" and reversal_confirmed:
            setup_type = "reversal_controlled"
        elif regime_name == "range" and structure_state in {"pullback", "reversal_risk"} and price_location in {"support", "resistance"}:
            setup_type = "reversal_controlled"
        elif structure_state in (CONTINUATION_STRUCTURE_STATES | {"breakout"}):
            setup_type = "continuation_breakout"
        elif structure_state == "pullback":
            setup_type = "pullback_trend"

        if signal_side == "bullish":
            candle_stop_pct = max((float(close_price) - float(low_price)) / float(close_price) * 100.0, 0.0)
            structure_stop_pct = (
                max((float(close_price) - float(recent_swing_low)) / float(close_price) * 100.0, 0.0)
                if recent_swing_low is not None
                else 0.0
            )
            structure_target_pct = (
                max((float(recent_swing_high) - float(close_price)) / float(close_price) * 100.0, 0.0)
                if recent_swing_high is not None
                else 0.0
            )
        else:
            candle_stop_pct = max((float(high_price) - float(close_price)) / float(close_price) * 100.0, 0.0)
            structure_stop_pct = (
                max((float(recent_swing_high) - float(close_price)) / float(close_price) * 100.0, 0.0)
                if recent_swing_high is not None
                else 0.0
            )
            structure_target_pct = (
                max((float(close_price) - float(recent_swing_low)) / float(close_price) * 100.0, 0.0)
                if recent_swing_low is not None
                else 0.0
            )

        base_stop_pct = max(candle_stop_pct, atr_pct * 0.85)
        if structure_stop_pct > 0:
            structure_stop_cap = max(
                base_stop_pct,
                atr_pct * (1.15 if structure_state in CONTINUATION_STRUCTURE_STATES else 1.35),
            )
            stop_distance_pct = max(base_stop_pct, min(structure_stop_pct, structure_stop_cap))
        else:
            stop_distance_pct = base_stop_pct
        target_distance_pct = max(structure_target_pct, atr_pct * (1.45 if structure_state == "breakout" else 1.05))
        if structure_state == "pullback":
            target_distance_pct = max(target_distance_pct, stop_distance_pct * 1.35)
        elif structure_state in CONTINUATION_STRUCTURE_STATES:
            target_distance_pct = max(target_distance_pct, stop_distance_pct * 1.20)
        elif setup_type == "reversal_controlled":
            target_distance_pct = max(target_distance_pct, stop_distance_pct * 1.10)
        rr_estimate = (target_distance_pct / stop_distance_pct) if stop_distance_pct > 0 else 0.0

        notes = []
        conflicts = []
        score_breakdown = {"regime": 0.0, "structure": 0.0, "candle": 0.0, "momentum": 0.0, "rsi_timing": 0.0}
        rejection_reason = None

        if setup_type in {"pullback_trend", "continuation_breakout"}:
            if aligned_trend_regime:
                score_breakdown["regime"] = min(3.0, 2.1 + (regime_score / 10.0))
                notes.append(f"regime compativel com {setup_type}")
            elif regime_name == "range":
                score_breakdown["regime"] = 0.7
                conflicts.append("regime lateral reduz setup direcional")
            else:
                score_breakdown["regime"] = 0.2
                conflicts.append("setup contra o regime dominante")
        elif setup_type == "reversal_controlled":
            if regime_name == "range":
                score_breakdown["regime"] = 2.5
                notes.append("reversao controlada em regime lateral")
            elif strong_trend_regime:
                score_breakdown["regime"] = 0.2
                conflicts.append("reversao simples contra trend forte")
            else:
                score_breakdown["regime"] = 1.0
                conflicts.append("reversao exige confirmacao adicional")

        if setup_type == "pullback_trend":
            score_breakdown["structure"] = min(2.0, 1.2 + (structure_quality / 10.0))
            if price_location == "trend_zone":
                score_breakdown["structure"] = min(2.0, score_breakdown["structure"] + 0.2)
            notes.append("pullback dentro da tendencia")
        elif setup_type == "continuation_breakout":
            score_breakdown["structure"] = min(2.0, 1.0 + (structure_quality / 10.0))
            if structure_state == "breakout" or micro_breakout_recent:
                score_breakdown["structure"] = min(2.0, score_breakdown["structure"] + 0.2)
            if structure_state == "continuation_weak_but_valid":
                score_breakdown["structure"] = max(0.8, score_breakdown["structure"] - 0.25)
                notes.append("continuidade fraca, mas validada por contexto")
            notes.append("continuidade apos compressao local")
        elif setup_type == "reversal_controlled":
            score_breakdown["structure"] = min(2.0, 0.9 + (structure_quality / 12.0))
            if price_location in {"support", "resistance"}:
                score_breakdown["structure"] = min(2.0, score_breakdown["structure"] + 0.3)
            notes.append("reversao controlada com estrutura local")
        else:
            conflicts.append("estrutura nao definiu setup valido")

        if candle_quality == "strong":
            score_breakdown["candle"] = 2.0
            notes.append("candle de entrada forte")
        elif candle_quality == "acceptable":
            score_breakdown["candle"] = 1.3
            notes.append("candle de entrada aceitavel")
        elif body_share >= 0.18 and adverse_wick_share <= 0.82 and not price_in_middle:
            score_breakdown["candle"] = 0.4
            conflicts.append("candle atual oferece baixa qualidade")
        else:
            conflicts.append("candle atual oferece baixa qualidade")

        if momentum_state == "strong":
            score_breakdown["momentum"] = 1.0
            notes.append("momentum recente confirma a direcao")
        elif momentum_state == "acceptable":
            score_breakdown["momentum"] = 0.6
            notes.append("momento recente suficiente")
        else:
            conflicts.append("momentum recente ainda fraco")

        if setup_type == "pullback_trend":
            if rsi_state == "pullback_recovery":
                score_breakdown["rsi_timing"] = 2.0
                notes.append("RSI confirma timing de retomada")
            elif rsi_state == "trend_supportive":
                score_breakdown["rsi_timing"] = 1.5
                notes.append("RSI apoia a tendencia")
            elif rsi_state == "momentum_supportive":
                score_breakdown["rsi_timing"] = 1.1
                notes.append("RSI apoia a retomada")
            elif rsi_state == "extended":
                score_breakdown["rsi_timing"] = 0.2
                conflicts.append("RSI mostra entrada ja esticada")
            else:
                score_breakdown["rsi_timing"] = 0.6
        elif setup_type == "continuation_breakout":
            if rsi_state in {"trend_supportive", "momentum_supportive"}:
                score_breakdown["rsi_timing"] = 1.6
                notes.append("RSI apoia a continuidade")
            elif rsi_state == "pullback_recovery":
                score_breakdown["rsi_timing"] = 1.2
                notes.append("RSI saiu do alivio local")
            elif rsi_state == "extended":
                score_breakdown["rsi_timing"] = 0.3
                conflicts.append("RSI mostra continuidade ja cansada")
            else:
                score_breakdown["rsi_timing"] = 0.7
        elif setup_type == "reversal_controlled":
            if rsi_state == "pullback_recovery":
                score_breakdown["rsi_timing"] = 1.7
                notes.append("RSI apoia a reversao controlada")
            elif rsi_state in {"trend_supportive", "momentum_supportive"}:
                score_breakdown["rsi_timing"] = 1.1
            else:
                score_breakdown["rsi_timing"] = 0.4
                conflicts.append("RSI ainda nao oferece timing limpo")

        if price_in_middle:
            conflicts.append("entrada no meio de range sem direcao")
        if low_volatility:
            conflicts.append("volatilidade muito baixa para entrada")
        if stretched_price:
            conflicts.append("preco esta esticado em relacao a ema 21")
        if late_entry:
            conflicts.append("entrada tardia apos impulso")
        if volatility_state == "high_volatility" and setup_type == "reversal_controlled":
            conflicts.append("alta volatilidade exige evitar reversao simples")
        if (
            regime_name == "range"
            and setup_type == "continuation_breakout"
            and (price_in_middle or volatility_state == "low_volatility")
        ):
            conflicts.append("continuacao com pouco edge dentro de range")
        if (
            signal_side == "bearish"
            and regime_name == "trend_bull"
            and regime_score >= (6.5 if parabolic else 7.0)
            and not reversal_confirmed
        ) or (
            signal_side == "bullish"
            and regime_name == "trend_bear"
            and regime_score >= (6.5 if parabolic else 7.0)
            and not reversal_confirmed
        ):
            rejection_reason = rejection_reason or "reversao simples contra trend forte"

        if signal_side == "bullish" and price_location == "resistance" and structure_state != "breakout":
            if resistance_zone_distance <= 0.018:
                rejection_reason = "Compra perto da resistencia sem rompimento."
            elif resistance_zone_distance <= 0.05:
                conflicts.append("compra perto da resistencia sem rompimento")
                notes.append("resistencia proxima penaliza a entrada")
        elif signal_side == "bearish" and price_location == "support" and structure_state != "breakout":
            if support_zone_distance <= 0.018:
                rejection_reason = "Venda perto do suporte sem rompimento."
            elif support_zone_distance <= 0.05:
                conflicts.append("venda perto do suporte sem rompimento")
                notes.append("suporte proximo penaliza a entrada")

        if rr_estimate < 0.75:
            rejection_reason = rejection_reason or "risco retorno insuficiente"
        elif rr_estimate < 1.0:
            conflicts.append("risco retorno insuficiente")
        elif rr_estimate >= 1.5:
            notes.append("risco retorno forte")

        if setup_type == "reversal_controlled" and (strong_trend_regime or parabolic):
            rejection_reason = rejection_reason or "reversao simples contra trend forte"
        if setup_type == "continuation_breakout" and candle_quality == "bad" and momentum_state == "weak":
            rejection_reason = rejection_reason or "continuacao sem candle minimamente aceitavel"
        if setup_type in {"pullback_trend", "continuation_breakout"} and regime_name == "range" and low_volatility:
            rejection_reason = rejection_reason or "mercado lateral sem edge suficiente"
        if setup_type == "continuation_breakout" and regime_name == "range" and price_in_middle:
            rejection_reason = rejection_reason or "continuacao fraca em mercado lateral"
        if stretched_price and distance_from_ema_pct >= (stretched_threshold_pct + 0.8):
            rejection_reason = rejection_reason or "entrada muito esticada da ema 21"
        if candle_quality == "bad" and (
            body_share < 0.16
            or adverse_wick_share > 0.82
            or (candle_range >= max(avg_range * 2.4, 0.0) and not breakout_extension)
        ):
            rejection_reason = rejection_reason or "candle atual oferece baixa qualidade"

        entry_score = sum(score_breakdown.values())
        if low_volatility:
            entry_score -= 0.7
        if dead_range:
            entry_score -= 0.9
        if stretched_price:
            entry_score -= 1.0
        if late_entry:
            entry_score -= 0.6
        if rr_estimate < 1.0:
            entry_score -= 0.7
        if parabolic and setup_type == "reversal_controlled":
            entry_score -= 1.2
        if regime_name == "range" and setup_type == "continuation_breakout":
            entry_score -= 0.9 if price_in_middle else 0.6

        entry_score = round(float(max(0.0, min(10.0, entry_score))), 2)
        entry_quality = self._classify_entry_quality(
            rr_estimate=rr_estimate,
            quality_score=entry_score,
            late_entry=late_entry,
            stretched_price=stretched_price,
            price_in_middle=price_in_middle,
            candle_is_acceptable=candle_quality != "bad",
            structure_state=structure_state,
            low_volatility=low_volatility,
            dead_range=dead_range,
        )
        if rejection_reason:
            entry_quality = "bad"
        elif entry_score >= 7.0:
            entry_quality = "strong"
        elif entry_score >= 4.0:
            entry_quality = "acceptable"
        else:
            entry_quality = "bad"
            rejection_reason = rejection_reason or "score de entrada insuficiente"

        entry_reason = None
        if entry_quality != "bad" and setup_type:
            entry_reason = (
                f"{setup_type} | candle {candle_quality} | momentum {momentum_state} | "
                f"RSI {rsi_state} | score {entry_score:.2f}"
            )

        notes = list(dict.fromkeys(str(note) for note in notes if note))
        conflicts = list(dict.fromkeys(str(conflict) for conflict in conflicts if conflict))
        reason = rejection_reason or entry_reason or " | ".join((notes + conflicts)[:3]) or "Entrada sem contexto suficiente."

        evaluation = {
            "timeframe": current_timeframe,
            "entry_signal": (
                "long_candidate"
                if entry_quality != "bad" and signal_side == "bullish"
                else "short_candidate"
                if entry_quality != "bad" and signal_side == "bearish"
                else "wait"
            ),
            "entry_quality": entry_quality,
            "rr_estimate": round(float(rr_estimate), 2),
            "entry_score": round(float(entry_score), 2),
            "quality_score": round(float(entry_score), 2),
            "setup_type": setup_type,
            "entry_reason": entry_reason,
            "rejection_reason": rejection_reason,
            "rsi_state": rsi_state,
            "structure_state": structure_state,
            "candle_quality": candle_quality,
            "momentum_state": momentum_state,
            "late_entry": bool(late_entry),
            "stretched_price": bool(stretched_price),
            "entry_in_middle": bool(price_in_middle),
            "low_volatility": bool(low_volatility),
            "dead_range": bool(dead_range),
            "is_tradeable": entry_quality != "bad",
            "has_minimum_history": True,
            "timestamp": pd.Timestamp(working_df.index[-1]).isoformat(),
            "stop_distance_pct": round(float(stop_distance_pct), 2),
            "target_distance_pct": round(float(target_distance_pct), 2),
            "reason": reason,
            "notes": notes,
            "conflicts": conflicts,
            "price_location": price_location,
            "candle_is_acceptable": candle_quality != "bad",
        }
        self._last_entry_quality_evaluation = evaluation
        return evaluation

    def validate_entry_quality(
        self,
        df: Optional[pd.DataFrame],
        market_bias: Optional[str] = None,
        structure_state: Optional[str] = None,
        regime_evaluation: Optional[Dict[str, object]] = None,
        structure_evaluation: Optional[Dict[str, object]] = None,
        signal_hypothesis: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> Dict[str, object]:
        # Compatibility wrapper kept for older call sites.
        return self.evaluate_contextual_entry(
            df,
            market_bias=market_bias,
            structure_state=structure_state,
            regime_evaluation=regime_evaluation,
            structure_evaluation=structure_evaluation,
            signal_hypothesis=signal_hypothesis,
            timeframe=timeframe,
        )


    @staticmethod
    def _classify_entry_quality(
        rr_estimate: float,
        quality_score: float,
        late_entry: bool,
        stretched_price: bool,
        price_in_middle: bool,
        candle_is_acceptable: bool,
        structure_state: Optional[str] = None,
        low_volatility: bool = False,
        dead_range: bool = False,
    ) -> str:
        structure_state = structure_state or "weak_structure"
        if dead_range and low_volatility:
            return "bad"
        if dead_range and quality_score < 5.0 and rr_estimate < 1.0:
            return "bad"
        if low_volatility and quality_score < 4.5 and rr_estimate < 1.0:
            return "bad"
        if late_entry and stretched_price and rr_estimate < 1.20:
            return "bad"
        if (
            quality_score >= 7.0
            and rr_estimate >= 1.10
            and not late_entry
            and candle_is_acceptable
            and not (stretched_price and rr_estimate < 1.35)
        ):
            return "strong"
        if (
            quality_score >= 4.0
            and rr_estimate >= 0.90
            and structure_state in (TREND_STRUCTURE_STATES | {"reversal_risk"})
            and not (price_in_middle and structure_state not in {"breakout", "reversal_risk"})
        ):
            return "acceptable"
        return "bad"

    @staticmethod
    def _normalize_entry_quality_label(label: Optional[str]) -> str:
        normalized = str(label or "bad").strip().lower()
        if normalized == "good":
            return "strong"
        if normalized in {"strong", "acceptable", "bad"}:
            return normalized
        return "bad"

    @staticmethod
    def _is_soft_entry_rejection(
        entry_evaluation: Optional[Dict[str, object]],
        structure_state: Optional[str] = None,
        structure_quality: float = 0.0,
        confirmation_state: Optional[str] = None,
    ) -> bool:
        if not isinstance(entry_evaluation, dict):
            return False

        reason = str(
            entry_evaluation.get("rejection_reason")
            or entry_evaluation.get("reason")
            or ""
        ).strip().lower()
        if not reason:
            return False

        soft_reason_tokens = (
            "score de entrada insuficiente",
            "candle atual oferece baixa qualidade",
            "continuacao sem candle minimamente aceitavel",
        )
        if not any(token in reason for token in soft_reason_tokens):
            return False

        rr_estimate = float(entry_evaluation.get("rr_estimate", 0.0) or 0.0)
        if rr_estimate < 0.95:
            return False

        if bool(entry_evaluation.get("stretched_price")):
            return False
        if bool(entry_evaluation.get("late_entry")):
            return False
        if bool(entry_evaluation.get("entry_in_middle")):
            return False
        if bool(entry_evaluation.get("dead_range")):
            return False
        if bool(entry_evaluation.get("low_volatility")):
            return False

        normalized_structure_state = str(
            structure_state
            or entry_evaluation.get("structure_state")
            or "weak_structure"
        )
        if normalized_structure_state not in TREND_STRUCTURE_STATES:
            return False
        if float(structure_quality or 0.0) < 5.6:
            return False

        normalized_confirmation_state = str(confirmation_state or "weak")
        if normalized_confirmation_state != "confirmed":
            return False

        return True

    def get_entry_quality_evaluation(
        self,
        df: Optional[pd.DataFrame],
        signal_hypothesis: Optional[str] = None,
        timeframe: Optional[str] = None,
        regime_evaluation: Optional[Dict[str, object]] = None,
        structure_evaluation: Optional[Dict[str, object]] = None,
        stop_loss_pct: Optional[float] = None,
        take_profit_pct: Optional[float] = None,
    ) -> Dict[str, object]:
        working_df = self._prefer_closed_candles(df)
        if working_df is not None and not working_df.empty:
            last_row = working_df.iloc[-1] if not working_df.empty else None
        else:
            last_row = None

        market_bias = self._resolve_confirmation_side(
            signal_hypothesis=signal_hypothesis,
            last_row=last_row,
        )
        evaluation = self.evaluate_contextual_entry(
            df,
            market_bias=market_bias,
            regime_evaluation=regime_evaluation,
            structure_state=(structure_evaluation or {}).get("structure_state"),
            structure_evaluation=structure_evaluation,
            signal_hypothesis=signal_hypothesis,
            timeframe=timeframe,
        )
        evaluation["timeframe"] = timeframe or self.timeframe

        normalized_stop_loss_pct = self._normalize_strategy_pct(
            stop_loss_pct,
            ProductionConfig.DEFAULT_LIVE_STOP_LOSS_PCT,
        )
        normalized_take_profit_pct = self._normalize_strategy_pct(
            take_profit_pct,
            ProductionConfig.DEFAULT_LIVE_TAKE_PROFIT_PCT,
        )
        if normalized_stop_loss_pct > 0:
            configured_stop_pct = round(normalized_stop_loss_pct * 100, 2)
            evaluation["stop_distance_pct"] = configured_stop_pct
        if normalized_take_profit_pct > 0:
            configured_target_pct = round(normalized_take_profit_pct * 100, 2)
            evaluation["target_distance_pct"] = configured_target_pct
        if normalized_stop_loss_pct > 0 and normalized_take_profit_pct > 0:
            evaluation["rr_estimate"] = round(float(normalized_take_profit_pct / normalized_stop_loss_pct), 2)
            evaluation["entry_quality"] = self._classify_entry_quality(
                rr_estimate=float(evaluation["rr_estimate"]),
                quality_score=float(evaluation.get("entry_score", evaluation.get("quality_score", 0.0)) or 0.0),
                late_entry=bool(evaluation.get("late_entry")),
                stretched_price=bool(evaluation.get("stretched_price")),
                price_in_middle=bool(evaluation.get("entry_in_middle")),
                candle_is_acceptable=bool(evaluation.get("candle_is_acceptable", True)),
                structure_state=(structure_evaluation or {}).get("structure_state") or evaluation.get("structure_state"),
                low_volatility=bool(any("volatilidade muito baixa" in str(item) for item in evaluation.get("conflicts", []))),
                dead_range=bool(any("range sem direção" in str(item) for item in evaluation.get("conflicts", []))),
            )
            evaluation["is_tradeable"] = evaluation["entry_quality"] != "bad"
            if evaluation["entry_quality"] == "bad":
                evaluation["entry_signal"] = "wait"
                evaluation["rejection_reason"] = evaluation.get("rejection_reason") or evaluation.get("reason")
                evaluation["entry_reason"] = None
            else:
                evaluation["entry_signal"] = "long_candidate" if market_bias == "bullish" else "short_candidate"

        self._last_entry_quality_evaluation = evaluation
        return evaluation

    def build_scenario_score(
        self,
        context_result: Optional[Dict[str, object]],
        structure_result: Optional[Dict[str, object]],
        confirmation_result: Optional[Dict[str, object]],
        entry_result: Optional[Dict[str, object]],
        regime_result: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        def _clip_score(value: Optional[float]) -> float:
            return round(float(max(0.0, min(10.0, float(value or 0.0)))), 2)

        def _resolve_context_score(result: Optional[Dict[str, object]]) -> float:
            if not result:
                return 0.0
            score = result.get("context_strength")
            if score is None:
                score = float(result.get("strength", 0.0) or 0.0) * 10.0
            return _clip_score(score)

        def _resolve_entry_score(result: Optional[Dict[str, object]]) -> float:
            if not result:
                return 0.0

            base_score = float(result.get("entry_score", result.get("quality_score", 0.0)) or 0.0)
            quality_label = self._normalize_entry_quality_label(result.get("entry_quality", "bad"))
            if base_score <= 0:
                base_score = {
                    "strong": 8.0,
                    "acceptable": 5.5,
                    "bad": 2.0,
                }.get(quality_label, 0.0)

            rr_estimate = float(result.get("rr_estimate", 0.0) or 0.0)
            if rr_estimate >= 1.8:
                base_score += 0.8
            elif rr_estimate >= 1.3:
                base_score += 0.3
            elif rr_estimate < 1.1:
                base_score -= 1.0

            if result.get("late_entry"):
                base_score -= 0.8
            if result.get("stretched_price"):
                base_score -= 0.8

            return _clip_score(base_score)

        def _resolve_pullback_intensity(
            entry_data: Optional[Dict[str, object]],
            structure_data: Optional[Dict[str, object]],
        ):
            setup_type = str((entry_data or {}).get("setup_type") or "").strip().lower()
            if setup_type != "pullback_trend":
                return "not_applicable", 0.0, None

            structure_state = str((structure_data or {}).get("structure_state") or "weak_structure")
            structure_quality = float((structure_data or {}).get("structure_quality", 0.0) or 0.0)
            against_market_bias = bool((structure_data or {}).get("against_market_bias", False))
            reversal_risk = bool((structure_data or {}).get("reversal_risk", structure_state == "reversal_risk"))
            contra_structure = (
                against_market_bias
                or reversal_risk
                or structure_state not in ({"pullback"} | CONTINUATION_STRUCTURE_STATES)
            )
            if contra_structure:
                return "against_structure", -2.0, "pullback contra estrutura reduz o cenario"
            if structure_state == "pullback":
                if structure_quality >= 5.8:
                    return "strong", 3.0, "pullback forte adiciona +3.0 ao cenario"
                return "moderate", 1.5, "pullback moderado adiciona +1.5 ao cenario"
            if structure_quality >= 5.4:
                return "continuation_valid", 0.0, "sem pullback claro; continuidade valida sem bonus"
            return "continuation_weak", -0.4, "sem pullback claro; continuidade fraca penaliza levemente"

        result_map = {
            "context": context_result,
            "structure": structure_result,
            "confirmation": confirmation_result,
            "entry": entry_result,
        }
        score_breakdown = {
            "context": _resolve_context_score(context_result),
            "structure": _clip_score((structure_result or {}).get("structure_quality")),
            "confirmation": _clip_score((confirmation_result or {}).get("confirmation_score")),
            "entry": _resolve_entry_score(entry_result),
        }
        weights = {
            "context": 0.30,
            "structure": 0.30,
            "confirmation": 0.25,
            "entry": 0.15,
        }

        available_components = {
            name: score
            for name, score in score_breakdown.items()
            if result_map.get(name) and result_map[name].get("has_minimum_history", True)
        }

        notes = []
        for name, score in available_components.items():
            if score >= 7.5:
                notes.append(f"{name} forte")
            elif score < 4.5:
                notes.append(f"{name} fraco")
        pullback_intensity, pullback_score, pullback_note = _resolve_pullback_intensity(
            entry_result,
            structure_result,
        )
        if pullback_note:
            notes.append(pullback_note)

        weak_components = [name for name, score in available_components.items() if score < 4.0]
        available_weight = sum(weights[name] for name in available_components)
        scenario_score = (
            sum(available_components[name] * weights[name] for name in available_components) / available_weight
            if available_components and available_weight > 0
            else 0.0
        )
        if weak_components:
            scenario_score -= 0.4 * len(weak_components)
            notes.append(
                "penalizado por componente fraco: " + ", ".join(weak_components)
            )

        scenario_side = "neutral"
        if context_result:
            scenario_side = str(
                context_result.get("market_bias")
                or context_result.get("bias")
                or scenario_side
            )
        if scenario_side not in {"bullish", "bearish"} and confirmation_result:
            scenario_side = str(confirmation_result.get("hypothesis_side") or scenario_side)
        if scenario_side not in {"bullish", "bearish"}:
            scenario_side = "neutral"

        if (
            context_result
            and not context_result.get("is_tradeable", True)
            and score_breakdown["context"] < 5.0
        ):
            scenario_score -= 0.5
            notes.append("contexto nao operavel reduz a nota final")

        if structure_result and structure_result.get("has_minimum_history", True):
            price_location = str(structure_result.get("price_location") or "mid_range")
            structure_state = str(structure_result.get("structure_state") or "weak_structure")
            resistance_zone_distance = float(structure_result.get("resistance_zone_distance", 1.0) or 1.0)
            support_zone_distance = float(structure_result.get("support_zone_distance", 1.0) or 1.0)
            if scenario_side == "bullish" and price_location == "resistance" and structure_state != "breakout" and resistance_zone_distance > 0.06:
                scenario_score -= 0.45
                notes.append("resistencia proxima penaliza o cenario")
            elif scenario_side == "bearish" and price_location == "support" and structure_state != "breakout" and support_zone_distance > 0.06:
                scenario_score -= 0.45
                notes.append("suporte proximo penaliza o cenario")

        if regime_result and regime_result.get("has_minimum_history", True):
            regime = str(regime_result.get("regime") or "range")
            regime_score = float(regime_result.get("regime_score", 0.0) or 0.0)
            volatility_state = str(regime_result.get("volatility_state") or "normal_volatility")
            structure_state = str((structure_result or {}).get("structure_state") or "weak_structure")
            confirmation_state = str((confirmation_result or {}).get("confirmation_state") or "weak")
            if regime == "range" and structure_state in (CONTINUATION_STRUCTURE_STATES | {"pullback"}):
                scenario_score -= 0.8
                notes.append("regime lateral reduz confianca do setup")
            if volatility_state == "low_volatility":
                scenario_score -= 0.6
                notes.append("volatilidade baixa reduz o edge do cenario")
            elif volatility_state == "high_volatility" and structure_state not in {"breakout", "pullback"}:
                scenario_score -= 0.35
                notes.append("volatilidade alta exige estrutura mais limpa")
            if regime_result.get("parabolic") and regime_score >= 7.0 and confirmation_state != "confirmed":
                scenario_score -= 0.6
                notes.append("regime parabolico penaliza reversao simples")

        if pullback_score != 0.0:
            scenario_score += float(pullback_score)

        scenario_score = _clip_score(scenario_score)
        if scenario_score >= 8.0:
            scenario_grade = "A"
        elif scenario_score >= 6.5:
            scenario_grade = "B"
        elif scenario_score >= 5.0:
            scenario_grade = "C"
        else:
            scenario_grade = "D"

        evaluation = {
            "scenario_score": scenario_score,
            "scenario_grade": scenario_grade,
            "score_breakdown": score_breakdown,
            "regime": (regime_result or {}).get("regime"),
            "pullback_intensity": pullback_intensity,
            "pullback_score": round(float(pullback_score), 2),
            "notes": list(dict.fromkeys(str(note) for note in notes if note)),
            "has_minimum_history": bool(available_components),
        }
        self._last_scenario_evaluation = evaluation
        return evaluation

    def make_trade_decision(
        self,
        context_result: Optional[Dict[str, object]],
        structure_result: Optional[Dict[str, object]],
        confirmation_result: Optional[Dict[str, object]],
        entry_result: Optional[Dict[str, object]],
        hard_block_result: Optional[Dict[str, object]],
        scenario_score_result: Optional[Dict[str, object]],
        risk_result: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        market_bias = "neutral"
        if context_result:
            market_bias = str(
                context_result.get("market_bias")
                or context_result.get("bias")
                or market_bias
            )
        if market_bias not in {"bullish", "bearish"} and confirmation_result:
            market_bias = str(confirmation_result.get("hypothesis_side") or market_bias)
        if market_bias not in {"bullish", "bearish"}:
            market_bias = "neutral"

        structure_state = str((structure_result or {}).get("structure_state") or "weak_structure")
        price_location = str((structure_result or {}).get("price_location") or "mid_range")
        structure_quality = float((structure_result or {}).get("structure_quality", 0.0) or 0.0)
        resistance_zone_distance = float((structure_result or {}).get("resistance_zone_distance", 1.0) or 1.0)
        support_zone_distance = float((structure_result or {}).get("support_zone_distance", 1.0) or 1.0)
        confirmation_state = str((confirmation_result or {}).get("confirmation_state") or "weak")
        entry_quality = self._normalize_entry_quality_label((entry_result or {}).get("entry_quality"))
        soft_bad_entry = bool((entry_result or {}).get("soft_bad_entry", False))
        entry_score = float((entry_result or {}).get("entry_score", (entry_result or {}).get("quality_score", 0.0)) or 0.0)
        rr_estimate = float((entry_result or {}).get("rr_estimate", 0.0) or 0.0)
        structure_available = bool(structure_result) and bool((structure_result or {}).get("has_minimum_history", True))
        confirmation_available = bool(confirmation_result) and bool((confirmation_result or {}).get("has_minimum_history", True))
        entry_available = bool(entry_result) and bool((entry_result or {}).get("has_minimum_history", True))
        scenario_available = bool(scenario_score_result) and bool((scenario_score_result or {}).get("has_minimum_history", True))
        scenario_score = float((scenario_score_result or {}).get("scenario_score", 0.0) or 0.0)
        scenario_grade = str((scenario_score_result or {}).get("scenario_grade", "D") or "D").upper()
        pullback_intensity = str((scenario_score_result or {}).get("pullback_intensity") or "not_applicable")
        pullback_score = float((scenario_score_result or {}).get("pullback_score", 0.0) or 0.0)
        against_market_bias = bool((structure_result or {}).get("against_market_bias", False))

        setup_type = (entry_result or {}).get("setup_type")
        if not setup_type:
            setup_type = (
                structure_state
                if structure_available and structure_state in TREND_STRUCTURE_STATES
                else None
            )
        block_reason = None
        required_scenario_score = 5.0
        if entry_quality == "acceptable":
            required_scenario_score = 5.6
        if structure_state in (CONTINUATION_STRUCTURE_STATES | {"breakout"}) and entry_quality != "strong":
            required_scenario_score = max(required_scenario_score, 5.8)
        if confirmation_state == "mixed":
            required_scenario_score = max(required_scenario_score, 5.9)
        if (
            confirmation_state == "confirmed"
            and structure_state in TREND_STRUCTURE_STATES
            and structure_quality >= 6.0
        ):
            required_scenario_score = max(4.7, required_scenario_score - 0.35)
        if entry_quality == "strong" and confirmation_state == "confirmed":
            required_scenario_score = max(4.6, required_scenario_score - 0.15)
        if (
            setup_type == "continuation_breakout"
            and structure_quality >= 5.8
            and confirmation_state in {"confirmed", "mixed"}
            and entry_quality in {"strong", "acceptable"}
        ):
            continuation_floor = 5.2 if confirmation_state == "confirmed" else 5.4
            required_scenario_score = min(required_scenario_score, continuation_floor)
        if setup_type == "pullback_trend":
            if pullback_intensity == "strong" or pullback_score >= 3.0:
                required_scenario_score = max(4.6, required_scenario_score - 0.6)
            elif pullback_intensity == "moderate" or pullback_score >= 1.5:
                required_scenario_score = max(4.9, required_scenario_score - 0.35)
            elif pullback_score < 0.0:
                required_scenario_score = max(required_scenario_score, 5.85)
        if soft_bad_entry and entry_quality == "bad":
            required_scenario_score = max(required_scenario_score, 6.4)

        allow_soft_bad_entry = (
            entry_available
            and entry_quality == "bad"
            and soft_bad_entry
            and confirmation_state == "confirmed"
            and scenario_score >= required_scenario_score
            and entry_score >= 4.8
            and rr_estimate >= 0.95
            and structure_state in TREND_STRUCTURE_STATES
            and not bool((entry_result or {}).get("late_entry"))
            and not bool((entry_result or {}).get("stretched_price"))
        )

        if hard_block_result and hard_block_result.get("hard_block"):
            block_reason = hard_block_result.get("block_reason") or "Hard block ativo."
        elif risk_result and not risk_result.get("allowed", True):
            block_reason = risk_result.get("reason") or "Risco operacional bloqueado."
        elif market_bias == "neutral":
            block_reason = "Vies de mercado neutro."
        elif structure_available and structure_state == "weak_structure":
            block_reason = (structure_result or {}).get("reason") or "Estrutura fraca."
        elif structure_available and structure_state == "reversal_risk" and against_market_bias:
            block_reason = (structure_result or {}).get("reason") or "Risco de reversao contra o vies."
        elif structure_available and structure_state not in TREND_STRUCTURE_STATES:
            block_reason = "Estrutura nao valida para entrada."
        elif (
            structure_available
            and market_bias == "bullish"
            and price_location == "resistance"
            and structure_state != "breakout"
            and not (
                structure_state in (CONTINUATION_STRUCTURE_STATES | {"pullback"})
                and structure_quality >= 5.4
                and resistance_zone_distance > 0.04
                and scenario_score >= 5.8
                and confirmation_state in {"confirmed", "mixed"}
                and entry_quality in {"strong", "acceptable"}
            )
        ):
            block_reason = "Compra perto da resistencia sem rompimento."
        elif (
            structure_available
            and market_bias == "bearish"
            and price_location == "support"
            and structure_state != "breakout"
            and not (
                structure_state in (CONTINUATION_STRUCTURE_STATES | {"pullback"})
                and structure_quality >= 5.4
                and support_zone_distance > 0.04
                and scenario_score >= 5.8
                and confirmation_state in {"confirmed", "mixed"}
                and entry_quality in {"strong", "acceptable"}
            )
        ):
            block_reason = "Venda perto do suporte sem rompimento."
        elif confirmation_available and confirmation_state == "weak":
            block_reason = (confirmation_result or {}).get("reason") or "Confirmacao tecnica fraca."
        elif entry_available and entry_quality == "bad" and not allow_soft_bad_entry:
            block_reason = (
                (entry_result or {}).get("rejection_reason")
                or (entry_result or {}).get("reason")
                or "Qualidade de entrada ruim."
            )
        elif scenario_available and (scenario_grade == "D" or scenario_score < required_scenario_score):
            block_reason = "Score do cenario abaixo do minimo."

        confidence = scenario_score
        if confirmation_state == "confirmed":
            confidence += 0.4
        elif confirmation_state == "mixed":
            confidence -= 0.3

        if entry_quality == "strong":
            confidence += 0.3
        elif entry_quality == "acceptable":
            confidence -= 0.2
        elif entry_quality == "bad":
            confidence -= 0.7 if not allow_soft_bad_entry else 0.4

        if structure_state == "pullback":
            confidence += 0.2
        elif structure_state == "continuation_weak_but_valid":
            confidence -= 0.15
        elif structure_state == "breakout":
            confidence -= 0.1

        confidence = round(float(max(0.0, min(10.0, confidence))), 2)

        if block_reason:
            decision = {
                "action": "wait",
                "confidence": confidence if confidence > 0 else round(float(max(0.0, min(10.0, scenario_score))), 2),
                "market_bias": market_bias,
                "setup_type": setup_type,
                "entry_reason": None,
                "block_reason": str(block_reason),
                "invalid_if": None,
            }
            self._last_trade_decision = decision
            return decision

        action = "buy" if market_bias == "bullish" else "sell"
        entry_reason = (
            (entry_result or {}).get("entry_reason")
            or (
                f"{setup_type or structure_state} | {market_bias} | "
                f"confirmacao {confirmation_state} | "
                f"entrada {entry_quality} | "
                f"score {scenario_score:.2f}"
            )
        )
        invalid_if = (
            f"perder vies {market_bias} ou invalidar o setup {setup_type or structure_state}"
        )
        decision = {
            "action": action,
            "confidence": confidence,
            "market_bias": market_bias,
            "setup_type": setup_type,
            "entry_reason": entry_reason,
            "block_reason": None,
            "invalid_if": invalid_if,
        }
        self._last_trade_decision = decision
        return decision

    def check_hard_blocks(
        self,
        signal: str,
        context_evaluation: Optional[Dict[str, object]] = None,
        regime_evaluation: Optional[Dict[str, object]] = None,
        structure_evaluation: Optional[Dict[str, object]] = None,
        confirmation_evaluation: Optional[Dict[str, object]] = None,
        entry_quality_evaluation: Optional[Dict[str, object]] = None,
        market_regime: Optional[str] = None,
        require_volume: bool = False,
        volume_ratio: Optional[float] = None,
        min_volume_ratio: Optional[float] = None,
        require_trend: bool = False,
        adx: Optional[float] = None,
        min_adx_threshold: Optional[float] = None,
        atr_pct: Optional[float] = None,
        min_atr_pct: Optional[float] = None,
        runtime_allowed: Optional[bool] = None,
        runtime_block_reason: Optional[str] = None,
        active_profile: Optional[Dict[str, object]] = None,
        risk_plan: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        evaluation = {
            "hard_block": False,
            "block_reason": None,
            "block_source": None,
            "notes": [],
        }
        notes = []

        def block(reason: str, source: str, extra_notes: Optional[list] = None) -> Dict[str, object]:
            payload = {
                "hard_block": True,
                "block_reason": str(reason or "").strip() or None,
                "block_source": source,
                "notes": list(dict.fromkeys(
                    [str(item).strip() for item in ((extra_notes or []) + ([reason] if reason else [])) if str(item).strip()]
                )),
            }
            self._last_hard_block_evaluation = payload
            return payload

        if runtime_allowed is False:
            governance_reason = runtime_block_reason or "Runtime bloqueado por governanca."
            if not active_profile:
                notes.append("nenhum setup ativo promovido para este mercado/timeframe")
            notes.append(governance_reason)
            return block(governance_reason, "runtime_governance", notes)

        if risk_plan and not risk_plan.get("allowed", True):
            notes.append(risk_plan.get("reason") or "risco operacional bloqueado")
            return block(
                risk_plan.get("reason") or "Risco operacional bloqueou a entrada.",
                "risk_guardrail",
                notes,
            )

        actionable_signals = {"COMPRA", "COMPRA_FRACA", "VENDA", "VENDA_FRACA"}
        if signal not in actionable_signals:
            self._last_hard_block_evaluation = evaluation
            return evaluation

        structure_state = None
        structure_quality = 0.0
        price_location = "mid_range"
        current_timeframe = str(getattr(self, "timeframe", "") or "").lower()
        if structure_evaluation and structure_evaluation.get("has_minimum_history"):
            structure_state = structure_evaluation.get("structure_state", "weak_structure")
            structure_quality = float(structure_evaluation.get("structure_quality", 0.0) or 0.0)
            price_location = str(structure_evaluation.get("price_location", "mid_range") or "mid_range")
            current_timeframe = str(structure_evaluation.get("timeframe") or current_timeframe or "").lower()
        is_higher_tf = current_timeframe in {"30m", "1h", "4h", "1d"}

        if context_evaluation:
            bias = context_evaluation.get("market_bias") or context_evaluation.get("bias") or "neutral"
            raw_context_strength = context_evaluation.get("context_strength", context_evaluation.get("strength"))
            has_explicit_strength = raw_context_strength is not None
            context_strength = float(raw_context_strength or 0.0)
            if not context_evaluation.get("is_tradeable", True) and bias in {"bullish", "bearish"} and context_strength < 3.5:
                return block(
                    context_evaluation.get("reason") or "Contexto superior nao esta operavel.",
                    "higher_timeframe_context",
                    [context_evaluation.get("reason") or "contexto superior sem operabilidade"],
                )
            elif signal.startswith("COMPRA") and bias == "bearish":
                if (not has_explicit_strength) or context_strength >= 6.2:
                    return block("Entrada contra o timeframe maior.", "higher_timeframe_conflict", ["contexto superior contra compra"])
                notes.append("contexto superior bearish com forca moderada; entrada penalizada")
            elif signal.startswith("VENDA") and bias == "bullish":
                if (not has_explicit_strength) or context_strength >= 6.2:
                    return block("Entrada contra o timeframe maior.", "higher_timeframe_conflict", ["contexto superior contra venda"])
                notes.append("contexto superior bullish com forca moderada; entrada penalizada")

        if regime_evaluation and regime_evaluation.get("has_minimum_history", True):
            regime = str(regime_evaluation.get("regime") or "range")
            regime_score = float(regime_evaluation.get("regime_score", 0.0) or 0.0)
            volatility_state = str(regime_evaluation.get("volatility_state") or "normal_volatility")
            parabolic = bool(regime_evaluation.get("parabolic", False))
            confirmation_state = str((confirmation_evaluation or {}).get("confirmation_state") or "weak")
            entry_quality_label = self._normalize_entry_quality_label((entry_quality_evaluation or {}).get("entry_quality"))
            has_controlled_reversal = (
                structure_state == "reversal_risk"
                and confirmation_state == "confirmed"
                and entry_quality_label in {"acceptable", "strong"}
            )
            if (
                signal.startswith("VENDA")
                and regime == "trend_bull"
                and regime_score >= (6.5 if parabolic else 7.2)
                and not has_controlled_reversal
            ):
                return block(
                    "Reversao simples contra regime bull.",
                    "market_regime",
                    list(regime_evaluation.get("notes", []) or []),
                )
            if (
                signal.startswith("COMPRA")
                and regime == "trend_bear"
                and regime_score >= (6.5 if parabolic else 7.2)
                and not has_controlled_reversal
            ):
                return block(
                    "Reversao simples contra regime bear.",
                    "market_regime",
                    list(regime_evaluation.get("notes", []) or []),
                )
            if regime == "range" and volatility_state == "low_volatility":
                if structure_state not in {"breakout"}:
                    return block(
                        "Mercado lateral sem edge suficiente.",
                        "market_regime",
                        list(regime_evaluation.get("notes", []) or []),
                    )

        if market_regime == "ranging":
            if structure_state not in TREND_STRUCTURE_STATES or price_location == "mid_range":
                return block("Mercado lateral demais para operar.", "market_regime", ["regime lateral"])

        if atr_pct is not None and not pd.isna(atr_pct):
            effective_min_atr_pct = min_atr_pct if min_atr_pct is not None else 0.12
            if float(atr_pct) < float(effective_min_atr_pct):
                return block(
                    "ATR muito baixo; volatilidade insuficiente para a entrada.",
                    "atr_floor",
                    [f"atr_pct {float(atr_pct):.4f} abaixo do minimo"],
                )

        if require_trend and adx is not None and min_adx_threshold is not None and not pd.isna(adx):
            relax_factor = 0.82 if structure_state in TREND_STRUCTURE_STATES and structure_quality >= 6.0 else 0.9
            if is_higher_tf:
                relax_factor -= 0.06
            effective_min_adx = float(min_adx_threshold) * max(0.72, relax_factor)
            if float(adx) < effective_min_adx:
                return block("ADX fraco; sem forca direcional suficiente.", "adx_floor", [f"adx {float(adx):.2f}"])

        if require_volume and volume_ratio is not None and min_volume_ratio is not None and not pd.isna(volume_ratio):
            volume_relax_factor = 0.82 if structure_state in TREND_STRUCTURE_STATES and structure_quality >= 6.0 else 0.9
            if is_higher_tf:
                volume_relax_factor -= 0.06
            base_volume_floor = 0.90 if is_higher_tf else 0.95
            effective_min_volume_ratio = max(
                base_volume_floor,
                float(min_volume_ratio) * max(0.72, volume_relax_factor),
            )
            if float(volume_ratio) < effective_min_volume_ratio:
                return block(
                    "Volume muito fraco para validar a entrada.",
                    "volume_floor",
                    [f"volume_ratio {float(volume_ratio):.2f} abaixo do minimo"],
                )

        if structure_evaluation and structure_evaluation.get("has_minimum_history"):
            reversal_risk = bool(structure_evaluation.get("reversal_risk", structure_state == "reversal_risk"))
            against_market_bias = bool(structure_evaluation.get("against_market_bias", reversal_risk))
            if structure_state == "weak_structure":
                structure_confirmation_state = str((confirmation_evaluation or {}).get("confirmation_state") or "weak")
                weak_structure_floor = (
                    4.1
                    if structure_confirmation_state == "confirmed" and price_location in {"trend_zone", "support", "resistance"}
                    else 4.4
                )
                if structure_quality >= weak_structure_floor and price_location in {"trend_zone", "support", "resistance"}:
                    notes.append("estrutura fraca tolerada por qualidade minima em zona operacional")
                else:
                    return block(
                        structure_evaluation.get("reason") or "Estrutura ruim para entrada.",
                        "price_structure",
                        structure_evaluation.get("notes", []),
                    )
            elif reversal_risk and against_market_bias:
                return block(
                    structure_evaluation.get("reason") or "Estrutura mostra risco de reversao contra o vies.",
                    "price_structure",
                    structure_evaluation.get("notes", []),
                )
            elif structure_quality < (4.2 if structure_state in TREND_STRUCTURE_STATES and price_location == "trend_zone" else 4.5):
                return block(
                    "Qualidade estrutural abaixo do minimo para operar.",
                    "price_structure_quality",
                    [f"structure_quality {structure_quality:.2f}"],
                )

        if confirmation_evaluation and confirmation_evaluation.get("has_minimum_history"):
            confirmation_state = confirmation_evaluation.get("confirmation_state", "weak")
            conflicts = confirmation_evaluation.get("conflicts", []) or []
            if confirmation_state == "weak":
                return block(
                    conflicts[0] if conflicts else "Conflito tecnico forte entre indicadores.",
                    "technical_confirmation",
                    list(conflicts) + list(confirmation_evaluation.get("notes", []) or []),
                )

        if entry_quality_evaluation and entry_quality_evaluation.get("has_minimum_history"):
            setup_type = str(entry_quality_evaluation.get("setup_type") or "").strip().lower()
            if setup_type == "pullback_trend":
                contra_structure = (
                    bool((structure_evaluation or {}).get("against_market_bias", False))
                    or structure_state in {"reversal_risk", "weak_structure"}
                    or structure_state not in ({"pullback"} | CONTINUATION_STRUCTURE_STATES)
                )
                if contra_structure:
                    return block(
                        "Setup pullback_trend contra estrutura vigente.",
                        "setup_filter",
                        list(entry_quality_evaluation.get("notes", []) or []),
                    )
                if structure_state == "pullback":
                    notes.append("setup pullback_trend alinhado com estrutura de pullback")
                else:
                    notes.append("setup pullback_trend sem pullback claro; continuidade valida com peso reduzido")

            entry_quality_label = self._normalize_entry_quality_label(entry_quality_evaluation.get("entry_quality"))
            soft_bad_entry = self._is_soft_entry_rejection(
                entry_quality_evaluation,
                structure_state=structure_state,
                structure_quality=structure_quality,
                confirmation_state=str((confirmation_evaluation or {}).get("confirmation_state") or "weak"),
            )
            entry_quality_evaluation["soft_bad_entry"] = soft_bad_entry
            if entry_quality_label == "bad":
                conflicts = entry_quality_evaluation.get("conflicts", []) or []
                rejection_reason = entry_quality_evaluation.get("rejection_reason")
                if soft_bad_entry:
                    notes.append("qualidade de entrada ruim suavizada por contexto estrutural forte")
                else:
                    fallback_reason = "Qualidade da entrada ruim."
                    if conflicts:
                        fallback_reason = str(conflicts[0])
                    elif rejection_reason:
                        fallback_reason = str(rejection_reason)
                    elif entry_quality_evaluation.get("reason"):
                        raw_reason = str(entry_quality_evaluation.get("reason") or "").strip()
                        if raw_reason and "|" not in raw_reason:
                            fallback_reason = raw_reason
                    return block(
                        fallback_reason,
                        "entry_quality",
                        list(conflicts) + list(entry_quality_evaluation.get("notes", []) or []),
                    )

        if notes:
            evaluation["notes"] = list(dict.fromkeys(str(note) for note in notes if note))
        self._last_hard_block_evaluation = evaluation
        return evaluation

    def get_hard_block_evaluation(
        self,
        signal: str,
        context_evaluation: Optional[Dict[str, object]] = None,
        regime_evaluation: Optional[Dict[str, object]] = None,
        structure_evaluation: Optional[Dict[str, object]] = None,
        confirmation_evaluation: Optional[Dict[str, object]] = None,
        entry_quality_evaluation: Optional[Dict[str, object]] = None,
        market_regime: Optional[str] = None,
        require_volume: bool = False,
        volume_ratio: Optional[float] = None,
        min_volume_ratio: Optional[float] = None,
        require_trend: bool = False,
        adx: Optional[float] = None,
        min_adx_threshold: Optional[float] = None,
        atr_pct: Optional[float] = None,
        min_atr_pct: Optional[float] = None,
        runtime_allowed: Optional[bool] = None,
        runtime_block_reason: Optional[str] = None,
        active_profile: Optional[Dict[str, object]] = None,
        risk_plan: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        return self.check_hard_blocks(
            signal=signal,
            context_evaluation=context_evaluation,
            regime_evaluation=regime_evaluation,
            structure_evaluation=structure_evaluation,
            confirmation_evaluation=confirmation_evaluation,
            entry_quality_evaluation=entry_quality_evaluation,
            market_regime=market_regime,
            require_volume=require_volume,
            volume_ratio=volume_ratio,
            min_volume_ratio=min_volume_ratio,
            require_trend=require_trend,
            adx=adx,
            min_adx_threshold=min_adx_threshold,
            atr_pct=atr_pct,
            min_atr_pct=min_atr_pct,
            runtime_allowed=runtime_allowed,
            runtime_block_reason=runtime_block_reason,
            active_profile=active_profile,
            risk_plan=risk_plan,
        )

    def _fetch_context_df(self, context_timeframe: str, limit: int = 260) -> Optional[pd.DataFrame]:
        if not context_timeframe or context_timeframe == self.timeframe:
            return None
        return self.get_market_data(limit=limit, symbol=self.symbol, timeframe=context_timeframe)

    def _apply_context_alignment(self, signal: str, context_evaluation: Optional[Dict[str, object]]) -> str:
        if signal not in {"COMPRA", "COMPRA_FRACA", "VENDA", "VENDA_FRACA"}:
            return signal
        if not context_evaluation:
            return signal

        bias = context_evaluation.get("market_bias") or context_evaluation.get("bias", "neutral")
        raw_context_strength = context_evaluation.get("context_strength", context_evaluation.get("strength"))
        has_explicit_strength = raw_context_strength is not None
        context_strength = float(raw_context_strength or 0.0)
        strong_context_conflict = (
            not has_explicit_strength
            or (context_strength >= 6.2 and context_evaluation.get("is_tradeable", True))
        )
        if signal.startswith("COMPRA") and bias == "bearish":
            if strong_context_conflict:
                return "NEUTRO"
            return "COMPRA_FRACA"
        if signal.startswith("VENDA") and bias == "bullish":
            if strong_context_conflict:
                return "NEUTRO"
            return "VENDA_FRACA"
        return signal

    def _apply_structure_alignment(self, signal: str, structure_evaluation: Optional[Dict[str, object]]) -> str:
        actionable_signals = {"COMPRA", "COMPRA_FRACA", "VENDA", "VENDA_FRACA"}
        if signal not in actionable_signals:
            return signal
        if not structure_evaluation or not structure_evaluation.get("has_minimum_history"):
            return signal

        structure_state = structure_evaluation.get("structure_state", "weak_structure")
        price_location = structure_evaluation.get("price_location", "mid_range")
        structure_quality = float(structure_evaluation.get("structure_quality", 0.0) or 0.0)
        resistance_zone_distance = float(structure_evaluation.get("resistance_zone_distance", 1.0) or 1.0)
        support_zone_distance = float(structure_evaluation.get("support_zone_distance", 1.0) or 1.0)
        reversal_risk = bool(structure_evaluation.get("reversal_risk", structure_state == "reversal_risk"))
        against_market_bias = bool(structure_evaluation.get("against_market_bias", reversal_risk))

        if structure_state == "weak_structure":
            if structure_quality >= 4.4 and price_location in {"trend_zone", "support", "resistance"}:
                if signal.startswith("COMPRA"):
                    return "COMPRA_FRACA"
                if signal.startswith("VENDA"):
                    return "VENDA_FRACA"
            return "NEUTRO"
        if reversal_risk and against_market_bias:
            return "NEUTRO"
        minimum_structure_quality = 4.5
        if structure_state in TREND_STRUCTURE_STATES and price_location == "trend_zone":
            minimum_structure_quality = 4.2
        if structure_quality < minimum_structure_quality:
            return "NEUTRO"
        if signal.startswith("COMPRA") and price_location == "resistance" and structure_state != "breakout":
            if structure_state in ({"pullback"} | CONTINUATION_STRUCTURE_STATES) and structure_quality >= 5.0 and resistance_zone_distance > 0.03:
                return "COMPRA_FRACA"
            return "NEUTRO"
        if signal.startswith("VENDA") and price_location == "support" and structure_state != "breakout":
            if structure_state in ({"pullback"} | CONTINUATION_STRUCTURE_STATES) and structure_quality >= 5.0 and support_zone_distance > 0.03:
                return "VENDA_FRACA"
            return "NEUTRO"
        return signal

    def _apply_confirmation_alignment(
        self,
        signal: str,
        confirmation_evaluation: Optional[Dict[str, object]],
    ) -> str:
        actionable_signals = {"COMPRA", "COMPRA_FRACA", "VENDA", "VENDA_FRACA"}
        if signal not in actionable_signals:
            return signal
        if not confirmation_evaluation or not confirmation_evaluation.get("has_minimum_history"):
            return signal

        confirmation_state = confirmation_evaluation.get("confirmation_state", "weak")
        if confirmation_state == "weak":
            return "NEUTRO"
        if confirmation_state == "mixed":
            if signal == "COMPRA":
                return "COMPRA_FRACA"
            if signal == "VENDA":
                return "VENDA_FRACA"
        return signal

    def _apply_entry_quality_alignment(
        self,
        signal: str,
        entry_quality_evaluation: Optional[Dict[str, object]],
    ) -> str:
        actionable_signals = {"COMPRA", "COMPRA_FRACA", "VENDA", "VENDA_FRACA"}
        if signal not in actionable_signals:
            return signal
        if not entry_quality_evaluation or not entry_quality_evaluation.get("has_minimum_history"):
            return signal

        entry_quality = self._normalize_entry_quality_label(entry_quality_evaluation.get("entry_quality", "bad"))
        if entry_quality == "bad":
            if bool(entry_quality_evaluation.get("soft_bad_entry")):
                if signal == "COMPRA":
                    return "COMPRA_FRACA"
                if signal == "VENDA":
                    return "VENDA_FRACA"
                return signal
            return "NEUTRO"
        if entry_quality == "acceptable":
            should_downgrade = (
                bool(entry_quality_evaluation.get("late_entry"))
                or bool(entry_quality_evaluation.get("stretched_price"))
                or float(entry_quality_evaluation.get("entry_score", entry_quality_evaluation.get("quality_score", 0.0)) or 0.0) < 6.0
            )
            if should_downgrade:
                if signal == "COMPRA":
                    return "COMPRA_FRACA"
                if signal == "VENDA":
                    return "VENDA_FRACA"
        return signal

    def _apply_scenario_score_alignment(
        self,
        signal: str,
        scenario_evaluation: Optional[Dict[str, object]],
    ) -> str:
        actionable_signals = {"COMPRA", "COMPRA_FRACA", "VENDA", "VENDA_FRACA"}
        if signal not in actionable_signals:
            return signal
        if not scenario_evaluation or not scenario_evaluation.get("has_minimum_history", True):
            return signal

        scenario_score = float(scenario_evaluation.get("scenario_score", 0.0) or 0.0)
        scenario_grade = str(scenario_evaluation.get("scenario_grade", "D") or "D").upper()
        if scenario_grade == "D" or scenario_score < 4.5:
            return "NEUTRO"
        if scenario_grade == "C":
            if signal == "COMPRA":
                return "COMPRA_FRACA"
            if signal == "VENDA":
                return "VENDA_FRACA"
        return signal

    @staticmethod
    def _map_trade_decision_to_signal(
        trade_decision: Optional[Dict[str, object]],
        current_signal: str = "NEUTRO",
    ) -> str:
        if not trade_decision:
            return current_signal

        action = str(trade_decision.get("action") or "wait").lower()
        confidence = float(trade_decision.get("confidence", 0.0) or 0.0)
        if action == "wait":
            return "NEUTRO"
        if action == "buy":
            if current_signal == "COMPRA_FRACA" or confidence < 7.0:
                return "COMPRA_FRACA"
            return "COMPRA"
        if action == "sell":
            if current_signal == "VENDA_FRACA" or confidence < 7.0:
                return "VENDA_FRACA"
            return "VENDA"
        return "NEUTRO"

    @staticmethod
    def _build_decision_context(
        signal: str,
        context_evaluation: Optional[Dict[str, object]],
        confirmation_evaluation: Optional[Dict[str, object]],
    ) -> Optional[Dict[str, object]]:
        current_context = dict(context_evaluation or {})
        current_bias = str(
            current_context.get("market_bias")
            or current_context.get("bias")
            or ""
        )
        if current_bias in {"bullish", "bearish"}:
            return current_context

        derived_bias = None
        if str(signal).startswith("COMPRA"):
            derived_bias = "bullish"
        elif str(signal).startswith("VENDA"):
            derived_bias = "bearish"
        else:
            confirmation_bias = str((confirmation_evaluation or {}).get("hypothesis_side") or "")
            if confirmation_bias in {"bullish", "bearish"}:
                derived_bias = confirmation_bias

        if not derived_bias:
            return current_context or None

        current_context["market_bias"] = derived_bias
        current_context["bias"] = derived_bias
        current_context.setdefault("is_tradeable", True)
        return current_context

    def _apply_signal_guardrails(
        self,
        signal: str,
        context_evaluation: Optional[Dict[str, object]] = None,
        regime_evaluation: Optional[Dict[str, object]] = None,
        structure_evaluation: Optional[Dict[str, object]] = None,
        confirmation_evaluation: Optional[Dict[str, object]] = None,
        entry_quality_evaluation: Optional[Dict[str, object]] = None,
        scenario_evaluation: Optional[Dict[str, object]] = None,
        market_regime: Optional[str] = None,
        require_volume: bool = False,
        volume_ratio: Optional[float] = None,
        min_volume_ratio: Optional[float] = None,
        require_trend: bool = False,
        adx: Optional[float] = None,
        min_adx_threshold: Optional[float] = None,
        atr_pct: Optional[float] = None,
        min_atr_pct: Optional[float] = None,
    ) -> str:
        hard_block_evaluation = self.check_hard_blocks(
            signal=signal,
            context_evaluation=context_evaluation,
            regime_evaluation=regime_evaluation,
            structure_evaluation=structure_evaluation,
            confirmation_evaluation=confirmation_evaluation,
            entry_quality_evaluation=entry_quality_evaluation,
            market_regime=market_regime,
            require_volume=require_volume,
            volume_ratio=volume_ratio,
            min_volume_ratio=min_volume_ratio,
            require_trend=require_trend,
            adx=adx,
            min_adx_threshold=min_adx_threshold,
            atr_pct=atr_pct,
            min_atr_pct=min_atr_pct,
        )
        if hard_block_evaluation.get("hard_block"):
            self.make_trade_decision(
                self._build_decision_context(signal, context_evaluation, confirmation_evaluation),
                structure_evaluation,
                confirmation_evaluation,
                entry_quality_evaluation,
                hard_block_evaluation,
                scenario_evaluation,
            )
            return "NEUTRO"
        if signal not in {"COMPRA", "COMPRA_FRACA", "VENDA", "VENDA_FRACA"}:
            self._last_trade_decision = {
                "action": "wait",
                "confidence": float((scenario_evaluation or {}).get("scenario_score", 0.0) or 0.0),
                "market_bias": str(
                    (context_evaluation or {}).get("market_bias")
                    or (context_evaluation or {}).get("bias")
                    or (confirmation_evaluation or {}).get("hypothesis_side")
                    or "neutral"
                ),
                "setup_type": (structure_evaluation or {}).get("structure_state"),
                "entry_reason": None,
                "block_reason": "Hipotese base neutra.",
                "invalid_if": None,
            }
            return signal

        guarded_signal = self._apply_structure_alignment(signal, structure_evaluation)
        if guarded_signal == "NEUTRO":
            decision = self.make_trade_decision(
                self._build_decision_context(signal, context_evaluation, confirmation_evaluation),
                structure_evaluation,
                confirmation_evaluation,
                entry_quality_evaluation,
                hard_block_evaluation,
                scenario_evaluation,
            )
            return self._map_trade_decision_to_signal(decision, guarded_signal)
        guarded_signal = self._apply_confirmation_alignment(guarded_signal, confirmation_evaluation)
        if guarded_signal == "NEUTRO":
            decision = self.make_trade_decision(
                self._build_decision_context(signal, context_evaluation, confirmation_evaluation),
                structure_evaluation,
                confirmation_evaluation,
                entry_quality_evaluation,
                hard_block_evaluation,
                scenario_evaluation,
            )
            return self._map_trade_decision_to_signal(decision, guarded_signal)
        guarded_signal = self._apply_entry_quality_alignment(guarded_signal, entry_quality_evaluation)
        if guarded_signal == "NEUTRO":
            decision = self.make_trade_decision(
                self._build_decision_context(signal, context_evaluation, confirmation_evaluation),
                structure_evaluation,
                confirmation_evaluation,
                entry_quality_evaluation,
                hard_block_evaluation,
                scenario_evaluation,
            )
            return self._map_trade_decision_to_signal(decision, guarded_signal)
        guarded_signal = self._apply_context_alignment(guarded_signal, context_evaluation)
        if guarded_signal == "NEUTRO":
            decision = self.make_trade_decision(
                self._build_decision_context(signal, context_evaluation, confirmation_evaluation),
                structure_evaluation,
                confirmation_evaluation,
                entry_quality_evaluation,
                hard_block_evaluation,
                scenario_evaluation,
            )
            return self._map_trade_decision_to_signal(decision, guarded_signal)
        decision = self.make_trade_decision(
            self._build_decision_context(guarded_signal, context_evaluation, confirmation_evaluation),
            structure_evaluation,
            confirmation_evaluation,
            entry_quality_evaluation,
            hard_block_evaluation,
            scenario_evaluation,
        )
        return self._map_trade_decision_to_signal(decision, guarded_signal)

    def calculate_indicators(self, df):
        """Calculate comprehensive technical indicators for the dataframe"""
        # Basic indicators
        logger.debug("Calculando RSI com periodo %s", self.rsi_period)
        df['rsi'] = self.indicators.calculate_rsi(df['close'], self.rsi_period)

        # Debug: Mostrar valores atuais do RSI
        current_rsi = df['rsi'].iloc[-1] if not df['rsi'].empty else None
        if current_rsi is not None and not pd.isna(current_rsi):
            logger.debug(
                "RSI atual: %.2f (Min: %s, Max: %s)",
                current_rsi,
                self.rsi_min,
                self.rsi_max
            )
        else:
            logger.warning("RSI nao calculado ou invalido")

        # Multiple moving averages for trend analysis
        smas = self.indicators.calculate_multiple_sma(df['close'], periods=[21, 50, 200])
        df['sma_21'] = smas['sma_21']
        df['sma_50'] = smas['sma_50']
        df['sma_200'] = smas['sma_200']
        df['sma_20'] = df['close'].rolling(window=20).mean()
        df['ema_21'] = df['close'].ewm(span=21, adjust=False).mean()
        df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()

        # MACD
        macd_data = self.indicators.calculate_macd(df['close'])
        df['macd'] = macd_data['macd']
        df['macd_signal'] = macd_data['signal']
        df['macd_histogram'] = macd_data['histogram']
        df['prev_macd_histogram'] = df['macd_histogram'].shift(1)

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
        df['prev_close'] = df['close'].shift(1)
        df['prev_rsi'] = df['rsi'].shift(1)

        # Market regime detection
        df['market_regime'] = 'trending'  # Default
        if len(df) >= 50:
            for i in range(49, len(df)):
                regime = self.indicators.detect_market_regime(
                    df['close'].iloc[max(0, i-20):i+1],
                    df['volume'].iloc[max(0, i-20):i+1],
                    df['atr'].iloc[max(0, i-20):i+1],
                    df['adx'].iloc[max(0, i-20):i+1],
                    di_plus=df['di_plus'].iloc[max(0, i-20):i+1],
                    di_minus=df['di_minus'].iloc[max(0, i-20):i+1],
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
        """Generate optimized trading signal with special 5m timeframe optimization"""
        # Skip if basic indicators are missing
        if pd.isna(row['rsi']) or pd.isna(row['macd']) or pd.isna(row['macd_signal']):
            return "NEUTRO"

        # Otimização específica para 5m - filtros mais rigorosos
        timeframe = getattr(self, 'timeframe', '5m')
        
        if timeframe == '5m':
            # Para 5m, exigir condições mais específicas
            market_regime = row.get('market_regime', 'trending')
            if market_regime == 'ranging':
                return "NEUTRO"  # Evitar mercados laterais em 5m
            
            # ADX mais restritivo para 5m
            adx = row.get('adx', 0)
            if not pd.isna(adx) and adx < 25:  # Aumentado de 18 para 25
                return "NEUTRO"
            
            # Filtro de volatilidade mais restritivo para 5m
            bb_width = row.get('bb_width', 0)
            atr = row.get('atr', 0)
            if not pd.isna(bb_width) and not pd.isna(atr):
                # Tolerância menor para 5m
                if bb_width > 0.15 or atr > row.get('close', 1) * 0.05:  # Mais restritivo
                    return "NEUTRO"
        else:
            # Configurações originais para outros timeframes
            market_regime = row.get('market_regime', 'trending')
            adx = row.get('adx', 0)
            if not pd.isna(adx) and adx < 18:
                return "NEUTRO"
            
            bb_width = row.get('bb_width', 0)
            atr = row.get('atr', 0)
            if not pd.isna(bb_width) and not pd.isna(atr):
                if bb_width > 0.25 or atr > row.get('close', 1) * 0.08:
                    return "NEUTRO"

        # Core indicators with optimized thresholds
        rsi = row['rsi']
        stoch_rsi_k = row.get('stoch_rsi_k', 50)
        williams_r = row.get('williams_r', -50)
        macd = row['macd']
        macd_signal = row['macd_signal']
        macd_histogram = row['macd_histogram']

        # Enhanced trend analysis
        price = row['close']
        sma_21 = row.get('sma_21', price)
        sma_50 = row.get('sma_50', price)
        sma_200 = row.get('sma_200', price)

        # Multi-timeframe trend alignment
        price_above_sma21 = price > sma_21
        sma21_above_sma50 = sma_21 > sma_50 if not pd.isna(sma_50) else True
        sma50_above_sma200 = sma_50 > sma_200 if not pd.isna(sma_200) else True

        # Volume analysis with multiple confirmations
        volume_ratio = row.get('volume_ratio', 1)
        strong_volume = volume_ratio > 1.5  # Increased threshold
        exceptional_volume = volume_ratio > 2.0  # New threshold

        # Bollinger Bands with dynamic thresholds
        bb_upper = row.get('bb_upper', price)
        bb_middle = row.get('bb_middle', price)
        bb_lower = row.get('bb_lower', price)
        bb_position = (price - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5

        # Sistema de scoring otimizado especialmente para 5m
        bullish_score = 0
        bearish_score = 0
        confidence_multiplier = 1.0

        # Usar os thresholds configurados no dashboard
        rsi_oversold_threshold = self.rsi_min if hasattr(self, 'rsi_min') else 20
        rsi_overbought_threshold = self.rsi_max if hasattr(self, 'rsi_max') else 80
        
        # Multiplicador especial para 5m
        if timeframe == '5m':
            confidence_multiplier = 1.2  # Aumentar exigência base para 5m

        # RSI scoring mais seletivo - evitar zonas moderadas amplas demais
        oversold_extreme = rsi_oversold_threshold - 5  # Zona extrema de compra
        oversold_moderate = rsi_oversold_threshold + 8
        overbought_moderate = rsi_overbought_threshold - 8
        overbought_extreme = rsi_overbought_threshold + 5  # Zona extrema de venda

        if rsi <= oversold_extreme:  # Extremo oversold (usuário definiu)
            bullish_score += 5
            confidence_multiplier += 0.3
        elif rsi <= rsi_oversold_threshold:  # Oversold configurado pelo usuário
            bullish_score += 4
            confidence_multiplier += 0.2
        elif rsi <= oversold_moderate:
            bullish_score += 2
        elif rsi >= overbought_extreme:  # Extremo overbought (usuário definiu)
            bearish_score += 5
            confidence_multiplier += 0.3
        elif rsi >= rsi_overbought_threshold:  # Overbought configurado pelo usuário
            bearish_score += 4
            confidence_multiplier += 0.2
        elif rsi >= overbought_moderate:
            bearish_score += 2

        # Enhanced Stochastic RSI (more sensitive)
        if not pd.isna(stoch_rsi_k):
            if stoch_rsi_k < 15:  # Extreme oversold
                bullish_score += 3
                confidence_multiplier += 0.1
            elif stoch_rsi_k < 25:
                bullish_score += 2
            elif stoch_rsi_k > 85:  # Extreme overbought
                bearish_score += 3
                confidence_multiplier += 0.1
            elif stoch_rsi_k > 75:
                bearish_score += 2

        # Williams %R with tighter levels
        if not pd.isna(williams_r):
            if williams_r < -85:  # Extreme oversold
                bullish_score += 3
            elif williams_r < -75:
                bullish_score += 2
            elif williams_r > -15:  # Extreme overbought
                bearish_score += 3
            elif williams_r > -25:
                bearish_score += 2

        # MACD with momentum analysis
        macd_bullish = macd > macd_signal and macd_histogram > 0
        macd_bearish = macd < macd_signal and macd_histogram < 0
        macd_strengthening = abs(macd_histogram) > abs(row.get('prev_macd_histogram', 0))

        if macd_bullish:
            bullish_score += 3 if macd_strengthening else 2
            if macd > 0:  # Above zero line
                bullish_score += 1
        elif macd_bearish:
            bearish_score += 3 if macd_strengthening else 2
            if macd < 0:  # Below zero line
                bearish_score += 1

        # Enhanced trend alignment (higher weight)
        trend_score = 0
        if price_above_sma21 and sma21_above_sma50 and sma50_above_sma200:
            trend_score = 5  # Strong uptrend
            bullish_score += trend_score
        elif not price_above_sma21 and not sma21_above_sma50 and not sma50_above_sma200:
            trend_score = 5  # Strong downtrend
            bearish_score += trend_score
        elif price_above_sma21 and sma21_above_sma50:
            trend_score = 3  # Medium uptrend
            bullish_score += trend_score
        elif not price_above_sma21 and not sma21_above_sma50:
            trend_score = 3  # Medium downtrend
            bearish_score += trend_score

        # Volume confirmation with enhanced scoring
        if exceptional_volume:
            if bullish_score > bearish_score:
                bullish_score += 3
                confidence_multiplier += 0.15
            elif bearish_score > bullish_score:
                bearish_score += 3
                confidence_multiplier += 0.15
        elif strong_volume:
            if bullish_score > bearish_score:
                bullish_score += 2
            elif bearish_score > bullish_score:
                bearish_score += 2

        # Bollinger Bands mean reversion + momentum
        if bb_position < 0.1 and bullish_score > 0:  # Near lower band
            bullish_score += 2
        elif bb_position > 0.9 and bearish_score > 0:  # Near upper band
            bearish_score += 2
        elif bb_position < 0.3 and macd_bullish:  # Mean reversion setup
            bullish_score += 1
        elif bb_position > 0.7 and macd_bearish:  # Mean reversion setup
            bearish_score += 1

        # ADX trend strength bonus (enhanced)
        if not pd.isna(adx):
            if adx > 40:  # Very strong trend
                trend_bonus = 3
                confidence_multiplier += 0.2
            elif adx > 30:  # Strong trend
                trend_bonus = 2
                confidence_multiplier += 0.1
            else:
                trend_bonus = 1

            if bullish_score > bearish_score:
                bullish_score += trend_bonus
            elif bearish_score > bullish_score:
                bearish_score += trend_bonus

        # Divergence detection (if available)
        price_momentum = price - row.get('prev_close', price)
        if not pd.isna(price_momentum) and price_momentum != 0:
            rsi_momentum = rsi - row.get('prev_rsi', rsi)
            if price_momentum > 0 and rsi_momentum < 0:  # Bearish divergence
                bearish_score += 2
            elif price_momentum < 0 and rsi_momentum > 0:  # Bullish divergence
                bullish_score += 2

        # Apply confidence multiplier
        bullish_score = int(bullish_score * confidence_multiplier)
        bearish_score = int(bearish_score * confidence_multiplier)

        # Thresholds otimizados por timeframe
        if timeframe == '5m':
            # Para 5m: menos trades, mais qualidade
            min_strong_signal = 8    # Aumentado de 6 para 8
            min_weak_signal = 6      # Aumentado de 4 para 6
            min_difference = 3       # Aumentado de 2 para 3
        else:
            # Outros timeframes: configuração original
            min_strong_signal = 6
            min_weak_signal = 4
            min_difference = 2

        # Sistema multi-tier otimizado
        if bullish_score >= min_strong_signal + 3 and bullish_score > bearish_score + min_difference + 2:
            return "COMPRA"  # High confidence buy
        elif bearish_score >= min_strong_signal + 3 and bearish_score > bullish_score + min_difference + 2:
            return "VENDA"   # High confidence sell
        elif bullish_score >= min_strong_signal and bullish_score > bearish_score + min_difference:
            return "COMPRA_FRACA"  # Medium confidence buy
        elif bearish_score >= min_strong_signal and bearish_score > bullish_score + min_difference:
            return "VENDA_FRACA"   # Medium confidence sell
        elif timeframe != '5m':  # Só permitir sinais fracos em outros timeframes
            if bullish_score >= min_weak_signal and bullish_score > bearish_score + 1:
                return "COMPRA_FRACA"
            elif bearish_score >= min_weak_signal and bearish_score > bullish_score + 1:
                return "VENDA_FRACA"
        
        return "NEUTRO"

    def _calculate_signal_confidence(self, row):
        """Calculate confidence score for the signal"""
        indicators_dict = {
            'rsi': row['rsi'],
            'macd': row['macd'],
            'macd_signal': row['macd_signal'],
            'macd_histogram': row['macd_histogram'],
            'prev_macd_histogram': row.get('prev_macd_histogram', 0),
            'trend_analysis': row.get('trend_analysis', 'LATERAL'),
            'trend_strength': row.get('trend_strength', 0),
            'adx': row.get('adx', 0),
            'stoch_rsi_k': row.get('stoch_rsi_k', 50),
            'williams_r': row.get('williams_r', -50),
            'volume_ratio': row.get('volume_ratio', 1),
            'market_regime': row.get('market_regime', 'trending'),
            'hour': getattr(row.name, 'hour', 12),
        }

        return self.indicators.calculate_signal_confidence(indicators_dict)

    def _get_effective_min_confidence(self, min_confidence: float, timeframe: Optional[str]) -> float:
        current_timeframe = timeframe or self.timeframe or "5m"
        if current_timeframe == "5m":
            return float(max(68, min_confidence - 1))
        if current_timeframe == "15m":
            return float(max(66, min_confidence - 1))
        if current_timeframe == "30m":
            return float(max(58, min_confidence - 10))
        if current_timeframe == "1h":
            return float(max(56, min_confidence - 12))
        return float(max(62, min_confidence - 1))

    @staticmethod
    def _relax_low_confidence_signal(
        signal: str,
        confidence: float,
        effective_min_confidence: float,
        timeframe: Optional[str],
    ) -> Optional[str]:
        current_timeframe = timeframe or "5m"
        actionable_signals = {"COMPRA", "COMPRA_FRACA", "VENDA", "VENDA_FRACA"}
        if signal not in actionable_signals:
            return None
        if current_timeframe not in {"30m", "1h"}:
            return None
        if confidence >= effective_min_confidence:
            return signal
        if signal == "COMPRA" and confidence >= effective_min_confidence - 6.0:
            return "COMPRA_FRACA"
        if signal == "VENDA" and confidence >= effective_min_confidence - 6.0:
            return "VENDA_FRACA"
        if signal in {"COMPRA_FRACA", "VENDA_FRACA"} and confidence >= effective_min_confidence - 5.0:
            return signal
        return None

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

    def _passes_signal_structure_guardrail(
        self,
        row,
        signal: str,
        timeframe: str,
        structure_evaluation: Optional[Dict[str, object]] = None,
    ) -> bool:
        """Reject weak entries when the closed candle structure conflicts with the signal side."""
        actionable_signals = {"COMPRA", "COMPRA_FRACA", "VENDA", "VENDA_FRACA"}
        if signal not in actionable_signals or row is None:
            return True

        open_price = row.get("open", np.nan)
        high_price = row.get("high", np.nan)
        low_price = row.get("low", np.nan)
        close_price = row.get("close", np.nan)
        if any(pd.isna(value) for value in (open_price, high_price, low_price, close_price)):
            return True

        candle_range = float(high_price) - float(low_price)
        if candle_range <= 0:
            return False

        timeframe = timeframe or self.timeframe or "5m"
        body_size = abs(float(close_price) - float(open_price))
        body_share = body_size / candle_range
        close_location = (float(close_price) - float(low_price)) / candle_range
        is_short_term = timeframe in {"5m", "15m"}
        is_weak_signal = signal.endswith("_FRACA")
        structure_state = str((structure_evaluation or {}).get("structure_state") or "")
        structure_quality = float((structure_evaluation or {}).get("structure_quality", 0.0) or 0.0)
        price_location = str((structure_evaluation or {}).get("price_location") or "mid_range")
        supportive_structure = (
            structure_state in TREND_STRUCTURE_STATES
            and structure_quality >= 5.0
        )
        body_share_floor = 0.25 if is_short_term else 0.12
        if supportive_structure and not is_short_term:
            body_share_floor = 0.09
        if is_weak_signal:
            body_share_floor += 0.05 if is_short_term else 0.02
        if body_share < body_share_floor:
            return False

        atr_value = row.get("atr", np.nan)
        if not pd.isna(atr_value) and float(atr_value) > 0:
            min_body_vs_atr = 0.18 if is_short_term else 0.06
            if supportive_structure and not is_short_term:
                min_body_vs_atr = 0.04
            if is_weak_signal:
                min_body_vs_atr += 0.05 if is_short_term else 0.02
            if body_size / float(atr_value) < min_body_vs_atr:
                return False

        sma_21 = row.get("sma_21", np.nan)
        max_distance_from_sma_atr = 2.4 if is_short_term else 3.6
        if supportive_structure and not is_short_term:
            max_distance_from_sma_atr = 4.2
        range_vs_atr = (
            candle_range / float(atr_value)
            if not pd.isna(atr_value) and float(atr_value) > 0
            else 1.0
        )
        adverse_wick = (
            float(high_price) - max(float(open_price), float(close_price))
            if signal.startswith("COMPRA")
            else min(float(open_price), float(close_price)) - float(low_price)
        )
        adverse_wick_share = adverse_wick / candle_range if candle_range > 0 else 1.0

        if signal.startswith("COMPRA"):
            allow_soft_close = (
                not is_short_term
                and supportive_structure
                and price_location in {"trend_zone", "support", "resistance"}
                and close_location >= 0.34
                and body_share >= max(body_share_floor, 0.10)
            )
            if float(close_price) <= float(open_price) and not allow_soft_close and not (
                not is_short_term and is_weak_signal and close_location >= 0.60 and body_share >= 0.18
            ):
                return False
            min_close_location = 0.58 if is_short_term else 0.40
            if supportive_structure and not is_short_term:
                min_close_location = 0.34
            if close_location < min_close_location:
                return False
            max_adverse_wick = 0.82 if is_short_term else 0.78
            if supportive_structure and not is_short_term:
                max_adverse_wick = 0.84
            if adverse_wick_share > max_adverse_wick:
                return False
            if (
                not pd.isna(sma_21)
                and not pd.isna(atr_value)
                and float(atr_value) > 0
                and (float(close_price) - float(sma_21)) / float(atr_value) > max_distance_from_sma_atr
            ):
                return False
            max_range_vs_atr = 4.2 if is_short_term else 4.8
            if supportive_structure and not is_short_term:
                max_range_vs_atr = 5.4
            if range_vs_atr > max_range_vs_atr and body_share < (0.42 if is_short_term else 0.28):
                return False
            return True

        allow_soft_close = (
            not is_short_term
            and supportive_structure
            and price_location in {"trend_zone", "support", "resistance"}
            and close_location <= 0.66
            and body_share >= max(body_share_floor, 0.10)
        )
        if float(close_price) >= float(open_price) and not allow_soft_close and not (
            not is_short_term and is_weak_signal and close_location <= 0.40 and body_share >= 0.18
        ):
            return False
        max_close_location = 0.42 if is_short_term else 0.60
        if supportive_structure and not is_short_term:
            max_close_location = 0.66
        if close_location > max_close_location:
            return False
        max_adverse_wick = 0.82 if is_short_term else 0.78
        if supportive_structure and not is_short_term:
            max_adverse_wick = 0.84
        if adverse_wick_share > max_adverse_wick:
            return False
        if (
            not pd.isna(sma_21)
            and not pd.isna(atr_value)
            and float(atr_value) > 0
            and (float(sma_21) - float(close_price)) / float(atr_value) > max_distance_from_sma_atr
        ):
            return False
        max_range_vs_atr = 4.2 if is_short_term else 4.8
        if supportive_structure and not is_short_term:
            max_range_vs_atr = 5.4
        if range_vs_atr > max_range_vs_atr and body_share < (0.42 if is_short_term else 0.28):
            return False
        return True

    def check_signal(self, df, min_confidence=60, require_volume=True, require_trend=False, avoid_ranging=False,
                    crypto_optimized=True, timeframe="5m", day_trading_mode=False, context_df=None,
                    context_timeframe: Optional[str] = None, stop_loss_pct: Optional[float] = None,
                    take_profit_pct: Optional[float] = None):
        """Check trading signal with special optimization for 5m timeframe"""
        if df is None or df.empty:
            self._clear_hard_block()
            return self._set_hard_block("Sem dados fechados suficientes para operar.", "market_data")

        self._last_context_evaluation = None
        self._last_price_structure_evaluation = None
        self._last_confirmation_evaluation = None
        self._last_entry_quality_evaluation = None
        self._last_scenario_evaluation = None
        self._last_trade_decision = None
        self._last_candidate_signal = "NEUTRO"
        self._last_signal_pipeline = None
        self._clear_hard_block()

        df = self._prefer_closed_candles(df)

        if df.empty:
            return self._set_hard_block("Sem candles fechados suficientes para operar.", "market_data")

        last_row = df.iloc[-1]
        signal = None

        # SEMPRE usar as configurações atuais do bot (definidas no dashboard)
        actual_rsi_min = self.rsi_min
        actual_rsi_max = self.rsi_max
        actual_rsi_period = self.rsi_period
        current_timeframe = timeframe or self.timeframe or "5m"
        resolved_context_timeframe = context_timeframe or AppConfig.get_context_timeframe(current_timeframe)
        current_atr_pct = (
            float(last_row.get('atr', 0) or 0.0) / float(last_row.get('close', 1) or 1.0) * 100.0
            if float(last_row.get('close', 1) or 1.0) != 0
            else 0.0
        )
        min_atr_floor_pct = 0.18 if current_timeframe in {"5m", "15m"} else 0.12 if current_timeframe in {"30m", "1h"} else 0.08
        market_regime = last_row.get('market_regime', 'trending')
        context_evaluation = None
        regime_evaluation = self.evaluate_market_regime(df, timeframe=current_timeframe)
        market_regime = regime_evaluation.get("legacy_regime", market_regime)
        structure_evaluation = None
        confirmation_evaluation = None
        entry_quality_evaluation = None
        scenario_evaluation = None

        if resolved_context_timeframe and resolved_context_timeframe != current_timeframe:
            if context_df is None:
                if hasattr(self, "_stream_clients") and getattr(self, "symbol", None):
                    try:
                        context_df = self._fetch_context_df(resolved_context_timeframe)
                    except Exception as exc:
                        logger.warning(
                            "Falha ao obter contexto %s para %s %s: %s",
                            resolved_context_timeframe,
                            self.symbol,
                            current_timeframe,
                            exc,
                        )
                        return self._set_hard_block(
                            "Falha ao carregar o timeframe maior para validar o setup.",
                            "higher_timeframe_context",
                        )
            if context_df is not None:
                context_evaluation = self.get_context_evaluation(
                    context_df=context_df,
                    as_of_timestamp=df.index[-1],
                    context_timeframe=resolved_context_timeframe,
                )

        structure_kwargs = {"timeframe": current_timeframe}
        if context_evaluation or regime_evaluation:
            try:
                structure_signature = inspect.signature(self.get_price_structure_evaluation)
                if "market_bias" in structure_signature.parameters:
                    structure_kwargs["market_bias"] = (
                        (context_evaluation or {}).get("market_bias")
                        or (context_evaluation or {}).get("bias")
                        or regime_evaluation.get("market_bias")
                    )
            except (TypeError, ValueError):
                pass
        structure_evaluation = self.get_price_structure_evaluation(df, **structure_kwargs)
        structure_state = str((structure_evaluation or {}).get("structure_state") or "weak_structure")
        structure_quality = float((structure_evaluation or {}).get("structure_quality", 0.0) or 0.0)
        price_location = str((structure_evaluation or {}).get("price_location") or "mid_range")

        # Quality prefilter: avoid generating candidate signals in dead mid-range structure.
        if (
            current_timeframe in {"30m", "1h", "4h"}
            and structure_state == "weak_structure"
            and price_location == "mid_range"
            and structure_quality < 5.0
        ):
            return self._set_hard_block(
                "Estrutura fraca no meio do range; sem edge para gerar candidato.",
                "price_structure_prefilter",
            )

        if market_regime == 'ranging' and current_timeframe in {"5m", "15m"}:
            return self._set_hard_block("Mercado lateral demais para operar.", "market_regime")

        if market_regime == 'volatile' and current_timeframe in {"5m", "15m"}:
            return self._set_hard_block("Volatilidade desordenada para este timeframe.", "market_regime")
        
        # Aplicar otimizações específicas para 5m
        if current_timeframe == "5m" or self.timeframe == "5m":
            try:
                from config import TimeFrame5mConfig
                signal = self._generate_advanced_signal(last_row)
                current_timestamp = last_row.get('timestamp') if hasattr(last_row, 'get') else None
                if current_timestamp is None and hasattr(df, 'index') and len(df.index) > 0:
                    current_timestamp = df.index[-1]
                current_hour = pd.Timestamp(current_timestamp).hour if current_timestamp is not None else None
                signal = TimeFrame5mConfig.apply_5m_filters(signal, last_row, current_hour)
            except ImportError:
                pass  # Continuar com lógica normal se config não existir

        # Configurações otimizadas para mais trades com melhor precisão
        if day_trading_mode:
            day_settings = AppConfig.get_day_trading_settings(timeframe)

            min_confidence = max(68, day_settings['min_confidence'] - 2)
            min_volume_ratio = max(1.4, day_settings['min_volume_ratio'])
            volatility_threshold = day_settings['volatility_filter'] * 1.1
            min_adx_threshold = max(24, day_settings['min_adx'] * 0.9)

            logger.debug(
                "Day trading otimizado - RSI: %s-%s, Conf: %s%%",
                actual_rsi_min,
                actual_rsi_max,
                min_confidence
            )

            # Less restrictive time filters
            current_hour = last_row.get('timestamp', pd.Timestamp.now()).hour
            # Removed lunch time filter to allow more trades

        elif crypto_optimized:
            crypto_settings = AppConfig.get_crypto_timeframe_settings(timeframe)

            min_confidence = max(64, crypto_settings['min_confidence'])
            min_volume_ratio = max(1.3, crypto_settings['min_volume_ratio'])
            volatility_threshold = crypto_settings['volatility_filter'] * 1.05
            min_adx_threshold = max(24, crypto_settings.get('min_adx', 20))

            if current_timeframe == "5m":
                min_confidence = max(min_confidence, 68)
                min_volume_ratio = max(min_volume_ratio, 1.6)
                min_adx_threshold = max(min_adx_threshold, 28)
            elif current_timeframe == "15m":
                min_confidence = max(min_confidence, 66)
                min_volume_ratio = max(min_volume_ratio, 1.4)
                min_adx_threshold = max(min_adx_threshold, 25)
            elif current_timeframe in {"30m", "1h"}:
                min_volume_ratio = max(0.92, min_volume_ratio * 0.78)
                min_adx_threshold = max(18, min_adx_threshold * 0.78)

            logger.debug(
                "Crypto otimizado - RSI: %s-%s, Conf: %s%%",
                actual_rsi_min,
                actual_rsi_max,
                min_confidence
            )

            # More permissive filters for crypto markets
            # Removed ranging market filter - crypto can be profitable in ranging markets
            
            # Optional trend requirement (less strict)
            if require_trend and last_row.get('adx', 0) < min_adx_threshold:
                return self._set_hard_block("ADX fraco; sem forca direcional suficiente.", "adx_floor")

            # More lenient volume requirement
            if require_volume and last_row.get('volume_ratio', 1) < min_volume_ratio:
                return self._set_hard_block("Volume muito fraco para validar a entrada.", "volume_floor")
        else:
            # More balanced default settings
            min_confidence = 60
            min_volume_ratio = 1.2
            volatility_threshold = 0.08
            min_adx_threshold = 18

            if current_timeframe in {"30m", "1h"}:
                min_volume_ratio = max(0.90, min_volume_ratio * 0.82)
                min_adx_threshold = max(15, min_adx_threshold * 0.82)

            logger.debug(
                "Configuracao padrao otimizada - RSI: %s-%s",
                actual_rsi_min,
                actual_rsi_max
            )

            # Very permissive filters for more opportunities
            if require_trend and last_row.get('adx', 0) < min_adx_threshold:
                return self._set_hard_block("ADX fraco; sem forca direcional suficiente.", "adx_floor")

            if require_volume and last_row.get('volume_ratio', 1) < min_volume_ratio:
                return self._set_hard_block("Volume muito fraco para validar a entrada.", "volume_floor")

        if require_trend and AppConfig.SIMPLE_TREND_SIGNAL_MODE:
            if current_timeframe in {"5m", "15m"} and market_regime != "trending":
                return self._set_hard_block("Mercado sem tendencia suficiente para o setup.", "market_regime")
            if avoid_ranging and current_timeframe in {"5m", "15m"} and market_regime == "ranging":
                return self._set_hard_block("Mercado lateral demais para operar.", "market_regime")
            if last_row.get('adx', 0) < min_adx_threshold:
                return self._set_hard_block("ADX fraco; sem forca direcional suficiente.", "adx_floor")
            if require_volume and last_row.get('volume_ratio', 1) < min_volume_ratio:
                return self._set_hard_block("Volume muito fraco para validar a entrada.", "volume_floor")

            signal = self._generate_trend_signal(last_row, actual_rsi_min, actual_rsi_max)
            if signal == "NEUTRO":
                return self._set_hard_block("Indicadores base nao confirmam hipotese de entrada.", "signal_hypothesis")

            effective_min_confidence = self._get_effective_min_confidence(min_confidence, current_timeframe)

            confidence = self._calculate_signal_confidence(last_row)
            if confidence < effective_min_confidence:
                relaxed_signal = self._relax_low_confidence_signal(
                    signal,
                    confidence,
                    effective_min_confidence,
                    current_timeframe,
                )
                if relaxed_signal is None:
                    return self._set_hard_block("Confianca insuficiente para validar a entrada.", "signal_confidence")
                signal = relaxed_signal

            max_volatility = (volatility_threshold * 100) * 1.5
            if current_atr_pct > max_volatility:
                return self._set_hard_block("ATR excessivo; mercado desordenado para entrada.", "atr_extreme")

            self._last_candidate_signal = signal
            confirmation_evaluation = self.get_confirmation_evaluation(
                df,
                signal_hypothesis=signal,
                timeframe=current_timeframe,
                context_evaluation=context_evaluation,
                structure_evaluation=structure_evaluation,
            )
            entry_quality_evaluation = self.get_entry_quality_evaluation(
                df,
                signal_hypothesis=signal,
                timeframe=current_timeframe,
                regime_evaluation=regime_evaluation,
                structure_evaluation=structure_evaluation,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
            )
            scenario_evaluation = self.build_scenario_score(
                context_evaluation,
                structure_evaluation,
                confirmation_evaluation,
                entry_quality_evaluation,
                regime_result=regime_evaluation,
            )
            return self._apply_signal_guardrails(
                signal,
                context_evaluation,
                regime_evaluation,
                structure_evaluation,
                confirmation_evaluation,
                entry_quality_evaluation,
                scenario_evaluation,
                market_regime=market_regime,
                require_volume=require_volume,
                volume_ratio=last_row.get('volume_ratio', 1),
                min_volume_ratio=min_volume_ratio,
                require_trend=require_trend,
                adx=last_row.get('adx', 0),
                min_adx_threshold=min_adx_threshold,
                atr_pct=current_atr_pct,
                min_atr_pct=min_atr_floor_pct,
            )

        if require_trend:
            if market_regime != "trending":
                return self._set_hard_block("Mercado sem tendencia suficiente para o setup.", "market_regime")
            signal = self._generate_trend_signal(last_row, actual_rsi_min, actual_rsi_max)

        # Gerar sinal usando configurações atuais
        if signal is None:
            signal = self._generate_advanced_signal(last_row)
        confidence = self._calculate_signal_confidence(last_row)

        # Log apenas sinais não-neutros
        if signal != "NEUTRO":
            rsi_atual = last_row.get('rsi', 50)
            logger.info("Sinal %s: RSI %.1f | Confianca %.0f%%", signal, rsi_atual, confidence)

        effective_min_confidence = self._get_effective_min_confidence(min_confidence, current_timeframe)
        if confidence < effective_min_confidence:
            relaxed_signal = self._relax_low_confidence_signal(
                signal,
                confidence,
                effective_min_confidence,
                current_timeframe,
            )
            if relaxed_signal is None:
                logger.debug(
                    "Rejeitado por confianca baixa: %.1f%% < %s%%",
                    confidence,
                    effective_min_confidence
                )
                return self._set_hard_block("Confianca insuficiente para validar a entrada.", "signal_confidence")
            signal = relaxed_signal

        # Relaxed volatility check - crypto markets need volatility
        max_volatility = (volatility_threshold * 100) * 1.5
        if current_atr_pct > max_volatility:
            return self._set_hard_block("ATR excessivo; mercado desordenado para entrada.", "atr_extreme")

        # More intelligent RSI validation
        rsi_atual = last_row.get('rsi', 50)
        
        # Dynamic RSI tolerance based on market conditions
        market_volatility = last_row.get('bb_width', 0.05)
        base_tolerance = 10 if market_volatility > 0.1 else 8
        
        # Smart signal adjustment instead of rejection
        if signal == 'COMPRA':
            # Allow buy signals even if RSI is moderately higher
            if rsi_atual > (actual_rsi_max - base_tolerance):
                logger.debug("COMPRA convertida para FRACA - RSI %.1f", rsi_atual)
                signal = 'COMPRA_FRACA'
        elif signal == 'VENDA':
            # Allow sell signals even if RSI is moderately lower  
            if rsi_atual < (actual_rsi_min + base_tolerance):
                logger.debug("VENDA convertida para FRACA - RSI %.1f", rsi_atual)
                signal = 'VENDA_FRACA'

        # More permissive secondary indicator filters for crypto
        if crypto_optimized:
            # Allow StochRSI in moderate zones
            stoch_rsi_k = last_row.get('stoch_rsi_k', 50)
            if signal in ['COMPRA', 'COMPRA_FRACA'] and stoch_rsi_k > 65:
                logger.debug("Sinal compra ajustado por StochRSI %.1f", stoch_rsi_k)
                if signal == 'COMPRA':
                    signal = 'COMPRA_FRACA'  # Downgrade instead of reject
            if signal in ['VENDA', 'VENDA_FRACA'] and stoch_rsi_k < 35:
                logger.debug("Sinal venda ajustado por StochRSI %.1f", stoch_rsi_k)
                if signal == 'VENDA':
                    signal = 'VENDA_FRACA'  # Downgrade instead of reject

            williams_r = last_row.get('williams_r', -50)
            if signal in ['COMPRA', 'COMPRA_FRACA'] and williams_r > -25:
                if signal == 'COMPRA':
                    signal = 'COMPRA_FRACA'
            if signal in ['VENDA', 'VENDA_FRACA'] and williams_r < -75:
                if signal == 'VENDA':
                    signal = 'VENDA_FRACA'

        self._last_candidate_signal = signal

        confirmation_evaluation = self.get_confirmation_evaluation(
            df,
            signal_hypothesis=signal,
            timeframe=current_timeframe,
            context_evaluation=context_evaluation,
            structure_evaluation=structure_evaluation,
        )
        entry_quality_evaluation = self.get_entry_quality_evaluation(
            df,
            signal_hypothesis=signal,
            timeframe=current_timeframe,
            regime_evaluation=regime_evaluation,
            structure_evaluation=structure_evaluation,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
        )
        scenario_evaluation = self.build_scenario_score(
            context_evaluation,
            structure_evaluation,
            confirmation_evaluation,
            entry_quality_evaluation,
            regime_result=regime_evaluation,
        )

        # Combine rule-based signal with advanced score for robust decision
        advanced_score = self.calculate_advanced_score(last_row, signal=signal)
        self.logger = logger
        logger.debug(f"💡 Advanced score: {advanced_score:.2f}")

        if advanced_score < 0.55 and signal in ['COMPRA', 'VENDA', 'COMPRA_FRACA', 'VENDA_FRACA']:
            logger.debug("📉 score baixo, converte para NEUTRO")
            self._last_candidate_signal = "NEUTRO"
            self._last_trade_decision = {
                "action": "wait",
                "confidence": round(float(max(0.0, min(10.0, advanced_score * 10))), 2),
                "market_bias": str(
                    (context_evaluation or {}).get("market_bias")
                    or (context_evaluation or {}).get("bias")
                    or (confirmation_evaluation or {}).get("hypothesis_side")
                    or "neutral"
                ),
                "setup_type": (structure_evaluation or {}).get("structure_state"),
                "entry_reason": None,
                "block_reason": "Score avancado insuficiente para validar a entrada.",
                "invalid_if": None,
            }
            return "NEUTRO"

        if advanced_score >= 0.82:
            if signal in ['COMPRA', 'COMPRA_FRACA']:
                return self._apply_signal_guardrails(
                    "COMPRA",
                    context_evaluation,
                    regime_evaluation,
                    structure_evaluation,
                    confirmation_evaluation,
                    entry_quality_evaluation,
                    scenario_evaluation,
                    market_regime=market_regime,
                    require_volume=require_volume,
                    volume_ratio=last_row.get('volume_ratio', 1),
                    min_volume_ratio=min_volume_ratio,
                    require_trend=require_trend,
                    adx=last_row.get('adx', 0),
                    min_adx_threshold=min_adx_threshold,
                    atr_pct=current_atr_pct,
                    min_atr_pct=min_atr_floor_pct,
                )
            if signal in ['VENDA', 'VENDA_FRACA']:
                return self._apply_signal_guardrails(
                    "VENDA",
                    context_evaluation,
                    regime_evaluation,
                    structure_evaluation,
                    confirmation_evaluation,
                    entry_quality_evaluation,
                    scenario_evaluation,
                    market_regime=market_regime,
                    require_volume=require_volume,
                    volume_ratio=last_row.get('volume_ratio', 1),
                    min_volume_ratio=min_volume_ratio,
                    require_trend=require_trend,
                    adx=last_row.get('adx', 0),
                    min_adx_threshold=min_adx_threshold,
                    atr_pct=current_atr_pct,
                    min_atr_pct=min_atr_floor_pct,
                )

        if advanced_score >= 0.68:
            return self._apply_signal_guardrails(
                signal,
                context_evaluation,
                regime_evaluation,
                structure_evaluation,
                confirmation_evaluation,
                entry_quality_evaluation,
                scenario_evaluation,
                market_regime=market_regime,
                require_volume=require_volume,
                volume_ratio=last_row.get('volume_ratio', 1),
                min_volume_ratio=min_volume_ratio,
                require_trend=require_trend,
                adx=last_row.get('adx', 0),
                min_adx_threshold=min_adx_threshold,
                atr_pct=current_atr_pct,
                min_atr_pct=min_atr_floor_pct,
            )

        # Se score intermediário e sinal fraco, devolver NEUTRO
        if signal == 'COMPRA' and advanced_score >= 0.62:
            return self._apply_signal_guardrails(
                'COMPRA_FRACA',
                context_evaluation,
                regime_evaluation,
                structure_evaluation,
                confirmation_evaluation,
                entry_quality_evaluation,
                scenario_evaluation,
                market_regime=market_regime,
                require_volume=require_volume,
                volume_ratio=last_row.get('volume_ratio', 1),
                min_volume_ratio=min_volume_ratio,
                require_trend=require_trend,
                adx=last_row.get('adx', 0),
                min_adx_threshold=min_adx_threshold,
                atr_pct=current_atr_pct,
                min_atr_pct=min_atr_floor_pct,
            )
        if signal == 'VENDA' and advanced_score >= 0.62:
            return self._apply_signal_guardrails(
                'VENDA_FRACA',
                context_evaluation,
                regime_evaluation,
                structure_evaluation,
                confirmation_evaluation,
                entry_quality_evaluation,
                scenario_evaluation,
                market_regime=market_regime,
                require_volume=require_volume,
                volume_ratio=last_row.get('volume_ratio', 1),
                min_volume_ratio=min_volume_ratio,
                require_trend=require_trend,
                adx=last_row.get('adx', 0),
                min_adx_threshold=min_adx_threshold,
                atr_pct=current_atr_pct,
                min_atr_pct=min_atr_floor_pct,
            )

        if signal in ['COMPRA_FRACA', 'VENDA_FRACA'] and advanced_score < 0.72:
            logger.debug("🔁 sinal fraco + score médio, NEUTRO")
            self._last_candidate_signal = "NEUTRO"
            self._last_trade_decision = {
                "action": "wait",
                "confidence": round(float(max(0.0, min(10.0, advanced_score * 10))), 2),
                "market_bias": str(
                    (context_evaluation or {}).get("market_bias")
                    or (context_evaluation or {}).get("bias")
                    or (confirmation_evaluation or {}).get("hypothesis_side")
                    or "neutral"
                ),
                "setup_type": (structure_evaluation or {}).get("structure_state"),
                "entry_reason": None,
                "block_reason": "Sinal fraco sem score suficiente para operar.",
                "invalid_if": None,
            }
            return "NEUTRO"

        return self._apply_signal_guardrails(
            signal,
            context_evaluation,
            regime_evaluation,
            structure_evaluation,
            confirmation_evaluation,
            entry_quality_evaluation,
            scenario_evaluation,
            market_regime=market_regime,
            require_volume=require_volume,
            volume_ratio=last_row.get('volume_ratio', 1),
            min_volume_ratio=min_volume_ratio,
            require_trend=require_trend,
            adx=last_row.get('adx', 0),
            min_adx_threshold=min_adx_threshold,
            atr_pct=current_atr_pct,
            min_atr_pct=min_atr_floor_pct,
        )

    def _generate_trend_signal(self, row, rsi_min: float, rsi_max: float) -> str:
        di_plus = row.get("di_plus", 0)
        di_minus = row.get("di_minus", 0)
        macd_hist = row.get("macd_histogram", row.get("macd", 0) - row.get("macd_signal", 0))
        rsi = row.get("rsi", 50)
        adx = row.get("adx", 0)

        if pd.isna(di_plus) or pd.isna(di_minus) or pd.isna(macd_hist) or pd.isna(rsi) or pd.isna(adx):
            return "NEUTRO"
        if adx < 25:
            return "NEUTRO"

        if di_plus > di_minus and macd_hist > 0:
            return "COMPRA" if rsi <= rsi_max else "COMPRA_FRACA"
        if di_minus > di_plus and macd_hist < 0:
            return "VENDA" if rsi >= rsi_min else "VENDA_FRACA"
        return "NEUTRO"

    def get_signal_with_confidence(self, df):
        """Get signal with confidence score"""
        if df is None or df.empty:
            return {"signal": "NEUTRO", "confidence": 0}

        last_row = df.iloc[-1]
        signal = self._generate_advanced_signal(last_row)
        confidence = self._calculate_signal_confidence(last_row)

        return {"signal": signal, "confidence": confidence}

    def calculate_advanced_score(self, row, signal=None):
        """Calculate a direction-aware ensemble score from advanced indicators."""
        if row is None or row.empty:
            return 0.0

        signal = signal or "NEUTRO"
        if signal.startswith("COMPRA"):
            signal_side = "bullish"
        elif signal.startswith("VENDA"):
            signal_side = "bearish"
        else:
            return 0.0

        scores = []

        rsi = row.get('rsi', 50)
        if not np.isnan(rsi):
            if signal_side == "bullish":
                if rsi < 20:
                    scores.append(0.95)
                elif rsi < 30:
                    scores.append(0.78)
                elif rsi < 38:
                    scores.append(0.60)
                elif rsi > 80:
                    scores.append(0.05)
                elif rsi > 70:
                    scores.append(0.18)
                else:
                    scores.append(0.45)
            else:
                if rsi > 80:
                    scores.append(0.95)
                elif rsi > 70:
                    scores.append(0.78)
                elif rsi > 62:
                    scores.append(0.60)
                elif rsi < 20:
                    scores.append(0.05)
                elif rsi < 30:
                    scores.append(0.18)
                else:
                    scores.append(0.45)

        macd = row.get('macd', 0)
        macd_signal = row.get('macd_signal', 0)
        macd_hist = row.get('macd_histogram', 0)
        if not np.isnan(macd) and not np.isnan(macd_signal):
            bullish_alignment = macd > macd_signal and macd_hist > 0
            bearish_alignment = macd < macd_signal and macd_hist < 0
            if (signal_side == "bullish" and bullish_alignment) or (signal_side == "bearish" and bearish_alignment):
                scores.append(0.85)
            elif (signal_side == "bullish" and bearish_alignment) or (signal_side == "bearish" and bullish_alignment):
                scores.append(0.15)
            else:
                scores.append(0.45)

        adx = row.get('adx', 0)
        if not np.isnan(adx):
            if adx > 40:
                scores.append(0.85)
            elif adx > 25:
                scores.append(0.65)
            else:
                scores.append(0.35)

        price = row.get('close', np.nan)
        sma_21 = row.get('sma_21', np.nan)
        sma_50 = row.get('sma_50', np.nan)
        sma_200 = row.get('sma_200', np.nan)
        if not np.isnan(price) and not np.isnan(sma_21):
            bullish_trend = price >= sma_21 and (np.isnan(sma_50) or sma_21 >= sma_50)
            bearish_trend = price <= sma_21 and (np.isnan(sma_50) or sma_21 <= sma_50)
            if signal_side == "bullish":
                scores.append(0.82 if bullish_trend else 0.22)
            else:
                scores.append(0.82 if bearish_trend else 0.22)

        di_plus = row.get('di_plus', np.nan)
        di_minus = row.get('di_minus', np.nan)
        if not np.isnan(di_plus) and not np.isnan(di_minus):
            if signal_side == "bullish":
                scores.append(0.78 if di_plus > di_minus else 0.20)
            else:
                scores.append(0.78 if di_minus > di_plus else 0.20)

        vol_ratio = row.get('volume_ratio', 1.0)
        if not np.isnan(vol_ratio):
            if vol_ratio > 2.0:
                scores.append(0.85)
            elif vol_ratio > 1.3:
                scores.append(0.65)
            else:
                scores.append(0.30)

        market_regime = row.get('market_regime', 'trending')
        if market_regime == 'trending':
            scores.append(0.75)
        elif market_regime == 'ranging':
            scores.append(0.20)
        elif market_regime == 'volatile':
            scores.append(0.25)
        else:
            scores.append(0.5)

        bb_width = row.get('bb_width', np.nan)
        if not np.isnan(bb_width):
            if bb_width > 0.18:
                scores.append(0.20)
            elif bb_width > 0.10:
                scores.append(0.45)
            else:
                scores.append(0.72)

        if not scores:
            return 0.0

        final_score = float(np.mean(scores))
        return min(1.0, max(0.0, final_score))

    def get_market_summary(self, df):
        """Get market summary statistics"""
        if df is None or df.empty:
            return None

        df = self._prefer_closed_candles(df)

        if df.empty:
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
            # Symbol já está no formato correto para Binance (BTC/USDT)
            return symbol in markets
        except:
            return False

    def format_symbol_for_binance(self, symbol):
        """Ensure symbol is in correct format for Binance"""
        # Binance usa formato BTC/USDT
        if not '/' in symbol:
            # Se não tem barra, adicionar /USDT como padrão
            return f"{symbol}/USDT"
        return symbol
