"""
CV Analysis Workflow - State-Based Pattern for Teams Compatibility

Architecture:
Same flow as TeamsOrchestrator but WITHOUT request_info HITL.
State is tracked via conversation history instead of generator suspension.

Input → Analyzer → (Conditional) → Q&A + Validation → Recommendation
                               ↘ Recommendation (skip Q&A if score ≥ 80)

Compatible with: Teams, Foundry Playground, any UI.
"""
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum

from dotenv import load_dotenv
load_dotenv()

from agent_framework import (
    AgentRunResponseUpdate,
    ChatAgent,
    ChatMessage,
    Executor,
    Role,
    TextContent,
    WorkflowBuilder,
    WorkflowContext,
    handler,
)
from agent_framework._workflows._edge import Case, Default
from agent_framework._workflows._events import AgentRunUpdateEvent
from agent_framework.azure import AzureOpenAIChatClient
from azure.identity import DefaultAzureCredential

from datetime import datetime, timezone
import uuid

from config import Config
from agent_definitions import AgentDefinitions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# Helper to emit response to HTTP (not just inter-executor messaging)
# ============================================================================

async def emit_response(ctx: WorkflowContext, text: str, executor_id: str = "state-workflow") -> None:
    """Emit a text response that will appear in the HTTP response.
    
    Unlike ctx.send_message() which sends between executors,
    this emits an AgentRunUpdateEvent that the server converts to HTTP response.
    """
    update = AgentRunResponseUpdate(
        contents=[TextContent(text=text)],
        role=Role.ASSISTANT,
        author_name=executor_id,
        response_id=str(uuid.uuid4()),
        message_id=str(uuid.uuid4()),
        created_at=datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    )
    await ctx.add_event(AgentRunUpdateEvent(executor_id=executor_id, data=update))


# ============================================================================
# Workflow States (for state-based tracking)
# ============================================================================

class WorkflowState(Enum):
    """Possible states in the conversation workflow."""
    WELCOME = "welcome"
    WAITING_CV = "waiting_cv"
    WAITING_JOB = "waiting_job"
    ANALYZING = "analyzing"
    QNA = "qna"
    RECOMMENDING = "recommending"
    COMPLETE = "complete"


# ============================================================================
# Message Types (kept from original for internal use)
# ============================================================================

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
    gaps: List[str] = field(default_factory=list)


@dataclass
class QnAComplete:
    """Signal that Q&A is complete, ready for recommendation."""
    analysis_result: AnalysisResult
    qna_insights: str
    conversation_history: List[str]


@dataclass
class FinalRecommendation:
    """Final output of the workflow."""
    recommendation: str


# ============================================================================
# Helper Functions (from original)
# ============================================================================

def should_run_qna(analysis_text: str) -> tuple[bool, int, list]:
    """Determine if Q&A is needed and extract gaps."""
    gaps = []
    try:
        if '{' in analysis_text and '}' in analysis_text:
            json_start = analysis_text.find('{')
            json_end = analysis_text.rfind('}') + 1
            json_str = analysis_text[json_start:json_end]
            
            try:
                analysis_data = json.loads(json_str)
                raw_gaps = analysis_data.get('gaps', [])
                gaps = [gap.get('name', str(gap)) for gap in raw_gaps]
                must_have_gaps = [gap for gap in raw_gaps if gap.get('requirement_type') == 'must']
                score = analysis_data.get('preliminary_score', 0)
                
                # Add mandatory gaps
                mandatory = ["Work authorization/location eligibility", "Role understanding and alignment with career goals"]
                for m in mandatory:
                    if not any(m.lower() in g.lower() for g in gaps):
                        gaps.append(m)
                
                if len(must_have_gaps) > 0 or score < 80:
                    return True, score, gaps
                else:
                    return False, score, gaps
            except json.JSONDecodeError:
                pass
        return True, 0, gaps
    except Exception as e:
        logger.warning(f"Error in decision logic: {e}")
        return True, 0, gaps


def detect_termination_question(response: str) -> bool:
    """Check if response contains a termination question."""
    termination_phrases = [
        'anything else about the position',
        'anything else about your background',
        'anything else about the role',
        'anything else about your experience',
        'anything else you',
        'before we wrap up',
        "anything else",
        "any other questions",
    ]
    return any(phrase in response.lower() for phrase in termination_phrases) and '?' in response


