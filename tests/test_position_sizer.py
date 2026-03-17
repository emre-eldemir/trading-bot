"""
tests/test_position_sizer.py — Unit tests for the Position Sizer.
"""

from __future__ import annotations

import pytest

from app.services.bankroll_manager import BankrollManager
from app.services.position_sizer import PositionSizer
from app.utils.math_helpers import (
    fractional_kelly,
    kelly_fraction,
    dynamic_kelly_fraction,
    correlation_adjusted_kelly,
)


class TestKellyMath:
    """Tests for Kelly Criterion math helpers."""

    def test_kelly_with_positive_edge(self):
        """Kelly fraction should be positive when edge > 0."""
        result = kelly_fraction(win_probability=0.60, win_payout=1.0)
        assert result > 0

    def test_kelly_with_zero_edge(self):
        """Kelly fraction should be zero when win_prob=0.5 and payout=1."""
        result = kelly_fraction(win_probability=0.50, win_payout=1.0)
        assert abs(result) < 1e-9

    def test_kelly_with_no_edge(self):
        """Kelly should return negative for unfavourable bets."""
        result = kelly_fraction(win_probability=0.40, win_payout=1.0)
        assert result < 0

    def test_fractional_kelly_smaller_than_full(self):
        """Fractional Kelly should always be <= full Kelly."""
        full = kelly_fraction(0.60, 1.0)
        frac = fractional_kelly(0.60, 1.0, fraction=0.25)
        assert frac <= full
        assert frac > 0

    def test_fractional_kelly_negative_returns_zero(self):
        """No-edge bets return 0 (not negative)."""
        result = fractional_kelly(0.40, 1.0, fraction=0.25)
        assert result == 0.0

    def test_dynamic_kelly_reduces_at_threshold(self):
        """Dynamic Kelly should reduce fraction at configured drawdown levels."""
        thresholds = [
            {"drawdown": 0.05, "multiplier": 0.75},
            {"drawdown": 0.10, "multiplier": 0.50},
        ]
        result = dynamic_kelly_fraction(0.25, current_drawdown=0.12, thresholds=thresholds)
        assert result == pytest.approx(0.25 * 0.50, rel=1e-5)

    def test_dynamic_kelly_no_reduction_below_threshold(self):
        """Dynamic Kelly should not reduce below first threshold."""
        thresholds = [{"drawdown": 0.10, "multiplier": 0.50}]
        result = dynamic_kelly_fraction(0.25, current_drawdown=0.03, thresholds=thresholds)
        assert result == pytest.approx(0.25, rel=1e-5)

    def test_correlation_adjusted_kelly_reduces_with_correlated(self):
        """Correlated positions should reduce new position size."""
        original = 0.10
        # 20% of bankroll in a highly correlated position
        result = correlation_adjusted_kelly(
            kelly_size=original,
            open_positions=[0.20],
            correlations=[0.90],
            correlation_threshold=0.70,
        )
        assert result < original

    def test_correlation_adjusted_kelly_no_change_uncorrelated(self):
        """Uncorrelated positions should not reduce new position size."""
        original = 0.10
        result = correlation_adjusted_kelly(
            kelly_size=original,
            open_positions=[0.20],
            correlations=[0.30],  # Below threshold
            correlation_threshold=0.70,
        )
        assert result == original


class TestPositionSizer:
    """Tests for PositionSizer component."""

    def test_basic_size_computation(self, test_settings, sample_signal, bankroll):
        """Should return a positive size for a signal with positive edge."""
        sizer = PositionSizer(bankroll, test_settings)
        size = sizer.compute_size(sample_signal)
        assert 0 < size <= test_settings.max_position_fraction

    def test_size_within_limits(self, test_settings, sample_signal, bankroll):
        """Size should respect min/max position fraction limits."""
        sizer = PositionSizer(bankroll, test_settings)
        size = sizer.compute_size(sample_signal)
        assert size >= test_settings.min_position_fraction
        assert size <= test_settings.max_position_fraction

    def test_dollar_size_returns_float(self, test_settings, sample_signal, bankroll):
        """Dollar size computation should return a positive float."""
        sizer = PositionSizer(bankroll, test_settings)
        dollar = sizer.compute_dollar_size(sample_signal)
        assert isinstance(dollar, float)
        assert dollar >= 0

    def test_drawdown_reduces_size(self, test_settings, sample_signal):
        """Higher drawdown should produce smaller position sizes."""
        bankroll_fresh = BankrollManager(test_settings)
        bankroll_distressed = BankrollManager(test_settings)
        # Simulate drawdown
        bankroll_distressed._total_equity = 8000.0  # 20% drawdown from 10000

        sizer_fresh = PositionSizer(bankroll_fresh, test_settings)
        sizer_distressed = PositionSizer(bankroll_distressed, test_settings)

        size_fresh = sizer_fresh.compute_size(sample_signal)
        size_distressed = sizer_distressed.compute_size(sample_signal)
        # Distressed should be <= fresh
        assert size_distressed <= size_fresh
