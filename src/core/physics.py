"""
Physics Engine for Industrial Communication Simulator.

Simulates realistic industrial process values with:
- Gaussian noise for sensor inaccuracies
- Drift over time (e.g., thermal drift, calibration drift)
- Cross-coupling between related physical quantities
- Configurable min/max bounds
- Time-series evolution
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple


class SignalType(Enum):
    """Types of physical signals that can be simulated."""

    ANALOG = "analog"  # Continuous value (e.g., temperature, pressure)
    DISCRETE = "discrete"  # On/off or state value (e.g., valve open/closed)
    COUNTER = "counter"  # Monotonically increasing (e.g., total flow)
    BINARY = "binary"  # 0 or 1 (e.g., alarm status)


class UnitCategory(Enum):
    """Categories of engineering units."""

    TEMPERATURE = "temperature"
    PRESSURE = "pressure"
    LEVEL = "level"
    FLOW = "flow"
    VOLTAGE = "voltage"
    CURRENT = "current"
    POWER = "power"
    SPEED = "speed"
    POSITION = "position"
    COUNT = "count"
    PERCENT = "percent"
    DIMENSIONLESS = "dimensionless"
    OTHER = "other"


@dataclass
class PhysicsConfig:
    """Configuration for the physics simulation engine."""

    update_interval: float = 1.0  # seconds between updates
    enable_noise: bool = True
    enable_drift: bool = True
    enable_cross_coupling: bool = True
    seed: Optional[int] = None

    def __post_init__(self):
        if self.seed is not None:
            random.seed(self.seed)


@dataclass
class SignalProfile:
    """
    Defines the behavior profile of a simulated physical signal.

    Attributes:
        name: Human-readable signal name (e.g., "Tank Level")
        signal_type: Type of signal (analog, discrete, counter, binary)
        unit: Engineering unit string (e.g., "m", "degC", "bar", "L/min")
        unit_category: Category of the unit for cross-coupling
        min_value: Minimum allowed value (clamped)
        max_value: Maximum allowed value (clamped)
        initial_value: Starting value
        noise_amplitude: Standard deviation of Gaussian noise
        drift_rate: Value change per second (positive or negative)
        drift_amplitude: Maximum random drift per update
        coupling_factors: Dict mapping other signal names to coupling coefficients
        trend: Optional function that returns the base value at time t
    """

    name: str
    signal_type: SignalType = SignalType.ANALOG
    unit: str = ""
    unit_category: UnitCategory = UnitCategory.DIMENSIONLESS
    min_value: float = 0.0
    max_value: float = 100.0
    initial_value: float = 50.0
    noise_amplitude: float = 0.5
    drift_rate: float = 0.0
    drift_amplitude: float = 0.1
    coupling_factors: Dict[str, float] = field(default_factory=dict)
    trend: Optional[Callable[[float], float]] = None

    def __post_init__(self):
        # Clamp initial value
        self.initial_value = max(self.min_value, min(self.max_value, self.initial_value))


@dataclass
class SignalState:
    """Runtime state of a simulated signal."""

    profile: SignalProfile
    current_value: float
    previous_value: float
    timestamp: float
    noise_component: float = 0.0
    drift_component: float = 0.0
    coupling_component: float = 0.0

    @property
    def raw_value(self) -> float:
        """The value without noise (useful for cross-coupling)."""
        return self.current_value - self.noise_component

    @property
    def is_stable(self) -> bool:
        """Check if the signal is within normal operating range."""
        mid = (self.profile.min_value + self.profile.max_value) / 2
        range_span = self.profile.max_value - self.profile.min_value
        return abs(self.current_value - mid) < range_span * 0.4

    @property
    def percentage(self) -> float:
        """Value as percentage of range."""
        span = self.profile.max_value - self.profile.min_value
        if span == 0:
            return 100.0
        return ((self.current_value - self.profile.min_value) / span) * 100.0


class PhysicsEngine:
    """
    Core physics simulation engine.

    Manages a collection of signals and evolves them over time with
    realistic physical behavior including noise, drift, and cross-coupling.
    """

    def __init__(self, config: Optional[PhysicsConfig] = None):
        self.config = config or PhysicsConfig()
        self.signals: Dict[str, SignalState] = {}
        self._last_update: float = 0.0
        self._time: float = 0.0
        self._running: bool = False

    def add_signal(self, profile: SignalProfile) -> SignalState:
        """Register a new signal with the physics engine."""
        state = SignalState(
            profile=profile,
            current_value=profile.initial_value,
            previous_value=profile.initial_value,
            timestamp=time.time(),
        )
        self.signals[profile.name] = state
        return state

    def add_signals(self, profiles: List[SignalProfile]) -> List[SignalState]:
        """Register multiple signals at once."""
        return [self.add_signal(p) for p in profiles]

    def remove_signal(self, name: str) -> None:
        """Remove a signal from the engine."""
        self.signals.pop(name, None)

    def get_value(self, name: str) -> Optional[float]:
        """Get the current value of a signal."""
        state = self.signals.get(name)
        return state.current_value if state else None

    def get_state(self, name: str) -> Optional[SignalState]:
        """Get the full state object for a signal."""
        return self.signals.get(name)

    def set_value(self, name: str, value: float) -> None:
        """Manually set a signal value (clamped to bounds)."""
        state = self.signals.get(name)
        if state:
            state.previous_value = state.current_value
            state.current_value = max(
                state.profile.min_value,
                min(state.profile.max_value, value),
            )
            state.timestamp = time.time()

    def get_all_values(self) -> Dict[str, float]:
        """Get current values of all signals."""
        return {name: state.current_value for name, state in self.signals.items()}

    def get_all_states(self) -> Dict[str, SignalState]:
        """Get all signal states."""
        return dict(self.signals)

    def step(self, dt: Optional[float] = None) -> Dict[str, float]:
        """
        Advance the simulation by one time step.

        Args:
            dt: Time delta in seconds. If None, uses config.update_interval.

        Returns:
            Dict mapping signal names to their new values.
        """
        if dt is None:
            dt = self.config.update_interval

        self._time += dt
        now = time.time()

        # Collect raw values for cross-coupling
        raw_values = {name: state.raw_value for name, state in self.signals.items()}

        for name, state in self.signals.items():
            profile = state.profile
            state.previous_value = state.current_value

            # 1. Base value from trend function (if provided)
            if profile.trend:
                base = profile.trend(self._time)
            else:
                base = state.current_value

            # 2. Drift component
            drift = 0.0
            if self.config.enable_drift:
                drift = profile.drift_rate * dt
                drift += random.uniform(-profile.drift_amplitude, profile.drift_amplitude) * dt
            state.drift_component = drift

            # 3. Cross-coupling from other signals
            coupling = 0.0
            if self.config.enable_cross_coupling and profile.coupling_factors:
                for other_name, factor in profile.coupling_factors.items():
                    other_raw = raw_values.get(other_name, 0.0)
                    other_state = self.signals.get(other_name)
                    if other_state:
                        # Coupling is proportional to deviation from initial
                        deviation = other_raw - other_state.profile.initial_value
                        coupling += factor * deviation * dt
            state.coupling_component = coupling

            # 4. Noise component
            noise = 0.0
            if self.config.enable_noise:
                noise = random.gauss(0, profile.noise_amplitude)
            state.noise_component = noise

            # 5. Combine all components
            new_value = base + drift + coupling + noise

            # 6. Clamp to bounds
            new_value = max(profile.min_value, min(profile.max_value, new_value))

            # Handle discrete/binary types
            if profile.signal_type == SignalType.BINARY:
                new_value = round(new_value)
                new_value = 0.0 if new_value < 0.5 else 1.0
            elif profile.signal_type == SignalType.DISCRETE:
                new_value = round(new_value)
            elif profile.signal_type == SignalType.COUNTER:
                # Counters only increase
                new_value = max(state.current_value, new_value)

            state.current_value = new_value
            state.timestamp = now

        self._last_update = now
        return self.get_all_values()

    def run_continuous(
        self,
        interval: Optional[float] = None,
        callback: Optional[Callable[[Dict[str, float]], None]] = None,
        max_steps: Optional[int] = None,
    ) -> None:
        """
        Run the physics simulation continuously.

        Args:
            interval: Update interval in seconds. Defaults to config.update_interval.
            callback: Called with values dict after each step.
            max_steps: Maximum number of steps (None = infinite).
        """
        import time as _time

        interval = interval or self.config.update_interval
        self._running = True
        steps = 0

        try:
            while self._running:
                if max_steps is not None and steps >= max_steps:
                    break

                values = self.step(interval)
                if callback:
                    callback(values)

                steps += 1
                _time.sleep(interval)
        except KeyboardInterrupt:
            pass
        finally:
            self._running = False

    def stop(self) -> None:
        """Stop continuous simulation."""
        self._running = False

    def reset(self) -> None:
        """Reset all signals to their initial values."""
        for state in self.signals.values():
            state.current_value = state.profile.initial_value
            state.previous_value = state.profile.initial_value
            state.noise_component = 0.0
            state.drift_component = 0.0
            state.coupling_component = 0.0
            state.timestamp = time.time()
        self._time = 0.0

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def elapsed_time(self) -> float:
        return self._time


# =============================================================================
# Predefined signal profiles for common industrial scenarios
# =============================================================================

def water_tank_profiles() -> List[SignalProfile]:
    """Create signal profiles for a water tank simulation."""
    return [
        SignalProfile(
            name="Tank Level",
            signal_type=SignalType.ANALOG,
            unit="m",
            unit_category=UnitCategory.LEVEL,
            min_value=0.0,
            max_value=10.0,
            initial_value=5.0,
            noise_amplitude=0.05,
            drift_amplitude=0.02,
            drift_rate=-0.01,  # Slow leak
        ),
        SignalProfile(
            name="Water Temperature",
            signal_type=SignalType.ANALOG,
            unit="degC",
            unit_category=UnitCategory.TEMPERATURE,
            min_value=5.0,
            max_value=95.0,
            initial_value=25.0,
            noise_amplitude=0.3,
            drift_amplitude=0.05,
            drift_rate=0.005,  # Slight warming
            coupling_factors={"Tank Level": -0.5},  # Lower level = faster temp change
        ),
        SignalProfile(
            name="Inlet Flow",
            signal_type=SignalType.ANALOG,
            unit="L/min",
            unit_category=UnitCategory.FLOW,
            min_value=0.0,
            max_value=100.0,
            initial_value=30.0,
            noise_amplitude=1.0,
            drift_amplitude=0.5,
        ),
        SignalProfile(
            name="Outlet Flow",
            signal_type=SignalType.ANALOG,
            unit="L/min",
            unit_category=UnitCategory.FLOW,
            min_value=0.0,
            max_value=100.0,
            initial_value=30.0,
            noise_amplitude=1.0,
            drift_amplitude=0.5,
            coupling_factors={"Tank Level": 2.0},  # Higher level = more outlet pressure
        ),
        SignalProfile(
            name="Pressure",
            signal_type=SignalType.ANALOG,
            unit="bar",
            unit_category=UnitCategory.PRESSURE,
            min_value=0.0,
            max_value=10.0,
            initial_value=3.5,
            noise_amplitude=0.1,
            drift_amplitude=0.03,
            coupling_factors={"Tank Level": 0.8, "Inlet Flow": 0.3},
        ),
        SignalProfile(
            name="Valve Position",
            signal_type=SignalType.DISCRETE,
            unit="%",
            unit_category=UnitCategory.PERCENT,
            min_value=0.0,
            max_value=100.0,
            initial_value=50.0,
            noise_amplitude=0.0,
            drift_amplitude=0.0,
        ),
        SignalProfile(
            name="High Level Alarm",
            signal_type=SignalType.BINARY,
            unit="",
            unit_category=UnitCategory.DIMENSIONLESS,
            min_value=0.0,
            max_value=1.0,
            initial_value=0.0,
            noise_amplitude=0.0,
            drift_amplitude=0.0,
            coupling_factors={"Tank Level": 0.0},  # Handled externally
        ),
        SignalProfile(
            name="Total Flow Counter",
            signal_type=SignalType.COUNTER,
            unit="L",
            unit_category=UnitCategory.COUNT,
            min_value=0.0,
            max_value=1_000_000.0,
            initial_value=0.0,
            noise_amplitude=0.0,
            drift_amplitude=0.0,
        ),
    ]


def hvac_profiles() -> List[SignalProfile]:
    """Create signal profiles for an HVAC system simulation."""
    return [
        SignalProfile(
            name="Room Temperature",
            signal_type=SignalType.ANALOG,
            unit="degC",
            unit_category=UnitCategory.TEMPERATURE,
            min_value=10.0,
            max_value=40.0,
            initial_value=22.0,
            noise_amplitude=0.2,
            drift_amplitude=0.1,
        ),
        SignalProfile(
            name="Supply Air Temp",
            signal_type=SignalType.ANALOG,
            unit="degC",
            unit_category=UnitCategory.TEMPERATURE,
            min_value=5.0,
            max_value=30.0,
            initial_value=14.0,
            noise_amplitude=0.3,
            drift_amplitude=0.1,
            coupling_factors={"Room Temperature": 0.2},
        ),
        SignalProfile(
            name="Return Air Temp",
            signal_type=SignalType.ANALOG,
            unit="degC",
            unit_category=UnitCategory.TEMPERATURE,
            min_value=10.0,
            max_value=40.0,
            initial_value=24.0,
            noise_amplitude=0.2,
            drift_amplitude=0.1,
            coupling_factors={"Room Temperature": 0.9},
        ),
        SignalProfile(
            name="Humidity",
            signal_type=SignalType.ANALOG,
            unit="%RH",
            unit_category=UnitCategory.PERCENT,
            min_value=0.0,
            max_value=100.0,
            initial_value=45.0,
            noise_amplitude=1.0,
            drift_amplitude=0.5,
            coupling_factors={"Room Temperature": -0.3},
        ),
        SignalProfile(
            name="Fan Speed",
            signal_type=SignalType.DISCRETE,
            unit="RPM",
            unit_category=UnitCategory.SPEED,
            min_value=0.0,
            max_value=3000.0,
            initial_value=1200.0,
            noise_amplitude=10.0,
            drift_amplitude=5.0,
        ),
        SignalProfile(
            name="Compressor Status",
            signal_type=SignalType.BINARY,
            unit="",
            unit_category=UnitCategory.DIMENSIONLESS,
            min_value=0.0,
            max_value=1.0,
            initial_value=1.0,
            noise_amplitude=0.0,
            drift_amplitude=0.0,
        ),
    ]


def power_grid_profiles() -> List[SignalProfile]:
    """Create signal profiles for a power grid/motor simulation."""
    return [
        SignalProfile(
            name="Voltage L1-N",
            signal_type=SignalType.ANALOG,
            unit="V",
            unit_category=UnitCategory.VOLTAGE,
            min_value=200.0,
            max_value=260.0,
            initial_value=230.0,
            noise_amplitude=1.0,
            drift_amplitude=0.5,
        ),
        SignalProfile(
            name="Current L1",
            signal_type=SignalType.ANALOG,
            unit="A",
            unit_category=UnitCategory.CURRENT,
            min_value=0.0,
            max_value=100.0,
            initial_value=15.0,
            noise_amplitude=0.5,
            drift_amplitude=0.2,
            coupling_factors={"Motor Speed": 0.5},
        ),
        SignalProfile(
            name="Power Factor",
            signal_type=SignalType.ANALOG,
            unit="",
            unit_category=UnitCategory.DIMENSIONLESS,
            min_value=0.0,
            max_value=1.0,
            initial_value=0.92,
            noise_amplitude=0.01,
            drift_amplitude=0.005,
        ),
        SignalProfile(
            name="Motor Speed",
            signal_type=SignalType.ANALOG,
            unit="RPM",
            unit_category=UnitCategory.SPEED,
            min_value=0.0,
            max_value=1800.0,
            initial_value=1450.0,
            noise_amplitude=5.0,
            drift_amplitude=2.0,
        ),
        SignalProfile(
            name="Motor Temperature",
            signal_type=SignalType.ANALOG,
            unit="degC",
            unit_category=UnitCategory.TEMPERATURE,
            min_value=20.0,
            max_value=120.0,
            initial_value=45.0,
            noise_amplitude=0.5,
            drift_amplitude=0.3,
            coupling_factors={"Motor Speed": 0.02, "Current L1": 0.5},
        ),
        SignalProfile(
            name="Breaker Status",
            signal_type=SignalType.BINARY,
            unit="",
            unit_category=UnitCategory.DIMENSIONLESS,
            min_value=0.0,
            max_value=1.0,
            initial_value=1.0,
            noise_amplitude=0.0,
            drift_amplitude=0.0,
        ),
    ]