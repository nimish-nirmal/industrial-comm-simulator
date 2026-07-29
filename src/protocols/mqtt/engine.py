"""
MQTT Protocol Engine.

Publishes physics-backed device signals as MQTT topics and
subscribes to command topics for external control.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import paho.mqtt.client as mqtt

from src.core.device import Device, SimulationManager
from src.protocols.base import ProtocolConfig, ProtocolEngine

logger = logging.getLogger(__name__)


class MqttEngine(ProtocolEngine):
    """
    MQTT protocol engine.

    Publishes device signal values to MQTT topics:
        industrial/{device_id}/{signal_name}

    Subscribes to command topics:
        industrial/{device_id}/{signal_name}/set
    """

    def __init__(
        self,
        name: str = "mqtt",
        config: Optional[ProtocolConfig] = None,
        simulation: Optional[SimulationManager] = None,
        broker_host: str = "localhost",
        broker_port: int = 1883,
        username: str = "",
        password: str = "",
        client_id: str = "industrial-simulator",
    ):
        super().__init__(name, config or ProtocolConfig(), simulation)
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.username = username
        self.password = password
        self.client_id = client_id
        self._client: Optional[mqtt.Client] = None
        self._topic_prefix = "industrial"

    @property
    def protocol_name(self) -> str:
        return "mqtt"

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: dict, rc: int) -> None:
        """Callback for MQTT connection."""
        if rc == 0:
            logger.info(f"Connected to MQTT broker at {self.broker_host}:{self.broker_port}")
            # Subscribe to command topics
            client.subscribe(f"{self._topic_prefix}/+/+/set")
        else:
            logger.error(f"MQTT connection failed with code {rc}")

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        """Callback for MQTT messages."""
        try:
            # Parse topic: industrial/{device_id}/{signal_name}/set
            parts = msg.topic.split("/")
            if len(parts) >= 4:
                device_id = parts[1]
                signal_name = parts[2]
                payload = msg.payload.decode("utf-8")
                value = float(payload)
                self.handle_command(device_id, signal_name, value)
        except (ValueError, IndexError) as e:
            logger.warning(f"Invalid MQTT command message: {e}")

    def _start_engine(self) -> None:
        """Start the MQTT client."""
        self._client = mqtt.Client(client_id=self.client_id, clean_session=True)

        if self.username:
            self._client.username_pw_set(self.username, self.password)

        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

        self._client.connect_async(self.broker_host, self.broker_port)
        self._client.loop_start()
        logger.info(f"MQTT client connecting to {self.broker_host}:{self.broker_port}")

    def _stop_engine(self) -> None:
        """Stop the MQTT client."""
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None
            logger.info("MQTT client disconnected")

    def _publish_device_values(self, device: Device) -> None:
        """Publish device signal values to MQTT topics."""
        if not self._client:
            return

        for signal_name, state in device.signals.items():
            topic = f"{self._topic_prefix}/{device.device_id}/{signal_name}"
            payload = json.dumps({
                "value": state.current_value,
                "unit": state.profile.unit,
                "timestamp": state.timestamp,
                "device_id": device.device_id,
                "signal": signal_name,
                "min": state.profile.min_value,
                "max": state.profile.max_value,
                "percentage": state.percentage,
                "stable": state.is_stable,
            })
            self._client.publish(topic, payload, qos=1)
            logger.debug(f"MQTT published {topic}: {state.current_value:.2f}")

    def _handle_external_command(self, device_id: str, signal_name: str, value: float) -> None:
        """Handle an MQTT command message."""
        logger.info(f"MQTT command: {device_id}.{signal_name} = {value}")
