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
from workflows.main_mvp import read_cv_file, parse_job_descriptions, extract_job_title
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
        
    logger.info("Setting up local agents for WorkflowBuilder executors...")
    
    agents_config = AgentDefinitions.get_all_agents()
    
    azure_endpoint = config.azure_ai_foundry_endpoint.split('/api/projects/')[0]
    
    credential = DefaultAzureCredential()
    
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
    
    try:
        if '{' in analysis_text and '}' in analysis_text:
            json_start = analysis_text.find('{')
            json_end = analysis_text.rfind('}') + 1
            json_str = analysis_text[json_start:json_end]
            
            try:
                analysis_data = json.loads(json_str)
                gaps = analysis_data.get('gaps', [])
                must_have_gaps = [gap for gap in gaps if gap.get('requirement_type') == 'must']
                score = analysis_data.get('preliminary_score', 0)
                
                if len(must_have_gaps) > 0:
                    logger.info(f"Missing must-have requirements - Q&A needed")
                    return True, score
                elif score < 80:
                    logger.info(f"Low score ({score}) - Q&A needed") 
                    return True, score
                else:
                    logger.info(f"Good score ({score}) - skipping Q&A")
                    return False, score
                    
            except json.JSONDecodeError:
                pass
        
        logger.info("Could not parse analysis - defaulting to Q&A")
        return True, 0
        
    except Exception as e:
        logger.warning(f"Error in decision logic: {e} - defaulting to Q&A")
        return True, 0

async def read_current_gaps(gaps_file_path: str) -> list[str]:
    """Read and parse current gaps from file."""
    try:
        with open(gaps_file_path, 'r') as f:
            current_gaps = f.read().strip().split('\n')
        return [gap.strip() for gap in current_gaps if gap.strip()]
    except FileNotFoundError:
        return []

async def update_gaps_file(gaps_file_path: str, gaps: list[str]) -> None:
    """Update gaps file with remaining gaps."""
    with open(gaps_file_path, 'w') as f:
        for gap in gaps:
            f.write(f"{gap}\n")

def detect_termination_question(response: str) -> bool:
    """Check if response contains a termination question."""
    termination_phrases = [
        'anything else about the position',
        'anything else about your background',
        'anything else about the role',
        'anything else about your experience',
        'anything else you',
        'before we wrap up'
    ]
    return any(phrase in response.lower() for phrase in termination_phrases) and '?' in response

async def get_agent_response(agent: ChatAgent, prompt: str, thread) -> str:
    """Get streaming response from agent."""
    print(f"\nCareer Advisor: ", end="", flush=True)
    response = ""
    async for chunk in agent.run_stream(prompt, thread=thread):
        if chunk.text:
            print(chunk.text, end="", flush=True)
            response += chunk.text
    print()
    return response

async def check_validation_status(validation_agent: ChatAgent, current_gaps: list[str], 
                                conversation_history: list[str], is_termination_attempt: bool = False) -> tuple[bool, list[str]]:
    """Check validation status and return readiness and updated gaps."""
    recent_conversation = "\n".join(conversation_history[-4:])
    
    if is_termination_attempt:
        validation_input = f"""Current gaps to track:
{chr(10).join(current_gaps)}

Recent conversation exchange:
{recent_conversation}

User wants to end conversation. Please provide final readiness assessment."""
    else:
        validation_input = f"""Current gaps to track:
{chr(10).join(current_gaps)}

Recent conversation exchange:
{recent_conversation}"""
    
    try:
        validation_result = await validation_agent.run(validation_input)
        validation_response = validation_result.messages[-1].text
        validation_ready = "READY" in validation_response.upper()
        
        # Parse validation response and update gaps
        remaining_gaps = current_gaps.copy()
        if "REMOVE:" in validation_response:
            remove_section = validation_response.split("REMOVE:")[1].split("KEEP:")[0] if "KEEP:" in validation_response else validation_response.split("REMOVE:")[1].split("READINESS:")[0]
            remove_text = remove_section.strip()
            
            for gap in current_gaps:
                if gap in remove_text:
                    remaining_gaps.remove(gap)
        
        return validation_ready, remaining_gaps
    except Exception as e:
        logger.warning(f"Validation check failed: {e}")
        return False, current_gaps

