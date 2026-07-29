"""
IEC 61850 Protocol Engine.

Implements an IEC 61850 server using the MMS (Manufacturing Message
Specification) protocol. IEC 61850 is the international standard for
communication in substation automation systems (SAS), covering protection,
control, measurement, and monitoring functions.

IEC 61850 Data Model:
- Physical Device (IED): The physical device running the protocol
- Logical Device (LD): Groups related functions within an IED
- Logical Node (LN): The smallest function in the substation
  - Prefix: Identifies the LN instance
  - LN Class: Defines the function type (e.g., MMXU, XCBR, YLTC)
  - LN Instance: Instance number within the same class
- Data Object (DO): Represents a specific information piece
- Data Attribute (DA): The actual value carrier within a DO
- Common Data Class (CDC): Template for data object structure

Standard LN Classes:
- MMXU: Measurement (measuring unit)
- XCBR: Circuit breaker
- XSWI: Disconnect switch
- YLTC: Tap changer
- YPTR: Power transformer
- MMTR: Metering
- MV: Measurement value

Protocol Details:
- Transport: TCP (MMS over TCP/IP)
- Default Port: 102 (MMS)
- Uses MMS (ISO 9506) for client-server communication
- Supports GOOSE (Generic Object Oriented Substation Events) for fast
  event-driven communication
- Supports Sampled Values (SV) for process bus communication
- SCL (Substation Configuration Language) for device description
- Reports and logging for event capture

Signal Mapping:
- Analog signals -> Measurement values in MMXU/MV logical nodes
- Binary/Discrete signals -> Status values in XCBR/XSWI logical nodes
- Counter signals -> Metered values in MMTR logical nodes
- Each device signal maps to a specific Data Object within a Logical Node
"""

from __future__ import annotations

import logging
import socket
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from src.core.device import Device, SimulationManager
from src.protocols.base import ProtocolConfig, ProtocolEngine

logger = logging.getLogger(__name__)

# IEC 61850/MMS default port
IEC_61850_PORT: int = 102

# MMS Object types
MMS_OBJECT_TYPE_VARIABLE: int = 0
MMS_OBJECT_TYPE_DOMAIN: int = 1
MMS_OBJECT_TYPE_NAMED_VARIABLE: int = 2
MMS_OBJECT_TYPE_NAMED_VARIABLE_LIST: int = 3

# MMS AccessResult types
MMS_SUCCESS: int = 0x00
MMS_ACCESS_DENIED: int = 0x01
MMS_OBJECT_ACCESS_DENIED: int = 0x02
MMS_OBJECT_NON_EXISTENT: int = 0x03
MMS_TYPE_CONFLICT: int = 0x05
MMS_TEMPORARY_FAILURE: int = 0x06

# CDC (Common Data Class) names
CDC_MV: str = "MV"  # Measured value
CDC_CMV: str = "CMV"  # Complex measured value
CDC_SAV: str = "SAV"  # Sampled analog value
CDC_SPS: str = "SPS"  # Single point status
CDC_DPC: str = "DPC"  # Controllable double point
CDC_APC: str = "APC"  # Controllable analog value
CDC_INS: str = "INS"  # Integer status
CDC_ACT: str = "ACT"  # Activation
CDC_BCR: str = "BCR"  # Binary counter reading

# Standard LN classes for simulation
LN_CLASS_MMXU: str = "MMXU"  # Measurement unit
LN_CLASS_XCBR: str = "XCBR"  # Circuit breaker
LN_CLASS_XSWI: str = "XSWI"  # Disconnect switch
LN_CLASS_YLTC: str = "YLTC"  # Tap changer
LN_CLASS_MMTR: str = "MMTR"  # Metering
LN_CLASS_GGIO: str = "GGIO"  # Generic I/O
LN_CLASS_LPHD: str = "LPHD"  # Physical device information
LN_CLASS_LLN0: str = "LLN0"  # Logical node zero

