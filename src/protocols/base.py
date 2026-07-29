"""
Base Protocol Engine Interface for Industrial Communication Simulator.

Defines the abstract interface that all protocol engines must implement.
Protocol engines bridge the physics simulation to real industrial protocols.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from threading import Thread
from typing import Any, Dict, List, Optional

from src.core.device import Device, SimulationManager

logger = logging.getLogger(__name__)


class ProtocolState(Enum):
    """State of a protocol engine."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"
    STOPPING = "stopping"


@dataclass
class ProtocolConfig:
    """Base configuration for a protocol engine."""

    enabled: bool = True
    update_interval: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class ProtocolEngine(ABC):
    """
    Abstract base class for all protocol engines.

    Each protocol engine is responsible for:
    1. Exposing physics-backed device signals over its protocol
    2. Receiving external commands and updating the physics simulation
    3. Managing its own lifecycle (start, stop, health checks)
    """

    def __init__(
        self,
        name: str,
        config: ProtocolConfig,
        simulation: Optional[SimulationManager] = None,
    ):
        self.name = name
        self.config = config
        self.simulation = simulation
        self.state = ProtocolState.STOPPED
        self._thread: Optional[Thread] = None
        self._running: bool = False
        self._start_time: float = 0.0
        self._error_count: int = 0
        self._last_error: Optional[str] = None

    @property
    @abstractmethod
    def protocol_name(self) -> str:
        """Return the protocol name (e.g., 'modbus', 'bacnet')."""
        ...

    @abstractmethod
    def _start_engine(self) -> None:
        """Start the protocol engine (e.g., bind ports, connect to broker)."""
        ...

    @abstractmethod
    def _stop_engine(self) -> None:
        """Stop the protocol engine (e.g., close connections)."""
        ...

    @abstractmethod
    def _publish_device_values(self, device: Device) -> None:
        """
        Publish a device's current values over the protocol.

        Called periodically by the update loop.
        """
        ...

    @abstractmethod
    def _handle_external_command(self, device_id: str, signal_name: str, value: float) -> None:
        """
        Handle an external command received via the protocol.

        This allows external systems to write values to the simulation.
        """
        ...

    def start(self) -> None:
        """Start the protocol engine in a background thread."""
        if self.state == ProtocolState.RUNNING:
            logger.warning(f"Protocol '{self.name}' is already running")
            return

        if not self.config.enabled:
            logger.info(f"Protocol '{self.name}' is disabled, skipping start")
            return

        self.state = ProtocolState.STARTING
        self._running = True
        self._start_time = time.time()

        try:
            self._start_engine()
            self.state = ProtocolState.RUNNING
            logger.info(f"Protocol '{self.name}' started successfully")

            # Start the update loop in a background thread
            self._thread = Thread(target=self._run_loop, name=f"{self.name}-protocol", daemon=True)
            self._thread.start()

        except Exception as e:
            self.state = ProtocolState.ERROR
            self._error_count += 1
            self._last_error = str(e)
            logger.error(f"Failed to start protocol '{self.name}': {e}")

    def stop(self) -> None:
        """Stop the protocol engine."""
        if self.state == ProtocolState.STOPPED:
            return

        self.state = ProtocolState.STOPPING
        self._running = False

        try:
            self._stop_engine()
        except Exception as e:
            logger.error(f"Error stopping protocol '{self.name}': {e}")

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

        self.state = ProtocolState.STOPPED
        logger.info(f"Protocol '{self.name}' stopped")

    def _run_loop(self) -> None:
        """Main update loop for the protocol engine."""
        while self._running:
            try:
                self._update()
            except Exception as e:
                self._error_count += 1
                self._last_error = str(e)
                logger.error(f"Error in protocol '{self.name}' update loop: {e}")

            time.sleep(self.config.update_interval)

    def _update(self) -> None:
        """Update the protocol engine - publish device values."""
        if not self.simulation:
            return

        # Get all devices for this protocol and publish their values
        devices = self.simulation.get_devices_by_protocol(self.protocol_name)
        for device in devices:
            try:
                self._publish_device_values(device)
            except Exception as e:
                logger.error(f"Error publishing device '{device.device_id}' on {self.name}: {e}")

    def handle_command(self, device_id: str, signal_name: str, value: float) -> None:
        """
        Handle an external command to set a signal value.

        This is called by protocol-specific listeners (e.g., HTTP endpoints,
        MQTT subscriptions, Modbus write requests).
        """
        if not self.simulation:
            logger.warning(f"Cannot handle command: no simulation attached to '{self.name}'")
            return

        device = self.simulation.get_device(device_id)
        if not device:
            logger.warning(f"Device '{device_id}' not found for command on '{self.name}'")
            return

        device.set_value(signal_name, value)
        logger.info(f"Command: {self.name} set {device_id}.{signal_name} = {value}")

        try:
            self._handle_external_command(device_id, signal_name, value)
        except Exception as e:
            logger.error(f"Error handling command on '{self.name}': {e}")

    @property
    def uptime(self) -> float:
        """Get the engine uptime in seconds."""
        if self.state == ProtocolState.RUNNING:
            return time.time() - self._start_time
        return 0.0

    @property
    def health_status(self) -> Dict[str, Any]:
        """Get the health status of the protocol engine."""
        return {
            "protocol": self.protocol_name,
            "name": self.name,
            "state": self.state.value,
            "uptime": self.uptime,
            "error_count": self._error_count,
            "last_error": self._last_error,
            "enabled": self.config.enabled,
        }

    def __repr__(self) -> str:
        return (
            f"ProtocolEngine(name={self.name}, protocol={self.protocol_name}, "
            f"state={self.state.value})"
        )


class ProtocolRegistry:
    """
    Registry for managing multiple protocol engines.

    Provides lifecycle management and unified access to all protocols.
    """

    def __init__(self):
        self._engines: Dict[str, ProtocolEngine] = {}

    def register(self, engine: ProtocolEngine) -> None:
        """Register a protocol engine."""
        self._engines[engine.name] = engine
        logger.info(f"Registered protocol engine '{engine.name}' ({engine.protocol_name})")

    def unregister(self, name: str) -> None:
        """Unregister a protocol engine."""
        engine = self._engines.pop(name, None)
        if engine:
            engine.stop()
            logger.info(f"Unregistered protocol engine '{name}'")

    def get(self, name: str) -> Optional[ProtocolEngine]:
        """Get a protocol engine by name."""
        return self._engines.get(name)

    def get_by_protocol(self, protocol: str) -> List[ProtocolEngine]:
        """Get all engines for a specific protocol type."""
        return [e for e in self._engines.values() if e.protocol_name == protocol]

    def start_all(self) -> None:
        """Start all registered protocol engines."""
        for name, engine in self._engines.items():
            try:
                engine.start()
            except Exception as e:
                logger.error(f"Failed to start protocol engine '{name}': {e}")

    def stop_all(self) -> None:
        """Stop all registered protocol engines."""
        for name, engine in self._engines.items():
            try:
                engine.stop()
            except Exception as e:
                logger.error(f"Failed to stop protocol engine '{name}': {e}")

    def get_all_health(self) -> Dict[str, Dict[str, Any]]:
        """Get health status of all engines."""
        return {name: engine.health_status for name, engine in self._engines.items()}

    @property
    def engines(self) -> Dict[str, ProtocolEngine]:
        return dict(self._engines)

    @property
    def count(self) -> int:
        return len(self._engines)

    def __repr__(self) -> str:
        return f"ProtocolRegistry(engines={list(self._engines.keys())})"
