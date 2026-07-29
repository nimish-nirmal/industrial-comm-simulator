"""
gRPC Protocol Engine.

Implements a gRPC server that exposes physics-backed device signals
via protobuf-based streaming services. gRPC is a high-performance RPC
framework developed by Google, using Protocol Buffers for interface
definition and message serialization.

gRPC Overview:
- Uses HTTP/2 as the transport protocol
- Protocol Buffers (protobuf) for message serialization
- Supports four service types:
  - Unary RPC: Single request, single response
  - Server Streaming: Single request, stream of responses
  - Client Streaming: Stream of requests, single response
  - Bidirectional Streaming: Stream of requests and responses
- Built-in authentication, load balancing, and health checking
- Code generation for multiple languages

Protocol Details:
- Transport: HTTP/2
- Default Port: 50051
- Uses protobuf for service definition and message serialization
- Supports TLS for secure communication
- Streaming for real-time data updates
- Reflection for service discovery

Service Definitions (conceptual):
- GetDevice(DeviceRequest) returns (DeviceResponse)
- ListDevices(Empty) returns (stream DeviceInfo)
- WatchDevice(DeviceRequest) returns (stream DeviceUpdate)
- SetSignal(SetSignalRequest) returns (SetSignalResponse)
- WatchSignals(WatchRequest) returns (stream SignalUpdate)

Signal Mapping:
- All device signals -> protobuf message fields
- Real-time streaming via server-side streaming RPCs
- Structured messages with device metadata
- Client can subscribe to specific devices/signals
- Unary RPCs for command/control operations
"""

from __future__ import annotations

import json
import logging
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from src.core.device import Device, SimulationManager
from src.protocols.base import ProtocolConfig, ProtocolEngine, ProtocolState

logger = logging.getLogger(__name__)

# gRPC default port
GRPC_PORT: int = 50051

# gRPC frame types (HTTP/2)
GRPC_FRAME_DATA: int = 0x00
GRPC_FRAME_HEADERS: int = 0x01
GRPC_FRAME_PRIORITY: int = 0x02
GRPC_FRAME_RST_STREAM: int = 0x03
GRPC_FRAME_SETTINGS: int = 0x04
GRPC_FRAME_PUSH_PROMISE: int = 0x05
GRPC_FRAME_PING: int = 0x06
GRPC_FRAME_GOAWAY: int = 0x07
GRPC_FRAME_WINDOW_UPDATE: int = 0x08
GRPC_FRAME_CONTINUATION: int = 0x09

# gRPC content-type header
GRPC_CONTENT_TYPE: str = "application/grpc"

# gRPC status codes
GRPC_STATUS_OK: int = 0
GRPC_STATUS_CANCELLED: int = 1
GRPC_STATUS_UNKNOWN: int = 2
GRPC_STATUS_INVALID_ARGUMENT: int = 3
GRPC_STATUS_DEADLINE_EXCEEDED: int = 4
GRPC_STATUS_NOT_FOUND: int = 5
GRPC_STATUS_ALREADY_EXISTS: int = 6
GRPC_STATUS_PERMISSION_DENIED: int = 7
GRPC_STATUS_UNAUTHENTICATED: int = 16
GRPC_STATUS_RESOURCE_EXHAUSTED: int = 8
GRPC_STATUS_FAILED_PRECONDITION: int = 9
GRPC_STATUS_ABORTED: int = 10
GRPC_STATUS_OUT_OF_RANGE: int = 11
GRPC_STATUS_UNIMPLEMENTED: int = 12
GRPC_STATUS_INTERNAL: int = 13
GRPC_STATUS_UNAVAILABLE: int = 14
GRPC_STATUS_DATA_LOSS: int = 15

# gRPC message compression flags
GRPC_COMPRESSION_NONE: int = 0x00
GRPC_COMPRESSION_GZIP: int = 0x01

# gRPC stream identifiers
GRPC_STREAM_ID_CLIENT: int = 1  # Client-initiated stream


@dataclass
class GrpcStream:
    """
    Represents a gRPC stream (HTTP/2 stream).

    Tracks the state of a bidirectional stream between
    the client and server.
    """

    stream_id: int
    client_addr: Tuple[str, int]
    service_method: str = ""
    subscribed_devices: Set[str] = field(default_factory=set)
    subscribed_signals: Set[str] = field(default_factory=set)
    is_watch_stream: bool = False
    is_list_stream: bool = False
    created_at: float = 0.0
    last_active: float = 0.0


