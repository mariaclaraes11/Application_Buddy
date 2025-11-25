"""
CV Analysis Workflow - Version 2 (WorkflowBuilder V1 + Concurrent Validation)
This version is exactly V1 but adds concurrent validation agent during Q&A phase.
All V1 logic remains identical - only the Q&A phase now runs validation in parallel.
Design Philosophy:
- Copy V1 exactly (same WorkflowBuilder @executor functions)
- Add concurrent validation agent ONLY during Q&A phase  
- Keep all existing business logic and conversation flow
- Same conditional routing with edges
- Validation agent monitors gaps.json and signals termination
Architecture:
Input → Analyzer → (Conditional) → Q&A + Validation (Concurrent) → Recommendation
                → (Skip Q&A) → Recommendation
"""
import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict
from dotenv import load_dotenv
# WorkflowBuilder imports  
from agent_framework import WorkflowBuilder, WorkflowContext, executor
from agent_framework import ChatAgent
from agent_framework.azure import AzureOpenAIChatClient
from azure.identity import DefaultAzureCredential, AzureCliCredential
# Import MVP functions directly (no code duplication!)
from main_mvp import read_cv_file, parse_job_descriptions, extract_job_title
from src.config import Config
from src.agents.agent_definitions import AgentDefinitions
# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class CVInput:
    """Initial input to the workflow."""
    cv_text: str
    job_description: str

@dataclass 
class AnalysisResult:
    """Analysis result with routing decision."""
    analysis_json: str
    cv_text: str
    job_description: str
    needs_qna: bool
    score: int

@dataclass
class QnAResult:
    """Q&A session result."""
    qna_insights: str
    analysis_result: AnalysisResult

# Global agents storage (direct agent setup like MVP)
_agents = {}

async def setup_agents(config: Config) -> Dict[str, ChatAgent]:
    """
    Setup agents directly (same logic as MVP's CleanOrchestrator._setup_agents)
    This creates local Agent Framework agents for use in executors.
    """
    global _agents
    if _agents:
        return _agents
        
    logger.info("Setting up local agents for WorkflowBuilder executors...")
    
    # Get agent definitions (same as MVP)
    agents_config = AgentDefinitions.get_all_agents()
    
    # Extract Azure endpoint (same logic as MVP)
    azure_endpoint = config.azure_ai_foundry_endpoint.split('/api/projects/')[0]
    
    # Create credential (same as MVP)
    credential = DefaultAzureCredential()
    
    # Create local agents (identical to MVP)
    for agent_type, agent_config in agents_config.items():
        logger.info(f"Creating local {agent_config['name']} agent")
        
        chat_client = AzureOpenAIChatClient(
            deployment_name=config.model_deployment_name,
            endpoint=azure_endpoint,
            api_version=config.api_version,
            credential=credential,
        )
        
        agent = ChatAgent(
            name=agent_config["name"],
            chat_client=chat_client,
            instructions=agent_config["instructions"]
        )
        
        _agents[agent_type] = agent
    
    logger.info(f"Created {len(_agents)} local agents for WorkflowBuilder")
    return _agents

def should_run_qna(analysis_text: str) -> tuple[bool, int]:
    """
    Same Q&A decision logic as MVP's CleanOrchestrator._should_run_qna
    This ensures identical routing behavior.
    """
    try:
        # Same JSON parsing logic as MVP
        if '{' in analysis_text and '}' in analysis_text:
            json_start = analysis_text.find('{')
            json_end = analysis_text.rfind('}') + 1
            json_str = analysis_text[json_start:json_end]
            
            try:
                analysis_data = json.loads(json_str)
                gaps = analysis_data.get('gaps', [])
                must_have_gaps = [gap for gap in gaps if gap.get('requirement_type') == 'must']
                score = analysis_data.get('preliminary_score', 0)
                
                # Same decision logic as MVP
                if len(must_have_gaps) > 0:
                    logger.info(f"Missing must-have requirements - Q&A needed")
                    return True, score
                elif score < 75:
                    logger.info(f"Low score ({score}) - Q&A needed") 
                    return True, score
                else:
                    logger.info(f"Good score ({score}) - skipping Q&A")
                    return False, score
                    
            except json.JSONDecodeError:
                pass
        
        # Fallback: default to Q&A (same as MVP)
        logger.info("Could not parse analysis - defaulting to Q&A")
        return True, 0
        
    except Exception as e:
        logger.warning(f"Error in decision logic: {e} - defaulting to Q&A")
        return True, 0

