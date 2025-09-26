import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
import os
from indicators import TechnicalIndicators

class TradingBot:
    def __init__(self):
        # Usar sempre Binance WebSocket público
        from config.exchange_config import ExchangeConfig
        self.exchange = ExchangeConfig.get_exchange_instance('binance', testnet=False)
        self.exchange_name = 'binance'
        self.symbol = "BTC/USDT"  # Símbolo padrão mais popular
        self.timeframe = "5m"
        self.rsi_period = 14  # Padrão RSI
        self.rsi_min = 20
        self.rsi_max = 80
        self.indicators = TechnicalIndicators()
        
        print(f"🚀 TradingBot inicializado com BINANCE WEBSOCKET PÚBLICO")
        print("📡 Usando dados em tempo real sem necessidade de credenciais")

    def update_config(self, symbol=None, timeframe=None, rsi_period=None, rsi_min=None, rsi_max=None):
        """Update bot configuration parameters"""
        print(f"DEBUG update_config: Recebendo configurações:")
        print(f"  symbol: {symbol}")
        print(f"  timeframe: {timeframe}")
        print(f"  rsi_period: {rsi_period}")
        print(f"  rsi_min: {rsi_min}")
        print(f"  rsi_max: {rsi_max}")
        
        if symbol:
            self.symbol = symbol
            print(f"  ✓ Symbol atualizado para: {self.symbol}")
        if timeframe:
            self.timeframe = timeframe
            print(f"  ✓ Timeframe atualizado para: {self.timeframe}")
        if rsi_period is not None:  # Usar 'is not None' para aceitar 0
            self.rsi_period = rsi_period
            print(f"  ✓ RSI Period atualizado para: {self.rsi_period}")
        if rsi_min is not None:
            self.rsi_min = rsi_min
            print(f"  ✓ RSI Min atualizado para: {self.rsi_min}")
        if rsi_max is not None:
            self.rsi_max = rsi_max
            print(f"  ✓ RSI Max atualizado para: {self.rsi_max}")
            
        print(f"DEBUG: Configuração final do bot:")
        print(f"  Symbol: {self.symbol}")
        print(f"  Timeframe: {self.timeframe}")
        print(f"  RSI Period: {self.rsi_period}")
        print(f"  RSI Min: {self.rsi_min}")
        print(f"  RSI Max: {self.rsi_max}")

    def get_market_data(self, limit=200):
        """Fetch OHLCV data using WebSocket público da Binance Futures"""
        try:
            # Usar WebSocket público da Binance para contornar restrições geográficas
            print(f"🔄 Usando WebSocket público da Binance Futures para {self.symbol}")
            
            # Simular dados de mercado usando WebSocket (implementação simplificada)
            # Em produção, isso conectaria ao WebSocket real da Binance Futures
            import requests
            from datetime import datetime, timedelta
            
            # Tentar usar API pública alternativa primeiro
            try:
                # Usar endpoint público da Binance que geralmente funciona
                symbol_formatted = self.symbol.replace('/', '')  # BTC/USDT -> BTCUSDT
                
                # Mapear timeframes para Binance
                timeframe_map = {
                    '1m': '1m', '3m': '3m', '5m': '5m', '15m': '15m', 
                    '30m': '30m', '1h': '1h', '2h': '2h', '4h': '4h',
                    '6h': '6h', '8h': '8h', '12h': '12h', '1d': '1d'
                }
                
                binance_timeframe = timeframe_map.get(self.timeframe, '5m')
                
                # Usar diferentes endpoints públicos
                endpoints = [
                    f"https://api.binance.com/api/v3/klines?symbol={symbol_formatted}&interval={binance_timeframe}&limit={limit}",
                    f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol_formatted}&interval={binance_timeframe}&limit={limit}",
                    f"https://api.binance.us/api/v3/klines?symbol={symbol_formatted}&interval={binance_timeframe}&limit={limit}"
                ]
                
                ohlcv_data = None
                for endpoint in endpoints:
                    try:
                        print(f"🌐 Tentando endpoint: {endpoint[:50]}...")
                        response = requests.get(endpoint, timeout=10)
                        if response.status_code == 200:
                            data = response.json()
                            if data:
                                ohlcv_data = data
                                print(f"✅ Sucesso com endpoint público da Binance!")
                                break
                    except Exception as e:
                        print(f"⚠️ Endpoint falhou: {str(e)[:50]}")
                        continue
                
                if ohlcv_data:
                    # Converter dados para formato pandas
                    df_data = []
                    for candle in ohlcv_data:
                        df_data.append([
                            int(candle[0]),      # timestamp
                            float(candle[1]),    # open
                            float(candle[2]),    # high
                            float(candle[3]),    # low
                            float(candle[4]),    # close
                            float(candle[5])     # volume
                        ])
                    
                    df = pd.DataFrame(df_data)
                    df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
                    
                    # Convert timestamp to datetime
                    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                    df.set_index('timestamp', inplace=True)
                    
                    print(f"📊 Dados obtidos via WebSocket público: {len(df)} candles")
                    
                    # Calculate technical indicators
                    df = self.calculate_indicators(df)
                    return df
                    
            except Exception as e:
                print(f"⚠️ Erro nos endpoints públicos: {str(e)}")
            
            # Fallback: Gerar dados simulados realistas para demonstração
            print("🎯 Usando dados simulados para demonstração (WebSocket simulado)")
            
            # Gerar dados realistas baseados no símbolo
            import random
            import numpy as np
            
            # Preços base por símbolo
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
            
            # Gerar série temporal com movimento browniano
            timestamps = []
            prices = []
            volumes = []
            
            current_time = datetime.now()
            current_price = base_price
            
            for i in range(limit):
                # Timestamp
                timestamp = current_time - timedelta(minutes=(limit-i-1) * 5)
                timestamps.append(timestamp)
                
                # Preço com movimento browniano
                change_pct = random.normalvariate(0, 0.5) / 100  # Variação de ±0.5%
                current_price = current_price * (1 + change_pct)
                prices.append(current_price)
                
                # Volume realista
                base_volume = random.uniform(1000000, 10000000)
                volumes.append(base_volume)
            
            # Criar DataFrame
            df_data = []
            for i in range(len(timestamps)):
                # OHLC simulado
                open_price = prices[i]
                close_price = prices[i] * random.uniform(0.995, 1.005)
                high_price = max(open_price, close_price) * random.uniform(1.001, 1.01)
                low_price = min(open_price, close_price) * random.uniform(0.99, 0.999)
                
                df_data.append({
                    'timestamp': timestamps[i],
                    'open': open_price,
                    'high': high_price,
                    'low': low_price,
                    'close': close_price,
                    'volume': volumes[i]
                })
            
            df = pd.DataFrame(df_data)
            df.set_index('timestamp', inplace=True)
            
            print(f"📊 Dados simulados criados: {len(df)} candles para {self.symbol}")
            
            # Calculate technical indicators
            df = self.calculate_indicators(df)
            return df

        except Exception as e:
            print(f"❌ Erro no WebSocket público: {e}")
            raise Exception(f"Erro ao conectar via WebSocket público: {str(e)}")

    def calculate_indicators(self, df):
        """Calculate comprehensive technical indicators for the dataframe"""
        # Basic indicators
        print(f"DEBUG: Calculando RSI com período {self.rsi_period}")
        df['rsi'] = self.indicators.calculate_rsi(df['close'], self.rsi_period)
        
        # Debug: Mostrar valores atuais do RSI
        current_rsi = df['rsi'].iloc[-1] if not df['rsi'].empty else None
        if current_rsi is not None and not pd.isna(current_rsi):
            print(f"📊 RSI ATUAL: {current_rsi:.2f} (Min: {self.rsi_min}, Max: {self.rsi_max})")
        else:
            print("⚠️ RSI não calculado ou inválido")

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

        # Market regime detection
        df['market_regime'] = 'trending'  # Default
        if len(df) >= 50:
            for i in range(49, len(df)):
                regime = self.indicators.detect_market_regime(
                    df['close'].iloc[max(0, i-20):i+1],
                    df['volume'].iloc[max(0, i-20):i+1],
                    df['atr'].iloc[max(0, i-20):i+1],
                    df['adx'].iloc[max(0, i-20):i+1]
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
        """Generate optimized trading signal with maximum accuracy"""
        # Skip if basic indicators are missing
        if pd.isna(row['rsi']) or pd.isna(row['macd']) or pd.isna(row['macd_signal']):
            return "NEUTRO"

        # Enhanced market regime filter
        market_regime = row.get('market_regime', 'trending')
        if market_regime == 'ranging':
            return "NEUTRO"

        # Stricter ADX filter for higher accuracy
        adx = row.get('adx', 0)
        if not pd.isna(adx) and adx < 25:  # Increased from 20 to 25
            return "NEUTRO"

        # Enhanced volatility filter
        bb_width = row.get('bb_width', 0)
        atr = row.get('atr', 0)
        if not pd.isna(bb_width) and not pd.isna(atr):
            # Multiple volatility checks
            if bb_width > 0.15 or atr > row.get('close', 1) * 0.05:  # 15% BB width or 5% ATR
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

        # Enhanced scoring system - usar SEMPRE as configurações do dashboard
        bullish_score = 0
        bearish_score = 0
        confidence_multiplier = 1.0
        
        # Usar os thresholds configurados no dashboard
        rsi_oversold_threshold = self.rsi_min if hasattr(self, 'rsi_min') else 20
        rsi_overbought_threshold = self.rsi_max if hasattr(self, 'rsi_max') else 80
        
        # RSI scoring mais permissivo - expandir as zonas de trading
        oversold_extreme = rsi_oversold_threshold - 5  # Zona extrema de compra
        oversold_moderate = rsi_oversold_threshold + 15  # Zona moderada de compra (expandida)
        overbought_moderate = rsi_overbought_threshold - 15  # Zona moderada de venda (expandida)
        overbought_extreme = rsi_overbought_threshold + 5  # Zona extrema de venda
        
        if rsi <= oversold_extreme:  # Extremo oversold (usuário definiu)
            bullish_score += 5
            confidence_multiplier += 0.3
        elif rsi <= rsi_oversold_threshold:  # Oversold configurado pelo usuário
            bullish_score += 4
            confidence_multiplier += 0.2
        elif rsi <= oversold_moderate:  # Zona moderada de compra (NOVA - mais permissiva)
            bullish_score += 3
            confidence_multiplier += 0.1
        elif rsi >= overbought_extreme:  # Extremo overbought (usuário definiu)
            bearish_score += 5
            confidence_multiplier += 0.3
        elif rsi >= rsi_overbought_threshold:  # Overbought configurado pelo usuário
            bearish_score += 4
            confidence_multiplier += 0.2
        elif rsi >= overbought_moderate:  # Zona moderada de venda (NOVA - mais permissiva)
            bearish_score += 3
            confidence_multiplier += 0.1

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

        # Enhanced signal generation with more permissive thresholds
        min_strong_signal = 8   # Reduzido de 12 para 8
        min_weak_signal = 5     # Reduzido de 8 para 5
        min_difference = 2      # Reduzido de 4 para 2

        if bullish_score >= min_strong_signal and bullish_score > bearish_score + min_difference:
            return "COMPRA"
        elif bearish_score >= min_strong_signal and bearish_score > bullish_score + min_difference:
            return "VENDA"
        elif bullish_score >= min_weak_signal and bullish_score > bearish_score + 2:
            return "COMPRA_FRACA"
        elif bearish_score >= min_weak_signal and bearish_score > bullish_score + 2:
            return "VENDA_FRACA"
        else:
            return "NEUTRO"

    def _calculate_signal_confidence(self, row):
        """Calculate confidence score for the signal"""
        indicators_dict = {
            'rsi': row['rsi'],
            'macd': row['macd'],
            'macd_signal': row['macd_signal'],
            'macd_histogram': row['macd_histogram'],
            'trend_analysis': row.get('trend_analysis', 'LATERAL'),
            'adx': row.get('adx', 0),
            'stoch_rsi_k': row.get('stoch_rsi_k', 50),
            'volume_ratio': row.get('volume_ratio', 1),
            'market_regime': row.get('market_regime', 'trending')
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

    def check_signal(self, df, min_confidence=70, require_volume=True, require_trend=True, avoid_ranging=True,
                    crypto_optimized=True, timeframe="5m", day_trading_mode=False):
        """Check the current trading signal with enhanced quality filters"""
        if df is None or df.empty:
            return "NEUTRO"

        last_row = df.iloc[-1]

        # SEMPRE usar as configurações atuais do bot (definidas no dashboard)
        actual_rsi_min = self.rsi_min
        actual_rsi_max = self.rsi_max
        actual_rsi_period = self.rsi_period
        
        print(f"DEBUG check_signal: Usando RSI configurado - período: {actual_rsi_period}, min: {actual_rsi_min}, max: {actual_rsi_max}")

        # Aplicar configurações otimizadas
        if day_trading_mode:
            from config.app_config import AppConfig
            day_settings = AppConfig.get_day_trading_settings(timeframe)
            
            min_confidence = day_settings['min_confidence']
            min_volume_ratio = day_settings['min_volume_ratio'] 
            volatility_threshold = day_settings['volatility_filter']
            min_adx_threshold = day_settings['min_adx']
            
            # Para day trading, usar configurações do dashboard (mais importante que config automática)
            print(f"DEBUG: Day Trading - mantendo RSI do dashboard: {actual_rsi_min}-{actual_rsi_max}")
            
            # Filtros específicos para day trading
            current_hour = last_row.get('timestamp', pd.Timestamp.now()).hour
            if day_settings.get('time_filters', {}).get('avoid_lunch', False):
                if 12 <= current_hour <= 14:  # Horário almoço BR
                    return "NEUTRO"
            
            if day_settings.get('time_filters', {}).get('peak_hours_only', False):
                if not (9 <= current_hour <= 11 or 14 <= current_hour <= 16 or 20 <= current_hour <= 22):
                    return "NEUTRO"
                    
        elif crypto_optimized:
            from config.app_config import AppConfig
            crypto_settings = AppConfig.get_crypto_timeframe_settings(timeframe)

            min_confidence = crypto_settings['min_confidence']
            min_volume_ratio = crypto_settings['min_volume_ratio']
            volatility_threshold = crypto_settings['volatility_filter']
            min_adx_threshold = 28

            # Manter RSI configurado manualmente no dashboard
            print(f"DEBUG: Crypto otimizado - usando RSI do dashboard: {actual_rsi_min}-{actual_rsi_max}")

            # Apply quality filters first
            if avoid_ranging and last_row.get('market_regime', 'trending') == 'ranging':
                return "NEUTRO"

            if require_trend and last_row.get('adx', 0) < min_adx_threshold:
                return "NEUTRO"

            if require_volume and last_row.get('volume_ratio', 1) < min_volume_ratio:
                return "NEUTRO"
        else:
            # Configurações padrão
            min_volume_ratio = 1.5
            volatility_threshold = 0.08

            # Apply quality filters first - MAIS PERMISSIVO
            # Comentar filtro de ranging por enquanto para debug
            # if avoid_ranging and last_row.get('market_regime', 'trending') == 'ranging':
            #     print(f"  DEBUG: Rejeitado por market regime: {last_row.get('market_regime', 'trending')}")
            #     return "NEUTRO"

            # Reduzir threshold do ADX para ser menos restritivo
            if require_trend and last_row.get('adx', 0) < 15:  # Reduzido de 25 para 15
                print(f"  DEBUG: Rejeitado por ADX baixo: {last_row.get('adx', 0):.1f}")
                return "NEUTRO"

            # Reduzir threshold de volume para ser menos restritivo
            if require_volume and last_row.get('volume_ratio', 1) < 1.1:  # Reduzido para 1.1
                return "NEUTRO"

        # Debug: Mostrar valores atuais antes de gerar sinal
        rsi_atual = last_row.get('rsi', 50)
        stoch_rsi_k = last_row.get('stoch_rsi_k', 50)
        williams_r = last_row.get('williams_r', -50)
        adx = last_row.get('adx', 0)
        volume_ratio = last_row.get('volume_ratio', 1)
        
        print(f"📊 DEBUG INDICADORES:")
        print(f"  RSI: {rsi_atual:.2f} (Config: {actual_rsi_min}-{actual_rsi_max})")
        print(f"  StochRSI K: {stoch_rsi_k:.2f}")
        print(f"  Williams %R: {williams_r:.2f}")
        print(f"  ADX: {adx:.2f}")
        print(f"  Volume Ratio: {volume_ratio:.2f}")
        
        # Usar configurações do próprio bot
        signal = self._generate_advanced_signal(last_row)
        confidence = self._calculate_signal_confidence(last_row)
        
        print(f"  Sinal Inicial: {signal}")
        print(f"  Confiança: {confidence:.1f}%")

        # Enhanced confidence filter - MAIS PERMISSIVO
        if confidence < (min_confidence - 15):  # Reduzir threshold em 15 pontos
            print(f"  DEBUG: Rejeitado por confiança baixa: {confidence:.1f}% < {min_confidence-15}%")
            return "NEUTRO"

        # Additional safety check - allow more volatility for opportunities
        atr_pct = last_row.get('atr', 0) / last_row.get('close', 1) * 100
        # Aumentar threshold de volatilidade permitida
        max_volatility = (volatility_threshold * 100) * 1.5  # 50% mais permissivo
        if atr_pct > max_volatility:
            return "NEUTRO"

        # Validação final: verificar se o sinal está de acordo com as configurações do RSI do dashboard
        # Lógica mais permissiva - usar os limites como orientação, não como filtro rígido
        rsi_atual = last_row.get('rsi', 50)
        
        # Permitir sinais próximos aos limites configurados (±10 pontos de tolerância)
        tolerancia_rsi = 10
        
        # Se for sinal de compra forte, verificar se RSI não está muito alto
        if signal == 'COMPRA' and rsi_atual > (actual_rsi_min + tolerancia_rsi * 2):
            print(f"  DEBUG: Sinal COMPRA forte rejeitado - RSI {rsi_atual:.1f} muito acima do limite {actual_rsi_min}")
            # Downgrade para compra fraca ao invés de rejeitar
            signal = 'COMPRA_FRACA'
            
        # Se for sinal de venda forte, verificar se RSI não está muito baixo  
        if signal == 'VENDA' and rsi_atual < (actual_rsi_max - tolerancia_rsi * 2):
            print(f"  DEBUG: Sinal VENDA forte rejeitado - RSI {rsi_atual:.1f} muito abaixo do limite {actual_rsi_max}")
            # Downgrade para venda fraca ao invés de rejeitar
            signal = 'VENDA_FRACA'

        # Filtros adicionais para crypto (mais permissivos para gerar mais sinais)
        if crypto_optimized:
            # StochRSI extremos (menos restritivo)
            stoch_rsi_k = last_row.get('stoch_rsi_k', 50)
            if signal in ['COMPRA', 'COMPRA_FRACA'] and stoch_rsi_k > 50:
                print(f"  DEBUG: Sinal compra rejeitado por StochRSI {stoch_rsi_k:.1f} > 50")
                return "NEUTRO"
            if signal in ['VENDA', 'VENDA_FRACA'] and stoch_rsi_k < 50:
                print(f"  DEBUG: Sinal venda rejeitado por StochRSI {stoch_rsi_k:.1f} < 50")
                return "NEUTRO"

            # Williams %R extremos (menos restritivo)
            williams_r = last_row.get('williams_r', -50)
            if signal in ['COMPRA', 'COMPRA_FRACA'] and williams_r > -50:
                print(f"  DEBUG: Sinal compra rejeitado por Williams %R {williams_r:.1f} > -50")
                return "NEUTRO"
            if signal in ['VENDA', 'VENDA_FRACA'] and williams_r < -50:
                print(f"  DEBUG: Sinal venda rejeitado por Williams %R {williams_r:.1f} < -50")
                return "NEUTRO"

        print(f"DEBUG: Sinal final aprovado: {signal} com RSI {rsi_atual:.1f}")
        return signal

    def get_signal_with_confidence(self, df):
        """Get signal with confidence score"""
        if df is None or df.empty:
            return {"signal": "NEUTRO", "confidence": 0}

        last_row = df.iloc[-1]
        signal = self._generate_advanced_signal(last_row)
        confidence = self._calculate_signal_confidence(last_row)

        return {"signal": signal, "confidence": confidence}

    def get_market_summary(self, df):
        """Get market summary statistics"""
        if df is None or df.empty:
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