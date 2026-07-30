"""
HTTP Protocol Engine.

Provides a REST API for accessing and controlling physics-backed
device signals over HTTP.
"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any, Optional
from urllib.parse import urlparse

from src.core.device import Device, SimulationManager
from src.protocols.base import ProtocolConfig, ProtocolEngine

logger = logging.getLogger(__name__)


class _SimulationHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the simulation API."""

    engine: Optional["HttpEngine"] = None

    def _send_json(self, data: Any, status: int = 200) -> None:
        """Send a JSON response."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode("utf-8"))

    def _send_error_json(self, message: str, status: int = 400) -> None:
        """Send an error JSON response."""
        self._send_json({"error": message}, status)

    def do_GET(self) -> None:
        """Handle GET requests."""
        if not self.engine or not self.engine.simulation:
            self._send_error_json("Simulation not available", 503)
            return

        parsed = urlparse(self.path)
        path = parsed.path.strip("/")
        parts = path.split("/") if path else []

        try:
            if not parts or parts[0] == "":
                # GET / - List all clusters
                data = self.engine.simulation.to_dict()
                self._send_json(data)

            elif parts[0] == "clusters":
                if len(parts) == 1:
                    # GET /clusters - List all clusters
                    clusters = {
                        cid: cluster.to_dict()
                        for cid, cluster in self.engine.simulation.clusters.items()
                    }
                    self._send_json(clusters)
                elif len(parts) == 2:
                    # GET /clusters/{cluster_id}
                    cluster = self.engine.simulation.get_cluster(parts[1])
                    if cluster:
                        self._send_json(cluster.to_dict())
                    else:
                        self._send_error_json(f"Cluster '{parts[1]}' not found", 404)
                elif len(parts) == 3:
                    # GET /clusters/{cluster_id}/devices
                    cluster = self.engine.simulation.get_cluster(parts[1])
                    if cluster:
                        devices = {
                            did: device.to_dict()
                            for did, device in cluster.devices.items()
                        }
                        self._send_json(devices)
                    else:
                        self._send_error_json(f"Cluster '{parts[1]}' not found", 404)

            elif parts[0] == "devices":
                if len(parts) == 1:
                    # GET /devices - List all devices
                    all_devices = {}
                    for cluster in self.engine.simulation.clusters.values():
                        for did, device in cluster.devices.items():
                            all_devices[did] = device.to_dict()
                    self._send_json(all_devices)
                elif len(parts) == 2:
                    # GET /devices/{device_id}
                    device = self.engine.simulation.get_device(parts[1])
                    if device:
                        self._send_json(device.to_dict())
                    else:
                        self._send_error_json(f"Device '{parts[1]}' not found", 404)
                elif len(parts) == 3:
                    # GET /devices/{device_id}/{signal_name}
                    device = self.engine.simulation.get_device(parts[1])
                    if device:
                        signal = device.get_signal(parts[2])
                        if signal:
                            self._send_json({
                                "device_id": device.device_id,
                                "signal": parts[2],
                                "value": signal.current_value,
                                "unit": signal.profile.unit,
                                "min": signal.profile.min_value,
                                "max": signal.profile.max_value,
                                "percentage": signal.percentage,
                                "stable": signal.is_stable,
                                "timestamp": signal.timestamp,
                            })
                        else:
                            self._send_error_json(f"Signal '{parts[2]}' not found", 404)
                    else:
                        self._send_error_json(f"Device '{parts[1]}' not found", 404)

            elif parts[0] == "health":
                # GET /health - Health status
                clusters_data = {
                    cid: cluster.to_dict()
                    for cid, cluster in self.engine.simulation.clusters.items()
                }
                self._send_json({
                    "status": "running",
                    "clusters": clusters_data,
                })

            else:
                self._send_error_json(f"Unknown path: {self.path}", 404)

        except Exception as e:
            logger.error(f"HTTP GET error: {e}")
            self._send_error_json(str(e), 500)

    def do_POST(self) -> None:
        """Handle POST requests (commands)."""
        if not self.engine or not self.engine.simulation:
            self._send_error_json("Simulation not available", 503)
            return

        parsed = urlparse(self.path)
        path = parsed.path.strip("/")
        parts = path.split("/") if path else []

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"
            data = json.loads(body)

            if len(parts) >= 3 and parts[0] == "devices":
                # POST /devices/{device_id}/{signal_name}
                device_id = parts[1]
                signal_name = parts[2]
                value = float(data.get("value", 0))
                self.engine.handle_command(device_id, signal_name, value)
                self._send_json({ "status": "ok", "device_id": device_id, "signal": signal_name,
                    "value": value
                })

            else:
                self._send_error_json(f"Unknown path: {self.path}", 404)

        except Exception as e:
            logger.error(f"HTTP POST error: {e}")
            self._send_error_json(str(e), 500)

    def do_OPTIONS(self) -> None:
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        """Override to use our logger."""
        logger.debug(f"HTTP: {format % args}")


class HttpEngine(ProtocolEngine):
    """
    HTTP REST API protocol engine.

    Provides a REST API for monitoring and controlling the simulation:
    - GET  /                          - List all clusters
    - GET  /clusters                  - List all clusters
    - GET  /clusters/{id}             - Get cluster details
    - GET  /devices                   - List all devices
    - GET  /devices/{id}              - Get device details
    - GET  /devices/{id}/{signal}     - Get signal value
    - POST /devices/{id}/{signal}     - Set signal value
    - GET  /health                    - Health check
    """

    def __init__(
        self,
        name: str = "http",
        config: Optional[ProtocolConfig] = None,
        simulation: Optional[SimulationManager] = None,
        host: str = "0.0.0.0",
        port: int = 8080,
    ):
        super().__init__(name, config or ProtocolConfig(), simulation)
        self.host = host
        self.port = port
        self._server: Optional[HTTPServer] = None

    @property
    def protocol_name(self) -> str:
        return "http"

    def _start_engine(self) -> None:
        """Start the HTTP server."""
        _SimulationHandler.engine = self
        self._server = HTTPServer((self.host, self.port), _SimulationHandler)
        server_thread = Thread(target=self._server.serve_forever, daemon=True)
        server_thread.start()
        logger.info(f"HTTP API server started on http://{self.host}:{self.port}")

    def _stop_engine(self) -> None:
        """Stop the HTTP server."""
        if self._server:
            self._server.shutdown()
            self._server = None
            logger.info("HTTP API server stopped")

    def _publish_device_values(self, device: Device) -> None:
        """HTTP engine doesn't actively publish - values are read via API."""
        pass

    def _handle_external_command(self, device_id: str, signal_name: str, value: float) -> None:
        """Handle an HTTP API command."""
        logger.info(f"HTTP command: {device_id}.{signal_name} = {value}")
