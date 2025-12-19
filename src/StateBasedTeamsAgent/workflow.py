"""
CV Analysis Workflow - Brain-Based Pattern for Teams/Foundry Compatibility

Architecture:
Brain agent handles conversational collection of CV and job description.
State is persisted in-memory keyed by conversation_id.

Brain → (collects CV & Job) → Analyzer → Q&A → Recommendation
                                     ↘ (skip Q&A if score ≥ 80)

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
from agent_framework._workflows._events import AgentRunUpdateEvent
from agent_framework.azure import AzureOpenAIChatClient
from azure.identity import DefaultAzureCredential

from datetime import datetime, timezone
import uuid
import time

from config import Config
from agent_definitions import AgentDefinitions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# Conversation State Store (in-memory, keyed by conversation_id)
# ============================================================================

# Global store for conversation states
# Key: conversation_id, Value: ConversationState dataclass
_conversation_store: Dict[str, "ConversationState"] = {}


@dataclass
class ConversationState:
    """Tracks state for a single conversation."""
    state: str = "collecting"  # collecting, waiting_confirmation, analyzing, qna, complete
    cv_text: Optional[str] = None
    job_text: Optional[str] = None
    analysis_text: Optional[str] = None
    gaps: List[str] = field(default_factory=list)
    initial_gaps: List[str] = field(default_factory=list)  # Original gaps before Q&A
    score: int = 0
    qna_history: List[str] = field(default_factory=list)
    brain_thread: Any = None  # Thread for Brain agent memory
    qna_thread: Any = None    # Thread for Q&A agent memory
    validation_ready: bool = False  # Set by validation agent when all gaps addressed


def get_conversation_state(conv_id: str) -> ConversationState:
    """Get or create conversation state."""
    if conv_id not in _conversation_store:
        _conversation_store[conv_id] = ConversationState()
        logger.info(f"Created new conversation state for: {conv_id}")
    return _conversation_store[conv_id]


def get_conversation_id_from_context() -> str:
    """Get conversation_id from request_context (set by agentserver middleware).
    
    In Foundry Playground: conversation_id changes per message (unusable)
    In Teams: conversation_id SHOULD be stable per chat
    
    We track if we've seen this ID before to detect stability.
    When we detect Playground mode, we migrate data to global_session.
    """
    from azure.ai.agentserver.core.logger import request_context
    
    # request_context is a ContextVar - .get() returns the whole dict, not a specific key
    try:
        ctx_dict = request_context.get() or {}
        conv_id = ctx_dict.get("azure.ai.agentserver.conversation_id", "") or ""
        conv_id = str(conv_id) if conv_id else ""
    except (LookupError, TypeError, AttributeError):
        conv_id = ""
    
    if conv_id:
        # Track if this conversation_id has been seen before
        if not hasattr(get_conversation_id_from_context, '_seen_ids'):
            get_conversation_id_from_context._seen_ids = set()
            get_conversation_id_from_context._playground_mode = False
        
        # If we already detected Playground mode, always use global
        if get_conversation_id_from_context._playground_mode:
            logger.info(f"⚠️ Playground mode active, using global session")
            return "global_session"
        
        was_seen = conv_id in get_conversation_id_from_context._seen_ids
        get_conversation_id_from_context._seen_ids.add(conv_id)
        
        if was_seen:
            # This ID was seen before = client is reusing conversation (Teams behavior)
            logger.info(f"✅ Stable conversation_id detected: {conv_id[:20]}...")
            return conv_id
        else:
            # First time seeing this ID
            # Check if we have ONLY seen unique IDs (Playground behavior)
            if len(get_conversation_id_from_context._seen_ids) > 2:
                # We've seen 3+ different IDs = Playground, switch to global
                logger.info(f"⚠️ Unstable conversation_id (Playground mode), switching to global session")
                get_conversation_id_from_context._playground_mode = True
                
                # MIGRATE data from previous sessions to global_session
                _migrate_to_global_session()
                
                return "global_session"
            else:
                # Could be first message in Teams, give it a chance
                logger.info(f"🔄 New conversation_id: {conv_id[:20]}... (waiting to confirm stability)")
                return conv_id
    
    # No conversation_id at all
    logger.info("⚠️ No conversation_id in context, using global session")
    return "global_session"


def _migrate_to_global_session():
    """Migrate data from personal sessions to global_session when switching to Playground mode."""
    global _conversation_store
    
    # Find the session with the most data (CV and/or job stored)
    best_session = None
    best_score = 0
    
    for session_id, state in _conversation_store.items():
        if session_id == "global_session":
            continue
        score = 0
        if state.cv_text:
            score += 2
        if state.job_text:
            score += 2
        if state.analysis_text:
            score += 1
        if score > best_score:
            best_score = score
            best_session = state
    
    if best_session and best_score > 0:
        # Create or update global_session with migrated data
        if "global_session" not in _conversation_store:
            _conversation_store["global_session"] = ConversationState()
        
        global_state = _conversation_store["global_session"]
        
        # Migrate data (only if global doesn't have it)
        if not global_state.cv_text and best_session.cv_text:
            global_state.cv_text = best_session.cv_text
            logger.info(f"📦 Migrated CV ({len(best_session.cv_text)} chars) to global session")
        if not global_state.job_text and best_session.job_text:
            global_state.job_text = best_session.job_text
            logger.info(f"📦 Migrated job ({len(best_session.job_text)} chars) to global session")
        if not global_state.analysis_text and best_session.analysis_text:
            global_state.analysis_text = best_session.analysis_text
            global_state.gaps = best_session.gaps.copy()
            global_state.score = best_session.score
            logger.info(f"📦 Migrated analysis to global session")
        
        # Copy state if we have data
        if best_session.cv_text and best_session.job_text:
            global_state.state = best_session.state
            logger.info(f"📦 Migrated state '{best_session.state}' to global session")


# ============================================================================
# Helper to emit response to HTTP (not just inter-executor messaging)
# ============================================================================

MAX_TEAMS_MESSAGE_LENGTH = 2000  # Keep responses concise for Teams

# Track last emit time to prevent rapid-fire messages (causes 400 on Teams)
_last_emit_time: float = 0.0
_emit_count: int = 0  # Track how many emits per request

async def emit_response(ctx: WorkflowContext, text: str, executor_id: str = "brain-workflow") -> None:
    """Emit a text response that will appear in the HTTP response.
    
    Unlike ctx.send_message() which sends between executors,
    this emits an AgentRunUpdateEvent that the server converts to HTTP response.
    """
    global _last_emit_time, _emit_count
    import asyncio
    import traceback
    
    _emit_count += 1
    logger.info(f"📤 emit_response #{_emit_count}: {len(text)} chars, preview: {text[:80]}...")
    
    # Add delay if last emit was too recent (Teams Bot Framework can't handle rapid messages)
    time_since_last = time.time() - _last_emit_time
    if time_since_last < 0.5:  # Less than 500ms since last emit
        delay = 0.5 - time_since_last
        logger.info(f"⏳ Rate limiting: waiting {delay:.2f}s before emit")
        await asyncio.sleep(delay)
    
    # Truncate if too long for Teams
    original_len = len(text)
    if original_len > MAX_TEAMS_MESSAGE_LENGTH:
        text = text[:MAX_TEAMS_MESSAGE_LENGTH - 50] + "\n\n*(continued...)*"
        logger.warning(f"⚠️ Response truncated from {original_len} to {len(text)} chars")
    
    try:
        update = AgentRunResponseUpdate(
            contents=[TextContent(text=text)],
            role=Role.ASSISTANT,
            author_name=executor_id,
            response_id=str(uuid.uuid4()),
            message_id=str(uuid.uuid4()),
            created_at=datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        )
        await ctx.add_event(AgentRunUpdateEvent(executor_id=executor_id, data=update))
        logger.info(f"✅ emit_response #{_emit_count} sent successfully")
    except Exception as e:
        error_details = f"❌ **EMIT ERROR #{_emit_count}**\n\nType: `{type(e).__name__}`\nMessage: `{str(e)[:500]}`\n\nTraceback:\n```\n{traceback.format_exc()[:1000]}\n```"
        logger.error(f"❌ emit_response #{_emit_count} FAILED: {type(e).__name__}: {e}")
        
        # Try to send error details to user (if this also fails, we're stuck)
        try:
            error_update = AgentRunResponseUpdate(
                contents=[TextContent(text=error_details)],
                role=Role.ASSISTANT,
                author_name=executor_id,
                response_id=str(uuid.uuid4()),
                message_id=str(uuid.uuid4()),
                created_at=datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            )
            await ctx.add_event(AgentRunUpdateEvent(executor_id=executor_id, data=error_update))
        except:
            pass  # If even error reporting fails, just log it
        raise
    
    # Update last emit time
    _last_emit_time = time.time()


# ============================================================================
# Workflow States
# ============================================================================

class WorkflowState(Enum):
    """Possible states in the conversation workflow."""
    COLLECTING = "collecting"  # Brain is collecting CV and job
    ANALYZING = "analyzing"    # Running CV analysis
    QNA = "qna"                # Q&A conversation
    COMPLETE = "complete"       # Recommendation provided


# ============================================================================
# Message Types (kept for internal use)
# ============================================================================

@dataclass
class AnalysisResult:
    """Analysis result with routing decision."""
    analysis_json: str
    cv_text: str
    job_description: str
    needs_qna: bool
    score: int
    gaps: List[str] = field(default_factory=list)


# ============================================================================
# Helper Functions
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
                mandatory = ["Work authorization/location eligibility", "Role understanding and alignment with career goals", "Company/culture research and fit"]
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


async def check_validation_status(
    validation_agent: ChatAgent, 
    current_gaps: List[str], 
    conversation_history: List[str], 
    is_termination_attempt: bool = False
) -> tuple[bool, List[str]]:
    """Check validation status and return readiness and updated gaps."""
    
    logger.info(f"[VALIDATION] Called with {len(current_gaps)} gaps: {current_gaps}")
    logger.info(f"[VALIDATION] Conversation history length: {len(conversation_history)}")
    
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
    
    logger.info(f"[VALIDATION] Input to agent: {validation_input[:300]}...")
    
    try:
        validation_result = await validation_agent.run(validation_input)
        validation_response = validation_result.messages[-1].text
        logger.info(f"[VALIDATION] Full response: {validation_response}")
        
        validation_ready = "READY" in validation_response.upper()
        
        remaining_gaps = current_gaps.copy()
        removed_gaps = []
        
        if "REMOVE:" in validation_response:
            remove_section = validation_response.split("REMOVE:")[1].split("KEEP:")[0] if "KEEP:" in validation_response else validation_response.split("REMOVE:")[1].split("READINESS:")[0]
            remove_text = remove_section.strip().lower()
            logger.info(f"[VALIDATION] Remove section extracted: '{remove_text}'")
            
            for gap in current_gaps:
                gap_lower = gap.lower()
                # More flexible matching
                if gap_lower in remove_text or any(word in remove_text for word in gap_lower.split() if len(word) > 4):
                    remaining_gaps.remove(gap)
                    removed_gaps.append(gap)
                    logger.info(f"[VALIDATION]  Removed gap: {gap}")
        else:
            logger.info("[VALIDATION]  No REMOVE: section found in response")
        
        if removed_gaps:
            logger.info(f"[VALIDATION]  Total gaps addressed this turn: {', '.join(removed_gaps)}")
        logger.info(f"[VALIDATION]  Remaining gaps: {len(remaining_gaps)} - {remaining_gaps}")
        
        return validation_ready, remaining_gaps
    except Exception as e:
        logger.warning(f"[VALIDATION]  Check failed with error: {e}")
        return False, current_gaps


# ============================================================================
# Brain-Based Workflow Executor
# ============================================================================

class BrainBasedWorkflowExecutor(Executor):
    """
    Brain-based workflow executor that uses in-memory state persistence.
    
    The Brain agent handles natural conversation and collects CV/job.
    State is persisted per conversation_id so multi-turn works even when
    Playground/Teams only sends the latest message.
    
    Flow:
    1. COLLECTING: Brain has natural conversation, collects CV and job
       - Detects CV via [CV_RECEIVED] marker in Brain response
       - Detects job via [JOB_RECEIVED] marker in Brain response
    2. ANALYZING: Run CV analysis when both CV and job are collected
    3. QNA: Multi-turn Q&A with validation agent tracking gaps
    4. COMPLETE: Recommendation provided
    """
    
    def __init__(
        self,
        brain_agent: ChatAgent,
        analyzer_agent: ChatAgent,
        qna_agent: ChatAgent,
        validation_agent: ChatAgent,
        recommender_agent: ChatAgent,
    ):
        super().__init__(id="brain-workflow-executor")
        self._brain = brain_agent
        self._analyzer = analyzer_agent
        self._qna_agent = qna_agent
        self._validation_agent = validation_agent
        self._recommender = recommender_agent
    
    @handler
    async def handle_messages(self, messages: List[ChatMessage], ctx: WorkflowContext) -> None:
        """Main handler - routes based on persisted state."""
        
        # Get conversation_id for state persistence
        # DEBUG: Log ALL available context to find stable identifier
        try:
            from azure.ai.agentserver.core.logger import request_context
            ctx_data = request_context.get() or {}
            logger.info("=== ALL REQUEST CONTEXT KEYS ===")
            for key, value in ctx_data.items():
                logger.info(f"  {key}: {value}")
        except Exception as e:
            logger.warning(f"Could not inspect request_context: {e}")
        
        conversation_id = get_conversation_id_from_context()
        is_global_session = (conversation_id == "global_session")
        session_mode = " Global" if is_global_session else "🔒 Personal"
        logger.info(f"=== CONVERSATION ID: {conversation_id} ({session_mode}) ===")
        
        # Get persisted state for this conversation
        conv_state = get_conversation_state(conversation_id)
        logger.info(f"Current state: {conv_state.state}, CV: {conv_state.cv_text is not None}, Job: {conv_state.job_text is not None}")
        
        # Get the latest user input
        user_input = ""
        user_messages = [m for m in messages if m.role == Role.USER]
        if user_messages:
            user_input = extract_message_text(user_messages[-1])
        
        # Check for debug command - detailed info for troubleshooting
        if user_input.lower().strip() == 'debug':
            seen_ids = getattr(get_conversation_id_from_context, '_seen_ids', set())
            
            # Build context reminder based on state
            context_reminder = ""
            if conv_state.state == "waiting_confirmation":
                context_reminder = "\n\n **Ready to analyze!** Say 'yes' or 'analyze' to proceed."
            elif conv_state.state == "qna":
                context_reminder = "\n\n **In Q&A mode.** Answer questions or type 'done' for recommendation."
            elif conv_state.state == "collecting":
                if conv_state.cv_text and not conv_state.job_text:
                    context_reminder = "\n\n **Waiting for job description.**"
                elif not conv_state.cv_text:
                    context_reminder = "\n\n **Waiting for your CV.**"
            
            debug_msg = f"""🔧 **Debug Info**