# Standard Data Object names for MMXU
DO_MMXU_TOTW: str = "TotW"  # Total active power
DO_MMXU_TOTVAr: str = "TotVAr"  # Total reactive power
DO_MMXU_TOTPF: str = "TotPF"  # Total power factor
DO_MMXU_PPV: str = "PPV"  # Phase-to-phase voltages
DO_MMXU_PNV: str = "PhV"  # Phase-to-neutral voltages
DO_MMXU_A: str = "A"  # Phase currents
DO_MMXU_W: str = "W"  # Active power (per phase)
DO_MMXU_VAr: str = "VAr"  # Reactive power (per phase)

# Standard Data Object names for XCBR
DO_XCBR_POS: str = "Pos"  # Position
DO_XCBR_BLK: str = "Blk"  # Block
DO_XCBR_OPCNT: str = "OpCnt"  # Operation counter

# Standard Data Object names for YLTC
DO_YLTC_TAP: str = "Tap"  # Tap position
DO_YLTC_END: str = "End"  # End position

# Standard Data Object names for GGIO
DO_GGIO_IND: str = "Ind"  # Indication (generic binary)
DO_GGIO_ANA: str = "Ana"  # Analog value (generic)

# Data Attribute names for MV CDC
DA_MV_INST_CVAL: str = "instCVal"  # Instantaneous value (cval)
DA_MV_MAG: str = "mag"  # Magnitude
DA_MV_F: str = "f"  # Float value
DA_MV_Q: str = "q"  # Quality
DA_MV_T: str = "t"  # Timestamp

# Data Attribute names for SPS CDC
DA_SPS_ST_VAL: str = "stVal"  # Status value (boolean)
DA_SPS_Q: str = "q"  # Quality
DA_SPS_T: str = "t"  # Timestamp

# Data Attribute names for DPC CDC
DA_DPC_ST_VAL: str = "stVal"  # Status value (0=off, 1=on, 2=intermediate)


@dataclass
class DataAttribute:
    """
    Represents a Data Attribute (DA) in the IEC 61850 data model.

    The DA is the leaf node in the hierarchy that holds the actual value.
    """

    name: str
    value: Any = None
    quality: int = 0x00  # 0 = good, 0x40 = invalid, 0x80 = questionable
    timestamp: float = 0.0
    data_type: str = "float"  # "float", "boolean", "integer", "string"
    access: str = "rw"  # "ro", "rw", "wo"


@dataclass
class DataObject:
    """
    Represents a Data Object (DO) in the IEC 61850 data model.

    A DO is a collection of Data Attributes that represent a specific
    piece of information (e.g., a measurement or status).
    """

    name: str
    cdc: str  # Common Data Class (e.g., "MV", "SPS", "DPC")
    description: str = ""
    attributes: Dict[str, DataAttribute] = field(default_factory=dict)


@dataclass
class LogicalNode:
    """
    Represents a Logical Node (LN) in the IEC 61850 data model.

    An LN is the smallest function in a substation, identified by
    a prefix, LN class, and instance number.
    """

    prefix: str
    ln_class: str
    instance: int
    description: str = ""
    data_objects: Dict[str, DataObject] = field(default_factory=dict)

    @property
    def name(self) -> str:
        """Get the full LN name (e.g., 'MMXU1', 'XCBR2')."""
        return f"{self.prefix}{self.ln_class}{self.instance}" if self.prefix else \
            f"{self.ln_class}{self.instance}"


@dataclass
class LogicalDevice:
    """
    Represents a Logical Device (LD) in the IEC 61850 data model.

    An LD is a grouping of related Logical Nodes that perform a
    specific function (e.g., protection, control, measurement).
    """

    name: str
    description: str = ""
    logical_nodes: Dict[str, LogicalNode] = field(default_factory=dict)

    def add_node(self, node: LogicalNode) -> None:
        """Add a Logical Node to this Logical Device."""
        self.logical_nodes[node.name] = node


