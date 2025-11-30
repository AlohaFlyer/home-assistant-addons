"""
Hybrid Agent Manager - Main entry point
Multi-agent system with Ollama (local) + Claude (fallback)
"""

import os
import sys
import asyncio
import logging
from datetime import datetime

from manager import AgentManager

# Configure logging
log_level = os.environ.get('LOG_LEVEL', 'info').upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)


async def main():
    """Main entry point"""
    logger.info("=" * 60)
    logger.info("Hybrid Agent Manager Starting")
    logger.info("=" * 60)

    # Log configuration
    logger.info(f"Ollama URL: {os.environ.get('OLLAMA_URL', 'not set')}")
    logger.info(f"Ollama Model: {os.environ.get('OLLAMA_MODEL', 'not set')}")
    logger.info(f"Claude API Key: {'configured' if os.environ.get('CLAUDE_API_KEY') else 'not configured'}")
    logger.info(f"Check Interval: {os.environ.get('CHECK_INTERVAL', '5')} minutes")
    logger.info(f"Confirm Critical: {os.environ.get('CONFIRM_CRITICAL', 'true')}")

    # Initialize manager
    manager = AgentManager()

    # Check HA connectivity
    logger.info("Checking Home Assistant API connectivity...")
    if await manager.ha_client.is_healthy():
        logger.info("✓ Home Assistant API is accessible")
    else:
        logger.error("✗ Cannot reach Home Assistant API")
        logger.error("Check SUPERVISOR_TOKEN and HA_URL environment variables")
        # Continue anyway - will retry on each cycle

    # Get check interval
    check_interval = int(os.environ.get('CHECK_INTERVAL', '5'))
    interval_seconds = check_interval * 60

    logger.info(f"Starting monitoring loop (every {check_interval} minutes)")
    logger.info("=" * 60)

    # Main loop
    cycle_count = 0
    while True:
        cycle_count += 1
        logger.info(f"")
        logger.info(f"{'='*20} CYCLE {cycle_count} {'='*20}")

        try:
            # Run monitoring cycle
            results = await manager.run_cycle()

            # Log results summary
            for agent_name, agent_result in results.get('agents', {}).items():
                issues = agent_result.get('issues', [])
                decision = agent_result.get('decision', 'unknown')
                tier = agent_result.get('tier', 'unknown')

                if issues:
                    logger.info(f"[{agent_name}] {len(issues)} issues → {decision} (Tier: {tier})")
                else:
                    logger.info(f"[{agent_name}] ✓ All normal")

            # Log actions
            actions_taken = results.get('actions_taken', [])
            actions_pending = results.get('actions_pending', [])

            if actions_taken:
                logger.info(f"Actions executed: {len(actions_taken)}")
                for action in actions_taken:
                    logger.info(f"  → {action['agent']}: {action['decision']}")

            if actions_pending:
                logger.info(f"Actions pending confirmation: {len(actions_pending)}")
                for action in actions_pending:
                    logger.info(f"  ⏳ {action['agent']}: {action['decision']}")

            # Log errors
            errors = results.get('errors', [])
            if errors:
                logger.warning(f"Errors: {len(errors)}")
                for error in errors:
                    logger.warning(f"  ⚠ {error['agent']}: {error['error']}")

            # Log LLM usage stats every 10 cycles
            if cycle_count % 10 == 0:
                stats = manager.get_stats()
                llm_stats = stats.get('llm_stats', {})
                logger.info(f"LLM Usage: Tier1={llm_stats.get('tier1_pct', 0)}%, "
                          f"Tier2={llm_stats.get('tier2_pct', 0)}%, "
                          f"Tier3={llm_stats.get('tier3_pct', 0)}%")

        except Exception as e:
            logger.error(f"Cycle failed with error: {e}")
            import traceback
            logger.error(traceback.format_exc())

        # Wait for next cycle
        logger.info(f"Next cycle in {check_interval} minutes...")
        await asyncio.sleep(interval_seconds)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
