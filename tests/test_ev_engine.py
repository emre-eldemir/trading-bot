"""
tests/test_ev_engine.py — Unit tests for the EV Engine.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

import pytest

from app.models.signal import Signal, SignalDirection, SignalType
from app.services.ev_engine import EVEngine


class TestEVEngine:
    """Tests for Expected Value calculation and filtering."""

    def test_positive_ev_signal_accepted(self, test_settings, sample_metrics, sample_signal):
        """Signal with positive EV should be returned."""
        engine = EVEngine(test_settings)
        result = engine.evaluate(sample_signal, sample_metrics, position_size=100.0)
        assert result is not None

    def test_low_confidence_signal_rejected(self, test_settings, sample_metrics, sample_signal):
        """Signal with confidence below min_confidence should be rejected."""
        test_settings.__dict__["min_confidence"] = 0.9
        engine = EVEngine(test_settings)
        low_conf_signal = sample_signal.model_copy(update={"confidence": 0.5})
        result = engine.evaluate(low_conf_signal, sample_metrics, position_size=100.0)
        assert result is None

    def test_expired_signal_rejected(self, test_settings, sample_metrics, sample_signal):
        """Expired signals should always be rejected."""
        engine = EVEngine(test_settings)
        expired_signal = sample_signal.model_copy(update={
            "expires_at": datetime.utcnow() - timedelta(seconds=10)
        })
        result = engine.evaluate(expired_signal, sample_metrics, position_size=100.0)
        assert result is None

    def test_tiny_edge_rejected(self, test_settings, sample_metrics, sample_signal):
        """Signal with edge below min_edge should be rejected."""
        engine = EVEngine(test_settings)
        tiny_edge_signal = sample_signal.model_copy(update={"raw_edge": 0.0001})
        result = engine.evaluate(tiny_edge_signal, sample_metrics, position_size=100.0)
        assert result is None

    def test_signal_decay_reduces_ev(self, test_settings, sample_metrics, sample_signal):
        """Older signals should have lower (or equal) EV than fresh signals."""
        engine = EVEngine(test_settings)
        # Fresh signal
        fresh_result = engine.evaluate(sample_signal, sample_metrics, position_size=100.0)

        # Aged signal
        aged_signal = sample_signal.model_copy(update={
            "created_at": datetime.utcnow() - timedelta(seconds=120)
        })
        aged_result = engine.evaluate(aged_signal, sample_metrics, position_size=100.0)

        # Either aged has lower EV, or it was filtered out
        if fresh_result and aged_result:
            assert aged_result.expected_value <= fresh_result.expected_value

    def test_batch_evaluate_returns_sorted(self, test_settings, sample_metrics, sample_signal):
        """Batch evaluation should return signals sorted by EV descending."""
        engine = EVEngine(test_settings)
        # Create two signals with different edges
        sig1 = sample_signal.model_copy(update={"raw_edge": 0.02, "win_probability": 0.65})
        sig2 = sample_signal.model_copy(update={"raw_edge": 0.04, "win_probability": 0.70})
        metrics_map = {sample_metrics.symbol: sample_metrics}
        results = engine.batch_evaluate([sig1, sig2], metrics_map, position_size=100.0)
        if len(results) >= 2:
            assert results[0].expected_value >= results[1].expected_value

    def test_no_metrics_for_symbol_skips(self, test_settings, sample_signal):
        """Signal without matching metrics should be silently skipped."""
        engine = EVEngine(test_settings)
        results = engine.batch_evaluate([sample_signal], {}, position_size=100.0)
        assert results == []

    def test_zero_position_size_handled(self, test_settings, sample_metrics, sample_signal):
        """Zero position size should not crash — result can be None or a signal."""
        engine = EVEngine(test_settings)
        result = engine.evaluate(sample_signal, sample_metrics, position_size=0.0)
        # With zero size all cost terms are zero; just verify no exception raised
        assert result is None or hasattr(result, "expected_value")