class Iec61850Engine(ProtocolEngine):
    """
    IEC 61850 protocol engine using the MMS data model.

    Maps physics-backed device signals to IEC 61850 Logical Nodes
    and Data Objects. Each signal value is represented as a Data
    Attribute within a Data Object, organized under the appropriate
    Logical Node class.

    Signal Mapping Pattern:
    - Analog process signals (temperature, pressure, flow) ->
      MMXU / ANA Data Objects with MV CDC
    - Binary status signals (valve open/closed, alarm) ->
      GGIO / XSWI Data Objects with SPS CDC
    - Counter signals (total flow, energy) ->
      MMTR / BCR Data Objects
    - Command signals (setpoint, control) ->
      XCBR / YLTC Data Objects with DPC/APC CDC

    External Commands:
    - MMS Write requests to Data Attributes
    - Control operations (operate) on controllable DOs
    - Maps to device signal writes in the physics simulation
    """

    def __init__(
        self,
        name: str = "iec61850",
        config: Optional[ProtocolConfig] = None,
        simulation: Optional[SimulationManager] = None,
        host: str = "0.0.0.0",
        port: int = 102,
        ied_name: str = "ICS_SIMULATOR",
    ):
        super().__init__(name, config or ProtocolConfig(), simulation)
        self.host = host
        self.port = port
        self.ied_name = ied_name

        # IEC 61850 data model
        self._logical_devices: Dict[str, LogicalDevice] = {}
        self._signal_to_da: Dict[str, Tuple[str, str, str, str]] = {}
        # Maps signal_name -> (ld_name, ln_name, do_name, da_name)

        self._tcp_server: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._running: bool = False

    @property
    def protocol_name(self) -> str:
        """Return the protocol name."""
        return "iec61850"

    def _create_mv_data_object(
        self, name: str, value: float, description: str = ""
    ) -> DataObject:
        """
        Create a Measurement Value (MV) Data Object.

        MV is the most common CDC for analog process values.
        """
        do = DataObject(
            name=name,
            cdc=CDC_MV,
            description=description,
        )
        do.attributes[DA_MV_INST_CVAL] = DataAttribute(
            name=DA_MV_INST_CVAL,
            value={"f": value},
            data_type="float",
            access="ro",
        )
        do.attributes[DA_MV_MAG] = DataAttribute(
            name=DA_MV_MAG,
            value={"f": value},
            data_type="float",
            access="ro",
        )
        do.attributes[DA_MV_F] = DataAttribute(
            name=DA_MV_F,
            value=value,
            data_type="float",
            access="ro",
        )
        do.attributes[DA_MV_Q] = DataAttribute(
            name=DA_MV_Q,
            value=0x00,  # Good quality
            data_type="integer",
            access="ro",
        )
        do.attributes[DA_MV_T] = DataAttribute(
            name=DA_MV_T,
            value=0.0,
            data_type="float",
            access="ro",
        )
        return do

    def _create_sps_data_object(
        self, name: str, value: bool, description: str = ""
    ) -> DataObject:
        """
        Create a Single Point Status (SPS) Data Object.

        SPS is used for binary status values (on/off, open/closed).
        """
        do = DataObject(
            name=name,
            cdc=CDC_SPS,
            description=description,
        )
        do.attributes[DA_SPS_ST_VAL] = DataAttribute(
            name=DA_SPS_ST_VAL,
            value=value,
            data_type="boolean",
            access="ro",
        )
        do.attributes[DA_SPS_Q] = DataAttribute(
            name=DA_SPS_Q,
            value=0x00,  # Good quality
            data_type="integer",
            access="ro",
        )
        do.attributes[DA_SPS_T] = DataAttribute(
            name=DA_SPS_T,
            value=0.0,
            data_type="float",
            access="ro",
        )
        return do

    def _create_apc_data_object(
        self, name: str, value: float, description: str = ""
    ) -> DataObject:
        """
        Create a Controllable Analog Value (APC) Data Object.

        APC is used for actuator commands that can be set by the client.
        """
        do = DataObject(
            name=name,
            cdc=CDC_APC,
            description=description,
        )
        do.attributes[DA_MV_F] = DataAttribute(
            name=DA_MV_F,
            value=value,
            data_type="float",
            access="rw",
        )
        do.attributes[DA_MV_Q] = DataAttribute(
            name=DA_MV_Q,
            value=0x00,
            data_type="integer",
            access="ro",
        )
        return do

    def _create_dpc_data_object(
        self, name: str, value: int, description: str = ""
    ) -> DataObject:
        """
        Create a Controllable Double Point (DPC) Data Object.

        DPC is used for two-state control (off/on) with intermediate state.
        """
        do = DataObject(
            name=name,
            cdc=CDC_DPC,
            description=description,
        )
        do.attributes[DA_DPC_ST_VAL] = DataAttribute(
            name=DA_DPC_ST_VAL,
            value=value,
            data_type="integer",
            access="rw",
        )
        do.attributes[DA_SPS_Q] = DataAttribute(
            name=DA_SPS_Q,
            value=0x00,
            data_type="integer",
            access="ro",
        )
        return do

    def _init_logical_device(self, device: Device) -> LogicalDevice:
        """
        Initialize a Logical Device for a simulated physical device.

        Creates the standard Logical Nodes (LLN0, LPHD) and
        maps device signals to appropriate LN classes.
        """
        ld_name = f"{self.ied_name}/{device.device_id}"
        ld = LogicalDevice(
            name=ld_name,
            description=f"Simulated device: {device.name}",
        )

        # Create LLN0 (Logical Node Zero) - device management
        lln0 = LogicalNode(
            prefix="",
            ln_class=LN_CLASS_LLN0,
            instance=1,
            description="Logical node zero - device management",
        )
        lln0.data_objects["NamPlt"] = self._create_mv_data_object(
            "NamPlt", 0.0, "Name plate"
        )
        lln0.data_objects["Health"] = self._create_mv_data_object(
            "Health", 1.0, "Device health"
        )
        ld.add_node(lln0)

        # Create LPHD (Physical Device Information)
        lphd = LogicalNode(
            prefix="",
            ln_class=LN_CLASS_LPHD,
            instance=1,
            description="Physical device information",
        )
        lphd.data_objects["PhyNam"] = self._create_mv_data_object(
            "PhyNam", 0.0, "Physical device name"
        )
        ld.add_node(lphd)

        # Create measurement LN (MMXU) for analog signals
        mmxu = LogicalNode(
            prefix="",
            ln_class=LN_CLASS_MMXU,
            instance=1,
            description="Measurements",
        )
        # Create GGIO LN for generic I/O signals
        ggio = LogicalNode(
            prefix="",
            ln_class=LN_CLASS_GGIO,
            instance=1,
            description="Generic I/O",
        )
        # Create XCBR LN for binary/control signals
        xcbr = LogicalNode(
            prefix="",
            ln_class=LN_CLASS_XCBR,
            instance=1,
            description="Circuit breaker / control",
        )

        # Map signals to data objects
        for signal_name, state in device.signals.items():
            profile = state.profile

            if profile.signal_type.value in ("binary", "discrete"):
                # Map to GGIO Indication or XCBR Position
                do_name = f"Ind_{signal_name}"
                do = self._create_sps_data_object(
                    do_name, bool(state.current_value),
                    f"{signal_name} ({profile.unit})",
                )
                ggio.data_objects[do_name] = do
                self._signal_to_da[signal_name] = (
                    ld_name, ggio.name, do_name, DA_SPS_ST_VAL
                )

                if "command" in signal_name.lower() or "control" in signal_name.lower():
                    # Also create a controllable version
                    ctrl_do_name = f"Pos_{signal_name}"
                    ctrl_do = self._create_dpc_data_object(
                        ctrl_do_name, int(state.current_value),
                        f"{signal_name} control ({profile.unit})",
                    )
                    xcbr.data_objects[ctrl_do_name] = ctrl_do
                    self._signal_to_da[f"{signal_name}_ctrl"] = (
                        ld_name, xcbr.name, ctrl_do_name, DA_DPC_ST_VAL
                    )

            elif profile.signal_type.value == "counter":
                # Map to MMXU measurement
                do_name = f"Meter_{signal_name}"
                do = self._create_mv_data_object(
                    do_name, state.current_value,
                    f"{signal_name} ({profile.unit})",
                )
                mmxu.data_objects[do_name] = do
                self._signal_to_da[signal_name] = (
                    ld_name, mmxu.name, do_name, DA_MV_F
                )
            else:
                # Analog signal - map to MMXU or GGIO Analog
                do_name = f"Ana_{signal_name}"
                do = self._create_mv_data_object(
                    do_name, state.current_value,
                    f"{signal_name} ({profile.unit})",
                )
                mmxu.data_objects[do_name] = do
                self._signal_to_da[signal_name] = (
                    ld_name, mmxu.name, do_name, DA_MV_F
                )

        # Add LNs to LD
        ld.add_node(mmxu)
        ld.add_node(ggio)
        ld.add_node(xcbr)

        self._logical_devices[ld_name] = ld

        logger.info(
            f"Created Logical Device '{ld_name}' with "
                f"{len(ld.logical_nodes)} LNs for device '{device.device_id}'"
        )
        return ld

    def _start_engine(self) -> None:
        """Start the IEC 61850 MMS server."""
        self._tcp_server = socket.socket(
            socket.AF_INET, socket.SOCK_STREAM
        )
        self._tcp_server.setsockopt(
            socket.SOL_SOCKET, socket.SO_REUSEADDR, 1
        )
        self._tcp_server.bind((self.host, self.port))
        self._tcp_server.listen(5)
        self._tcp_server.settimeout(1.0)

        logger.info(
            f"IEC 61850 MMS server listening on {self.host}:{self.port}"
        )

    def _stop_engine(self) -> None:
        """Stop the IEC 61850 MMS server."""
        if self._tcp_server:
            try:
                self._tcp_server.close()
            except Exception as e:
                logger.error(f"Error closing TCP server: {e}")
        with self._lock:
            self._logical_devices.clear()
            self._signal_to_da.clear()
        logger.info("IEC 61850 MMS server stopped")

    def _publish_device_values(self, device: Device) -> None:
        """Publish device signal values to the IEC 61850 data model."""
        # Initialize LD if not already done
        ld_name = f"{self.ied_name}/{device.device_id}"
        if ld_name not in self._logical_devices:
            self._init_logical_device(device)

        # Update Data Attributes with current signal values
        for signal_name, state in device.signals.items():
            da_location = self._signal_to_da.get(signal_name)
            if not da_location:
                continue

            ld_name, ln_name, do_name, da_name = da_location
            ld = self._logical_devices.get(ld_name)
            if not ld:
                continue

            ln = ld.logical_nodes.get(ln_name)
            if not ln:
                continue

            do = ln.data_objects.get(do_name)
            if not do:
                continue

            da = do.attributes.get(da_name)
            if not da:
                continue

            # Update the attribute value
            profile = state.profile
            if profile.signal_type.value in ("binary", "discrete"):
                da.value = bool(state.current_value)
            else:
                da.value = state.current_value

            da.timestamp = state.timestamp
            da.quality = 0x00  # Good quality

            logger.debug(
                f"Updated IEC 61850 attribute: {ld_name}/{ln_name}/{do_name}.{da_name} = {da.value}"
            )

    def _handle_mms_read(
        self, ld_name: str, ln_name: str, do_name: str, da_name: str
    ) -> Tuple[int, Any]:
        """
        Handle an MMS Read request.

        Returns (status_code, value).
        """
        logger.debug(
            f"MMS Read: {ld_name}/{ln_name}/{do_name}.{da_name}"
        )

        ld = self._logical_devices.get(ld_name)
        if not ld:
            return MMS_OBJECT_NON_EXISTENT, None

        ln = ld.logical_nodes.get(ln_name)
        if not ln:
            return MMS_OBJECT_NON_EXISTENT, None

        do = ln.data_objects.get(do_name)
        if not do:
            return MMS_OBJECT_NON_EXISTENT, None

        da = do.attributes.get(da_name)
        if not da:
            return MMS_OBJECT_NON_EXISTENT, None

        if da.access == "wo":
            return MMS_OBJECT_ACCESS_DENIED, None

        return MMS_SUCCESS, da.value

    def _handle_mms_write(
        self, ld_name: str, ln_name: str, do_name: str, da_name: str, value: Any
    ) -> int:
        """
        Handle an MMS Write request.

        Returns status code.
        """
        logger.info(
            f"MMS Write: {ld_name}/{ln_name}/{do_name}.{da_name} = {value}"
        )

        ld = self._logical_devices.get(ld_name)
        if not ld:
            return MMS_OBJECT_NON_EXISTENT

        ln = ld.logical_nodes.get(ln_name)
        if not ln:
            return MMS_OBJECT_NON_EXISTENT

        do = ln.data_objects.get(do_name)
        if not do:
            return MMS_OBJECT_NON_EXISTENT

        da = do.attributes.get(da_name)
        if not da:
            return MMS_OBJECT_NON_EXISTENT

        if da.access not in ("rw", "wo"):
            return MMS_OBJECT_ACCESS_DENIED

        da.value = value
        da.timestamp = 0.0  # Will be updated on next publish

        logger.info(
            f"MMS Write applied: {ld_name}/{ln_name}/{do_name}.{da_name} = {value}"
        )

        # If this DA maps to a device signal, update the simulation
        for signal_name, sig_da in self._signal_to_da.items():
            if sig_da == (ld_name, ln_name, do_name, da_name):
                if self.simulation:
                    for cluster in self.simulation.clusters.values():
                        for device in cluster.devices.values():
                            if signal_name in device.signals:
                                float_val = float(value) if value is not None else 0.0
                                self.handle_command(
                                    device.device_id, signal_name, float_val
                                )
                                logger.debug(
                                    f"MMS Write -> simulation: "
                                    f"{device.device_id}.{signal_name} = {float_val}"
                                )
                                break
                break

        return MMS_SUCCESS

    def _handle_external_command(
        self, device_id: str, signal_name: str, value: float
    ) -> None:
        """Handle an external IEC 61850 write command."""
        logger.info(
            f"IEC 61850 external command: {device_id}.{signal_name} = {value}"
        )
        # Update the corresponding Data Attribute
        da_location = self._signal_to_da.get(signal_name)
        if da_location:
            ld_name, ln_name, do_name, da_name = da_location
            ld = self._logical_devices.get(ld_name)
            if ld:
                ln = ld.logical_nodes.get(ln_name)
                if ln:
                    do = ln.data_objects.get(do_name)
                    if do:
                        da = do.attributes.get(da_name)
                        if da:
                            da.value = value
                            da.timestamp = 0.0
                            logger.debug(
                                f"Updated IEC 61850 attribute after external command: "
                                    f"{ld_name}/{ln_name}/{do_name}.{da_name} = {value}"
                            )

    def get_data_model(self) -> Dict[str, Any]:
        """
        Get a dump of the complete IEC 61850 data model.

        Returns a hierarchical dict of Logical Devices -> Logical Nodes ->
        Data Objects -> Data Attributes.
        """
        model: Dict[str, Any] = {}
        for ld_name, ld in self._logical_devices.items():
            model[ld_name] = {
                "description": ld.description,
                "logical_nodes": {},
            }
            for ln_name, ln in ld.logical_nodes.items():
                model[ld_name]["logical_nodes"][ln_name] = {
                    "description": ln.description,
                    "data_objects": {},
                }
                for do_name, do in ln.data_objects.items():
                    model[ld_name]["logical_nodes"][ln_name][
                        "data_objects"
                    ][do_name] = {
                        "cdc": do.cdc,
                        "description": do.description,
                        "attributes": {
                            da_name: {
                                "value": da.value,
                                "data_type": da.data_type,
                                "access": da.access,
                                "quality": da.quality,
                            }
                            for da_name, da in do.attributes.items()
                        },
                    }
        return model
