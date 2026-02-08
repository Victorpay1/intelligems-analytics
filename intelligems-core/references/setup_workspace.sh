#!/usr/bin/env bash
#
# Intelligems Analytics — Workspace Setup
#
# Creates ~/intelligems-analytics/ with a Python virtual environment
# and all required dependencies. Safe to run multiple times.
#

WORKSPACE="$HOME/intelligems-analytics"
VENV="$WORKSPACE/venv"

echo "Setting up Intelligems Analytics workspace..."

# Create workspace
mkdir -p "$WORKSPACE"

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv "$VENV"
fi

# Activate and install dependencies
echo "Installing dependencies..."
source "$VENV/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet requests python-dotenv

# Create .env template if it doesn't exist
if [ ! -f "$WORKSPACE/.env" ]; then
    echo "INTELLIGEMS_API_KEY=your_api_key_here" > "$WORKSPACE/.env"
    echo "Created .env template at $WORKSPACE/.env"
    echo "  → Replace 'your_api_key_here' with your Intelligems API key"
fi

echo ""
echo "Workspace ready at $WORKSPACE"
echo "  Virtual env: $VENV"
echo "  Config: $WORKSPACE/.env"
echo ""
echo "To activate manually: source $VENV/bin/activate"
