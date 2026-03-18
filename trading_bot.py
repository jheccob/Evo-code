import ccxt
import pandas as pd
import numpy as np
import logging
from datetime import datetime
import os
from typing import Dict, Optional
from indicators import TechnicalIndicators
from config import AppConfig

logger = logging.getLogger(__name__)

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
        self._last_price_structure_evaluation = None

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
        symbol_formatted = symbol.replace('/', '')  # BTC/USDT -> BTCUSDT

        timeframe_map = {
            '1m': '1m', '3m': '3m', '5m': '5m', '15m': '15m',
            '30m': '30m', '1h': '1h', '2h': '2h', '4h': '4h',
            '6h': '6h', '8h': '8h', '12h': '12h', '1d': '1d'
        }

        binance_timeframe = timeframe_map.get(timeframe, '5m')

        endpoints = [
            f"https://api.binance.com/api/v3/klines?symbol={symbol_formatted}&interval={binance_timeframe}&limit={limit}",
            f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol_formatted}&interval={binance_timeframe}&limit={limit}",
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
        try:
            logger.info("Conectando ao stream real de mercado para %s %s", symbol, timeframe)
            df = self._get_realtime_stream_client(symbol=symbol, timeframe=timeframe).get_market_data(limit=limit, timeout=20)
        except Exception as e:
            realtime_error = e
            logger.warning("Falha ao obter dados pelo stream real: %s", e)

        if df is None:
            if not self.allow_simulated_data:
                raise ConnectionError(
                    "Nao foi possivel obter dados reais via stream com failover; fallback simulado esta desabilitado"
                ) from realtime_error

            logger.warning("Stream indisponivel; tentando REST real antes do fallback local")
            try:
                df = self._fetch_public_ohlcv(limit=limit, symbol=symbol, timeframe=timeframe)
                df["is_closed"] = True
            except Exception:
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
            "regime": "range_low_vol",
            "volatility_state": "low_vol",
            "is_tradeable": False,
            "timestamp": None,
            "reason": "Sem contexto configurado.",
        }
        if context_df is None or context_df.empty:
            evaluation["reason"] = "Sem dados de contexto."
            self._last_context_evaluation = evaluation
            return evaluation

        working_df = context_df
        if "is_closed" in working_df.columns:
            closed_context = working_df[working_df["is_closed"].fillna(False)]
            if not closed_context.empty:
                working_df = closed_context
            elif len(working_df) > 1:
                working_df = working_df.iloc[:-1]

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

        context_row = working_df.iloc[-1]
        recent_window = working_df.tail(min(30, len(working_df)))
        price = context_row.get("close", np.nan)
        sma_21 = context_row.get("sma_21", np.nan)
        sma_50 = context_row.get("sma_50", np.nan)
        sma_200 = context_row.get("sma_200", np.nan)
        macd_hist = context_row.get("macd_histogram", context_row.get("macd", 0) - context_row.get("macd_signal", 0))
        adx = context_row.get("adx", np.nan)
        di_plus = context_row.get("di_plus", np.nan)
        di_minus = context_row.get("di_minus", np.nan)
        rsi = context_row.get("rsi", np.nan)
        base_regime = context_row.get("market_regime", "trending")

        sma_21_slope = self._calculate_context_slope(recent_window.get("sma_21"))
        sma_50_slope = self._calculate_context_slope(recent_window.get("sma_50"))
        sma_200_slope = self._calculate_context_slope(recent_window.get("sma_200"))

        atr_pct = float("nan")
        atr_pct_baseline = float("nan")
        atr_series = recent_window.get("atr")
        close_series = recent_window.get("close")
        if atr_series is not None and close_series is not None:
            atr_pct_series = atr_series / close_series.replace(0, np.nan)
            clean_atr_pct = atr_pct_series.dropna()
            if not clean_atr_pct.empty:
                atr_pct = float(clean_atr_pct.iloc[-1])
                atr_pct_baseline = float(clean_atr_pct.median())

        recent_range_pct = float("nan")
        recent_range_baseline = float("nan")
        high_series = recent_window.get("high")
        low_series = recent_window.get("low")
        range_window = min(8, len(recent_window))
        if (
            high_series is not None
            and low_series is not None
            and close_series is not None
            and range_window >= 2
        ):
            rolling_range_pct = (
                high_series.rolling(range_window).max() - low_series.rolling(range_window).min()
            ) / close_series.replace(0, np.nan)
            clean_range = rolling_range_pct.dropna()
            if not clean_range.empty:
                recent_range_pct = float(clean_range.iloc[-1])
                recent_range_baseline = float(clean_range.median())

        bullish_score = 0.0
        bearish_score = 0.0
        directional_reasons = []

        if not pd.isna(price) and not pd.isna(sma_21):
            if float(price) >= float(sma_21):
                bullish_score += 1.0
                directional_reasons.append("preco acima da SMA21")
            else:
                bearish_score += 1.0
                directional_reasons.append("preco abaixo da SMA21")
        if not pd.isna(sma_21) and not pd.isna(sma_50):
            if float(sma_21) >= float(sma_50):
                bullish_score += 1.0
                directional_reasons.append("SMA21 acima da SMA50")
            else:
                bearish_score += 1.0
                directional_reasons.append("SMA21 abaixo da SMA50")
        if not pd.isna(sma_50) and not pd.isna(sma_200):
            if float(sma_50) >= float(sma_200):
                bullish_score += 1.0
                directional_reasons.append("SMA50 acima da SMA200")
            else:
                bearish_score += 1.0
                directional_reasons.append("SMA50 abaixo da SMA200")
        if not pd.isna(sma_21_slope):
            if sma_21_slope > 0:
                bullish_score += 1.0
                directional_reasons.append("SMA21 inclinada para cima")
            elif sma_21_slope < 0:
                bearish_score += 1.0
                directional_reasons.append("SMA21 inclinada para baixo")
        if not pd.isna(sma_50_slope):
            if sma_50_slope > 0:
                bullish_score += 1.0
                directional_reasons.append("SMA50 inclinada para cima")
            elif sma_50_slope < 0:
                bearish_score += 1.0
                directional_reasons.append("SMA50 inclinada para baixo")
        if not pd.isna(macd_hist):
            if float(macd_hist) > 0:
                bullish_score += 1.0
                directional_reasons.append("MACD histograma positivo")
            elif float(macd_hist) < 0:
                bearish_score += 1.0
                directional_reasons.append("MACD histograma negativo")

        di_spread = 0.0
        if not pd.isna(di_plus) and not pd.isna(di_minus):
            di_spread = abs(float(di_plus) - float(di_minus))
            if float(di_plus) > float(di_minus):
                bullish_score += 1.0 if di_spread >= 8 else 0.5
                directional_reasons.append("DI+ acima do DI-")
            elif float(di_minus) > float(di_plus):
                bearish_score += 1.0 if di_spread >= 8 else 0.5
                directional_reasons.append("DI- acima do DI+")
        if not pd.isna(rsi):
            if float(rsi) >= 55:
                bullish_score += 0.5
                directional_reasons.append("RSI acima da linha de equilibrio")
            elif float(rsi) <= 45:
                bearish_score += 0.5
                directional_reasons.append("RSI abaixo da linha de equilibrio")

        trend_votes = 0
        range_votes = 0
        if base_regime == "trending":
            trend_votes += 1
        elif base_regime == "ranging":
            range_votes += 1
        elif base_regime == "volatile":
            if not pd.isna(adx) and float(adx) >= 25 and di_spread >= 8:
                trend_votes += 1
            else:
                range_votes += 1

        if not pd.isna(adx):
            if float(adx) >= 25:
                trend_votes += 1
            elif float(adx) < 22:
                range_votes += 1
        if di_spread >= 8:
            trend_votes += 1
        elif di_spread < 5:
            range_votes += 1

        slope_alignment = 0
        if not pd.isna(sma_21_slope) and not pd.isna(sma_50_slope):
            if sma_21_slope > 0 and sma_50_slope > 0:
                slope_alignment = 1
            elif sma_21_slope < 0 and sma_50_slope < 0:
                slope_alignment = 1
            else:
                range_votes += 1
        if slope_alignment:
            trend_votes += 1

        if not pd.isna(price) and not pd.isna(sma_21) and not pd.isna(sma_50):
            if (float(price) > float(sma_21) > float(sma_50)) or (float(price) < float(sma_21) < float(sma_50)):
                trend_votes += 1
            else:
                range_votes += 1

        is_high_vol = False
        if not pd.isna(atr_pct):
            atr_threshold = max((atr_pct_baseline * 1.2) if not pd.isna(atr_pct_baseline) else 0.0, 0.018)
            is_high_vol = atr_pct >= atr_threshold
        if not pd.isna(recent_range_pct):
            range_threshold = max((recent_range_baseline * 1.15) if not pd.isna(recent_range_baseline) else 0.0, 0.06)
            is_high_vol = is_high_vol or recent_range_pct >= range_threshold
        if base_regime == "volatile":
            is_high_vol = True

        volatility_state = "high_vol" if is_high_vol else "low_vol"
        trend_state = "trend" if trend_votes >= max(3, range_votes + 1) else "range"
        regime = f"{trend_state}_{volatility_state}"

        if trend_state == "trend" and bullish_score >= 5 and bullish_score >= bearish_score + 1.5:
            market_bias = "bullish"
        elif trend_state == "trend" and bearish_score >= 5 and bearish_score >= bullish_score + 1.5:
            market_bias = "bearish"
        else:
            market_bias = "neutral"

        dominant_score = max(bullish_score, bearish_score)
        directional_gap = abs(bullish_score - bearish_score)
        context_strength = 0.0

        ma_alignment_points = 0.0
        if not pd.isna(price) and not pd.isna(sma_21):
            ma_alignment_points += 0.5
        if not pd.isna(sma_21) and not pd.isna(sma_50):
            ma_alignment_points += 0.75
        if not pd.isna(sma_50) and not pd.isna(sma_200):
            ma_alignment_points += 0.75
        if market_bias == "neutral":
            ma_alignment_points *= 0.3
        context_strength += ma_alignment_points

        slope_points = 0.0
        if not pd.isna(sma_21_slope):
            slope_points += 0.75
        if not pd.isna(sma_50_slope):
            slope_points += 0.75
        if not pd.isna(sma_200_slope):
            slope_points += 0.25
        if slope_alignment == 0:
            slope_points *= 0.35
        context_strength += min(1.75, slope_points)

        context_strength += min(2.0, dominant_score * 0.35)
        context_strength += min(1.5, directional_gap * 0.35)

        if not pd.isna(adx):
            if float(adx) >= 35:
                context_strength += 1.5
            elif float(adx) >= 25:
                context_strength += 1.0
            elif float(adx) >= 20:
                context_strength += 0.5

        if di_spread >= 15:
            context_strength += 1.25
        elif di_spread >= 8:
            context_strength += 0.85
        elif di_spread >= 4:
            context_strength += 0.35

        if trend_state == "trend":
            context_strength += 0.75
        if volatility_state == "low_vol":
            context_strength += 0.75
        elif trend_state == "trend":
            context_strength += 0.4

        if not pd.isna(recent_range_pct):
            if 0.02 <= recent_range_pct <= 0.12:
                context_strength += 0.5
            elif recent_range_pct > 0.18:
                context_strength -= 0.4

        context_strength = round(float(max(0.0, min(10.0, context_strength))), 2)
        strength = round(context_strength / 10.0, 2)
        is_tradeable = market_bias != "neutral" and trend_state == "trend" and context_strength >= 5.0

        reasons = []
        if market_bias == "bullish":
            reasons.append("vies direcional de alta no contexto")
        elif market_bias == "bearish":
            reasons.append("vies direcional de baixa no contexto")
        else:
            reasons.append("contexto sem vies direcional claro")
        reasons.append(f"regime {regime}")
        if not pd.isna(adx):
            reasons.append(f"ADX {float(adx):.1f}")
        if not pd.isna(atr_pct):
            reasons.append(f"ATR% {atr_pct * 100:.2f}")
        if not pd.isna(recent_range_pct):
            reasons.append(f"range recente {recent_range_pct * 100:.2f}%")
        if directional_reasons:
            reasons.append(directional_reasons[0])
        reason = " | ".join(reasons)

        evaluation = {
            "timeframe": context_timeframe,
            "bias": market_bias,
            "market_bias": market_bias,
            "strength": strength,
            "context_strength": context_strength,
            "regime": regime,
            "volatility_state": volatility_state,
            "is_tradeable": is_tradeable,
            "atr_pct": None if pd.isna(atr_pct) else round(atr_pct * 100, 2),
            "recent_range_pct": None if pd.isna(recent_range_pct) else round(recent_range_pct * 100, 2),
            "ma_slopes": {
                "sma_21": None if pd.isna(sma_21_slope) else round(sma_21_slope, 4),
                "sma_50": None if pd.isna(sma_50_slope) else round(sma_50_slope, 4),
                "sma_200": None if pd.isna(sma_200_slope) else round(sma_200_slope, 4),
            },
            "timestamp": pd.Timestamp(working_df.index[-1]).isoformat(),
            "reason": reason,
        }
        self._last_context_evaluation = evaluation
        return evaluation

    def get_price_structure_evaluation(
        self,
        df: Optional[pd.DataFrame],
        timeframe: Optional[str] = None,
    ) -> Dict[str, object]:
        evaluation = {
            "timeframe": timeframe or self.timeframe,
            "structure_state": "weak_structure",
            "price_location": "mid_range",
            "structure_quality": 0.0,
            "is_tradeable": False,
            "has_minimum_history": False,
            "timestamp": None,
            "reason": "Sem dados suficientes para avaliar a estrutura.",
        }
        if df is None or df.empty:
            self._last_price_structure_evaluation = evaluation
            return evaluation

        working_df = df
        if "is_closed" in working_df.columns:
            closed_df = working_df[working_df["is_closed"].fillna(False)]
            if not closed_df.empty:
                working_df = closed_df
            elif len(working_df) > 1:
                working_df = working_df.iloc[:-1]

        if len(working_df) < 6:
            self._last_price_structure_evaluation = evaluation
            return evaluation

        current_timeframe = timeframe or self.timeframe or "5m"
        last_row = working_df.iloc[-1]
        prior_df = working_df.iloc[:-1]
        lookback = min(20, len(prior_df))
        recent_df = prior_df.tail(lookback)
        structure_window = working_df.tail(min(30, len(working_df)))

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
            return evaluation

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

        distance_from_sma_atr = 0.0
        if not pd.isna(atr_value) and float(atr_value) > 0 and not pd.isna(sma_21):
            distance_from_sma_atr = abs(float(close_price) - float(sma_21)) / float(atr_value)

        support_zone_distance = abs(float(close_price) - recent_low) / range_span
        resistance_zone_distance = abs(recent_high - float(close_price)) / range_span

        bullish_rejection = lower_wick >= max(body_size * 1.4, candle_range * 0.22)
        bearish_rejection = upper_wick >= max(body_size * 1.4, candle_range * 0.22)
        bullish_impulse = (
            float(close_price) > float(open_price)
            and body_share >= 0.58
            and close_location >= 0.7
            and body_size >= max(avg_body * 1.2, 0.0)
        )
        bearish_impulse = (
            float(close_price) < float(open_price)
            and body_share >= 0.58
            and close_location <= 0.3
            and body_size >= max(avg_body * 1.2, 0.0)
        )

        breakout_threshold = 0.15 * float(atr_value) if not pd.isna(atr_value) and float(atr_value) > 0 else range_span * 0.01
        broke_recent_high = float(close_price) > recent_high + breakout_threshold
        broke_recent_low = float(close_price) < recent_low - breakout_threshold

        if broke_recent_high:
            price_location = "resistance"
        elif broke_recent_low:
            price_location = "support"
        elif distance_from_sma_atr <= 1.25 and (bullish_stack or bearish_stack):
            price_location = "trend_zone"
        elif support_zone_distance <= 0.15:
            price_location = "support"
        elif resistance_zone_distance <= 0.15:
            price_location = "resistance"
        else:
            price_location = "mid_range"

        recent_close = prior_df["close"].iloc[-1]
        higher_lows = float(low_price) > float(recent_df["low"].tail(min(5, len(recent_df))).min()) if not recent_df.empty else False
        lower_highs = float(high_price) < float(recent_df["high"].tail(min(5, len(recent_df))).max()) if not recent_df.empty else False

        is_pullback = False
        if bullish_stack and not pd.isna(sma_21):
            pullback_floor = float(sma_21) - (float(atr_value) * 0.8 if not pd.isna(atr_value) and float(atr_value) > 0 else 0.0)
            is_pullback = (
                float(low_price) <= float(sma_21)
                and float(close_price) >= pullback_floor
                and float(close_price) >= float(open_price)
                and higher_lows
            )
        elif bearish_stack and not pd.isna(sma_21):
            pullback_ceiling = float(sma_21) + (float(atr_value) * 0.8 if not pd.isna(atr_value) and float(atr_value) > 0 else 0.0)
            is_pullback = (
                float(high_price) >= float(sma_21)
                and float(close_price) <= pullback_ceiling
                and float(close_price) <= float(open_price)
                and lower_highs
            )

        losing_structure = False
        if bullish_stack and not pd.isna(sma_21):
            losing_structure = float(close_price) < float(sma_21) and float(close_price) < float(recent_close)
        elif bearish_stack and not pd.isna(sma_21):
            losing_structure = float(close_price) > float(sma_21) and float(close_price) > float(recent_close)

        is_stretched = distance_from_sma_atr >= (2.6 if current_timeframe in {"5m", "15m"} else 2.9)

        structure_state = "weak_structure"
        reasons = []
        if (broke_recent_high and bullish_impulse) or (broke_recent_low and bearish_impulse):
            structure_state = "breakout"
            reasons.append("rompimento de maxima/minima com candle de impulso")
        elif is_pullback:
            structure_state = "pullback"
            reasons.append("preco corrigindo para a zona de tendencia")
        elif losing_structure or is_stretched or (
            price_location == "resistance" and bearish_rejection and bullish_stack
        ) or (
            price_location == "support" and bullish_rejection and bearish_stack
        ):
            structure_state = "reversal_risk"
            reasons.append("estrutura mostra risco de reversao")
        elif (bullish_stack and bullish_impulse) or (bearish_stack and bearish_impulse):
            structure_state = "continuation"
            reasons.append("estrutura de continuidade com impulso")
        else:
            reasons.append("estrutura fraca ou indefinida")

        structure_quality = 0.0
        if structure_state == "breakout":
            structure_quality += 4.0
        elif structure_state == "continuation":
            structure_quality += 3.4
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

        if not pd.isna(volume_ratio):
            if float(volume_ratio) >= 1.6:
                structure_quality += 1.0
            elif float(volume_ratio) >= 1.2:
                structure_quality += 0.5
            elif float(volume_ratio) < 0.9:
                structure_quality -= 0.6

        if market_regime == "trending":
            structure_quality += 0.9
        elif market_regime == "ranging":
            structure_quality -= 0.8
        elif market_regime == "volatile":
            structure_quality -= 0.5

        if is_stretched:
            structure_quality -= 1.5
            reasons.append("preco esticado em relacao a media")
        if losing_structure:
            structure_quality -= 1.2
            reasons.append("preco perdendo estrutura recente")

        structure_quality = round(float(max(0.0, min(10.0, structure_quality))), 2)
        is_tradeable = structure_state in {"continuation", "pullback", "breakout"} and structure_quality >= 5.5

        if price_location == "support":
            reasons.append("preco proximo do suporte recente")
        elif price_location == "resistance":
            reasons.append("preco proximo da resistencia recente")
        elif price_location == "trend_zone":
            reasons.append("preco em zona de tendencia")
        else:
            reasons.append("preco no meio do range")

        evaluation = {
            "timeframe": current_timeframe,
            "structure_state": structure_state,
            "price_location": price_location,
            "structure_quality": structure_quality,
            "is_tradeable": is_tradeable,
            "has_minimum_history": True,
            "timestamp": pd.Timestamp(working_df.index[-1]).isoformat(),
            "recent_high": round(recent_high, 4),
            "recent_low": round(recent_low, 4),
            "distance_from_sma21_atr": round(distance_from_sma_atr, 2) if distance_from_sma_atr else 0.0,
            "impulse_candle": bool(bullish_impulse or bearish_impulse),
            "rejection_candle": bool(bullish_rejection or bearish_rejection),
            "reason": " | ".join(reasons),
        }
        self._last_price_structure_evaluation = evaluation
        return evaluation

    def _fetch_context_df(self, context_timeframe: str, limit: int = 260) -> Optional[pd.DataFrame]:
        if not context_timeframe or context_timeframe == self.timeframe:
            return None
        return self.get_market_data(limit=limit, symbol=self.symbol, timeframe=context_timeframe)

    def _apply_context_alignment(self, signal: str, context_evaluation: Optional[Dict[str, object]]) -> str:
        if signal not in {"COMPRA", "COMPRA_FRACA", "VENDA", "VENDA_FRACA"}:
            return signal
        if not context_evaluation:
            return signal

        if not context_evaluation.get("is_tradeable", True):
            return "NEUTRO"

        bias = context_evaluation.get("bias", "neutral")
        if signal.startswith("COMPRA") and bias != "bullish":
            return "NEUTRO"
        if signal.startswith("VENDA") and bias != "bearish":
            return "NEUTRO"
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

        if structure_state in {"weak_structure", "reversal_risk"}:
            return "NEUTRO"
        if structure_quality < 5.5:
            return "NEUTRO"
        if signal.startswith("COMPRA") and price_location == "resistance" and structure_state != "breakout":
            return "NEUTRO"
        if signal.startswith("VENDA") and price_location == "support" and structure_state != "breakout":
            return "NEUTRO"
        return signal

    def _apply_signal_guardrails(
        self,
        signal: str,
        context_evaluation: Optional[Dict[str, object]] = None,
        structure_evaluation: Optional[Dict[str, object]] = None,
    ) -> str:
        guarded_signal = self._apply_structure_alignment(signal, structure_evaluation)
        if guarded_signal == "NEUTRO":
            return guarded_signal
        return self._apply_context_alignment(guarded_signal, context_evaluation)

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

    def _passes_signal_structure_guardrail(self, row, signal: str, timeframe: str) -> bool:
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
        body_share_floor = 0.25 if is_short_term else 0.18
        if is_weak_signal:
            body_share_floor += 0.05
        if body_share < body_share_floor:
            return False

        atr_value = row.get("atr", np.nan)
        if not pd.isna(atr_value) and float(atr_value) > 0:
            min_body_vs_atr = 0.18 if is_short_term else 0.12
            if is_weak_signal:
                min_body_vs_atr += 0.05
            if body_size / float(atr_value) < min_body_vs_atr:
                return False

        sma_21 = row.get("sma_21", np.nan)
        macd_hist = row.get("macd_histogram", row.get("macd", 0) - row.get("macd_signal", 0))
        di_plus = row.get("di_plus", np.nan)
        di_minus = row.get("di_minus", np.nan)
        di_gap_floor = 4.0 if is_short_term else 3.0
        if is_weak_signal:
            di_gap_floor += 1.0
        max_distance_from_sma_atr = 2.4 if is_short_term else 2.8

        if signal.startswith("COMPRA"):
            if float(close_price) <= float(open_price):
                return False
            if close_location < (0.58 if is_short_term else 0.55):
                return False
            if not pd.isna(macd_hist) and float(macd_hist) <= 0:
                return False
            if not pd.isna(sma_21) and float(close_price) < float(sma_21):
                return False
            if not pd.isna(di_plus) and not pd.isna(di_minus) and float(di_plus) < float(di_minus) + di_gap_floor:
                return False
            if (
                not pd.isna(sma_21)
                and not pd.isna(atr_value)
                and float(atr_value) > 0
                and (float(close_price) - float(sma_21)) / float(atr_value) > max_distance_from_sma_atr
            ):
                return False
            return True

        if float(close_price) >= float(open_price):
            return False
        if close_location > (0.42 if is_short_term else 0.45):
            return False
        if not pd.isna(macd_hist) and float(macd_hist) >= 0:
            return False
        if not pd.isna(sma_21) and float(close_price) > float(sma_21):
            return False
        if not pd.isna(di_plus) and not pd.isna(di_minus) and float(di_minus) < float(di_plus) + di_gap_floor:
            return False
        if (
            not pd.isna(sma_21)
            and not pd.isna(atr_value)
            and float(atr_value) > 0
            and (float(sma_21) - float(close_price)) / float(atr_value) > max_distance_from_sma_atr
        ):
            return False
        return True

    def check_signal(self, df, min_confidence=60, require_volume=True, require_trend=False, avoid_ranging=False,
                    crypto_optimized=True, timeframe="5m", day_trading_mode=False, context_df=None,
                    context_timeframe: Optional[str] = None):
        """Check trading signal with special optimization for 5m timeframe"""
        if df is None or df.empty:
            return "NEUTRO"

        if "is_closed" in df.columns:
            closed_df = df[df["is_closed"].fillna(False)]
            if not closed_df.empty:
                df = closed_df
            elif len(df) > 1:
                df = df.iloc[:-1]

        if df.empty:
            return "NEUTRO"

        last_row = df.iloc[-1]
        signal = None

        # SEMPRE usar as configurações atuais do bot (definidas no dashboard)
        actual_rsi_min = self.rsi_min
        actual_rsi_max = self.rsi_max
        actual_rsi_period = self.rsi_period
        current_timeframe = timeframe or self.timeframe or "5m"
        resolved_context_timeframe = context_timeframe or AppConfig.get_context_timeframe(current_timeframe)
        market_regime = last_row.get('market_regime', 'trending')
        context_evaluation = None
        structure_evaluation = self.get_price_structure_evaluation(df, timeframe=current_timeframe)

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
                        return "NEUTRO"
            if context_df is not None:
                context_evaluation = self.get_context_evaluation(
                    context_df=context_df,
                    as_of_timestamp=df.index[-1],
                    context_timeframe=resolved_context_timeframe,
                )
                if context_evaluation.get("bias") == "neutral":
                    return "NEUTRO"

        if market_regime == 'ranging' and (avoid_ranging or current_timeframe in {"5m", "15m"}):
            return "NEUTRO"

        if market_regime == 'volatile' and current_timeframe in {"5m", "15m"}:
            return "NEUTRO"
        
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
                return "NEUTRO"

            # More lenient volume requirement
            if require_volume and last_row.get('volume_ratio', 1) < min_volume_ratio:
                return "NEUTRO"
        else:
            # More balanced default settings
            min_confidence = 60
            min_volume_ratio = 1.2
            volatility_threshold = 0.08
            min_adx_threshold = 18

            logger.debug(
                "Configuracao padrao otimizada - RSI: %s-%s",
                actual_rsi_min,
                actual_rsi_max
            )

            # Very permissive filters for more opportunities
            if require_trend and last_row.get('adx', 0) < min_adx_threshold:
                return "NEUTRO"

            if require_volume and last_row.get('volume_ratio', 1) < min_volume_ratio:
                return "NEUTRO"

        if require_trend and AppConfig.SIMPLE_TREND_SIGNAL_MODE:
            if market_regime != "trending":
                return "NEUTRO"
            if avoid_ranging and market_regime == "ranging":
                return "NEUTRO"
            if last_row.get('adx', 0) < min_adx_threshold:
                return "NEUTRO"
            if require_volume and last_row.get('volume_ratio', 1) < min_volume_ratio:
                return "NEUTRO"

            signal = self._generate_trend_signal(last_row, actual_rsi_min, actual_rsi_max)
            if signal == "NEUTRO":
                return "NEUTRO"

            effective_min_confidence = max(62, min_confidence - 1)
            if current_timeframe == "5m" or self.timeframe == "5m":
                effective_min_confidence = max(effective_min_confidence, 68)
            elif current_timeframe == "15m":
                effective_min_confidence = max(effective_min_confidence, 66)
            elif current_timeframe in {"30m", "1h"}:
                effective_min_confidence = max(effective_min_confidence, 63)

            confidence = self._calculate_signal_confidence(last_row)
            if confidence < effective_min_confidence:
                return "NEUTRO"

            atr_pct = last_row.get('atr', 0) / last_row.get('close', 1) * 100
            max_volatility = (volatility_threshold * 100) * 1.5
            if atr_pct > max_volatility:
                return "NEUTRO"

            if not self._passes_signal_structure_guardrail(last_row, signal, current_timeframe):
                return "NEUTRO"

            return self._apply_signal_guardrails(signal, context_evaluation, structure_evaluation)

        if require_trend:
            if market_regime != "trending":
                return "NEUTRO"
            signal = self._generate_trend_signal(last_row, actual_rsi_min, actual_rsi_max)

        # Gerar sinal usando configurações atuais
        if signal is None:
            signal = self._generate_advanced_signal(last_row)
        confidence = self._calculate_signal_confidence(last_row)

        # Log apenas sinais não-neutros
        if signal != "NEUTRO":
            rsi_atual = last_row.get('rsi', 50)
            logger.info("Sinal %s: RSI %.1f | Confianca %.0f%%", signal, rsi_atual, confidence)

        effective_min_confidence = max(62, min_confidence - 1)
        if current_timeframe == "5m" or self.timeframe == "5m":
            effective_min_confidence = max(effective_min_confidence, 68)
        elif current_timeframe == "15m":
            effective_min_confidence = max(effective_min_confidence, 66)
        elif current_timeframe in {"30m", "1h"}:
            effective_min_confidence = max(effective_min_confidence, 63)
        if confidence < effective_min_confidence:
            logger.debug(
                "Rejeitado por confianca baixa: %.1f%% < %s%%",
                confidence,
                effective_min_confidence
            )
            return "NEUTRO"

        # Relaxed volatility check - crypto markets need volatility
        atr_pct = last_row.get('atr', 0) / last_row.get('close', 1) * 100
        max_volatility = (volatility_threshold * 100) * 1.5
        if atr_pct > max_volatility:
            return "NEUTRO"

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

        if not self._passes_signal_structure_guardrail(last_row, signal, current_timeframe):
            logger.debug("Guardrail estrutural bloqueou o sinal %s", signal)
            return "NEUTRO"

        # Combine rule-based signal with advanced score for robust decision
        advanced_score = self.calculate_advanced_score(last_row, signal=signal)
        self.logger = logger
        logger.debug(f"💡 Advanced score: {advanced_score:.2f}")

        if advanced_score < 0.55 and signal in ['COMPRA', 'VENDA', 'COMPRA_FRACA', 'VENDA_FRACA']:
            logger.debug("📉 score baixo, converte para NEUTRO")
            return "NEUTRO"

        if advanced_score >= 0.82:
            if signal in ['COMPRA', 'COMPRA_FRACA']:
                return self._apply_signal_guardrails("COMPRA", context_evaluation, structure_evaluation)
            if signal in ['VENDA', 'VENDA_FRACA']:
                return self._apply_signal_guardrails("VENDA", context_evaluation, structure_evaluation)

        if advanced_score >= 0.68:
            return self._apply_signal_guardrails(signal, context_evaluation, structure_evaluation)

        # Se score intermediário e sinal fraco, devolver NEUTRO
        if signal == 'COMPRA' and advanced_score >= 0.62:
            return self._apply_signal_guardrails('COMPRA_FRACA', context_evaluation, structure_evaluation)
        if signal == 'VENDA' and advanced_score >= 0.62:
            return self._apply_signal_guardrails('VENDA_FRACA', context_evaluation, structure_evaluation)

        if signal in ['COMPRA_FRACA', 'VENDA_FRACA'] and advanced_score < 0.72:
            logger.debug("🔁 sinal fraco + score médio, NEUTRO")
            return "NEUTRO"

        return self._apply_signal_guardrails(signal, context_evaluation, structure_evaluation)

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

        if "is_closed" in df.columns:
            closed_df = df[df["is_closed"].fillna(False)]
            if not closed_df.empty:
                df = closed_df
            elif len(df) > 1:
                df = df.iloc[:-1]

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
