"""
Workflow Manager for Industrial Communication Simulator.

Manages the lifecycle of the simulation including:
- Startup sequence (load config, create devices, start protocols)
- Runtime operations (monitoring, health checks, logging)
- Shutdown sequence (graceful stop, cleanup)
- Scenario management (load/save simulation scenarios)
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Thread
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.config.settings import Settings, load_settings
from src.core.device import (
    ClusterConfig,
    DeviceConfig,
    DeviceCluster,
    DeviceRole,
    SimulationManager,
)
from src.core.physics import (
    PhysicsConfig,
    PhysicsEngine,
    SignalProfile,
    SignalType,
    UnitCategory,
    water_tank_profiles,
    hvac_profiles,
    power_grid_profiles,
)
from src.protocols.base import ProtocolConfig, ProtocolEngine, ProtocolRegistry
from src.protocols.modbus import ModbusEngine
from src.protocols.bacnet import BacnetEngine
from src.protocols.mqtt import MqttEngine
from src.protocols.opcua import OpcUaEngine
from src.protocols.siemens import SiemensEngine
from src.protocols.http import HttpEngine
from src.protocols.sparkplug import SparkplugEngine
from src.protocols.dnp3 import Dnp3Engine
from src.protocols.ethernetip import EthernetIpEngine
from src.protocols.profinet import ProfinetEngine
from src.protocols.canopen import CanopenEngine
from src.protocols.iec61850 import Iec61850Engine
from src.protocols.iec104 import Iec104Engine
from src.protocols.websocket import WebSocketEngine
from src.protocols.grpc import GrpcEngine

logger = logging.getLogger(__name__)


@dataclass
class WorkflowConfig:
    """Configuration for the workflow manager."""

    auto_start: bool = True
    health_check_interval: float = 5.0
    log_interval: float = 10.0
    scenario_dir: str = "scenarios"
    enable_auto_recovery: bool = True


class WorkflowManager:
    """
    Manages the complete lifecycle of the industrial communication simulator.

    Handles:
    - Initialization and configuration loading
    - Device and cluster creation
    - Protocol engine registration and lifecycle
    - Health monitoring and auto-recovery
    - Graceful shutdown
    - Scenario save/load
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        workflow_config: Optional[WorkflowConfig] = None,
    ):
        self.settings = settings or load_settings()
        self.workflow_config = workflow_config or WorkflowConfig()
        self.simulation = SimulationManager()
        self.registry = ProtocolRegistry()
        self._running: bool = False
        self._health_thread: Optional[Thread] = None
        self._log_thread: Optional[Thread] = None
        self._start_time: float = 0.0

        # Setup logging
        self._setup_logging()

    def _setup_logging(self) -> None:
        """Configure logging based on settings."""
        logging.basicConfig(
            level=getattr(logging, self.settings.log_level.upper(), logging.INFO),
            format=self.settings.log_format,
        )

    def initialize(self) -> None:
        """
        Initialize the simulation with default clusters and devices.

        This is the main startup sequence:
        1. Create default clusters with physics-backed devices
        2. Register and start protocol engines
        3. Start health monitoring
        """
        logger.info(f"Initializing {self.settings.simulator_name} v{self.settings.simulator_version}")
        self._start_time = time.time()

        # Step 1: Create default clusters
        self._create_default_clusters()

        # Step 2: Register protocol engines
        self._register_protocols()

        # Step 3: Start protocol engines
        if self.workflow_config.auto_start:
            self.registry.start_all()

        # Step 4: Start monitoring
        self._start_monitoring()

        self._running = True
        logger.info("Simulation initialization complete")

    def _create_default_clusters(self) -> None:
        """Create default device clusters with physics-backed signals."""
        # --- Water Treatment Cluster ---
        water_tank_devices = [
            DeviceConfig(
                device_id="tank-01",
                name="Main Water Tank",
                role=DeviceRole.TANK,
                protocol="modbus",
                description="Primary water storage tank with level, temperature, and flow monitoring",
                signal_profiles=water_tank_profiles(),
            ),
            DeviceConfig(
                device_id="pump-01",
                name="Inlet Pump",
                role=DeviceRole.PUMP,
                protocol="modbus",
                description="Main inlet water pump",
                signal_profiles=[
                    SignalProfile(
                        name="Pump Speed",
                        signal_type=SignalType.ANALOG,
                        unit="RPM",
                        unit_category=UnitCategory.SPEED,
                        min_value=0.0,
                        max_value=3600.0,
                        initial_value=1500.0,
                        noise_amplitude=10.0,
                        drift_amplitude=5.0,
                    ),
                    SignalProfile(
                        name="Motor Current",
                        signal_type=SignalType.ANALOG,
                        unit="A",
                        unit_category=UnitCategory.CURRENT,
                        min_value=0.0,
                        max_value=50.0,
                        initial_value=12.5,
                        noise_amplitude=0.5,
                        drift_amplitude=0.2,
                        coupling_factors={"Pump Speed": 0.01},
                    ),
                    SignalProfile(
                        name="Pump Status",
                        signal_type=SignalType.BINARY,
                        unit="",
                        unit_category=UnitCategory.DIMENSIONLESS,
                        min_value=0.0,
                        max_value=1.0,
                        initial_value=1.0,
                        noise_amplitude=0.0,
                        drift_amplitude=0.0,
                    ),
                ],
            ),
        ]

        water_cluster = ClusterConfig(
            cluster_id="water-treatment",
            name="Water Treatment System",
            description="Water treatment plant with tank, pumps, and monitoring",
            devices=water_tank_devices,
            tags={"area": "treatment", "priority": "critical"},
        )
        self.simulation.add_cluster(water_cluster)

        # --- HVAC Cluster ---
        hvac_devices = [
            DeviceConfig(
                device_id="ahu-01",
                name="Air Handling Unit 1",
                role=DeviceRole.CONTROLLER,
                protocol="bacnet",
                description="Main air handling unit with temperature and humidity control",
                signal_profiles=hvac_profiles(),
            ),
            DeviceConfig(
                device_id="compressor-01",
                name="HVAC Compressor",
                role=DeviceRole.COMPRESSOR,
                protocol="bacnet",
                description="HVAC system compressor",
                signal_profiles=[
                    SignalProfile(
                        name="Compressor Speed",
                        signal_type=SignalType.ANALOG,
                        unit="RPM",
                        unit_category=UnitCategory.SPEED,
                        min_value=0.0,
                        max_value=3000.0,
                        initial_value=1800.0,
                        noise_amplitude=20.0,
                        drift_amplitude=10.0,
                    ),
                    SignalProfile(
                        name="Discharge Pressure",
                        signal_type=SignalType.ANALOG,
                        unit="bar",
                        unit_category=UnitCategory.PRESSURE,
                        min_value=0.0,
                        max_value=25.0,
                        initial_value=12.0,
                        noise_amplitude=0.3,
                        drift_amplitude=0.1,
                        coupling_factors={"Compressor Speed": 0.005},
                    ),
                    SignalProfile(
                        name="Suction Pressure",
                        signal_type=SignalType.ANALOG,
                        unit="bar",
                        unit_category=UnitCategory.PRESSURE,
                        min_value=0.0,
                        max_value=10.0,
                        initial_value=3.5,
                        noise_amplitude=0.2,
                        drift_amplitude=0.05,
                        coupling_factors={"Compressor Speed": -0.002},
                    ),
                ],
            ),
        ]

        hvac_cluster = ClusterConfig(
            cluster_id="hvac-system",
            name="HVAC System",
            description="Building HVAC system with AHU and compressor",
            devices=hvac_devices,
            tags={"area": "building-a", "floor": "all"},
        )
        self.simulation.add_cluster(hvac_cluster)

        # --- Power Distribution Cluster ---
        power_devices = [
            DeviceConfig(
                device_id="motor-01",
                name="Main Drive Motor",
                role=DeviceRole.MOTOR,
                protocol="siemens",
                description="Main industrial drive motor with power monitoring",
                signal_profiles=power_grid_profiles(),
            ),
            DeviceConfig(
                device_id="vfd-01",
                name="Variable Frequency Drive",
                role=DeviceRole.CONTROLLER,
                protocol="modbus",
                description="VFD controlling main motor speed",
                signal_profiles=[
                    SignalProfile(
                        name="Output Frequency",
                        signal_type=SignalType.ANALOG,
                        unit="Hz",
                        unit_category=UnitCategory.OTHER,
                        min_value=0.0,
                        max_value=60.0,
                        initial_value=45.0,
                        noise_amplitude=0.1,
                        drift_amplitude=0.05,
                    ),
                    SignalProfile(
                        name="DC Bus Voltage",
                        signal_type=SignalType.ANALOG,
                        unit="V",
                        unit_category=UnitCategory.VOLTAGE,
                        min_value=0.0,
                        max_value=800.0,
                        initial_value=540.0,
                        noise_amplitude=2.0,
                        drift_amplitude=1.0,
                    ),
                    SignalProfile(
                        name="Drive Temperature",
                        signal_type=SignalType.ANALOG,
                        unit="degC",
                        unit_category=UnitCategory.TEMPERATURE,
                        min_value=0.0,
                        max_value=85.0,
                        initial_value=35.0,
                        noise_amplitude=0.5,
                        drift_amplitude=0.2,
                        coupling_factors={"Output Frequency": 0.3},
                    ),
                ],
            ),
        ]

        power_cluster = ClusterConfig(
            cluster_id="power-distribution",
            name="Power Distribution",
            description="Motor control center with VFD and power monitoring",
            devices=power_devices,
            tags={"area": "electrical", "voltage": "480V"},
        )
        self.simulation.add_cluster(power_cluster)

        logger.info(
            f"Created {len(self.simulation.clusters)} clusters with "
            f"{sum(len(c.devices) for c in self.simulation.clusters.values())} devices"
        )

    def _register_protocols(self) -> None:
        """Register protocol engines based on settings."""
        protocol_map = {
            "modbus": (
                self.settings.is_protocol_active("modbus"),
                lambda: ModbusEngine(
                    simulation=self.simulation,
                    host=self.settings.modbus.tcp_host,
                    port=self.settings.modbus.tcp_port,
                    mode=self.settings.modbus.mode,
                    serial_port=self.settings.modbus.serial_port,
                    serial_baud=self.settings.modbus.serial_baud,
                    config=ProtocolConfig(
                        enabled=self.settings.modbus.enabled,
                        update_interval=self.settings.modbus.poll_interval,
                    ),
                ),
            ),
            "bacnet": (
                self.settings.is_protocol_active("bacnet"),
                lambda: BacnetEngine(
                    simulation=self.simulation,
                    ip=self.settings.bacnet.ip,
                    port=self.settings.bacnet.port,
                    device_id=self.settings.bacnet.device_id,
                    config=ProtocolConfig(
                        enabled=self.settings.bacnet.enabled,
                    ),
                ),
            ),
            "mqtt": (
                self.settings.is_protocol_active("mqtt"),
                lambda: MqttEngine(
                    simulation=self.simulation,
                    broker_host=self.settings.mqtt.broker_host,
                    broker_port=self.settings.mqtt.broker_port,
                    username=self.settings.mqtt.username,
                    password=self.settings.mqtt.password,
                    client_id=self.settings.mqtt.client_id,
                    config=ProtocolConfig(
                        enabled=self.settings.mqtt.enabled,
                        update_interval=self.settings.mqtt.publish_interval,
                    ),
                ),
            ),
            "opcua": (
                self.settings.is_protocol_active("opcua"),
                lambda: OpcUaEngine(
                    simulation=self.simulation,
                    endpoint=self.settings.opcua.endpoint,
                    server_name=self.settings.opcua.server_name,
                    config=ProtocolConfig(
                        enabled=self.settings.opcua.enabled,
                    ),
                ),
            ),
            "siemens": (
                self.settings.is_protocol_active("siemens"),
                lambda: SiemensEngine(
                    simulation=self.simulation,
                    rack=self.settings.siemens.rack,
                    slot=self.settings.siemens.slot,
                    config=ProtocolConfig(
                        enabled=self.settings.siemens.enabled,
                    ),
                ),
            ),
            "http": (
                self.settings.is_protocol_active("http"),
                lambda: HttpEngine(
                    simulation=self.simulation,
                    host=self.settings.http.host,
                    port=self.settings.http.port,
                    config=ProtocolConfig(
                        enabled=self.settings.http.enabled,
                    ),
                ),
            ),
            "sparkplug": (
                self.settings.is_protocol_active("sparkplug"),
                lambda: SparkplugEngine(
                    simulation=self.simulation,
                    broker_host=self.settings.mqtt.broker_host,
                    broker_port=self.settings.mqtt.broker_port,
                    group_id=self.settings.sparkplug.group_id,
                    edge_node=self.settings.sparkplug.edge_node,
                    device_id=self.settings.sparkplug.device_id,
                    config=ProtocolConfig(
                        enabled=self.settings.sparkplug.enabled,
                        update_interval=self.settings.sparkplug.publish_interval,
                    ),
                ),
            ),
            "dnp3": (
                self.settings.is_protocol_active("dnp3"),
                lambda: Dnp3Engine(
                    simulation=self.simulation,
                    host=self.settings.dnp3.host,
                    port=self.settings.dnp3.port,
                    outstation_address=self.settings.dnp3.outstation_address,
                    config=ProtocolConfig(
                        enabled=self.settings.dnp3.enabled,
                    ),
                ),
            ),
            "ethernetip": (
                self.settings.is_protocol_active("ethernetip"),
                lambda: EthernetIpEngine(
                    simulation=self.simulation,
                    host=self.settings.ethernetip.host,
                    port=self.settings.ethernetip.port,
                    config=ProtocolConfig(
                        enabled=self.settings.ethernetip.enabled,
                    ),
                ),
            ),
            "profinet": (
                self.settings.is_protocol_active("profinet"),
                lambda: ProfinetEngine(
                    simulation=self.simulation,
                    host=self.settings.profinet.host,
                    port=self.settings.profinet.port,
                    config=ProtocolConfig(
                        enabled=self.settings.profinet.enabled,
                    ),
                ),
            ),
            "canopen": (
                self.settings.is_protocol_active("canopen"),
                lambda: CanopenEngine(
                    simulation=self.simulation,
                    node_id=self.settings.canopen.node_id,
                    config=ProtocolConfig(
                        enabled=self.settings.canopen.enabled,
                    ),
                ),
            ),
            "iec61850": (
                self.settings.is_protocol_active("iec61850"),
                lambda: Iec61850Engine(
                    simulation=self.simulation,
                    host=self.settings.iec61850.host,
                    port=self.settings.iec61850.port,
                    config=ProtocolConfig(
                        enabled=self.settings.iec61850.enabled,
                    ),
                ),
            ),
            "iec104": (
                self.settings.is_protocol_active("iec104"),
                lambda: Iec104Engine(
                    simulation=self.simulation,
                    host=self.settings.iec104.host,
                    port=self.settings.iec104.port,
                    asdu_address=self.settings.iec104.asdu_address,
                    config=ProtocolConfig(
                        enabled=self.settings.iec104.enabled,
                    ),
                ),
            ),
            "websocket": (
                self.settings.is_protocol_active("websocket"),
                lambda: WebSocketEngine(
                    simulation=self.simulation,
                    host=self.settings.websocket.host,
                    port=self.settings.websocket.port,
                    config=ProtocolConfig(
                        enabled=self.settings.websocket.enabled,
                    ),
                ),
            ),
            "grpc": (
                self.settings.is_protocol_active("grpc"),
                lambda: GrpcEngine(
                    simulation=self.simulation,
                    host=self.settings.grpc.host,
                    port=self.settings.grpc.port,
                    config=ProtocolConfig(
                        enabled=self.settings.grpc.enabled,
                    ),
                ),
            ),
        }

        for name, (active, factory) in protocol_map.items():
            if active:
                try:
                    engine = factory()
                    self.registry.register(engine)
                    logger.info(f"Registered protocol engine: {name}")
                except Exception as e:
                    logger.error(f"Failed to register protocol '{name}': {e}")

        logger.info(f"Registered {self.registry.count} protocol engines")

    def _start_monitoring(self) -> None:
        """Start health monitoring and logging threads."""
        self._health_thread = Thread(target=self._health_loop, daemon=True, name="health-monitor")
        self._health_thread.start()

        self._log_thread = Thread(target=self._log_loop, daemon=True, name="log-monitor")
        self._log_thread.start()

    def _health_loop(self) -> None:
        """Periodic health check loop."""
        while self._running:
            try:
                health = self.registry.get_all_health()
                for name, status in health.items():
                    if status["state"] == "error":
                        logger.warning(f"Protocol '{name}' in error state: {status['last_error']}")
                        if self.workflow_config.enable_auto_recovery:
                            self._recover_engine(name)
            except Exception as e:
                logger.error(f"Health check error: {e}")
            time.sleep(self.workflow_config.health_check_interval)

    def _log_loop(self) -> None:
        """Periodic status logging loop."""
        while self._running:
            try:
                device_count = sum(
                    len(cluster.devices)
                    for cluster in self.simulation.clusters.values()
                )
                signal_count = sum(
                    len(device.signals)
                    for cluster in self.simulation.clusters.values()
                    for device in cluster.devices.values()
                )
                logger.info(
                    f"Status: {len(self.simulation.clusters)} clusters, "
                    f"{device_count} devices, {signal_count} signals, "
                    f"{self.registry.count} protocols active"
                )
            except Exception as e:
                logger.error(f"Status log error: {e}")
            time.sleep(self.workflow_config.log_interval)

    def _recover_engine(self, name: str) -> None:
        """Attempt to recover a failed protocol engine."""
        engine = self.registry.get(name)
        if engine:
            logger.info(f"Attempting to recover protocol engine '{name}'")
            try:
                engine.stop()
                time.sleep(1)
                engine.start()
                logger.info(f"Recovery successful for '{name}'")
            except Exception as e:
                logger.error(f"Recovery failed for '{name}': {e}")

    def run(self) -> None:
        """Run the simulation main loop."""
        logger.info("Simulation running. Press Ctrl+C to stop.")

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # Run the simulation physics loop
        try:
            self.simulation.run(interval=self.settings.physics.update_interval)
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, initiating shutdown...")
        self.shutdown()
        sys.exit(0)

    def shutdown(self) -> None:
        """Graceful shutdown of all components."""
        logger.info("Shutting down simulation...")

        self._running = False

        # Stop protocol engines
        logger.info("Stopping protocol engines...")
        self.registry.stop_all()

        # Stop simulation
        self.simulation.stop()

        uptime = time.time() - self._start_time
        logger.info(f"Simulation shutdown complete (uptime: {uptime:.1f}s)")

    def save_scenario(self, path: Optional[str] = None) -> str:
        """Save the current simulation state as a scenario."""
        if not path:
            os.makedirs(self.workflow_config.scenario_dir, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            path = os.path.join(self.workflow_config.scenario_dir, f"scenario_{timestamp}.json")

        state = self.simulation.to_dict()
        with open(path, "w") as f:
            json.dump(state, f, indent=2)

        logger.info(f"Scenario saved to {path}")
        return path

    def load_scenario(self, path: str) -> None:
        """Load a simulation scenario from file."""
        with open(path, "r") as f:
            state = json.load(f)

        # TODO: Implement scenario loading
        logger.info(f"Scenario loaded from {path}")

    @property
    def status(self) -> Dict[str, Any]:
        """Get the current status of the simulation."""
        return {
            "running": self._running,
            "uptime": time.time() - self._start_time if self._running else 0,
            "clusters": len(self.simulation.clusters),
            "protocols": self.registry.count,
            "protocol_health": self.registry.get_all_health(),
        }