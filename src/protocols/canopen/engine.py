"""
CANopen Protocol Engine.

Implements a CANopen device simulator using the CANopen object dictionary
model. CANopen is a communication protocol and device profile specification
based on CAN (Controller Area Network), widely used in embedded systems,
automation, and motion control.

CANopen Object Dictionary Model:
- Object Dictionary (OD): Central data structure indexed by 16-bit keys
- Index (0x0000-0xFFFF): Groups related objects by function
- Subindex (0x00-0xFF): Individual entries within an index
- Standardized index ranges:
  - 0x1000-0x1FFF: Communication profile area (device control, status)
  - 0x2000-0x5FFF: Manufacturer-specific profile area
  - 0x6000-0x9FFF: Standardized device profile area
- PDO (Process Data Object): Real-time data exchange (1-8 bytes)
- SDO (Service Data Object): Configuration/parameter access
- NMT (Network Management): State machine (Pre-operational, Operational, Stopped)

Protocol Details:
- Transport: CAN bus (CAN 2.0A with 11-bit identifiers)
- Default Port: N/A (uses CAN bus interface, e.g., SocketCAN)
- COB-ID (Communication Object Identifier): 11-bit CAN identifier
- Supports up to 127 nodes on a single CAN bus
- Heartbeat protocol for node monitoring
- Emergency messages for error reporting

Signal Mapping:
- Analog signals -> Manufacturer-specific OD entries (0x2000-0x5FFF)
- Binary/Discrete signals -> OD entries with appropriate data types
- Each device signal maps to a unique OD index + subindex
- PDO mapping for cyclic data exchange
"""

from __future__ import annotations

import logging
import struct
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from src.core.device import Device, SimulationManager
from src.protocols.base import ProtocolConfig, ProtocolEngine

logger = logging.getLogger(__name__)

# CANopen COB-ID base identifiers
COB_ID_NMT: int = 0x000  # Network Management
COB_ID_SYNC: int = 0x080  # Synchronization
COB_ID_EMERGENCY: int = 0x080  # Emergency (node-specific: 0x080 + node_id)
COB_ID_TSDO: int = 0x580  # Transmit SDO (node-specific: 0x580 + node_id)
COB_ID_RSDO: int = 0x600  # Receive SDO (node-specific: 0x600 + node_id)
COB_ID_TPDO1: int = 0x180  # Transmit PDO 1 (node-specific: 0x180 + node_id)
COB_ID_RPDO1: int = 0x200  # Receive PDO 1 (node-specific: 0x200 + node_id)
COB_ID_HEARTBEAT: int = 0x700  # Heartbeat (node-specific: 0x700 + node_id)

# CANopen NMT command specifiers
NMT_CMD_START_REMOTE_NODE: int = 0x01
NMT_CMD_STOP_REMOTE_NODE: int = 0x02
NMT_CMD_ENTER_PRE_OPERATIONAL: int = 0x80
NMT_CMD_RESET_NODE: int = 0x81
NMT_CMD_RESET_COMMUNICATION: int = 0x82

# CANopen NMT states
NMT_STATE_BOOTUP: int = 0x00
NMT_STATE_STOPPED: int = 0x04
NMT_STATE_OPERATIONAL: int = 0x05
NMT_STATE_PRE_OPERATIONAL: int = 0x7F

# CANopen SDO command specifiers
SDO_CMD_UPLOAD_REQ: int = 0x40  # Initiate upload request
SDO_CMD_UPLOAD_RESP: int = 0x42  # Initiate upload response
SDO_CMD_DOWNLOAD_REQ: int = 0x21  # Initiate download request
SDO_CMD_DOWNLOAD_RESP: int = 0x60  # Initiate download response
SDO_CMD_ABORT: int = 0x80  # Abort transfer

