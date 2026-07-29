"""
EtherNet/IP (CIP) Protocol Engine.

Implements an EtherNet/IP server using the Common Industrial Protocol (CIP)
object model. EtherNet/IP is an industrial network protocol that adapts CIP
to standard Ethernet. It is widely used in industrial automation and
manufacturing systems.

CIP Object Model:
- Each device is represented as a collection of CIP objects
- Objects are identified by Class ID, Instance ID, and Attribute ID
- Standard objects: Identity (0x01), Message Router (0x02),
  Assembly (0x04), Connection Manager (0x06)
- Device signals are mapped to Assembly object instances

Protocol Details:
- Transport: TCP (encapsulation layer)
- Default Port: 44818 (TCP)
- Uses CIP encapsulation protocol for session management
- Supports both explicit (request/response) and implicit (I/O) messaging
"""

from __future__ import annotations

import logging
import socket
import struct
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.core.device import Device, SimulationManager
from src.protocols.base import ProtocolConfig, ProtocolEngine, ProtocolState

logger = logging.getLogger(__name__)

# CIP Encapsulation Protocol constants
CIP_CMD_REGISTER_SESSION: int = 0x0065
CIP_CMD_UNREGISTER_SESSION: int = 0x0066
CIP_CMD_SEND_RR_DATA: int = 0x006F  # Send request/reply data
CIP_CMD_SEND_UNIT_DATA: int = 0x0070  # Send unit data (I/O)

# CIP Service codes
CIP_SERVICE_GET_ATTRIBUTE_ALL: int = 0x01
CIP_SERVICE_SET_ATTRIBUTE_SINGLE: int = 0x02
CIP_SERVICE_GET_ATTRIBUTE_SINGLE: int = 0x0E

# CIP Class IDs
CIP_CLASS_IDENTITY: int = 0x01
CIP_CLASS_MESSAGE_ROUTER: int = 0x02
CIP_CLASS_ASSEMBLY: int = 0x04
CIP_CLASS_CONNECTION_MANAGER: int = 0x06

# CIP Path sizes (in bytes)
CIP_PATH_SIZE: int = 4  # Class (2) + Instance (2)


@dataclass
class CipSession:
    """Represents an active CIP session."""

    session_id: int
    remote_addr: Tuple[str, int]
    created_at: float = 0.0
    last_active: float = 0.0


@dataclass
class CipAssemblyObject:
    """
    Represents a CIP Assembly object instance.

    Assembly objects group multiple signals into a single data structure
    for efficient I/O data exchange.
    """

    instance_id: int
    device_id: str
    signal_names: List[str] = field(default_factory=list)
    data: bytes = b""


