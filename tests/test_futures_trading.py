import unittest
from unittest import mock

from futures_trading import FuturesTrading


class FuturesTradingSafetyTests(unittest.TestCase):
    def test_create_futures_order_blocks_new_live_orders_when_not_ready(self):
        bot = FuturesTrading.__new__(FuturesTrading)
        bot.exchange = mock.Mock()
        bot.timeframe = "1h"
        bot.get_live_execution_readiness = mock.Mock(
            return_value={
                "allowed": False,
                "message": "Execucao live bloqueada: setup ainda nao aprovado.",
            }
        )

        success, message = FuturesTrading.create_futures_order(
            bot,
            symbol="BTC/USDT",
            side="buy",
            quantity=1.0,
        )

        self.assertFalse(success)
        self.assertIn("Execucao live bloqueada", message)
        bot.exchange.create_market_order.assert_not_called()

    def test_create_futures_order_calls_exchange_when_live_is_ready(self):
        bot = FuturesTrading.__new__(FuturesTrading)
        bot.exchange = mock.Mock()
        bot.timeframe = "1h"
        bot.get_live_execution_readiness = mock.Mock(return_value={"allowed": True})
        bot.exchange.create_market_order.return_value = {"id": "abc123", "price": 100.0}
        bot._create_stop_loss_order = mock.Mock()
        bot._create_take_profit_order = mock.Mock()

        success, result = FuturesTrading.create_futures_order(
            bot,
            symbol="BTC/USDT",
            side="buy",
            quantity=1.0,
            stop_loss=95.0,
            take_profit=110.0,
        )

        self.assertTrue(success)
        self.assertEqual(result["order_id"], "abc123")
        bot.exchange.create_market_order.assert_called_once_with("BTC/USDT", "buy", 1.0)
        bot._create_stop_loss_order.assert_called_once()
        bot._create_take_profit_order.assert_called_once()


if __name__ == "__main__":
    unittest.main()
