from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from indicators import TechnicalIndicators


class IndicatorQualityTests(unittest.TestCase):
    def setUp(self):
        self.indicators = TechnicalIndicators()

    def test_rsi_returns_neutral_value_on_flat_series(self):
        prices = pd.Series([100.0] * 40)

        rsi = self.indicators.calculate_rsi(prices, period=14)

        self.assertAlmostEqual(float(rsi.iloc[-1]), 50.0, places=2)

    def test_detect_market_regime_flags_ranging_market(self):
        close = pd.Series(100 + np.sin(np.linspace(0, 6 * np.pi, 60)) * 0.12)
        volume = pd.Series([1_000 + (idx % 4) * 10 for idx in range(60)])
        atr = pd.Series([0.14] * 60)
        adx = pd.Series([15.0] * 60)
        di_plus = pd.Series([18.0] * 60)
        di_minus = pd.Series([16.0] * 60)

        regime = self.indicators.detect_market_regime(
            close=close,
            volume=volume,
            atr=atr,
            adx=adx,
            period=20,
            di_plus=di_plus,
            di_minus=di_minus,
        )

        self.assertEqual(regime, "ranging")

    def test_detect_market_regime_flags_trending_market(self):
        close = pd.Series(np.linspace(100, 120, 60) + np.sin(np.linspace(0, 5 * np.pi, 60)) * 0.25)
        volume = pd.Series(np.linspace(1_100, 1_900, 60))
        atr = pd.Series(np.linspace(0.9, 1.2, 60))
        adx = pd.Series(np.linspace(28, 38, 60))
        di_plus = pd.Series([34.0] * 60)
        di_minus = pd.Series([11.0] * 60)

        regime = self.indicators.detect_market_regime(
            close=close,
            volume=volume,
            atr=atr,
            adx=adx,
            period=20,
            di_plus=di_plus,
            di_minus=di_minus,
        )

        self.assertEqual(regime, "trending")

    def test_signal_confidence_penalizes_ranging_market(self):
        base_indicators = {
            "rsi": 19.0,
            "macd": 1.2,
            "macd_signal": 0.6,
            "macd_histogram": 0.5,
            "prev_macd_histogram": 0.3,
            "trend_analysis": "FORTE_ALTA",
            "trend_strength": 85,
            "adx": 31.0,
            "stoch_rsi_k": 12.0,
            "williams_r": -88.0,
            "volume_ratio": 2.1,
        }

        trending_confidence = self.indicators.calculate_signal_confidence(
            {**base_indicators, "market_regime": "trending"}
        )
        ranging_confidence = self.indicators.calculate_signal_confidence(
            {**base_indicators, "market_regime": "ranging"}
        )

        self.assertGreater(trending_confidence, ranging_confidence)
        self.assertLess(ranging_confidence, 50)


if __name__ == "__main__":
    unittest.main()
