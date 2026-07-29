"""
WebSocket Protocol Engine.

Implements a WebSocket server that exposes physics-backed device signals
via real-time JSON messages for browser-based dashboards and monitoring
applications.

WebSocket Protocol Overview:
- Upgrades HTTP connection to full-duplex WebSocket connection
- Uses frame-based messaging with opcode identification
- Supports text (UTF-8) and binary frames
- Built-in ping/pong for connection keep-alive
- Secure variant (WSS) available via TLS

Protocol Details:
- Transport: TCP (upgraded from HTTP)
- Default Port: 8765
- WebSocket protocol version 13 (RFC 6455)
- Uses SHA-1 based key exchange for handshake
- Text frames (opcode 0x1) for JSON payloads
- Binary frames (opcode 0x2) for binary data
- Ping/pong frames for connection health monitoring

Signal Mapping:
- All device signals -> JSON message payload
- Real-time streaming of physics simulation values
- Structured JSON format with device metadata
- Client can subscribe to specific devices/signals
- Command messages from client to set signal values
"""

from __future__ import annotations

import hashlib
import json
import logging
import socket
import struct
import threading
import time
import base64
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from src.core.device import Device, SimulationManager
from src.protocols.base import ProtocolConfig, ProtocolEngine, ProtocolState

logger = logging.getLogger(__name__)

# WebSocket opcodes
OPCODE_CONTINUATION: int = 0x0
OPCODE_TEXT: int = 0x1
OPCODE_BINARY: int = 0x2
OPCODE_CLOSE: int = 0x8
OPCODE_PING: int = 0x9
OPCODE_PONG: int = 0xA

# WebSocket magic GUID for handshake
WEBSOCKET_MAGIC_GUID: str = "258EAFA5-E914-47DA-95CA-5AB5DC11B713"

# WebSocket close status codes
CLOSE_NORMAL: int = 1000
CLOSE_GOING_AWAY: int = 1001
CLOSE_PROTOCOL_ERROR: int = 1002
CLOSE_UNSUPPORTED_DATA: int = 1003
CLOSE_INVALID_FRAME: int = 1007
CLOSE_POLICY_VIOLATION: int = 1008
CLOSE_MESSAGE_TOO_BIG: int = 1009
CLOSE_INTERNAL_ERROR: int = 1011


@dataclass
class WsClient:
    """Represents a connected WebSocket client."""

    socket: socket.socket
    addr: Tuple[str, int]
    subscribed_devices: Set[str] = field(default_factory=set)
    subscribed_signals: Set[str] = field(default_factory=set)
    connected_at: float = 0.0
    last_active: float = 0.0
    client_id: str = ""


