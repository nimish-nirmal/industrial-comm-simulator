"""
IEC 60870-5-104 Protocol Engine.

Implements an IEC 60870-5-104 server using the ASDU (Application Service
Data Unit) addressing model. IEC 60870-5-104 (IEC 104) is a standard for
telecontrol, teleprotection, and associated telecommunications for electric
power systems, widely used in SCADA and energy management systems.

IEC 104 Data Model:
- ASDU (Application Service Data Unit): The basic data unit
- COT (Cause of Transmission): Identifies why the data was sent
  (e.g., periodic, spontaneous, interrogation, command)
- IOA (Information Object Address): 3-byte address identifying
  the specific data point (up to 16,777,215 addresses)
- ASDU Address: 2-byte address identifying the station (Common ASDU Address)
- Type ID: Identifies the type of data in the ASDU
  (e.g., M_ME_NA_1 = measured value, C_SC_NA_1 = single command)

Common Type IDs:
- M_SP_NA_1 (1): Single-point information (binary)
- M_DP_NA_1 (3): Double-point information
- M_ME_NA_1 (9): Measured value, normalized
- M_ME_NB_1 (11): Measured value, scaled
- M_ME_NC_1 (13): Measured value, short floating point
- M_IT_NA_1 (15): Integrated totals (counters)
- C_SC_NA_1 (45): Single command
- C_DC_NA_1 (46): Double command
- C_SE_NA_1 (48): Setpoint command, normalized
- C_SE_NC_1 (50): Setpoint command, short floating point

Protocol Details:
- Transport: TCP
- Default Port: 2404
- Uses APCI (Application Protocol Control Information) framing
- Supports spontaneous, cyclic, and interrogated data transmission
- Test frames for connection monitoring (keep-alive)
- Clock synchronization
- Interrogation commands (station, group)

Signal Mapping:
- Analog signals -> M_ME_NC_1 (short floating point) ASDU
- Binary/Discrete signals -> M_SP_NA_1 (single point) ASDU
- Counter signals -> M_IT_NA_1 (integrated totals) ASDU
- Command signals -> C_SC_NA_1 / C_SE_NC_1 ASDUs
- Each signal gets a unique IOA within the station ASDU address
"""

from __future__ import annotations

import logging
import socket
import struct
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from src.core.device import Device, SimulationManager
from src.protocols.base import ProtocolConfig, ProtocolEngine

logger = logging.getLogger(__name__)

# IEC 104 port
IEC_104_PORT: int = 2404

# IEC 104 APCI frame types
APCI_TYPE_I: int = 0x00  # Information frame (bit 0 = 0)
APCI_TYPE_S: int = 0x01  # Supervisory frame (bits 1-0 = 01)
APCI_TYPE_U: int = 0x03  # Unnumbered frame (bits 1-0 = 11)

# IEC 104 U-frame command codes
U_STARTDT: int = 0x07  # STARTDT (start data transfer)
U_STARTDT_CON: int = 0x0B  # STARTDT confirmation
U_STOPDT: int = 0x13  # STOPDT (stop data transfer)
U_STOPDT_CON: int = 0x23  # STOPDT confirmation
U_TESTFR: int = 0x43  # TESTFR (test frame)
U_TESTFR_CON: int = 0x83  # TESTFR confirmation

# IEC 104 Type IDs (monitor direction)
M_SP_NA_1: int = 1   # Single-point information
M_DP_NA_1: int = 3   # Double-point information
M_ST_NA_1: int = 5   # Step position information
M_BO_NA_1: int = 7   # Bitstring of 32 bits
M_ME_NA_1: int = 9   # Measured value, normalized
M_ME_NB_1: int = 11  # Measured value, scaled
M_ME_NC_1: int = 13  # Measured value, short floating point
M_IT_NA_1: int = 15  # Integrated totals
M_PS_NA_1: int = 21  # Packed single-point information with SCQ

# IEC 104 Type IDs (control direction)
C_SC_NA_1: int = 45  # Single command
C_DC_NA_1: int = 46  # Double command
C_RC_NA_1: int = 47  # Regulating step command
C_SE_NA_1: int = 48  # Setpoint command, normalized
C_SE_NB_1: int = 49  # Setpoint command, scaled
C_SE_NC_1: int = 50  # Setpoint command, short floating point