async def conduct_qna_conversation_direct(analysis_result: AnalysisResult) -> str:
    """
    Direct Q&A conversation using agents with proper thread-based conversation state
    """
    logger.info("Starting Q&A conversation using direct agent calls...")
    
    qna_agent = _agents["qna"]
    
    # Create thread for multi-turn conversation state
    thread = qna_agent.get_new_thread()
    
    # Start Q&A with thread (same prompt structure as MVP)
    qna_response = ""
    print(f"\nCareer Advisor: ", end="", flush=True)
    async for chunk in qna_agent.run_stream(f"""**ANALYSIS:**
{analysis_result.analysis_json}
**CV:** {analysis_result.cv_text}
**JOB:** {analysis_result.job_description}""", thread=thread):
        if chunk.text:
            print(chunk.text, end="", flush=True)
            qna_response += chunk.text
    print()  # New line after streaming complete
    
    # Interactive conversation loop with thread continuity
    conversation_complete = False
    
    while not conversation_complete:
        print(f"\nYour response (or type 'done' to finish):")
        user_input = input().strip()
        
        if user_input.lower() in ['done']:
            # Ask the Q&A agent for final assessment based on conversation using same thread with streaming
            print("\nGenerating conversation summary...")
            print("Career Advisor: ", end="", flush=True)
            qna_summary = ""
            async for chunk in qna_agent.run_stream("""The user has indicated they're ready to finish the conversation. 
Based on our entire conversation, please provide your final assessment in JSON format. Consider what you learned about:
- Skills/experiences that emerged through our conversation that weren't obvious in their CV
- Ways their background connects to this job that weren't apparent initially  
- Areas they could develop with learning vs significant barriers
- Things that should boost their confidence about applying
- How well they understand the role and their genuine interest
Provide the assessment in the required JSON format with discovered_strengths, hidden_connections, addressable_gaps, real_barriers, confidence_boosters, growth_areas, role_understanding, genuine_interest, and conversation_notes.""", thread=thread):
                if chunk.text:
                    print(chunk.text, end="", flush=True)
                    qna_summary += chunk.text
            print()  # New line after streaming complete
            print("\nQ&A assessment complete!")
            conversation_complete = True
        else:
            # Continue Q&A conversation using same thread for memory with streaming
            print(f"\nCareer Advisor: ", end="", flush=True)
            qna_response = ""
            async for chunk in qna_agent.run_stream(f"User response: {user_input}", thread=thread):
                if chunk.text:
                    print(chunk.text, end="", flush=True)
                    qna_response += chunk.text
            print()  # New line after streaming complete
            
            # Check if the agent provided a final JSON assessment (same logic as MVP)
            if ('discovered_strengths' in qna_response and 'conversation_notes' in qna_response) or \
               ('final assessment' in qna_response.lower()) or \
               ('{' in qna_response and '}' in qna_response and 'discovered_strengths' in qna_response):
                print("\nQ&A session complete!")
                qna_summary = qna_response
                conversation_complete = True
    
    logger.info("Q&A conversation completed using direct agent calls with thread")
    return qna_summary

