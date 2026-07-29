"""
Settings and configuration management for Industrial Communication Simulator.

Uses pydantic-settings to load from .env files with full validation.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from pydantic_settings import BaseSettings, SettingsConfigDict


class ModbusSettings(BaseSettings):
    """Modbus protocol settings."""

    model_config = SettingsConfigDict(env_prefix="MODBUS_", extra="ignore")

    enabled: bool = True
    mode: str = "tcp"  # 'tcp' or 'serial'
    tcp_host: str = "0.0.0.0"
    tcp_port: int = 5020
    serial_port: str = "/dev/ttyUSB0"
    serial_baud: int = 9600
    poll_interval: int = 5


class BacnetSettings(BaseSettings):
    """BACnet protocol settings."""

    model_config = SettingsConfigDict(env_prefix="BACNET_", extra="ignore")

    enabled: bool = True
    ip: str = "0.0.0.0"
    port: int = 47808
    mask: int = 24
    device_id: int = 1001


class MqttSettings(BaseSettings):
    """MQTT protocol settings."""

    model_config = SettingsConfigDict(env_prefix="MQTT_", extra="ignore")

    enabled: bool = True
    broker_host: str = "localhost"
    broker_port: int = 1883
    username: str = ""
    password: str = ""
    client_id: str = "industrial-simulator"
    publish_interval: int = 5


class OpcUaSettings(BaseSettings):
    """OPC UA protocol settings."""

    model_config = SettingsConfigDict(env_prefix="OPCUA_", extra="ignore")

    enabled: bool = True
    endpoint: str = "opc.tcp://0.0.0.0:4840"
    server_name: str = "IndustrialSimulator"


class SiemensSettings(BaseSettings):
    """Siemens S7 (Snap7) protocol settings."""

    model_config = SettingsConfigDict(env_prefix="SIEMENS_", extra="ignore")

    enabled: bool = True
    rack: int = 0
    slot: int = 2
    rack1: int = 0
    slot2: int = 2
    plc_address: str = "127.0.0.1"
    tsap: int = 0x0100


class HttpSettings(BaseSettings):
    """HTTP simulator settings."""

    model_config = SettingsConfigDict(env_prefix="HTTP_", extra="ignore")

    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8080


class SparkplugSettings(BaseSettings):
    """Sparkplug B settings."""

    model_config = SettingsConfigDict(env_prefix="SPARKPLUG_", extra="ignore")

    enabled: bool = True
    group_id: str = "IndustrialSim"
    edge_node: str = "simulator-edge-01"
    device_id: str = "sim-device-01"
    publish_interval: int = 5


class Dnp3Settings(BaseSettings):
    """DNP3 (SCADA/Utilities) settings."""

    model_config = SettingsConfigDict(env_prefix="DNP3_", extra="ignore")

    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 20000
    outstation_address: int = 100


class EthernetIpSettings(BaseSettings):
    """EtherNet/IP (Rockwell Automation CIP) settings."""

    model_config = SettingsConfigDict(env_prefix="ETHERNETIP_", extra="ignore")

    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 44818


class ProfinetSettings(BaseSettings):
    """PROFINET (Siemens Industrial Ethernet) settings."""

    model_config = SettingsConfigDict(env_prefix="PROFINET_", extra="ignore")

    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 34964


class CanopenSettings(BaseSettings):
    """CANopen (Motion Control/Robotics) settings."""

    model_config = SettingsConfigDict(env_prefix="CANOPEN_", extra="ignore")

    enabled: bool = False
    node_id: int = 1


class Iec61850Settings(BaseSettings):
    """IEC 61850 (Substation Automation) settings."""

    model_config = SettingsConfigDict(env_prefix="IEC61850_", extra="ignore")

    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 102


class Iec104Settings(BaseSettings):
    """IEC 60870-5-104 (Power Telecontrol) settings."""

    model_config = SettingsConfigDict(env_prefix="IEC104_", extra="ignore")

    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 2404
    asdu_address: int = 1


class WebSocketSettings(BaseSettings):
    """WebSocket (Real-time Dashboards) settings."""

    model_config = SettingsConfigDict(env_prefix="WEBSOCKET_", extra="ignore")

    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8765


class GrpcSettings(BaseSettings):
    """gRPC (High-performance RPC) settings."""

    model_config = SettingsConfigDict(env_prefix="GRPC_", extra="ignore")

    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 50051


class PhysicsSettings(BaseSettings):
    """Physics engine settings."""

    model_config = SettingsConfigDict(env_prefix="PHYSICS_", extra="ignore")

    update_interval: float = 1.0
    enable_noise: bool = True
    enable_drift: bool = True
    enable_cross_coupling: bool = True
    seed: Optional[int] = 42


class Settings(BaseSettings):
    """
    Root settings for the Industrial Communication Simulator.

    Loads from .env file in the project root directory.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # General
    simulator_name: str = "IndustrialCommSimulator"
    simulator_version: str = "1.0.0"
    log_level: str = "INFO"
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    active_protocols: str = "modbus,bacnet,mqtt,opcua,siemens,http,sparkplug"

    # Default device templates (comma-separated)
    default_devices: str = ""

    # Protocol settings
    modbus: ModbusSettings = ModbusSettings()
    bacnet: BacnetSettings = BacnetSettings()
    mqtt: MqttSettings = MqttSettings()
    opcua: OpcUaSettings = OpcUaSettings()
    siemens: SiemensSettings = SiemensSettings()
    http: HttpSettings = HttpSettings()
    sparkplug: SparkplugSettings = SparkplugSettings()
    dnp3: Dnp3Settings = Dnp3Settings()
    ethernetip: EthernetIpSettings = EthernetIpSettings()
    profinet: ProfinetSettings = ProfinetSettings()
    canopen: CanopenSettings = CanopenSettings()
    iec61850: Iec61850Settings = Iec61850Settings()
    iec104: Iec104Settings = Iec104Settings()
    websocket: WebSocketSettings = WebSocketSettings()
    grpc: GrpcSettings = GrpcSettings()

    # Physics settings
    physics: PhysicsSettings = PhysicsSettings()

    @property
    def active_protocol_list(self) -> List[str]:
        """Get list of active protocols."""
        return [p.strip().lower() for p in self.active_protocols.split(",") if p.strip()]

    @property
    def active_protocol_set(self) -> Set[str]:
        """Get set of active protocols."""
        return set(self.active_protocol_list)

    def is_protocol_active(self, protocol: str) -> bool:
        """Check if a protocol is enabled."""
        protocol = protocol.lower().strip()
        # Check both the active list and the individual protocol's enabled flag
        if protocol not in self.active_protocol_set:
            return False
        settings_map = {
            "modbus": self.modbus,
            "bacnet": self.bacnet,
            "mqtt": self.mqtt,
            "opcua": self.opcua,
            "siemens": self.siemens,
            "http": self.http,
            "sparkplug": self.sparkplug,
            "dnp3": self.dnp3,
            "ethernetip": self.ethernetip,
            "profinet": self.profinet,
            "canopen": self.canopen,
            "iec61850": self.iec61850,
            "iec104": self.iec104,
            "websocket": self.websocket,
            "grpc": self.grpc,
        }
        proto_settings = settings_map.get(protocol)
        return proto_settings.enabled if hasattr(proto_settings, "enabled") else True

    def parse_default_devices(self) -> List[Dict[str, str]]:
        """
        Parse the DEFAULT_DEVICES string into device configs.

        Format: name:protocol:type:unit:min:max:noise:drift:initial
        Example: level:modbus:analog:m:0:100:0.5:0.01:50
        """
        if not self.default_devices:
            return []

        devices = []
        for device_str in self.default_devices.split(","):
            parts = device_str.strip().split(":")
            if len(parts) >= 9:
                devices.append({
                    "name": parts[0],
                    "protocol": parts[1],
                    "type": parts[2],
                    "unit": parts[3],
                    "min": float(parts[4]),
                    "max": float(parts[5]),
                    "noise": float(parts[6]),
                    "drift": float(parts[7]),
                    "initial": float(parts[8]),
                })
        return devices


def load_settings(env_file: Optional[str] = None) -> Settings:
    """
    Load application settings from .env file.

    Args:
        env_file: Path to .env file. If None, looks for .env in CWD.

    Returns:
        Fully validated Settings object.
    """
    if env_file:
        return Settings(_env_file=env_file)
    return Settings()
