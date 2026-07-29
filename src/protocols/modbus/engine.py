"""
Modbus Protocol Engine.

Implements Modbus TCP/RTU server that exposes physics-backed device signals
as Modbus registers, coils, and discrete inputs.

Modbus Protocol Overview:
-------------------------
Modbus is a serial communication protocol developed by Modicon in 1979.
It has become a standard communication protocol for industrial electronic
devices (PLCs, RTUs, sensors, actuators).

Two main variants:
1. Modbus TCP (Port 502): Ethernet-based, uses TCP/IP
2. Modbus RTU/ASCII: Serial-based, uses RS-485/RS-232

Function Codes Supported:
- FC01 (0x01): Read Coils
- FC02 (0x02): Read Discrete Inputs
- FC03 (0x03): Read Holding Registers
- FC04 (0x04): Read Input Registers
- FC05 (0x05): Write Single Coil
- FC06 (0x06): Write Single Register
- FC15 (0x0F): Write Multiple Coils
- FC16 (0x10): Write Multiple Registers

Data Model:
- Coils (0x): Read-write binary values
- Discrete Inputs (1x): Read-only binary values
- Input Registers (4x): Read-only analog values
- Holding Registers (3x): Read-write analog values

Virtual Serial Port Setup (for Modbus RTU):
-------------------------------------------
To create virtual serial port pairs for testing:

    # Create a pair of linked virtual serial ports
    socat -d -d pty,raw,echo=0 pty,raw,echo=0

    # This creates two ports like /dev/pts/2 and /dev/pts/3
    # Data written to one port appears on the other

    # Run simulator with serial mode
    MODBUS_SERIAL_PORT=/dev/pts/2 python -m src.main

    # Connect a Modbus RTU client to the other port
    modbus-client --port /dev/pts/3

In Docker:
    # The entrypoint.sh automatically creates virtual serial ports
    # when MODBUS_SERIAL_PORT environment variable is set
"""

from __future__ import annotations

import logging
import struct
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext
try:
    from pymodbus.device import ModbusDeviceIdentification
except ImportError:
    try:
        from pymodbus.server import ModbusDeviceIdentification
    except ImportError:
        # ModbusDeviceIdentification not available in newer pymodbus versions
        ModbusDeviceIdentification = None
from pymodbus.server import StartTcpServer
from pymodbus.server import StopServer
from pymodbus.server import StartSerialServer
from pymodbus.server import StopSerialServer

from src.core.device import Device, SimulationManager
from src.protocols.base import ProtocolConfig, ProtocolEngine, ProtocolState

logger = logging.getLogger(__name__)