async def conduct_interactive_qna_with_validation(analysis_result: AnalysisResult) -> str:
    """
    V2 Enhancement: Interactive Q&A with validation agent monitoring gaps
    User has interactive conversation while validation agent monitors gaps file
    """
    logger.info("Starting interactive Q&A with validation monitoring...")
    
    # Initialize gaps file for validation agent to monitor
    gaps_file_path = "gaps_current.json"
    
    # Clean JSON from analyzer output (remove markdown if present)
    analysis_json = analysis_result.analysis_json
    if "```json" in analysis_json:
        # Extract JSON from markdown code block
        json_start = analysis_json.find("{")
        json_end = analysis_json.rfind("}") + 1
        analysis_json = analysis_json[json_start:json_end]
    
    try:
        analysis_data = json.loads(analysis_json) if analysis_json else {}
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse analysis JSON: {e}")
        logger.warning(f"Raw analysis: {analysis_json[:200]}...")
        analysis_data = {"gaps": []}
    
    gaps_list = []
    
    # Extract gaps from analysis
    for gap in analysis_data.get('gaps', []):
        gaps_list.append(gap.get('name', str(gap)))
    
    # Add critical topics if mentioned in job posting
    job_lower = analysis_result.job_description.lower()
    if any(keyword in job_lower for keyword in ['visa', 'work authorization', 'location', 'remote', 'relocation']):
        gaps_list.append("Work authorization/location")
    
    # Write initial gaps file
    with open(gaps_file_path, 'w') as f:
        for gap in gaps_list:
            f.write(f"{gap}\n")
    
    # Setup agents
    qna_agent = _agents["qna"]
    validation_agent = _agents["validation"]
    
    # Create thread for Q&A conversation state
    thread = qna_agent.get_new_thread()
    
    # Start Q&A with initial analysis
    qna_response = ""
    print(f"\nCareer Advisor: ", end="", flush=True)
    async for chunk in qna_agent.run_stream(f"""**ANALYSIS:**
{analysis_result.analysis_json}
**CV:** {analysis_result.cv_text}
**JOB:** {analysis_result.job_description}""", thread=thread):
        if chunk.text:
            print(chunk.text, end="", flush=True)
            qna_response += chunk.text
    print()  # New line after streaming complete
    
    # Interactive conversation loop with validation monitoring
    conversation_complete = False
    conversation_history = [qna_response]
    
    while not conversation_complete:
        print(f"\nYour response (or type 'done' to finish):")
        user_input = input().strip()
        
        if user_input.lower() in ['done']:
            # User wants to finish - end conversation naturally
            print("\nQ&A session complete!")
            qna_summary = "User chose to end conversation. Based on conversation: " + "\n".join(conversation_history)
            conversation_complete = True
        else:
            # Continue conversation
            print(f"\nCareer Advisor: ", end="", flush=True)
            user_response = ""
            async for chunk in qna_agent.run_stream(f"User response: {user_input}", thread=thread):
                if chunk.text:
                    print(chunk.text, end="", flush=True)
                    user_response += chunk.text
            print()
            
            conversation_history.append(f"User: {user_input}")
            conversation_history.append(f"Advisor: {user_response}")
            
            # Check with validation agent if we should continue
            recent_conversation = "\n".join(conversation_history[-4:])  # Last 2 exchanges
            
            # Read current gaps file content
            try:
                with open(gaps_file_path, 'r') as f:
                    current_gaps = f.read().strip().split('\n')
                current_gaps = [gap.strip() for gap in current_gaps if gap.strip()]
            except FileNotFoundError:
                current_gaps = []
            
            validation_input = f"""Current gaps to track:
{chr(10).join(current_gaps)}

Recent conversation exchange:
{recent_conversation}

TASK: Analyze the conversation to see if the user has addressed any of the gaps listed above.

For each gap, determine if the user has provided relevant information, experience, or discussion that addresses that specific gap. Look for:
- Direct mentions of the gap topic
- Related experience or skills 
- Plans to learn or develop in that area
- Any discussion that shows knowledge or capability in that domain

Respond in this exact format:
REMOVE: [list the specific gap names that were addressed in the conversation]
KEEP: [list the specific gap names that still need discussion]
DECISION: CONTINUE/STOP - [brief reasoning]

Be specific - use the exact gap names from the list above."""
            
            try:
                validation_result = await validation_agent.run(validation_input)
                validation_response = validation_result.messages[-1].text
                
                # Parse validation response and update gaps file
                remaining_gaps = current_gaps.copy()
                if "REMOVE:" in validation_response:
                    # Extract the text after "REMOVE:"
                    remove_section = validation_response.split("REMOVE:")[1].split("KEEP:")[0] if "KEEP:" in validation_response else validation_response.split("REMOVE:")[1].split("DECISION:")[0]
                    remove_text = remove_section.strip()
                    
                    # Let the validation agent decide which exact gaps to remove
                    for gap in current_gaps:
                        if gap in remove_text:
                            remaining_gaps.remove(gap)
                
                # Update gaps file with remaining gaps
                with open(gaps_file_path, 'w') as f:
                    for gap in remaining_gaps:
                        f.write(f"{gap}\n")
                
                # Check if validation says to stop
                if "STOP" in validation_response.upper():
                    print(f"\n🔍 Validation Agent: {validation_response}")
                    print("\nQ&A session complete based on validation!")
                    
                    # Generate final assessment from Q&A agent
                    print("\nGenerating final assessment...")
                    print("Career Advisor: ", end="", flush=True)
                    qna_summary = ""
                    
                    # Create summary prompt using only conversation thread
                    conversation_text = "\n".join(conversation_history)
                    summary_prompt = f"""Based ONLY on our conversation thread below, provide your final assessment in JSON format.

CONVERSATION THREAD:
{conversation_text}

IMPORTANT: Only include information that was actually discussed in this conversation. Do not include any information from the user's CV or external knowledge. Focus only on what the user said during our Q&A exchange.

Provide assessment with: discovered_strengths, hidden_connections, addressable_gaps, real_barriers, confidence_boosters, growth_areas, role_understanding, genuine_interest, and conversation_notes."""
                    
                    async for chunk in qna_agent.run_stream(summary_prompt, thread=thread):
                        if chunk.text:
                            print(chunk.text, end="", flush=True)
                            qna_summary += chunk.text
                    print()
                    conversation_complete = True
                else:
                    # Don't show validation details, just continue
                    pass
                    
            except Exception as e:
                logger.warning(f"Validation check failed: {e}")
                # Continue conversation even if validation fails
            
            # Check if Q&A agent provided final assessment
            if ('discovered_strengths' in user_response and 'conversation_notes' in user_response) or \
               ('final assessment' in user_response.lower()):
                print("\nQ&A session complete!")
                qna_summary = user_response
                conversation_complete = True
    
    # Clean up gaps file
    try:
        os.remove(gaps_file_path)
    except:
        pass
    
    logger.info("Interactive Q&A with validation monitoring completed")
    return qna_summary

