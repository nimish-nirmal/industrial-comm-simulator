"""
Device and Cluster Models for Industrial Communication Simulator.

Represents industrial devices (sensors, actuators, controllers) and
clusters (groups of related devices) with physics-backed signal values.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from src.core.physics import (
    PhysicsEngine,
    PhysicsConfig,
    SignalProfile,
    SignalState,
    SignalType,
    UnitCategory,
)

logger = logging.getLogger(__name__)


class DeviceRole(Enum):
    """Role of a device in the industrial process."""

    SENSOR = "sensor"
    ACTUATOR = "actuator"
    CONTROLLER = "controller"
    PUMP = "pump"
    VALVE = "valve"
    MOTOR = "motor"
    TANK = "tank"
    COMPRESSOR = "compressor"
    CONVEYOR = "conveyor"
    GENERIC = "generic"


@dataclass
class DeviceConfig:
    """Configuration for a simulated device."""

    device_id: str
    name: str
    role: DeviceRole = DeviceRole.GENERIC
    protocol: str = "modbus"  # Primary protocol for this device
    description: str = ""
    tags: Dict[str, str] = field(default_factory=dict)
    signal_profiles: List[SignalProfile] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class Device:
    """
    Represents a simulated industrial device with physics-backed signals.

    Each device has a collection of signals (e.g., temperature, pressure,
    valve position) that evolve realistically over time.
    """

    def __init__(self, config: DeviceConfig, physics: Optional[PhysicsEngine] = None):
        self.config = config
        self.physics = physics or PhysicsEngine()
        self.signals: Dict[str, SignalState] = {}
        self._initialized: bool = False
        self._last_update: float = 0.0

        # Register signal profiles
        for profile in config.signal_profiles:
            state = self.physics.add_signal(profile)
            self.signals[profile.name] = state

        self._initialized = True
        logger.debug(f"Device '{config.name}' ({config.device_id}) initialized with {len(self.signals)} signals")

    @property
    def device_id(self) -> str:
        return self.config.device_id

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def protocol(self) -> str:
        return self.config.protocol

    @property
    def role(self) -> DeviceRole:
        return self.config.role

    def get_signal(self, name: str) -> Optional[SignalState]:
        """Get a signal state by name."""
        return self.signals.get(name)

    def get_value(self, name: str) -> Optional[float]:
        """Get current value of a signal."""
        state = self.signals.get(name)
        return state.current_value if state else None

    def set_value(self, name: str, value: float) -> None:
        """Set a signal value (e.g., actuator command)."""
        self.physics.set_value(name, value)

    def get_all_values(self) -> Dict[str, float]:
        """Get all signal values for this device."""
        return {
            name: state.current_value
            for name, state in self.signals.items()
        }

    def get_all_states(self) -> Dict[str, SignalState]:
        """Get all signal states."""
        return dict(self.signals)

    def step(self, dt: Optional[float] = None) -> Dict[str, float]:
        """Advance device simulation by one time step."""
        values = self.physics.step(dt)
        self._last_update = time.time()
        return {name: values[name] for name in self.signals if name in values}

    def to_dict(self) -> Dict[str, Any]:
        """Serialize device state to dictionary."""
        return {
            "device_id": self.device_id,
            "name": self.name,
            "role": self.role.value,
            "protocol": self.protocol,
            "description": self.config.description,
            "tags": self.config.tags,
            "signals": {
                name: {
                    "value": state.current_value,
                    "unit": state.profile.unit,
                    "type": state.profile.signal_type.value,
                    "min": state.profile.min_value,
                    "max": state.profile.max_value,
                    "percentage": state.percentage,
                    "stable": state.is_stable,
                    "timestamp": state.timestamp,
                }
                for name, state in self.signals.items()
            },
        }

    def __repr__(self) -> str:
        return f"Device(id={self.device_id}, name={self.name}, protocol={self.protocol})"


@dataclass
class ClusterConfig:
    """Configuration for a device cluster."""

    cluster_id: str
    name: str
    description: str = ""
    devices: List[DeviceConfig] = field(default_factory=list)
    tags: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class DeviceCluster:
    """
    Represents a group of related devices that form a functional unit.

    Clusters can represent physical areas (e.g., "Boiler Room"),
    process units (e.g., "Cooling System"), or logical groupings.
    """

    def __init__(self, config: ClusterConfig):
        self.config = config
        self.devices: Dict[str, Device] = {}
        self.physics = PhysicsEngine()
        self._initialized: bool = False

        for dev_config in config.devices:
            device = Device(config=dev_config, physics=self.physics)
            self.devices[dev_config.device_id] = device

        self._initialized = True
        logger.info(
            f"Cluster '{config.name}' ({config.cluster_id}) initialized with {len(self.devices)} devices"
        )

    @property
    def cluster_id(self) -> str:
        return self.config.cluster_id

    @property
    def name(self) -> str:
        return self.config.name

    def add_device(self, device_config: DeviceConfig) -> Device:
        """Add a new device to the cluster."""
        device = Device(config=device_config, physics=self.physics)
        self.devices[device_config.device_id] = device
        logger.info(f"Added device '{device.name}' to cluster '{self.name}'")
        return device

    def remove_device(self, device_id: str) -> None:
        """Remove a device from the cluster."""
        device = self.devices.pop(device_id, None)
        if device:
            for signal_name in device.signals:
                self.physics.remove_signal(signal_name)
            logger.info(f"Removed device '{device_id}' from cluster '{self.name}'")

    def get_device(self, device_id: str) -> Optional[Device]:
        """Get a device by ID."""
        return self.devices.get(device_id)

    def get_devices_by_protocol(self, protocol: str) -> List[Device]:
        """Get all devices using a specific protocol."""
        return [d for d in self.devices.values() if d.protocol == protocol]

    def get_devices_by_role(self, role: DeviceRole) -> List[Device]:
        """Get all devices with a specific role."""
        return [d for d in self.devices.values() if d.role == role]

    def step(self, dt: Optional[float] = None) -> Dict[str, Dict[str, float]]:
        """
        Advance all devices in the cluster by one time step.

        Returns:
            Dict mapping device_id -> {signal_name: value}
        """
        self.physics.step(dt)
        return {
            dev_id: device.get_all_values()
            for dev_id, device in self.devices.items()
        }

    def get_all_values(self) -> Dict[str, Dict[str, float]]:
        """Get all signal values for all devices."""
        return {
            dev_id: device.get_all_values()
            for dev_id, device in self.devices.items()
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize cluster state to dictionary."""
        return {
            "cluster_id": self.cluster_id,
            "name": self.name,
            "description": self.config.description,
            "tags": self.config.tags,
            "devices": {
                dev_id: device.to_dict()
                for dev_id, device in self.devices.items()
            },
        }

    def __repr__(self) -> str:
        return f"DeviceCluster(id={self.cluster_id}, name={self.name}, devices={len(self.devices)})"


