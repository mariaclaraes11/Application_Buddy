"""
Test file for the Foundry Hosting Adapter

One-line deployment: Transform complex agent deployment into a single line of code
that instantly hosts your agent on localhost:8088 with all necessary HTTP endpoints,
streaming support, and Foundry protocol compliance.

To test:
1. Run this file: python test_hosting_adapter.py
2. Send a POST request to http://localhost:8088/responses with JSON body

Example curl request:
curl -X POST http://localhost:8088/responses \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "messages": [
        {
          "role": "user", 
          "content": "CV: [your cv text] JOB: [job description]"
        }
      ]
    }
  }'
"""

import sys
import os
from dotenv import load_dotenv

# Load environment variables FIRST
load_dotenv()

# Add parent directories to Python path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(project_root)
sys.path.append(os.path.join(project_root, 'workflows'))
sys.path.append(os.path.join(project_root, 'src'))

# Import hosting adapter - CORRECT import (dots!)
from azure.ai.agentserver.agentframework import from_agent_framework

# Import Agent Framework for creating the ChatAgent
from agent_framework import ChatAgent
from agent_framework.azure import AzureOpenAIChatClient
from azure.identity import DefaultAzureCredential

# Import config
from config import Config


def create_cv_analysis_agent() -> ChatAgent:
    """
    Create the CV Analysis ChatAgent that will be wrapped by the hosting adapter.
    
    The hosting adapter wraps your existing ChatAgent and exposes it via HTTP
    on localhost:8088 with Foundry-compatible endpoints.
    """
    # Load config
    config = Config()
    
    # Create Azure OpenAI client
    # Extract base endpoint (remove /api/projects/... part)
    azure_endpoint = config.azure_ai_foundry_endpoint.split('/api/projects/')[0]
    credential = DefaultAzureCredential()
    
    chat_client = AzureOpenAIChatClient(
        deployment_name=config.model_deployment_name,
        endpoint=azure_endpoint,
        api_version=config.api_version,
        credential=credential,
    )
    
    # Create the agent with CV analysis instructions
    agent = ChatAgent(
        name="CVAnalysisAgent",
        chat_client=chat_client,
        instructions="""You are a CV Analysis Agent that helps analyze candidate CVs against job descriptions.

When a user provides their CV and a job description, you will:
1. Analyze the CV against the job requirements
2. Identify gaps and strengths
3. Ask clarifying questions if needed
4. Provide recommendations

To analyze a CV, the user should provide both CV text and job description in the format:
CV: [cv text]
JOB: [job description]

Be thorough but concise in your analysis."""
    )
    
    return agent


def main():
    """
    Run the hosted agent server locally.
    
    One-line deployment pattern:
        from_agent_framework(my_agent).run()
    
    This instantly hosts your agent on localhost:8088 with:
    - HTTP endpoints for the Foundry Responses API
    - Streaming support (SSE)
    - Foundry protocol compliance
    - OpenTelemetry tracing
    - CORS support
    """
    print("=" * 60)
    print("🚀 Starting CV Analysis Hosted Agent Server")
    print("=" * 60)
    print()
    print("Server will start on: http://localhost:8088")
    print()
    print("To test, send a POST request:")
    print()
    print('curl -X POST http://localhost:8088/responses \\')
    print('  -H "Content-Type: application/json" \\')
    print('  -d \'{"input": {"messages": [{"role": "user", "content": "Hello, can you help me analyze my CV?"}]}}\'')
    print()
    print("=" * 60)
    print()
    
    # Create the CV analysis agent
    print("Creating CV Analysis Agent...")
    agent = create_cv_analysis_agent()
    print("✅ Agent created successfully!")
    print()
    print("Starting server...")
    
    # ONE-LINE DEPLOYMENT - That's it!
    from_agent_framework(agent).run()


if __name__ == "__main__":
    main()
