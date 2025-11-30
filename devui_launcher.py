"""
DevUI Launcher for Application Buddy
Minimal launcher that uses the official Microsoft Agent Framework DevUI 
to visualize your existing CV analysis workflow - zero code duplication!
"""
import asyncio
import os
from dotenv import load_dotenv

# Official Microsoft DevUI imports
from agent_framework.devui import serve

# Import EVERYTHING from your existing workflow - no duplication!
from main_workflow_v2 import create_cv_analysis_workflow, setup_agents, CVInput, read_cv_file, parse_job_descriptions
from src.config import Config

async def main():
    """Launch DevUI with your existing workflow - minimal launcher code!"""
    print(" Application Buddy DevUI Launcher")
    print("=" * 50)
    
    # Load environment and check config
    load_dotenv()
    if not os.getenv("AZURE_AI_FOUNDRY_ENDPOINT"):
        print(" Please set up your .env file with Azure AI Foundry configuration")
        return
    
    try:
        # Use your EXISTING setup functions
        config = Config()
        await setup_agents(config)
        workflow = create_cv_analysis_workflow()
        
        print("✅ Using your existing workflow from main_workflow_v2.py")
        print(f"🌐 Starting DevUI at http://localhost:8080")
        
        # THE ONLY LINE THAT CREATES DEVUI - using your existing workflow!
        await serve(entities=[workflow], port=8080, auto_open=True)
        
    except Exception as e:
        print(f" Error: {e}")
        print(" Check your .env config and run: pip install agent-framework-devui --pre")

def launch_devui():
    """Entry point."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n DevUI stopped")

if __name__ == "__main__":
    launch_devui()