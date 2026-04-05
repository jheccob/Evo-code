import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Optional, Tuple

from trading_bot import TradingBot
from config.exchange_config import ExchangeConfig


class FuturesTrading(TradingBot):

    def __init__(self, exchange_name='binance'):
        super().__init__()

        self.exchange = ExchangeConfig.get_exchange_instance(exchange_name, testnet=False)
        self.exchange_name = exchange_name

        # 🔥 ESSENCIAL para futuros na Binance
        self.exchange.options['defaultType'] = 'future'

        self.symbol = "XLM/USDT"

        # Configs
        self.leverage = 5
        self.position_size_pct = 0.1
        self.stop_loss_pct = 0.02
        self.take_profit_pct = 0.04
        self.max_positions = 3

    # =========================
    # 🔧 CONFIGURAÇÃO
    # =========================
    def set_leverage(self, symbol: str, leverage: int):
        try:
            self.exchange.set_leverage(leverage, symbol)
            self.leverage = leverage
            return True, f"{leverage}x definido para {symbol}"
        except Exception as e:
            return False, str(e)

    # =========================
    # 💰 SALDO FUTUROS
    # =========================
    def get_account_balance(self):
        try:
            balance = self.exchange.fetch_balance({'type': 'future'})

            usdt = balance.get('USDT', {})
            info = balance.get('info', {})

            return {
                'total_balance': usdt.get('total', 0),
                'available_balance': usdt.get('free', 0),
                'used_balance': usdt.get('used', 0),
                'unrealized_pnl': float(info.get('totalUnrealizedProfit', 0)),
                'margin_ratio': float(info.get('totalMaintMargin', 0)),
            }

        except Exception as e:
            print(f"Erro saldo: {e}")
            return None

    # =========================
    # 📊 POSIÇÕES ABERTAS
    # =========================
    def get_open_positions(self):
        try:
            positions = self.exchange.fetch_positions([self.symbol])
            return [p for p in positions if float(p['contracts']) > 0]
        except Exception as e:
            print(f"Erro posições: {e}")
            return []

    # =========================
    # 📏 TAMANHO DA POSIÇÃO (COM RISCO REAL)
    # =========================
    def calculate_position_size(self, balance: float, price: float):

        risk_per_trade = balance * 0.01  # 🔥 1% risco real

        stop_distance = price * self.stop_loss_pct

        quantity = risk_per_trade / stop_distance

        # aplicar alavancagem
        quantity = quantity * self.leverage

        # respeitar mínimo da exchange
        market = self.exchange.market(self.symbol)
        min_qty = market['limits']['amount']['min'] or 0.0001

        return round(max(quantity, min_qty), 6)

    # =========================
    # 🚀 CRIAR ORDEM COMPLETA
    # =========================
    def create_futures_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: Optional[float] = None
    ):

        try:
            # 🚫 Limite de posições
            if len(self.get_open_positions()) >= self.max_positions:
                return False, "Máximo de posições atingido"

            ticker = self.exchange.fetch_ticker(symbol)
            current_price = ticker['last']

            # 🎯 SL / TP
            if side.lower() == 'buy':
                stop_loss = current_price * (1 - self.stop_loss_pct)
                take_profit = current_price * (1 + self.take_profit_pct)
            else:
                stop_loss = current_price * (1 + self.stop_loss_pct)
                take_profit = current_price * (1 - self.take_profit_pct)

            # 🟢 ORDEM PRINCIPAL
            order = self.exchange.create_order(
                symbol=symbol,
                type='market',
                side=side,
                amount=quantity
            )

            # 🔴 STOP LOSS
            self.exchange.create_order(
                symbol=symbol,
                type='STOP_MARKET',
                side='sell' if side == 'buy' else 'buy',
                amount=quantity,
                params={
                    'stopPrice': stop_loss,
                    'reduceOnly': True
                }
            )

            # 🟢 TAKE PROFIT
            self.exchange.create_order(
                symbol=symbol,
                type='TAKE_PROFIT_MARKET',
                side='sell' if side == 'buy' else 'buy',
                amount=quantity,
                params={
                    'stopPrice': take_profit,
                    'reduceOnly': True
                }
            )

            return True, {
                "order": order,
                "stop_loss": stop_loss,
                "take_profit": take_profit
            }

        except Exception as e:
            return False, str(e)
