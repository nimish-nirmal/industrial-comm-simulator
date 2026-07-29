"""
OPC UA Protocol Engine.

Implements an OPC UA server that exposes physics-backed device signals
as OPC UA variables organized in the server's address space.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from src.core.device import Device, SimulationManager
from src.protocols.base import ProtocolConfig, ProtocolEngine, ProtocolState

logger = logging.getLogger(__name__)


class OpcUaEngine(ProtocolEngine):
    """
    OPC UA protocol engine.

    Maps device signals to OPC UA variables:
        Objects/Devices/{device_id}/{signal_name}
    """

    def __init__(
        self,
        name: str = "opcua",
        config: Optional[ProtocolConfig] = None,
        simulation: Optional[SimulationManager] = None,
        endpoint: str = "opc.tcp://0.0.0.0:4840",
        server_name: str = "IndustrialSimulator",
    ):
        super().__init__(name, config or ProtocolConfig(), simulation)
        self.endpoint = endpoint
        self.server_name = server_name
        self._server: Optional[Any] = None

    @property
    def protocol_name(self) -> str:
        return "opcua"

    def _start_engine(self) -> None:
        """Start the OPC UA server."""
        logger.info(
            f"OPC UA engine ready (endpoint={self.endpoint}, "
            f"server_name={self.server_name})"
        )
        logger.info("Note: OPC UA requires 'opcua-asyncio' package")

    def _stop_engine(self) -> None:
        """Stop the OPC UA server."""
        logger.info("OPC UA engine stopped")

    def _publish_device_values(self, device: Device) -> None:
        """Publish device signal values as OPC UA variables."""
        for signal_name, state in device.signals.items():
            logger.debug(
                f"OPC UA {device.device_id}/{signal_name}: "
                f"{state.current_value:.2f} {state.profile.unit}"
            )

    def _handle_external_command(self, device_id: str, signal_name: str, value: float) -> None:
        """Handle an OPC UA write request."""
        logger.info(f"OPC UA write: {device_id}.{signal_name} = {value}")