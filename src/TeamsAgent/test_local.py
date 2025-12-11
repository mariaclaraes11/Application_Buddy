"""
Local test script for CV workflow - uses actual sample files.
"""
import asyncio
import sys
import os

# Add parent paths for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def test_workflow():
    """Test the workflow locally with real data."""
    from agent_framework import ChatMessage, FunctionCallContent, FunctionResultContent, Role, WorkflowAgent
    from workflow import build_cv_workflow_agent, QnAAnswer
    
    print("=" * 60)
    print("CV Analysis Workflow - Local Test")
    print("=" * 60)
    
    # Load sample files
    samples_dir = os.path.join(os.path.dirname(__file__), "..", "..", "text_examples")
    
    try:
        with open(os.path.join(samples_dir, "my_cv.txt"), "r") as f:
            cv_text = f.read()
        with open(os.path.join(samples_dir, "job_descriptions.txt"), "r") as f:
            job_text = f.read()
        print(f"✓ Loaded CV ({len(cv_text)} chars) and job description ({len(job_text)} chars)")
    except FileNotFoundError:
        print("Sample files not found, using placeholder text...")
        cv_text = """
        Jane Doe - Software Engineer
        5 years experience in Python, AWS, and distributed systems.
        Education: BS Computer Science
        """
        job_text = """
        Senior Software Engineer
        Requirements: 7+ years experience, Python, cloud platforms, team leadership.
        Location: Seattle, WA (hybrid)
        """
    
    print("\nBuilding workflow agent...")
    agent = build_cv_workflow_agent()
    print("✓ Agent built successfully")
    
    print("\n" + "=" * 60)
    print("Starting analysis...")
    print("=" * 60 + "\n")
    
    # Start workflow
    response = await agent.run(f"Analyze this CV:\n{cv_text}\n\nFor this job:\n{job_text}")
    
    turn = 0
    # Handle HITL loop
    while True:
        turn += 1
        
        # Check for HITL request
        hitl_call = None
        for message in response.messages:
            for content in message.contents:
                if isinstance(content, FunctionCallContent) and content.name == WorkflowAgent.REQUEST_INFO_FUNCTION_NAME:
                    hitl_call = content
                    break
            if hitl_call:
                break
        
        if not hitl_call:
            # Workflow complete
            print("\n" + "=" * 60)
            print("WORKFLOW COMPLETE")
            print("=" * 60)
            print("\nFinal response:")
            print(response.messages[-1].text if response.messages else "No response")
            break
        
        # Extract the question from the HITL request
        print(f"\n--- Turn {turn} ---")
        
        # Try to extract question text
        try:
            if hasattr(hitl_call, 'arguments'):
                args = hitl_call.arguments
                if isinstance(args, str):
                    import json
                    args = json.loads(args)
                if isinstance(args, dict) and 'data' in args:
                    data = args['data']
                    if hasattr(data, 'question'):
                        print(f"\n🤖 Advisor: {data.question}")
                    elif isinstance(data, dict) and 'question' in data:
                        print(f"\n🤖 Advisor: {data['question']}")
                    else:
                        print(f"\n🤖 Advisor is asking a question...")
                else:
                    print(f"\n🤖 Advisor is asking a question...")
        except Exception as e:
            print(f"\n🤖 Advisor is asking a question... (debug: {e})")
        
        # Get user input
        print()
        user_answer = input("👤 You: ")
        
        if user_answer.lower() == 'quit':
            print("Exiting test...")
            break
        
        # Send back to workflow
        result = FunctionResultContent(
            call_id=hitl_call.call_id,
            result=QnAAnswer(answer=user_answer)
        )
        response = await agent.run(ChatMessage(role=Role.TOOL, contents=[result]))


if __name__ == "__main__":
    print("Starting local test...")
    asyncio.run(test_workflow())