async def handle_termination_attempt(qna_agent: ChatAgent, validation_agent: ChatAgent, 
                                   user_input: str, conversation_history: list[str],
                                   gaps_file_path: str, thread) -> tuple[bool, str]:
    """Handle user termination attempt with validation check."""
    current_gaps = await read_current_gaps(gaps_file_path)
    validation_ready, updated_gaps = await check_validation_status(
        validation_agent, current_gaps, conversation_history, is_termination_attempt=True
    )
    
    # User explicitly said "n" to termination question - respect their choice and end conversation
    if user_input.lower().strip() == 'n':
        print("\nGenerating final assessment...")
        summary = await get_agent_response(qna_agent, "Please provide your final assessment based on our conversation.", thread)
        return True, summary
    
    # For other termination attempts, check validation status
    if validation_ready and len(updated_gaps) == 0:
        # Proceed with final assessment
        print("\nGenerating final assessment...")
        summary = await get_agent_response(qna_agent, "Please provide your final assessment based on our conversation.", thread)
        return True, summary
    else:
        # Continue conversation - gaps remain or validation not ready
        print(f"\nCareer Advisor: Actually, let me ask you a bit more about a few things before we wrap up...")
        conversation_history.append(f"User: {user_input}")
        
        continue_prompt = f"The user wants to end the conversation, but we still have some important topics to explore. Please continue the conversation naturally to address remaining gaps: {', '.join(updated_gaps) if updated_gaps else 'general understanding'}."
        response = await get_agent_response(qna_agent, continue_prompt, thread)
        conversation_history.append(f"Advisor: {response}")
        
        await update_gaps_file(gaps_file_path, updated_gaps)
        return False, ""

