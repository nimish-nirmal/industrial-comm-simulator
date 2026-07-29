#!/bin/bash
# Setup script for Industrial Communication Simulator
# Run: chmod +x setup.sh && ./setup.sh

set -e

echo "========================================"
echo "Industrial Communication Simulator Setup"
echo "========================================"

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "Installing core dependencies..."
pip install pydantic>=2.0.0 pydantic-settings>=2.0.0 paho-mqtt>=1.6.0 pymodbus>=3.0.0 python-dotenv>=1.0.0

# Install dev dependencies
echo "Installing dev dependencies..."
pip install pytest pytest-cov black ruff mypy

# Create .env if not exists
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from .env.example"
fi

echo ""
echo "========================================"
echo "Setup complete!"
echo ""
echo "Activate: source venv/bin/activate"
echo "Run:      python -m src.main"
echo "Test:     python -m src.main --dry-run"
echo "========================================"