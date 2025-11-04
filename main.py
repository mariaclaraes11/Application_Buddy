"""
Application Buddy - Multi-Agent Orchestration System

This is the main entry point for the Application Buddy system that demonstrates
how to use Agent Framework with Azure AI Foundry to create a sophisticated
multi-agent orchestration system.

Architecture:
- Orchestrator Agent: Main coordinator that manages the workflow
- Data Analyzer Agent: Handles data processing and analysis
- Task Planner Agent: Creates structured plans and task breakdowns  
- Response Formatter Agent: Formats and presents final responses

Usage:
1. Set up your .env file with Azure AI Foundry configuration
2. Install dependencies: pip install -r requirements.txt
3. Run: python main.py
"""

import asyncio
import os
from dotenv import load_dotenv
from src.agents.optimized_orchestrator import FoundryIntegratedOrchestrator
from src.config import Config


# Example scenarios removed for simplicity


async def main():
    """
    Simple CV/Job matching - just paste CV and job description
    """
    # Load environment variables
    load_dotenv()
    
    # Check if configuration is set up
    if not os.getenv("AZURE_AI_FOUNDRY_ENDPOINT"):
        print("⚠️  Configuration Setup Required")
        print("=" * 50)
        print("Please set up your configuration:")
        print("1. Copy .env.example to .env")
        print("2. Fill in your Azure AI Foundry endpoint and model deployment name")
        print("3. Ensure you're authenticated with Azure (az login)")
        print()
        print("Example .env contents:")
        print("AZURE_AI_FOUNDRY_ENDPOINT=https://your-project.westus2.ai.azure.com")
        print("MODEL_DEPLOYMENT_NAME=gpt-4o")
        return
    
    print("🤖 CV/Job Matching System")
    print("=" * 40)
    
    try:
        print("\n📄 Please paste the CV text:")
        cv_text = input().strip()
        
        if not cv_text:
            print("❌ No CV text provided.")
            return
            
        print("\n� Please paste the job description:")
        job_description = input().strip()
        
        if not job_description:
            print("❌ No job description provided.")
            return
            
        print(f"\n🔄 Processing CV/Job matching...")
        print("   Creating agents in Azure AI Foundry...")
        
        # Use intelligent Foundry-integrated orchestration with adaptive Q&A
        config = Config()
        orchestrator = FoundryIntegratedOrchestrator(config)
        
        # Use the intelligent direct analysis that skips Q&A for strong fits
        final_result = await orchestrator.direct_analyze(cv_text, job_description)
        
        print(f"\n📋 Matching Report:")
        print("=" * 40)
        print(final_result)
        
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"❌ Error: {str(e)}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Application terminated by user.")
    except Exception as e:
        print(f"💥 Fatal error: {str(e)}")
        print("Please check your configuration and try again.")