# CANopen SDO abort codes
SDO_ABORT_NO_SUCH_OBJECT: int = 0x06020000
SDO_ABORT_UNSUPPORTED_ACCESS: int = 0x06010000
SDO_ABORT_OUT_OF_MEMORY: int = 0x06040000
SDO_ABORT_GENERAL_ERROR: int = 0x08000000

# Object Dictionary index ranges
OD_COMMUNICATION_START: int = 0x1000
OD_COMMUNICATION_END: int = 0x1FFF
OD_MANUFACTURER_START: int = 0x2000
OD_MANUFACTURER_END: int = 0x5FFF
OD_DEVICE_PROFILE_START: int = 0x6000
OD_DEVICE_PROFILE_END: int = 0x9FFF

# Standard communication profile entries
OD_DEVICE_TYPE: int = 0x1000
OD_ERROR_REGISTER: int = 0x1001
OD_MANUFACTURER_DEVICE_NAME: int = 0x1008
OD_MANUFACTURER_HARDWARE_VERSION: int = 0x1009
OD_MANUFACTURER_SOFTWARE_VERSION: int = 0x100A
OD_STORE_PARAMETERS: int = 0x1010
OD_RESTORE_PARAMETERS: int = 0x1011
OD_COB_ID_SYNC: int = 0x1005
OD_HEARTBEAT_TIME: int = 0x1017
OD_IDENTITY_OBJECT: int = 0x1018

# Data type constants
ODT_BOOLEAN: int = 0x01
ODT_INTEGER8: int = 0x02
ODT_INTEGER16: int = 0x03
ODT_INTEGER32: int = 0x04
ODT_UNSIGNED8: int = 0x05
ODT_UNSIGNED16: int = 0x06
ODT_UNSIGNED32: int = 0x07
ODT_REAL32: int = 0x08
ODT_VISIBLE_STRING: int = 0x09
ODT_OCTET_STRING: int = 0x0A


@dataclass
class OdEntry:
    """
    Represents a single entry in the CANopen Object Dictionary.

    Each entry is identified by an index and subindex, and contains
    a value with associated metadata (data type, access rights, etc.).
    """

    index: int
    subindex: int
    name: str
    data_type: int
    value: Any = 0
    access: str = "rw"  # "ro", "wo", "rw", "const"
    description: str = ""
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    default_value: Any = 0


@dataclass
class PdoMapping:
    """
    Represents a PDO (Process Data Object) mapping.

    Maps OD entries to PDO data for cyclic real-time communication.
    """

    pdo_number: int  # 1-4 for TPDO/RPDO
    is_transmit: bool  # True = TPDO, False = RPDO
    cob_id: int
    transmission_type: int = 255  # 255 = async, 1-240 = cyclic
    inhibit_time: int = 0
    event_timer: int = 0
    mapped_entries: List[Tuple[int, int]] = field(default_factory=list)
    # List of (index, subindex) tuples


