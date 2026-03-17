"""
tests/test_risk_manager.py — Unit tests for the Risk Manager.
"""

from __future__ import annotations

import pytest

from app.models.signal import Signal, SignalDirection, SignalType
from app.risk.kill_switch import KillSwitch
from app.risk.regime_detector import RegimeDetector
from app.risk.risk_manager import RiskManager
from app.services.bankroll_manager import BankrollManager


@pytest.fixture
def risk_components(test_settings):
    """Provide standard risk management components."""
    bankroll = BankrollManager(test_settings)
    kill_switch = KillSwitch()
    regime = RegimeDetector(settings=test_settings)
    risk_manager = RiskManager(bankroll, kill_switch, regime, test_settings)
    return bankroll, kill_switch, regime, risk_manager


class TestKillSwitch:
    """Tests for the kill switch mechanism."""

    def test_initially_inactive(self):
        ks = KillSwitch()
        assert not ks.is_active

    def test_activation(self):
        ks = KillSwitch()
        ks.activate("test reason")
        assert ks.is_active
        assert ks.reason == "test reason"

    def test_double_activation_idempotent(self):
        ks = KillSwitch()
        ks.activate("first")
        ks.activate("second")  # Should not overwrite
        assert ks.reason == "first"

    def test_reset_requires_confirmation(self):
        ks = KillSwitch()
        ks.activate("test")
        assert not ks.reset(operator_confirmed=False)
        assert ks.is_active

    def test_reset_with_confirmation(self):
        ks = KillSwitch()
        ks.activate("test")
        assert ks.reset(operator_confirmed=True)
        assert not ks.is_active

    def test_check_raises_when_active(self):
        ks = KillSwitch()
        ks.activate("test")
        with pytest.raises(RuntimeError):
            ks.check()


class TestRiskManager:
    """Tests for the Risk Manager pre-trade checks."""

    def test_allows_valid_trade(self, risk_components, sample_signal):
        bankroll, kill_switch, regime, risk_manager = risk_components
        allowed, reason = risk_manager.check_pre_trade(sample_signal, 100.0, [])
        assert allowed
        assert reason == ""

    def test_blocks_when_kill_switch_active(self, risk_components, sample_signal):
        bankroll, kill_switch, regime, risk_manager = risk_components
        kill_switch.activate("test")
        allowed, reason = risk_manager.check_pre_trade(sample_signal, 100.0, [])
        assert not allowed
        assert "kill switch" in reason.lower()

    def test_blocks_on_daily_loss_limit(self, risk_components, sample_signal, test_settings):
        bankroll, kill_switch, regime, risk_manager = risk_components
        # Simulate daily loss exceeding limit
        bankroll._total_equity = 9700.0  # 3% loss, limit is 2%
        bankroll._daily_start_equity = 10000.0
        allowed, reason = risk_manager.check_pre_trade(sample_signal, 100.0, [])
        assert not allowed
        assert "daily loss" in reason.lower()

    def test_blocks_on_max_positions(self, risk_components, sample_signal, sample_position, test_settings):
        bankroll, kill_switch, regime, risk_manager = risk_components
        # Create max_open_positions positions
        positions = [sample_position] * test_settings.max_open_positions
        allowed, reason = risk_manager.check_pre_trade(sample_signal, 100.0, positions)
        assert not allowed

    def test_blocks_on_insufficient_capital(self, risk_components, sample_signal):
        bankroll, kill_switch, regime, risk_manager = risk_components
        # Request more than available capital
        allowed, reason = risk_manager.check_pre_trade(
            sample_signal,
            bankroll.available_capital * 2,  # 2x available
            [],
        )
        assert not allowed


class TestRegimeDetector:
    """Tests for volatility regime detection."""

    def test_initial_regime_is_normal(self, test_settings):
        detector = RegimeDetector(settings=test_settings)
        assert detector.current_regime.value == "normal"

    def test_risk_multiplier_is_1_in_normal(self, test_settings):
        detector = RegimeDetector(settings=test_settings)
        assert detector.risk_multiplier == 1.0

    def test_update_with_stable_prices_stays_normal(self, test_settings):
        detector = RegimeDetector(settings=test_settings)
        for _ in range(20):
            detector.update(65000.0)  # Constant price = zero volatility
        # With zero volatility, should be LOW or NORMAL
        assert detector.current_regime.value in ("low", "normal")
