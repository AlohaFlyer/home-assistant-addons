#!/usr/bin/with-contenv bashio
# Pool AI Agent - Entry Point

# Get configuration from add-on options
export ANTHROPIC_API_KEY=$(bashio::config 'anthropic_api_key')
export DECISION_INTERVAL=$(bashio::config 'decision_interval_minutes')
export LOG_LEVEL=$(bashio::config 'log_level')

# Hybrid LLM configuration
export HYBRID_MODE_ENABLED=$(bashio::config 'hybrid_mode_enabled')
export OLLAMA_URL=$(bashio::config 'ollama_url')
export OLLAMA_MODEL=$(bashio::config 'ollama_model')

# Get Supervisor token for HA API access
export SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN}"

bashio::log.info "Starting Pool AI Agent..."
bashio::log.info "Decision interval: ${DECISION_INTERVAL} minutes"
bashio::log.info "Log level: ${LOG_LEVEL}"
bashio::log.info "Hybrid mode: ${HYBRID_MODE_ENABLED}"
if [ "${HYBRID_MODE_ENABLED}" = "true" ]; then
    bashio::log.info "Ollama URL: ${OLLAMA_URL}"
    bashio::log.info "Ollama model: ${OLLAMA_MODEL}"
fi

# Run the Python daemon
exec python3 -m src.main
