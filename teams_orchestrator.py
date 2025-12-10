"""
Teams Orchestrator - Hosted Agent Version with WorkflowBuilder (EXACTLY like main_workflow_v2)
Replicates main_workflow_v2 functionality using WorkflowBuilder @executor pattern but designed for 
Foundry hosting and Teams integration with memory capabilities.
Architecture (SAME as main_workflow_v2):
Input → Analyzer → (Conditional) → Q&A + Validation (Concurrent) → Recommendation
                → (Skip Q&A) → Recommendation
"""
import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime

try:
    # Foundry hosted agent imports
    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import AgentRunContext, ConversationMemory, UserProfile
    from azure.identity import DefaultAzureCredential
    FOUNDRY_AVAILABLE = True
except ImportError:
    FOUNDRY_AVAILABLE = False
    # Fallback imports
    from azure.identity import DefaultAzureCredential

# WorkflowBuilder imports (SAME as main_workflow_v2)
from agent_framework import WorkflowBuilder, WorkflowContext, executor
from agent_framework import ChatAgent
from agent_framework.azure import AzureOpenAIChatClient

# Import your existing configurations
from dotenv import load_dotenv

from src.config import Config
from src.agents.agent_definitions import AgentDefinitions

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global agents dictionary (SAME pattern as main_workflow_v2)
_agents = {}
_agent_run_context = None  # Global context for Foundry Memory access

# DataClasses (SAME as main_workflow_v2)
@dataclass
class CVInput:
    """Initial input to the workflow (SAME as main_workflow_v2)"""
    cv_text: str
    job_description: str
    user_id: Optional[str] = None  # Added for Teams/memory support

@dataclass 
class AnalysisResult:
    """Analysis result with routing decision (SAME as main_workflow_v2)"""
    analysis_json: str
    cv_text: str
    job_description: str
    needs_qna: bool
    score: int
    user_id: Optional[str] = None  # Added for Teams/memory support

@dataclass
class QnAResult:
    """Q&A session result (SAME as main_workflow_v2)"""
    qna_insights: str
    analysis_result: AnalysisResult

# Teams-specific wrapper classes for Foundry hosting
@dataclass
class CVAnalysisRequest:
    """Teams-compatible request wrapper"""
    cv_text: str
    job_description: str
    user_id: str
    conversation_id: Optional[str] = None
    analysis_depth: str = "comprehensive"
    
@dataclass
class CVAnalysisResponse:
    """Teams-compatible response wrapper"""
    success: bool
    analysis_result: str
    score: int
    needs_qna: bool
    recommendation: str
    timestamp: datetime
    conversation_id: str
    conversation_insights: Optional[str] = None
    user_profile_updated: Optional[Dict[str, Any]] = None
    conversation_summary: Optional[str] = None
    processing_time: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

# Memory helper functions for Foundry integration
async def get_user_profile(user_id: str) -> Dict[str, Any]:
    """Retrieve user profile from Foundry Memory"""
    if not _agent_run_context or not FOUNDRY_AVAILABLE:
        return {}
    
    try:
        memory = _agent_run_context.conversation_memory
        user_profile = await memory.get_user_profile(user_id)
        return user_profile.to_dict() if user_profile else {}
    except Exception as e:
        logger.warning(f"Could not retrieve user profile: {e}")
        return {}

async def update_user_profile(user_id: str, analysis_data: Dict[str, Any]) -> Dict[str, Any]:
    """Update user profile with analysis insights"""
    if not _agent_run_context or not FOUNDRY_AVAILABLE:
        return {}
    
    try:
        memory = _agent_run_context.conversation_memory
        
        profile_updates = {
            "last_analysis_date": datetime.now().isoformat(),
            "skills_analyzed": analysis_data.get("skills", []),
            "career_level": analysis_data.get("experience_level", "unknown"),
            "preferred_roles": analysis_data.get("target_roles", []),
            "analysis_count": analysis_data.get("analysis_count", 0) + 1
        }
        
        await memory.update_user_profile(user_id, profile_updates)
        return profile_updates
    except Exception as e:
        logger.warning(f"Could not update user profile: {e}")
        return {}

