"""Test all 15 protocol engines for basic functionality."""
from __future__ import annotations

import pytest


class TestAllProtocols:
    """Test suite for all protocol engines."""

    def test_modbus_engine(self):
        """Test Modbus engine can be instantiated."""
        from src.protocols.modbus import ModbusEngine
        engine = ModbusEngine(
            name="modbus-test",
            host="127.0.0.1",
            port=5020,
            mode="tcp",
        )
        assert engine.protocol_name == "modbus"
        assert engine.state.value == "stopped"

    def test_bacnet_engine(self):
        """Test BACnet engine can be instantiated."""
        from src.protocols.bacnet import BacnetEngine
        engine = BacnetEngine(
            name="bacnet-test",
            ip="127.0.0.1",
            port=47808,
            device_id=1001,
        )
        assert engine.protocol_name == "bacnet"
        assert engine.state.value == "stopped"

    def test_mqtt_engine(self):
        """Test MQTT engine can be instantiated."""
        from src.protocols.mqtt import MqttEngine
        engine = MqttEngine(
            name="mqtt-test",
            broker_host="localhost",
            broker_port=1883,
        )
        assert engine.protocol_name == "mqtt"
        assert engine.state.value == "stopped"

    def test_opcua_engine(self):
        """Test OPC UA engine can be instantiated."""
        from src.protocols.opcua import OpcUaEngine
        engine = OpcUaEngine(
            name="opcua-test",
            endpoint="opc.tcp://127.0.0.1:4840",
        )
        assert engine.protocol_name == "opcua"
        assert engine.state.value == "stopped"

    def test_siemens_engine(self):
        """Test Siemens S7 engine can be instantiated."""
        from src.protocols.siemens import SiemensEngine
        engine = SiemensEngine(
            name="siemens-test",
            rack=0,
            slot=2,
        )
        assert engine.protocol_name == "siemens"
        assert engine.state.value == "stopped"

    def test_http_engine(self):
        """Test HTTP engine can be instantiated."""
        from src.protocols.http import HttpEngine
        engine = HttpEngine(
            name="http-test",
            host="127.0.0.1",
            port=8080,
        )
        assert engine.protocol_name == "http"
        assert engine.state.value == "stopped"

    def test_sparkplug_engine(self):
        """Test Sparkplug B engine can be instantiated."""
        from src.protocols.sparkplug import SparkplugEngine
        engine = SparkplugEngine(
            name="sparkplug-test",
            broker_host="localhost",
            broker_port=1883,
            group_id="TestGroup",
            edge_node="test-edge",
            device_id="test-device",
        )
        assert engine.protocol_name == "sparkplug"
        assert engine.state.value == "stopped"

    def test_dnp3_engine(self):
        """Test DNP3 engine can be instantiated."""
        from src.protocols.dnp3 import Dnp3Engine
        engine = Dnp3Engine(
            name="dnp3-test",
            host="127.0.0.1",
            port=20000,
            outstation_address=100,
        )
        assert engine.protocol_name == "dnp3"
        assert engine.state.value == "stopped"

    def test_ethernetip_engine(self):
        """Test EtherNet/IP engine can be instantiated."""
        from src.protocols.ethernetip import EthernetIpEngine
        engine = EthernetIpEngine(
            name="ethernetip-test",
            host="127.0.0.1",
            port=44818,
        )
        assert engine.protocol_name == "ethernetip"
        assert engine.state.value == "stopped"

    def test_profinet_engine(self):
        """Test PROFINET engine can be instantiated."""
        from src.protocols.profinet import ProfinetEngine
        engine = ProfinetEngine(
            name="profinet-test",
            host="127.0.0.1",
            port=34964,
        )
        assert engine.protocol_name == "profinet"
        assert engine.state.value == "stopped"

    def test_canopen_engine(self):
        """Test CANopen engine can be instantiated."""
        from src.protocols.canopen import CanopenEngine
        engine = CanopenEngine(
            name="canopen-test",
            node_id=1,
        )
        assert engine.protocol_name == "canopen"
        assert engine.state.value == "stopped"

    def test_iec61850_engine(self):
        """Test IEC 61850 engine can be instantiated."""
        from src.protocols.iec61850 import Iec61850Engine
        engine = Iec61850Engine(
            name="iec61850-test",
            host="127.0.0.1",
            port=102,
        )
        assert engine.protocol_name == "iec61850"
        assert engine.state.value == "stopped"

    def test_iec104_engine(self):
        """Test IEC 104 engine can be instantiated."""
        from src.protocols.iec104 import Iec104Engine
        engine = Iec104Engine(
            name="iec104-test",
            host="127.0.0.1",
            port=2404,
            asdu_address=1,
        )
        assert engine.protocol_name == "iec104"
        assert engine.state.value == "stopped"

    def test_websocket_engine(self):
        """Test WebSocket engine can be instantiated."""
        from src.protocols.websocket import WebSocketEngine
        engine = WebSocketEngine(
            name="websocket-test",
            host="127.0.0.1",
            port=8765,
        )
        assert engine.protocol_name == "websocket"
        assert engine.state.value == "stopped"

    def test_grpc_engine(self):
        """Test gRPC engine can be instantiated."""
        from src.protocols.grpc import GrpcEngine
        engine = GrpcEngine(
            name="grpc-test",
            host="127.0.0.1",
            port=50051,
        )
        assert engine.protocol_name == "grpc"
        assert engine.state.value == "stopped"

    def test_all_protocols_registry(self):
        """Test that all protocols can be registered in a registry."""
        from src.protocols.base import ProtocolRegistry
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

        registry = ProtocolRegistry()
        
        # Register all 15 protocols
        engines = [
            ModbusEngine(name="modbus"),
            BacnetEngine(name="bacnet"),
            MqttEngine(name="mqtt"),
            OpcUaEngine(name="opcua"),
            SiemensEngine(name="siemens"),
            HttpEngine(name="http"),
            SparkplugEngine(name="sparkplug"),
            Dnp3Engine(name="dnp3"),
            EthernetIpEngine(name="ethernetip"),
            ProfinetEngine(name="profinet"),
            CanopenEngine(name="canopen"),
            Iec61850Engine(name="iec61850"),
            Iec104Engine(name="iec104"),
            WebSocketEngine(name="websocket"),
            GrpcEngine(name="grpc"),
        ]

        for engine in engines:
            registry.register(engine)

        assert registry.count == 15
        assert len(registry.get_all_health()) == 15

    def test_protocol_health_status(self):
        """Test that all protocols report health status."""
        from src.protocols.base import ProtocolRegistry
        from src.protocols.modbus import ModbusEngine
        from src.protocols.mqtt import MqttEngine

        registry = ProtocolRegistry()
        registry.register(ModbusEngine(name="modbus"))
        registry.register(MqttEngine(name="mqtt"))

        health = registry.get_all_health()
        assert "modbus" in health
        assert "mqtt" in health
        assert health["modbus"]["state"] == "stopped"
        assert health["modbus"]["enabled"] is True
        assert health["modbus"]["error_count"] == 0