class CanopenEngine(ProtocolEngine):
    """
    CANopen protocol engine.

    Maps physics-backed device signals to CANopen Object Dictionary entries
    in the manufacturer-specific range (0x2000-0x5FFF). Each device signal
    is represented as an OD entry with appropriate data type and access
    rights.

    Signal Mapping:
    - Analog signals -> OD entries with REAL32 data type (0x08)
    - Binary/Discrete signals -> OD entries with BOOLEAN data type (0x01)
    - Sensor signals -> Read-only OD entries (ro)
    - Actuator signals -> Read-Write OD entries (rw)
    - Each signal gets a unique index in the 0x2000-0x5FFF range

    External Commands:
    - SDO download requests (write to OD entries)
    - RPDO (Receive PDO) data frames
    - Maps to device signal writes in the physics simulation
    """

    def __init__(
        self,
        name: str = "canopen",
        config: Optional[ProtocolConfig] = None,
        simulation: Optional[SimulationManager] = None,
        node_id: int = 1,
        can_interface: str = "vcan0",
        use_socketcan: bool = False,
    ):
        super().__init__(name, config or ProtocolConfig(), simulation)
        self.node_id = node_id
        self.can_interface = can_interface
        self.use_socketcan = use_socketcan

        # CANopen state
        self._nmt_state: int = NMT_STATE_PRE_OPERATIONAL
        self._object_dictionary: Dict[int, Dict[int, OdEntry]] = {}
        self._pdo_mappings: Dict[int, PdoMapping] = {}
        self._signal_to_od: Dict[str, Tuple[int, int]] = {}
        self._next_manufacturer_index: int = OD_MANUFACTURER_START
        self._lock = threading.Lock()
        self._can_socket: Any = None

    @property
    def protocol_name(self) -> str:
        """Return the protocol name."""
        return "canopen"

    def _add_od_entry(
        self,
        index: int,
        subindex: int,
        name: str,
        data_type: int,
        value: Any = 0,
        access: str = "rw",
        description: str = "",
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
    ) -> None:
        """Add an entry to the Object Dictionary."""
        if index not in self._object_dictionary:
            self._object_dictionary[index] = {}

        entry = OdEntry(
            index=index,
            subindex=subindex,
            name=name,
            data_type=data_type,
            value=value,
            access=access,
            description=description,
            min_value=min_value,
            max_value=max_value,
            default_value=value,
        )
        self._object_dictionary[index][subindex] = entry

        logger.debug(
            f"Added OD entry: 0x{index:04X}:{subindex:02X} '{name}' (type={data_type}, access={access})"
        )

    def _init_communication_profile(self) -> None:
        """Initialize the standard communication profile area (0x1000-0x1FFF)."""
        # Device type (0x1000)
        self._add_od_entry(
            OD_DEVICE_TYPE, 0x00, "Device Type", ODT_UNSIGNED32,
            value=0x00000000, access="ro",
            description="Device type and profile number",
        )

        # Error register (0x1001)
        self._add_od_entry(
            OD_ERROR_REGISTER, 0x00, "Error Register", ODT_UNSIGNED8,
            value=0x00, access="ro",
            description="Error register (bit field)",
        )

        # Manufacturer device name (0x1008)
        self._add_od_entry(
            OD_MANUFACTURER_DEVICE_NAME, 0x00, "Manufacturer Device Name",
            ODT_VISIBLE_STRING, value="IndustrialCommSimulator", access="ro",
            description="Manufacturer device name",
        )

        # Hardware version (0x1009)
        self._add_od_entry(
            OD_MANUFACTURER_HARDWARE_VERSION, 0x00, "Hardware Version",
            ODT_VISIBLE_STRING, value="1.0", access="ro",
            description="Hardware version",
        )

        # Software version (0x100A)
        self._add_od_entry(
            OD_MANUFACTURER_SOFTWARE_VERSION, 0x00, "Software Version",
            ODT_VISIBLE_STRING, value="1.0.0", access="ro",
            description="Software version",
        )

        # Heartbeat time (0x1017)
        self._add_od_entry(
            OD_HEARTBEAT_TIME, 0x00, "Heartbeat Time", ODT_UNSIGNED16,
            value=1000, access="rw",  # 1000 ms
            description="Heartbeat producer time in ms",
        )

        # Identity object (0x1018)
        self._add_od_entry(
            OD_IDENTITY_OBJECT, 0x00, "Identity Object", ODT_UNSIGNED8,
            value=4, access="ro", description="Number of subentries",
        )
        self._add_od_entry(
            OD_IDENTITY_OBJECT, 0x01, "Vendor ID", ODT_UNSIGNED32,
            value=0x00001234, access="ro",
            description="Vendor ID (assigned by CiA)",
        )
        self._add_od_entry(
            OD_IDENTITY_OBJECT, 0x02, "Product Code", ODT_UNSIGNED32,
            value=0x00000001, access="ro",
            description="Product code",
        )
        self._add_od_entry(
            OD_IDENTITY_OBJECT, 0x03, "Revision Number", ODT_UNSIGNED32,
            value=0x00010000, access="ro",
            description="Revision number (major.minor)",
        )
        self._add_od_entry(
            OD_IDENTITY_OBJECT, 0x04, "Serial Number", ODT_UNSIGNED32,
            value=0x00000001, access="ro",
            description="Serial number",
        )

        logger.debug("Initialized CANopen communication profile (0x1000-0x1FFF)")

    def _map_device_to_od(self, device: Device) -> None:
        """
        Map a device's signals to Object Dictionary entries.

        Each signal is assigned a unique index in the manufacturer-specific
        range (0x2000-0x5FFF). The subindex 0x00 stores the number of
        subentries, and subindex 0x01+ stores individual signal values.
        """
        if device.device_id in self._signal_to_od:
            return

        device_index = self._next_manufacturer_index
        self._next_manufacturer_index += 1

        if device_index > OD_MANUFACTURER_END:
            logger.error("Out of manufacturer-specific OD indices!")
            return

        # Add device entry with number of signals as subindex 0
        num_signals = len(device.signals)
        self._add_od_entry(
            device_index, 0x00, f"Device: {device.device_id}",
            ODT_UNSIGNED8, value=num_signals, access="ro",
            description=f"Number of signals for device '{device.device_id}'",
        )

        # Map each signal to a subindex
        for idx, (signal_name, state) in enumerate(device.signals.items()):
            subindex = idx + 1
            profile = state.profile

            # Determine data type and access
            if profile.signal_type.value in ("binary", "discrete"):
                data_type = ODT_BOOLEAN
            else:
                data_type = ODT_REAL32

            # Sensor signals are read-only, actuator signals are read-write
            if profile.signal_type.value in ("counter",) or "command" in signal_name.lower():
                access = "rw"
            else:
                access = "ro"

            self._add_od_entry(
                device_index, subindex, signal_name, data_type,
                value=state.current_value, access=access,
                description=f"Signal: {signal_name} ({profile.unit})",
                min_value=profile.min_value,
                max_value=profile.max_value,
            )

            # Store mapping from signal name to OD location
            self._signal_to_od[signal_name] = (device_index, subindex)

        logger.info(
            f"Mapped device '{device.device_id}' to OD index 0x{device_index:04X} with {num_signals} signals"
        )

    def _setup_pdo_mapping(self, device: Device) -> None:
        """
        Set up PDO (Process Data Object) mappings for a device.

        Creates TPDO (Transmit PDO) for sensor signals and
        RPDO (Receive PDO) for actuator signals.
        """
        # TPDO1: Transmit sensor values (device -> controller)
        tpdo1_cob_id = COB_ID_TPDO1 + self.node_id
        tpdo1 = PdoMapping(
            pdo_number=1,
            is_transmit=True,
            cob_id=tpdo1_cob_id,
            transmission_type=255,  # Async (event-driven)
        )

        # RPDO1: Receive actuator commands (controller -> device)
        rpdo1_cob_id = COB_ID_RPDO1 + self.node_id
        rpdo1 = PdoMapping(
            pdo_number=1,
            is_transmit=False,
            cob_id=rpdo1_cob_id,
            transmission_type=255,  # Async
        )

        # Map signals to PDOs
        for signal_name, state in device.signals.items():
            od_location = self._signal_to_od.get(signal_name)
            if not od_location:
                continue

            profile = state.profile
            if profile.signal_type.value in ("counter",) or "command" in signal_name.lower():
                rpdo1.mapped_entries.append(od_location)
            else:
                tpdo1.mapped_entries.append(od_location)

        self._pdo_mappings[1] = tpdo1
        self._pdo_mappings[2] = rpdo1

        logger.debug(
            f"PDO mapping: TPDO1 has {len(tpdo1.mapped_entries)} entries, RPDO1 has {len(rpdo1.mapped_entries)} entries"
        )

    def _encode_sdo_data(self, data_type: int, value: Any) -> bytes:
        """Encode a value into SDO data bytes based on data type."""
        if data_type == ODT_BOOLEAN:
            return struct.pack("<B", 1 if value else 0)
        elif data_type == ODT_INTEGER8:
            return struct.pack("<b", int(value))
        elif data_type == ODT_INTEGER16:
            return struct.pack("<h", int(value))
        elif data_type == ODT_INTEGER32:
            return struct.pack("<i", int(value))
        elif data_type == ODT_UNSIGNED8:
            return struct.pack("<B", int(value))
        elif data_type == ODT_UNSIGNED16:
            return struct.pack("<H", int(value))
        elif data_type == ODT_UNSIGNED32:
            return struct.pack("<I", int(value))
        elif data_type == ODT_REAL32:
            return struct.pack("<f", float(value))
        elif data_type == ODT_VISIBLE_STRING:
            return str(value).encode("utf-8")
        else:
            return struct.pack("<I", int(value))

    def _decode_sdo_data(self, data_type: int, data: bytes) -> Any:
        """Decode SDO data bytes into a value based on data type."""
        if not data:
            return 0

        try:
            if data_type == ODT_BOOLEAN:
                return bool(struct.unpack_from("<B", data, 0)[0])
            elif data_type == ODT_INTEGER8:
                return struct.unpack_from("<b", data, 0)[0]
            elif data_type == ODT_INTEGER16:
                return struct.unpack_from("<h", data, 0)[0]
            elif data_type == ODT_INTEGER32:
                return struct.unpack_from("<i", data, 0)[0]
            elif data_type == ODT_UNSIGNED8:
                return struct.unpack_from("<B", data, 0)[0]
            elif data_type == ODT_UNSIGNED16:
                return struct.unpack_from("<H", data, 0)[0]
            elif data_type == ODT_UNSIGNED32:
                return struct.unpack_from("<I", data, 0)[0]
            elif data_type == ODT_REAL32:
                return struct.unpack_from("<f", data, 0)[0]
            elif data_type == ODT_VISIBLE_STRING:
                return data.decode("utf-8", errors="replace")
            else:
                return struct.unpack_from("<I", data, 0)[0]
        except (struct.error, UnicodeDecodeError) as e:
            logger.error(f"Failed to decode SDO data (type={data_type}): {e}")
            return 0

    def _handle_sdo_download(
        self, index: int, subindex: int, data: bytes
    ) -> Tuple[bool, int]:
        """
        Handle an SDO download request (write to OD).

        Returns (success, abort_code).
        """
        with self._lock:
            if index not in self._object_dictionary:
                logger.warning(
                    f"SDO download: index 0x{index:04X} not found"
                )
                return False, SDO_ABORT_NO_SUCH_OBJECT

            subentries = self._object_dictionary[index]
            if subindex not in subentries:
                logger.warning(
                    f"SDO download: subindex 0x{subindex:02X} not found in index 0x{index:04X}"
                )
                return False, SDO_ABORT_NO_SUCH_OBJECT

            entry = subentries[subindex]

            if entry.access not in ("rw", "wo"):
                logger.warning(
                    f"SDO download: entry 0x{index:04X}:{subindex:02X} is read-only"
                )
                return False, SDO_ABORT_UNSUPPORTED_ACCESS

            # Decode and validate the value
            new_value = self._decode_sdo_data(entry.data_type, data)

            if entry.min_value is not None and new_value < entry.min_value:
                new_value = entry.min_value
            if entry.max_value is not None and new_value > entry.max_value:
                new_value = entry.max_value

            entry.value = new_value

            logger.info(
                f"SDO download: 0x{index:04X}:{subindex:02X} = {new_value}"
            )

            # If this OD entry maps to a device signal, update the simulation
            for signal_name, od_loc in self._signal_to_od.items():
                if od_loc == (index, subindex):
                    # Find the device that owns this signal
                    if self.simulation:
                        for cluster in self.simulation.clusters.values():
                            for device in cluster.devices.values():
                                if signal_name in device.signals:
                                    self.handle_command(
                                        device.device_id,
                                        signal_name,
                                        float(new_value),
                                    )
                                    logger.debug(
                                        f"SDO download -> simulation: {device.device_id}.{signal_name} = {new_value}"
                                    )
                                    break
                    break

            return True, 0

    def _handle_sdo_upload(
        self, index: int, subindex: int
    ) -> Tuple[bool, Any, int]:
        """
        Handle an SDO upload request (read from OD).

        Returns (success, value, abort_code).
        """
        with self._lock:
            if index not in self._object_dictionary:
                logger.warning(
                    f"SDO upload: index 0x{index:04X} not found"
                )
                return False, None, SDO_ABORT_NO_SUCH_OBJECT

            subentries = self._object_dictionary[index]
            if subindex not in subentries:
                logger.warning(
                    f"SDO upload: subindex 0x{subindex:02X} not found in index 0x{index:04X}"
                )
                return False, None, SDO_ABORT_NO_SUCH_OBJECT

            entry = subentries[subindex]

            if entry.access == "wo":
                logger.warning(
                    f"SDO upload: entry 0x{index:04X}:{subindex:02X} is write-only"
                )
                return False, None, SDO_ABORT_UNSUPPORTED_ACCESS

            logger.debug(
                f"SDO upload: 0x{index:04X}:{subindex:02X} = {entry.value}"
            )
            return True, entry.value, 0

    def _build_sdo_download_response(self, index: int, subindex: int) -> bytes:
        """Build an SDO download response."""
        response = struct.pack("<B", SDO_CMD_DOWNLOAD_RESP)
        response += struct.pack("<H", index)
        response += struct.pack("<B", subindex)
        response += b"\x00\x00\x00\x00"  # Reserved
        return response

    def _build_sdo_upload_response(
        self, index: int, subindex: int, value: Any, data_type: int
    ) -> bytes:
        """Build an SDO upload response."""
        data = self._encode_sdo_data(data_type, value)
        response = struct.pack("<B", SDO_CMD_UPLOAD_RESP)
        response += struct.pack("<H", index)
        response += struct.pack("<B", subindex)
        # Data follows (padded to 4 bytes)
        response += data.ljust(4, b"\x00")
        return response

    def _build_sdo_abort_response(
        self, index: int, subindex: int, abort_code: int
    ) -> bytes:
        """Build an SDO abort response."""
        response = struct.pack("<B", SDO_CMD_ABORT)
        response += struct.pack("<H", index)
        response += struct.pack("<B", subindex)
        response += struct.pack("<I", abort_code)
        return response

    def _process_sdo_message(self, data: bytes) -> Optional[bytes]:
        """
        Process an incoming SDO message.

        Returns the response data, or None if no response needed.
        """
        if len(data) < 4:
            return None

        command = data[0]
        index = struct.unpack_from("<H", data, 1)[0]
        subindex = data[3]

        logger.debug(
            f"SDO message: cmd=0x{command:02X}, index=0x{index:04X}, subindex=0x{subindex:02X}"
        )

        if command == SDO_CMD_DOWNLOAD_REQ:
            # Download request (write)
            data_bytes = data[4:]
            success, abort_code = self._handle_sdo_download(
                index, subindex, data_bytes
            )
            if success:
                return self._build_sdo_download_response(index, subindex)
            else:
                return self._build_sdo_abort_response(
                    index, subindex, abort_code
                )

        elif command == SDO_CMD_UPLOAD_REQ:
            # Upload request (read)
            success, value, abort_code = self._handle_sdo_upload(
                index, subindex
            )
            if success:
                # Find the data type
                data_type = ODT_REAL32
                if index in self._object_dictionary:
                    if subindex in self._object_dictionary[index]:
                        data_type = self._object_dictionary[index][subindex].data_type
                return self._build_sdo_upload_response(
                    index, subindex, value, data_type
                )
            else:
                return self._build_sdo_abort_response(
                    index, subindex, abort_code
                )

        return None

    def _process_nmt_message(self, data: bytes) -> None:
        """Process an NMT (Network Management) message."""
        if len(data) < 2:
            return

        command = data[0]
        target_node = data[1]

        # Only process messages addressed to this node or all nodes (0)
        if target_node != 0 and target_node != self.node_id:
            return

        logger.info(
            f"NMT command: 0x{command:02X} for node {target_node}"
        )

        if command == NMT_CMD_START_REMOTE_NODE:
            self._nmt_state = NMT_STATE_OPERATIONAL
            logger.info(f"CANopen node {self.node_id} -> Operational")
        elif command == NMT_CMD_STOP_REMOTE_NODE:
            self._nmt_state = NMT_STATE_STOPPED
            logger.info(f"CANopen node {self.node_id} -> Stopped")
        elif command == NMT_CMD_ENTER_PRE_OPERATIONAL:
            self._nmt_state = NMT_STATE_PRE_OPERATIONAL
            logger.info(f"CANopen node {self.node_id} -> Pre-operational")
        elif command == NMT_CMD_RESET_NODE:
            self._nmt_state = NMT_STATE_PRE_OPERATIONAL
            logger.info(f"CANopen node {self.node_id} -> Reset")
        elif command == NMT_CMD_RESET_COMMUNICATION:
            self._nmt_state = NMT_STATE_PRE_OPERATIONAL
            logger.info(f"CANopen node {self.node_id} -> Communication reset")

    def _process_rpdo_message(self, data: bytes) -> None:
        """
        Process an RPDO (Receive PDO) message.

        RPDO data contains output values from the CANopen master
        that need to be written to the physics simulation.
        """
        if not self._pdo_mappings:
            return

        # Find RPDO mappings
        for pdo_num, mapping in self._pdo_mappings.items():
            if mapping.is_transmit:
                continue

            if len(data) < len(mapping.mapped_entries):
                logger.warning(
                    f"RPDO{1} data too short: {len(data)} bytes for {len(mapping.mapped_entries)} entries"
                )
                continue

            offset = 0
            for idx, (index, subindex) in enumerate(mapping.mapped_entries):
                if index in self._object_dictionary and subindex in self._object_dictionary[index]:
                    entry = self._object_dictionary[index][subindex]
                    data_size = 4  # Default to 4 bytes per entry

                    if entry.data_type in (ODT_BOOLEAN, ODT_UNSIGNED8, ODT_INTEGER8):
                        data_size = 1
                    elif entry.data_type in (ODT_UNSIGNED16, ODT_INTEGER16):
                        data_size = 2

                    if offset + data_size <= len(data):
                        entry_data = data[offset : offset + data_size]
                        new_value = self._decode_sdo_data(
                            entry.data_type, entry_data
                        )
                        entry.value = new_value

                        # Update simulation
                        for signal_name, od_loc in self._signal_to_od.items():
                            if od_loc == (index, subindex):
                                if self.simulation:
                                    for cluster in self.simulation.clusters.values():
                                        for device in cluster.devices.values():
                                            if signal_name in device.signals:
                                                self.handle_command(
                                                    device.device_id,
                                                    signal_name,
                                                    float(new_value),
                                                )
                                                logger.debug(
                                                    f"RPDO -> simulation: {device.device_id}.{signal_name} = {new_value}"
                                                )
                                                break
                                break

                        offset += data_size

            logger.debug(
                f"Processed RPDO{1} with {len(mapping.mapped_entries)} entries"
            )

    def _build_tpdo_message(self) -> Optional[bytes]:
        """
        Build a TPDO (Transmit PDO) message with current signal values.

        Returns the PDO data bytes, or None if no TPDO mapping exists.
        """
        for pdo_num, mapping in self._pdo_mappings.items():
            if not mapping.is_transmit:
                continue

            data = b""
            for index, subindex in mapping.mapped_entries:
                if index in self._object_dictionary and subindex in self._object_dictionary[index]:
                    entry = self._object_dictionary[index][subindex]
                    entry_data = self._encode_sdo_data(
                        entry.data_type, entry.value
                    )
                    data += entry_data

            if data:
                logger.debug(
                    f"Built TPDO{1} message: {len(data)} bytes"
                )
                return data

        return None

    def _start_engine(self) -> None:
        """Start the CANopen engine."""
        # Initialize the communication profile
        self._init_communication_profile()

        # Set initial NMT state
        self._nmt_state = NMT_STATE_PRE_OPERATIONAL

        logger.info(
            f"CANopen engine started (node_id={self.node_id}, interface={self.can_interface})"
        )

        if self.use_socketcan:
            try:
                import socket as _socket
                self._can_socket = _socket.socket(
                    _socket.AF_CAN, _socket.SOCK_RAW, _socket.CAN_RAW
                )
                self._can_socket.bind((self.can_interface,))
                self._can_socket.settimeout(1.0)
                logger.info(
                    f"Bound to SocketCAN interface '{self.can_interface}'"
                )
            except Exception as e:
                logger.warning(
                    f"Could not bind to SocketCAN interface '{self.can_interface}': {e}"
                )
                self._can_socket = None

    def _stop_engine(self) -> None:
        """Stop the CANopen engine."""
        self._nmt_state = NMT_STATE_STOPPED
        if self._can_socket:
            try:
                self._can_socket.close()
            except Exception as e:
                logger.error(f"Error closing CAN socket: {e}")
        with self._lock:
            self._object_dictionary.clear()
            self._pdo_mappings.clear()
            self._signal_to_od.clear()
        logger.info("CANopen engine stopped")

    def _publish_device_values(self, device: Device) -> None:
        """Publish device signal values to the Object Dictionary."""
        # Map device to OD if not already done
        self._map_device_to_od(device)

        # Set up PDO mapping if not already done
        if not self._pdo_mappings:
            self._setup_pdo_mapping(device)

        # Update OD entries with current signal values
        for signal_name, state in device.signals.items():
            od_location = self._signal_to_od.get(signal_name)
            if not od_location:
                continue

            index, subindex = od_location
            if index in self._object_dictionary and subindex in self._object_dictionary[index]:
                entry = self._object_dictionary[index][subindex]
                entry.value = state.current_value

        # Build and "send" TPDO message (logged for now)
        tpdo_data = self._build_tpdo_message()
        if tpdo_data:
            logger.debug(
                f"TPDO1 data for device '{device.device_id}': {tpdo_data.hex()} ({len(tpdo_data)} bytes)"
            )

    def _handle_external_command(
        self, device_id: str, signal_name: str, value: float
    ) -> None:
        """Handle an external CANopen write command."""
        logger.info(
            f"CANopen external command: {device_id}.{signal_name} = {value}"
        )
        # Update the corresponding OD entry
        od_location = self._signal_to_od.get(signal_name)
        if od_location:
            index, subindex = od_location
            if index in self._object_dictionary and subindex in self._object_dictionary[index]:
                self._object_dictionary[index][subindex].value = value
                logger.debug(
                    f"Updated OD entry 0x{index:04X}:{subindex:02X} = {value}"
                )

    def get_od_dump(self) -> Dict[str, Any]:
        """
        Get a dump of the entire Object Dictionary.

        Useful for debugging and monitoring.
        """
        od_dump = {}
        for index, subentries in self._object_dictionary.items():
            index_key = f"0x{index:04X}"
            od_dump[index_key] = {}
            for subindex, entry in subentries.items():
                sub_key = f"0x{subindex:02X}"
                od_dump[index_key][sub_key] = {
                    "name": entry.name,
                    "value": entry.value,
                    "type": entry.data_type,
                    "access": entry.access,
                    "description": entry.description,
                }
        return od_dump
