"""Tests for Device, DeviceCluster, and SimulationManager."""
from __future__ import annotations

import pytest

from src.core.device import (
    ClusterConfig,
    Device,
    DeviceCluster,
    DeviceConfig,
    DeviceRole,
    DeviceCluster,
    SimulationManager,
)
from src.core.physics import SignalProfile, SignalState, SignalType, UnitCategory, water_tank_profiles


class TestDevice:
    """Test suite for Device class."""

    def test_device_creation(self, sample_device):
        """Test device is created with correct properties."""
        assert sample_device.device_id == "test-tank"
        assert sample_device.name == "Test Tank"
        assert sample_device.role == DeviceRole.TANK
        assert sample_device.protocol == "modbus"

    def test_device_signals_count(self, sample_device):
        """Test device has expected number of signals."""
        assert len(sample_device.signals) == 8  # water_tank_profiles has 8 signals

    def test_get_value(self, sample_device):
        """Test getting signal value by name."""
        value = sample_device.get_value("Tank Level")
        assert value is not None
        assert 0.0 <= value <= 10.0  # Within bounds

    def test_get_signal(self, sample_device):
        """Test getting full signal state."""
        signal = sample_device.get_signal("Tank Level")
        assert signal is not None
        assert isinstance(signal, SignalState)
        assert signal.profile.name == "Tank Level"

    def test_get_all_values(self, sample_device):
        """Test getting all signal values."""
        values = sample_device.get_all_values()
        assert len(values) == 8
        for name, value in values.items():
            assert value is not None

    def test_set_value(self, sample_device):
        """Test setting signal value."""
        sample_device.set_value("Tank Level", 7.5)
        assert sample_device.get_value("Tank Level") == 7.5

    def test_set_value_clamping(self, sample_device):
        """Test that set_value clamps to bounds."""
        # Tank Level has bounds 0-10
        sample_device.set_value("Tank Level", 15.0)
        assert sample_device.get_value("Tank Level") == 10.0
        
        sample_device.set_value("Tank Level", -5.0)
        assert sample_device.get_value("Tank Level") == 0.0

    def test_device_step(self, sample_device):
        """Test device step() advances simulation."""
        initial = sample_device.get_value("Tank Level")
        sample_device.step(1.0)
        new_value = sample_device.get_value("Tank Level")
        # Value should change (or stay same due to randomness)
        assert new_value is not None

    def test_device_to_dict(self, sample_device):
        """Test device serialization."""
        data = sample_device.to_dict()
        assert data["device_id"] == "test-tank"
        assert data["name"] == "Test Tank"
        assert data["role"] == "tank"
        assert data["protocol"] == "modbus"
        assert "signals" in data
        assert len(data["signals"]) == 8


