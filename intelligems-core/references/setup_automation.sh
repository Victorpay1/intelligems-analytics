#!/usr/bin/env bash
#
# Intelligems Analytics — Automation Setup
#
# Creates a macOS LaunchAgent to run a skill script on a schedule.
# Sends output to Slack via --slack flag.
#
# Usage: bash setup_automation.sh <script_name> <webhook_url> [hour] [minute]
#   script_name: brief.py, verdict.py, or impact.py
#   webhook_url: Slack incoming webhook URL
#   hour: Hour to run (0-23, default 8)
#   minute: Minute to run (0-59, default 0)
#

SCRIPT_NAME="${1:?Usage: setup_automation.sh <script.py> <webhook_url> [hour] [minute]}"
WEBHOOK_URL="${2:?Usage: setup_automation.sh <script.py> <webhook_url> [hour] [minute]}"
HOUR="${3:-8}"
MINUTE="${4:-0}"

WORKSPACE="$HOME/intelligems-analytics"
VENV="$WORKSPACE/venv/bin/python3"
SCRIPT_PATH="$WORKSPACE/$SCRIPT_NAME"

# Derive a clean name for the plist
BASE_NAME=$(basename "$SCRIPT_NAME" .py)
PLIST_NAME="com.intelligems.${BASE_NAME}"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"
LOG_PATH="/tmp/intelligems-${BASE_NAME}.log"
ERROR_LOG="/tmp/intelligems-${BASE_NAME}.error.log"

# Verify files exist
if [ ! -f "$VENV" ]; then
    echo "Error: Virtual environment not found at $VENV"
    echo "Run setup_workspace.sh first."
    exit 1
fi

if [ ! -f "$SCRIPT_PATH" ]; then
    echo "Error: Script not found at $SCRIPT_PATH"
    echo "Copy the script to ~/intelligems-analytics/ first."
    exit 1
fi

# Unload existing plist if present
if [ -f "$PLIST_PATH" ]; then
    echo "Removing existing automation..."
    launchctl unload "$PLIST_PATH" 2>/dev/null
fi

# Create the plist
echo "Creating automation: $PLIST_NAME"
echo "  Script: $SCRIPT_PATH"
echo "  Schedule: daily at $(printf '%02d:%02d' $HOUR $MINUTE)"
echo "  Slack: $WEBHOOK_URL"

cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_NAME}</string>

    <key>ProgramArguments</key>
    <array>
        <string>${VENV}</string>
        <string>${SCRIPT_PATH}</string>
        <string>--slack</string>
        <string>${WEBHOOK_URL}</string>
    </array>

    <key>WorkingDirectory</key>
    <string>${WORKSPACE}</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
    </dict>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>${HOUR}</integer>
        <key>Minute</key>
        <integer>${MINUTE}</integer>
    </dict>

    <key>StandardOutPath</key>
    <string>${LOG_PATH}</string>

    <key>StandardErrorPath</key>
    <string>${ERROR_LOG}</string>

    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
PLIST

# Load the agent
launchctl load "$PLIST_PATH"

echo ""
echo "Automation active!"
echo "  Plist: $PLIST_PATH"
echo "  Logs: $LOG_PATH"
echo "  Errors: $ERROR_LOG"
echo ""
echo "To test now: $VENV $SCRIPT_PATH --slack '$WEBHOOK_URL'"
echo "To stop: launchctl unload $PLIST_PATH"
