"""
Protocol implementations for Industrial Communication Simulator.

Supported Protocols (15 total):
  1. Modbus TCP      - Industrial automation (PLC, RTU)
  2. BACnet/IP       - Building automation (HVAC, lighting)
  3. MQTT            - IoT messaging (pub/sub)
  4. OPC UA          - Platform-independent industrial communication
  5. Siemens S7      - Siemens PLC communication (Snap7)
  6. HTTP REST       - Web API for monitoring/control
  7. Sparkplug B     - MQTT-based IIoT standard
  8. DNP3            - SCADA/utility communication
  9. EtherNet/IP     - Rockwell Automation CIP
  10. PROFINET       - Siemens industrial Ethernet
  11. CANopen         - Motion control/robotics
  12. IEC 61850       - Substation automation (MMS)
  13. IEC 60870-5-104 - Power system telecontrol
  14. WebSocket       - Real-time browser dashboards
  15. gRPC            - High-performance RPC streaming
"""
from src.protocols.base import (
    ProtocolConfig,
    ProtocolEngine,
    ProtocolRegistry,
    ProtocolState,
)

__all__ = [
    "ProtocolEngine",
    "ProtocolConfig",
    "ProtocolState",
    "ProtocolRegistry",
]
