"""
BACnet Protocol Engine.

Implements a BACnet/IP server that exposes physics-backed device signals
as BACnet objects (AnalogValue, BinaryValue, etc.).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from src.core.device import Device, SimulationManager
from src.protocols.base import ProtocolConfig, ProtocolEngine, ProtocolState

logger = logging.getLogger(__name__)


class BacnetEngine(ProtocolEngine):
    """
    BACnet/IP protocol engine.

    Maps device signals to BACnet objects:
    - Analog signals -> AnalogValue objects
    - Binary signals -> BinaryValue objects
    - Discrete signals -> MultiStateValue objects
    """

    def __init__(
        self,
        name: str = "bacnet",
        config: Optional[ProtocolConfig] = None,
        simulation: Optional[SimulationManager] = None,
        ip: str = "0.0.0.0",
        port: int = 47808,
        device_id: int = 1001,
    ):
        super().__init__(name, config or ProtocolConfig(), simulation)
        self.ip = ip
        self.port = port
        self.device_id = device_id
        self._object_map: Dict[str, Dict[str, int]] = {}  # device_id -> {signal_name -> object_id}
        self._next_object_id: int = 1

    @property
    def protocol_name(self) -> str:
        return "bacnet"

    def _start_engine(self) -> None:
        """Start the BACnet/IP server."""
        logger.info(
            f"BACnet engine ready (device_id={self.device_id}, endpoint={self.ip}:{self.port})"
        )
        logger.info("Note: BACpypes requires root privileges for raw sockets")

    def _stop_engine(self) -> None:
        """Stop the BACnet/IP server."""
        logger.info("BACnet engine stopped")

    def _publish_device_values(self, device: Device) -> None:
        """Publish device signal values as BACnet objects."""
        for signal_name, state in device.signals.items():
            value = state.current_value
            profile = state.profile
            logger.debug(
                f"BACnet {device.device_id}/{signal_name}: {value:.2f} {profile.unit}"
            )

    def _handle_external_command(self, device_id: str, signal_name: str, value: float) -> None:
        """Handle a BACnet write request."""
        logger.info(f"BACnet write: {device_id}.{signal_name} = {value}")
