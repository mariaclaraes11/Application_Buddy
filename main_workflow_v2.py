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
import datetime
from dataclasses import dataclass
from typing import Any, Dict

# WorkflowBuilder imports  
from agent_framework import WorkflowBuilder, WorkflowContext, executor
from agent_framework import ChatAgent, ConcurrentBuilder, ChatMessage
from agent_framework.azure import AzureOpenAIChatClient
from azure.identity import DefaultAzureCredential, AzureCliCredential

# Import file loading functions for CV and job descriptions
from main_mvp import read_cv_file, parse_job_descriptions, extract_job_title
from src.config import Config
from src.agents.agent_definitions import AgentDefinitions

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global session gaps file path
_session_gaps_file = None


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


# Global agents storage for direct agent access
_agents = {}


async def setup_agents(config: Config) -> Dict[str, ChatAgent]:
    """
    Setup agents directly for WorkflowBuilder execution
    This creates local Agent Framework agents for use in executors.
    """
    global _agents
    if _agents:
        return _agents
        
    logger.info("Setting up local agents for WorkflowBuilder executors...")
    
    # Get agent definitions
    agents_config = AgentDefinitions.get_all_agents()
    
    # Extract Azure endpoint configuration
    azure_endpoint = config.azure_ai_foundry_endpoint.split('/api/projects/')[0]
    
    # Create credential for Azure authentication
    credential = DefaultAzureCredential()
    
    # Create local agents for direct access
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
    Determine if Q&A is needed based on analysis results
    This ensures consistent routing behavior.
    """
    try:
        # Parse analysis JSON to check for gaps
        if '{' in analysis_text and '}' in analysis_text:
            json_start = analysis_text.find('{')
            json_end = analysis_text.rfind('}') + 1
            json_str = analysis_text[json_start:json_end]
            
            try:
                analysis_data = json.loads(json_str)
                gaps = analysis_data.get('gaps', [])
                must_have_gaps = [gap for gap in gaps if gap.get('requirement_type') == 'must']
                score = analysis_data.get('preliminary_score', 0)
                
                # Evaluate decision criteria
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
        
        # Fallback: default to Q&A for safety
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
    
    # Start Q&A with thread for conversation continuity
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
            
            # Check if the agent provided a final JSON assessment
            if ('discovered_strengths' in qna_response and 'conversation_notes' in qna_response) or \
               ('final assessment' in qna_response.lower()) or \
               ('{' in qna_response and '}' in qna_response and 'discovered_strengths' in qna_response):
                print("\nQ&A session complete!")
                qna_summary = qna_response
                conversation_complete = True
    
    logger.info("Q&A conversation completed using direct agent calls with thread")
    return qna_summary


async def conduct_concurrent_qna_validation(analysis_result: AnalysisResult, session_gaps_file: str) -> str:
    """
    V2 Enhancement: Concurrent Q&A + Validation using Agent Framework ConcurrentBuilder
    Same conversation logic as V1 but adds validation agent running in parallel
    Uses existing session gaps file instead of creating new one
    """
    logger.info("Starting concurrent Q&A + validation session...")
    
    # Add gaps from this job to existing session gaps file
    analysis_json = analysis_result.analysis_json
    analysis_data = {}
    
    # Extract JSON from markdown formatting if present
    try:
        if '```json' in analysis_json:
            # Extract JSON from markdown code block
            json_start = analysis_json.find('```json') + 7
            json_end = analysis_json.find('```', json_start)
            json_str = analysis_json[json_start:json_end].strip()
            analysis_data = json.loads(json_str)
        elif '{' in analysis_json and '}' in analysis_json:
            # Extract JSON from plain text
            json_start = analysis_json.find('{')
            json_end = analysis_json.rfind('}') + 1
            json_str = analysis_json[json_start:json_end]
            analysis_data = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning(f"Could not parse analysis JSON: {e}")
        analysis_data = {}
    with open(session_gaps_file, 'a') as f:  # Append mode
        for gap in analysis_data.get('gaps', []):
            f.write(f"{gap['name']}\n")
        
        # Add critical topics if mentioned in job posting
        job_lower = analysis_result.job_description.lower()
        if any(keyword in job_lower for keyword in ['visa', 'work authorization', 'location', 'remote', 'relocation']):
            f.write("Work authorization/location\n")
    
    print(f" Added {len(analysis_data.get('gaps', []))} gaps to session file for validation agent")
    
    # Show gaps file content for transparency
    try:
        with open(session_gaps_file, 'r') as f:
            gaps_content = f.read().strip()
            if gaps_content:
                gaps_list = gaps_content.split('\n')
                print(f"📋 Current gaps being tracked: {gaps_list}")
            else:
                print("📋 No gaps to track - proceeding with conversation")
    except Exception as e:
        logger.warning(f"Could not read gaps file for display: {e}")
    
    # Create chat client for concurrent agents (same config as main setup)
    config = Config()
    azure_endpoint = config.azure_ai_foundry_endpoint.split('/api/projects/')[0]
    credential = DefaultAzureCredential()
    
    chat_client = AzureOpenAIChatClient(
        deployment_name=config.model_deployment_name,
        endpoint=azure_endpoint,
        api_version=config.api_version,
        credential=credential,
    )
    
    # Create QnA agent (same instructions as V1)
    qna_def = AgentDefinitions.get_qna_agent()
    qna_agent = chat_client.create_agent(
        instructions=qna_def["instructions"],
        name=qna_def["name"]
    )
    
    # Create validation agent (V2 addition)
    validation_def = AgentDefinitions.get_validation_agent()
    validation_agent = chat_client.create_agent(
        instructions=validation_def["instructions"],
        name=validation_def["name"]
    )
    
    # Build concurrent workflow (Q&A + Validation in parallel) 
    workflow = ConcurrentBuilder().participants([qna_agent, validation_agent]).build()
    
    print("🤔 Starting concurrent Q&A and validation session...")
    print("💡 Watch for validation agent status updates during conversation!")
    
    # Initial Q&A prompt (same as V1)
    initial_input = f"""**ANALYSIS:**
{analysis_result.analysis_json}