**Session:**
- Mode: {session_mode}
- Conv ID: `{conversation_id}`
- Is global: {is_global_session}

**State:**
- Current: `{conv_state.state}`
- CV stored: {len(conv_state.cv_text) if conv_state.cv_text else 0} chars
- Job stored: {len(conv_state.job_text) if conv_state.job_text else 0} chars
- Score: {conv_state.score}
- Gaps: {len(conv_state.gaps)}
- Q&A history: {len(conv_state.qna_history)} turns

**Memory:**
- Total sessions: {len(_conversation_store)}
- Seen conv IDs: {len(seen_ids)}

**Diagnosis:**
{"✅ Plan A: Personal sessions via request_context" if not is_global_session else "⚠️ Plan B: Global fallback (single user)"}{context_reminder}"""
            await emit_response(ctx, debug_msg, self.id)
            return
        
        # Check for status command - tells user which mode
        if user_input.lower().strip() == 'status':
            status_msg = f"""**Session Status**
- Mode: {session_mode} session
- Conversation ID: `{conversation_id[:20]}...` 
- State: {conv_state.state}
- CV: {'✅ Received' if conv_state.cv_text else '❌ Not yet'}
- Job: {'✅ Received' if conv_state.job_text else '❌ Not yet'}

{"⚠️ Global mode = single user only (Playground)" if is_global_session else "✅ Personal mode = multi-user supported (Teams)"}"""
            await emit_response(ctx, status_msg, self.id)
            return
        
        # Check for reset command - allows user to start fresh
        if user_input.lower().strip() in ['reset', 'start over', 'new', 'restart', 'clear']:
            _conversation_store.pop(conversation_id, None)
            conv_state = get_conversation_state(conversation_id)
            await emit_response(
                ctx,
                f"🔄 **Session reset!** Let's start fresh.\n\n_({session_mode} session)_\n\nHey! 👋 Welcome to Application Buddy! I help you evaluate if a job is right for you. Share your CV and a job description, and I'll analyze your fit.\n\nWhat would you like to do?",
                self.id
            )
            return
        
        logger.info(f"User input ({len(user_input)} chars): {user_input[:100]}...")
        
        # Route based on state
        if conv_state.state == "collecting":
            await self._handle_collecting(ctx, conv_state, user_input, conversation_id)
        
        elif conv_state.state == "waiting_confirmation":
            await self._handle_confirmation(ctx, conv_state, user_input, conversation_id)
        
        elif conv_state.state == "analyzing":
            # This shouldn't normally be hit (analysis is triggered automatically)
            # but handle it just in case
            await self._run_analysis(ctx, conv_state, conversation_id)
        
        elif conv_state.state == "qna":
            await self._handle_qna(ctx, conv_state, user_input, conversation_id)
        
        elif conv_state.state == "complete":
            # Check if we need to generate recommendation first (validation_ready but not yet generated)
            if conv_state.validation_ready and conv_state.analysis_text and not hasattr(conv_state, '_recommendation_sent'):
                logger.info("[COMPLETE] Validation ready - generating recommendation now")
                conv_state._recommendation_sent = True
                qna_summary = "\n".join(conv_state.qna_history[-10:]) if conv_state.qna_history else "Q&A conversation completed."
                await self._generate_recommendation(ctx, conv_state, qna_summary)
            else:
                # After recommendation, allow user to try another job or update CV
                await self._handle_post_recommendation(ctx, conv_state, user_input, conversation_id)
    
    async def _handle_collecting(
        self, 
        ctx: WorkflowContext, 
        conv_state: ConversationState, 
        user_input: str,
        conversation_id: str
    ) -> None:
        """Brain handles conversation while collecting CV and job."""
        
        # Ensure we have a Brain thread for memory
        if conv_state.brain_thread is None:
            conv_state.brain_thread = self._brain.get_new_thread()
            logger.info("Created new Brain thread")
        
        # If no user input, send initial greeting
        if not user_input.strip():
            result = await self._brain.run("Hi", thread=conv_state.brain_thread)
            response = result.messages[-1].text
            await emit_response(ctx, response, self.id)
            return
        
        # Check if user is providing CV (before asking Brain)
        # If CV not yet received and this is a long message, prepend context for Brain
        brain_prompt = user_input
        if conv_state.cv_text is None and len(user_input) > 200:
            brain_prompt = f"[User is sharing what appears to be a CV/resume]\n\n{user_input}"
        elif conv_state.cv_text is not None and conv_state.job_text is None and len(user_input) > 150:
            brain_prompt = f"[User is sharing what appears to be a job description]\n\n{user_input}"
        
        # Get Brain's response
        result = await self._brain.run(brain_prompt, thread=conv_state.brain_thread)
        response = result.messages[-1].text
        
        # Check for state transition markers
        if "[CV_RECEIVED]" in response:
            conv_state.cv_text = user_input
            # Remove the marker from displayed response
            response = response.replace("[CV_RECEIVED]", "").strip()
            logger.info(f"CV received ({len(user_input)} chars)")
        
        if "[JOB_RECEIVED]" in response:
            conv_state.job_text = user_input
            # Remove the marker from displayed response  
            response = response.replace("[JOB_RECEIVED]", "").strip()
            logger.info(f"Job description received ({len(user_input)} chars)")
        
        # Check if ready to ask for confirmation
        if conv_state.cv_text is not None and conv_state.job_text is not None and conv_state.state == "collecting":
            # Both collected - wait for user confirmation before analysis
            conv_state.state = "waiting_confirmation"
            logger.info("Both CV and job collected - waiting for user confirmation")
        
        # Send Brain's response (which should ask "ready to analyze?")
        await emit_response(ctx, response, self.id)
    
    async def _handle_confirmation(
        self,
        ctx: WorkflowContext,
        conv_state: ConversationState,
        user_input: str,
        conversation_id: str
    ) -> None:
        """Handle user confirmation to start analysis - Brain decides based on user intent."""
        
        try:
            # Let the Brain agent decide if we should start analysis
            # Brain will output [START_ANALYSIS] if user wants to proceed
            logger.info(f"[CONFIRMATION] User said: {user_input[:100]}")
            result = await self._brain.run(user_input, thread=conv_state.brain_thread)
            response = result.messages[-1].text
            logger.info(f"[CONFIRMATION] Brain response: {response[:200]}...")
            
            # Check if Brain decided to trigger analysis
            if "[START_ANALYSIS]" in response:
                logger.info("[CONFIRMATION] Brain triggered [START_ANALYSIS]")
                
                # NOTE: Don't send "Starting analysis..." - only ONE emit_response per request
                # to avoid 400 Bad Request from Teams Bot Framework
                
                # Proceed to analysis (will emit its own response)
                conv_state.state = "analyzing"
                await self._run_analysis(ctx, conv_state, conversation_id)
            else:
                logger.info("[CONFIRMATION] Brain did NOT trigger analysis")
                # Brain decided not to start analysis - check for other markers
                if "[CV_RECEIVED]" in response:
                    conv_state.cv_text = user_input
                    response = response.replace("[CV_RECEIVED]", "").strip()
                    logger.info(f"New CV received ({len(user_input)} chars)")
                
                if "[JOB_RECEIVED]" in response:
                    conv_state.job_text = user_input
                    response = response.replace("[JOB_RECEIVED]", "").strip()
                    logger.info(f"New job description received ({len(user_input)} chars)")
                
                await emit_response(ctx, response, self.id)
        
        except Exception as e:
            logger.error(f"[CONFIRMATION] Error: {e}", exc_info=True)
            await emit_response(ctx, f"⚠️ Error during confirmation. Please type 'yes' to analyze or 'reset' to start over.\n\nError: {str(e)[:100]}", self.id)

    async def _run_analysis(
        self, 
        ctx: WorkflowContext, 
        conv_state: ConversationState,
        conversation_id: str
    ) -> None:
        """Run CV analysis and transition to Q&A or recommendation."""
        
        logger.info("[ANALYZER] Starting CV analysis...")
        
        try:
            # Run analyzer (NO message yet - we'll send ONE combined message at the end)
            analysis_prompt = f"""**CANDIDATE CV:**
{conv_state.cv_text}

