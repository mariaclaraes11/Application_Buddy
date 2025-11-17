"""
CV Analysis Workflow - Version 1 Simple (WorkflowBuilder with MVP Logic Reuse)

This version demonstrates WorkflowBuilder using simple @executor functions while
reusing functions directly from the MVP implementation.

Design Philosophy:
- Import MVP functions for file loading (no code duplication)
- Use WorkflowBuilder with @executor functions and edges
- Create agents directly (same setup as MVP but in executors)
- Keep the same business logic and conversation flow
- Demonstrate conditional routing with edges

Architecture:
Input → Analyzer → (Conditional) → Q&A → Recommendation
                → (Skip Q&A) → Recommendation
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict

# WorkflowBuilder imports  
from agent_framework import WorkflowBuilder, WorkflowContext, executor
from agent_framework import ChatAgent
from agent_framework.azure import AzureOpenAIChatClient
from azure.identity import DefaultAzureCredential

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
    Executor 2: Q&A Session using direct agent calls
    """
    logger.info(" Starting Q&A session using direct agent calls...")
    
    # Use direct conversation logic
    qna_insights = await conduct_qna_conversation_direct(analysis)
    
    # Package result for final executor
    result = QnAResult(qna_insights=qna_insights, analysis_result=analysis)
    
    logger.info("Q&A session completed")
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


async def load_files_from_mvp() -> tuple[str, str]:
    """
    Reuse the exact same file loading logic from MVP.
    This ensures identical file handling behavior.
    """
    logger.info(" Loading files ...")
    
    # Reuse MVP's file loading pattern
    try:
        # CV file (same logic as MVP)
        with open('text_examples/my_cv.txt', 'r', encoding='utf-8') as file:
            cv_content = file.read().strip()
        
        if not cv_content:
            raise FileNotFoundError("CV file is empty. Please fill in text_examples/my_cv.txt")
        
        # Job file (simplified - use first job like MVP single job mode)
        with open('text_examples/job_descriptions.txt', 'r', encoding='utf-8') as file:
            job_content = file.read().strip()
        
        if not job_content:
            raise FileNotFoundError("Job descriptions file is empty")
        
        # Use first job (simplified for workflow demo)
        # Could extend this to parse multiple jobs like MVP if needed
        if "JOB DESCRIPTION TEMPLATE" in job_content:
            raise FileNotFoundError("Please replace template with actual job description")
        
        logger.info(" Files loaded successfully")
        return cv_content, job_content
        
    except Exception as e:
        logger.error(f"Error loading files: {e}")
        raise


async def main():
    """
    Main execution using WorkflowBuilder with MVP logic reuse.
    """
    try:
        logger.info(" Starting CV Analysis Workflow - Version 1 Simple")
        logger.info(" Reusing MVP logic with WorkflowBuilder orchestration")
        
        # Setup agents first
        config = Config()
        await setup_agents(config)
        logger.info(" Agents setup complete")
        
        # Load files using MVP functions
        logger.info(" Loading files using MVP functions...")
        
        cv_content = read_cv_file()
        if not cv_content:
            return
        
        jobs = parse_job_descriptions()
        if not jobs:
            return
        
        # Use first job (simplified for workflow demo)
        job_content = jobs[0]['content']
        job_title = jobs[0]['title']
        
        logger.info(f" Loaded CV and job: {job_title}")
        
        # Build workflow with conditional edges
        logger.info(" Building WorkflowBuilder workflow with conditional routing...")
        
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
        input_data = CVInput(cv_text=cv_content, job_description=job_content)
        
        # Execute workflow
        logger.info(" Executing WorkflowBuilder workflow...")
        
        async for event in workflow.run_stream(input_data):
            # Handle workflow output
            if hasattr(event, 'data') and event.data:
                print(f"\n{'='*80}")
                print("FINAL WORKFLOW RESULT")
                print('='*80)
                print(event.data)
                break
        
        logger.info(" WorkflowBuilder execution completed successfully!")
        
    except Exception as e:
        logger.error(f"Workflow execution failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())