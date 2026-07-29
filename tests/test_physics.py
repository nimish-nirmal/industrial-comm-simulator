"""Tests for PhysicsEngine and signal simulation."""
from __future__ import annotations

import pytest

from src.core.physics import (
    PhysicsConfig,
    PhysicsEngine,
    SignalProfile,
    SignalState,
    SignalType,
    UnitCategory,
    water_tank_profiles,
    hvac_profiles,
    power_grid_profiles,
)


class TestPhysicsEngine:
    """Test suite for PhysicsEngine."""

    def test_signal_registration(self, physics_engine, water_tank_signals):
        """Test that signals are properly registered."""
        profiles = water_tank_signals
        states = physics_engine.add_signals(profiles)
        
        assert len(states) == len(profiles)
        assert len(physics_engine.signals) == len(profiles)
        for state in states:
            assert state.profile.name in physics_engine.signals

    def test_initial_values(self, physics_engine, water_tank_signals):
        """Test that initial values are set correctly."""
        physics_engine.add_signals(water_tank_signals)
        values = physics_engine.get_all_values()
        
        # Check that values are within bounds
        for name, state in physics_engine.signals.items():
            assert state.profile.min_value <= values[name] <= state.profile.max_value

    def test_step_returns_all_values(self, physics_engine, water_tank_signals):
        """Test that step() returns values for all signals."""
        physics_engine.add_signals(water_tank_signals)
        values = physics_engine.step(1.0)
        
        assert len(values) == len(water_tank_signals)
        for profile in water_tank_signals:
            assert profile.name in values

    def test_deterministic_mode(self, physics_engine):
        """Test that same seed produces same results."""
        profiles = water_tank_profiles()
        
        # Run first simulation
        engine1 = PhysicsEngine(PhysicsConfig(seed=42))
        engine1.add_signals(profiles)
        vals1 = [engine1.step(1.0)["Tank Level"] for _ in range(5)]
        
        # Run second simulation with same seed
        engine2 = PhysicsEngine(PhysicsConfig(seed=42))
        engine2.add_signals(profiles)
        vals2 = [engine2.step(1.0)["Tank Level"] for _ in range(5)]
        
        assert vals1 == vals2

    def test_signal_clamping(self, physics_engine):
        """Test that signals are clamped to min/max bounds."""
        profile = SignalProfile(
            name="Test Signal",
            signal_type=SignalType.ANALOG,
            min_value=0.0,
            max_value=100.0,
            initial_value=50.0,
            noise_amplitude=0.0,
            drift_amplitude=0.0,
        )
        physics_engine.add_signal(profile)
        
        # Set value above max
        physics_engine.set_value("Test Signal", 150.0)
        assert physics_engine.get_value("Test Signal") == 100.0
        
        # Set value below min
        physics_engine.set_value("Test Signal", -50.0)
        assert physics_engine.get_value("Test Signal") == 0.0

    def test_binary_signal_type(self, physics_engine):
        """Test binary signal type (0 or 1)."""
        profile = SignalProfile(
            name="Binary Test",
            signal_type=SignalType.BINARY,
            min_value=0.0,
            max_value=1.0,
            initial_value=0.5,
            noise_amplitude=0.0,
            drift_amplitude=0.0,
        )
        physics_engine.add_signal(profile)
        
        # Step should produce 0 or 1
        for _ in range(10):
            values = physics_engine.step(1.0)
            assert values["Binary Test"] in (0.0, 1.0)

    def test_discrete_signal_type(self, physics_engine):
        """Test discrete signal type (integer values)."""
        profile = SignalProfile(
            name="Discrete Test",
            signal_type=SignalType.DISCRETE,
            min_value=0.0,
            max_value=5.0,
            initial_value=2.5,
            noise_amplitude=0.0,
            drift_amplitude=0.0,
        )
        physics_engine.add_signal(profile)
        
        # Step should produce integer values
        for _ in range(10):
            values = physics_engine.step(1.0)
            assert values["Discrete Test"] == int(values["Discrete Test"])

    def test_counter_monotonic(self, physics_engine):
        """Test that counter signals only increase."""
        profile = SignalProfile(
            name="Counter Test",
            signal_type=SignalType.COUNTER,
            min_value=0.0,
            max_value=1000.0,
            initial_value=10.0,
            noise_amplitude=0.0,
            drift_amplitude=0.0,
        )
        physics_engine.add_signal(profile)
        
        prev_value = physics_engine.get_value("Counter Test")
        for _ in range(10):
            values = physics_engine.step(1.0)
            current = values["Counter Test"]
            assert current >= prev_value
            prev_value = current

    def test_reset(self, physics_engine, water_tank_signals):
        """Test reset() returns signals to initial values."""
        physics_engine.add_signals(water_tank_signals)
        
        # Step several times
        for _ in range(10):
            physics_engine.step(1.0)
        
        # Reset
        physics_engine.reset()
        
        # Check all values are back to initial
        for name, state in physics_engine.signals.items():
            assert state.current_value == state.profile.initial_value
            assert state.noise_component == 0.0
            assert state.drift_component == 0.0

    def test_set_value_clamping(self, physics_engine):
        """Test that set_value() clamps to bounds."""
        profile = SignalProfile(
            name="Clamp Test",
            signal_type=SignalType.ANALOG,
            min_value=10.0,
            max_value=20.0,
            initial_value=15.0,
        )
        physics_engine.add_signal(profile)
        
        physics_engine.set_value("Clamp Test", 25.0)
        assert physics_engine.get_value("Clamp Test") == 20.0
        
        physics_engine.set_value("Clamp Test", 5.0)
        assert physics_engine.get_value("Clamp Test") == 10.0

    def test_percentage_property(self, physics_engine):
        """Test percentage property calculation."""
        profile = SignalProfile(
            name="Pct Test",
            signal_type=SignalType.ANALOG,
            min_value=0.0,
            max_value=100.0,
            initial_value=50.0,
        )
        physics_engine.add_signal(profile)
        state = physics_engine.signals["Pct Test"]
        
        assert state.percentage == 50.0
        
        physics_engine.set_value("Pct Test", 25.0)
        assert physics_engine.signals["Pct Test"].percentage == 25.0

    def test_is_stable_property(self, physics_engine):
        """Test is_stable property."""
        profile = SignalProfile(
            name="Stable Test",
            signal_type=SignalType.ANALOG,
            min_value=0.0,
            max_value=100.0,
            initial_value=50.0,
        )
        physics_engine.add_signal(profile)
        
        # At midpoint, should be stable
        assert physics_engine.signals["Stable Test"].is_stable is True
        
        # At extreme, should be unstable
        physics_engine.set_value("Stable Test", 95.0)
        assert physics_engine.signals["Stable Test"].is_stable is False

    def test_remove_signal(self, physics_engine):
        """Test removing a signal."""
        profile = SignalProfile(
            name="To Remove",
            signal_type=SignalType.ANALOG,
            min_value=0.0,
            max_value=100.0,
            initial_value=50.0,
        )
        physics_engine.add_signal(profile)
        assert "To Remove" in physics_engine.signals
        
        physics_engine.remove_signal("To Remove")
        assert "To Remove" not in physics_engine.signals

    def test_run_continuous_callback(self, physics_engine):
        """Test run_continuous with callback."""
        profile = SignalProfile(
            name="Callback Test",
            signal_type=SignalType.ANALOG,
            min_value=0.0,
            max_value=100.0,
            initial_value=50.0,
        )
        physics_engine.add_signal(profile)
        
        callback_values = []
        
        def callback(values):
            callback_values.append(values["Callback Test"])
            if len(callback_values) >= 3:
                physics_engine.stop()
        
        physics_engine.run_continuous(interval=0.01, callback=callback, max_steps=3)
        
        assert len(callback_values) == 3

    def test_physics_features_disabled(self):
        """Test with all physics features disabled."""
        config = PhysicsConfig(
            seed=42,
            enable_noise=False,
            enable_drift=False,
            enable_cross_coupling=False,
        )
        engine = PhysicsEngine(config)
        
        profile = SignalProfile(
            name="No Physics",
            signal_type=SignalType.ANALOG,
            min_value=0.0,
            max_value=100.0,
            initial_value=50.0,
            noise_amplitude=5.0,
            drift_rate=1.0,
        )
        engine.add_signal(profile)
        
        # Step multiple times
        for _ in range(10):
            values = engine.step(1.0)
            # With all features disabled, value should stay at initial
            assert values["No Physics"] == 50.0

    def test_water_tank_profiles_count(self, water_tank_signals):
        """Test that water tank profiles have expected count."""
        assert len(water_tank_signals) == 8

    def test_hvac_profiles_count(self, hvac_signals):
        """Test that HVAC profiles have expected count."""
        assert len(hvac_signals) == 6

    def test_power_grid_profiles_count(self, power_signals):
        """Test that power grid profiles have expected count."""
        assert len(power_signals) == 6

    def test_cross_coupling_effect(self, physics_engine):
        """Test that cross-coupling affects related signals."""
        profile1 = SignalProfile(
            name="Signal A",
            signal_type=SignalType.ANALOG,
            min_value=0.0,
            max_value=100.0,
            initial_value=50.0,
            noise_amplitude=0.0,
            drift_amplitude=0.0,
            coupling_factors={"Signal B": 1.0},
        )
        profile2 = SignalProfile(
            name="Signal B",
            signal_type=SignalType.ANALOG,
            min_value=0.0,
            max_value=100.0,
            initial_value=80.0,  # Different from initial
            noise_amplitude=0.0,
            drift_amplitude=0.0,
        )
        physics_engine.add_signal(profile1)
        physics_engine.add_signal(profile2)
        
        # Step and check coupling effect
        values = physics_engine.step(1.0)
        # Signal A should be affected by Signal B's deviation from initial
        assert values["Signal A"] != 50.0  # Should change due to coupling