# IEC 104 Cause of Transmission (COT)
COT_PERIODIC: int = 1       # Periodic / cyclic
COT_SPONTANEOUS: int = 3    # Spontaneous
COT_INTERROGATED: int = 5   # Interrogated by station interrogation
COT_ACTIVATION: int = 6     # Activation
COT_ACTIVATION_CON: int = 7  # Activation confirmation
COT_DEACTIVATION: int = 8   # Deactivation
COT_DEACTIVATION_CON: int = 9  # Deactivation confirmation
COT_ACTIVATION_TERM: int = 10  # Activation termination
COT_RETURN_INFO_REMOTE: int = 11  # Return information caused by a remote command
COT_RETURN_INFO_LOCAL: int = 12  # Return information caused by a local command
COT_FILE_TRANSFER: int = 13  # File transfer
COT_INTERROGATED_BY_GROUP: int = 20  # Interrogated by group interrogation
COT_INTERROGATED_BY_STATION: int = 21  # Interrogated by station interrogation

# IEC 104 Qualifier of Interrogation (QOI)
QOI_STATION: int = 20  # Station interrogation (global)
QOI_GROUP_1: int = 21  # Group 1 interrogation
QOI_GROUP_16: int = 36  # Group 16 interrogation

# IEC 104 Qualifier of Command (QU)
QU_SHORT_PULSE: int = 0  # Short pulse
QU_LONG_PULSE: int = 1   # Long pulse
QU_PERSISTENT: int = 2   # Persistent output
QU_NO_CMD: int = 3       # No additional definition

# IEC 104 Select/Qualifier (S/E)
SE_EXECUTE: int = 0  # Execute
SE_SELECT: int = 1   # Select


@dataclass
class Iec104Asdu:
    """
    Represents an IEC 104 ASDU (Application Service Data Unit).

    The ASDU is the core data structure containing the actual
    telecontrol information.
    """

    type_id: int
    cot: int  # Cause of Transmission
    asdu_address: int  # Common ASDU address (station)
    ioa: int  # Information Object Address
    value: Any = None
    quality: int = 0x00
    timestamp: float = 0.0
    select: int = SE_EXECUTE


@dataclass
class Iec104Connection:
    """Represents an active IEC 104 connection."""

    socket: socket.socket
    addr: Tuple[str, int]
    started: bool = False
    send_seq: int = 0  # Send sequence number
    recv_seq: int = 0  # Receive sequence number
    last_received: float = 0.0
    last_sent: float = 0.0