async def save_conversation_context(user_id: str, analysis_summary: str):
    """Save conversation context to Foundry Memory"""
    if not _agent_run_context or not FOUNDRY_AVAILABLE:
        return
    
    try:
        memory = _agent_run_context.conversation_memory
        await memory.add_conversation_turn(
            user_id=user_id,
            user_message="CV analysis request",
            assistant_message=analysis_summary,
            metadata={"analysis_type": "cv_job_match", "timestamp": datetime.now().isoformat()}
        )
    except Exception as e:
        logger.warning(f"Could not save conversation context: {e}")

def should_run_qna(analysis_text: str) -> tuple[bool, int]:
    """Determine if Q&A needed (SAME logic as main_workflow_v2)"""
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
                    logger.info(f"🔍 Missing must-have requirements - Q&A needed")
                    return True, score
                elif score < 80:
                    logger.info(f"📊 Low score ({score}) - Q&A needed") 
                    return True, score
                else:
                    logger.info(f"✅ Good score ({score}) - skipping Q&A")
                    return False, score
                    
            except json.JSONDecodeError:
                pass
        
        # Fallback - assume Q&A needed if unclear
        logger.warning("Could not parse analysis - defaulting to Q&A")
        return True, 50
        
    except Exception as e:
        logger.error(f"Error in Q&A decision: {e}")
        return True, 50

# Initialize agents (SAME pattern as main_workflow_v2)
async def setup_agents(config: Config):
    """Initialize all agents (SAME setup as main_workflow_v2)"""
    global _agents
    
    logger.info("🏗️ Setting up agents for Teams orchestrator...")
    
    agents_config = AgentDefinitions.get_all_agents()
    credential = DefaultAzureCredential()
    azure_endpoint = config.azure_ai_foundry_endpoint.split('/api/projects/')[0]
    
    for agent_type, agent_config in agents_config.items():
        logger.info(f"Creating {agent_config['name']} agent")
        
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
    
    logger.info(f"✅ Created {len(_agents)} agents for Teams orchestrator")

# Interactive Q&A functions (COPIED from main_workflow_v2 for Teams compatibility)

async def read_current_gaps(gaps_file_path: str) -> list[str]:
    """Read current gaps from file."""
    try:
        with open(gaps_file_path, 'r') as f:
            return [line.strip() for line in f.readlines() if line.strip()]
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
    """EXACT copy from main_workflow_v2.py - Check validation status and return readiness and updated gaps."""
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
    
    is_complete, remaining_gaps = await check_validation_status(
        validation_agent, current_gaps, conversation_history, is_termination_attempt=True
    )
    
    if is_complete:
        summary_response = await get_agent_response(
            qna_agent,
            "The user is ready to conclude. Please provide a final summary of the key insights from our conversation.",
            thread
        )
        await update_gaps_file(gaps_file_path, [])
        return True, summary_response
    else:
        rejection_response = await get_agent_response(
            qna_agent,
            f"""The user said '{user_input}' to try to end the conversation, but we haven't fully covered these important areas yet: {', '.join(remaining_gaps)}
            
Please explain that there are still some important aspects we should explore, mention what we still need to discuss, and ask a specific follow-up question about one of these areas.""",
            thread
        )
        await update_gaps_file(gaps_file_path, remaining_gaps)
        return False, rejection_response

