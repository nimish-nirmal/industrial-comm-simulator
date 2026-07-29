#!/usr/bin/env python3
"""
Industrial Communication Simulator - Main Entry Point.

A production-ready industrial protocol simulator with physics-backed
device values supporting Modbus, BACnet, MQTT, OPC UA, Siemens S7,
HTTP REST API, and Sparkplug B.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.config.settings import load_settings
from src.workflows.manager import WorkflowConfig, WorkflowManager

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Industrial Communication Simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # Run with .env configuration
  %(prog)s --env-file /path/to/.env # Use custom env file
  %(prog)s --list-protocols         # List available protocols
  %(prog)s --dry-run                # Validate config without starting
        """,
    )

    parser.add_argument(
        "--env-file",
        type=str,
        default=None,
        help="Path to .env configuration file (default: ./.env)",
    )
    parser.add_argument(
        "--list-protocols",
        action="store_true",
        help="List available protocol engines and exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration and exit without starting simulation",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        help="Override log level from .env",
    )
    parser.add_argument(
        "--no-auto-start",
        action="store_true",
        help="Don't auto-start protocol engines",
    )
    parser.add_argument(
        "--save-scenario",
        type=str,
        default=None,
        help="Save simulation scenario to file and exit",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show version and exit",
    )

    return parser.parse_args()


def list_protocols() -> None:
    """Display available protocol engines."""
    protocols = [
        ("modbus",     "Modbus TCP server (port 5020)"),
        ("bacnet",     "BACnet/IP server (UDP 47808)"),
        ("mqtt",       "MQTT publisher/subscriber (port 1883)"),
        ("opcua",      "OPC UA server (opc.tcp://:4840)"),
        ("siemens",    "Siemens S7 (Snap7) simulator"),
        ("http",       "HTTP REST API (port 8080)"),
        ("sparkplug",  "Sparkplug B edge node (MQTT)"),
        ("dnp3",       "DNP3 outstation for SCADA/utilities (port 20000)"),
        ("ethernetip", "EtherNet/IP (CIP) for Rockwell Automation (port 44818)"),
        ("profinet",   "PROFINET IO for Siemens industrial Ethernet (port 34964)"),
        ("canopen",    "CANopen for motion control/robotics"),
        ("iec61850",   "IEC 61850 MMS for substation automation (port 102)"),
        ("iec104",     "IEC 60870-5-104 for power telecontrol (port 2404)"),
        ("websocket",  "WebSocket for real-time browser dashboards (port 8765)"),
        ("grpc",       "gRPC for high-performance RPC streaming (port 50051)"),
    ]

    print("=" * 60)
    print("Industrial Communication Simulator - Available Protocols")
    print("=" * 60)
    for name, desc in protocols:
        print(f"  {name:<12} {desc}")
    print("=" * 60)
    print(f"Total: {len(protocols)} protocol engines")
    print()


def show_version() -> None:
    """Display version information."""
    print("Industrial Communication Simulator v1.0.0")
    print("Copyright (c) 2024 Industrial Comm Simulator")
    print("License: MIT")


def main() -> int:
    """Main entry point for the simulator."""
    args = parse_args()

    if args.version:
        show_version()
        return 0

    if args.list_protocols:
        list_protocols()
        return 0

    # Load settings
    try:
        if args.env_file:
            env_path = Path(args.env_file)
            if not env_path.exists():
                logger.error(f"Environment file not found: {args.env_file}")
                return 1
            settings = load_settings(str(env_path))
        else:
            settings = load_settings()

        # Override log level if specified
        if args.log_level:
            settings.log_level = args.log_level

        # Override auto-start
        workflow_config = WorkflowConfig(
            auto_start=not args.no_auto_start,
        )

    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        return 1

    if args.dry_run:
        print("Configuration validated successfully!")
        print(f"  Active protocols: {', '.join(settings.active_protocol_list)}")
        print(f"  Log level: {settings.log_level}")
        print(f"  Physics update interval: {settings.physics.update_interval}s")
        print("Dry run complete. Exiting.")
        return 0

    # Create and initialize workflow manager
    try:
        manager = WorkflowManager(settings=settings, workflow_config=workflow_config)
        manager.initialize()

        # Save scenario if requested
        if args.save_scenario:
            path = manager.save_scenario(args.save_scenario)
            print(f"Scenario saved to: {path}")
            manager.shutdown()
            return 0

        # Run the simulation
        manager.run()
        return 0

    except KeyboardInterrupt:
        logger.info("Simulation interrupted by user")
        return 0
    except Exception as e:
        logger.error(f"Simulation error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