class Iec104Engine(ProtocolEngine):
    """
    IEC 60870-5-104 protocol engine.

    Maps physics-backed device signals to IEC 104 ASDUs with
    appropriate Type IDs and Information Object Addresses.

    Signal Mapping:
    - Analog signals -> M_ME_NC_1 (short floating point) ASDUs
    - Binary/Discrete signals -> M_SP_NA_1 (single point) ASDUs
    - Counter signals -> M_IT_NA_1 (integrated totals) ASDUs
    - Command signals -> C_SC_NA_1 / C_SE_NC_1 ASDUs
    - Each signal gets a unique IOA within the station ASDU address

    External Commands:
    - C_SC_NA_1 (single command) ASDUs from the control station
    - C_SE_NC_1 (setpoint command) ASDUs from the control station
    - Maps to device signal writes in the physics simulation
    """

    def __init__(
        self,
        name: str = "iec104",
        config: Optional[ProtocolConfig] = None,
        simulation: Optional[SimulationManager] = None,
        host: str = "0.0.0.0",
        port: int = 2404,
        asdu_address: int = 1,
        station_name: str = "ICS_SUBSTATION_01",
    ):
        super().__init__(name, config or ProtocolConfig(), simulation)
        self.host = host
        self.port = port
        self.asdu_address = asdu_address
        self.station_name = station_name

        self._server_socket: Optional[socket.socket] = None
        self._connections: Dict[Tuple[str, int], Iec104Connection] = {}
        self._signal_to_ioa: Dict[str, int] = {}
        self._ioa_to_signal: Dict[int, str] = {}
        self._next_ioa: int = 1
        self._lock = threading.Lock()
        self._accept_thread: Optional[threading.Thread] = None

    @property
    def protocol_name(self) -> str:
        """Return the protocol name."""
        return "iec104"

    def _allocate_ioa(self, signal_name: str) -> int:
        """Allocate an Information Object Address for a signal."""
        if signal_name in self._signal_to_ioa:
            return self._signal_to_ioa[signal_name]

        ioa = self._next_ioa
        self._next_ioa += 1
        self._signal_to_ioa[signal_name] = ioa
        self._ioa_to_signal[ioa] = signal_name

        logger.debug(f"Allocated IOA {ioa} for signal '{signal_name}'")
        return ioa

    def _get_type_id_for_signal(self, device: Device, signal_name: str) -> int:
        """Determine the IEC 104 Type ID for a signal."""
        state = device.get_signal(signal_name)
        if not state:
            return M_ME_NC_1

        profile = state.profile
        if profile.signal_type.value in ("binary", "discrete"):
            return M_SP_NA_1
        elif profile.signal_type.value == "counter":
            return M_IT_NA_1
        else:
            return M_ME_NC_1

    def _get_command_type_id_for_signal(
        self, device: Device, signal_name: str
    ) -> int:
        """Determine the command Type ID for a signal."""
        state = device.get_signal(signal_name)
        if not state:
            return C_SE_NC_1

        profile = state.profile
        if profile.signal_type.value in ("binary", "discrete"):
            return C_SC_NA_1
        else:
            return C_SE_NC_1

    def _build_apci_header(
        self, frame_type: int, send_seq: int = 0, recv_seq: int = 0
    ) -> bytes:
        """
        Build an APCI (Application Protocol Control Information) header.

        For I-frames: control field contains send and receive sequence numbers
        For S-frames: control field contains receive sequence number only
        For U-frames: control field contains command code
        """
        if frame_type == APCI_TYPE_I:
            # I-frame: send_seq in bits 15-1, recv_seq in bits 31-16
            control = (send_seq << 1) | ((recv_seq << 1) << 16)
        elif frame_type == APCI_TYPE_S:
            # S-frame: 0x0001 in bits 1-0, recv_seq in bits 31-16
            control = 0x0001 | ((recv_seq << 1) << 16)
        else:
            # U-frame: command code in bits 7-2
            control = send_seq  # send_seq holds the U-frame command

        # APCI: Start byte (0x68) + Length + Control field (4 bytes)
        header = struct.pack("<BB", 0x68, 0x04)  # Length = 4 (no ASDU)
        header += struct.pack("<I", control)
        return header

    def _build_i_frame(
        self, asdu: Iec104Asdu, send_seq: int, recv_seq: int
    ) -> bytes:
        """
        Build an I-frame (Information frame) with ASDU payload.

        I-frames carry the actual telecontrol data.
        """
        # Build ASDU
        asdu_data = self._build_asdu(asdu)

        # Build APCI header with sequence numbers
        apci = self._build_apci_header(APCI_TYPE_I, send_seq, recv_seq)

        # Update length byte to include ASDU
        total_length = 4 + len(asdu_data)  # 4 = control field size
        frame = bytearray(apci)
        frame[1] = total_length  # Update length
        frame += asdu_data

        return bytes(frame)

    def _build_asdu(self, asdu: Iec104Asdu) -> bytes:
        """
        Build an ASDU (Application Service Data Unit).

        ASDU structure:
        - Type ID (1 byte)
        - Variable Structure Qualifier (1 byte): number of objects + SQ bit
        - Cause of Transmission (2 bytes): COT + originator address
        - Common ASDU Address (2 bytes)
        - Information Object Address (3 bytes)
        - Information Object Data (variable)
        """
        data = bytearray()

        # Type ID
        data.append(asdu.type_id)

        # Variable Structure Qualifier (VSQ)
        # Bit 7 = SQ (sequence flag), Bits 6-0 = number of objects
        vsq = 0x01  # Single object, not sequenced
        data.append(vsq)

        # Cause of Transmission (COT)
        # Byte 0: COT, Byte 1: originator address (0 = station)
        data += struct.pack("<HB", asdu.cot, 0x00)

        # Common ASDU Address (2 bytes)
        data += struct.pack("<H", asdu.asdu_address)

        # Information Object Address (3 bytes)
        data += struct.pack("<I", asdu.ioa)[:3]

        # Information Object Data (depends on Type ID)
        data += self._build_asdu_data(asdu)

        logger.debug(
            f"Built ASDU: type={asdu.type_id}, COT={asdu.cot}, ASDU addr={asdu.asdu_address}, "
                f"IOA={asdu.ioa}, value={asdu.value}"
        )
        return bytes(data)

    def _build_asdu_data(self, asdu: Iec104Asdu) -> bytes:
        """Build the information object data for an ASDU."""
        if asdu.type_id == M_SP_NA_1:
            # Single-point: SIQ (Status and Indication Qualifier)
            # Bit 0 = SP (signal value), Bits 1-3 = quality, Bit 4 = BL, Bit 5 = SB, Bit 6 = NT, Bit 7 = IV
            siq = (1 if asdu.value else 0) | (asdu.quality << 1)
            return struct.pack("<B", siq)

        elif asdu.type_id == M_ME_NC_1:
            # Short floating point: IEEE 754 float + quality
            data = struct.pack("<f", float(asdu.value))
            data += struct.pack("<B", asdu.quality)
            return data

        elif asdu.type_id == M_IT_NA_1:
            # Integrated totals: 4-byte counter + quality
            data = struct.pack("<I", int(asdu.value))
            data += struct.pack("<B", asdu.quality)
            return data

        elif asdu.type_id == C_SC_NA_1:
            # Single command: SCO (Single Command Qualifier)
            # Bit 0 = S/E (select/execute), Bit 1 = QU (qualifier), Bit 2-6 = reserved, Bit 7 = DCS
            sco = (asdu.select & 0x01) | (QU_SHORT_PULSE << 1) | ((1 if asdu.value else 0) << 7)
            return struct.pack("<B", sco)

        elif asdu.type_id == C_SE_NC_1:
            # Setpoint command, short floating point: float + qualifier
            data = struct.pack("<f", float(asdu.value))
            # Qualifier: S/E bit + reserved
            qos = asdu.select & 0x01
            data += struct.pack("<B", qos)
            return data

        else:
            logger.warning(f"Unsupported Type ID for ASDU data: {asdu.type_id}")
            return b"\x00"

    def _parse_asdu(self, data: bytes) -> Optional[Iec104Asdu]:
        """
        Parse an ASDU from received data.

        Returns an Iec104Asdu object, or None if parsing fails.
        """
        if len(data) < 10:
            return None

        try:
            type_id = data[0]
            vsq = data[1]
            cot = struct.unpack_from("<H", data, 2)[0]
            asdu_address = struct.unpack_from("<H", data, 4)[0]
            ioa = struct.unpack_from("<I", data, 6)[0] & 0xFFFFFF

            # Parse data based on Type ID
            value = None
            select = SE_EXECUTE

            if type_id == C_SC_NA_1 and len(data) >= 10:
                sco = data[9]
                value = bool((sco >> 7) & 0x01)
                select = sco & 0x01

            elif type_id == C_SE_NC_1 and len(data) >= 14:
                value = struct.unpack_from("<f", data, 9)[0]
                select = data[13] & 0x01

            asdu = Iec104Asdu(
                type_id=type_id,
                cot=cot,
                asdu_address=asdu_address,
                ioa=ioa,
                value=value,
                select=select,
            )

            logger.debug(
                f"Parsed ASDU: type={type_id}, COT={cot}, ASDU addr={asdu_address}, IOA={ioa}, "
                    f"value={value}"
            )
            return asdu

        except (struct.error, IndexError) as e:
            logger.error(f"Failed to parse ASDU: {e}")
            return None

    def _handle_u_frame(
        self, command: int, conn: Iec104Connection
    ) -> Optional[bytes]:
        """Handle a U-frame (Unnumbered frame) command."""
        if command == U_STARTDT:
            conn.started = True
            logger.info(
                f"STARTDT received from {conn.addr[0]}:{conn.addr[1]}"
            )
            return self._build_apci_header(APCI_TYPE_U, U_STARTDT_CON)

        elif command == U_STOPDT:
            conn.started = False
            logger.info(
                f"STOPDT received from {conn.addr[0]}:{conn.addr[1]}"
            )
            return self._build_apci_header(APCI_TYPE_U, U_STOPDT_CON)

        elif command == U_TESTFR:
            logger.debug(
                f"TESTFR received from {conn.addr[0]}:{conn.addr[1]}"
            )
            return self._build_apci_header(APCI_TYPE_U, U_TESTFR_CON)

        return None

    def _handle_i_frame(
        self, data: bytes, conn: Iec104Connection
    ) -> Optional[bytes]:
        """
        Handle an I-frame (Information frame).

        Processes command ASDUs from the control station and
        sends back confirmation ASDUs.
        """
        if len(data) < 6:
            return None

        # Parse ASDU from the data (after APCI header)
        asdu_data = data[4:]  # Skip APCI control field
        asdu = self._parse_asdu(asdu_data)
        if not asdu:
            return None

        # Process command ASDUs
        if asdu.type_id in (C_SC_NA_1, C_SE_NC_1):
            signal_name = self._ioa_to_signal.get(asdu.ioa)
            if signal_name and asdu.value is not None:
                logger.info(
                    f"IEC 104 command: IOA={asdu.ioa} ({signal_name}) = {asdu.value}"
                )

                # Update the simulation
                if self.simulation:
                    for cluster in self.simulation.clusters.values():
                        for device in cluster.devices.values():
                            if signal_name in device.signals:
                                self.handle_command(
                                    device.device_id,
                                    signal_name,
                                    float(asdu.value),
                                )
                                break

                # Send activation confirmation
                conf_asdu = Iec104Asdu(
                    type_id=asdu.type_id,
                    cot=COT_ACTIVATION_CON,
                    asdu_address=self.asdu_address,
                    ioa=asdu.ioa,
                    value=asdu.value,
                )
                return self._build_i_frame(
                    conf_asdu, conn.send_seq, conn.recv_seq
                )

        # Handle interrogation commands
        if asdu.type_id == 100:  # C_IC_NA_1 (interrogation command)
            qoi = asdu.value if asdu.value else QOI_STATION
            logger.info(
                f"Interrogation command: QOI={qoi} from {conn.addr[0]}:{conn.addr[1]}"
            )
            # Send interrogation confirmation
            conf_asdu = Iec104Asdu(
                type_id=100,
                cot=COT_ACTIVATION_CON,
                asdu_address=self.asdu_address,
                ioa=0,
                value=qoi,
            )
            return self._build_i_frame(
                conf_asdu, conn.send_seq, conn.recv_seq
            )

        return None

    def _handle_client(
        self, client_socket: socket.socket, addr: Tuple[str, int]
    ) -> None:
        """Handle a single IEC 104 client connection."""
        logger.info(f"IEC 104 client connected: {addr[0]}:{addr[1]}")

        conn = Iec104Connection(
            socket=client_socket,
            addr=addr,
        )

        with self._lock:
            self._connections[addr] = conn

        try:
            buffer = b""
            while True:
                data = client_socket.recv(4096)
                if not data:
                    break

                buffer += data
                conn.last_received = time.time()

                # Process complete frames
                while len(buffer) >= 2:
                    if buffer[0] != 0x68:
                        logger.warning(
                            f"Invalid start byte from {addr}: 0x{buffer[0]:02X}"
                        )
                        buffer = buffer[1:]
                        continue

                    length = buffer[1]
                    if length < 4:
                        buffer = buffer[2:]
                        continue

                    frame_length = 2 + length  # Start + Length + Control + ASDU
                    if len(buffer) < frame_length:
                        break

                    frame = buffer[:frame_length]
                    buffer = buffer[frame_length:]

                    # Parse control field to determine frame type
                    control = struct.unpack_from("<I", frame, 2)[0]

                    if control & 0x03 == APCI_TYPE_U:
                        # U-frame
                        command = control & 0xFF
                        response = self._handle_u_frame(command, conn)
                        if response:
                            client_socket.sendall(response)
                            conn.last_sent = time.time()

                    elif control & 0x03 == APCI_TYPE_S:
                        # S-frame (acknowledgment)
                        conn.recv_seq = (control >> 16) & 0x7FFF
                        logger.debug(
                            f"S-frame from {addr}: recv_seq={conn.recv_seq}"
                        )

                    else:
                        # I-frame
                        send_seq = (control >> 1) & 0x7FFF
                        recv_seq = (control >> 17) & 0x7FFF
                        conn.send_seq = send_seq
                        conn.recv_seq = recv_seq

                        response = self._handle_i_frame(frame, conn)
                        if response:
                            client_socket.sendall(response)
                            conn.last_sent = time.time()

        except ConnectionResetError:
            logger.debug(f"IEC 104 client {addr} reset connection")
        except Exception as e:
            logger.error(f"IEC 104 client handler error for {addr}: {e}")
        finally:
            with self._lock:
                self._connections.pop(addr, None)
            client_socket.close()
            logger.info(f"IEC 104 client disconnected: {addr[0]}:{addr[1]}")

    def _start_engine(self) -> None:
        """Start the IEC 104 TCP server."""
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
            f"IEC 104 server listening on {self.host}:{self.port} "
            f"(ASDU address={self.asdu_address})"
        )

        # Start accept thread
        self._accept_thread = threading.Thread(
            target=self._accept_loop,
            name=f"{self.name}-accept",
            daemon=True,
        )
        self._accept_thread.start()

    def _accept_loop(self) -> None:
        """Accept incoming IEC 104 connections."""
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
        """Stop the IEC 104 TCP server."""
        self._running = False
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception as e:
                logger.error(f"Error closing server socket: {e}")
        with self._lock:
            for conn in self._connections.values():
                try:
                    conn.socket.close()
                except Exception:
                    pass
            self._connections.clear()
        logger.info("IEC 104 server stopped")

    def _publish_device_values(self, device: Device) -> None:
        """Publish device signal values as IEC 104 ASDUs."""
        for signal_name, state in device.signals.items():
            ioa = self._allocate_ioa(signal_name)
            type_id = self._get_type_id_for_signal(device, signal_name)

            asdu = Iec104Asdu(
                type_id=type_id,
                cot=COT_PERIODIC,
                asdu_address=self.asdu_address,
                ioa=ioa,
                value=state.current_value,
                quality=0x00,
                timestamp=state.timestamp,
            )

            # Send to all connected and started clients
            with self._lock:
                for conn in self._connections.values():
                    if not conn.started:
                        continue

                    try:
                        frame = self._build_i_frame(
                            asdu, conn.send_seq, conn.recv_seq
                        )
                        conn.socket.sendall(frame)
                        conn.send_seq = (conn.send_seq + 1) & 0x7FFF
                        conn.last_sent = time.time()
                    except Exception as e:
                        logger.error(
                            f"Failed to send to {conn.addr}: {e}"
                        )

            logger.debug(
                f"Published signal '{signal_name}' (IOA={ioa}): {state.current_value}"
            )

    def _handle_external_command(
        self, device_id: str, signal_name: str, value: float
    ) -> None:
        """Handle an external IEC 104 write command."""
        logger.info(
            f"IEC 104 external command: {device_id}.{signal_name} = {value}"
        )
        # Send spontaneous ASDU to all connected clients
        ioa = self._signal_to_ioa.get(signal_name)
        if ioa is not None:
            asdu = Iec104Asdu(
                type_id=M_ME_NC_1,
                cot=COT_SPONTANEOUS,
                asdu_address=self.asdu_address,
                ioa=ioa,
                value=value,
            )
            with self._lock:
                for conn in self._connections.values():
                    if not conn.started:
                        continue
                    try:
                        frame = self._build_i_frame(
                            asdu, conn.send_seq, conn.recv_seq
                        )
                        conn.socket.sendall(frame)
                        conn.send_seq = (conn.send_seq + 1) & 0x7FFF
                    except Exception as e:
                        logger.error(
                            f"Failed to send spontaneous to {conn.addr}: {e}"
                        )
