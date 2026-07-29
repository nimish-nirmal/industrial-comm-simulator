"""Pytest configuration and shared fixtures for test suite."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def physics_config():
    """Provide a default PhysicsConfig for tests."""
    from src.core.physics import PhysicsConfig
    return PhysicsConfig(seed=42, update_interval=1.0)


@pytest.fixture
def physics_engine(physics_config):
    """Provide a fresh PhysicsEngine instance."""
    from src.core.physics import PhysicsEngine
    return PhysicsEngine(physics_config)


@pytest.fixture
def water_tank_signals():
    """Provide water tank signal profiles."""
    from src.core.physics import water_tank_profiles
    return water_tank_profiles()


@pytest.fixture
def hvac_signals():
    """Provide HVAC signal profiles."""
    from src.core.physics import hvac_profiles
    return hvac_profiles()


@pytest.fixture
def power_signals():
    """Provide power grid signal profiles."""
    from src.core.physics import power_grid_profiles
    return power_grid_profiles()


@pytest.fixture
def sample_device():
    """Provide a sample device with water tank signals."""
    from src.core.device import Device, DeviceConfig, DeviceRole
    from src.core.physics import water_tank_profiles

    config = DeviceConfig(
        device_id="test-tank",
        name="Test Tank",
        role=DeviceRole.TANK,
        protocol="modbus",
        signal_profiles=water_tank_profiles(),
    )
    return Device(config)


@pytest.fixture
def sample_cluster(sample_device):
    """Provide a sample cluster with one device."""
    from src.core.device import ClusterConfig, DeviceCluster

    config = ClusterConfig(
        cluster_id="test-cluster",
        name="Test Cluster",
        devices=[sample_device.config],
    )
    return DeviceCluster(config)


@pytest.fixture
def simulation_manager(sample_cluster):
    """Provide a simulation manager with one cluster."""
    from src.core.device import SimulationManager

    sim = SimulationManager()
    sim.add_cluster(sample_cluster.config)
    return sim