**JOB DESCRIPTION:**
{conv_state.job_text}"""
            
            logger.info(f"[ANALYZER] Sending prompt ({len(analysis_prompt)} chars)")
            result = await self._analyzer.run(analysis_prompt)
            analysis_text = result.messages[-1].text
            conv_state.analysis_text = analysis_text
            logger.info(f"[ANALYZER] Got response ({len(analysis_text)} chars)")
            
            # Determine if Q&A is needed
            needs_qna, score, gaps = should_run_qna(analysis_text)
            conv_state.gaps = gaps
            conv_state.initial_gaps = gaps.copy()  # Save original gaps for recommendation
            conv_state.score = score
            
            logger.info(f"[ANALYZER] Score: {score}, Needs Q&A: {needs_qna}, Gaps: {len(gaps)}")
        
        except Exception as e:
            logger.error(f"[ANALYZER] Error during analysis: {e}", exc_info=True)
            await emit_response(ctx, f"⚠️ Analysis error. Please type 'reset' and try again.", self.id)
            conv_state.state = "collecting"
            return
        
        try:
            if needs_qna:
                # Transition to Q&A
                conv_state.state = "qna"
                conv_state.qna_thread = self._qna_agent.get_new_thread()
                conv_state.qna_history = []
                
                logger.info("[Q&A] Starting Q&A phase...")
                
                try:
                    # Q&A agent generates first question
                    qna_prompt = f"""ANALYSIS GAPS: {', '.join(gaps[:5])}

