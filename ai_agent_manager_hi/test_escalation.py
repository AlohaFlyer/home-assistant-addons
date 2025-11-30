#!/usr/bin/env python3
"""Test script to simulate escalation scenarios."""

import asyncio
import sys
import os

# Add the agent_manager to path
sys.path.insert(0, '/agent_manager')
os.chdir('/agent_manager')

from hybrid_llm import HybridLLMManager, LLMTier

async def test_escalation():
    """Test different scenarios to trigger escalation."""

    # Get API key from environment
    api_key = os.environ.get('CLAUDE_API_KEY', '').strip()
    ollama_url = os.environ.get('OLLAMA_URL', 'http://homeassistant.local:11434')

    print("=" * 70)
    print("HYBRID LLM ESCALATION TEST")
    print("=" * 70)

    manager = HybridLLMManager(
        claude_api_key=api_key,
        ollama_url=ollama_url,
        ollama_model='llama3.2:3b',
        claude_model='claude-3-haiku-20240307',
        escalation_threshold=0.7
    )

    # Initialize
    ollama_available = await manager.initialize()
    print(f"\nOllama available: {ollama_available}")
    print(f"Claude API key configured: {'Yes' if api_key else 'No'}")

    # SCENARIO 1: Simple healthy state (should stay at Tier 1)
    print("\n" + "=" * 70)
    print("SCENARIO 1: Healthy System (expect Tier 1)")
    print("=" * 70)

    healthy_states = {
        'powerwall': {'status': 'on_track', 'battery_pct': 85, 'is_charging': True, 'grid_power': 0},
        'light_manager': {'status': 'healthy', 'sync_issues': 0, 'drifted_lights': 0},
        'zwave': {'status': 'healthy', 'unavailable_count': 1},
        'security': {'status': 'healthy', 'cameras_online': 10, 'total_cameras': 10},
    }

    result = await manager.analyze(healthy_states)
    print(f"Tier: {result.tier.name}")
    print(f"Summary: {result.summary}")
    print(f"Confidence: {result.confidence}")
    print(f"Issues: {len(result.issues)}")
    print(f"Cost: ${result.cost:.4f}")
    print(f"Latency: {result.latency_ms}ms")

    # SCENARIO 2: Multiple warnings (should escalate to Tier 2)
    print("\n" + "=" * 70)
    print("SCENARIO 2: Multiple Warnings - 4 agents with issues (expect Tier 2)")
    print("=" * 70)

    warning_states = {
        'powerwall': {'status': 'at_risk', 'battery_pct': 45, 'is_charging': False, 'grid_power': 5.0},
        'light_manager': {'status': 'warning', 'sync_issues': 3, 'drifted_lights': 5, 'unavailable_lights': 2},
        'zwave': {'status': 'warning', 'unavailable_count': 8},
        'occupancy': {'status': 'idle', 'idle_count': 5, 'idle_rooms': [
            {'name': 'Kitchen', 'light_entity': 'light.kitchen_relay', 'minutes': 30},
            {'name': 'Living Room', 'light_entity': 'light.living_room_relay', 'minutes': 45},
        ]},
        'security': {'status': 'warning', 'cameras_online': 7, 'total_cameras': 10},
    }

    result = await manager.analyze(warning_states)
    print(f"Tier: {result.tier.name}")
    print(f"Summary: {result.summary}")
    print(f"Confidence: {result.confidence}")
    print(f"Issues: {len(result.issues)}")
    for issue in result.issues[:5]:
        print(f"  - [{issue.get('severity', '?')}] {issue.get('agent', '?')}: {issue.get('description', '?')}")
    print(f"Actions: {len(result.actions)}")
    print(f"Cost: ${result.cost:.4f}")
    print(f"Latency: {result.latency_ms}ms")
    print(f"Escalated: {result.escalate}")

    # SCENARIO 3: Critical issues (should escalate to Tier 2 or 3)
    print("\n" + "=" * 70)
    print("SCENARIO 3: Critical Issues - Multiple criticals (expect Tier 2/3)")
    print("=" * 70)

    critical_states = {
        'powerwall': {'status': 'critical', 'battery_pct': 3, 'is_charging': False, 'grid_power': 8.0},
        'light_manager': {'status': 'critical', 'sync_issues': 10, 'drifted_lights': 15, 'unavailable_lights': 8},
        'zwave': {'status': 'critical', 'unavailable_count': 25, 'unavailable_devices': [
            {'name': 'Kitchen Light', 'entity_id': 'light.kitchen'},
            {'name': 'Living Room', 'entity_id': 'light.living_room'},
        ]},
        'garage': {'status': 'critical', 'open_count': 3, 'obstruction': True},
        'security': {'status': 'critical', 'cameras_online': 4, 'total_cameras': 10},
    }

    result = await manager.analyze(critical_states)
    print(f"Tier: {result.tier.name}")
    print(f"Summary: {result.summary}")
    print(f"Confidence: {result.confidence}")
    print(f"Issues: {len(result.issues)}")
    for issue in result.issues[:5]:
        print(f"  - [{issue.get('severity', '?')}] {issue.get('agent', '?')}: {issue.get('description', '?')}")
    print(f"Actions: {len(result.actions)}")
    for action in result.actions[:3]:
        print(f"  - {action.get('agent', '?')}: {action.get('action', '?')} -> {action.get('entity', '?')}")
    print(f"Predictions: {len(result.predictions)}")
    print(f"Cost: ${result.cost:.4f}")
    print(f"Latency: {result.latency_ms}ms")

    # SCENARIO 4: Force Tier 2 (Ollama)
    print("\n" + "=" * 70)
    print("SCENARIO 4: Force Tier 2 (Ollama) directly")
    print("=" * 70)

    if ollama_available:
        result = await manager.analyze(warning_states, force_tier=LLMTier.LOCAL)
        print(f"Tier: {result.tier.name}")
        print(f"Summary: {result.summary}")
        print(f"Confidence: {result.confidence}")
        print(f"Issues: {len(result.issues)}")
        print(f"Cost: ${result.cost:.4f}")
        print(f"Latency: {result.latency_ms}ms")
        if result.error:
            print(f"Error: {result.error}")
    else:
        print("Ollama not available - skipping")

    # Print final stats
    print("\n" + "=" * 70)
    print("FINAL STATISTICS")
    print("=" * 70)
    stats = manager.get_stats()
    print(f"Total requests: {stats.get('total_requests', 0)}")
    print(f"Rule-based: {stats.get('rule_based_count', 0)} ({stats.get('rule_based_pct', 0):.1f}%)")
    print(f"Local (Ollama): {stats.get('local_count', 0)} ({stats.get('local_pct', 0):.1f}%)")
    print(f"Claude: {stats.get('claude_count', 0)} ({stats.get('claude_pct', 0):.1f}%)")
    print(f"Total cost: ${stats.get('total_cost', 0):.4f}")
    print(f"Avg latency: {stats.get('avg_latency_ms', 0):.0f}ms")
    print(f"Error rate: {stats.get('error_rate_pct', 0):.1f}%")

    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)

if __name__ == '__main__':
    asyncio.run(test_escalation())