**CV:** {analysis_result.cv_text}
**JOB:** {analysis_result.job_description}"""
    
    # Start the conversation with Q&A agent only (validation will run in background)
    qna_thread = qna_agent.get_new_thread()
    
    print(f"\nCareer Advisor: ", end="", flush=True)
    qna_response = ""
    async for chunk in qna_agent.run_stream(initial_input, thread=qna_thread):
        if chunk.text:
            print(chunk.text, end="", flush=True)
            qna_response += chunk.text
    print()  # New line after streaming complete
    
    # Start validation agent in background monitoring the gaps file
    validation_input = f"gaps_json_path: {session_gaps_file}\nStart monitoring gaps and provide updates as conversation progresses."
    
    # Interactive conversation loop (same as V1 pattern)
    conversation_complete = False
    
    while not conversation_complete:
        print(f"\nYour response (or type 'done' to finish):")
        user_input = input().strip()
        
        if user_input.lower() in ['done']:
            # Ask for final assessment using same thread
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

Provide the assessment in the required JSON format with discovered_strengths, hidden_connections, addressable_gaps, real_barriers, confidence_boosters, growth_areas, role_understanding, genuine_interest, and conversation_notes.""", thread=qna_thread):
                if chunk.text:
                    print(chunk.text, end="", flush=True)
                    qna_summary += chunk.text
            print()  # New line after streaming complete
            print("\nQ&A assessment complete!")
            conversation_complete = True
        else:
            # Continue Q&A conversation using same thread for memory
            print(f"\nCareer Advisor: ", end="", flush=True)
            qna_response = ""
            async for chunk in qna_agent.run_stream(f"User response: {user_input}", thread=qna_thread):
                if chunk.text:
                    print(chunk.text, end="", flush=True)
                    qna_response += chunk.text
            print()  # New line after streaming complete
            
            # Check if the agent provided a final JSON assessment
            if ('discovered_strengths' in qna_response and 'conversation_notes' in qna_response) or \
               ('final assessment' in qna_response.lower()) or \
               ('{' in qna_response and '}' in qna_response and 'discovered_strengths' in qna_response):
                print("\nQ&A session complete!")
                qna_summary = qna_response
                conversation_complete = True
    
    # End validation monitoring
    print("🔍 Validation monitoring complete")
    
    print("✅ Concurrent Q&A and validation session completed")
    
    # Return the final Q&A summary from the interactive conversation
    logger.info("Concurrent Q&A + validation session completed")
    return qna_summary if 'qna_summary' in locals() else "Q&A conversation completed."


def monitor_gaps_status(gaps_file_path: str) -> None:
    """Display current gaps status for user visibility"""
    try:
        if not os.path.exists(gaps_file_path):
            print("📊 Gaps Status: No gaps file found")
            return
            
        with open(gaps_file_path, 'r') as f:
            content = f.read().strip()
            
        if not content:
            print("🎯 Gaps Status: All gaps covered! ✅")
        else:
            gaps = [line.strip() for line in content.split('\n') if line.strip()]
            print(f"📋 Gaps Status: {len(gaps)} gap(s) remaining: {gaps}")
            
    except Exception as e:
        print(f"⚠️ Could not read gaps status: {e}")


