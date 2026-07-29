"""
PROFINET Protocol Engine.

Implements a PROFINET IO device simulator using the PROFINET IO device model.
PROFINET is the open Industrial Ethernet standard for automation, developed
by PROFIBUS & PROFINET International (PI). It uses a provider-consumer model
for cyclic data exchange.

PROFINET IO Device Model:
- Device Access Point (DAP): Represents the physical device
- Slots: Physical or logical slots for modules
- Subslots: Individual data channels within a slot
- Modules: Functional units plugged into slots
- I/O Data Objects (IODOs): The actual process data values
- API (Application Process Identifier): Groups related functionality

Protocol Details:
- Transport: UDP (Real-Time / RT) and TCP (Context Management / CM)
- Default Port: 34964 (UDP) for RT data, 34963 (TCP) for CM
- Uses DCE/RPC for connection establishment (CM)
- Cyclic data exchange via UDP multicast/broadcast
- Supports isochronous real-time (IRT) for motion control

Signal Mapping:
- Analog signals -> IODOs in subslots (32-bit float)
- Binary/Discrete signals -> IODOs in subslots (8-bit boolean)
- Each device maps to a PROFINET IO device with configurable slots
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

# PROFINET IO constants
PNIO_ETHERTYPE: int = 0x8892  # PROFINET EtherType
PNIO_FRAME_ID_RT: int = 0x8000  # RT frame ID base
PNIO_FRAME_ID_RTC: int = 0xC000  # RTC (cyclic) frame ID base
PNIO_FRAME_ID_ALARM: int = 0xFC01  # Alarm frame ID
PNIO_FRAME_ID_DCP: int = 0xFEFE  # Discovery and Configuration Protocol

# DCP service IDs
DCP_SERVICE_ID_IDENTIFY: int = 0x05
DCP_SERVICE_ID_SET: int = 0x04
DCP_SERVICE_ID_GET: int = 0x03

# DCP service types
DCP_SERVICE_TYPE_REQUEST: int = 0x00
DCP_SERVICE_TYPE_RESPONSE_SUCCESS: int = 0x01
DCP_SERVICE_TYPE_RESPONSE_FAILURE: int = 0x05

# Default slot/subslot configuration
DEFAULT_DAP_SLOT: int = 0
DEFAULT_DAP_SUBSLOT: int = 0x8000
DEFAULT_APP_SUBSLOT: int = 0x0001


@dataclass
class PnIoSubslot:
    """Represents a PROFINET IO subslot with I/O data for a data channel."""

    slot: int
    subslot: int
    device_id: str
    signal_name: str
    data_type: str  # "float32", "uint16", "uint8", "boolean"
    input_data: bytes = b""
    output_data: bytes = b""


@dataclass
class PnIoDevice:
    """Represents a PROFINET IO device configuration with slot/subslot mapping."""

    device_id: str
    name: str
    subslots: Dict[Tuple[int, int], PnIoSubslot] = field(default_factory=dict)
    data_cycle_counter: int = 0


class ProfinetEngine(ProtocolEngine):
    """
    PROFINET IO protocol engine.

    Maps physics-backed device signals to PROFINET IO subslots.
    Each device signal is represented as an IOD (I/O Data) object
    in a specific slot/subslot combination.

    Signal Mapping:
    - Analog signals -> 32-bit float IODOs in subslots
    - Binary/Discrete signals -> 8-bit boolean IODOs in subslots
    - Each device gets a unique set of slots/subslots

    External Commands:
    - PROFINET IO output data writes from IO Controller
    - DCP Set requests for device configuration
    - Maps to device signal writes in the physics simulation
    """

    def __init__(
        self,
        name: str = "profinet",
        config: Optional[ProtocolConfig] = None,
        simulation: Optional[SimulationManager] = None,
        host: str = "0.0.0.0",
        port: int = 34964,
        station_name: str = "ics-profinet-device",
        vendor_id: str = "0x1234",
        device_id: str = "0x0001",
    ):
        super().__init__(name, config or ProtocolConfig(), simulation)
        self.host = host
        self.port = port
        self.station_name = station_name
        self.vendor_id = vendor_id
        self.device_id = device_id

        self._udp_socket: Optional[socket.socket] = None
        self._pn_devices: Dict[str, PnIoDevice] = {}
        self._subslot_to_device: Dict[Tuple[int, int], str] = {}
        self._next_slot: int = 1
        self._lock = threading.Lock()
        self._running: bool = False

    @property
    def protocol_name(self) -> str:
        """Return the protocol name."""
        return "profinet"

    def _register_device_subslots(self, device: Device) -> PnIoDevice:
        """Register a device's signals as PROFINET IO subslots."""
        if device.device_id in self._pn_devices:
            return self._pn_devices[device.device_id]

        slot = self._next_slot
        self._next_slot += 1

        pn_device = PnIoDevice(device_id=device.device_id, name=device.name)

        for idx, (signal_name, state) in enumerate(device.signals.items()):
            profile = state.profile
            subslot = idx + 1

            if profile.signal_type.value in ("binary", "discrete"):
                data_type = "boolean"
                data_size = 1
            else:
                data_type = "float32"
                data_size = 4

            pn_subslot = PnIoSubslot(
                slot=slot,
                subslot=subslot,
                device_id=device.device_id,
                signal_name=signal_name,
                data_type=data_type,
                input_data=b"\x00" * data_size,
                output_data=b"\x00" * data_size,
            )
            pn_device.subslots[(slot, subslot)] = pn_subslot
            self._subslot_to_device[(slot, subslot)] = device.device_id

        self._pn_devices[device.device_id] = pn_device

        logger.debug(
            f"Registered device '{device.device_id}' as PROFINET IO device with {len(pn_device.subslots)} subslots in slot {slot}"
        )
        return pn_device

    def _pack_subslot_data(self, device: Device, subslot: PnIoSubslot) -> bytes:
        """Pack a signal value into subslot data bytes."""
        state = device.get_signal(subslot.signal_name)
        if state is None:
            return subslot.input_data

        value = state.current_value

        if subslot.data_type == "float32":
            data = struct.pack("<f", value)
        elif subslot.data_type == "boolean":
            data = struct.pack("<?", bool(value))
        elif subslot.data_type == "uint16":
            data = struct.pack("<H", int(value))
        elif subslot.data_type == "uint8":
            data = struct.pack("<B", int(value))
        else:
            data = struct.pack("<f", value)

        logger.debug(
            f"Packed subslot ({subslot.slot}, {subslot.subslot}) data: {len(data)} bytes"
        )
        return data

    def _unpack_subslot_data(self, subslot: PnIoSubslot, data: bytes) -> Optional[float]:
        """Unpack subslot data bytes back into a signal value."""
        if not data:
            return None

        try:
            if subslot.data_type == "float32" and len(data) >= 4:
                (value,) = struct.unpack_from("<f", data, 0)
            elif subslot.data_type == "boolean" and len(data) >= 1:
                (value,) = struct.unpack_from("<?", data, 0)
                value = float(value)
            elif subslot.data_type == "uint16" and len(data) >= 2:
                (value,) = struct.unpack_from("<H", data, 0)
            elif subslot.data_type == "uint8" and len(data) >= 1:
                (value,) = struct.unpack_from("<B", data, 0)
            else:
                value = 0.0

            logger.debug(f"Unpacked subslot ({subslot.slot}, {subslot.subslot}) data: {value}")
            return float(value)
        except struct.error as e:
            logger.error(f"Failed to unpack subslot data: {e}")
            return None

    def _build_rt_frame(self, frame_id: int, data: bytes) -> bytes:
        """Build a PROFINET RT (Real-Time) frame."""
        frame = struct.pack("<H", frame_id)
        frame += data
        return frame

    def _parse_rt_frame(self, data: bytes) -> Optional[Dict[str, Any]]:
        """Parse a PROFINET RT frame."""
        if len(data) < 2:
            return None
        frame_id = struct.unpack_from("<H", data, 0)[0]
        payload = data[2:]
        return {"frame_id": frame_id, "payload": payload}

    def _build_dcp_identify_response(self, request_data: bytes, addr: Tuple[str, int]) -> bytes:
        """Build a DCP Identify response for device discovery."""
        if len(request_data) < 10:
            return b""

        service_id = request_data[0]
        xid = struct.unpack_from("<I", request_data, 2)[0]

        response = struct.pack("<BB", service_id, DCP_SERVICE_TYPE_RESPONSE_SUCCESS)
        response += struct.pack("<I", xid)
        response += struct.pack("<HH", 0, 0)

        blocks = b""
        ip_block = self._build_dcp_ip_block(addr)
        blocks += ip_block
        options_block = self._build_dcp_options_block()
        blocks += options_block

        data_length = len(blocks)
        response = response[:8] + struct.pack("<H", data_length) + response[10:]
        response += blocks

        logger.debug(f"Built DCP Identify response for {addr[0]}:{addr[1]} ({len(response)} bytes)")
        return response

    def _build_dcp_ip_block(self, addr: Tuple[str, int]) -> bytes:
        """Build a DCP IP parameter block."""
        block = struct.pack("<BBH", 0x01, 0x02, 12)
        ip_parts = [int(x) for x in addr[0].split(".")]
        block += struct.pack("<BBBB", ip_parts[0], ip_parts[1], ip_parts[2], ip_parts[3])
        block += struct.pack("<BBBB", 255, 255, 255, 0)
        block += struct.pack("<BBBB", ip_parts[0], ip_parts[1], ip_parts[2], 1)
        return block

    def _build_dcp_options_block(self) -> bytes:
        """Build a DCP device options block."""
        blocks = b""
        station_name_bytes = self.station_name.encode("utf-8")
        blocks += struct.pack("<BBH", 0x02, 0x02, len(station_name_bytes))
        blocks += station_name_bytes
        vendor_id_int = int(self.vendor_id, 16)
        blocks += struct.pack("<BBH", 0x03, 0x01, 2)
        blocks += struct.pack("<H", vendor_id_int)
        device_id_int = int(self.device_id, 16)
        blocks += struct.pack("<BBH", 0x03, 0x02, 2)
        blocks += struct.pack("<H", device_id_int)
        blocks += struct.pack("<BBH", 0x03, 0x0A, 2)
        blocks += struct.pack("<H", 0x0002)
        return blocks

    def _handle_dcp_set(self, data: bytes, addr: Tuple[str, int]) -> bytes:
        """Handle a DCP Set request (device configuration)."""
        if len(data) < 10:
            return b""
        service_id = data[0]
        xid = struct.unpack_from("<I", data, 2)[0]
        logger.info(f"DCP Set request from {addr[0]}:{addr[1]}, service=0x{service_id:02X}, xid=0x{xid:08X}")
        response = struct.pack("<BB", service_id, DCP_SERVICE_TYPE_RESPONSE_SUCCESS)
        response += struct.pack("<I", xid)
        response += struct.pack("<HH", 0, 0)
        return response

    def _handle_rt_data(self, frame: Dict[str, Any], addr: Tuple[str, int]) -> None:
        """Handle incoming PROFINET RT data (output data from controller)."""
        frame_id = frame["frame_id"]
        payload = frame["payload"]
        logger.debug(f"RT data frame: id=0x{frame_id:04X}, {len(payload)} bytes from {addr[0]}:{addr[1]}")

        if frame_id >= PNIO_FRAME_ID_RTC:
            self._handle_rtc_data(frame_id, payload)
        elif frame_id == PNIO_FRAME_ID_ALARM:
            logger.debug("Received PROFINET alarm frame")
        else:
            logger.debug(f"Unhandled RT frame: 0x{frame_id:04X}")

    def _handle_rtc_data(self, frame_id: int, payload: bytes) -> None:
        """Handle RTC (Real-Time Cyclic) data from the IO Controller."""
        offset = 0
        data_cycle_counter = 0

        if len(payload) >= 2:
            data_cycle_counter = struct.unpack_from("<H", payload, 0)[0]
            offset += 2

        while offset < len(payload):
            if offset + 4 > len(payload):
                break

            slot = struct.unpack_from("<H", payload, offset)[0]
            subslot = struct.unpack_from("<H", payload, offset + 2)[0]
            offset += 4

            key = (slot, subslot)
            device_id = self._subslot_to_device.get(key)
            if not device_id:
                logger.warning(f"No device found for subslot ({slot}, {subslot})")
                continue

            pn_device = self._pn_devices.get(device_id)
            if not pn_device:
                continue

            pn_subslot = pn_device.subslots.get(key)
            if not pn_subslot:
                continue

            data_size = len(payload) - offset
            if data_size <= 0:
                break

            iod_data = payload[offset : offset + data_size]
            pn_subslot.output_data = iod_data

            value = self._unpack_subslot_data(pn_subslot, iod_data)
            if value is not None:
                self.handle_command(device_id, pn_subslot.signal_name, value)
                logger.debug(f"RTC output: {device_id}.{pn_subslot.signal_name} = {value} (cycle={data_cycle_counter})")

            offset += data_size

    def _handle_dcp_frame(self, data: bytes, addr: Tuple[str, int]) -> Optional[bytes]:
        """Handle a DCP (Discovery and Configuration Protocol) frame."""
        if len(data) < 10:
            return None

        service_id = data[0]
        service_type = data[1]

        logger.debug(f"DCP frame: service=0x{service_id:02X}, type=0x{service_type:02X} from {addr[0]}:{addr[1]}")

        if service_type == DCP_SERVICE_TYPE_REQUEST:
            if service_id == DCP_SERVICE_ID_IDENTIFY:
                return self._build_dcp_identify_response(data, addr)
            elif service_id == DCP_SERVICE_ID_SET:
                return self._handle_dcp_set(data, addr)

        return None

    def _start_engine(self) -> None:
        """Start the PROFINET IO UDP server."""
        self._udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._udp_socket.bind((self.host, self.port))
        self._udp_socket.settimeout(1.0)

        logger.info(f"PROFINET IO device listening on {self.host}:{self.port} (station_name={self.station_name})")

    def _stop_engine(self) -> None:
        """Stop the PROFINET IO UDP server."""
        if self._udp_socket:
            try:
                self._udp_socket.close()
            except Exception as e:
                logger.error(f"Error closing UDP socket: {e}")
        with self._lock:
            self._pn_devices.clear()
            self._subslot_to_device.clear()
        logger.info("PROFINET IO device stopped")

    def _publish_device_values(self, device: Device) -> None:
        """Publish device signal values as PROFINET IO input data."""
        pn_device = self._register_device_subslots(device)

        for subslot in pn_device.subslots.values():
            subslot.input_data = self._pack_subslot_data(device, subslot)

        if self._udp_socket:
            pn_device.data_cycle_counter += 1
            frame_data = struct.pack("<H", pn_device.data_cycle_counter & 0xFFFF)

            for subslot in pn_device.subslots.values():
                frame_data += struct.pack("<HH", subslot.slot, subslot.subslot)
                frame_data += subslot.input_data

            frame_id = PNIO_FRAME_ID_RTC + pn_device.data_cycle_counter % 256
            rt_frame = self._build_rt_frame(frame_id, frame_data)

            try:
                self._udp_socket.sendto(rt_frame, ("<broadcast>", self.port))
                logger.debug(
                    f"Published {len(rt_frame)} bytes for device '{device.device_id}' (cycle={pn_device.data_cycle_counter})"
                )
            except Exception as e:
                logger.error(f"Failed to publish RT frame: {e}")

    def _handle_external_command(self, device_id: str, signal_name: str, value: float) -> None:
        """Handle an external PROFINET IO write command."""
        logger.info(f"PROFINET external command: {device_id}.{signal_name} = {value}")
        pn_device = self._pn_devices.get(device_id)
        if pn_device:
            for subslot in pn_device.subslots.values():
                if subslot.signal_name == signal_name:
                    device = self.simulation.get_device(device_id) if self.simulation else None
                    if device:
                        subslot.output_data = self._pack_subslot_data(device, subslot)
                        logger.debug(f"Updated subslot ({subslot.slot}, {subslot.subslot}) output data")
                    break

    def _update(self) -> None:
        """Update the PROFINET engine - listen for incoming packets and publish values."""
        if self._udp_socket:
            try:
                data, addr = self._udp_socket.recvfrom(65535)
                self._handle_incoming_packet(data, addr)
            except socket.timeout:
                pass
            except Exception as e:
                logger.error(f"Error receiving UDP packet: {e}")

        super()._update()

    def _handle_incoming_packet(self, data: bytes, addr: Tuple[str, int]) -> None:
        """Handle an incoming PROFINET packet."""
        if len(data) < 2:
            return

        first_word = struct.unpack_from("<H", data, 0)[0]

        if first_word in (DCP_SERVICE_ID_IDENTIFY, DCP_SERVICE_ID_SET, DCP_SERVICE_ID_GET):
            response = self._handle_dcp_frame(data, addr)
            if response and self._udp_socket:
                self._udp_socket.sendto(response, addr)
                logger.debug(f"Sent DCP response to {addr[0]}:{addr[1]} ({len(response)} bytes)")
        else:
            frame = self._parse_rt_frame(data)
            if frame:
                self._handle_rt_data(frame, addr)
