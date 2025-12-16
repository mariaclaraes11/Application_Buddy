"""
Simple DevUI Launcher for Application Buddy
Uses the TeamsOrchestrator HITL workflow.
"""
import os
import sys
from dotenv import load_dotenv

# Add TeamsOrchestrator to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'TeamsOrchestrator'))

from agent_framework.devui import serve
from workflow import build_cv_workflow_agent

def main():
    """Launch DevUI - simple version!"""
    print("🚀 Application Buddy DevUI")
    
    load_dotenv()
    if not os.getenv("AZURE_AI_FOUNDRY_ENDPOINT"):
        print("❌ Set up your .env file first")
        return
    
    print("✅ Building HITL workflow agent...")
    workflow_agent = build_cv_workflow_agent()
    
    print("🌐 Starting DevUI at http://localhost:8080")
    serve(entities=[workflow_agent], port=8080, auto_open=True)

if __name__ == "__main__":
    main()