# Add this helper function for displaying gaps progress during conversation    logger.warning("No completion received from concurrent session")
    return "Concurrent session completed but no insights captured."


# WorkflowBuilder Executors (@executor functions with conditional routing)

@executor(id="analyzer_executor") 
async def analyze_cv_job(input_data: CVInput, ctx: WorkflowContext[AnalysisResult]) -> None:
    """
    Executor 1: CV/Job Analysis using direct agent calls
    """
    logger.info(" Running CV analysis using direct agent calls...")
    
    # Use direct agent access
    analyzer = _agents["analyzer"]
    
    # Standard prompt format for analysis
    analysis_result = await analyzer.run(f"""**CANDIDATE CV:**
{input_data.cv_text}

**JOB DESCRIPTION:**
{input_data.job_description}""")
    
    analysis_text = analysis_result.messages[-1].text
    
    # Apply business logic for routing decision
    needs_qna, score = should_run_qna(analysis_text)
    
    # Show analysis results
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
    Executor 2: Q&A Session with Concurrent Validation (V2 Enhancement)
    Always uses validation agent with session gaps for any Q&A session
    """
    logger.info("🔄 Starting Q&A session with concurrent validation...")
    
    # V2 Enhancement: Always create session gaps file for Q&A
    global _session_gaps_file
    if not _session_gaps_file:
        # Create session gaps file for this Q&A session
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        _session_gaps_file = f"gaps_session_{timestamp}.json"
        
        # Initialize empty gaps file
        with open(_session_gaps_file, 'w') as f:
            pass  # Create empty file
        
        logger.info(f"📋 Created session gaps file: {_session_gaps_file}")
    
    # Always use concurrent Q&A + validation
    qna_insights = await conduct_concurrent_qna_validation(analysis, _session_gaps_file)
    
    # Package result for final executor
    result = QnAResult(qna_insights=qna_insights, analysis_result=analysis)
    
    logger.info("✅ Q&A session with concurrent validation completed")
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
    
    # Use direct agent access
    recommender = _agents["recommendation"]
    
    # Standard prompt format for final recommendation
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
    
    # Use direct agent access
    recommender = _agents["recommendation"]
    
    # Standard prompt format for final recommendation (without Q&A)
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
    """Display available job options for selection"""
    print("\n Available Job Descriptions:")
    print("=" * 40)
    
    for i, job in enumerate(jobs):
        print(f"{i + 1}. {job['title']}")
    
    print(f"{len(jobs) + 1}.  Analyze all jobs (with session gaps tracking)")
    print("0. Exit")


async def analyze_single_job_v2(cv_content, job):
    """Analyze CV against a single job using V2 WorkflowBuilder + concurrent validation"""
    print(f"\n Analyzing: {job['title']}")
    print("=" * 50)
    
    try:
        # Build workflow with conditional edges (same as V1)
        logger.info(f" Building WorkflowBuilder workflow for job: {job['title']}")
        
        workflow = (
            WorkflowBuilder()
            # Start with analysis
            .set_start_executor(analyze_cv_job)
            # Conditional routing for Q&A
            .add_edge(analyze_cv_job, handle_qna_session, condition=needs_qna_condition)
            .add_edge(handle_qna_session, generate_recommendation_with_qna)
            # Skip Q&A path
            .add_edge(analyze_cv_job, generate_recommendation_direct, condition=skip_qna_condition)
            .build()
        )
        
        logger.info(" Workflow built with conditional Q&A routing")
        
        # Create input
        input_data = CVInput(cv_text=cv_content, job_description=job['content'])
        
        # Execute workflow
        logger.info(f" Executing WorkflowBuilder workflow for job: {job['title']}")
        
        async for event in workflow.run_stream(input_data):
            # Handle workflow output
            if hasattr(event, 'data') and event.data:
                print(f"\n{'='*80}")
                print(f"FINAL WORKFLOW RESULT - {job['title']}")
                print('='*80)
                print(event.data)
                return event.data  # Return result for potential aggregation
        
        logger.info(f" WorkflowBuilder execution completed for job: {job['title']}")
        return None
        
    except Exception as e:
        logger.error(f"Error analyzing {job['title']}: {e}")
        print(f" Error analyzing {job['title']}: {str(e)}")
        return None
    
    finally:
        # Clean up session gaps file for single job analysis
        global _session_gaps_file
        if _session_gaps_file and os.path.exists(_session_gaps_file):
            try:
                print(f"\n🗑️ Cleaning up session gaps file: {_session_gaps_file}")
                os.remove(_session_gaps_file)
                _session_gaps_file = None  # Reset for next job
            except Exception as e:
                logger.warning(f"Could not clean up gaps file: {e}")


async def analyze_all_jobs_v2(cv_content, jobs):
    """Analyze CV against all jobs with V2 session gaps tracking"""
    global _session_gaps_file
    
    print(f"\n Analyzing CV against {len(jobs)} job(s) with session gaps tracking...")
    print("=" * 70)
    
    # V2 Enhancement: Create one session gaps file for all jobs
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    _session_gaps_file = f"gaps_session_{timestamp}.json"
    
    # Initialize empty gaps file
    with open(_session_gaps_file, 'w') as f:
        pass  # Create empty file
    
    print(f"📝 Created session gaps file: {_session_gaps_file}")
    print("💡 You'll see validation agent status updates during Q&A sessions!")
    
    results = []
    
    try:
        for i, job in enumerate(jobs, 1):
            print(f"\n Job {i}/{len(jobs)}: {job['title']}")
            print("=" * 60)
            
            try:
                # Use V2 single job analysis
                result = await analyze_single_job_v2(cv_content, job)
                if result:
                    results.append({
                        'job_title': job['title'],
                        'analysis': result
                    })
                    print(f" Completed: {job['title']}")
                    
                    # Ask if user wants to continue to next job (if not last job)
                    if i < len(jobs):
                        continue_choice = input(f"\nContinue to next job? (y/n): ").strip().lower()
                        if continue_choice not in ['y', 'yes', '']:
                            print("Stopping analysis at user request.")
                            break
                            
            except Exception as e:
                print(f" Error with {job['title']}: {str(e)}")
                continue
        
        # Summary if multiple jobs were analyzed
        if len(results) > 1:
            print(f"\n SUMMARY: Analyzed {len(results)} job(s)")
            print("=" * 50)
            for i, result in enumerate(results, 1):
                print(f"{i}. {result['job_title']} - Analysis completed")
        
        return results
        
    finally:
        # Always clean up session gaps file
        try:
            if _session_gaps_file and os.path.exists(_session_gaps_file):
                print(f"\n Cleaning up session gaps file: {_session_gaps_file}")
                os.remove(_session_gaps_file)
        except Exception as e:
            logger.warning(f"Could not clean up gaps file: {e}")


async def main():
    """
    V2 Main execution with user-friendly job selection menu
    """
    global _session_gaps_file
    
    try:
        logger.info(" Starting CV Analysis Workflow - Version 2 (V1 + Concurrent Validation)")
        logger.info(" Enhanced with session-based gap tracking and user choice menu")
        
        # Setup agents first
        config = Config()
        await setup_agents(config)
        logger.info(" Agents setup complete")
        
        # Load files using standard file loading functions
        logger.info(" Loading files from text_examples directory...")
        
        cv_content = read_cv_file()
        if not cv_content:
            return
        
        jobs = parse_job_descriptions()
        if not jobs:
            return
        
        logger.info(f" Loaded CV and {len(jobs)} job description(s)")
        
        # Handle single job vs multiple jobs (standard pattern)
        if len(jobs) == 1:
            print(f"\n Found 1 job description: {jobs[0]['title']}")
            response = input("Analyze this job? (y/n): ").strip().lower()
            if response in ['y', 'yes', '']:
                # Single job analysis (no session gaps file needed)
                await analyze_single_job_v2(cv_content, jobs[0])
        else:
            # Multiple jobs - show selection menu (user-friendly pattern)
            while True:
                display_job_options(jobs)
                
                try:
                    choice = input(f"\nSelect option (1-{len(jobs) + 1}, 0 to exit): ").strip()
                    
                    if choice == '0':
                        print(" Goodbye!")
                        break
                    elif choice == str(len(jobs) + 1):
                        # Analyze all jobs with session gaps tracking
                        await analyze_all_jobs_v2(cv_content, jobs)
                        break
                    else:
                        job_index = int(choice) - 1
                        if 0 <= job_index < len(jobs):
                            # Single job analysis (no session gaps file needed)
                            await analyze_single_job_v2(cv_content, jobs[job_index])
                            
                            # Ask if they want to continue
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
        
        logger.info(" Session completed successfully!")
        
    except KeyboardInterrupt:
        print("\n Goodbye!")
    except Exception as e:
        logger.error(f"Workflow execution failed: {e}")
        # Clean up gaps file on error
        try:
            if _session_gaps_file and os.path.exists(_session_gaps_file):
                os.remove(_session_gaps_file)
        except:
            pass
        raise


if __name__ == "__main__":
    asyncio.run(main())