class TestDeviceCluster:
    """Test suite for DeviceCluster class."""

    def test_cluster_creation(self, sample_cluster):
        """Test cluster is created with correct properties."""
        assert sample_cluster.cluster_id == "test-cluster"
        assert sample_cluster.name == "Test Cluster"
        assert len(sample_cluster.devices) == 1

    def test_cluster_get_device(self, sample_cluster):
        """Test getting device by ID."""
        device = sample_cluster.get_device("test-tank")
        assert device is not None
        assert device.device_id == "test-tank"

    def test_cluster_get_device_not_found(self, sample_cluster):
        """Test getting non-existent device returns None."""
        device = sample_cluster.get_device("nonexistent")
        assert device is None

    def test_cluster_get_devices_by_protocol(self, sample_cluster):
        """Test filtering devices by protocol."""
        devices = sample_cluster.get_devices_by_protocol("modbus")
        assert len(devices) == 1
        assert devices[0].protocol == "modbus"

    def test_cluster_get_devices_by_role(self, sample_cluster):
        """Test filtering devices by role."""
        devices = sample_cluster.get_devices_by_role(DeviceRole.TANK)
        assert len(devices) == 1
        assert devices[0].role == DeviceRole.TANK

    def test_cluster_add_device(self, sample_cluster):
        """Test adding a device to cluster."""
        from src.core.physics import SignalProfile, SignalType
        
        new_config = DeviceConfig(
            device_id="new-device",
            name="New Device",
            role=DeviceRole.SENSOR,
            protocol="bacnet",
            signal_profiles=[
                SignalProfile(
                    name="Temperature",
                    signal_type=SignalType.ANALOG,
                    unit="degC",
                    min_value=0.0,
                    max_value=100.0,
                    initial_value=25.0,
                )
            ],
        )
        
        device = sample_cluster.add_device(new_config)
        assert device.device_id == "new-device"
        assert len(sample_cluster.devices) == 2

    def test_cluster_remove_device(self, sample_cluster):
        """Test removing a device from cluster."""
        sample_cluster.remove_device("test-tank")
        assert len(sample_cluster.devices) == 0
        assert sample_cluster.get_device("test-tank") is None

    def test_cluster_step(self, sample_cluster):
        """Test cluster step() returns values for all devices."""
        result = sample_cluster.step(1.0)
        assert len(result) == 1
        assert "test-tank" in result
        assert len(result["test-tank"]) == 8

    def test_cluster_get_all_values(self, sample_cluster):
        """Test cluster get_all_values()."""
        values = sample_cluster.get_all_values()
        assert len(values) == 1
        assert "test-tank" in values

    def test_cluster_to_dict(self, sample_cluster):
        """Test cluster serialization."""
        data = sample_cluster.to_dict()
        assert data["cluster_id"] == "test-cluster"
        assert data["name"] == "Test Cluster"
        assert "devices" in data
        assert len(data["devices"]) == 1


class TestSimulationManager:
    """Test suite for SimulationManager class."""

    def test_add_cluster(self, simulation_manager):
        """Test adding a cluster."""
        assert len(simulation_manager.clusters) == 1
        assert "test-cluster" in simulation_manager.clusters

    def test_remove_cluster(self, simulation_manager):
        """Test removing a cluster."""
        simulation_manager.remove_cluster("test-cluster")
        assert len(simulation_manager.clusters) == 0

    def test_get_cluster(self, simulation_manager):
        """Test getting cluster by ID."""
        cluster = simulation_manager.get_cluster("test-cluster")
        assert cluster is not None
        assert cluster.cluster_id == "test-cluster"

    def test_get_device(self, simulation_manager):
        """Test getting device across clusters."""
        device = simulation_manager.get_device("test-tank")
        assert device is not None
        assert device.device_id == "test-tank"

    def test_get_device_not_found(self, simulation_manager):
        """Test getting non-existent device returns None."""
        device = simulation_manager.get_device("nonexistent")
        assert device is None

    def test_get_devices_by_protocol(self, simulation_manager):
        """Test getting devices by protocol across all clusters."""
        devices = simulation_manager.get_devices_by_protocol("modbus")
        assert len(devices) == 1
        assert devices[0].protocol == "modbus"

    def test_step(self, simulation_manager):
        """Test simulation step()."""
        result = simulation_manager.step(1.0)
        assert len(result) == 1
        assert "test-cluster" in result

    def test_register_update_callback(self, simulation_manager):
        """Test registering update callback."""
        callback_called = []
        
        def callback(data):
            callback_called.append(True)
        
        simulation_manager.register_update_callback(callback)
        simulation_manager.step(1.0)
        
        assert len(callback_called) == 1

    def test_to_dict(self, simulation_manager):
        """Test simulation serialization."""
        data = simulation_manager.to_dict()
        assert "clusters" in data
        assert len(data["clusters"]) == 1

    def test_multiple_clusters(self):
        """Test simulation with multiple clusters."""
        sim = SimulationManager()
        
        # Add first cluster
        config1 = ClusterConfig(
            cluster_id="cluster-1",
            name="Cluster 1",
            devices=[],
        )
        sim.add_cluster(config1)
        
        # Add second cluster
        config2 = ClusterConfig(
            cluster_id="cluster-2",
            name="Cluster 2",
            devices=[],
        )
        sim.add_cluster(config2)
        
        assert len(sim.clusters) == 2
        assert sim.get_cluster("cluster-1") is not None
        assert sim.get_cluster("cluster-2") is not None