async def conduct_interactive_qna_with_validation(analysis_result: AnalysisResult) -> str:
    gaps_file_path = "gaps_current.json"
    
    # Parse analysis and extract gaps
    analysis_json = analysis_result.analysis_json
    if "```json" in analysis_json:
        json_start = analysis_json.find("{")
        json_end = analysis_json.rfind("}") + 1
        analysis_json = analysis_json[json_start:json_end]
    
    try:
        analysis_data = json.loads(analysis_json) if analysis_json else {}
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse analysis JSON: {e}")
        analysis_data = {"gaps": []}
    
    # Initialize gaps file with mandatory gaps
    gaps_list = [gap.get('name', str(gap)) for gap in analysis_data.get('gaps', [])]
    
    # Add mandatory gaps that must always be addressed
    mandatory_gaps = [
        "Work authorization/location eligibility",
        "Role understanding and alignment with career goals"
    ]
    
    # Add mandatory gaps if they don't already exist
    for mandatory_gap in mandatory_gaps:
        if not any(mandatory_gap.lower() in existing_gap.lower() for existing_gap in gaps_list):
            gaps_list.append(mandatory_gap)
    
    await update_gaps_file(gaps_file_path, gaps_list)
    
    # Setup agents and conversation
    qna_agent = _agents["qna"]
    validation_agent = _agents["validation"]
    thread = qna_agent.get_new_thread()
    
    # Initial agent response
    initial_prompt = f"""**ANALYSIS:**
{analysis_result.analysis_json}
**CV:** {analysis_result.cv_text}
**JOB:** {analysis_result.job_description}"""
    
    qna_response = await get_agent_response(qna_agent, initial_prompt, thread)
    
    # Main conversation loop
    conversation_complete = False
    conversation_history = [qna_response]
    agent_asked_termination_question = False
    in_wrap_up_mode = False  # Track if we're in wrap-up mode where every response should end with 'n' prompt
    qna_summary = ""  # Initialize to avoid undefined variable error
    
    while not conversation_complete:
        print(f"\nYour response (or type 'done' to finish):")
        user_input = input().strip()
        
        if user_input.lower() == 'done':
            print("\nQ&A session complete!")
            return "User chose to end conversation. Based on conversation: " + "\n".join(conversation_history)
        
        # Add user input to conversation history
        conversation_history.append(f"User: {user_input}")
        
        user_exchanges = len([msg for msg in conversation_history if msg.startswith("User:")])
        current_gaps = await read_current_gaps(gaps_file_path)
        
        should_do_gap_targeting = (user_exchanges > 0 and user_exchanges % 5 == 0 and current_gaps)
        
        # Check for termination attempt BEFORE getting agent response
        if user_input.lower().strip() == 'n' and (agent_asked_termination_question or in_wrap_up_mode):
            try:
                is_complete, summary = await handle_termination_attempt(
                    qna_agent, validation_agent, user_input, conversation_history, gaps_file_path, thread
                )
                if is_complete:
                    conversation_complete = True
                    qna_summary = summary
                    continue
                else:
                    # Termination was rejected, reset flags and exit wrap-up mode
                    agent_asked_termination_question = False
                    in_wrap_up_mode = False
            except Exception as e:
                logger.warning(f"Final validation check failed: {e} - allowing conversation to end")
                summary = await get_agent_response(qna_agent, "Please provide your final assessment based on our conversation.", thread)
                conversation_complete = True
                qna_summary = summary
                continue
        elif should_do_gap_targeting:
            # Do gap targeting instead of normal response
            priority_gaps = [gap for gap in current_gaps if any(keyword in gap.lower() for keyword in ['networking', 'communication', 'teamwork', 'authorization', 'location'])]
            target_gap = priority_gaps[0] if priority_gaps else current_gaps[0]
            
            print(f"\n Note: Guiding conversation to explore: {target_gap}")
            
            gap_targeting_prompt = f"""The user just responded: "{user_input}"

Now I'd like you to acknowledge their response briefly, then naturally steer the conversation to explore their experience with: {target_gap}

Don't directly mention 'gaps' or make it obvious - just ask about related experiences, examples, or specific situations. Avoid asking 'what excites you' questions. Be conversational and focus on concrete examples."""
            
            gap_response = await get_agent_response(qna_agent, gap_targeting_prompt, thread)
            conversation_history.append(f"Advisor: {gap_response}")
            
            # Run validation check and update gaps after gap targeting
            validation_ready, updated_gaps = await check_validation_status(
                validation_agent, current_gaps, conversation_history
            )
            await update_gaps_file(gaps_file_path, updated_gaps)
            
            # Gap targeting responses might ask termination questions
            agent_asked_termination_question = detect_termination_question(gap_response)
            if agent_asked_termination_question:
                in_wrap_up_mode = True
        elif in_wrap_up_mode:
            # We're in wrap-up mode - user asked about something else, answer and prompt for 'n' again
            wrap_up_response = await get_agent_response(qna_agent, f"""User asked: "{user_input}"

Please answer their question thoroughly, then end your response by asking if there's anything else they'd like to explore, making it clear they can answer 'n' if they feel everything has been covered.""", thread)
            conversation_history.append(f"Advisor: {wrap_up_response}")
            
            # Run validation check and update gaps after wrap-up response
            validation_ready, updated_gaps = await check_validation_status(
                validation_agent, current_gaps, conversation_history
            )
            await update_gaps_file(gaps_file_path, updated_gaps)
            
            # We know we're asking for termination, so set the flag
            agent_asked_termination_question = True
            # Stay in wrap-up mode
        else:
            # Normal conversation flow - get agent response
            user_response = await get_agent_response(qna_agent, f"User response: {user_input}", thread)
            conversation_history.append(f"Advisor: {user_response}")
            
            # Check if agent asked termination question
            agent_asked_termination_question = detect_termination_question(user_response)
            
            # Run validation check and update gaps (reuse current_gaps from above)
            validation_ready, remaining_gaps = await check_validation_status(
                validation_agent, current_gaps, conversation_history
            )
            
            await update_gaps_file(gaps_file_path, remaining_gaps)
            
            # Handle termination logic - only ONE path should execute
            if agent_asked_termination_question:
                # Agent naturally asked termination question - enter wrap-up mode
                in_wrap_up_mode = True
            elif validation_ready and len(conversation_history) >= 10 and not in_wrap_up_mode:
                # FALLBACK: Agent didn't naturally conclude but validation says we're ready
                ending_response = await get_agent_response(
                    qna_agent, 
                    "The conversation has covered the key areas well. Ask if there's anything specific they'd like to explore further, and make it clear they can answer 'n' if they feel everything has been covered.", 
                    thread
                )
                
                conversation_history.append(f"Advisor: {ending_response}")
                # Enter wrap-up mode since we just asked a termination question
                agent_asked_termination_question = True
                in_wrap_up_mode = True
    
    # Cleanup - ensure gaps file is removed
    try:
        if os.path.exists(gaps_file_path):
            os.remove(gaps_file_path)
            print(f"\n Cleaned up {gaps_file_path}")
    except Exception as e:
        logger.warning(f"Could not remove gaps file: {e}")
    
    logger.info("Interactive Q&A with validation monitoring completed")
    return qna_summary if qna_summary else "Conversation completed without formal termination."