class WebSocketEngine(ProtocolEngine):
    """
    WebSocket protocol engine.

    Maps physics-backed device signals to real-time JSON messages
    for browser-based visualization and monitoring.

    Message Format (Server -> Client):
    {
        "type": "device_update",
        "device_id": "sensor_01",
        "device_name": "Temperature Sensor",
        "timestamp": 1234567890.123,
        "signals": {
            "temperature": {
                "value": 25.5,
                "unit": "celsius",
                "quality": "good"
            }
        }
    }

    Message Format (Client -> Server - Command):
    {
        "type": "command",
        "device_id": "valve_01",
        "signal": "position",
        "value": 75.0
    }

    External Commands:
    - JSON command messages from connected clients
    - Subscription requests to filter signal updates
    - Maps to device signal writes in the physics simulation
    """

    def __init__(
        self,
        name: str = "websocket",
        config: Optional[ProtocolConfig] = None,
        simulation: Optional[SimulationManager] = None,
        host: str = "0.0.0.0",
        port: int = 8765,
        max_payload_size: int = 65536,
    ):
        super().__init__(name, config or ProtocolConfig(), simulation)
        self.host = host
        self.port = port
        self.max_payload_size = max_payload_size

        self._server_socket: Optional[socket.socket] = None
        self._clients: Dict[Tuple[str, int], WsClient] = {}
        self._lock = threading.Lock()
        self._accept_thread: Optional[threading.Thread] = None
        self._last_broadcast: float = 0.0

    @property
    def protocol_name(self) -> str:
        """Return the protocol name."""
        return "websocket"

    def _compute_accept_key(self, key: str) -> str:
        """Compute the WebSocket accept key from the client key."""
        combined = key + WEBSOCKET_MAGIC_GUID
        sha1 = hashlib.sha1(combined.encode("utf-8")).digest()
        return base64.b64encode(sha1).decode("utf-8")

    def _perform_handshake(
        self, data: bytes, client_socket: socket.socket
    ) -> bool:
        """
        Perform the WebSocket upgrade handshake.

        Parses the HTTP upgrade request and sends the appropriate
        101 Switching Protocols response.
        Returns True if handshake succeeded.
        """
        try:
            request = data.decode("utf-8", errors="replace")
        except Exception as e:
            logger.error(f"Failed to decode handshake: {e}")
            return False

        lines = request.split("\r\n")
        if not lines:
            return False

        # Parse the request line
        request_line = lines[0]
        if "GET" not in request_line or "HTTP/1.1" not in request_line:
            logger.warning("Invalid WebSocket handshake request line")
            return False

        # Parse headers
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()

        # Validate WebSocket upgrade
        upgrade = headers.get("upgrade", "").lower()
        connection = headers.get("connection", "").lower()
        ws_key = headers.get("sec-websocket-key", "")
        ws_version = headers.get("sec-websocket-version", "")

        if "websocket" not in upgrade:
            logger.warning("Not a WebSocket upgrade request")
            return False

        if ws_version != "13":
            logger.warning(f"Unsupported WebSocket version: {ws_version}")
            return False

        if not ws_key:
            logger.warning("Missing Sec-WebSocket-Key")
            return False

        # Compute accept key
        accept_key = self._compute_accept_key(ws_key)

        # Build response
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept_key}\r\n"
            "Sec-WebSocket-Protocol: json\r\n"
            "\r\n"
        )

        client_socket.sendall(response.encode("utf-8"))

        logger.debug(
            f"WebSocket handshake completed for client "
        )
        return True

    def _encode_frame(
        self, data: bytes, opcode: int = OPCODE_TEXT
    ) -> bytes:
        """
        Encode a WebSocket frame.

        Supports payload sizes up to max_payload_size.
        """
        frame = bytearray()
        frame.append(0x80 | opcode)  # FIN + opcode

        length = len(data)
        if length < 126:
            frame.append(length)
        elif length < 65536:
            frame.append(126)
            frame += struct.pack(">H", length)
        else:
            frame.append(127)
            frame += struct.pack(">Q", length)

        frame.extend(data)
        return bytes(frame)

    def _decode_frame(self, data: bytes) -> Optional[Dict[str, Any]]:
        """
        Decode a WebSocket frame.

        Returns a dict with 'opcode', 'payload', and 'mask' keys.
        Returns None if the frame is incomplete or invalid.
        """
        if len(data) < 2:
            return None

        first_byte = data[0]
        second_byte = data[1]

        fin = bool(first_byte & 0x80)
        opcode = first_byte & 0x0F
        masked = bool(second_byte & 0x80)

        payload_length = second_byte & 0x7F
        offset = 2

        if payload_length == 126:
            if len(data) < 4:
                return None
            payload_length = struct.unpack_from(">H", data, offset)[0]
            offset += 2
        elif payload_length == 127:
            if len(data) < 10:
                return None
            payload_length = struct.unpack_from(">Q", data, offset)[0]
            offset += 8

        if payload_length > self.max_payload_size:
            logger.warning(
                f"Frame payload too large: {payload_length} bytes"
            )
            return None

        mask_bytes = None
        if masked:
            if len(data) < offset + 4:
                return None
            mask_bytes = data[offset : offset + 4]
            offset += 4

        if len(data) < offset + payload_length:
            return None

        payload = data[offset : offset + payload_length]

        # Unmask if needed
        if masked and mask_bytes:
            payload = bytes(
                b ^ mask_bytes[i % 4] for i, b in enumerate(payload)
            )

        return {
            "fin": fin,
            "opcode": opcode,
            "payload": payload,
        }

    def _send_message(
        self, client_socket: socket.socket, message: str
    ) -> None:
        """Send a text message to a WebSocket client."""
        try:
            frame = self._encode_frame(
                message.encode("utf-8"), OPCODE_TEXT
            )
            client_socket.sendall(frame)
        except Exception as e:
            logger.error(f"Failed to send message: {e}")

    def _send_close(
        self, client_socket: socket.socket, code: int = CLOSE_NORMAL
    ) -> None:
        """Send a WebSocket close frame."""
        try:
            payload = struct.pack(">H", code)
            frame = self._encode_frame(payload, OPCODE_CLOSE)
            client_socket.sendall(frame)
        except Exception as e:
            logger.debug(f"Error sending close frame: {e}")

    def _send_pong(
        self, client_socket: socket.socket, payload: bytes = b""
    ) -> None:
        """Send a WebSocket pong frame."""
        try:
            frame = self._encode_frame(payload, OPCODE_PONG)
            client_socket.sendall(frame)
        except Exception as e:
            logger.debug(f"Error sending pong: {e}")

    def _build_device_message(self, device: Device) -> str:
        """
        Build a JSON message for a device update.

        Returns a JSON string with the device's current signal values.
        """
        device_dict = device.to_dict()
        message = {
            "type": "device_update",
            "device_id": device.device_id,
            "device_name": device.name,
            "role": device.role.value,
            "protocol": device.protocol,
            "timestamp": time.time(),
            "signals": {
                name: {
                    "value": info["value"],
                    "unit": info["unit"],
                    "type": info["type"],
                    "min": info["min"],
                    "max": info["max"],
                    "percentage": info["percentage"],
                    "quality": "good" if info["stable"] else "transition",
                }
                for name, info in device_dict.get("signals", {}).items()
            },
        }
        return json.dumps(message)

    def _handle_client_message(
        self, frame: Dict[str, Any], client: WsClient
    ) -> None:
        """
        Handle an incoming message from a WebSocket client.

        Processes command messages and subscription requests.
        """
        opcode = frame["opcode"]
        payload = frame["payload"]

        if opcode == OPCODE_CLOSE:
            logger.info(
                f"Client {client.addr} sent close frame"
            )
            self._send_close(client.socket)
            return

        elif opcode == OPCODE_PING:
            logger.debug(f"Ping from {client.addr}")
            self._send_pong(client.socket, payload)
            return

        elif opcode == OPCODE_PONG:
            logger.debug(f"Pong from {client.addr}")
            return

        elif opcode == OPCODE_TEXT:
            try:
                message = json.loads(payload.decode("utf-8"))
                self._process_json_message(message, client)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.warning(
                    f"Invalid JSON from {client.addr}: {e}"
                )
                self._send_message(
                    client.socket,
                    json.dumps({
                        "type": "error",
                        "message": f"Invalid JSON: {str(e)}",
                    }),
                )

        elif opcode == OPCODE_BINARY:
            logger.debug(f"Binary frame from {client.addr}: {len(payload)} bytes")

    def _process_json_message(
        self, message: Dict[str, Any], client: WsClient
    ) -> None:
        """
        Process a JSON message from a client.

        Supported message types:
        - command: Set a signal value
        - subscribe: Subscribe to device/signal updates
        - unsubscribe: Unsubscribe from updates
        - ping: Connection test
        """
        msg_type = message.get("type", "")

        if msg_type == "command":
            device_id = message.get("device_id", "")
            signal_name = message.get("signal", "")
            value = message.get("value")

            if device_id and signal_name is not None and value is not None:
                logger.info(
                    f"WebSocket command from {client.addr}: {device_id}.{signal_name} = {value}"
                )
                self.handle_command(device_id, signal_name, float(value))

                # Send confirmation
                self._send_message(
                    client.socket,
                    json.dumps({
                        "type": "command_ack",
                        "device_id": device_id,
                        "signal": signal_name,
                        "value": float(value),
                        "timestamp": time.time(),
                    }),
                )
            else:
                self._send_message(
                    client.socket,
                    json.dumps({
                        "type": "error",
                        "message": "Invalid command: "
                        "device_id, signal, and value required",
                    }),
                )

        elif msg_type == "subscribe":
            device_id = message.get("device_id", "")
            signal_name = message.get("signal", "")

            if device_id:
                client.subscribed_devices.add(device_id)
                if signal_name:
                    client.subscribed_signals.add(signal_name)

                logger.info(
                    f"Client {client.addr} subscribed to {'all' if not signal_name else signal_name} signals for device '{device_id}'"
                )

                self._send_message(
                    client.socket,
                    json.dumps({
                        "type": "subscribe_ack",
                        "device_id": device_id,
                        "signal": signal_name or "*",
                        "timestamp": time.time(),
                    }),
                )

        elif msg_type == "unsubscribe":
            device_id = message.get("device_id", "")
            signal_name = message.get("signal", "")

            if device_id:
                client.subscribed_devices.discard(device_id)
                if signal_name:
                    client.subscribed_signals.discard(signal_name)

                logger.info(
                    f"Client {client.addr} unsubscribed from device '{device_id}'"
                )

        elif msg_type == "ping":
            self._send_message(
                client.socket,
                json.dumps({
                    "type": "pong",
                    "timestamp": time.time(),
                }),
            )

        elif msg_type == "get_devices":
            # Send list of all devices
            devices_list = []
            if self.simulation:
                for cluster in self.simulation.clusters.values():
                    for device in cluster.devices.values():
                        devices_list.append({
                            "device_id": device.device_id,
                            "name": device.name,
                            "role": device.role.value,
                            "protocol": device.protocol,
                            "signal_count": len(device.signals),
                        })

            self._send_message(
                client.socket,
                json.dumps({
                    "type": "device_list",
                    "devices": devices_list,
                    "timestamp": time.time(),
                }),
            )

        else:
            logger.debug(
                f"Unknown message type '{msg_type}' from {client.addr}"
            )
            self._send_message(
                client.socket,
                json.dumps({
                    "type": "error",
                    "message": f"Unknown message type: {msg_type}",
                }),
            )

    def _handle_client(
        self, client_socket: socket.socket, addr: Tuple[str, int]
    ) -> None:
        """
        Handle a WebSocket client connection.

        Performs the handshake, then enters the message loop.
        """
        logger.info(f"WebSocket client connected: {addr[0]}:{addr[1]}")

        try:
            # Receive HTTP upgrade request
            data = client_socket.recv(4096)
            if not data:
                client_socket.close()
                return

            # Perform WebSocket handshake
            if not self._perform_handshake(data, client_socket):
                client_socket.close()
                return

            client = WsClient(
                socket=client_socket,
                addr=addr,
                connected_at=time.time(),
                last_active=time.time(),
                client_id=f"{addr[0]}:{addr[1]}",
            )

            with self._lock:
                self._clients[addr] = client

            logger.info(
                f"WebSocket client {addr} connected successfully"
            )

            # Send welcome message
            self._send_message(
                client_socket,
                json.dumps({
                    "type": "welcome",
                    "version": "1.0",
                    "server": "IndustrialCommSimulator WebSocket",
                    "timestamp": time.time(),
                }),
            )

            # Message loop
            buffer = b""
            while True:
                data = client_socket.recv(65536)
                if not data:
                    break

                buffer += data
                client.last_active = time.time()

                # Process complete frames
                while True:
                    frame = self._decode_frame(buffer)
                    if frame is None:
                        break

                    # Calculate frame size
                    payload_length = len(frame["payload"])
                    frame_size = 2 + (
                        2 if payload_length >= 126 else
                        8 if payload_length >= 65536 else 0
                    ) + 4 + payload_length  # +4 for mask

                    buffer = buffer[frame_size:]

                    self._handle_client_message(frame, client)

        except ConnectionResetError:
            logger.debug(f"WebSocket client {addr} reset connection")
        except Exception as e:
            logger.error(
                f"WebSocket client handler error for {addr}: {e}"
            )
        finally:
            with self._lock:
                self._clients.pop(addr, None)
            try:
                client_socket.close()
            except Exception:
                pass
            logger.info(
                f"WebSocket client disconnected: {addr[0]}:{addr[1]}"
            )

    def _start_engine(self) -> None:
        """Start the WebSocket server."""
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
            f"WebSocket server listening on {self.host}:{self.port}"
        )

        # Start accept thread
        self._accept_thread = threading.Thread(
            target=self._accept_loop,
            name=f"{self.name}-accept",
            daemon=True,
        )
        self._accept_thread.start()

    def _accept_loop(self) -> None:
        """Accept incoming WebSocket connections."""
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
        """Stop the WebSocket server."""
        self._running = False
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception as e:
                logger.error(f"Error closing server socket: {e}")
        with self._lock:
            for client in list(self._clients.values()):
                try:
                    self._send_close(client.socket, CLOSE_GOING_AWAY)
                    client.socket.close()
                except Exception:
                    pass
            self._clients.clear()
        logger.info("WebSocket server stopped")

    def _publish_device_values(self, device: Device) -> None:
        """Publish device signal values to connected WebSocket clients."""
        if not self._clients:
            return

        message = self._build_device_message(device)
        disconnected: List[Tuple[str, int]] = []

        with self._lock:
            for addr, client in self._clients.items():
                # Check if client is subscribed to this device
                if (client.subscribed_devices and
                    device.device_id not in client.subscribed_devices):
                    continue

                try:
                    self._send_message(client.socket, message)
                    client.last_active = time.time()
                except Exception as e:
                    logger.error(
                        f"Failed to send to {addr}: {e}"
                    )
                    disconnected.append(addr)

            # Clean up disconnected clients
            for addr in disconnected:
                self._clients.pop(addr, None)

        if disconnected:
            logger.info(
                f"Removed {len(disconnected)} disconnected WebSocket clients"
            )

        logger.debug(
            f"Published device '{device.device_id}' to {len(self._clients)} WebSocket clients"
        )

    def _handle_external_command(
        self, device_id: str, signal_name: str, value: float
    ) -> None:
        """Handle an external command and notify WebSocket clients."""
        logger.info(
            f"WebSocket external command: {device_id}.{signal_name} = {value}"
        )
        # Notify clients about the command
        message = json.dumps({
            "type": "command_notification",
            "device_id": device_id,
            "signal": signal_name,
            "value": value,
            "timestamp": time.time(),
        })

        with self._lock:
            for addr, client in list(self._clients.items()):
                if device_id in client.subscribed_devices or not client.subscribed_devices:
                    try:
                        self._send_message(client.socket, message)
                    except Exception as e:
                        logger.error(
                            f"Failed to notify {addr}: {e}"
                        )
