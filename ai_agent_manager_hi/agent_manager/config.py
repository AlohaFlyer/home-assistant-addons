#!/usr/bin/env python3
"""Configuration management for Claude Agent Manager."""

import os
from dataclasses import dataclass


@dataclass
class Config:
    """Configuration loaded from environment variables."""

    claude_api_key: str = ""
    ha_token: str = ""
    supervisor_token: str = ""
    ha_url: str = "http://supervisor/core"
    check_interval: int = 5  # minutes
    autonomous_actions: bool = True
    learning_enabled: bool = True
    notification_level: str = "warning"
    max_auto_fixes: int = 10
    log_level: str = "info"

    # Hybrid LLM settings (cost optimization)
    hybrid_mode_enabled: bool = True  # Use tiered LLM approach
    ollama_url: str = "http://homeassistant.local:11434"  # Local Ollama server
    ollama_model: str = "llama3.2:3b"  # Small, fast local model
    claude_model: str = "claude-3-haiku-20240307"  # Cost-effective Claude model
    escalation_threshold: float = 0.7  # Confidence threshold for escalation

    def __post_init__(self):
        """Load configuration from environment variables."""
        # Strip whitespace from API keys (common copy-paste issue)
        self.claude_api_key = os.environ.get('CLAUDE_API_KEY', self.claude_api_key).strip()
        self.ha_token = os.environ.get('HA_TOKEN', self.ha_token).strip()
        self.supervisor_token = os.environ.get('SUPERVISOR_TOKEN', self.supervisor_token).strip()
        self.ha_url = os.environ.get('HA_URL', self.ha_url)

        # Parse integer values
        try:
            self.check_interval = int(os.environ.get('CHECK_INTERVAL', self.check_interval))
        except ValueError:
            pass

        try:
            self.max_auto_fixes = int(os.environ.get('MAX_AUTO_FIXES', self.max_auto_fixes))
        except ValueError:
            pass

        # Parse boolean values
        autonomous = os.environ.get('AUTONOMOUS_ACTIONS', str(self.autonomous_actions))
        self.autonomous_actions = autonomous.lower() in ('true', '1', 'yes', 'on')

        learning = os.environ.get('LEARNING_ENABLED', str(self.learning_enabled))
        self.learning_enabled = learning.lower() in ('true', '1', 'yes', 'on')

        # String values
        self.notification_level = os.environ.get('NOTIFICATION_LEVEL', self.notification_level)
        self.log_level = os.environ.get('LOG_LEVEL', self.log_level)

        # Hybrid LLM settings
        hybrid = os.environ.get('HYBRID_MODE_ENABLED', str(self.hybrid_mode_enabled))
        self.hybrid_mode_enabled = hybrid.lower() in ('true', '1', 'yes', 'on')

        self.ollama_url = os.environ.get('OLLAMA_URL', self.ollama_url)
        self.ollama_model = os.environ.get('OLLAMA_MODEL', self.ollama_model)
        self.claude_model = os.environ.get('CLAUDE_MODEL', self.claude_model)

        try:
            self.escalation_threshold = float(os.environ.get('ESCALATION_THRESHOLD', self.escalation_threshold))
        except ValueError:
            pass

    def validate(self) -> list:
        """Validate configuration and return list of issues."""
        issues = []

        if not self.claude_api_key:
            issues.append("CLAUDE_API_KEY is required")

        if not self.ha_token and not self.supervisor_token:
            issues.append("Either HA_TOKEN or SUPERVISOR_TOKEN is required")

        if self.check_interval < 1 or self.check_interval > 60:
            issues.append("CHECK_INTERVAL must be between 1 and 60 minutes")

        if self.notification_level not in ('debug', 'info', 'warning', 'error'):
            issues.append("NOTIFICATION_LEVEL must be one of: debug, info, warning, error")

        if self.escalation_threshold < 0 or self.escalation_threshold > 1:
            issues.append("ESCALATION_THRESHOLD must be between 0 and 1")

        return issues

    def get_llm_stats_summary(self) -> str:
        """Get a summary of LLM configuration for logging."""
        if self.hybrid_mode_enabled:
            return (
                f"Hybrid Mode: ON | "
                f"Ollama: {self.ollama_url} ({self.ollama_model}) | "
                f"Claude: {self.claude_model} | "
                f"Escalation threshold: {self.escalation_threshold}"
            )
        else:
            return f"Hybrid Mode: OFF | Claude-only: {self.claude_model}"