Start a friendly conversation to learn more about the candidate's relevant experience. Ask about ONE gap area."""
                    
                    qna_result = await self._qna_agent.run(qna_prompt, thread=conv_state.qna_thread)
                    first_question = qna_result.messages[-1].text
                    conv_state.qna_history.append(f"Advisor: {first_question}")
                    
                    # ONE COMBINED MESSAGE - avoids 400 error from multiple emit_response calls
                    combined_response = (
                        f" **Analysis Complete!** Score: **{score}%** | Areas to explore: **{len(gaps)}**\n\n"
                        f"---\n\n"
                        f" **[Q&A Agent]** {first_question}\n\n"
                        f"*(Type 'done' anytime for your recommendation)*"
                    )
                    await emit_response(ctx, combined_response, self.id)
                    
                except Exception as e:
                    logger.error(f"[Q&A] Error starting Q&A: {e}", exc_info=True)
                    # Fall back to recommendation if Q&A fails
                    conv_state.state = "complete"
                    await self._generate_recommendation(ctx, conv_state, "")
            
            else:
                # High score - skip Q&A, go straight to recommendation
                logger.info("High score - skipping Q&A, generating recommendation...")
                conv_state.state = "complete"
                # NOTE: Don't emit here - let _generate_recommendation be the only response
                await self._generate_recommendation(ctx, conv_state, "")
                
        except Exception as e:
            logger.error(f"Error during analysis: {e}")
            await emit_response(ctx, f"⚠️ Error during analysis. Type 'reset' to try again.", self.id)
            conv_state.state = "collecting"
    
    async def _handle_qna(
        self,
        ctx: WorkflowContext,
        conv_state: ConversationState,
        user_input: str,
        conversation_id: str
    ) -> None:
        """Handle Q&A conversation turn. Q&A just converses - validation tracks gaps."""
        
        # Check for done command - IMMEDIATE exit to recommendation
        user_lower = user_input.lower().strip()
        if user_lower == 'done':
            logger.info("User typed 'done' - immediate exit to recommendation")
            conv_state.state = "complete"
            
            # NOTE: Don't emit here - let _generate_recommendation be the only response
            
            qna_summary = "\n".join(conv_state.qna_history[-8:]) if conv_state.qna_history else "Brief Q&A conversation."
            await self._generate_recommendation(ctx, conv_state, qna_summary)
            return
        
        # Regular Q&A turn - just have conversation
        conv_state.qna_history.append(f"User: {user_input}")
        
        if conv_state.qna_thread is None:
            conv_state.qna_thread = self._qna_agent.get_new_thread()
        
        # Steer toward a gap every 4 exchanges to ensure coverage
        user_exchanges = len([h for h in conv_state.qna_history if h.startswith("User:")])
        should_target_gap = (user_exchanges > 0 and user_exchanges % 4 == 0 and conv_state.gaps)
        
        if should_target_gap:
            target_gap = conv_state.gaps[0]
            qna_prompt = f"""The user just responded: "{user_input}"

Acknowledge their response briefly, then naturally steer to explore: {target_gap}

Don't mention 'gaps' - just ask about related experiences. Be conversational and brief."""
            logger.info(f"[Q&A] Steering toward gap: {target_gap}")
        else:
            qna_prompt = f"User response: {user_input}"
        
        # Get Q&A response
        logger.info("[Q&A AGENT] Generating response...")
        result = await self._qna_agent.run(qna_prompt, thread=conv_state.qna_thread)
        response = result.messages[-1].text
        conv_state.qna_history.append(f"Advisor: {response}")
        
        # Run validation BEFORE emitting so we can append wrap-up question if done
        logger.info("[VALIDATION] Checking status...")
        validation_ready, updated_gaps = await check_validation_status(
            self._validation_agent,
            conv_state.gaps,
            conv_state.qna_history
        )
        conv_state.gaps = updated_gaps
        conv_state.validation_ready = validation_ready
        logger.info(f"[VALIDATION] Ready: {validation_ready}, Remaining gaps: {len(updated_gaps)}")
        
        # Build the response message
        if validation_ready or len(updated_gaps) == 0:
            # All gaps addressed - ask if there's anything else before generating recommendation
            logger.info("[Q&A] All gaps addressed - asking user if anything else")
            response_msg = (
                f"**[Q&A Agent]** {response}\n\n"
                "---\n\n"
                "✅ **Great progress!** I think we've covered all the key areas.\n\n"
                "**Is there anything else you'd like to discuss** about this role or your background "
                "before I give you my recommendation?\n\n"
                "*(Reply with your question, or type 'done' for my recommendation)*"
            )
            # Don't auto-complete yet - wait for user to confirm with 'done' or ask more
            # This gives them a chance to add anything else
        else:
            # Still have gaps to explore - normal Q&A flow
            response_msg = f"**[Q&A Agent]** {response}\n\n*(Type 'done' anytime for your recommendation)*"
        
        await emit_response(ctx, response_msg, self.id)
    
    async def _get_qna_summary(self, conv_state: ConversationState) -> str:
        """Get final summary from Q&A agent."""
        if conv_state.qna_thread is None:
            logger.info("[Q&A SUMMARY] No thread, skipping summary")
            return "No Q&A conversation occurred."
        
        logger.info("[Q&A SUMMARY] Requesting summary from Q&A agent...")
        summary_prompt = "Please provide your final assessment based on our conversation."
        result = await self._qna_agent.run(summary_prompt, thread=conv_state.qna_thread)
        logger.info("[Q&A SUMMARY] Summary received")
        return result.messages[-1].text
    
    async def _generate_recommendation(
        self,
        ctx: WorkflowContext,
        conv_state: ConversationState,
        qna_insights: str
    ) -> None:
        """Generate final recommendation and send as multiple messages."""
        
        logger.info("[RECOMMENDER] Generating final recommendation...")
        
        # Build gap coverage summary - all gaps should be addressed by validation agent
        initial_gaps = conv_state.initial_gaps if conv_state.initial_gaps else []
        
        gap_summary = f"""**INITIAL GAPS IDENTIFIED ({len(initial_gaps)}):**
{chr(10).join(f'- {g}' for g in initial_gaps) if initial_gaps else 'None identified'}

All gaps were explored during the Q&A conversation. The validation agent confirmed each area was addressed."""
        
        recommendation_prompt = f"""**CV:**
{conv_state.cv_text}

**JOB DESCRIPTION:**
{conv_state.job_text}

**ANALYSIS:**
{conv_state.analysis_text}

{gap_summary}

**Q&A CONVERSATION (how gaps were addressed):**
{qna_insights if qna_insights else "No Q&A conversation - high initial match score."}

Please provide your recommendation. Include a section titled "Gaps Explored During Q&A" that lists each initial gap and summarizes what was learned about the candidate's experience in that area."""
        
        result = await self._recommender.run(recommendation_prompt)
        recommendation = result.messages[-1].text
        
        # Send as ONE message to avoid 400 Bad Request on Teams
        # Multiple rapid emit_response calls cause Bot Framework to reject the request
        follow_up = (
            "---\n\n"
            "🔄 **What's next?**\n\n"
            "• Try a **new job description** (just paste it)\n"
            "• Update your **CV** and try again\n"
            "• Type **'reset'** to start completely fresh"
        )
        
        combined = f"**[Recommendation Agent]** Here's my assessment:\n\n{recommendation}\n\n{follow_up}"
        
        # Truncate if too long for Teams (4000 char limit for single message)
        if len(combined) > 3900:
            combined = combined[:3850] + "\n\n*(message truncated)*"
        
        await emit_response(ctx, combined, self.id)
    
    def _split_recommendation_into_sections(self, recommendation: str) -> list:
        """Split recommendation text into logical sections for separate messages."""
        import re
        
        # Split by markdown headers (## or **Section:**)
        # Pattern matches ## Header or **Header** at start of line
        pattern = r'(?=^##\s|\*\*[A-Z])'
        sections = re.split(pattern, recommendation, flags=re.MULTILINE)
        
        # If no sections found, split by double newlines
        if len(sections) <= 1:
            sections = recommendation.split('\n\n')
        
        # Group small sections together (under 300 chars)
        result = []
        current = ""
        for section in sections:
            if len(current) + len(section) < 1500:  # Keep under limit
                current += section
            else:
                if current.strip():
                    result.append(current)
                current = section
        if current.strip():
            result.append(current)
        
        return result if result else [recommendation]
    
    async def _handle_post_recommendation(
        self,
        ctx: WorkflowContext,
        conv_state: ConversationState,
        user_input: str,
        conversation_id: str
    ) -> None:
        """Handle user input after recommendation - route through Brain for natural conversation."""
        
        user_lower = user_input.lower().strip()
        
        # Check if user wants to analyze with existing CV (they just provided a new job)
        analyze_phrases = ['use my old cv', 'use my cv', 'use previous cv', 'use my previous', 
                          'yes analyze', 'yes please', 'go ahead', 'analyze', 'analyse',
                          'yes', 'do it', 'proceed', 'continue', 'ready']
        
        if any(phrase in user_lower for phrase in analyze_phrases):
            # User wants to analyze - check if we have CV and job
            if conv_state.cv_text and conv_state.job_text:
                logger.info("User confirmed analysis with existing CV - running pipeline")
                # Clear previous analysis state but keep CV and job
                conv_state.analysis_text = None
                conv_state.gaps = []
                conv_state.qna_history = []
                conv_state.qna_thread = None
                conv_state.state = "analyzing"
                await self._run_analysis(ctx, conv_state, conversation_id)
                return
            elif conv_state.cv_text and not conv_state.job_text:
                await emit_response(ctx, "I have your CV! Please paste the job description you'd like me to analyze.", self.id)
                conv_state.state = "collecting"
                return
            else:
                await emit_response(ctx, "I don't have your CV saved. Please paste your CV first.", self.id)
                conv_state.state = "collecting"
                return
        
        # Prepare context for Brain about current state
        context_prefix = "[POST_RECOMMENDATION] User has received their recommendation. "
        
        # Check if this looks like a new CV
        if len(user_input) > 500 and any(word in user_input.lower() for word in ['experience', 'education', 'skills', 'worked at', 'degree']):
            context_prefix += "User appears to be sharing a new/updated CV.\n\n"
            
        # Check if this looks like a new job description
        elif len(user_input) > 150 and any(word in user_input.lower() for word in ['requirements', 'responsibilities', 'qualifications', 'we are looking', 'you will']):
            context_prefix += "User appears to be sharing a new job description. DO NOT analyze it yourself - just acknowledge receipt and use the [JOB_RECEIVED] marker.\n\n"
        
        # Send to Brain with context
        brain_prompt = context_prefix + user_input
        result = await self._brain.run(brain_prompt, thread=conv_state.brain_thread)
        response = result.messages[-1].text
        
        # Check for markers indicating new documents
        if "[CV_RECEIVED]" in response:
            # User provided new CV - reset for new analysis
            conv_state.cv_text = user_input
            conv_state.job_text = None
            conv_state.analysis_text = None
            conv_state.gaps = []
            conv_state.qna_history = []
            conv_state.qna_thread = None
            conv_state.state = "collecting"
            logger.info(f"New CV received post-recommendation ({len(user_input)} chars)")
            response = response.replace("[CV_RECEIVED]", "").strip()
            
        elif "[JOB_RECEIVED]" in response:
            # User provided new job - keep CV, go to confirmation
            conv_state.job_text = user_input
            conv_state.analysis_text = None
            conv_state.gaps = []
            conv_state.qna_history = []
            conv_state.qna_thread = None
            conv_state.state = "waiting_confirmation"
            logger.info(f"New job description received post-recommendation ({len(user_input)} chars)")
            response = response.replace("[JOB_RECEIVED]", "").strip()
        
        await emit_response(ctx, response, self.id)


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
    
    logger.info(f"Created {len(agents)} agents: {list(agents.keys())}")
    return agents


