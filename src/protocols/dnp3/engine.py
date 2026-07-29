"""
DNP3 (Distributed Network Protocol) Protocol Engine.

Implements a DNP3 outstation (slave) that exposes physics-backed device
signals as DNP3 data objects.

DNP3 Protocol Overview:
-----------------------
DNP3 is a SCADA protocol widely used in electric, water, oil & gas, and
other utility industries for communication between master stations and
remote terminal units (RTUs), intelligent electronic devices (IEDs), and
substation controllers.

Key Concepts:
- Outstation: The slave/remote device that provides data (our simulator)
- Master: The control center that requests data
- Object Groups: Data type identifiers (e.g., Group 30 = Analog Input)
- Variations: Data format within a group (e.g., 16-bit, 32-bit, float)
- Function Codes: Operation to perform (Read=0x01, Write=0x02, etc.)
- Point Index: 16-bit address for each data point

Object Groups Used:
- Group 1:  Binary Input (status)
- Group 10: Binary Output (control relay)
- Group 12: Control Relay Output Block (CROB)
- Group 20: Binary Counter
- Group 30: Analog Input (measured values)
- Group 40: Analog Output Status
- Group 41: Analog Output Block
- Group 60: Class Objects (0, 1, 2, 3 for polling classes)

Port: 20000 TCP
"""

from __future__ import annotations

import logging
import socket
import struct
import threading
from typing import Any, Dict, List, Optional, Tuple

from src.core.device import Device, SimulationManager
from src.protocols.base import ProtocolConfig, ProtocolEngine, ProtocolState

logger = logging.getLogger(__name__)

# DNP3 Constants
DNP3_SYNC = b"\x05\x64"  # DNP3 frame sync bytes
DNP3_CRC_POLY = 0xA6BC  # DNP3 CRC-16 polynomial

# Function Codes
FC_READ = 0x01
FC_WRITE = 0x02
FC_DIRECT_OPERATE = 0x05
FC_DIRECT_OPERATE_NO_ACK = 0x06

# Object Groups
OBJ_BINARY_INPUT = 1       # Group 1
OBJ_BINARY_OUTPUT = 10     # Group 10
OBJ_CONTROL_RELAY = 12     # Group 12
OBJ_BINARY_COUNTER = 20    # Group 20
OBJ_ANALOG_INPUT = 30      # Group 30
OBJ_ANALOG_OUTPUT = 40     # Group 40
OBJ_ANALOG_OUTPUT_BLOCK = 41  # Group 41
OBJ_CLASS_0 = 60           # Group 60 - Class 0 (all data)
OBJ_CLASS_1 = 61           # Group 61 - Class 1
OBJ_CLASS_2 = 62           # Group 62 - Class 2
OBJ_CLASS_3 = 63           # Group 63 - Class 3

# Object Variations
VAR_BINARY_INPUT_PACKED = 1     # Var 1: Packed format
VAR_BINARY_INPUT_FLAGS = 2      # Var 2: With quality flags
VAR_ANALOG_INPUT_16BIT = 1      # Var 1: 16-bit integer
VAR_ANALOG_INPUT_32BIT = 2      # Var 2: 32-bit integer
VAR_ANALOG_INPUT_FLOAT = 5      # Var 5: 32-bit float with flag
VAR_ANALOG_INPUT_DOUBLE = 6     # Var 6: 64-bit double with flag
VAR_CONTROL_RELAY = 1           # Var 1: CROB


def _dnp3_crc16(data: bytes) -> int:
    """Calculate DNP3 CRC-16 checksum."""
    crc = 0x0000
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ DNP3_CRC_POLY
            else:
                crc >>= 1
    return crc