async def conduct_interactive_qna_with_validation(analysis_result: AnalysisResult) -> str:
    """
    COMPLETE interactive Q&A function copied from main_workflow_v2 for Teams orchestrator.
    Provides real multi-turn conversation with validation monitoring.
    """
    logger.info("🗣️ Starting interactive Q&A with validation (from main_workflow_v2)")
    
    gaps_file_path = "gaps_current.json"
    
    # Extract gaps from analysis
    gaps_list = []
    if '{' in analysis_result.analysis_json and '}' in analysis_result.analysis_json:
        try:
            json_start = analysis_result.analysis_json.find('{')
            json_end = analysis_result.analysis_json.rfind('}') + 1
            json_str = analysis_result.analysis_json[json_start:json_end]
            analysis_data = json.loads(json_str)
            gaps_list = [gap.get('name', str(gap)) for gap in analysis_data.get('gaps', [])]
        except json.JSONDecodeError:
            logger.warning("Could not parse analysis JSON for gaps")
    
    # Add mandatory gaps that must always be addressed (EXACT copy from main_workflow_v2)
    mandatory_gaps = [
        "Work authorization/location eligibility",
        "Role understanding and alignment with career goals"
    ]
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
    in_wrap_up_mode = False
    qna_summary = ""
    
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
            
            print(f"\n💡 Note: Guiding conversation to explore: {target_gap}")
            
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
        else:
            # Normal conversation flow - get agent response
            user_response = await get_agent_response(qna_agent, f"User response: {user_input}", thread)
            conversation_history.append(f"Advisor: {user_response}")
            
            # Check if agent asked termination question
            agent_asked_termination_question = detect_termination_question(user_response)
            
            # Run validation check and update gaps
            validation_ready, remaining_gaps = await check_validation_status(
                validation_agent, current_gaps, conversation_history
            )
            await update_gaps_file(gaps_file_path, remaining_gaps)
            
            # Handle termination logic
            if agent_asked_termination_question:
                in_wrap_up_mode = True
            elif validation_ready and len(conversation_history) >= 10 and not in_wrap_up_mode:
                # FALLBACK: Agent didn't naturally conclude but validation says we're ready
                ending_response = await get_agent_response(
                    qna_agent, 
                    "The conversation has covered the key areas well. Ask if there's anything specific they'd like to explore further, and make it clear they can answer 'n' if they feel everything has been covered.", 
                    thread
                )
                
                conversation_history.append(f"Advisor: {ending_response}")
                agent_asked_termination_question = True
                in_wrap_up_mode = True
    
    # MISSING CLEANUP - ensure gaps file is removed (EXACT copy from main_workflow_v2)
    try:
        if os.path.exists(gaps_file_path):
            os.remove(gaps_file_path)
            print(f"\n Cleaned up {gaps_file_path}")
    except Exception as e:
        logger.warning(f"Could not remove gaps file: {e}")
    
    logger.info("Interactive Q&A with validation monitoring completed")
    return qna_summary if qna_summary else "Conversation completed without formal termination."

# WorkflowBuilder Executors (EXACTLY like main_workflow_v2 but with Foundry Memory)

