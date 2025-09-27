
class TimeFrame5mConfig:
    """Configurações especificamente otimizadas para timeframe 5m"""
    
    @staticmethod
    def get_optimized_settings():
        """Retorna configurações otimizadas para 5m baseadas em backtests"""
        return {
            # RSI otimizado para 5m
            "rsi_period": 14,        # RSI 14 mais estável que RSI 9
            "rsi_oversold": 15,      # Mais restritivo - só extremos
            "rsi_overbought": 85,    # Mais restritivo - só extremos
            
            # Confiança alta obrigatória
            "min_confidence": 80,    # Alta confiança para reduzir falsos sinais
            
            # Volume excepcional obrigatório
            "min_volume_ratio": 2.5, # Volume 2.5x acima da média
            
            # ADX forte obrigatório
            "min_adx": 30,           # Tendência muito forte
            
            # Filtros de volatilidade
            "max_atr_pct": 4,        # ATR máximo 4% do preço
            "max_bb_width": 0.12,    # Bollinger width máximo
            
            # MACD otimizado
            "macd_fast": 8,
            "macd_slow": 21,
            "macd_signal": 5,
            
            # Stochastic RSI extremos
            "stoch_rsi_oversold": 10,
            "stoch_rsi_overbought": 90,
            
            # Williams %R extremos
            "williams_r_oversold": -90,
            "williams_r_overbought": -10,
            
            # Filtros temporais
            "avoid_lunch_break": True,
            "only_peak_hours": True,
            "min_hold_candles": 3,    # Mínimo 3 candles = 15 minutos
            "max_trades_per_hour": 2, # Máximo 2 trades por hora
            
            # Stop loss e take profit para 5m
            "use_stop_loss": True,
            "stop_loss_pct": 2.0,     # Stop loss 2%
            "use_take_profit": True,
            "take_profit_pct": 4.0,   # Take profit 4% (risk/reward 1:2)
            
            # Filtro de market regime
            "avoid_ranging_markets": True,
            "require_trending_market": True,
        }
    
    @staticmethod
    def get_conservative_5m():
        """Configuração ainda mais conservadora para 5m"""
        base = TimeFrame5mConfig.get_optimized_settings()
        return {
            **base,
            "rsi_oversold": 10,       # Extremamente oversold
            "rsi_overbought": 90,     # Extremamente overbought
            "min_confidence": 85,     # Confiança muito alta
            "min_volume_ratio": 3.0,  # Volume excepcional
            "min_adx": 35,           # Tendência fortíssima
            "max_trades_per_day": 5,  # Máximo 5 trades por dia
        }
    
    @staticmethod
    def apply_5m_filters(signal, row, current_hour=None):
        """Aplica filtros específicos para 5m"""
        settings = TimeFrame5mConfig.get_optimized_settings()
        
        # Filtro de horário
        if current_hour is not None and settings["only_peak_hours"]:
            if settings["avoid_lunch_break"] and 12 <= current_hour <= 14:
                return "NEUTRO"
            if not (9 <= current_hour <= 11 or 14 <= current_hour <= 16 or 20 <= current_hour <= 22):
                return "NEUTRO"
        
        # Só aceitar sinais fortes em 5m
        if signal in ['COMPRA_FRACA', 'VENDA_FRACA']:
            return "NEUTRO"
        
        # Filtros de qualidade
        rsi = row.get('rsi', 50)
        volume_ratio = row.get('volume_ratio', 1)
        adx = row.get('adx', 0)
        
        # Aplicar thresholds mais rigorosos
        if signal == 'COMPRA' and rsi > settings["rsi_oversold"]:
            return "NEUTRO"
        if signal == 'VENDA' and rsi < settings["rsi_overbought"]:
            return "NEUTRO"
        if volume_ratio < settings["min_volume_ratio"]:
            return "NEUTRO"
        if adx < settings["min_adx"]:
            return "NEUTRO"
        
        return signal
