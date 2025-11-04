"""
Interactive Application Buddy - Multi-Agent Orchestration System with Real Q&A

This version handles proper interactive Q&A sessions with the user.

Architecture:
- Step 1: Analyze CV vs Job match
- Step 2: If gaps found, start interactive Q&A with user
- Step 3: Generate final application recommendation

Usage:
1. Set up your .env file with Azure AI Foundry configuration
2. Install dependencies: pip install -r requirements.txt
3. Run: python main_interactive.py
"""

import asyncio
import os
from dotenv import load_dotenv
from src.agents.optimized_orchestrator import FoundryIntegratedOrchestrator
from src.config import Config


async def main():
    """
    Interactive CV/Job matching with optional Q&A conversation
    """
    # Load environment variables
    load_dotenv()
    
    # Check if configuration is set up
    if not os.getenv("AZURE_AI_FOUNDRY_ENDPOINT"):
        print("Configuration Setup Required")
        print("=" * 40)
        print("Please set up your configuration:")
        print("1. Copy .env.example to .env")
        print("2. Fill in your Azure AI Foundry endpoint and model deployment name")
        print("3. Ensure you're authenticated with Azure (az login)")
        print()
        print("Example .env contents:")
        print("AZURE_AI_FOUNDRY_ENDPOINT=https://your-project.westus2.ai.azure.com")
        print("MODEL_DEPLOYMENT_NAME=gpt-4o")
        return
    
    print("CV/Job Matching System")
    print("=" * 30)
    
    try:
        print("\nPlease paste the CV text:")
        cv_text = input().strip()
        
        if not cv_text:
            print("No CV text provided.")
            return
            
        print("\nPlease paste the job description:")
        job_description = input().strip()
        
        if not job_description:
            print("No job description provided.")
            return
            
        print(f"\nProcessing CV/Job matching...")
        print("Creating agents in Azure AI Foundry...")
        
        # Initialize orchestrator
        config = Config()
        orchestrator = FoundryIntegratedOrchestrator(config)
        
        # Step 1: Analyze and check if Q&A is needed
        print("\nAnalyzing your CV against the job requirements...")
        analysis_data = await orchestrator.analyze_and_check_qna_needed(cv_text, job_description)
        
        if "error" in analysis_data:
            print(f"Error: {analysis_data['error']}")
            return
        
        print("\nInitial Analysis Complete!")
        print("=" * 40)
        print(analysis_data["analysis"])
        print("=" * 40)
        
        qna_summary = None
        
        if analysis_data["needs_qna"]:
            print("\nLet's have a conversation to better understand your background.")
            print("=" * 50)
            
            # Start interactive Q&A
            qna_response = await orchestrator.interactive_qna_session(analysis_data)
            print(f"\nCareer Advisor: {qna_response}")
            
            # Interactive conversation loop
            conversation_complete = False
            conversation_turns = 0
            max_turns = 10  # Prevent infinite conversations
            
            while not conversation_complete and conversation_turns < max_turns:
                print(f"\nYour response (or type 'done' to finish):")
                user_input = input().strip()
                
                if user_input.lower() in ['done', 'finished', 'complete', 'end', 'skip']:
                    conversation_complete = True
                    qna_summary = "Conversation completed - user indicated they were ready to proceed with recommendation"
                    print("\nMoving to final recommendation...")
                else:
                    # Continue Q&A conversation
                    qna_response = await orchestrator.continue_qna(user_input)
                    print(f"\nCareer Advisor: {qna_response}")
                    
                    # Check if the agent indicated conversation is complete
                    if any(phrase in qna_response.lower() for phrase in [
                        'ready to apply', 'covered everything', 'final assessment', 
                        'wrap up', 'analysis complete', 'recommendation', 'that concludes'
                    ]):
                        print("\nQ&A session complete!")
                        qna_summary = qna_response
                        conversation_complete = True
                    
                    conversation_turns += 1
            
            if conversation_turns >= max_turns:
                print("\nQ&A session reached maximum length - moving to recommendation")
                qna_summary = "Extended conversation completed - moving to final recommendation"
                
        else:
            print("\nAnalysis shows a strong fit - no additional questions needed")
        
        # Step 2: Generate final recommendation
        print("\nGenerating your personalized application recommendation...")
        final_result = await orchestrator.finalize_recommendation(analysis_data, qna_summary)
        
        print("\n" + "=" * 60)
        print("YOUR PERSONALIZED APPLICATION RECOMMENDATION")
        print("=" * 60)
        print(final_result)
        
        print("\nNext Steps:")
        print("- Review the recommendation above")
        print("- Consider the application strategy suggestions")
        print("- Take action based on the advice provided")
        print("\nGood luck with your application!")
        
    except KeyboardInterrupt:
        print("\nGoodbye!")
    except Exception as e:
        print(f"Error: {str(e)}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nApplication terminated by user.")
    except Exception as e:
        print(f"Fatal error: {str(e)}")
        print("Please check your configuration and try again.")