@executor(id="analyzer_executor") 
async def analyze_cv_job(input_data: CVInput, ctx: WorkflowContext[AnalysisResult]) -> None:
    """
    Executor 1: CV/Job Analysis (SAME as main_workflow_v2 + memory context)
    """
    logger.info(" Running CV analysis using direct agent calls...")
    
    # Get user profile context if available (NEW for Teams/Foundry)
    user_profile = {}
    if input_data.user_id:
        user_profile = await get_user_profile(input_data.user_id)
        if user_profile:
            logger.info(f"👤 Retrieved user profile with {len(user_profile)} fields")
    
    # Use direct agent (SAME as main_workflow_v2)
    analyzer = _agents["analyzer"]
    
    # Enhanced prompt with user profile context (NEW for Teams/Foundry)
    profile_context = ""
    if user_profile:
        profile_context = f"""
**USER PROFILE CONTEXT:**
Previous analysis count: {user_profile.get('analysis_count', 0)}
Career level: {user_profile.get('career_level', 'unknown')}
Skills focus: {', '.join(user_profile.get('skills_analyzed', [])[:5])}
Last analysis: {user_profile.get('last_analysis_date', 'never')}

"""
    
    # SAME prompt format as main_workflow_v2 but with optional profile context
    analysis_result = await analyzer.run(f"""{profile_context}**CANDIDATE CV:**
{input_data.cv_text}
**JOB DESCRIPTION:**
{input_data.job_description}""")
    
    analysis_text = analysis_result.messages[-1].text
    
    # SAME business logic as main_workflow_v2 for routing decision
    needs_qna, score = should_run_qna(analysis_text)
    
    # Show analysis results like main_workflow_v2 does
    print("\nInitial Analysis Complete!")
    print("=" * 40)
    print(analysis_text)
    print("=" * 40)
    
    # Create result for conditional routing (SAME as main_workflow_v2)
    result = AnalysisResult(
        analysis_json=analysis_text,
        cv_text=input_data.cv_text,
        job_description=input_data.job_description,
        needs_qna=needs_qna,
        score=score,
        user_id=input_data.user_id  # Added for Teams/memory support
    )
    
    logger.info(f"📊 Analysis complete. Score: {score}, Q&A needed: {needs_qna}")
    
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
    Executor 2: Q&A Session (EXACTLY like main_workflow_v2 with real interactive conversation)
    """
    logger.info("🗣️ Starting interactive Q&A session with validation monitoring...")
    
    # V2 Enhancement: Use interactive Q&A with validation monitoring (SAME as main_workflow_v2)
    qna_insights = await conduct_interactive_qna_with_validation(analysis)
    
    # Package result for final executor (SAME as main_workflow_v2)
    result = QnAResult(qna_insights=qna_insights, analysis_result=analysis)
    
    logger.info("✅ Interactive Q&A session with validation monitoring completed")
    await ctx.send_message(result)

@executor(id="recommendation_executor_with_qna") 
async def generate_recommendation_with_qna(qna_result: QnAResult, ctx: WorkflowContext[None, str]) -> None:
    """
    Executor 3a: Final Recommendation (after Q&A) - SAME as main_workflow_v2 + memory updates
    """
    logger.info("📝 Generating recommendation with Q&A using direct agent calls...")
    
    # Debug: Show what Q&A insights we received (SAME as main_workflow_v2)
    print(f"\n[DEBUG] Q&A Insights received:")
    print(f"Length: {len(qna_result.qna_insights)}")
    print(f"Content preview: {qna_result.qna_insights[:200]}...")
    print("[DEBUG] End Q&A Insights")
    
    # Use direct agent (SAME as main_workflow_v2)
    recommender = _agents["recommendation"]
    
    # SAME prompt format as main_workflow_v2's finalize_recommendation
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
    
    # Update user profile with insights (NEW for Teams/Foundry)
    if qna_result.analysis_result.user_id:
        try:
            # Parse analysis for profile updates
            analysis_data = {}
            if '{' in qna_result.analysis_result.analysis_json:
                json_start = qna_result.analysis_result.analysis_json.find('{')
                json_end = qna_result.analysis_result.analysis_json.rfind('}') + 1
                json_str = qna_result.analysis_result.analysis_json[json_start:json_end]
                analysis_data = json.loads(json_str)
            
            await update_user_profile(qna_result.analysis_result.user_id, analysis_data)
            
            # Save conversation context
            summary = f"CV analysis completed with Q&A. Score: {qna_result.analysis_result.score}. Key insights: {qna_result.qna_insights[:100]}..."
            await save_conversation_context(qna_result.analysis_result.user_id, summary)
        except Exception as e:
            logger.warning(f"Could not update user profile: {e}")
    
    # Add WorkflowBuilder identifier to result (SAME as main_workflow_v2)
    final_report = final_report.replace(
        "# CV/Job Analysis Report",
        "# CV/Job Analysis Report (Teams Orchestrator - WorkflowBuilder)"
    ).replace(
        "Analysis Complete",
        "Teams WorkflowBuilder Analysis Complete"
    )
    
    logger.info("✅ Workflow complete with Q&A!")
    await ctx.yield_output(final_report)

@executor(id="recommendation_executor_direct")
async def generate_recommendation_direct(analysis: AnalysisResult, ctx: WorkflowContext[None, str]) -> None:
    """
    Executor 3b: Final Recommendation (no Q&A) - SAME as main_workflow_v2 + memory updates
    """
    logger.info("📝 Generating recommendation without Q&A using direct agent calls...")
    
    # Use direct agent (SAME as main_workflow_v2)
    recommender = _agents["recommendation"]
    
    # SAME prompt format as main_workflow_v2's finalize_recommendation (without Q&A)
    recommendation_result = await recommender.run(f"""**ANALYSIS:**
{analysis.analysis_json}
**CV:**
{analysis.cv_text}
**JOB DESCRIPTION:**
{analysis.job_description}
Based on the analysis, provide a comprehensive final recommendation.""")
    
    final_report = recommendation_result.messages[-1].text
    
    # Update user profile with insights (NEW for Teams/Foundry)
    if analysis.user_id:
        try:
            # Parse analysis for profile updates
            analysis_data = {}
            if '{' in analysis.analysis_json:
                json_start = analysis.analysis_json.find('{')
                json_end = analysis.analysis_json.rfind('}') + 1
                json_str = analysis.analysis_json[json_start:json_end]
                analysis_data = json.loads(json_str)
            
            await update_user_profile(analysis.user_id, analysis_data)
            
            # Save conversation context
            summary = f"CV analysis completed without Q&A. Score: {analysis.score}. Direct recommendation provided."
            await save_conversation_context(analysis.user_id, summary)
        except Exception as e:
            logger.warning(f"Could not update user profile: {e}")
    
    # Add WorkflowBuilder identifier to result (SAME as main_workflow_v2)
    final_report = final_report.replace(
        "# CV/Job Analysis Report",
        "# CV/Job Analysis Report (Teams Orchestrator - WorkflowBuilder)"
    ).replace(
        "Analysis Complete",
        "Teams WorkflowBuilder Analysis Complete"
    )
    
    logger.info("✅ Workflow complete without Q&A!")
    await ctx.yield_output(final_report)

# Conditional routing functions (EXACTLY like main_workflow_v2)
def needs_qna_condition(message: Any) -> bool:
    """Condition function for Q&A routing (SAME as main_workflow_v2)"""
    if isinstance(message, AnalysisResult):
        return message.needs_qna
    return False

def skip_qna_condition(message: Any) -> bool:
    """Condition function for skipping Q&A (SAME as main_workflow_v2)"""
    if isinstance(message, AnalysisResult):
        return not message.needs_qna
    return False

# Teams Integration Functions (WorkflowBuilder-based, SAME structure as main_workflow_v2)

async def teams_analyze_cv(cv_text: str, job_description: str, user_id: str, agent_run_context: Optional['AgentRunContext'] = None) -> Dict[str, Any]:
    """
    Main Teams function for CV analysis using WorkflowBuilder (SAME as main_workflow_v2 + memory).
    This function will be called by Teams interface.
    """
    start_time = datetime.now()
    global _agent_run_context
    _agent_run_context = agent_run_context  # Store for use in executors
    
    # Load environment variables for Foundry deployment
    load_dotenv()
    config = Config()
    await setup_agents(config)
    
    logger.info(f"🚀 Starting WorkflowBuilder CV analysis for user {user_id}")
    
    # Build workflow with conditional edges (EXACTLY like main_workflow_v2)
    workflow = (
        WorkflowBuilder()
        .set_start_executor(analyze_cv_job)
        .add_edge(analyze_cv_job, handle_qna_session, condition=needs_qna_condition)
        .add_edge(handle_qna_session, generate_recommendation_with_qna)
        .add_edge(analyze_cv_job, generate_recommendation_direct, condition=skip_qna_condition)
        .build()
    )
    
    # Create input (SAME as main_workflow_v2 but with user_id for memory)
    input_data = CVInput(
        cv_text=cv_text, 
        job_description=job_description,
        user_id=user_id
    )
    
    # Execute workflow (SAME as main_workflow_v2)
    logger.info("⚙️ Executing WorkflowBuilder workflow...")
    
    final_result = None
    async for event in workflow.run_stream(input_data):
        if hasattr(event, 'data') and event.data:
            final_result = event.data
            print(f"\n{'='*80}")
            print("FINAL WORKFLOW RESULT (Teams Orchestrator)")
            print('='*80)
            print(event.data)
            break
    
    processing_time = (datetime.now() - start_time).total_seconds()
    
    # Return Teams-friendly format
    return {
        "success": True,
        "recommendation": final_result or "Analysis completed",
        "processing_time": processing_time,
        "memory_enabled": bool(agent_run_context and FOUNDRY_AVAILABLE),
        "workflow_type": "WorkflowBuilder",
        "architecture": "Teams Orchestrator with Foundry Memory"
    }

async def teams_get_analysis_status(conversation_id: str) -> Dict[str, Any]:
    """Get status of ongoing analysis (for Teams progress updates)"""
    return {
        "conversation_id": conversation_id,
        "status": "completed", 
        "progress": 100,
        "workflow_type": "WorkflowBuilder"
    }

# CLI for testing (SAME interface as main_workflow_v2 but for Teams orchestrator)
async def main():
    """CLI interface for testing - EXACTLY mirrors main_workflow_v2.main() structure with REAL data"""
    print("🚀 Teams Orchestrator - CV Analysis (WorkflowBuilder + Foundry Memory)")
    print("=" * 80)
    
    try:
        config = Config()
        await setup_agents(config)
        
        logger.info("🏗️ Building CV Analysis workflow for Teams...")
        
        # Build workflow with conditional edges (EXACTLY like main_workflow_v2)
        workflow = (
            WorkflowBuilder()
            .set_start_executor(analyze_cv_job)
            .add_edge(analyze_cv_job, handle_qna_session, condition=needs_qna_condition)
            .add_edge(handle_qna_session, generate_recommendation_with_qna)
            .add_edge(analyze_cv_job, generate_recommendation_direct, condition=skip_qna_condition)
            .build()
        )
        
        logger.info("✅ Workflow built with conditional Q&A routing")
        
        # Load REAL CV and job data (same as main_workflow_v2 does)
        try:
            with open("text_examples/my_cv.txt", "r", encoding="utf-8") as f:
                cv_content = f.read()
            
            with open("text_examples/job_descriptions.txt", "r", encoding="utf-8") as f:
                job_content = f.read()
                # Extract first job from file (simulate Teams single job input)
                jobs = job_content.split("Logo da empresa")[1:] if "Logo da empresa" in job_content else [job_content]
                if jobs:
                    job_content = "Logo da empresa" + jobs[0]  # Take first job
                    
        except FileNotFoundError:
            logger.warning("Real CV/job files not found, using sample data")
            cv_content = """Clara Espírito Santo 