async def check_validation_status(
    validation_agent: ChatAgent, 
    current_gaps: List[str], 
    conversation_history: List[str], 
    is_termination_attempt: bool = False
) -> tuple[bool, List[str]]:
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
        
        remaining_gaps = current_gaps.copy()
        removed_gaps = []
        if "REMOVE:" in validation_response:
            remove_section = validation_response.split("REMOVE:")[1].split("KEEP:")[0] if "KEEP:" in validation_response else validation_response.split("REMOVE:")[1].split("READINESS:")[0]
            remove_text = remove_section.strip()
            
            for gap in current_gaps:
                if gap in remove_text:
                    remaining_gaps.remove(gap)
                    removed_gaps.append(gap)
        
        if removed_gaps:
            print(f"\n Gaps addressed: {', '.join(removed_gaps)}")
            print(f" Remaining gaps: {len(remaining_gaps)}")
        
        return validation_ready, remaining_gaps
    except Exception as e:
        logger.warning(f"Validation check failed: {e}")
        return False, current_gaps


# ============================================================================
# State Detection from Message History
# ============================================================================

# Markers to identify state from assistant messages
STATE_MARKERS = {
    "cv_request": "please paste your cv",
    "job_request": "paste the job description",
    "analysis_complete": " analysis complete",
    "recommendation": "## should you apply?",
}


def extract_message_text(msg: ChatMessage) -> str:
    """Extract text from a ChatMessage."""
    if hasattr(msg, 'content') and msg.content:
        text = ""
        for c in msg.content:
            if hasattr(c, 'text'):
                text += c.text
        return text
    elif hasattr(msg, 'text'):
        return msg.text
    return str(msg)


def determine_state_from_history(messages: List[ChatMessage]) -> tuple[WorkflowState, Dict[str, Any]]:
    """
    Determine current workflow state from conversation history.
    Returns (state, context_data).
    """
    context = {
        "cv_text": None,
        "job_description": None,
        "in_qna": False,
        "in_wrap_up": False,
    }
    
    if not messages:
        return WorkflowState.WELCOME, context
    
    user_messages = [m for m in messages if m.role == Role.USER]
    assistant_messages = [m for m in messages if m.role == Role.ASSISTANT]
    
    # Get message texts
    user_texts = [extract_message_text(m) for m in user_messages]
    assistant_texts = [extract_message_text(m) for m in assistant_messages]
    
    last_assistant_text = assistant_texts[-1].lower() if assistant_texts else ""
    
    # Check for completion (recommendation already given)
    for text in assistant_texts:
        if STATE_MARKERS["recommendation"] in text.lower():
            return WorkflowState.COMPLETE, context
    
    # Check for Q&A mode (analysis was completed)
    for text in assistant_texts:
        if STATE_MARKERS["analysis_complete"] in text.lower():
            # We're in Q&A mode
            if len(user_texts) >= 2:
                context["cv_text"] = user_texts[0]
                context["job_description"] = user_texts[1]
            context["in_qna"] = True
            
            # Check if we're in wrap-up
            if detect_termination_question(last_assistant_text):
                context["in_wrap_up"] = True
            
            return WorkflowState.QNA, context
    
    # Check what assistant has asked for to determine state
    cv_was_requested = any(STATE_MARKERS["cv_request"] in text.lower() for text in assistant_texts)
    job_was_requested = any(STATE_MARKERS["job_request"] in text.lower() for text in assistant_texts)
    
    # If assistant hasn't asked for CV yet, this is welcome state
    if not cv_was_requested:
        return WorkflowState.WELCOME, context
    
    # CV was requested - check if user provided it
    # Count user messages AFTER the CV request
    cv_request_idx = next(
        (i for i, text in enumerate(assistant_texts) if STATE_MARKERS["cv_request"] in text.lower()),
        -1
    )
    
    # User messages count (first user message after CV request is the CV)
    user_count = len(user_texts)
    
    if user_count == 0:
        # CV requested but not provided yet
        return WorkflowState.WAITING_CV, context
    
    if user_count == 1:
        # Got CV, check if we asked for job yet
        context["cv_text"] = user_texts[0]
        if job_was_requested:
            return WorkflowState.WAITING_JOB, context
        else:
            # Need to ask for job description
            return WorkflowState.WAITING_JOB, context
    
    if user_count == 2:
        # Got both CV and job - need to analyze
        context["cv_text"] = user_texts[0]
        context["job_description"] = user_texts[1]
        return WorkflowState.ANALYZING, context
    
    # More than 2 messages - must be in Q&A
    if len(user_texts) >= 2:
        context["cv_text"] = user_texts[0]
        context["job_description"] = user_texts[1]
    context["in_qna"] = True
    return WorkflowState.QNA, context


