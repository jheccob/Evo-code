
import ccxt
import pandas as pd
import numpy as np
import logging
from datetime import datetime
from typing import Dict, Optional, Tuple
from trading_bot import TradingBot
from config import ExchangeConfig

logger = logging.getLogger(__name__)

class FuturesTrading(TradingBot):
    """
    Trading Bot especializado para mercado futuro
    Suporte para alavancagem, posições short/long e gerenciamento de risco
    """
    
    def __init__(self, exchange_name='binance'):
        super().__init__()
        # Configurar exchange que funciona no Brasil
        self.exchange = ExchangeConfig.get_exchange_instance(exchange_name, testnet=False)
        self.exchange_name = exchange_name
        
        # Definir símbolo padrão em USDT
        self.symbol = "XLM/USDT"
        
        # Configurações específicas para futuros
        self.leverage = 5  # Alavancagem padrão
        self.position_size_pct = 0.1  # 10% do saldo por trade
        self.stop_loss_pct = 0.02  # Stop loss 2%
        self.take_profit_pct = 0.04  # Take profit 4%
        self.max_positions = 3  # Máximo de posições simultaneas
        
    def set_leverage(self, symbol: str, leverage: int):
        """Define alavancagem para um símbolo USDT"""
        try:
            # Verificar se é par USDT
            if not self.validate_usdt_pair(symbol):
                return False, f"Símbolo {symbol} não é um par USDT válido para futuros"
            
            result = self.exchange.set_leverage(leverage, symbol)
            self.leverage = leverage
            return True, f"Alavancagem {leverage}x definida para {symbol} (USDT)"
        except Exception as e:
            return False, f"Erro ao definir alavancagem: {str(e)}"
    
    def get_account_balance(self):
        """Obtém saldo da conta de futuros em USDT"""
        try:
            balance = self.exchange.fetch_balance()
            
            # Informações específicas de futuros USDT
            return {
                'total_balance': balance['USDT']['total'],
                'available_balance': balance['USDT']['free'],
                'used_balance': balance['USDT']['used'],
                'unrealized_pnl': balance['info'].get('totalUnrealizedProfit', 0),
                'margin_ratio': balance['info'].get('totalMaintMargin', 0),
                'currency': 'USDT'
            }
        except Exception as e:
            logger.error("Erro ao obter saldo USDT: %s", e)
            return None
    
    def calculate_position_size(self, balance: float, price: float, signal_strength: float = 1.0):
        """
        Calcula tamanho da posição baseado no saldo USDT e alavancagem
        
        Args:
            balance: Saldo disponível em USDT
            price: Preço atual do par /USDT
            signal_strength: Força do sinal (0.1 a 1.0)
        
        Returns:
            Quantidade para a ordem
        """
        # Validar se é par USDT
        if not self.symbol.endswith('/USDT'):
            raise ValueError("Mercado futuro configurado apenas para pares USDT")
        
        # Ajustar tamanho baseado na força do sinal
        adjusted_size_pct = self.position_size_pct * signal_strength
        
        # Valor em USDT para a posição
        position_value = balance * adjusted_size_pct
        
        # Quantidade considerando alavancagem
        quantity = (position_value * self.leverage) / price
        
        return round(quantity, 6)
    
    def create_futures_order(self, symbol: str, side: str, quantity: float, 
                           order_type: str = 'market', price: Optional[float] = None,
                           stop_loss: Optional[float] = None, take_profit: Optional[float] = None):
        """
        Criar ordem no mercado futuro com stop loss e take profit
        
        Args:
            symbol: Par de trading
            side: 'buy' ou 'sell'
            quantity: Quantidade
            order_type: 'market' ou 'limit'
            price: Preço (para ordem limit)
            stop_loss: Preço do stop loss
            take_profit: Preço do take profit
        """
        try:
            # Ordem principal
            if order_type == 'market':
                order = self.exchange.create_market_order(symbol, side, quantity)
            else:
                order = self.exchange.create_limit_order(symbol, side, quantity, price)
            
            order_id = order['id']
            fill_price = order.get('price', price)
            
            # Definir stop loss e take profit se especificados
            if stop_loss and fill_price:
                self._create_stop_loss_order(symbol, side, quantity, stop_loss, order_id)
            
            if take_profit and fill_price:
                self._create_take_profit_order(symbol, side, quantity, take_profit, order_id)
            
            return True, {
                'order_id': order_id,
                'symbol': symbol,
                'side': side,
                'quantity': quantity,
                'price': fill_price,
                'stop_loss': stop_loss,
                'take_profit': take_profit
            }
            
        except Exception as e:
            return False, f"Erro ao criar ordem: {str(e)}"
    
    def _create_stop_loss_order(self, symbol: str, side: str, quantity: float, 
                               stop_price: float, parent_order_id: str):
        """Criar ordem de stop loss"""
        try:
            # Inverter o lado para fechar a posição
            stop_side = 'sell' if side == 'buy' else 'buy'
            
            stop_order = self.exchange.create_order(
                symbol=symbol,
                type='STOP_MARKET',
                side=stop_side,
                amount=quantity,
                params={
                    'stopPrice': stop_price,
                    'reduceOnly': True  # Apenas reduzir posição
                }
            )
            
            return stop_order
            
        except Exception as e:
            logger.error("Erro ao criar stop loss: %s", e)
            return None
    
    def _create_take_profit_order(self, symbol: str, side: str, quantity: float, 
                                 take_profit_price: float, parent_order_id: str):
        """Criar ordem de take profit"""
        try:
            # Inverter o lado para fechar a posição
            tp_side = 'sell' if side == 'buy' else 'buy'
            
            tp_order = self.exchange.create_limit_order(
                symbol=symbol,
                side=tp_side,
                amount=quantity,
                price=take_profit_price,
                params={
                    'reduceOnly': True,  # Apenas reduzir posição
                    'timeInForce': 'GTC'  # Good Till Cancelled
                }
            )
            
            return tp_order
            
        except Exception as e:
            logger.error("Erro ao criar take profit: %s", e)
            return None
    
    def get_open_positions(self):
        """Obter posições abertas"""
        try:
            positions = self.exchange.fetch_positions()
            
            # Filtrar apenas posições abertas
            open_positions = []
            for position in positions:
                if float(position['contracts']) != 0:
                    open_positions.append({
                        'symbol': position['symbol'],
                        'side': position['side'],
                        'size': position['contracts'],
                        'entry_price': position['entryPrice'],
                        'mark_price': position['markPrice'],
                        'unrealized_pnl': position['unrealizedPnl'],
                        'margin': position['initialMargin'],
                        'leverage': position.get('leverage', self.leverage)
                    })
            
            return open_positions
            
        except Exception as e:
            logger.error("Erro ao obter posicoes: %s", e)
            return []
    
    def close_position(self, symbol: str, reduce_only: bool = True):
        """Fechar posição aberta"""
        try:
            positions = self.get_open_positions()
            target_position = None
            
            for pos in positions:
                if pos['symbol'] == symbol:
                    target_position = pos
                    break
            
            if not target_position:
                return False, "Posição não encontrada"
            
            # Determinar lado da ordem de fechamento
            close_side = 'sell' if target_position['side'] == 'long' else 'buy'
            
            # Criar ordem de mercado para fechar
            order = self.exchange.create_market_order(
                symbol=symbol,
                side=close_side,
                amount=abs(float(target_position['size'])),
                params={'reduceOnly': True} if reduce_only else {}
            )
            
            return True, {
                'closed_position': target_position,
                'close_order': order
            }
            
        except Exception as e:
            return False, f"Erro ao fechar posição: {str(e)}"
    
    def generate_futures_signal(self, df: pd.DataFrame, account_balance: float):
        """
        Gerar sinal específico para futuros com gerenciamento de risco
        
        Args:
            df: DataFrame com dados de mercado e indicadores
            account_balance: Saldo da conta
            
        Returns:
            Dicionário com sinal e parâmetros de trade
        """
        if df is None or df.empty:
            return {"signal": "NEUTRO", "confidence": 0}
        
        last_row = df.iloc[-1]
        current_price = last_row['close']
        
        # Usar análise avançada do TradingBot pai
        base_signal = self._generate_advanced_signal(last_row)
        confidence = self._calculate_signal_confidence(last_row)
        
        # Adaptações para futuros
        signal_data = {
            "signal": base_signal,
            "confidence": confidence,
            "entry_price": current_price,
            "leverage": self.leverage,
            "position_side": None,
            "quantity": 0,
            "stop_loss": None,
            "take_profit": None
        }
        
        # Calcular parâmetros específicos baseados no sinal
        if base_signal in ['COMPRA', 'COMPRA_FRACA']:
            signal_data.update({
                "position_side": "LONG",
                "quantity": self.calculate_position_size(
                    account_balance, 
                    current_price, 
                    confidence / 100
                ),
                "stop_loss": current_price * (1 - self.stop_loss_pct),
                "take_profit": current_price * (1 + self.take_profit_pct)
            })
            
        elif base_signal in ['VENDA', 'VENDA_FRACA']:
            signal_data.update({
                "position_side": "SHORT",
                "quantity": self.calculate_position_size(
                    account_balance, 
                    current_price, 
                    confidence / 100
                ),
                "stop_loss": current_price * (1 + self.stop_loss_pct),
                "take_profit": current_price * (1 - self.take_profit_pct)
            })
        
        return signal_data
    
    def execute_futures_trade(self, signal_data: Dict, dry_run: bool = True):
        """
        Executar trade baseado no sinal
        
        Args:
            signal_data: Dados do sinal gerado
            dry_run: Se True, apenas simula o trade
            
        Returns:
            Resultado da execução
        """
        if signal_data["signal"] == "NEUTRO":
            return {"success": False, "message": "Sinal neutro, nenhuma ação"}
        
        symbol = self.symbol
        side = "buy" if signal_data["position_side"] == "LONG" else "sell"
        quantity = signal_data["quantity"]
        stop_loss = signal_data["stop_loss"]
        take_profit = signal_data["take_profit"]
        
        if dry_run:
            return {
                "success": True,
                "message": f"SIMULAÇÃO - {signal_data['position_side']} {quantity} {symbol}",
                "details": {
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "entry_price": signal_data["entry_price"],
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "leverage": signal_data["leverage"],
                    "confidence": signal_data["confidence"]
                }
            }
        
        # Executar trade real
        success, result = self.create_futures_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type='market',
            stop_loss=stop_loss,
            take_profit=take_profit
        )
        
        return {
            "success": success,
            "message": "Trade executado com sucesso" if success else "Erro ao executar trade",
            "details": result
        }
    
    def get_funding_rate(self, symbol: str):
        """Obter taxa de funding do símbolo"""
        try:
            funding_rate = self.exchange.fetch_funding_rate(symbol)
            return {
                'symbol': symbol,
                'funding_rate': funding_rate['fundingRate'],
                'next_funding_time': funding_rate['fundingDatetime']
            }
        except Exception as e:
            logger.error("Erro ao obter funding rate: %s", e)
            return None
    
    def calculate_liquidation_price(self, entry_price: float, leverage: int, 
                                  side: str, margin_ratio: float = 0.1):
        """
        Calcular preço de liquidação para pares USDT
        
        Args:
            entry_price: Preço de entrada em USDT
            leverage: Alavancagem utilizada
            side: 'long' ou 'short'
            margin_ratio: Razão de margem de manutenção
        """
        if side.lower() == 'long':
            liquidation_price = entry_price * (1 - (1/leverage) + margin_ratio)
        else:  # short
            liquidation_price = entry_price * (1 + (1/leverage) - margin_ratio)
        
        return liquidation_price
    
    def validate_usdt_pair(self, symbol: str):
        """Validar se o símbolo é um par USDT válido"""
        if not symbol.endswith('/USDT'):
            return False
        
        try:
            markets = self.exchange.load_markets()
            return symbol in markets and markets[symbol]['future']
        except:
            return False
    
    def get_supported_usdt_pairs(self):
        """Obter lista de pares USDT suportados para futuros"""
        try:
            markets = self.exchange.load_markets()
            usdt_futures = []
            
            for symbol, market in markets.items():
                if (symbol.endswith('/USDT') and 
                    market.get('type') == 'future' and 
                    market.get('active', True)):
                    usdt_futures.append(symbol)
            
            return sorted(usdt_futures)
        except Exception as e:
            logger.error("Erro ao obter pares USDT: %s", e)
            return ["BTC/USDT", "ETH/USDT", "XLM/USDT"]  # fallback