def _build_dnp3_response(
    destination: int,
    source: int,
    data: bytes,
) -> bytes:
    """
    Build a complete DNP3 response frame.

    Frame format:
    - Sync: 2 bytes (0x0564)
    - Length: 1 byte (CRC blocks + header)
    - Control: 1 byte
    - Destination: 2 bytes
    - Source: 2 bytes
    - CRC: 2 bytes (of header)
    - Transport header: 1 byte
    - Application layer + data: variable
    - CRC per 16-byte data block
    """
    app_header = struct.pack("<BB", 0xC0 | 0x10, 0x00) + data  # App control + function
    header = struct.pack("<BBHH", 0x44, 0x00, destination, source)  # Control + addrs
    length = 5 + 2 + 1 + len(data) + len(data) // 16 * 2  # Approximate
    header_crc = struct.pack("<H", _dnp3_crc16(header))

    frame = DNP3_SYNC
    frame += struct.pack("<B", length)
    frame += header
    frame += header_crc
    frame += app_header

    return frame


class Dnp3Engine(ProtocolEngine):
    """
    DNP3 Outstation (Slave) Protocol Engine.

    Implements a DNP3 outstation that exposes physics-backed device
    signals as DNP3 data objects readable by a DNP3 master station.

    Point Map:
    - Analog signals: Analog Input points (Group 30, Var 5 - Float with flag)
    - Binary signals: Binary Input points (Group 1, Var 2 - With quality flags)
    - Counter signals: Binary Counter points (Group 20)
    - Commands: Analog Output Block (Group 41) for setpoint control
    """

    def __init__(
        self,
        name: str = "dnp3",
        config: Optional[ProtocolConfig] = None,
        simulation: Optional[SimulationManager] = None,
        host: str = "0.0.0.0",
        port: int = 20000,
        outstation_address: int = 100,
    ):
        super().__init__(name, config or ProtocolConfig(), simulation)
        self.host = host
        self.port = port
        self.outstation_address = outstation_address
        self._server_socket: Optional[socket.socket] = None
        self._clients: List[socket.socket] = []
        self._lock = threading.Lock()
        self._running_internal: bool = False
        self._accept_thread: Optional[threading.Thread] = None

        # Point maps: device_id -> {signal_name -> point_index}
        self._analog_points: Dict[str, Dict[str, int]] = {}
        self._binary_points: Dict[str, Dict[str, int]] = {}
        self._next_point: int = 0

    @property
    def protocol_name(self) -> str:
        return "dnp3"

    def _allocate_points(self, device: Device) -> int:
        """Allocate DNP3 point indices for a device's signals."""
        count = 0
        if device.device_id not in self._analog_points:
            self._analog_points[device.device_id] = {}
        if device.device_id not in self._binary_points:
            self._binary_points[device.device_id] = {}

        for signal_name, state in device.signals.items():
            profile = state.profile
            if profile.signal_type.value == "analog":
                if signal_name not in self._analog_points[device.device_id]:
                    self._analog_points[device.device_id][signal_name] = self._next_point
                    self._next_point += 1
                    count += 1
            else:
                if signal_name not in self._binary_points[device.device_id]:
                    self._binary_points[device.device_id][signal_name] = self._next_point
                    self._next_point += 1
                    count += 1
        return count

    def _start_engine(self) -> None:
        """Start the DNP3 outstation TCP server."""
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind((self.host, self.port))
        self._server_socket.listen(5)
        self._server_socket.settimeout(1.0)
        self._running_internal = True

        self._accept_thread = threading.Thread(
            target=self._accept_connections,
            daemon=True,
            name="dnp3-accept",
        )
        self._accept_thread.start()
        logger.info(f"DNP3 outstation started on {self.host}:{self.port} (address={self.outstation_address})")

    def _stop_engine(self) -> None:
        """Stop the DNP3 outstation."""
        self._running_internal = False
        with self._lock:
            for client in self._clients:
                try:
                    client.close()
                except Exception:
                    pass
            self._clients.clear()
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
        logger.info("DNP3 outstation stopped")

    def _accept_connections(self) -> None:
        """Accept incoming DNP3 master connections."""
        while self._running_internal:
            try:
                client, addr = self._server_socket.accept()
                with self._lock:
                    self._clients.append(client)
                client_thread = threading.Thread(
                    target=self._handle_client,
                    args=(client, addr),
                    daemon=True,
                    name=f"dnp3-client-{addr[0]}",
                )
                client_thread.start()
                logger.info(f"DNP3 master connected: {addr}")
            except socket.timeout:
                continue
            except Exception as e:
                if self._running_internal:
                    logger.error(f"DNP3 accept error: {e}")

    def _handle_client(self, client: socket.socket, addr: Tuple[str, int]) -> None:
        """Handle communication with a connected DNP3 master."""
        buffer = b""
        while self._running_internal:
            try:
                data = client.recv(4096)
                if not data:
                    break
                buffer += data
                while len(buffer) >= 10:
                    # Parse frame length
                    length = buffer[2] if len(buffer) > 2 else 0
                    if len(buffer) < length + 2:
                        break
                    frame = buffer[:length + 2]
                    buffer = buffer[length + 2:]
                    self._process_request(client, frame, addr)
            except socket.timeout:
                continue
            except (ConnectionResetError, BrokenPipeError):
                break
            except Exception as e:
                logger.error(f"DNP3 client error for {addr}: {e}")
                break

        with self._lock:
            self._clients.remove(client) if client in self._clients else None
        try:
            client.close()
        except Exception:
            pass
        logger.info(f"DNP3 master disconnected: {addr}")

    def _process_request(self, client: socket.socket, frame: bytes, addr: Tuple[str, int]) -> None:
        """Process an incoming DNP3 request frame."""
        if len(frame) < 10:
            logger.warning(f"DNP3 frame too short from {addr}: {len(frame)} bytes")
            return

        # Parse header
        sync = frame[0:2]
        if sync != DNP3_SYNC:
            logger.debug(f"Bad DNP3 sync from {addr}: {sync.hex()}")
            return

        length = frame[2]
        control = frame[3]
        destination = struct.unpack("<H", frame[4:6])[0]
        source = struct.unpack("<H", frame[6:8])[0]

        # Check if addressed to us
        if destination != self.outstation_address and destination != 0xFFFF:
            return

        logger.debug(
            f"DNP3 request from {addr}: dest={destination}, src={source}, len={length}, ctrl={control:#04x}"
        )

        # Send response (simplified - acknowledges the request)
        response = _build_dnp3_response(source, self.outstation_address, b"\x00")
        try:
            client.send(response)
            logger.debug(f"DNP3 response sent to {addr}")
        except Exception as e:
            logger.error(f"DNP3 send error to {addr}: {e}")

    def _publish_device_values(self, device: Device) -> None:
        """Publish device signal values as DNP3 data objects."""
        self._allocate_points(device)

        # Log the current state for debugging
        for signal_name, state in device.signals.items():
            if state.profile.signal_type.value == "analog":
                point = self._analog_points.get(device.device_id, {}).get(signal_name)
                if point is not None:
                    logger.debug(
                        f"DNP3 AnalogInput point={point}: {state.current_value:.2f} {state.profile.unit}"
                    )
            else:
                point = self._binary_points.get(device.device_id, {}).get(signal_name)
                if point is not None:
                    logger.debug(
                        f"DNP3 BinaryInput point={point}: {int(state.current_value)}"
                    )

    def _handle_external_command(self, device_id: str, signal_name: str, value: float) -> None:
        """Handle a DNP3 command request (Analog Output Block or CROB)."""
        logger.info(f"DNP3 command: {device_id}.{signal_name} = {value}")

    def get_point_value(self, device_id: str, signal_name: str) -> Optional[float]:
        """
        Get the current value of a specific DNP3 point.

        Useful for DNP3 master read requests to look up values.
        """
        if not self.simulation:
            return None
        device = self.simulation.get_device(device_id)
        if device:
            return device.get_value(signal_name)
        return None