class ModbusEngine(ProtocolEngine):
    """
    Modbus TCP/RTU protocol engine.

    Maps device signals to Modbus address space:
    - Analog signals -> Holding Registers (3x) and Input Registers (4x)
    - Binary signals -> Coils (0x) and Discrete Inputs (1x)

    Supports both TCP (port 502) and Serial (RTU/ASCII) modes.
    """

    def __init__(
        self,
        name: str = "modbus",
        config: Optional[ProtocolConfig] = None,
        simulation: Optional[SimulationManager] = None,
        host: str = "0.0.0.0",
        port: int = 5020,
        mode: str = "tcp",  # 'tcp' or 'serial'
        serial_port: str = "/dev/ttyUSB0",
        serial_baud: int = 9600,
    ):
        super().__init__(name, config or ProtocolConfig(), simulation)
        self.host = host
        self.port = port
        self.mode = mode.lower()
        self.serial_port = serial_port
        self.serial_baud = serial_baud
        self._context: Optional[ModbusServerContext] = None
        self._lock = Lock()
        self._register_map: Dict[str, Dict[str, int]] = {}  # device_id -> {signal_name -> address}
        self._next_address: int = 0

    @property
    def protocol_name(self) -> str:
        return "modbus"

    def _allocate_addresses(self, device: Device) -> None:
        """Allocate Modbus addresses for a device's signals."""
        if device.device_id in self._register_map:
            return

        addresses = {}
        for signal_name in device.signals:
            addresses[signal_name] = self._next_address
            self._next_address += 2  # Each analog value uses 2 registers (32-bit float)
        self._register_map[device.device_id] = addresses
        logger.debug(f"Allocated Modbus addresses for device '{device.device_id}': {addresses}")

    def _start_engine(self) -> None:
        """Start the Modbus server (TCP or Serial based on mode)."""
        if self.mode == "serial":
            self._start_serial_engine()
        else:
            self._start_tcp_engine()

    def _start_tcp_engine(self) -> None:
        """Start the Modbus TCP server."""
        # Initialize data store with 10000 registers
        block = ModbusSequentialDataBlock(0, [0] * 10000)
        self._context = ModbusServerContext(slaves={1: block}, single=True)

        # Set device identification (if available)
        identity = None
        if ModbusDeviceIdentification:
            identity = ModbusDeviceIdentification()
            identity.VendorName = "IndustrialCommSimulator"
            identity.ProductCode = "ICS"
            identity.VendorUrl = "https://github.com/nimish-nirmal/industrial-comm-simulator"
            identity.ProductName = "Industrial Communication Simulator"
            identity.ModelName = "Modbus Simulator"
            identity.MajorMinorRevision = "1.0"

        # Start server in a separate thread
        StartTcpServer(
            context=self._context,
            identity=identity,
            address=(self.host, self.port),
        )
        logger.info(f"Modbus TCP server started on {self.host}:{self.port}")

    def _start_serial_engine(self) -> None:
        """Start the Modbus RTU/ASCII serial server."""
        logger.info(f"Starting Modbus serial server on {self.serial_port} at {self.serial_baud} baud")
        
        # Initialize data store with 10000 registers
        block = ModbusSequentialDataBlock(0, [0] * 10000)
        self._context = ModbusServerContext(slaves={1: block}, single=True)

        # Set device identification (if available)
        identity = None
        if ModbusDeviceIdentification:
            identity = ModbusDeviceIdentification()
            identity.VendorName = "IndustrialCommSimulator"
            identity.ProductCode = "ICS"
            identity.ProductName = "Industrial Communication Simulator"
            identity.ModelName = "Modbus RTU Simulator"
            identity.MajorMinorRevision = "1.0"

        # Start serial server
        StartSerialServer(
            context=self._context,
            identity=identity,
            port=self.serial_port,
            baudrate=self.serial_baud,
        )
        logger.info(f"Modbus RTU server started on {self.serial_port} at {self.serial_baud} baud")

    def _stop_engine(self) -> None:
        """Stop the Modbus server."""
        if self.mode == "serial":
            StopSerialServer()
            logger.info("Modbus RTU server stopped")
        else:
            StopServer()
            logger.info("Modbus TCP server stopped")

    def _publish_device_values(self, device: Device) -> None:
        """Publish device signal values to Modbus registers."""
        if not self._context:
            return

        self._allocate_addresses(device)
        addresses = self._register_map.get(device.device_id, {})

        with self._lock:
            context = self._context[1]  # Slave ID 1

            for signal_name, state in device.signals.items():
                address = addresses.get(signal_name)
                if address is None:
                    continue

                value = state.current_value
                profile = state.profile

                # Pack float into two 16-bit registers
                packed = struct.pack(">f", value)
                high, low = struct.unpack(">HH", packed)

                if profile.signal_type.value in ("binary", "discrete"):
                    # Use coil (0x) for binary/discrete
                    context.setValues(0, address, [int(value)])
                else:
                    # Use holding register (3x) for analog
                    context.setValues(3, address, [high, low])

    def _handle_external_command(self, device_id: str, signal_name: str, value: float) -> None:
        """Handle a Modbus write request."""
        logger.info(f"Modbus write: {device_id}.{signal_name} = {value}")
        # The value is already set in the simulation by handle_command()
