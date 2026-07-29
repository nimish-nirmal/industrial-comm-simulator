#!/usr/bin/env python3
"""Test script to verify the PhysicsConfig import fix."""

import sys
sys.path.insert(0, 'src')

from core.device import SimulationManager, ClusterConfig, DeviceConfig, DeviceRole

def test_simulation_manager_basic():
    """Test basic SimulationManager instantiation."""
    sim = SimulationManager()
    assert sim.physics_config is not None
    print("✓ SimulationManager instantiation works")

def test_simulation_manager_with_config():
    """Test SimulationManager with custom config."""
    from src.core.physics import PhysicsConfig
    config = PhysicsConfig(update_interval=2.0, enable_noise=False)
    sim = SimulationManager(physics_config=config)
    assert sim.physics_config.update_interval == 2.0
    assert sim.physics_config.enable_noise is False
    print("✓ SimulationManager with custom config works")

def test_add_cluster():
    """Test adding a cluster to simulation manager."""
    sim = SimulationManager()
    cluster_config = ClusterConfig(
        cluster_id="test-cluster",
        name="Test Cluster",
        devices=[
            DeviceConfig(
                device_id="dev1",
                name="Test Device 1",
                role=DeviceRole.SENSOR
            )
        ]
    )
    cluster = sim.add_cluster(cluster_config)
    assert cluster is not None
    assert cluster.cluster_id == "test-cluster"
    print("✓ Adding cluster works")

def test_get_cluster():
    """Test getting a cluster from simulation manager."""
    sim = SimulationManager()
    cluster_config = ClusterConfig(
        cluster_id="test-cluster",
        name="Test Cluster"
    )
    sim.add_cluster(cluster_config)
    
    cluster = sim.get_cluster("test-cluster")
    assert cluster is not None
    assert cluster.name == "Test Cluster"
    
    missing_cluster = sim.get_cluster("nonexistent")
    assert missing_cluster is None
    print("✓ Getting cluster works")

def test_remove_cluster():
    """Test removing a cluster from simulation manager."""
    sim = SimulationManager()
    cluster_config = ClusterConfig(
        cluster_id="test-cluster",
        name="Test Cluster"
    )
    sim.add_cluster(cluster_config)
    assert sim.get_cluster("test-cluster") is not None
    
    sim.remove_cluster("test-cluster")
    assert sim.get_cluster("test-cluster") is None
    print("✓ Removing cluster works")

def test_get_device():
    """Test getting a device across clusters."""
    sim = SimulationManager()
    cluster_config = ClusterConfig(
        cluster_id="test-cluster",
        name="Test Cluster",
        devices=[
            DeviceConfig(
                device_id="dev1",
                name="Device 1",
                role=DeviceRole.SENSOR
            )
        ]
    )
    sim.add_cluster(cluster_config)
    
    device = sim.get_device("dev1")
    assert device is not None
    assert device.device_id == "dev1"
    assert device.name == "Device 1"
    
    missing_device = sim.get_device("nonexistent")
    assert missing_device is None
    print("✓ Getting device works")

def test_get_devices_by_protocol():
    """Test getting devices by protocol."""
    sim = SimulationManager()
    cluster_config = ClusterConfig(
        cluster_id="test-cluster",
        name="Test Cluster",
        devices=[
            DeviceConfig(
                device_id="dev1",
                name="Device 1",
                role=DeviceRole.SENSOR,
                protocol="modbus"
            ),
            DeviceConfig(
                device_id="dev2",
                name="Device 2",
                role=DeviceRole.ACTUATOR,
                protocol="bacnet"
            )
        ]
    )
    sim.add_cluster(cluster_config)
    
    modbus_devices = sim.get_devices_by_protocol("modbus")
    assert len(modbus_devices) == 1
    assert modbus_devices[0].device_id == "dev1"
    
    bacnet_devices = sim.get_devices_by_protocol("bacnet")
    assert len(bacnet_devices) == 1
    assert bacnet_devices[0].device_id == "dev2"
    
    unknown_devices = sim.get_devices_by_protocol("unknown")
    assert len(unknown_devices) == 0
    print("✓ Getting devices by protocol works")

def test_step():
    """Test simulation step."""
    sim = SimulationManager()
    cluster_config = ClusterConfig(
        cluster_id="test-cluster",
        name="Test Cluster",
        devices=[
            DeviceConfig(
                device_id="dev1",
                name="Device 1",
                role=DeviceRole.SENSOR,
                signal_profiles=[]
            )
        ]
    )
    sim.add_cluster(cluster_config)
    
    result = sim.step(1.0)
    assert "test-cluster" in result
    print("✓ Simulation step works")

def test_register_callback():
    """Test registering update callbacks."""
    sim = SimulationManager()
    callback_called = []
    
    def callback(data):
        callback_called.append(True)
    
    sim.register_update_callback(callback)
    sim.step(1.0)
    
    assert len(callback_called) == 1
    print("✓ Registering callback works")

def test_to_dict():
    """Test serialization to dict."""
    sim = SimulationManager()
    cluster_config = ClusterConfig(
        cluster_id="test-cluster",
        name="Test Cluster"
    )
    sim.add_cluster(cluster_config)
    
    result = sim.to_dict()
    assert "clusters" in result
    assert "test-cluster" in result["clusters"]
    assert "running" in result
    print("✓ Serialization to dict works")

if __name__ == "__main__":
    print("Running PhysicsConfig import fix verification tests...\n")
    
    try:
        test_simulation_manager_basic()
        test_simulation_manager_with_config()
        test_add_cluster()
        test_get_cluster()
        test_remove_cluster()
        test_get_device()
        test_get_devices_by_protocol()
        test_step()
        test_register_callback()
        test_to_dict()
        
        print("\n✅ All tests passed! The PhysicsConfig import fix is working correctly.")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)