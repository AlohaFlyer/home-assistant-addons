#!/usr/bin/with-contenv bashio
# shellcheck shell=bash

# Get configuration from add-on options
export CLAUDE_API_KEY=$(bashio::config 'claude_api_key')
export HA_TOKEN=$(bashio::config 'ha_token')
export CHECK_INTERVAL=$(bashio::config 'check_interval_minutes')
export AUTONOMOUS_ACTIONS=$(bashio::config 'autonomous_actions')
export LEARNING_ENABLED=$(bashio::config 'learning_enabled')
export NOTIFICATION_LEVEL=$(bashio::config 'notification_level')
export MAX_AUTO_FIXES=$(bashio::config 'max_auto_fixes_per_hour')
export LOG_LEVEL=$(bashio::config 'log_level')

# Get Supervisor token for API access
export SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN}"

# Home Assistant URL (internal)
export HA_URL="http://supervisor/core"

bashio::log.info "Starting Claude Agent Manager..."
bashio::log.info "Check interval: ${CHECK_INTERVAL} minutes"
bashio::log.info "Autonomous actions: ${AUTONOMOUS_ACTIONS}"
bashio::log.info "Learning enabled: ${LEARNING_ENABLED}"

# Start the Python agent
cd /agent_manager
exec python3 main.py