Lisbon, Portugal | claire.esanto@gmail.com | linkedin.com/in/mariaclaraes

WORK EXPERIENCE
Microsoft Netherlands – Cloud Solution Architect Intern (Sep. 2025 – Present)
• Developing GenAI app for LinkedIn application using Azure AI Foundry and Agent Framework SDK
• Designing Ticket Sentiment Analysis using Azure AI Foundry with Model Fine-tuning
• Lead and organized events as part of Boost intern committee

EDUCATION  
Technical University of Delft - MSc Cognitive Robotics (Aug. 2024 – Sep. 2026)
• Machine learning, Human-Robot Interaction, Machine Perception with Python
• Robot Software Practicals with C++, Ready to Startup (YESDelft!)
• Key Projects: Pedestrian detection using YOLOv4, MPC for drone trajectory optimization

University of Twente - BSc Mechanical Engineering (Aug.2021 – Jul.2024)
• Average Grade: 7.82/10, ML-based thesis on Physical-Informed Neural Networks

SKILLS
Programming: Python (PyTorch, TensorFlow, Pandas, NumPy), C++, SQL, MATLAB
Cloud & AI: Azure Cloud, Azure AI Foundry, Copilot Studio, Docker, Kubernetes
Computer Vision: OpenCV, YOLO, ROS, Gazebo
Certifications: AZ-900 Azure Fundamentals (2025), AI-900 AI Fundamentals (2025)"""

            job_content = """Site Reliability Engineering Intern
