# Testing & Validation Guide

This document provides comprehensive guidance for testing, validating, and debugging the Industrial Communication Simulator.

## Table of Contents

1. [Quick Start Testing](#quick-start-testing)
2. [Running Test Suite](#running-test-suite)
3. [Manual Testing](#manual-testing)
4. [Protocol-Specific Testing](#protocol-specific-testing)
5. [Debugging Guide](#debugging-guide)
6. [Docker Testing](#docker-testing)
7. [Performance Testing](#performance-testing)
8. [Troubleshooting](#troubleshooting)

---

## Quick Start Testing

### Verify Installation

```bash
# Test physics engine (no dependencies needed)
python3 -c "
import sys; sys.path.insert(0, '.')
from src.core.physics import PhysicsEngine, PhysicsConfig, water_tank_profiles
e = PhysicsEngine(PhysicsConfig(seed=42))
e.add_signals(water_tank_profiles())
v = e.step(1.0)
print(f'✓ Physics engine: {len(v)} signals working')
print(f'  Tank Level: {v[\"Tank Level\"]:.3f}m')
"

# Test device models
python3 -c "
import sys; sys.path.insert(0, '.')
from src.core.device import DeviceConfig, Device, DeviceRole
from src.core.physics import water_tank_profiles
config = DeviceConfig('test', 'Test', role=DeviceRole.TANK, signal_profiles=water_tank_profiles())
device = Device(config)
print(f'✓ Device model: {len(device.signals)} signals')
"

# List available protocols
python3 -m src.main --list-protocols

# Validate configuration
python3 -m src.main --dry-run
```

---

## Running Test Suite

### Install Test Dependencies

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Or install manually
pip install pytest pytest-cov
```

### Run All Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html

# Run specific test file
pytest tests/test_physics.py -v

# Run specific test
pytest tests/test_physics.py::TestPhysicsEngine::test_deterministic_mode -v
```

### Test Structure

```
tests/
├── __init__.py              # Test package
├── conftest.py              # Shared fixtures
├── test_physics.py          # PhysicsEngine tests (20 tests)
└── test_device.py           # Device/Cluster tests (20 tests)
```

### Test Coverage

```bash
# Generate coverage report
pytest tests/ --cov=src --cov-report=term-missing

# Expected coverage: >80% for core modules
# - src/core/physics.py: ~95%
# - src/core/device.py: ~90%
```

---

## Manual Testing

### 1. Start the Simulator

```bash
# Basic start
python3 -m src.main

# With debug logging
python3 -m src.main --log-level DEBUG

# Without auto-start
python3 -m src.main --no-auto-start
```

### 2. Test HTTP REST API

```bash
# Health check
curl http://localhost:8080/health

# List all clusters
curl http://localhost:8080/clusters

# Get cluster details
curl http://localhost:8080/clusters/water-treatment

# List all devices
curl http://localhost:8080/devices

# Get device details
curl http://localhost:8080/devices/tank-01

# Get specific signal
curl http://localhost:8080/devices/tank-01/Tank%20Level

# Set signal value (actuator command)
curl -X POST http://localhost:8080/devices/pump-01/Pump%20Speed \
  -H "Content-Type: application/json" \
  -d '{"value": 1800.0}'
```

### 3. Test MQTT

```bash
# Subscribe to device values (using mosquitto_sub)
mosquitto_sub -h localhost -t "industrial/+/+" -v

# Set a value (publish to command topic)
mosquitto_pub -h localhost -t "industrial/tank-01/Tank Level/set" \
  -m "7.5"
```

### 4. Test Modbus TCP

```bash
# Using modbus-cli (install: pip install modbus-cli)
modbus read 0 --count 2 --host localhost --port 5020

# Write a value
modbus write 0 7.5 --host localhost --port 5020
```

### 5. Test Sparkplug B

```bash
# Subscribe to Sparkplug topics
mosquitto_sub -h localhost -t "spBv1.0/+/+/+" -v

# Expected messages:
# - spBv1.0/IndustrialSim/NBIRTH/simulator-edge-01
# - spBv1.0/IndustrialSim/DBIRTH/simulator-edge-01/sim-device-01
# - spBv1.0/IndustrialSim/DDATA/simulator-edge-01/sim-device-01
```

---

## Protocol-Specific Testing

### Modbus Serial (Virtual TTY)

#### On Linux/macOS:

```bash
# Create virtual serial port pair
socat -d -d pty,raw,echo=0 pty,raw,echo=0

# Output will show two ports, e.g.:
# PTY is /dev/pts/2
# PTY is /dev/pts/3

# Terminal 1: Start simulator in serial mode
MODBUS_MODE=serial MODBUS_SERIAL_PORT=/dev/pts/2 python3 -m src.main

# Terminal 2: Connect Modbus RTU client to other port
modbus-client --port /dev/pts/3 --baudrate 9600
```

#### In Docker:

```bash
# The entrypoint.sh automatically creates virtual serial ports
# when MODBUS_SERIAL_PORT environment variable is set

docker-compose up simulator

# Check logs for virtual port creation
docker logs industrial-simulator
# Output: "Created virtual serial port pair: /dev/pts/2 <-> /dev/pts/3"
```

### DNP3 Testing

```bash
# Install DNP3 client (e.g., OpenDNP3)
# Start simulator with DNP3 enabled
DNP3_ENABLED=true python3 -m src.main

# Connect DNP3 master to port 20000
dnp3-master --host localhost --port 20000 --address 100
```

### EtherNet/IP Testing

```bash
# Start simulator with EtherNet/IP enabled
ETHERNETIP_ENABLED=true python3 -m src.main

# Use Rockwell Automation/ENIP scanner or pycomm3
python3 -c "
from pycomm3 import LogixDriver
plc = LogixDriver('localhost')
plc.open()
print(plc.read('Tag1'))
"
```

### WebSocket Testing

```bash
# Start simulator with WebSocket enabled
WEBSOCKET_ENABLED=true python3 -m src.main

# Connect with wscat
npm install -g wscat
wscat -c ws://localhost:8765

# Or use Python websockets client
python3 -c "
import asyncio
import websockets
import json

async def test():
    async with websockets.connect('ws://localhost:8765') as ws:
        msg = await ws.recv()
        print(f'Received: {json.loads(msg)}')

asyncio.run(test())
"
```

### gRPC Testing

```bash
# Start simulator with gRPC enabled
GRPC_ENABLED=true python3 -m src.main

# Use grpcurl to test
grpcurl -plaintext localhost:50051 list

# Or use Python gRPC client
python3 -c "
import grpc
# Add generated protobuf stubs here
channel = grpc.insecure_channel('localhost:50051')
stub = channel # Replace with actual stub
"
```

---

## Debugging Guide

### Enable Debug Logging

```bash
# Via command line
python3 -m src.main --log-level DEBUG

# Via .env
LOG_LEVEL=DEBUG
```

### Debug Physics Engine

```python
import sys
sys.path.insert(0, '.')

from src.core.physics import PhysicsEngine, PhysicsConfig, water_tank_profiles

# Create engine with debug
config = PhysicsConfig(seed=42, enable_noise=True, enable_drift=True, enable_cross_coupling=True)
engine = PhysicsEngine(config)

# Add signals
engine.add_signals(water_tank_profiles())

# Step and inspect
for i in range(5):
    values = engine.step(1.0)
    state = engine.signals["Tank Level"]
    print(f"Step {i+1}:")
    print(f"  Value: {state.current_value:.3f}")
    print(f"  Noise: {state.noise_component:.3f}")
    print(f"  Drift: {state.drift_component:.3f}")
    print(f"  Coupling: {state.coupling_component:.3f}")
```

### Debug Protocol Engine

```python
import sys
sys.path.insert(0, '.')

from src.config.settings import load_settings
from src.workflows.manager import WorkflowManager

# Load settings
settings = load_settings()

# Create manager
manager = WorkflowManager(settings=settings)

# Initialize
manager.initialize()

# Check protocol health
for name, health in manager.registry.get_all_health().items():
    print(f"{name}: {health['state']}")

# Get simulation status
print(manager.status)
```

### Common Debug Points

1. **Physics not updating**: Check `PHYSICS_UPDATE_INTERVAL` in .env
2. **Protocol not starting**: Check `ACTIVE_PROTOCOLS` and protocol-specific `*_ENABLED` flags
3. **Values not changing**: Ensure noise/drift are enabled (`PHYSICS_ENABLE_NOISE=true`)
4. **Port already in use**: Check for other services on protocol ports
5. **Serial port errors**: Verify `/dev/pts/*` permissions (add user to `dialout` group)

### Log Analysis

```bash
# Filter logs by protocol
grep "Modbus" logs/simulator.log

# Filter by log level
grep "ERROR" logs/simulator.log

# Watch logs in real-time
tail -f logs/simulator.log | grep "Status:"
```

---

## Docker Testing

### Build and Run

```bash
# Build image
docker-compose build

# Start services
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f simulator

# Test HTTP API
curl http://localhost:8080/health

# Stop services
docker-compose down
```

### Test with MQTT Broker

```bash
# Start with Mosquitto
docker-compose up -d mosquitto simulator

# Wait for health check
sleep 10

# Test MQTT
mosquitto_sub -h localhost -t "industrial/+/+" -v

# Stop
docker-compose down
```

### Test Serial Mode in Docker

```bash
# Start with serial mode enabled
docker-compose up -d simulator

# Check logs for virtual port creation
docker logs industrial-simulator | grep "virtual serial port"

# The simulator will create virtual serial ports automatically
```

---

## Performance Testing

### Benchmark Physics Engine

```python
import time
import sys
sys.path.insert(0, '.')

from src.core.physics import PhysicsEngine, PhysicsConfig, water_tank_profiles

config = PhysicsConfig(seed=42)
engine = PhysicsEngine(config)
engine.add_signals(water_tank_profiles())

# Benchmark 1000 steps
start = time.time()
for _ in range(1000):
    engine.step(1.0)
elapsed = time.time() - start

print(f"1000 steps in {elapsed:.2f}s ({1000/elapsed:.0f} steps/sec)")
```

### Benchmark Protocol Publishing

```python
import time
import sys
sys.path.insert(0, '.')

from src.config.settings import load_settings
from src.workflows.manager import WorkflowManager

settings = load_settings()
manager = WorkflowManager(settings=settings)
manager.initialize()

# Benchmark 100 simulation steps
start = time.time()
for _ in range(100):
    manager.simulation.step(1.0)
elapsed = time.time() - start

print(f"100 simulation steps in {elapsed:.2f}s")
print(f"Devices: {sum(len(c.devices) for c in manager.simulation.clusters.values())}")
print(f"Signals: {sum(len(d.signals) for c in manager.simulation.clusters.values() for d in c.devices.values())}")
```

---

## Troubleshooting

### Issue: "No module named 'pydantic'"

**Solution:**
```bash
pip install pydantic pydantic-settings
```

### Issue: "Address already in use" (Port 5020, 8080, etc.)

**Solution:**
```bash
# Find process using port
lsof -i :5020
# or
netstat -tulpn | grep 5020

# Kill process
kill -9 <PID>

# Or change port in .env
MODBUS_TCP_PORT=5021
```

### Issue: "Permission denied" on serial port

**Solution:**
```bash
# Add user to dialout group
sudo usermod -a -G dialout $USER

# Log out and back in, or
newgrp dialout

# For Docker, ensure container has access to /dev/pts/*
```

### Issue: Physics values not changing

**Solution:**
```bash
# Check physics settings
grep PHYSICS .env

# Ensure noise is enabled
PHYSICS_ENABLE_NOISE=true

# Check seed is set
PHYSICS_SEED=42
```

### Issue: Protocol engine in error state

**Solution:**
```bash
# Check logs for error details
python3 -m src.main --log-level DEBUG 2>&1 | grep -A 5 "error"

# Common causes:
# - Missing dependencies (install protocol extras)
# - Port already in use
# - Invalid configuration
```

### Issue: Tests failing

**Solution:**
```bash
# Run with verbose output
pytest tests/ -v --tb=long

# Run specific failing test
pytest tests/test_physics.py::TestPhysicsEngine::test_deterministic_mode -vv

# Check Python version (requires 3.10+)
python3 --version
```

---

## Continuous Integration

### GitHub Actions Example

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install -e ".[dev]"
      - name: Run tests
        run: |
          pytest tests/ --cov=src --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

---

## Validation Checklist

Use this checklist to validate simulator functionality:

- [ ] Physics engine runs without errors
- [ ] All 15 protocol engines can be listed (`--list-protocols`)
- [ ] Configuration loads successfully (`--dry-run`)
- [ ] HTTP API responds on port 8080
- [ ] MQTT publishes and subscribes correctly
- [ ] Modbus TCP reads/writes work
- [ ] Modbus serial (virtual TTY) works
- [ ] Sparkplug B birth/death messages published
- [ ] DNP3 outstation accepts connections
- [ ] WebSocket streams real-time data
- [ ] gRPC service responds
- [ ] Docker container starts and passes health check
- [ ] All tests pass (`pytest tests/`)
- [ ] Test coverage >80%
- [ ] Graceful shutdown works (Ctrl+C)
- [ ] Scenario save/load works

---

## Additional Resources

- **Physics Engine**: See `src/core/physics.py` docstrings
- **Protocol Engines**: See individual `src/protocols/*/engine.py` docstrings
- **Configuration**: See `.env.example` for all options
- **Docker**: See `Dockerfile` and `docker-compose.yml`
- **Examples**: See `configs/water-treatment.yaml`

For issues or questions, check the [GitHub Issues](https://github.com/nimish-nirmal/industrial-comm-simulator/issues) page.