# WorkflowBuilder Executors (Simple @executor functions using MVP orchestrator)
@executor(id="analyzer_executor") 
async def analyze_cv_job(input_data: CVInput, ctx: WorkflowContext[AnalysisResult]) -> None:
    """
    Executor 1: CV/Job Analysis using direct agent calls
    """
    logger.info(" Running CV analysis using direct agent calls...")
    
    # Use direct agent (same as MVP setup)
    analyzer = _agents["analyzer"]
    
    # Same prompt format as MVP
    analysis_result = await analyzer.run(f"""**CANDIDATE CV:**
{input_data.cv_text}
**JOB DESCRIPTION:**
{input_data.job_description}""")
    
    analysis_text = analysis_result.messages[-1].text
    
    # Same business logic as MVP for routing decision
    needs_qna, score = should_run_qna(analysis_text)
    
    # Show analysis results like MVP does
    print("\nInitial Analysis Complete!")
    print("=" * 40)
    print(analysis_text)
    print("=" * 40)
    
    # Create result for conditional routing
    result = AnalysisResult(
        analysis_json=analysis_text,
        cv_text=input_data.cv_text,
        job_description=input_data.job_description,
        needs_qna=needs_qna,
        score=score
    )
    
    logger.info(f" Analysis complete. Score: {score}, Q&A needed: {needs_qna}")
    
    if needs_qna:
        print("\nLet's have a conversation to better understand your background.")
        print("=" * 50)
    else:
        print("\nAnalysis shows a strong fit - no additional questions needed")
    
    # Send to next executor (WorkflowBuilder handles conditional routing)
    await ctx.send_message(result)

@executor(id="qna_executor")
async def handle_qna_session(analysis: AnalysisResult, ctx: WorkflowContext[QnAResult]) -> None:
    """
    Executor 2: Interactive Q&A Session with Validation Monitoring (V2 Enhancement)
    User has interactive conversation while validation agent monitors gaps file
    """
    logger.info(" Starting interactive Q&A session with validation monitoring...")
    
    # V2 Enhancement: Use interactive Q&A with validation monitoring
    qna_insights = await conduct_interactive_qna_with_validation(analysis)
    
    # Package result for final executor (same as V1)
    result = QnAResult(qna_insights=qna_insights, analysis_result=analysis)
    
    logger.info("Interactive Q&A session with validation monitoring completed")
    await ctx.send_message(result)

