"""Claude API client for AI-powered decision making."""

import os
import json
import logging
from typing import Optional
from dataclasses import dataclass, field

from anthropic import Anthropic

logger = logging.getLogger(__name__)


@dataclass
class Decision:
    """Represents a decision made by Claude."""
    action_required: bool
    actions: list[dict] = field(default_factory=list)
    explanation: str = ""
    confidence: float = 0.0
    reasoning: str = ""
    raw_response: str = ""


@dataclass
class TokenUsage:
    """Track token usage for cost estimation."""
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def estimated_cost(self) -> float:
        """Estimate cost based on Claude Sonnet 4.5 pricing ($3/$15 per million)."""
        input_cost = (self.input_tokens / 1_000_000) * 3.0
        output_cost = (self.output_tokens / 1_000_000) * 15.0
        return input_cost + output_cost


class ClaudeClient:
    """Client for Anthropic Claude API."""

    def __init__(self, system_prompt: str):
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")

        self.client = Anthropic(api_key=api_key)
        self.system_prompt = system_prompt
        self.model = "claude-sonnet-4-5-20250929"
        self.total_usage = TokenUsage()

    async def analyze(
        self,
        current_state: dict,
        patterns: dict,
        history: list[dict],
        question: str
    ) -> Decision:
        """
        Send pool state to Claude for analysis and get a decision.

        Args:
            current_state: Current state of all pool entities
            patterns: Detected patterns/anomalies from local analysis
            history: Recent decision history
            question: Specific question or analysis request

        Returns:
            Decision object with recommended actions
        """
        # Build the user message
        user_content = f"""## Current Pool System State
```json
{json.dumps(current_state, indent=2)}
```

## Detected Patterns/Anomalies
```json
{json.dumps(patterns, indent=2)}
```

## Recent Decision History (last 24h)
```json
{json.dumps(history[-10:] if history else [], indent=2)}
```

## Analysis Request
{question}

Please analyze the current state and provide your decision in the following JSON format:
```json
{{
    "action_required": true/false,
    "actions": [
        {{
            "type": "service_call",
            "domain": "input_boolean",
            "service": "turn_on",
            "entity_id": "input_boolean.hot_tub_heat"
        }}
    ],
    "explanation": "Brief explanation for user notification",
    "confidence": 0.0-1.0,
    "reasoning": "Detailed reasoning for logging"
}}
```
"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=self.system_prompt,
                messages=[
                    {"role": "user", "content": user_content}
                ]
            )

            # Track token usage
            self.total_usage.input_tokens += response.usage.input_tokens
            self.total_usage.output_tokens += response.usage.output_tokens

            # Parse the response
            raw_text = response.content[0].text
            return self._parse_decision(raw_text)

        except Exception as e:
            logger.error(f"Claude API error: {e}")
            return Decision(
                action_required=False,
                explanation=f"Error communicating with AI: {str(e)}",
                raw_response=str(e)
            )

    def _parse_decision(self, response_text: str) -> Decision:
        """Parse Claude's response into a Decision object."""
        try:
            # Extract JSON from response (may be wrapped in markdown)
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1

            if json_start == -1 or json_end == 0:
                logger.warning("No JSON found in response")
                return Decision(
                    action_required=False,
                    explanation="Could not parse AI response",
                    raw_response=response_text
                )

            json_str = response_text[json_start:json_end]
            data = json.loads(json_str)

            return Decision(
                action_required=data.get("action_required", False),
                actions=data.get("actions", []),
                explanation=data.get("explanation", ""),
                confidence=data.get("confidence", 0.0),
                reasoning=data.get("reasoning", ""),
                raw_response=response_text
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse decision JSON: {e}")
            return Decision(
                action_required=False,
                explanation="Could not parse AI response",
                raw_response=response_text
            )

    def get_usage_stats(self) -> dict:
        """Get current token usage statistics."""
        return {
            "input_tokens": self.total_usage.input_tokens,
            "output_tokens": self.total_usage.output_tokens,
            "estimated_cost_usd": round(self.total_usage.estimated_cost, 4)
        }

    def reset_usage(self):
        """Reset token usage counters (e.g., daily reset)."""
        self.total_usage = TokenUsage()