# ============================================================================
# Single State-Based Executor (replaces multiple HITL executors)
# ============================================================================

class StateBasedWorkflowExecutor(Executor):
    """
    Single executor that handles the entire workflow using state detection.
    
    Instead of HITL request_info pauses, this executor:
    1. Receives the full conversation history each turn
    2. Determines current state from history
    3. Performs the appropriate action
    4. Returns a text response
    
    The workflow "advances" by detecting state changes in the conversation.
    """
    
    def __init__(
        self,
        analyzer_agent: ChatAgent,
        qna_agent: ChatAgent,
        validation_agent: ChatAgent,
        recommender_agent: ChatAgent,
    ):
        super().__init__(id="state-based-workflow-executor")
        self._analyzer = analyzer_agent
        self._qna_agent = qna_agent
        self._validation_agent = validation_agent
        self._recommender = recommender_agent
        
        # Q&A conversation state
        self._qna_thread = None
        self._gaps: List[str] = []
        self._analysis_text: str = ""
        self._conversation_history: List[str] = []
    
    @handler
    async def handle_messages(self, messages: List[ChatMessage], ctx: WorkflowContext) -> None:
        """Main handler - determines state and responds appropriately."""
        
        # Determine state from conversation history
        state, context_data = determine_state_from_history(messages)
        logger.info(f"State detected: {state.value}")
        
        # Get the latest user input
        user_input = ""
        user_messages = [m for m in messages if m.role == Role.USER]
        if user_messages:
            user_input = extract_message_text(user_messages[-1])
        
        # Route to appropriate handler
        if state == WorkflowState.WELCOME:
            await self._send_welcome(ctx)
        
        elif state == WorkflowState.WAITING_JOB:
            await self._acknowledge_cv_ask_job(ctx, context_data.get("cv_text", ""))
        
        elif state == WorkflowState.ANALYZING:
            await self._run_analysis(
                ctx, 
                context_data.get("cv_text", ""),
                context_data.get("job_description", "")
            )
        
        elif state == WorkflowState.QNA:
            await self._handle_qna_turn(
                ctx,
                user_input,
                context_data,
                messages
            )
        
        elif state == WorkflowState.COMPLETE:
            await emit_response(
                ctx,
                "Your recommendation has already been provided. Start a new conversation to analyze another job!",
                self.id
            )
    
    async def _send_welcome(self, ctx: WorkflowContext) -> None:
        """Send welcome message and ask for CV."""
        welcome = (
            "👋 **Welcome to Application Buddy!**\n\n"
            "I'll help you evaluate if a job is right for you by:\n"
            "1. Analyzing your CV against the job requirements\n"
            "2. Having a conversation to understand your experience better\n"
            "3. Providing a personalized recommendation\n\n"
            "Let's start - **please paste your CV** (your full resume text):"
        )
        await emit_response(ctx, welcome, self.id)
    
    async def _acknowledge_cv_ask_job(self, ctx: WorkflowContext, cv_text: str) -> None:
        """Acknowledge CV receipt and ask for job description."""
        if not cv_text or len(cv_text.strip()) < 50:
            await emit_response(
                ctx,
                "I didn't receive a valid CV. Please paste your full resume text.",
                self.id
            )
            return
        
        response = (
            f" **Got your CV!** ({len(cv_text)} characters)\n\n"
            "Now, **please paste the job description** you're interested in:"
        )
        await emit_response(ctx, response, self.id)
    
    async def _run_analysis(
        self, 
        ctx: WorkflowContext, 
        cv_text: str, 
        job_description: str
    ) -> None:
        """Run CV analysis and start Q&A or skip to recommendation."""
        
        logger.info("Running CV analysis...")
        
        # Run analyzer
        analysis_prompt = f"""**CANDIDATE CV:**
{cv_text}

**JOB DESCRIPTION:**
{job_description}"""
        
        result = await self._analyzer.run(analysis_prompt)
        analysis_text = result.messages[-1].text
        self._analysis_text = analysis_text
        
        # Determine if Q&A is needed
        needs_qna, score, gaps = should_run_qna(analysis_text)
        self._gaps = gaps
        
        logger.info(f"Analysis complete. Score: {score}, Needs Q&A: {needs_qna}, Gaps: {len(gaps)}")
        
        # Print analysis summary
        print("\n" + "=" * 60)
        print(" ANALYSIS COMPLETE")
        print("=" * 60)
        print(f" Score: {score}/100")
        print(f" Gaps: {len(gaps)}")
        for i, gap in enumerate(gaps, 1):
            print(f"   {i}. {gap}")
        print("=" * 60 + "\n")
        
        if needs_qna:
            # Start Q&A - initialize thread and get first question
            self._qna_thread = self._qna_agent.get_new_thread()
            self._conversation_history = []
            
            qna_prompt = f"""**ANALYSIS:**
{analysis_text}

**CV:**
{cv_text}

**JOB DESCRIPTION:**
{job_description}"""
            
            qna_result = await self._qna_agent.run(qna_prompt, thread=self._qna_thread)
            first_question = qna_result.messages[-1].text
            self._conversation_history.append(f"Advisor: {first_question}")
            
            response = (
                f" **Analysis complete!**\n\n"
                f"I found {len(gaps)} areas to explore. Let's chat to understand your experience better.\n\n"
                f"---\n\n"
                f"{first_question}\n\n"
                f"*(Type 'done' anytime to get your final recommendation)*"
            )
            await emit_response(ctx, response, self.id)
        
        else:
            # High score - skip Q&A, generate recommendation directly
            logger.info("High score - skipping Q&A, generating recommendation...")
            await self._generate_recommendation(ctx, cv_text, job_description, "")
    
    async def _handle_qna_turn(
        self,
        ctx: WorkflowContext,
        user_input: str,
        context_data: Dict[str, Any],
        messages: List[ChatMessage]
    ) -> None:
        """Handle a turn in the Q&A conversation."""
        
        cv_text = context_data.get("cv_text", "")
        job_description = context_data.get("job_description", "")
        in_wrap_up = context_data.get("in_wrap_up", False)
        
        # Check for done/termination commands
        user_lower = user_input.lower().strip()
        if user_lower in ['done', 'n', 'no', 'nothing', "that's all", "thats all"]:
            logger.info("User ended Q&A - generating recommendation")
            qna_summary = await self._get_qna_summary()
            await self._generate_recommendation(ctx, cv_text, job_description, qna_summary)
            return
        
        # Add user input to conversation history
        self._conversation_history.append(f"User: {user_input}")
        
        # Ensure we have a Q&A thread
        if self._qna_thread is None:
            self._qna_thread = self._qna_agent.get_new_thread()
        
        # Determine prompt based on context
        user_exchanges = len([h for h in self._conversation_history if h.startswith("User:")])
        
        # Gap targeting every 5th exchange
        should_target_gap = (user_exchanges > 0 and user_exchanges % 5 == 0 and self._gaps)
        
        if should_target_gap:
            priority_gaps = [gap for gap in self._gaps if any(keyword in gap.lower() 
                for keyword in ['networking', 'communication', 'teamwork', 'authorization', 'location'])]
            target_gap = priority_gaps[0] if priority_gaps else self._gaps[0]
            
            qna_prompt = f"""The user just responded: "{user_input}"

Now I'd like you to acknowledge their response briefly, then naturally steer the conversation to explore their experience with: {target_gap}

Don't directly mention 'gaps' - just ask about related experiences. Be conversational."""
        
        elif in_wrap_up:
            qna_prompt = f"""User asked: "{user_input}"

Please answer their question thoroughly, then ask if there's anything else they'd like to explore. Make it clear they can say 'done' or 'n' when ready for the final recommendation."""
        
        else:
            qna_prompt = f"User response: {user_input}"
        
        # Get Q&A agent response
        result = await self._qna_agent.run(qna_prompt, thread=self._qna_thread)
        response = result.messages[-1].text
        self._conversation_history.append(f"Advisor: {response}")
        
        # Run validation to update gaps
        _, updated_gaps = await check_validation_status(
            self._validation_agent, 
            self._gaps, 
            self._conversation_history
        )
        self._gaps = updated_gaps
        
        # Check if this is a wrap-up question
        if detect_termination_question(response):
            response += "\n\n*(Say 'done' or 'n' when you're ready for your recommendation)*"
        
        await emit_response(ctx, response, self.id)
    
    async def _get_qna_summary(self) -> str:
        """Get final summary from Q&A agent."""
        if self._qna_thread is None:
            return "No Q&A conversation occurred."
        
        summary_prompt = "Please provide your final assessment based on our conversation."
        result = await self._qna_agent.run(summary_prompt, thread=self._qna_thread)
        return result.messages[-1].text
    
    async def _generate_recommendation(
        self,
        ctx: WorkflowContext,
        cv_text: str,
        job_description: str,
        qna_insights: str
    ) -> None:
        """Generate final recommendation."""
        
        logger.info("Generating final recommendation...")
        
        recommendation_prompt = f"""**CV:**
{cv_text}

**JOB DESCRIPTION:**
{job_description}

**ANALYSIS:**
{self._analysis_text}

**Q&A INSIGHTS:**
{qna_insights if qna_insights else "No Q&A conversation - high initial match score."}

Please provide your recommendation."""
        
        result = await self._recommender.run(recommendation_prompt)
        recommendation = result.messages[-1].text
        
        await emit_response(ctx, recommendation, self.id)