@executor(id="recommendation_executor_with_qna") 
async def generate_recommendation_with_qna(qna_result: QnAResult, ctx: WorkflowContext[None, str]) -> None:
    """
    Executor 3a: Final Recommendation (after Q&A)
    Uses direct agent calls.
    """
    logger.info(" Generating recommendation with Q&A using direct agent calls...")
    
    # Debug: Show what Q&A insights we received
    print(f"\n[DEBUG] Q&A Insights received:")
    print(f"Length: {len(qna_result.qna_insights)}")
    print(f"Content preview: {qna_result.qna_insights[:200]}...")
    print("[DEBUG] End Q&A Insights")
    
    # Use direct agent (same as MVP setup)
    recommender = _agents["recommendation"]
    
    # Same prompt format as MVP's finalize_recommendation
    recommendation_result = await recommender.run(f"""**INITIAL ANALYSIS:**
{qna_result.analysis_result.analysis_json}
**Q&A INSIGHTS:**
{qna_result.qna_insights}
**CV:**
{qna_result.analysis_result.cv_text}
**JOB DESCRIPTION:**
{qna_result.analysis_result.job_description}
Based on the initial analysis and the Q&A conversation insights, provide a comprehensive final recommendation.""")
    
    final_report = recommendation_result.messages[-1].text
    
    # Add WorkflowBuilder identifier to result
    final_report = final_report.replace(
        "# CV/Job Analysis Report",
        "# CV/Job Analysis Report (WorkflowBuilder Version 1)"
    ).replace(
        "Analysis Complete",
        "WorkflowBuilder Analysis Complete"
    )
    logger.info(" Workflow complete with Q&A!")
    await ctx.yield_output(final_report)

@executor(id="recommendation_executor_direct")
async def generate_recommendation_direct(analysis: AnalysisResult, ctx: WorkflowContext[None, str]) -> None:
    """
    Executor 3b: Final Recommendation (skipping Q&A)  
    Uses direct agent calls.
    """
    logger.info(" Generating recommendation without Q&A using direct agent calls...")
    
    # Use direct agent (same as MVP setup)
    recommender = _agents["recommendation"]
    
    # Same prompt format as MVP's finalize_recommendation (without Q&A)
    recommendation_result = await recommender.run(f"""**ANALYSIS:**
{analysis.analysis_json}
**CV:**
{analysis.cv_text}
**JOB DESCRIPTION:**
{analysis.job_description}
Based on the analysis, provide a comprehensive final recommendation.""")
    
    final_report = recommendation_result.messages[-1].text
    
    # Add WorkflowBuilder identifier to result
    final_report = final_report.replace(
        "# CV/Job Analysis Report",
        "# CV/Job Analysis Report (WorkflowBuilder Version 1)"
    ).replace(
        "Analysis Complete",
        "WorkflowBuilder Analysis Complete"
    )
    logger.info(" Workflow complete without Q&A!")
    await ctx.yield_output(final_report)

def needs_qna_condition(message: Any) -> bool:
    """Condition function for Q&A routing."""
    return isinstance(message, AnalysisResult) and message.needs_qna

def skip_qna_condition(message: Any) -> bool:
    """Condition function for skipping Q&A."""
    return isinstance(message, AnalysisResult) and not message.needs_qna

def display_job_options(jobs):
    """Display job selection menu (same as MVP)"""
    print("\n Available Job Descriptions:")
    print("-" * 40)
    for i, job in enumerate(jobs, 1):
        print(f"{i}. {job['title']}")
    print(f"{len(jobs) + 1}. Analyze all jobs")
    print("0. Exit")