class EthernetIpEngine(ProtocolEngine):
    """
    EtherNet/IP (CIP) protocol engine.

    Maps physics-backed device signals to CIP Assembly objects.
    Each device is represented as an Assembly object instance containing
    its signal values packed as IEEE 754 32-bit floats.

    Signal Mapping:
    - Analog signals -> 32-bit float values in Assembly data
    - Binary/Discrete signals -> 16-bit integer values in Assembly data
    - Each device gets a unique Assembly instance ID

    External Commands:
    - CIP SetAttributeSingle service on Assembly instances
    - Maps to device signal writes in the physics simulation
    """

    def __init__(
        self,
        name: str = "ethernetip",
        config: Optional[ProtocolConfig] = None,
        simulation: Optional[SimulationManager] = None,
        host: str = "0.0.0.0",
        port: int = 44818,
    ):
        super().__init__(name, config or ProtocolConfig(), simulation)
        self.host = host
        self.port = port
        self._server_socket: Optional[socket.socket] = None
        self._sessions: Dict[int, CipSession] = {}
        self._assembly_objects: Dict[int, CipAssemblyObject] = {}
        self._device_to_assembly: Dict[str, int] = {}
        self._next_session_id: int = 1
        self._next_instance_id: int = 1
        self._lock = threading.Lock()
        self._accept_thread: Optional[threading.Thread] = None

    @property
    def protocol_name(self) -> str:
        """Return the protocol name."""
        return "ethernetip"

    def _build_cip_path(self, class_id: int, instance_id: int) -> bytes:
        """Build a CIP path segment (class + instance)."""
        return struct.pack("<HH", class_id, instance_id)

    def _pack_assembly_data(self, device: Device) -> bytes:
        """
        Pack device signal values into Assembly data bytes.

        Analog signals are packed as 32-bit floats.
        Binary/discrete signals are packed as 16-bit integers.
        """
        data = b""
        for signal_name, state in device.signals.items():
            value = state.current_value
            profile = state.profile
            if profile.signal_type.value in ("binary", "discrete"):
                data += struct.pack("<H", int(value))
            else:
                data += struct.pack("<f", value)
        logger.debug(
            f"Packed assembly data for device '{device.device_id}': {len(data)} bytes"
        )
        return data

    def _unpack_assembly_data(
        self, data: bytes, device: Device
    ) -> Dict[str, float]:
        """
        Unpack Assembly data bytes back into signal values.

        Returns a dict mapping signal names to their unpacked values.
        """
        values: Dict[str, float] = {}
        offset = 0
        for signal_name, state in device.signals.items():
            profile = state.profile
            if offset >= len(data):
                logger.warning(
                    f"Assembly data truncated for signal '{signal_name}'"
                )
                break
            if profile.signal_type.value in ("binary", "discrete"):
                (val,) = struct.unpack_from("<H", data, offset)
                values[signal_name] = float(val)
                offset += 2
            else:
                (val,) = struct.unpack_from("<f", data, offset)
                values[signal_name] = val
                offset += 4
        logger.debug(
            f"Unpacked assembly data for device '{device.device_id}': {len(values)} values"
        )
        return values

    def _register_device_assembly(self, device: Device) -> int:
        """
        Register a device's signals as a CIP Assembly object.

        Returns the Assembly instance ID.
        """
        if device.device_id in self._device_to_assembly:
            return self._device_to_assembly[device.device_id]

        instance_id = self._next_instance_id
        self._next_instance_id += 1

        assembly = CipAssemblyObject(
            instance_id=instance_id,
            device_id=device.device_id,
            signal_names=list(device.signals.keys()),
            data=self._pack_assembly_data(device),
        )
        self._assembly_objects[instance_id] = assembly
        self._device_to_assembly[device.device_id] = instance_id

        logger.debug(
            f"Registered device '{device.device_id}' as CIP Assembly instance {instance_id} with {len(assembly.signal_names)} signals"
        )
        return instance_id

    def _handle_register_session(
        self, data: bytes, addr: Tuple[str, int]
    ) -> bytes:
        """Handle a CIP RegisterSession request."""
        with self._lock:
            session_id = self._next_session_id
            self._next_session_id += 1
            session = CipSession(
                session_id=session_id,
                remote_addr=addr,
            )
            self._sessions[session_id] = session

        logger.info(
            f"New CIP session {session_id} from {addr[0]}:{addr[1]}"
        )

        # Build response: session handle (4 bytes) + status (4 bytes)
        return struct.pack("<II", session_id, 0x0000_0000)

    def _handle_unregister_session(
        self, data: bytes, session_id: int
    ) -> bytes:
        """Handle a CIP UnregisterSession request."""
        with self._lock:
            self._sessions.pop(session_id, None)

        logger.info(f"CIP session {session_id} unregistered")
        return struct.pack("<I", 0x0000_0000)

    def _handle_send_rr_data(
        self, data: bytes, session_id: int
    ) -> Optional[bytes]:
        """
        Handle a CIP SendRRData request (explicit messaging).

        Parses the CIP request and dispatches to the appropriate
        service handler (GetAttributeSingle, SetAttributeSingle, etc.).
        """
        if len(data) < 6:
            logger.warning("CIP SendRRData: data too short")
            return None

        # Parse CIP request header
        service = data[0]
        path_size = data[1] * 2  # Path size in words -> bytes
        request_path = data[2 : 2 + path_size]

        logger.debug(
            f"CIP request: service=0x{service:02X}, path_size={path_size} bytes"
        )

        # Parse class and instance from path
        if path_size >= 4:
            class_id = struct.unpack_from("<H", request_path, 0)[0]
            instance_id = struct.unpack_from("<H", request_path, 2)[0]
        else:
            class_id = 0
            instance_id = 0

        # Service data starts after the path
        service_data = data[2 + path_size :]

        if service == CIP_SERVICE_GET_ATTRIBUTE_SINGLE:
            return self._handle_get_attribute_single(
                class_id, instance_id, service_data, session_id
            )
        elif service == CIP_SERVICE_GET_ATTRIBUTE_ALL:
            return self._handle_get_attribute_all(
                class_id, instance_id, session_id
            )
        elif service == CIP_SERVICE_SET_ATTRIBUTE_SINGLE:
            return self._handle_set_attribute_single(
                class_id, instance_id, service_data, session_id
            )
        else:
            logger.warning(
                f"Unsupported CIP service: 0x{service:02X}"
            )
            return self._build_cip_error_response(
                service, 0x08  # Service not supported
            )

    def _handle_get_attribute_single(
        self,
        class_id: int,
        instance_id: int,
        service_data: bytes,
        session_id: int,
    ) -> bytes:
        """Handle CIP GetAttributeSingle request."""
        logger.debug(
            f"GetAttributeSingle: class=0x{class_id:04X}, instance={instance_id}, session={session_id}"
        )

        if class_id == CIP_CLASS_ASSEMBLY:
            assembly = self._assembly_objects.get(instance_id)
            if not assembly:
                return self._build_cip_error_response(
                    CIP_SERVICE_GET_ATTRIBUTE_SINGLE, 0x06
                )

            # Return assembly data as the attribute value
            response = struct.pack(
                "<B", CIP_SERVICE_GET_ATTRIBUTE_SINGLE | 0x80
            )
            response += struct.pack("<H", len(assembly.data))
            response += assembly.data
            return response

        return self._build_cip_error_response(
            CIP_SERVICE_GET_ATTRIBUTE_SINGLE, 0x05
        )

    def _handle_get_attribute_all(
        self,
        class_id: int,
        instance_id: int,
        session_id: int,
    ) -> bytes:
        """Handle CIP GetAttributeAll request."""
        logger.debug(
            f"GetAttributeAll: class=0x{class_id:04X}, instance={instance_id}, session={session_id}"
        )

        if class_id == CIP_CLASS_IDENTITY and instance_id == 1:
            # Return Identity object attributes
            response = struct.pack(
                "<B", CIP_SERVICE_GET_ATTRIBUTE_ALL | 0x80
            )
            # Vendor ID (2) + Device Type (2) + Product Code (2) +
            # Revision (2) + Status (2) + Serial Number (4) +
            # Product Name (variable)
            vendor_id = 0x1234
            device_type = 0x000C  # Communications adapter
            product_code = 0x0001
            revision = struct.pack("<BB", 1, 0)  # Major, Minor
            status = 0x0000
            serial_number = struct.pack("<I", hash(self.name) & 0xFFFFFFFF)
            product_name = b"IndustrialCommSimulator"
            product_name_len = len(product_name)

            response += struct.pack(
                "<HHH", vendor_id, device_type, product_code
            )
            response += revision
            response += struct.pack("<H", status)
            response += serial_number
            response += struct.pack("<B", product_name_len)
            response += product_name
            return response

        return self._build_cip_error_response(
            CIP_SERVICE_GET_ATTRIBUTE_ALL, 0x05
        )

    def _handle_set_attribute_single(
        self,
        class_id: int,
        instance_id: int,
        service_data: bytes,
        session_id: int,
    ) -> bytes:
        """Handle CIP SetAttributeSingle request (external command)."""
        logger.debug(
            f"SetAttributeSingle: class=0x{class_id:04X}, instance={instance_id}, session={session_id}"
        )

        if class_id == CIP_CLASS_ASSEMBLY:
            assembly = self._assembly_objects.get(instance_id)
            if not assembly:
                return self._build_cip_error_response(
                    CIP_SERVICE_SET_ATTRIBUTE_SINGLE, 0x06
                )

            # Parse attribute data
            if len(service_data) < 3:
                return self._build_cip_error_response(
                    CIP_SERVICE_SET_ATTRIBUTE_SINGLE, 0x07
                )

            attribute_id = service_data[0]
            data_length = struct.unpack_from("<H", service_data, 1)[0]
            attribute_data = service_data[3 : 3 + data_length]

            # Update device signals from assembly data
            device = self.simulation.get_device(assembly.device_id) if self.simulation else None
            if device:
                values = self._unpack_assembly_data(attribute_data, device)
                for signal_name, value in values.items():
                    self.handle_command(
                        assembly.device_id, signal_name, value
                    )
                logger.info(
                    f"CIP SetAttributeSingle: updated {assembly.device_id} with {len(values)} values"
                )

            # Build success response
            response = struct.pack(
                "<B", CIP_SERVICE_SET_ATTRIBUTE_SINGLE | 0x80
            )
            return response

        return self._build_cip_error_response(
            CIP_SERVICE_SET_ATTRIBUTE_SINGLE, 0x05
        )

    def _build_cip_error_response(
        self, service: int, error_code: int
    ) -> bytes:
        """Build a CIP error response."""
        response = struct.pack("<B", service | 0x80)
        response += struct.pack("<H", error_code)
        response += struct.pack("<B", 0x00)  # Additional code
        logger.debug(
            f"CIP error response: service=0x{service:02X}, code=0x{error_code:04X}"
        )
        return response

    def _build_encapsulation_header(
        self,
        command: int,
        session_id: int,
        data: bytes,
        status: int = 0x0000_0000,
    ) -> bytes:
        """Build a CIP encapsulation header."""
        length = len(data)
        header = struct.pack(
            "<HHIIII",
            command,       # Command code
            length,        # Length of data
            session_id,    # Session handle
            status,        # Status
            0,             # Sender context (8 bytes, zeroed)
            0,
            0,             # Options
        )
        return header + data

    def _parse_encapsulation_header(
        self, data: bytes
    ) -> Optional[Dict[str, Any]]:
        """Parse a CIP encapsulation header."""
        if len(data) < 24:
            return None

        command, length, session_id, status, ctx1, ctx2, options = (
            struct.unpack_from("<HHIIIII", data, 0)
        )

        return {
            "command": command,
            "length": length,
            "session_id": session_id,
            "status": status,
            "sender_context": (ctx1, ctx2),
            "options": options,
        }

    def _handle_client(self, client_socket: socket.socket, addr: Tuple[str, int]) -> None:
        """Handle a single CIP client connection."""
        logger.info(f"CIP client connected: {addr[0]}:{addr[1]}")
        session_id = 0

        try:
            while True:
                # Read encapsulation header (24 bytes)
                header_data = client_socket.recv(24)
                if not header_data or len(header_data) < 24:
                    break

                header = self._parse_encapsulation_header(header_data)
                if not header:
                    logger.warning(f"Invalid CIP header from {addr}")
                    break

                command = header["command"]
                length = header["length"]
                session_id = header["session_id"]

                logger.debug(
                    f"CIP packet: command=0x{command:04X}, length={length}, session={session_id}"
                )

                # Read the command-specific data
                if length > 0:
                    cmd_data = client_socket.recv(length)
                else:
                    cmd_data = b""

                # Dispatch command
                if command == CIP_CMD_REGISTER_SESSION:
                    response_data = self._handle_register_session(
                        cmd_data, addr
                    )
                    # Extract new session ID from response
                    new_session = struct.unpack_from(
                        "<I", response_data, 0
                    )[0]
                    session_id = new_session
                elif command == CIP_CMD_UNREGISTER_SESSION:
                    response_data = self._handle_unregister_session(
                        cmd_data, session_id
                    )
                elif command == CIP_CMD_SEND_RR_DATA:
                    result = self._handle_send_rr_data(
                        cmd_data, session_id
                    )
                    if result is None:
                        continue
                    response_data = result
                else:
                    logger.warning(
                        f"Unsupported CIP command: 0x{command:04X}"
                    )
                    continue

                # Send response
                response = self._build_encapsulation_header(
                    command, session_id, response_data
                )
                client_socket.sendall(response)

        except ConnectionResetError:
            logger.debug(f"CIP client {addr} reset connection")
        except Exception as e:
            logger.error(f"CIP client handler error for {addr}: {e}")
        finally:
            with self._lock:
                self._sessions.pop(session_id, None)
            client_socket.close()
            logger.info(f"CIP client disconnected: {addr[0]}:{addr[1]}")

    def _start_engine(self) -> None:
        """Start the EtherNet/IP TCP server."""
        self._server_socket = socket.socket(
            socket.AF_INET, socket.SOCK_STREAM
        )
        self._server_socket.setsockopt(
            socket.SOL_SOCKET, socket.SO_REUSEADDR, 1
        )
        self._server_socket.bind((self.host, self.port))
        self._server_socket.listen(5)
        self._server_socket.settimeout(1.0)

        logger.info(
            f"EtherNet/IP server listening on {self.host}:{self.port}"
        )

        # Start accept thread
        self._accept_thread = threading.Thread(
            target=self._accept_loop,
            name=f"{self.name}-accept",
            daemon=True,
        )
        self._accept_thread.start()

    def _accept_loop(self) -> None:
        """Accept incoming CIP connections."""
        while self._running:
            try:
                client_socket, addr = self._server_socket.accept()
                client_thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_socket, addr),
                    name=f"{self.name}-client-{addr[0]}:{addr[1]}",
                    daemon=True,
                )
                client_thread.start()
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    logger.error(f"Accept error: {e}")

    def _stop_engine(self) -> None:
        """Stop the EtherNet/IP TCP server."""
        self._running = False
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception as e:
                logger.error(f"Error closing server socket: {e}")
        with self._lock:
            self._sessions.clear()
        logger.info("EtherNet/IP server stopped")

    def _publish_device_values(self, device: Device) -> None:
        """Publish device signal values to CIP Assembly objects."""
        instance_id = self._register_device_assembly(device)
        assembly = self._assembly_objects.get(instance_id)
        if not assembly:
            return

        # Update assembly data with current signal values
        assembly.data = self._pack_assembly_data(device)

        logger.debug(
            f"Published device '{device.device_id}' to CIP Assembly instance {instance_id}: {len(assembly.data)} bytes"
        )

    def _handle_external_command(
        self, device_id: str, signal_name: str, value: float
    ) -> None:
        """Handle an external CIP write command."""
        logger.info(
            f"CIP external command: {device_id}.{signal_name} = {value}"
        )
        # The value is already set in the simulation by handle_command()
        # This hook allows protocol-specific side effects (e.g., updating
        # the assembly data immediately)
        instance_id = self._device_to_assembly.get(device_id)
        if instance_id is not None:
            assembly = self._assembly_objects.get(instance_id)
            if assembly and self.simulation:
                device = self.simulation.get_device(device_id)
                if device:
                    assembly.data = self._pack_assembly_data(device)
                    logger.debug(
                        f"Updated assembly {instance_id} data after external command"
                    )
