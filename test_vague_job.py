"""
Test script for vague job posting handling
"""

import asyncio
from src.agents.optimized_orchestrator import FoundryIntegratedOrchestrator
from src.config import Config

async def test_vague_job():
    """Test with a vague job posting that has no clear must-have/nice-to-have distinctions"""
    
    # Sample CV
    cv_text = """
    Jane Smith
    Software Developer
    
    Experience:
    - 2 years Python development
    - Worked with databases
    - Some cloud experience
    
    Skills: Python, HTML, CSS, Git
    Education: BS Computer Science
    """
    
    # Deliberately vague job posting
    vague_job = """
    Software Engineer Position
    
    We're looking for a software engineer to join our team.
    
    Skills we're looking for:
    - Python programming
    - Database knowledge  
    - Cloud platforms
    - React experience
    - Kubernetes
    - Machine learning
    - Docker
    - AWS certification
    - 5+ years experience
    - Team collaboration
    
    Join our dynamic team and help us build amazing products!
    """
    
    print("Testing with VAGUE job posting (no clear must-have/nice-to-have):")
    print("=" * 60)
    
    config = Config()
    orchestrator = FoundryIntegratedOrchestrator(config)
    
    # Test the analysis
    analysis_data = await orchestrator.analyze_and_check_qna_needed(cv_text, vague_job)
    
    if "error" in analysis_data:
        print(f"Error: {analysis_data['error']}")
        return
    
    print("Analysis Results:")
    print("=" * 40)
    print(analysis_data["analysis"])
    print("=" * 40)
    print(f"Q&A Needed: {analysis_data['needs_qna']}")

if __name__ == "__main__":
    asyncio.run(test_vague_job())