"""
Sparkplug B Protocol Engine.

Implements a Sparkplug B edge node that publishes physics-backed
device signals using the Sparkplug B MQTT payload format.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

import paho.mqtt.client as mqtt

from src.core.device import Device, SimulationManager
from src.protocols.base import ProtocolConfig, ProtocolEngine, ProtocolState

logger = logging.getLogger(__name__)


class SparkplugEngine(ProtocolEngine):
    """
    Sparkplug B protocol engine.

    Implements a Sparkplug B edge node that:
    1. Publishes NBIRTH/DBIRTH messages on startup
    2. Publishes DDATA messages with device signal values
    3. Publishes NDEATH on shutdown
    4. Subscribes to device command topics
    """

    def __init__(
        self,
        name: str = "sparkplug",
        config: Optional[ProtocolConfig] = None,
        simulation: Optional[SimulationManager] = None,
        broker_host: str = "localhost",
        broker_port: int = 1883,
        group_id: str = "IndustrialSim",
        edge_node: str = "simulator-edge-01",
        device_id: str = "sim-device-01",
    ):
        super().__init__(name, config or ProtocolConfig(), simulation)
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.group_id = group_id
        self.edge_node = edge_node
        self.device_id = device_id
        self._client: Optional[mqtt.Client] = None
        self._seq: int = 0
        self._bd_seq: int = 0

    @property
    def protocol_name(self) -> str:
        return "sparkplug"

    def _topic(self, *parts: str) -> str:
        """Build a Sparkplug B topic string."""
        return "/".join(parts)

    def _next_seq(self) -> int:
        """Get next sequence number (0-255)."""
        self._seq = (self._seq + 1) % 256
        return self._seq

    def _publish_nbirth(self) -> None:
        """Publish Node Birth (NBIRTH) message."""
        if not self._client:
            return
        topic = self._topic("spBv1.0", self.group_id, "NBIRTH", self.edge_node)
        payload = json.dumps({
            "timestamp": int(time.time() * 1000),
            "seq": self._next_seq(),
            "bdSeq": self._bd_seq,
            "metrics": [
                {"name": "Node Control/NextBirth", "type": "Boolean", "value": False},
                {"name": "Node Control/Rebirth", "type": "Boolean", "value": False},
            ],
        })
        self._client.publish(topic, payload, qos=1, retain=True)
        logger.info(f"Published NBIRTH for edge node '{self.edge_node}'")

    def _publish_dbirt(self) -> None:
        """Publish Device Birth (DBIRTH) message."""
        if not self._client:
            return
        topic = self._topic("spBv1.0", self.group_id, "DBIRTH", self.edge_node, self.device_id)
        payload = json.dumps({
            "timestamp": int(time.time() * 1000),
            "seq": self._next_seq(),
            "metrics": [
                {"name": "Device Control/NextBirth", "type": "Boolean", "value": False},
                {"name": "Device Control/Rebirth", "type": "Boolean", "value": False},
            ],
        })
        self._client.publish(topic, payload, qos=1, retain=True)
        logger.info(f"Published DBIRTH for device '{self.device_id}'")

    def _publish_ndeath(self) -> None:
        """Publish Node Death (NDEATH) message."""
        if not self._client:
            return
        topic = self._topic("spBv1.0", self.group_id, "NDEATH", self.edge_node)
        payload = json.dumps({
            "timestamp": int(time.time() * 1000),
            "seq": self._next_seq(),
            "bdSeq": self._bd_seq,
        })
        self._client.publish(topic, payload, qos=1, retain=True)
        logger.info(f"Published NDEATH for edge node '{self.edge_node}'")

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: dict, rc: int) -> None:
        """Callback for MQTT connection."""
        if rc == 0:
            logger.info(f"Sparkplug connected to MQTT broker at {self.broker_host}:{self.broker_port}")
            # Publish birth certificates
            self._publish_nbirth()
            self._publish_dbirt()
            # Subscribe to device commands
            cmd_topic = self._topic("spBv1.0", self.group_id, "DCMD", self.edge_node, self.device_id)
            client.subscribe(cmd_topic, qos=1)
        else:
            logger.error(f"Sparkplug MQTT connection failed with code {rc}")

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        """Callback for MQTT messages."""
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            metrics = payload.get("metrics", [])
            for metric in metrics:
                name = metric.get("name", "")
                value = metric.get("value")
                if value is not None:
                    self.handle_command(self.device_id, name, float(value))
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning(f"Invalid Sparkplug command: {e}")

    def _start_engine(self) -> None:
        """Start the Sparkplug B edge node."""
        self._client = mqtt.Client(
            client_id=f"sparkplug-{self.edge_node}",
            clean_session=True,
        )
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.will_set(
            self._topic("spBv1.0", self.group_id, "NDEATH", self.edge_node),
            json.dumps({"timestamp": int(time.time() * 1000), "seq": 0, "bdSeq": self._bd_seq}),
            qos=1,
            retain=True,
        )
        self._client.connect_async(self.broker_host, self.broker_port)
        self._client.loop_start()
        logger.info(f"Sparkplug edge node '{self.edge_node}' starting")

    def _stop_engine(self) -> None:
        """Stop the Sparkplug B edge node."""
        if self._client:
            self._publish_ndeath()
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None
            logger.info("Sparkplug edge node stopped")

    def _publish_device_values(self, device: Device) -> None:
        """Publish device signal values as Sparkplug DDATA."""
        if not self._client:
            return

        topic = self._topic("spBv1.0", self.group_id, "DDATA", self.edge_node, self.device_id)
        metrics = []
        for signal_name, state in device.signals.items():
            metrics.append({
                "name": signal_name,
                "type": "Float" if state.profile.signal_type.value == "analog" else "Boolean",
                "value": state.current_value,
                "unit": state.profile.unit,
                "properties": {
                    "min": state.profile.min_value,
                    "max": state.profile.max_value,
                    "noise": state.profile.noise_amplitude,
                },
            })

        payload = json.dumps({
            "timestamp": int(time.time() * 1000),
            "seq": self._next_seq(),
            "metrics": metrics,
        })
        self._client.publish(topic, payload, qos=1)
        logger.debug(f"Published DDATA for device '{self.device_id}'")

    def _handle_external_command(self, device_id: str, signal_name: str, value: float) -> None:
        """Handle a Sparkplug DCMD message."""
        logger.info(f"Sparkplug command: {device_id}.{signal_name} = {value}")