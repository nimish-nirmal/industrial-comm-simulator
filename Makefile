# Makefile for Industrial Communication Simulator
# Provides shortcuts for common development and CI tasks

.PHONY: help install install-all test test-unit test-protocols test-integration \
        lint format typecheck docker-build docker-test ci-local clean

# Default target
help:
	@echo "Industrial Communication Simulator - Development Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install          - Install core dependencies"
	@echo "  make install-all      - Install all protocol dependencies"
	@echo "  make install-dev      - Install development dependencies"
	@echo ""
	@echo "Testing:"
	@echo "  make test             - Run all tests"
	@echo "  make test-unit        - Run unit tests with coverage"
	@echo "  make test-protocols   - Validate all protocol imports"
	@echo "  make test-integration - Run integration tests"
	@echo "  make test-physics     - Run physics engine tests only"
	@echo "  make test-devices     - Run device model tests only"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint             - Run linter (ruff)"
	@echo "  make format           - Format code (black)"
	@echo "  make format-check     - Check formatting without changing"
	@echo "  make typecheck        - Run type checker (mypy)"
	@echo "  make ci-local         - Run all CI checks locally"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-build     - Build Docker image"
	@echo "  make docker-test      - Test Docker image"
	@echo "  make docker-run       - Run simulator in Docker"
	@echo ""
	@echo "Validation:"
	@echo "  make validate-config  - Validate configuration"
	@echo "  make list-protocols   - List available protocols"
	@echo "  make dry-run          - Dry run simulation"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean            - Remove build artifacts and cache"

# Setup
install:
	pip install -e .

install-all:
	pip install -e ".[all]"

install-dev:
	pip install -e ".[dev]"

# Testing
test: test-unit test-protocols

test-unit:
	@echo "Running unit tests..."
	pytest tests/test_physics.py tests/test_device.py -v --cov=src --cov-report=term-missing

test-protocols:
	@echo "Validating protocol imports..."
	@python3 -c "\
		import sys; sys.path.insert(0, '.'); \
		protocols = [('modbus','ModbusEngine'), ('bacnet','BacnetEngine'), ('mqtt','MqttEngine'), \
		             ('opcua','OpcUaEngine'), ('siemens','SiemensEngine'), ('http','HttpEngine'), \
		             ('sparkplug','SparkplugEngine'), ('dnp3','Dnp3Engine'), \
		             ('ethernetip','EthernetIpEngine'), ('profinet','ProfinetEngine'), \
		             ('canopen','CanopenEngine'), ('iec61850','Iec61850Engine'), \
		             ('iec104','Iec104Engine'), ('websocket','WebSocketEngine'), ('grpc','GrpcEngine')]; \
		failed = []; \
		for p,c in protocols: \
			try: \
				m = __import__(f'src.protocols.{p}', fromlist=[c]); \
				e = getattr(m,c)(name='test'); \
				assert e.protocol_name == p; \
				print(f'✓ {p}'); \
			except Exception as e: \
				print(f'✗ {p}: {e}'); \
				failed.append(p); \
		if failed: sys.exit(1); \
		print(f'✓ All {len(protocols)} protocols validated'); \
	"

test-integration:
	@echo "Running integration tests..."
	pytest tests/ -v -m integration

test-physics:
	@echo "Running physics engine tests..."
	pytest tests/test_physics.py -v

test-devices:
	@echo "Running device model tests..."
	pytest tests/test_device.py -v

test-all-protocols:
	@echo "Running all protocol tests..."
	pytest tests/test_all_protocols.py -v

# Code Quality
lint:
	@echo "Running linter..."
	ruff check src/ tests/

format:
	@echo "Formatting code..."
	black src/ tests/

format-check:
	@echo "Checking code formatting..."
	black --check --diff src/ tests/

typecheck:
	@echo "Running type checker..."
	mypy src/ --ignore-missing-imports

# CI - Run all checks locally (simulates GitHub Actions)
ci-local: format-check lint typecheck test test-protocols
	@echo ""
	@echo "========================================="
	@echo "✓ All CI checks passed!"
	@echo "========================================="

# Docker
docker-build:
	@echo "Building Docker image..."
	docker build -t industrial-simulator:test .

docker-test:
	@echo "Testing Docker image..."
	docker run --rm industrial-simulator:test python3 -m src.main --list-protocols
	docker run --rm industrial-simulator:test python3 -m src.main --dry-run

docker-run:
	@echo "Running simulator in Docker..."
	docker-compose up

# Validation
validate-config:
	@echo "Validating configuration..."
	python3 -m src.main --dry-run

list-protocols:
	@echo "Listing available protocols..."
	python3 -m src.main --list-protocols

dry-run:
	@echo "Running dry-run..."
	python3 -m src.main --dry-run

# Cleanup
clean:
	@echo "Cleaning up..."
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf .ruff_cache
	rm -rf htmlcov
	rm -rf .coverage
	rm -rf coverage.xml
	rm -rf dist
	rm -rf build
	rm -rf *.egg-info
	@echo "Cleanup complete!"

# Quick validation (fast checks)
quick-test:
	@echo "Running quick validation..."
	@python3 -c "import sys; sys.path.insert(0, '.'); from src.core.physics import PhysicsEngine, PhysicsConfig, water_tank_profiles; e = PhysicsEngine(PhysicsConfig(seed=42)); e.add_signals(water_tank_profiles()); v = e.step(1.0); print(f'✓ Physics: {len(v)} signals')"
	@python3 -c "import sys; sys.path.insert(0, '.'); from src.core.device import DeviceConfig, Device, DeviceRole; from src.core.physics import water_tank_profiles; d = Device(DeviceConfig('test', 'Test', role=DeviceRole.TANK, signal_profiles=water_tank_profiles())); print(f'✓ Device: {len(d.signals)} signals')"
	@echo "✓ Quick validation passed! (Note: Config validation requires 'make install' first)"
