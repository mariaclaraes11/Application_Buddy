"""
Teams Orchestration Agent - Hosted Agent Wrapper for main_workflow_v2

This file wraps the main_workflow_v2.py CV analysis workflow into a hosted agent 
that can be deployed to Azure AI Foundry and integrated with Microsoft Teams.
"""

import asyncio
import sys
import os
from dotenv import load_dotenv

# Add parent directories to Python path so we can import modules
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(project_root)
sys.path.append(os.path.join(project_root, 'workflows'))
sys.path.append(os.path.join(project_root, 'src'))

# Import the main workflow components  
from main_workflow_v2 import CVInput, analyze_single_job, setup_agents
from config import Config

# Global setup tracking
_agents_setup = False
_config = None

async def _ensure_agents_setup():
    """Ensure agents are set up before processing."""
    global _agents_setup, _config
    if not _agents_setup:
        # Load environment variables first (like main_workflow_v2 does)
        load_dotenv()
        
        # Check if configuration is set up
        if not os.getenv("AZURE_AI_FOUNDRY_ENDPOINT"):
            raise Exception("Configuration required: AZURE_AI_FOUNDRY_ENDPOINT not set in .env file")
        
        _config = Config()
        await setup_agents(_config)
        _agents_setup = True

# Hosted agent function - this is what Azure AI Foundry calls
async def teams_analyze_cv(cv_text: str, job_description: str, job_title: str = "Software Engineer") -> dict:
    """
    Hosted agent function for complete CV analysis workflow.
    This is the entry point that Azure AI Foundry will call.
    This runs the ENTIRE main_workflow_v2 including analysis, Q&A, validation, and recommendation.
    
    Usage in Teams:
    User can copy/paste their CV text and job description directly into Teams chat.
    """
    try:
        # Ensure agents are set up
        await _ensure_agents_setup()
        
        # Create job object in the format expected by analyze_single_job
        job = {
            "title": job_title,
            "content": job_description  # main_workflow_v2 expects 'content', not 'description'
        }
        
        print(f"🔍 Debug: Job object created: {job['title']}")
        print(f"🔍 Debug: CV length: {len(cv_text)} characters")
        
        # Run the complete workflow (analysis + Q&A + validation + recommendation)
        result = await analyze_single_job(cv_text, job)
        
        # Return the result
        return {
            "status": "success",
            "analysis": result,
            "message": "Complete CV analysis workflow completed successfully"
        }
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"🚨 Full error details:\n{error_details}")
        return {
            "status": "error", 
            "error": str(e),
            "message": "CV analysis workflow failed",
            "details": error_details
        }
# For testing locally
if __name__ == "__main__":
    async def test():
        """Test function for local development - asks for user input."""
        print("🧪 Testing Teams Orchestration Agent")
        print("=" * 50)
        print("Please paste your CV text below, then press Ctrl+D when done:")
        
        cv_lines = []
        try:
            while True:
                line = input()
                cv_lines.append(line)
        except EOFError:
            pass
        cv_text = "\n".join(cv_lines)
        
        print("\nNow paste the job description below, then press Ctrl+D when done:")
        job_lines = []
        try:
            while True:
                line = input()
                job_lines.append(line)
        except EOFError:
            pass
        job_description = "\n".join(job_lines)
        
        print(f"\n🚀 Running CV analysis...")
        
        try:
            result = await teams_analyze_cv(cv_text, job_description)
            
            print("\n✅ Analysis Complete!")
            print("=" * 50)
            print(f"Status: {result['status']}")
            print(f"Message: {result['message']}")
            
            if result['status'] == 'success':
                analysis = result.get('analysis', 'No analysis data')
                print(f"\n📊 Analysis Result:\n{analysis}")
            else:
                print(f"\n❌ Error: {result.get('error', 'Unknown error')}")
                
        except Exception as e:
            print(f"\n💥 Test failed: {str(e)}")
            import traceback
            traceback.print_exc()
    
    asyncio.run(test())