async def analyze_single_job(cv_content, job):
    """Analyze a single job using WorkflowBuilder (V2 with validation)"""
    logger.info(f" Analyzing job: {job['title']}")
    
    # Build workflow with conditional edges (same as before)
    workflow = (
        WorkflowBuilder()
        .set_start_executor(analyze_cv_job)
        .add_edge(analyze_cv_job, handle_qna_session, condition=needs_qna_condition)
        .add_edge(handle_qna_session, generate_recommendation_with_qna)
        .add_edge(analyze_cv_job, generate_recommendation_direct, condition=skip_qna_condition)
        .build()
    )
    
    # Create input and execute
    input_data = CVInput(cv_text=cv_content, job_description=job['content'])
    
    async for event in workflow.run_stream(input_data):
        if hasattr(event, 'data') and event.data:
            print(f"\n{'='*80}")
            print("FINAL WORKFLOW RESULT")
            print('='*80)
            print(event.data)
            break

async def analyze_all_jobs(cv_content, jobs):
    """Analyze all jobs sequentially (same as MVP logic)"""
    print(f"\n Analyzing all {len(jobs)} jobs...")
    print("=" * 50)
    
    for i, job in enumerate(jobs, 1):
        print(f"\n{'='*60}")
        print(f" JOB {i}/{len(jobs)}: {job['title']}")
        print("="*60)
        
        await analyze_single_job(cv_content, job)
        
        # Add spacing between jobs
        if i < len(jobs):
            print("\n" + "="*60)
            print(" Moving to next job...")
            print("="*60)
    
    print(f"\n Analysis of all {len(jobs)} jobs completed!")

async def main():
    """
    Main execution with full MVP user experience + V2 validation agent.
    """
    # Load environment variables
    load_dotenv()
    
    # Check if configuration is set up (same as MVP)
    if not os.getenv("AZURE_AI_FOUNDRY_ENDPOINT"):
        print("  Configuration Setup Required")
        print("=" * 50)
        print("Please set up your configuration:")
        print("1. Copy .env.example to .env")
        print("2. Fill in your Azure AI Foundry endpoint and model deployment name")
        print("3. Ensure you're authenticated with Azure (az login)")
        return
    
    print(" CV/Job Analysis Workflow - Version 2 (With Validation Agent)")
    print("=" * 65)
    
    try:
        # Setup agents first
        config = Config()
        await setup_agents(config)
        logger.info(" Agents setup complete")
        
        # Read CV content (same as MVP)
        print(" Reading your CV...")
        cv_content = read_cv_file()
        if not cv_content:
            return
        print(" CV loaded successfully")
        
        # Parse job descriptions (same as MVP)
        print(" Loading job descriptions...")
        jobs = parse_job_descriptions()
        if not jobs:
            return
        print(f" Found {len(jobs)} job description(s)")
        
        # Handle single job vs multiple jobs (same as MVP logic)
        if len(jobs) == 1:
            print(f"\n Found 1 job description: {jobs[0]['title']}")
            response = input("Analyze this job? (y/n): ").strip().lower()
            if response in ['y', 'yes', '']:
                await analyze_single_job(cv_content, jobs[0])
        else:
            # Multiple jobs - show selection menu (same as MVP)
            while True:
                display_job_options(jobs)
                
                try:
                    choice = input(f"\nSelect option (1-{len(jobs) + 1}, 0 to exit): ").strip()
                    
                    if choice == '0':
                        print(" Goodbye!")
                        break
                    elif choice == str(len(jobs) + 1):
                        # Analyze all jobs
                        await analyze_all_jobs(cv_content, jobs)
                        break
                    else:
                        job_index = int(choice) - 1
                        if 0 <= job_index < len(jobs):
                            await analyze_single_job(cv_content, jobs[job_index])
                            
                            # Ask if they want to continue (same as MVP)
                            continue_choice = input(f"\nAnalyze another job? (y/n): ").strip().lower()
                            if continue_choice not in ['y', 'yes']:
                                break
                        else:
                            print(" Invalid selection. Please try again.")
                            
                except ValueError:
                    print(" Please enter a valid number.")
                except KeyboardInterrupt:
                    print("\n Goodbye!")
                    break
        
    except KeyboardInterrupt:
        print("\n Goodbye!")
    except Exception as e:
        print(f" Error: {str(e)}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n Application terminated by user.")
    except Exception as e:
        print(f" Fatal error: {str(e)}")
        print("Please check your configuration and try again.")
