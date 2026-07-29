# Multi-stage build for Industrial Communication Simulator
# Stage 1: Builder
FROM python:3.11-slim-bookworm AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml requirements.txt setup.sh ./
COPY src/ ./src/
COPY configs/ ./configs/

# Install Python dependencies
RUN pip install --no-cache-dir --prefix=/install \
    pydantic>=2.0.0 \
    pydantic-settings>=2.0.0 \
    paho-mqtt>=1.6.0 \
    pymodbus>=3.0.0 \
    python-dotenv>=1.0.0

# Stage 2: Runtime
FROM python:3.11-slim-bookworm

WORKDIR /app

# Install runtime dependencies and socat for virtual serial ports
RUN apt-get update && apt-get install -y --no-install-recommends \
    socat \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY src/ ./src/
COPY configs/ ./configs/
COPY .env.example ./

# Create entrypoint script
COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create directories for data and logs
RUN mkdir -p /app/logs /app/scenarios

# Expose all protocol ports
# Modbus TCP, BACnet, MQTT, OPC UA, HTTP, DNP3, EtherNet/IP, PROFINET,
# IEC 61850, IEC 104, WebSocket, gRPC
EXPOSE 5020 47808 1883 4840 8080 20000 44818 34964 102 2404 8765 50051

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Set entrypoint
ENTRYPOINT ["/entrypoint.sh"]

# Default command
CMD ["python", "-m", "src.main"]