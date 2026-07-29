# Industrial Communication Simulator

A **production-ready** industrial protocol simulator with **physics-backed device values**. Simulates realistic industrial processes with noise, drift, and cross-coupling between physical quantities, exposed through multiple industrial protocols simultaneously.

## Features

### 🏭 Physics Engine
- **Realistic signal simulation** with Gaussian noise, thermal drift, and cross-coupling
- **Multiple signal types**: Analog, Discrete, Binary, Counter
- **Pre-built scenarios**: Water treatment, HVAC, Power distribution
- **Customizable profiles**: Min/max bounds, noise amplitude, drift rates, coupling factors
- **Deterministic mode**: Reproducible simulations with configurable seed

### 🔌 Protocol Support (7 Protocols)
| Protocol | Type | Default Port | Status |
|----------|------|-------------|--------|
| **Modbus** | TCP Server | 5020 | ✅ Active |
| **BACnet** | IP Server | 47808 | ✅ Active |
| **MQTT** | Pub/Sub | 1883 | ✅ Active |
| **OPC UA** | Server | 4840 | ✅ Active |
| **Siemens S7** | Snap7 | - | ✅ Active |
| **HTTP** | REST API | 8080 | ✅ Active |
| **Sparkplug B** | Edge Node | 1883 | ✅ Active |

### 📊 Device & Cluster Management
- **Devices**: Sensors, actuators, pumps, valves, motors, compressors, tanks
- **Clusters**: Logical groupings (Water Treatment, HVAC, Power Distribution)
- **Physics-backed**: Every signal evolves realistically over time
- **Cross-coupling**: Related signals influence each other (e.g., temperature affects pressure)

### 🚀 Production Features
- **`.env` configuration** with pydantic-settings validation
- **Health monitoring** with auto-recovery
- **Graceful shutdown** (SIGINT/SIGTERM handling)
- **Scenario save/load** for reproducible simulations
- **Structured logging** with configurable levels
- **CLI interface** with `--help`, `--dry-run`, `--list-protocols`

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/nimish-nirmal/industrial-comm-simulator.git
cd industrial-comm-simulator

# Install with all protocol support
pip install -e ".[all]"

# Or install with specific protocols
pip install -e ".[modbus,mqtt,http]"
```

### Configuration

```bash
# Copy the example environment file
cp .env.example .env

# Edit .env to match your needs
nano .env
```

### Run the Simulator

```bash
# Run with default configuration
python -m src.main

# Run with custom env file
python -m src.main --env-file /path/to/.env

# List available protocols
python -m src.main --list-protocols

# Validate configuration without starting
python -m src.main --dry-run

# Run with debug logging
python -m src.main --log-level DEBUG
```

## Architecture

```
industrial-comm-simulator/
├── src/
│   ├── main.py                    # Entry point with CLI
│   ├── core/
│   │   ├── physics.py             # Physics engine (noise, drift, coupling)
│   │   └── device.py              # Device, Cluster, SimulationManager
│   ├── config/
│   │   └── settings.py            # Pydantic settings from .env
│   ├── protocols/
│   │   ├── base.py                # Abstract ProtocolEngine
│   │   ├── modbus/engine.py       # Modbus TCP server
│   │   ├── bacnet/engine.py       # BACnet/IP server
│   │   ├── mqtt/engine.py         # MQTT pub/sub
│   │   ├── opcua/engine.py        # OPC UA server
│   │   ├── siemens/engine.py      # Siemens S7 (Snap7)
│   │   ├── http/engine.py         # HTTP REST API
│   │   └── sparkplug/engine.py    # Sparkplug B edge node
│   └── workflows/
│       └── manager.py             # Lifecycle management
├── configs/
│   └── water-treatment.yaml       # Example scenario
├── .env.example                   # Environment template
├── pyproject.toml                 # Project configuration
└── README.md
```

## API Reference

### HTTP REST API (Port 8080)

```bash
# List all clusters
curl http://localhost:8080/

# Get cluster details
curl http://localhost:8080/clusters/water-treatment

# List all devices
curl http://localhost:8080/devices

# Get device details
curl http://localhost:8080/devices/tank-01

# Get specific signal value
curl http://localhost:8080/devices/tank-01/Tank%20Level

# Set signal value (actuator command)
curl -X POST http://localhost:8080/devices/pump-01/Pump%20Speed \
  -H "Content-Type: application/json" \
  -d '{"value": 1800.0}'

# Health check
curl http://localhost:8080/health
```

### MQTT Topics

```
# Device values (published)
industrial/{device_id}/{signal_name}

# Commands (subscribe to set values)
industrial/{device_id}/{signal_name}/set
```

### Sparkplug B Topics

```
spBv1.0/{group_id}/NBIRTH/{edge_node}
spBv1.0/{group_id}/DBIRTH/{edge_node}/{device_id}
spBv1.0/{group_id}/DDATA/{edge_node}/{device_id}
spBv1.0/{group_id}/NDEATH/{edge_node}
spBv1.0/{group_id}/DCMD/{edge_node}/{device_id}
```

## Physics Engine

The physics engine simulates realistic industrial process values:

- **Noise**: Gaussian noise simulates sensor inaccuracies
- **Drift**: Gradual value changes over time (thermal drift, calibration drift)
- **Cross-coupling**: Related physical quantities influence each other
  - Tank level → Pressure (higher level = more pressure)
  - Motor speed → Temperature (faster = hotter)
  - Temperature → Humidity (inverse relationship)

### Signal Types

| Type | Description | Example |
|------|-------------|---------|
| `analog` | Continuous value | Temperature, Pressure, Level |
| `discrete` | Integer state | Valve position, Fan speed |
| `binary` | On/Off | Alarm status, Breaker state |
| `counter` | Monotonically increasing | Total flow, Energy meter |

## Development

```bash
# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black src/

# Lint
ruff check src/

# Type check
mypy src/
```

## License

MIT License - see [LICENSE](LICENSE) for details.