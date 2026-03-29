import tempfile
import threading
import unittest
from unittest import mock
from pathlib import Path

import pandas as pd

from config import ProductionConfig
from database.database import db as runtime_db
from futures_trading import FuturesTrading


class FuturesTradingSafetyTests(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self._original_runtime_state_path = ProductionConfig.BINANCE_FUTURES_RUNTIME_STATE_PATH
        ProductionConfig.BINANCE_FUTURES_RUNTIME_STATE_PATH = str(
            Path(self._tempdir.name) / "binance_futures_runtime_state.json"
        )

    def tearDown(self):
        ProductionConfig.BINANCE_FUTURES_RUNTIME_STATE_PATH = self._original_runtime_state_path
        self._tempdir.cleanup()

    def test_init_keeps_exchange_lazy_reuses_runtime_db_and_defaults_to_testnet(self):
        with mock.patch.object(
            FuturesTrading,
            "_load_exchange",
            side_effect=AssertionError("exchange nao deve carregar no __init__"),
        ):
            bot = FuturesTrading()

        self.assertIsNone(bot._exchange)
        self.assertIs(bot.database, runtime_db)
        self.assertEqual(bot.get_exchange_environment(), "testnet")

    def test_create_futures_order_blocks_new_live_orders_when_not_ready(self):
        bot = FuturesTrading.__new__(FuturesTrading)
        bot.exchange = mock.Mock()
        bot.timeframe = "1h"
        bot.symbol = "BTC/USDT"
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
        bot.exchange.create_order.assert_not_called()

    def test_create_futures_order_calls_exchange_with_native_protection_when_live_is_ready(self):
        bot = FuturesTrading.__new__(FuturesTrading)
        bot.exchange = mock.Mock()
        bot.timeframe = "1h"
        bot.symbol = "BTC/USDT"
        bot._exchange_testnet = True
        bot.get_live_execution_readiness = mock.Mock(return_value={"allowed": True})
        bot.reconcile_symbol_state = mock.Mock(
            return_value={
                "open_position": True,
                "has_stop_loss": True,
                "has_take_profit": True,
                "status": "healthy",
                "warnings": [],
            }
        )
        bot.exchange.create_order.side_effect = [
            {"id": "entry-1", "average": 100.0, "filled": 1.0},
            {"id": "sl-1"},
            {"id": "tp-1"},
        ]

        success, result = FuturesTrading.create_futures_order(
            bot,
            symbol="BTC/USDT",
            side="buy",
            quantity=1.0,
            stop_loss=95.0,
            take_profit=110.0,
        )

        self.assertTrue(success)
        self.assertEqual(result["order_id"], "entry-1")
        self.assertEqual(result["environment"], "testnet")
        self.assertEqual(len(result["protection_orders"]), 2)
        self.assertEqual(result["protection_errors"], [])
        self.assertEqual(result["runtime_snapshot"]["status"], "open")

        entry_call = bot.exchange.create_order.call_args_list[0]
        self.assertEqual(entry_call.kwargs["symbol"], "BTC/USDT")
        self.assertEqual(entry_call.kwargs["type"], "market")
        self.assertEqual(entry_call.kwargs["side"], "buy")
        self.assertEqual(entry_call.kwargs["amount"], 1.0)
        self.assertEqual(
            entry_call.kwargs["params"]["newOrderRespType"],
            ProductionConfig.BINANCE_FUTURES_ENTRY_RESPONSE_TYPE,
        )
        self.assertIn("newClientOrderId", entry_call.kwargs["params"])

        stop_call = bot.exchange.create_order.call_args_list[1]
        self.assertEqual(stop_call.kwargs["type"], "STOP_MARKET")
        self.assertEqual(stop_call.kwargs["side"], "sell")
        self.assertIsNone(stop_call.kwargs["amount"])
        self.assertTrue(stop_call.kwargs["params"]["closePosition"])
        self.assertEqual(stop_call.kwargs["params"]["stopPrice"], 95.0)
        self.assertEqual(
            stop_call.kwargs["params"]["workingType"],
            ProductionConfig.BINANCE_FUTURES_WORKING_TYPE,
        )

        take_call = bot.exchange.create_order.call_args_list[2]
        self.assertEqual(take_call.kwargs["type"], "TAKE_PROFIT_MARKET")
        self.assertEqual(take_call.kwargs["side"], "sell")
        self.assertTrue(take_call.kwargs["params"]["closePosition"])
        self.assertEqual(take_call.kwargs["params"]["stopPrice"], 110.0)

    def test_create_futures_order_rejects_invalid_side(self):
        bot = FuturesTrading.__new__(FuturesTrading)
        bot.exchange = mock.Mock()
        bot.timeframe = "1h"
        bot.symbol = "BTC/USDT"
        bot.get_live_execution_readiness = mock.Mock(return_value={"allowed": True})

        success, message = FuturesTrading.create_futures_order(
            bot,
            symbol="BTC/USDT",
            side="hold",
            quantity=1.0,
        )

        self.assertFalse(success)
        self.assertIn("buy", message)
        bot.exchange.create_order.assert_not_called()

    def test_create_futures_order_rejects_non_positive_quantity(self):
        bot = FuturesTrading.__new__(FuturesTrading)
        bot.exchange = mock.Mock()
        bot.timeframe = "1h"
        bot.symbol = "BTC/USDT"
        bot.get_live_execution_readiness = mock.Mock(return_value={"allowed": True})

        success, message = FuturesTrading.create_futures_order(
            bot,
            symbol="BTC/USDT",
            side="buy",
            quantity=0,
        )

        self.assertFalse(success)
        self.assertIn("Quantidade", message)
        bot.exchange.create_order.assert_not_called()

    def test_generate_futures_signal_uses_risk_plan_quantity(self):
        bot = FuturesTrading.__new__(FuturesTrading)
        bot.symbol = "BTC/USDT"
        bot.timeframe = "15m"
        bot.leverage = 5
        bot.stop_loss_pct = 0.008
        bot.take_profit_pct = 0.018
        bot.risk_management_service = mock.Mock()
        bot.risk_management_service.evaluate_risk_engine.return_value = {
            "allowed": True,
            "quantity": 0.123456,
            "risk_mode": "normal",
        }
        bot.evaluate_signal_pipeline = mock.Mock(
            return_value={
                "approved_signal": "COMPRA",
                "trade_decision": {"confidence": 7.3},
            }
        )

        df = pd.DataFrame([{"close": 100.0}])

        signal = FuturesTrading.generate_futures_signal(bot, df, account_balance=1000.0)

        self.assertEqual(signal["position_side"], "LONG")
        self.assertAlmostEqual(signal["quantity"], 0.123456)
        self.assertTrue(signal["risk_allowed"])
        self.assertEqual(signal["risk_plan"]["risk_mode"], "normal")

    def test_execute_futures_trade_blocks_when_risk_plan_disallows(self):
        bot = FuturesTrading.__new__(FuturesTrading)
        bot.symbol = "BTC/USDT"

        result = FuturesTrading.execute_futures_trade(
            bot,
            {
                "signal": "COMPRA",
                "position_side": "LONG",
                "quantity": 0.5,
                "risk_reason": "Drawdown acima do limite.",
                "risk_plan": {"allowed": False, "reason": "Drawdown acima do limite."},
            },
            dry_run=False,
        )

        self.assertFalse(result["success"])
        self.assertIn("Drawdown", result["message"])

    def test_reconcile_symbol_state_reports_missing_native_protection(self):
        bot = FuturesTrading.__new__(FuturesTrading)
        bot.exchange = mock.Mock()
        bot._exchange_testnet = True
        bot.exchange.fetch_open_orders.return_value = []
        bot.exchange.fetch_my_trades.return_value = []
        bot.get_open_positions = mock.Mock(
            return_value=[
                {
                    "symbol": "BTC/USDT",
                    "side": "long",
                    "size": 0.5,
                    "entry_price": 100.0,
                }
            ]
        )

        reconciliation = FuturesTrading.reconcile_symbol_state(bot, "BTC/USDT")

        self.assertEqual(reconciliation["status"], "warning")
        self.assertTrue(reconciliation["open_position"])
        self.assertFalse(reconciliation["has_stop_loss"])
        self.assertFalse(reconciliation["has_take_profit"])
        self.assertGreaterEqual(len(reconciliation["warnings"]), 2)

    def test_recover_symbol_state_recreates_missing_protection_from_snapshot(self):
        bot = FuturesTrading.__new__(FuturesTrading)
        bot.exchange_name = "binance"
        bot.symbol = "BTC/USDT"
        bot.timeframe = "15m"
        bot._exchange_testnet = True
        bot._runtime_state_lock = threading.RLock()
        bot._create_native_exit_orders = mock.Mock(
            return_value=(
                [
                    {"label": "stop_loss", "order_id": "sl-1"},
                    {"label": "take_profit", "order_id": "tp-1"},
                ],
                [],
            )
        )
        bot.reconcile_symbol_state = mock.Mock(
            side_effect=[
                {
                    "open_position": True,
                    "has_stop_loss": False,
                    "has_take_profit": False,
                    "status": "warning",
                    "position": {"side": "long", "size": 0.5, "entry_price": 100.0},
                    "warnings": ["sem protecao"],
                },
                {
                    "open_position": True,
                    "has_stop_loss": True,
                    "has_take_profit": True,
                    "status": "healthy",
                    "position": {"side": "long", "size": 0.5, "entry_price": 100.0},
                    "warnings": [],
                },
            ]
        )

        FuturesTrading._persist_runtime_snapshot(
            bot,
            {
                "symbol": "BTC/USDT",
                "status": "open",
                "entry_side": "buy",
                "entry_price": 100.0,
                "stop_loss": 95.0,
                "take_profit": 110.0,
                "protection_orders": [],
            },
        )

        recovery = FuturesTrading.recover_symbol_state(bot, "BTC/USDT", source="startup")

        self.assertTrue(recovery["restored"])
        bot._create_native_exit_orders.assert_called_once_with(
            symbol="BTC/USDT",
            entry_side="buy",
            stop_loss=95.0,
            take_profit=110.0,
        )
        self.assertEqual(recovery["status"], "healthy")

    def test_handle_user_stream_event_triggers_recovery_on_trade_update(self):
        bot = FuturesTrading.__new__(FuturesTrading)
        bot.exchange_name = "binance"
        bot.symbol = "BTC/USDT"
        bot.timeframe = "15m"
        bot._exchange_testnet = True
        bot._runtime_state_lock = threading.RLock()
        bot._last_recovery_timestamps = {}
        bot.recover_symbol_state = mock.Mock(return_value={"status": "healthy"})
        bot._persist_runtime_snapshot = mock.Mock()

        FuturesTrading._handle_user_stream_event(
            bot,
            {
                "e": "ORDER_TRADE_UPDATE",
                "E": 1710000000000,
                "o": {
                    "s": "BTCUSDT",
                    "c": "evo_entry_btc",
                    "X": "FILLED",
                    "x": "TRADE",
                },
            },
        )

        bot._persist_runtime_snapshot.assert_called()
        bot.recover_symbol_state.assert_called_once_with(
            "BTC/USDT",
            source="user_stream:order_trade_update",
        )


if __name__ == "__main__":
    unittest.main()