# WorkflowBuilder Executors (Simple @executor functions using MVP orchestrator)
@executor(id="analyzer_executor") 
async def analyze_cv_job(input_data: CVInput, ctx: WorkflowContext[AnalysisResult]) -> None:
    logger.info("🔧 Running CV analysis using direct agent calls...")
    
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
    logger.info("🔧 Starting interactive Q&A session with validation monitoring...")
    
    # V2 Enhancement: Use interactive Q&A with validation monitoring
    qna_insights = await conduct_interactive_qna_with_validation(analysis)
    
    # Package result for final executor (same as V1)
    result = QnAResult(qna_insights=qna_insights, analysis_result=analysis)
    
    logger.info("Interactive Q&A session with validation monitoring completed")
    await ctx.send_message(result)

@executor(id="recommendation_executor_with_qna") 
async def generate_recommendation_with_qna(qna_result: QnAResult, ctx: WorkflowContext[None, str]) -> None:

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

def create_cv_analysis_workflow():
    """Create the CV Analysis workflow for DevUI visualization."""
    logger.info("🏗️ Building CV Analysis workflow for DevUI...")
    
    workflow = (
        WorkflowBuilder()
        .set_start_executor(analyze_cv_job)
        .add_edge(analyze_cv_job, handle_qna_session, condition=needs_qna_condition)
        .add_edge(handle_qna_session, generate_recommendation_with_qna)
        .add_edge(analyze_cv_job, generate_recommendation_direct, condition=skip_qna_condition)
        .build()
    )
    
    # Set workflow metadata for DevUI
    workflow.id = "cv_analysis_workflow"
    workflow.description = "CV Analysis Workflow - Analyzes candidate CV against job requirements with optional Q&A session"
    
    logger.info(" CV Analysis workflow built for DevUI")
    return workflow

async def main():
    load_dotenv()
    
    # Check if configuration is set up (same as MVP)
    if not os.getenv("AZURE_AI_FOUNDRY_ENDPOINT"):
        print("⚠️  Configuration Setup Required")
        print("=" * 50)
        print("Please set up your configuration:")
        print("1. Copy .env.example to .env")
        print("2. Fill in your Azure AI Foundry endpoint and model deployment name")
        print("3. Ensure you're authenticated with Azure (az login)")
        return
    
    print("🔧 CV/Job Analysis Workflow - Version 2 (With Validation Agent)")
    print("=" * 65)
    
    try:
        # Setup agents first
        config = Config()
        await setup_agents(config)
        logger.info("✅ Agents setup complete")
        
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
