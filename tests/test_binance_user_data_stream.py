import unittest
from unittest import mock

from services.binance_user_data_stream import BinanceFuturesUserDataStream


class BinanceUserDataStreamTests(unittest.TestCase):
    def test_build_ws_url_uses_testnet_base(self):
        stream = BinanceFuturesUserDataStream(exchange=mock.Mock(), testnet=True)

        url = stream._build_ws_url("listen-key")

        self.assertIn("stream.binancefuture.com/ws/listen-key", url)

    def test_listen_key_lifecycle_uses_fapi_methods(self):
        exchange = mock.Mock()
        exchange.fapiPrivatePostListenKey.return_value = {"listenKey": "abc123"}
        stream = BinanceFuturesUserDataStream(exchange=exchange, testnet=False)

        listen_key = stream._start_listen_key()
        stream._keepalive_listen_key()
        stream._close_listen_key()

        self.assertEqual(listen_key, "abc123")
        exchange.fapiPrivatePostListenKey.assert_called_once_with({})
        exchange.fapiPrivatePutListenKey.assert_called_once_with({"listenKey": "abc123"})
        exchange.fapiPrivateDeleteListenKey.assert_called_once_with({"listenKey": "abc123"})

    def test_dispatch_event_invokes_callback(self):
        callback = mock.Mock()
        stream = BinanceFuturesUserDataStream(exchange=mock.Mock(), on_event=callback)

        payload = {"e": "ORDER_TRADE_UPDATE", "E": 123}
        stream._dispatch_event(payload)

        callback.assert_called_once_with(payload)
        status = stream.get_status()
        self.assertEqual(status["events_processed"], 1)
        self.assertEqual(status["last_event_type"], "ORDER_TRADE_UPDATE")


if __name__ == "__main__":
    unittest.main()