# ============================================================================
# Agent Factory
# ============================================================================

def create_agents(config: Config) -> Dict[str, ChatAgent]:
    """Create all ChatAgents for the workflow."""
    logger.info("Setting up agents...")
    
    agents_config = AgentDefinitions.get_all_agents()
    azure_endpoint = config.azure_ai_foundry_endpoint.split('/api/projects/')[0]
    credential = DefaultAzureCredential()
    
    agents = {}
    for agent_type, agent_config in agents_config.items():
        chat_client = AzureOpenAIChatClient(
            deployment_name=config.model_deployment_name,
            endpoint=azure_endpoint,
            api_version=config.api_version,
            credential=credential,
        )
        agents[agent_type] = ChatAgent(
            name=agent_config["name"],
            chat_client=chat_client,
            instructions=agent_config["instructions"]
        )
    
    logger.info(f"Created {len(agents)} agents")
    return agents


# ============================================================================
# Build Workflow as Agent
# ============================================================================

def build_cv_workflow_agent():
    """Build the state-based CV analysis workflow as an agent."""
    config = Config()
    agents = create_agents(config)
    
    workflow = (
        WorkflowBuilder()
        .register_executor(
            lambda: StateBasedWorkflowExecutor(
                analyzer_agent=agents["analyzer"],
                qna_agent=agents["qna"],
                validation_agent=agents["validation"],
                recommender_agent=agents["recommendation"],
            ),
            name="state-based-workflow"
        )
        .set_start_executor("state-based-workflow")
        .build()
        .as_agent()
    )
    
    logger.info("State-based CV workflow agent built successfully")
    return workflow


# ============================================================================
# For testing locally without hosting adapter
# ============================================================================

async def test_workflow():
    """Test the workflow locally."""
    from agent_framework import WorkflowAgent
    
    agent = build_cv_workflow_agent()
    
    print("\n" + "=" * 60)
    print(" State-Based CV Workflow - Local Test")
    print("=" * 60)
    print("\nWorkflow agent built successfully!")
    print("This version uses conversation history for state tracking.")
    print("Compatible with Teams, Foundry Playground, and all UIs.")
    print("\nTo deploy: azd deploy")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_workflow())