# ============================================================================
# Build Workflow as Agent
# ============================================================================

def build_cv_workflow_agent():
    """Build the Brain-based CV analysis workflow as an agent."""
    config = Config()
    agents = create_agents(config)
    
    workflow = (
        WorkflowBuilder()
        .register_executor(
            lambda: BrainBasedWorkflowExecutor(
                brain_agent=agents["brain"],
                analyzer_agent=agents["analyzer"],
                qna_agent=agents["qna"],
                validation_agent=agents["validation"],
                recommender_agent=agents["recommendation"],
            ),
            name="brain-workflow"
        )
        .set_start_executor("brain-workflow")
        .build()
        .as_agent()
    )
    
    logger.info("Brain-based CV workflow agent built successfully")
    return workflow


# ============================================================================
# For testing locally without hosting adapter
# ============================================================================

async def test_workflow():
    """Test the workflow locally."""
    agent = build_cv_workflow_agent()
    
    print("\n" + "=" * 60)
    print(" Brain-Based CV Workflow - Local Test")
    print("=" * 60)
    print("\nWorkflow agent built successfully!")
    print("This version uses Brain agent for natural conversation")
    print("and in-memory state persistence per conversation_id.")
    print("\nCompatible with: Teams, Foundry Playground, and all UIs.")
    print("\nTo deploy: azd deploy")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_workflow())