class SimulationManager:
    """
    Top-level manager for the entire simulation.

    Manages multiple clusters, coordinates physics updates,
    and provides a unified interface for protocol engines.
    """

    def __init__(self, physics_config: Optional[PhysicsConfig] = None):
        self.clusters: Dict[str, DeviceCluster] = {}
        self.physics_config = physics_config or PhysicsConfig()
        self._running: bool = False
        self._update_callbacks: List[Callable[[Dict[str, Any]], None]] = []

    def add_cluster(self, config: ClusterConfig) -> DeviceCluster:
        """Add a new cluster to the simulation."""
        cluster = DeviceCluster(config=config)
        self.clusters[config.cluster_id] = cluster
        logger.info(f"Added cluster '{cluster.name}' to simulation")
        return cluster

    def remove_cluster(self, cluster_id: str) -> None:
        """Remove a cluster from the simulation."""
        self.clusters.pop(cluster_id, None)
        logger.info(f"Removed cluster '{cluster_id}' from simulation")

    def get_cluster(self, cluster_id: str) -> Optional[DeviceCluster]:
        """Get a cluster by ID."""
        return self.clusters.get(cluster_id)

    def get_device(self, device_id: str) -> Optional[Device]:
        """Find a device across all clusters."""
        for cluster in self.clusters.values():
            device = cluster.get_device(device_id)
            if device:
                return device
        return None

    def get_devices_by_protocol(self, protocol: str) -> List[Device]:
        """Get all devices using a specific protocol across all clusters."""
        devices = []
        for cluster in self.clusters.values():
            devices.extend(cluster.get_devices_by_protocol(protocol))
        return devices

    def register_update_callback(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Register a callback for physics updates."""
        self._update_callbacks.append(callback)

    def step(self, dt: Optional[float] = None) -> Dict[str, Any]:
        """Advance the entire simulation by one time step."""
        result = {}
        for cluster_id, cluster in self.clusters.items():
            result[cluster_id] = cluster.step(dt)

        for callback in self._update_callbacks:
            try:
                callback(result)
            except Exception as e:
                logger.error(f"Update callback error: {e}")

        return result

    def run(self, interval: Optional[float] = None) -> None:
        """Run the simulation continuously."""
        import time as _time

        interval = interval or self.physics_config.update_interval
        self._running = True
        logger.info(f"Simulation started (interval={interval}s)")

        try:
            while self._running:
                self.step(interval)
                _time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("Simulation stopped by user")
        finally:
            self._running = False

    def stop(self) -> None:
        """Stop the simulation."""
        self._running = False
        logger.info("Simulation stopping...")

    @property
    def is_running(self) -> bool:
        return self._running

    def to_dict(self) -> Dict[str, Any]:
        """Serialize full simulation state."""
        return {
            "clusters": {
                cid: cluster.to_dict()
                for cid, cluster in self.clusters.items()
            },
            "running": self._running,
        }