@dataclass
class GrpcConnection:
    """Represents a gRPC connection (HTTP/2 session)."""

    socket: socket.socket
    addr: Tuple[str, int]
    streams: Dict[int, GrpcStream] = field(default_factory=dict)
    next_stream_id: int = 3  # Server-initiated streams start at 3
    connected_at: float = 0.0
    last_active: float = 0.0
    settings_received: bool = False


class GrpcEngine(ProtocolEngine):
    """
    gRPC protocol engine.

    Maps physics-backed device signals to gRPC service methods
    using protobuf-style message serialization over HTTP/2.

    Service Methods (conceptual):
    - GetDevice(DeviceRequest) -> DeviceResponse
      Returns current state of a single device
    - ListDevices(Empty) -> stream DeviceInfo
      Lists all available devices
    - WatchDevice(DeviceRequest) -> stream DeviceUpdate
      Real-time streaming of device signal values
    - SetSignal(SetSignalRequest) -> SetSignalResponse
      Sets a signal value on a device
    - WatchSignals(WatchRequest) -> stream SignalUpdate
      Real-time streaming of specific signals

    External Commands:
    - SetSignal RPC calls from gRPC clients
    - Maps to device signal writes in the physics simulation
    """

    def __init__(
        self,
        name: str = "grpc",
        config: Optional[ProtocolConfig] = None,
        simulation: Optional[SimulationManager] = None,
        host: str = "0.0.0.0",
        port: int = 50051,
        max_message_size: int = 4194304,  # 4 MB
    ):
        super().__init__(name, config or ProtocolConfig(), simulation)
        self.host = host
        self.port = port
        self.max_message_size = max_message_size

        self._server_socket: Optional[socket.socket] = None
        self._connections: Dict[Tuple[str, int], GrpcConnection] = {}
        self._lock = threading.Lock()
        self._accept_thread: Optional[threading.Thread] = None

    @property
    def protocol_name(self) -> str:
        """Return the protocol name."""
        return "grpc"

    def _build_grpc_message(
        self, data: bytes, compressed: bool = False
    ) -> bytes:
        """
        Build a gRPC wire-format message.

        Format: 1-byte compression flag + 4-byte length + payload
        """
        compression_flag = GRPC_COMPRESSION_GZIP if compressed else GRPC_COMPRESSION_NONE
        length = len(data)
        header = struct.pack("<BI", compression_flag, length)
        return header + data

    def _parse_grpc_message(self, data: bytes) -> Optional[Dict[str, Any]]:
        """
        Parse a gRPC wire-format message.

        Returns a dict with 'compressed', 'length', and 'payload' keys.
        Returns None if the message is incomplete.
        """
        if len(data) < 5:
            return None

        compression_flag = data[0]
        length = struct.unpack_from("<I", data, 1)[0]

        if len(data) < 5 + length:
            return None

        payload = data[5 : 5 + length]

        return {
            "compressed": compression_flag == GRPC_COMPRESSION_GZIP,
            "length": length,
            "payload": payload,
        }

    def _build_http2_headers(
        self, status: int = 200, content_type: str = GRPC_CONTENT_TYPE
    ) -> bytes:
        """
        Build HTTP/2 HEADERS frame pseudo-headers.

        Returns encoded HPACK-style headers for a gRPC response.
        """
        headers = bytearray()

        # :status pseudo-header
        status_str = str(status).encode("utf-8")
        headers.append(len(b":status"))
        headers.extend(b":status")
        headers.append(len(status_str))
        headers.extend(status_str)

        # content-type header
        ct_bytes = content_type.encode("utf-8")
        headers.append(len(b"content-type"))
        headers.extend(b"content-type")
        headers.append(len(ct_bytes))
        headers.extend(ct_bytes)

        # grpc-status header (initially 0 = OK)
        headers.append(len(b"grpc-status"))
        headers.extend(b"grpc-status")
        headers.append(1)
        headers.append(GRPC_STATUS_OK)

        return bytes(headers)

    def _build_grpc_response(
        self, payload: bytes, status: int = GRPC_STATUS_OK
    ) -> bytes:
        """
        Build a complete gRPC response message.

        Includes the gRPC framing and HTTP/2 headers.
        """
        # Build gRPC message
        grpc_msg = self._build_grpc_message(payload)

        # Build response with headers
        response = bytearray()
        response.extend(self._build_http2_headers(200))
        response.extend(grpc_msg)

        return bytes(response)

    def _build_device_response(self, device: Device) -> bytes:
        """
        Build a protobuf-style device response message.

        Serializes device state into a binary format
        that mimics protobuf encoding.
        """
        device_dict = device.to_dict()
        message = {
            "device_id": device.device_id,
            "name": device.name,
            "role": device.role.value,
            "protocol": device.protocol,
            "signals": {
                name: {
                    "value": info["value"],
                    "unit": info["unit"],
                    "type": info["type"],
                    "min": info["min"],
                    "max": info["max"],
                    "percentage": info["percentage"],
                    "stable": info["stable"],
                }
                for name, info in device_dict.get("signals", {}).items()
            },
            "timestamp": time.time(),
        }
        return json.dumps(message).encode("utf-8")

    def _build_device_info(self, device: Device) -> bytes:
        """Build a device info message (for ListDevices)."""
        message = {
            "device_id": device.device_id,
            "name": device.name,
            "role": device.role.value,
            "protocol": device.protocol,
            "signal_count": len(device.signals),
        }
        return json.dumps(message).encode("utf-8")

    def _build_device_update(self, device: Device) -> bytes:
        """Build a device update message (for WatchDevice)."""
        return self._build_device_response(device)

    def _build_signal_update(
        self, device_id: str, signal_name: str, value: float
    ) -> bytes:
        """Build a signal update message (for WatchSignals)."""
        message = {
            "device_id": device_id,
            "signal": signal_name,
            "value": value,
            "timestamp": time.time(),
        }
        return json.dumps(message).encode("utf-8")

    def _handle_grpc_request(
        self, data: bytes, stream: GrpcStream, conn: GrpcConnection
    ) -> Optional[bytes]:
        """
        Handle a gRPC request message.

        Dispatches to the appropriate service method handler
        based on the stream's service method.
        """
        msg = self._parse_grpc_message(data)
        if not msg:
            return None

        payload = msg["payload"]

        try:
            request = json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(f"Failed to parse gRPC request: {e}")
            return self._build_grpc_response(
                json.dumps({
                    "error": f"Invalid request: {str(e)}",
                }).encode("utf-8"),
                GRPC_STATUS_INVALID_ARGUMENT,
            )

        method = stream.service_method

        if method == "GetDevice":
            return self._handle_get_device(request)
        elif method == "ListDevices":
            return self._handle_list_devices(request, stream)
        elif method == "WatchDevice":
            return self._handle_watch_device(request, stream)
        elif method == "SetSignal":
            return self._handle_set_signal(request)
        elif method == "WatchSignals":
            return self._handle_watch_signals(request, stream)
        else:
            logger.warning(f"Unknown gRPC method: {method}")
            return self._build_grpc_response(
                json.dumps({
                    "error": f"Unknown method: {method}",
                }).encode("utf-8"),
                GRPC_STATUS_UNIMPLEMENTED,
            )

    def _handle_get_device(
        self, request: Dict[str, Any]
    ) -> bytes:
        """Handle a GetDevice unary RPC."""
        device_id = request.get("device_id", "")

        if not device_id:
            return self._build_grpc_response(
                json.dumps({
                    "error": "device_id is required",
                }).encode("utf-8"),
                GRPC_STATUS_INVALID_ARGUMENT,
            )

        device = self.simulation.get_device(device_id) if self.simulation else None
        if not device:
            return self._build_grpc_response(
                json.dumps({
                    "error": f"Device '{device_id}' not found",
                }).encode("utf-8"),
                GRPC_STATUS_NOT_FOUND,
            )

        response_data = self._build_device_response(device)
        logger.info(
            f"gRPC GetDevice: {device_id} -> {len(response_data)} bytes"
        )
        return self._build_grpc_response(response_data)

    def _handle_list_devices(
        self, request: Dict[str, Any], stream: GrpcStream
    ) -> Optional[bytes]:
        """
        Handle a ListDevices server-streaming RPC.

        Returns the first batch of device info. Subsequent
        updates are sent via the publish loop.
        """
        stream.is_list_stream = True

        devices_list = []
        if self.simulation:
            for cluster in self.simulation.clusters.values():
                for device in cluster.devices.values():
                    devices_list.append(self._build_device_info(device))

        # Return all devices in a single response
        response_data = json.dumps({
            "devices": [
                json.loads(d.decode("utf-8")) for d in devices_list
            ],
            "count": len(devices_list),
        }).encode("utf-8")

        logger.info(
            f"gRPC ListDevices: returning {len(devices_list)} devices"
        )
        return self._build_grpc_response(response_data)

    def _handle_watch_device(
        self, request: Dict[str, Any], stream: GrpcStream
    ) -> Optional[bytes]:
        """
        Handle a WatchDevice server-streaming RPC.

        Sets up the stream for real-time device updates.
        The initial response contains the current device state.
        """
        device_id = request.get("device_id", "")
        if not device_id:
            return self._build_grpc_response(
                json.dumps({
                    "error": "device_id is required",
                }).encode("utf-8"),
                GRPC_STATUS_INVALID_ARGUMENT,
            )

        stream.is_watch_stream = True
        stream.subscribed_devices.add(device_id)

        device = self.simulation.get_device(device_id) if self.simulation else None
        if not device:
            return self._build_grpc_response(
                json.dumps({
                    "error": f"Device '{device_id}' not found",
                }).encode("utf-8"),
                GRPC_STATUS_NOT_FOUND,
            )

        response_data = self._build_device_update(device)
        logger.info(
            f"gRPC WatchDevice started: {device_id}"
        )
        return self._build_grpc_response(response_data)

    def _handle_set_signal(
        self, request: Dict[str, Any]
    ) -> bytes:
        """Handle a SetSignal unary RPC."""
        device_id = request.get("device_id", "")
        signal_name = request.get("signal", "")
        value = request.get("value")

        if not device_id or not signal_name or value is None:
            return self._build_grpc_response(
                json.dumps({
                    "error": "device_id, signal, and value are required",
                }).encode("utf-8"),
                GRPC_STATUS_INVALID_ARGUMENT,
            )

        logger.info(
            f"gRPC SetSignal: {device_id}.{signal_name} = {value}"
        )

        self.handle_command(device_id, signal_name, float(value))

        response_data = json.dumps({
            "success": True,
            "device_id": device_id,
            "signal": signal_name,
            "value": float(value),
            "timestamp": time.time(),
        }).encode("utf-8")

        return self._build_grpc_response(response_data)

    def _handle_watch_signals(
        self, request: Dict[str, Any], stream: GrpcStream
    ) -> Optional[bytes]:
        """
        Handle a WatchSignals server-streaming RPC.

        Sets up the stream for real-time signal updates.
        """
        device_id = request.get("device_id", "")
        signal_name = request.get("signal", "")

        if not device_id:
            return self._build_grpc_response(
                json.dumps({
                    "error": "device_id is required",
                }).encode("utf-8"),
                GRPC_STATUS_INVALID_ARGUMENT,
            )

        stream.is_watch_stream = True
        stream.subscribed_devices.add(device_id)
        if signal_name:
            stream.subscribed_signals.add(signal_name)

        logger.info(
            f"gRPC WatchSignals started: {device_id}/{signal_name or '*'}"
        )

        # Return initial state
        device = self.simulation.get_device(device_id) if self.simulation else None
        if device:
            response_data = self._build_device_update(device)
            return self._build_grpc_response(response_data)

        return self._build_grpc_response(
            json.dumps({
                "device_id": device_id,
                "message": "Watching for updates",
            }).encode("utf-8")
        )

    def _handle_client(
        self, client_socket: socket.socket, addr: Tuple[str, int]
    ) -> None:
        """
        Handle a gRPC client connection.

        Manages the HTTP/2 session and dispatches gRPC requests
        to the appropriate service method handlers.
        """
        logger.info(f"gRPC client connected: {addr[0]}:{addr[1]}")

        conn = GrpcConnection(
            socket=client_socket,
            addr=addr,
            connected_at=time.time(),
            last_active=time.time(),
        )

        with self._lock:
            self._connections[addr] = conn

        try:
            buffer = b""
            while True:
                data = client_socket.recv(65536)
                if not data:
                    break

                buffer += data
                conn.last_active = time.time()

                # Process gRPC messages from the buffer
                while len(buffer) >= 5:
                    msg = self._parse_grpc_message(buffer)
                    if msg is None:
                        break

                    msg_size = 5 + msg["length"]
                    buffer = buffer[msg_size:]

                    # Determine the stream and method from context
                    # In a simplified implementation, we use a default stream
                    stream_id = GRPC_STREAM_ID_CLIENT
                    if stream_id not in conn.streams:
                        stream = GrpcStream(
                            stream_id=stream_id,
                            client_addr=addr,
                            service_method="GetDevice",  # Default method
                            created_at=time.time(),
                        )
                        conn.streams[stream_id] = stream

                    stream = conn.streams[stream_id]

                    # Try to determine method from payload
                    try:
                        request = json.loads(msg["payload"].decode("utf-8"))
                        method = request.get("method", stream.service_method)
                        stream.service_method = method
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        pass

                    # Handle the request
                    response = self._handle_grpc_request(
                        msg["payload"], stream, conn
                    )
                    if response:
                        try:
                            client_socket.sendall(response)
                            conn.last_active = time.time()
                        except Exception as e:
                            logger.error(
                                f"Failed to send gRPC response to {addr}: {e}"
                            )
                            break

        except ConnectionResetError:
            logger.debug(f"gRPC client {addr} reset connection")
        except Exception as e:
            logger.error(f"gRPC client handler error for {addr}: {e}")
        finally:
            with self._lock:
                self._connections.pop(addr, None)
            try:
                client_socket.close()
            except Exception:
                pass
            logger.info(f"gRPC client disconnected: {addr[0]}:{addr[1]}")

    def _start_engine(self) -> None:
        """Start the gRPC server."""
        self._server_socket = socket.socket(
            socket.AF_INET, socket.SOCK_STREAM
        )
        self._server_socket.setsockopt(
            socket.SOL_SOCKET, socket.SO_REUSEADDR, 1
        )
        self._server_socket.bind((self.host, self.port))
        self._server_socket.listen(10)
        self._server_socket.settimeout(1.0)

        logger.info(
            f"gRPC server listening on {self.host}:{self.port}"
        )

        # Start accept thread
        self._accept_thread = threading.Thread(
            target=self._accept_loop,
            name=f"{self.name}-accept",
            daemon=True,
        )
        self._accept_thread.start()

    def _accept_loop(self) -> None:
        """Accept incoming gRPC connections."""
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
        """Stop the gRPC server."""
        self._running = False
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception as e:
                logger.error(f"Error closing server socket: {e}")
        with self._lock:
            for conn in list(self._connections.values()):
                try:
                    conn.socket.close()
                except Exception:
                    pass
            self._connections.clear()
        logger.info("gRPC server stopped")

    def _publish_device_values(self, device: Device) -> None:
        """Publish device signal values to gRPC watch streams."""
        if not self._connections:
            return

        # Build device update message
        update_data = self._build_device_update(device)
        grpc_response = self._build_grpc_response(update_data)

        disconnected: List[Tuple[str, int]] = []

        with self._lock:
            for addr, conn in list(self._connections.items()):
                for stream in list(conn.streams.values()):
                    if not stream.is_watch_stream:
                        continue

                    # Check if this stream is watching this device
                    if (stream.subscribed_devices and
                        device.device_id not in stream.subscribed_devices):
                        continue

                    try:
                        conn.socket.sendall(grpc_response)
                        stream.last_active = time.time()
                        conn.last_active = time.time()
                    except Exception as e:
                        logger.error(
                            f"Failed to stream to {addr}: {e}"
                        )
                        disconnected.append(addr)
                        break

            # Clean up disconnected clients
            for addr in disconnected:
                self._connections.pop(addr, None)

        if disconnected:
            logger.info(
                f"Removed {len(disconnected)} disconnected gRPC clients"
            )

        logger.debug(
            f"Published device '{device.device_id}' to {len(self._connections)} gRPC connections"
        )

    def _handle_external_command(
        self, device_id: str, signal_name: str, value: float
    ) -> None:
        """Handle an external gRPC command."""
        logger.info(
            f"gRPC external command: {device_id}.{signal_name} = {value}"
        )
        # Notify watch streams about the command
        update_data = self._build_signal_update(
            device_id, signal_name, value
        )
        grpc_response = self._build_grpc_response(update_data)

        with self._lock:
            for conn in list(self._connections.values()):
                for stream in list(conn.streams.values()):
                    if not stream.is_watch_stream:
                        continue
                    if (stream.subscribed_devices and
                        device_id not in stream.subscribed_devices):
                        continue
                    if (stream.subscribed_signals and
                        signal_name not in stream.subscribed_signals):
                        continue
                    try:
                        conn.socket.sendall(grpc_response)
                    except Exception:
                        pass