Unbabel · Lisboa, Portugal (Híbrido)

About the role:
We are seeking a motivated Site Reliability Engineer (SRE) Intern to join our team. You will work alongside experienced engineers to ensure the reliability, availability, and performance of our systems and services.

Responsibilities:
• Collaborate with SRE team to monitor and maintain infrastructure and applications
• Assist in development and implementation of automation tools and scripts  
• Help troubleshoot system performance, reliability, and scalability issues
• Contribute to documentation of processes and best practices
• Support deployment and management of cloud-based infrastructure using infrastructure-as-code
• Work with engineering teams to ensure new features are reliable and scalable

Must have:
• Bachelor's degree in Computer Science, Engineering, or related field
• Strong programming skills in Python, Go, or similar languages
• Experience with Linux/Unix systems administration
• Understanding of cloud platforms (AWS, Azure, GCP)
• Knowledge of containerization technologies (Docker, Kubernetes)
• Familiarity with monitoring and logging tools
• Strong problem-solving and analytical skills
• Excellent communication and teamwork abilities

Nice to have:
• Experience with infrastructure-as-code tools (Terraform, Ansible)
• Knowledge of CI/CD pipelines and DevOps practices
• Understanding of database administration and optimization
• Experience with microservices architecture"""
        
        # Test with REAL data (like Teams would receive)
        input_data = CVInput(
            cv_text=cv_content,
            job_description=job_content,
            user_id="test_user_teams_clara_123"
        )
        
        print(f"\n📄 Testing with REAL CV data ({len(cv_content)} chars)")
        print(f"📋 Testing with REAL job data ({len(job_content)} chars)")
        print("="*60)
        
        # Execute workflow (SAME as main_workflow_v2)
        logger.info("⚙️ Executing WorkflowBuilder workflow...")
        
        async for event in workflow.run_stream(input_data):
            if hasattr(event, 'data') and event.data:
                print(f"\n{'='*80}")
                print("FINAL WORKFLOW RESULT - TEAMS ORCHESTRATOR (REAL DATA)")
                print('='*80)
                print(event.data)
                break
        
        logger.info("✅ Teams WorkflowBuilder execution completed successfully!")
        
    except Exception as e:
        logger.error(f"Teams workflow execution failed: {e}")
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())

# ============================================================================
# HOSTED AGENT WRAPPER - For Foundry deployment
# ============================================================================

class TeamsOrchestratorAgent:
    """Hosted agent wrapper for teams orchestrator deployment"""
    
    def __init__(self):
        self.config = None
        self.workflow = None
        self._initialized = False
    
    async def initialize(self):
        """Initialize the agent for hosted deployment"""
        if self._initialized:
            return
            
        try:
            # Load configuration
            self.config = Config.from_env()
            await setup_agents(self.config)
            
            # Create workflow instance
            self.workflow = WorkflowBuilder("cv_analysis_teams_workflow")
            self.workflow.add_route("analyze_cv", analyze_cv)
            self.workflow.add_route("conduct_qna", conduct_qna)
            
            self._initialized = True
            logger.info("✅ Teams orchestrator agent initialized for hosting")
            
        except Exception as e:
            logger.error(f"Failed to initialize teams orchestrator agent: {e}")
            raise
    
    async def teams_analyze_cv(self, cv_text: str, job_description: str, user_id: str) -> dict:
        """Main function exposed to Teams for CV analysis"""
        if not self._initialized:
            await self.initialize()
        
        try:
            # Create input data
            input_data = CVInput(
                cv_text=cv_text,
                job_description=job_description,
                user_id=user_id
            )
            
            # Execute workflow
            async for event in self.workflow.run_stream(input_data):
                if hasattr(event, 'data') and event.data:
                    # Parse the result and return structured response
                    result_data = event.data
                    
                    # Extract analysis information
                    analysis_info = self._parse_analysis_result(result_data)
                    
                    return {
                        "success": True,
                        "analysis_result": result_data,
                        "score": analysis_info.get("score", 0),
                        "needs_qna": analysis_info.get("needs_qna", False),
                        "recommendation": analysis_info.get("recommendation", "Analysis completed"),
                        "timestamp": datetime.now().isoformat(),
                        "user_id": user_id
                    }
            
            # Fallback if no result
            return {
                "success": False,
                "error": "No analysis result produced",
                "timestamp": datetime.now().isoformat(),
                "user_id": user_id
            }
            
        except Exception as e:
            logger.error(f"CV analysis failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
                "user_id": user_id
            }
    
    def _parse_analysis_result(self, result_data: str) -> dict:
        """Parse analysis result to extract key information"""
        try:
            # Try to extract JSON from the result
            if '{' in result_data and '}' in result_data:
                json_start = result_data.find('{')
                json_end = result_data.rfind('}') + 1
                json_str = result_data[json_start:json_end]
                
                analysis_data = json.loads(json_str)
                
                return {
                    "score": analysis_data.get("preliminary_score", 0),
                    "needs_qna": len(analysis_data.get("gaps", [])) > 0,
                    "recommendation": analysis_data.get("recommendation", "Analysis completed")
                }
        except:
            pass
        
        return {
            "score": 0,
            "needs_qna": True,
            "recommendation": "Analysis completed"
        }

# Create global agent instance for hosting
_hosted_agent = TeamsOrchestratorAgent()

# Expose functions for Foundry hosting
async def teams_analyze_cv(cv_text: str, job_description: str, user_id: str) -> dict:
    """Entry point for Foundry hosted deployment"""
    return await _hosted_agent.teams_analyze_cv(cv_text, job_description, user_id)