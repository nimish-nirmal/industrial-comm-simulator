#!/bin/bash
# Docker entrypoint script for Industrial Communication Simulator
# Handles virtual serial port setup and graceful shutdown

set -e

echo "========================================"
echo "Industrial Communication Simulator"
echo "Docker Entrypoint"
echo "========================================"

# Function to handle shutdown signals
shutdown() {
    echo ""
    echo "Received shutdown signal, stopping simulator..."
    kill -TERM "$SIMULATOR_PID" 2>/dev/null || true
    wait "$SIMULATOR_PID" 2>/dev/null || true
    echo "Simulator stopped."
    exit 0
}

# Trap SIGTERM and SIGINT
trap shutdown SIGTERM SIGINT

# Create virtual serial ports if MODBUS_SERIAL_PORT is set
if [ -n "$MODBUS_SERIAL_PORT" ]; then
    echo "Setting up virtual serial ports..."
    
    # Create a pair of virtual serial ports using socat
    # Format: /dev/pts/N <-> /dev/pts/M
    PTS1=$(socat -d -d pty,raw,echo=0 pty,raw,echo=0 2>&1 | grep "PTY is" | head -1 | sed 's/.*PTY is //')
    PTS2=$(socat -d -d pty,raw,echo=0 pty,raw,echo=0 2>&1 | grep "PTY is" | tail -1 | sed 's/.*PTY is //')
    
    if [ -n "$PTS1" ] && [ -n "$PTS2" ]; then
        echo "Created virtual serial port pair:"
        echo "  Port 1: $PTS1"
        echo "  Port 2: $PTS2"
        
        # Link the two ports
        socat $PTS1,raw,echo=0 $PTS2,raw,echo=0 &
        SOCAT_PID=$!
        
        # Set the serial port environment variable
        export MODBUS_SERIAL_PORT=$PTS1
        echo "Modbus serial port set to: $MODBUS_SERIAL_PORT"
    else
        echo "WARNING: Failed to create virtual serial ports"
    fi
fi

# Create logs directory if it doesn't exist
mkdir -p /app/logs /app/scenarios

# Display configuration
echo ""
echo "Starting simulator with configuration:"
echo "  Active protocols: ${ACTIVE_PROTOCOLS:-modbus,bacnet,mqtt,opcua,siemens,http,sparkplug}"
echo "  Log level: ${LOG_LEVEL:-INFO}"
echo "  Physics update interval: ${PHYSICS_UPDATE_INTERVAL:-1.0}s"
echo ""

# Start the simulator
echo "Starting simulator..."
python -m src.main &
SIMULATOR_PID=$!

# Wait for the simulator process
wait $SIMULATOR_PID
SIMULATOR_EXIT=$?

# Cleanup
if [ -n "$SOCAT_PID" ]; then
    echo "Cleaning up virtual serial ports..."
    kill $SOCAT_PID 2>/dev/null || true
fi

echo "Entrypoint script exiting with code: $SIMULATOR_EXIT"
exit $SIMULATOR_EXIT