#!/usr/bin/with-contenv bashio

CONFIG_PATH=/data/options.json

export OLLAMA_URL=$(bashio::config 'ollama_url')
export OLLAMA_MODEL=$(bashio::config 'ollama_model')
export CLAUDE_API_KEY=$(bashio::config 'claude_api_key')
export CLAUDE_MODEL=$(bashio::config 'claude_model')
export HA_URL="http://supervisor/core"
export CHECK_INTERVAL=$(bashio::config 'check_interval_minutes')
export ESCALATION_THRESHOLD=$(bashio::config 'escalation_confidence_threshold')
export CONFIRM_CRITICAL=$(bashio::config 'confirm_critical_actions')
export LOG_LEVEL=$(bashio::config 'log_level')
export SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN}"

bashio::log.info "Starting Hybrid Agent Manager..."
bashio::log.info "Ollama: ${OLLAMA_URL} (${OLLAMA_MODEL})"
bashio::log.info "Check interval: ${CHECK_INTERVAL} minutes"

cd /app
exec python3 -u main.py
