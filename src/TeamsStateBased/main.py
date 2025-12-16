"""
Main entry point for hosted agent deployment.

Exposes the CV Analysis workflow as an HTTP agent on port 8088.
Azure AI Foundry connects this to Microsoft Teams.
"""
import logging
from azure.ai.agentserver.agentframework import from_agent_framework
from workflow import build_cv_workflow_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    """Start the hosted agent server."""
    logger.info("Building CV workflow agent...")
    agent = build_cv_workflow_agent()
    
    logger.info("Starting hosted agent server on port 8088...")
    logger.info("Ready to receive requests from Azure AI Foundry / Microsoft Teams")
    
    # Wrap with hosting adapter → exposes HTTP on port 8088
    from_agent_framework(agent).run()


if __name__ == "__main__":
    main()