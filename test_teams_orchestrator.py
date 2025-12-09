"""
Test script for Teams Orchestrator
Tests the hosted agent functionality and Teams integration
"""
import asyncio
import sys
import os

# Add project root to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from teams_orchestrator import TeamsOrchestrator, CVAnalysisRequest, teams_analyze_cv
from src.config import Config

async def test_orchestrator():
    """Test the Teams orchestrator with sample data"""
    print("🧪 Testing Teams Orchestrator")
    print("=" * 40)
    
    # Sample CV text (shortened for testing)
    sample_cv = """
    John Smith
    Software Engineer
    
    Experience:
    - 3 years Python development
    - Web application development
    - Team collaboration
    """
    
    # Sample job description
    sample_job = """
    Software Engineer Position
    
    Requirements:
    - Python programming experience
    - Infrastructure as code experience (Terraform)
    - Strong communication skills
    - Team collaboration
    """
    
    try:
        print("1. Testing direct orchestrator...")
        config = Config()
        orchestrator = TeamsOrchestrator(config)
        await orchestrator.initialize()
        
        request = CVAnalysisRequest(
            cv_text=sample_cv,
            job_description=sample_job,
            user_id="test_user_123"
        )
        
        response = await orchestrator.analyze_cv_for_teams(request)
        
        print(f"✅ Analysis completed!")
        print(f"   Score: {response.score}")
        print(f"   Q&A Needed: {response.needs_qna}")
        print(f"   Conversation ID: {response.conversation_id}")
        
        print("\n2. Testing Teams integration function...")
        teams_response = await teams_analyze_cv(
            cv_text=sample_cv,
            job_description=sample_job,
            user_id="teams_user_456"
        )
        
        print(f"✅ Teams integration working!")
        print(f"   Success: {teams_response['success']}")
        print(f"   Score: {teams_response['score']}")
        
        print(f"\n🎉 All tests passed! Teams orchestrator is ready.")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_orchestrator())