"""
DevUI Launcher for Application Buddy
Uses the official Microsoft Agent Framework DevUI to visualize 
the TeamsOrchestrator HITL CV analysis workflow.
"""
import asyncio
import os
import sys
from dotenv import load_dotenv

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'TeamsOrchestrator'))

# Official Microsoft DevUI imports
from agent_framework.devui import serve

# Import the TeamsOrchestrator workflow
from workflow import build_cv_workflow_agent

async def main():
    """Launch DevUI with the TeamsOrchestrator HITL workflow."""
    print("🎯 Application Buddy DevUI Launcher")
    print("=" * 50)
    
    # Load environment
    load_dotenv()
    if not os.getenv("AZURE_AI_FOUNDRY_ENDPOINT"):
        print("❌ Please set up your .env file with Azure AI Foundry configuration")
        return
    
    try:
        # Build the HITL workflow agent
        print("🔧 Building CV workflow agent...")
        workflow_agent = build_cv_workflow_agent()
        
        print("✅ Using TeamsOrchestrator HITL workflow")
        print("🌐 Starting DevUI at http://localhost:8080")
        print("")
        print("💡 This workflow uses Human-in-the-Loop (HITL) pattern:")
        print("   1. Collect CV from user")
        print("   2. Collect job description")  
        print("   3. Analyze match & Q&A conversation")
        print("   4. Generate recommendation")
        
        # Launch DevUI with the workflow agent
        await serve(entities=[workflow_agent], port=8080, auto_open=True)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        print("\n💡 Check your .env config and run: pip install agent-framework-devui --pre")

def launch_devui():
    """Entry point."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 DevUI stopped")

if __name__ == "__main__":
    launch_devui()