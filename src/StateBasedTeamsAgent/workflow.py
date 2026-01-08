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
import os
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
# User Profile Store (tracks application history across sessions)
# ============================================================================

@dataclass
class ApplicationRecord:
    """Single job application record."""
    date: str
    job_title: str
    company: str
    industry: str  # Could be LLM-extracted in future
    score: int
    must_have_gaps: List[str]
    nice_to_have_gaps: List[str]
    recommendation: str  # "apply", "apply_with_prep", "consider_alternatives"


@dataclass 
class UserProfile:
    """Persistent user profile across sessions."""
    applications: List[ApplicationRecord] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


# In-memory profile cache (loaded from blob on first access)
_profile_store: Dict[str, UserProfile] = {}


def _get_blob_container():
    """Get Azure Blob container client for profile storage."""
    import os
    storage_account = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
    if not storage_account:
        logger.info("[PROFILE] No AZURE_STORAGE_ACCOUNT_NAME configured")
        return None
    
    try:
        from azure.storage.blob import BlobServiceClient
        from azure.identity import DefaultAzureCredential
        
        blob_service = BlobServiceClient(
            account_url=f"https://{storage_account}.blob.core.windows.net",
            credential=DefaultAzureCredential()
        )
        container = blob_service.get_container_client("user-profiles")
        
        # Create container if not exists
        try:
            container.create_container()
            logger.info("[PROFILE] Created user-profiles container")
        except Exception:
            pass  # Already exists
        
        return container
    except Exception as e:
        logger.warning(f"[PROFILE] Blob client init failed: {e}")
        return None


def get_user_profile(user_id: str) -> UserProfile:
    """Get or create user profile (loads from blob if not in memory)."""
    if user_id in _profile_store:
        return _profile_store[user_id]
    
    # Try loading from blob
    container = _get_blob_container()
    if container:
        try:
            blob = container.get_blob_client(f"{user_id}.json")
            data = json.loads(blob.download_blob().readall())
            profile = UserProfile(
                applications=[ApplicationRecord(**app) for app in data.get("applications", [])],
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", "")
            )
            _profile_store[user_id] = profile
            logger.info(f"[PROFILE] Loaded profile for {user_id}: {len(profile.applications)} applications")
            return profile
        except Exception as e:
            logger.info(f"[PROFILE] No existing profile for {user_id}: {type(e).__name__}")
    
    # Create new profile
    profile = UserProfile(created_at=datetime.now(tz=timezone.utc).isoformat())
    _profile_store[user_id] = profile
    return profile


def save_user_profile(user_id: str, profile: UserProfile) -> bool:
    """Save profile to blob storage."""
    profile.updated_at = datetime.now(tz=timezone.utc).isoformat()
    _profile_store[user_id] = profile
    
    container = _get_blob_container()
    if container:
        try:
            blob = container.get_blob_client(f"{user_id}.json")
            data = {
                "applications": [
                    {
                        "date": app.date,
                        "job_title": app.job_title,
                        "company": app.company,
                        "industry": app.industry,
                        "score": app.score,
                        "must_have_gaps": app.must_have_gaps,
                        "nice_to_have_gaps": app.nice_to_have_gaps,
                        "recommendation": app.recommendation,
                    }
                    for app in profile.applications
                ],
                "created_at": profile.created_at,
                "updated_at": profile.updated_at
            }
            blob.upload_blob(json.dumps(data, indent=2), overwrite=True)
            logger.info(f"[PROFILE] Saved profile for {user_id}: {len(profile.applications)} applications")
            return True
        except Exception as e:
            logger.warning(f"[PROFILE] Save failed: {e}")
    return False

def delete_user_profile(user_id: str) -> bool:
    """Delete user profile from memory and blob storage."""
    # Remove from memory
    if user_id in _profile_store:
        del _profile_store[user_id]
        logger.info(f"[PROFILE] Removed {user_id} from memory cache")
    
    # Remove from blob storage
    container = _get_blob_container()
    if container:
        try:
            blob = container.get_blob_client(f"{user_id}.json")
            blob.delete_blob()
            logger.info(f"[PROFILE] Deleted profile blob for {user_id}")
            return True
        except Exception as e:
            logger.info(f"[PROFILE] No blob to delete for {user_id}: {e}")
    return False

# ============================================================================
# Conversation State Store (in-memory, keyed by conversation_id)
# ============================================================================

# Global store for conversation states
# Key: conversation_id, Value: ConversationState dataclass
_conversation_store: Dict[str, "ConversationState"] = {}


@dataclass
class ConversationState:
    """Tracks state for a single conversation."""
    state: str = "collecting"  # collecting, waiting_confirmation, analyzing, qna, viewing_recommendation, complete
    cv_text: Optional[str] = None
    job_text: Optional[str] = None
    analysis_text: Optional[str] = None
    gaps: List[str] = field(default_factory=list)  # Remaining gaps (shrinks as addressed)
    initial_gaps: List[str] = field(default_factory=list)  # Original gaps before Q&A
    addressed_gaps: List[str] = field(default_factory=list)  # Gaps that were addressed in Q&A
    score: int = 0
    qna_history: List[str] = field(default_factory=list)
    brain_thread: Any = None  # Thread for Brain agent memory
    qna_thread: Any = None    # Thread for Q&A agent memory
    validation_ready: bool = False  # Set by validation agent when all gaps addressed
    recommendation_sections: List[str] = field(default_factory=list)  # Sections for menu-based browsing


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
            logger.info(f" Playground mode active, using global session")
            return "global_session"
        
        was_seen = conv_id in get_conversation_id_from_context._seen_ids
        get_conversation_id_from_context._seen_ids.add(conv_id)
        
        if was_seen:
            # This ID was seen before = client is reusing conversation (Teams behavior)
            logger.info(f" Stable conversation_id detected: {conv_id[:20]}...")
            return conv_id
        else:
            # First time seeing this ID
            # Check if we have ONLY seen unique IDs (Playground behavior)
            if len(get_conversation_id_from_context._seen_ids) > 2:
                # We've seen 3+ different IDs = Playground, switch to global
                logger.info(f" Unstable conversation_id (Playground mode), switching to global session")
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
            logger.info(f" Migrated CV ({len(best_session.cv_text)} chars) to global session")
        if not global_state.job_text and best_session.job_text:
            global_state.job_text = best_session.job_text
            logger.info(f" Migrated job ({len(best_session.job_text)} chars) to global session")
        if not global_state.analysis_text and best_session.analysis_text:
            global_state.analysis_text = best_session.analysis_text
            global_state.gaps = best_session.gaps.copy()
            global_state.score = best_session.score
            logger.info(f" Migrated analysis to global session")
        
        # Copy state if we have data
        if best_session.cv_text and best_session.job_text:
            global_state.state = best_session.state
            logger.info(f" Migrated state '{best_session.state}' to global session")


# ============================================================================
# Helper to emit response to HTTP (not just inter-executor messaging)
# ============================================================================

MAX_MESSAGE_LENGTH = 16000  # Increased for Streamlit/Playground (Teams has its own limits)

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
        logger.info(f" Rate limiting: waiting {delay:.2f}s before emit")
        await asyncio.sleep(delay)
    
    # Only truncate extremely long responses (safety limit)
    original_len = len(text)
    if original_len > MAX_MESSAGE_LENGTH:
        text = text[:MAX_MESSAGE_LENGTH - 50] + "\n\n*(truncated due to length)*"
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
        error_details = f" **EMIT ERROR #{_emit_count}**\n\nType: `{type(e).__name__}`\nMessage: `{str(e)[:500]}`\n\nTraceback:\n```\n{traceback.format_exc()[:1000]}\n```"
        logger.error(f" emit_response #{_emit_count} FAILED: {type(e).__name__}: {e}")
        
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
                matched_skills = analysis_data.get('matched_skills', [])
                
                # Get score from JSON, or calculate fallback if missing
                score = analysis_data.get('preliminary_score', 0)
                if score == 0 and (matched_skills or raw_gaps):
                    # Fallback: calculate score from matched vs gaps
                    must_matched = len([s for s in matched_skills if s.get('requirement_type') == 'must'])
                    nice_matched = len([s for s in matched_skills if s.get('requirement_type') == 'nice'])
                    must_gaps = len([g for g in raw_gaps if g.get('requirement_type') == 'must'])
                    nice_gaps = len([g for g in raw_gaps if g.get('requirement_type') == 'nice'])
                    
                    total_must = must_matched + must_gaps
                    total_nice = nice_matched + nice_gaps
                    
                    must_ratio = must_matched / max(total_must, 1)
                    nice_ratio = nice_matched / max(total_nice, 1)
                    score = round(100 * (0.7 * must_ratio + 0.3 * nice_ratio))
                    logger.info(f"[SCORE] Calculated fallback score: {score} (must: {must_matched}/{total_must}, nice: {nice_matched}/{total_nice})")
                
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


async def extract_pdf_from_messages(messages: List[ChatMessage], user_input: str = "") -> Optional[bytes]:
    """
    Extract PDF attachment from messages if present.
    
    Supports:
    1. Teams/Foundry URL-based attachments (downloaded via HTTP)
    2. Streamlit base64-encoded format: [PDF_ATTACHMENT:filename:base64data]
    
    Returns PDF bytes if found, None otherwise.
    """
    import aiohttp
    import base64
    import re
    
    # First check for base64-encoded PDF in user input (from Streamlit)
    if user_input:
        match = re.search(r'\[PDF_ATTACHMENT:([^:]+):([A-Za-z0-9+/=]+)\]', user_input)
        if match:
            filename = match.group(1)
            b64_data = match.group(2)
            try:
                pdf_bytes = base64.b64decode(b64_data)
                logger.info(f"[PDF] Decoded base64 PDF '{filename}': {len(pdf_bytes)} bytes")
                return pdf_bytes
            except Exception as e:
                logger.error(f"[PDF] Base64 decode error: {e}")
    
    # Then check message content for URL-based attachments (Teams format)
    for msg in messages:
        if not hasattr(msg, 'content') or not msg.content:
            continue
            
        for content in msg.content:
            # Check for file content type
            content_type = getattr(content, 'type', None) or getattr(content, 'content_type', '')
            
            # Check if it's a PDF
            if 'pdf' in str(content_type).lower():
                url = getattr(content, 'url', None) or getattr(content, 'content_url', None)
                if url:
                    logger.info(f"[PDF] Found PDF attachment: {url[:80]}...")
                    try:
                        async with aiohttp.ClientSession() as session:
                            async with session.get(url) as response:
                                if response.status == 200:
                                    data = await response.read()
                                    logger.info(f"[PDF] Downloaded {len(data)} bytes")
                                    return data
                                else:
                                    logger.error(f"[PDF] Download failed: HTTP {response.status}")
                    except Exception as e:
                        logger.error(f"[PDF] Download error: {e}")
            
            # Also check attachments list (alternative format)
            attachments = getattr(content, 'attachments', []) or []
            for att in attachments:
                att_type = getattr(att, 'content_type', '') or getattr(att, 'type', '')
                if 'pdf' in str(att_type).lower():
                    url = getattr(att, 'content_url', None) or getattr(att, 'url', None)
                    if url:
                        logger.info(f"[PDF] Found PDF in attachments list: {url[:80]}...")
                        try:
                            async with aiohttp.ClientSession() as session:
                                async with session.get(url) as response:
                                    if response.status == 200:
                                        data = await response.read()
                                        logger.info(f"[PDF] Downloaded {len(data)} bytes")
                                        return data
                        except Exception as e:
                            logger.error(f"[PDF] Download error: {e}")
    
    return None


async def check_validation_status(
    validation_agent: ChatAgent, 
    current_gaps: List[str], 
    conversation_history: List[str], 
    is_termination_attempt: bool = False
) -> tuple[bool, List[str]]:
    """Check validation status using intent-based LLM analysis."""
    
    logger.info(f"[VALIDATION] Called with {len(current_gaps)} gaps: {current_gaps}")
    logger.info(f"[VALIDATION] Conversation history length: {len(conversation_history)}")
    
    recent_conversation = "\n".join(conversation_history[-6:])  # More context for better judgment
    
    validation_input = f"""Gaps being tracked:
{chr(10).join(f'- {gap}' for gap in current_gaps)}

Recent conversation:
{recent_conversation}

{"User wants to end conversation. Provide final assessment." if is_termination_attempt else "Analyze which gaps were meaningfully discussed."}"""
    
    logger.info(f"[VALIDATION] Input to agent: {validation_input[:300]}...")
    
    try:
        validation_result = await validation_agent.run(validation_input)
        validation_response = validation_result.messages[-1].text
        logger.info(f"[VALIDATION] Full response: {validation_response}")
        
        # Parse JSON response
        import json
        import re
        
        # Extract JSON from response (might be wrapped in ```json blocks)
        json_match = re.search(r'\{[^{}]*"addressed"[^{}]*\}', validation_response, re.DOTALL)
        
        if json_match:
            try:
                result = json.loads(json_match.group())
                addressed = result.get("addressed", [])
                validation_ready = result.get("ready", False)
                reasoning = result.get("reasoning", "")
                
                # Remove addressed gaps (case-insensitive matching)
                remaining_gaps = current_gaps.copy()
                removed_gaps = []
                
                for gap in current_gaps:
                    gap_lower = gap.lower()
                    # Check if this gap appears in addressed list
                    for addr in addressed:
                        if gap_lower in addr.lower() or addr.lower() in gap_lower:
                            if gap in remaining_gaps:
                                remaining_gaps.remove(gap)
                                removed_gaps.append(gap)
                                break
                
                if removed_gaps:
                    logger.info(f"[VALIDATION] Gaps addressed this turn: {', '.join(removed_gaps)}")
                logger.info(f"[VALIDATION] Remaining gaps: {len(remaining_gaps)} - {remaining_gaps}")
                logger.info(f"[VALIDATION] Ready: {validation_ready}, Reasoning: {reasoning}")
                
                return validation_ready, remaining_gaps
                
            except json.JSONDecodeError as e:
                logger.warning(f"[VALIDATION] JSON parse failed: {e}")
        
        # Fallback: look for READY in response
        validation_ready = "READY" in validation_response.upper() and "NOT READY" not in validation_response.upper()
        logger.info(f"[VALIDATION] Fallback parsing - Ready: {validation_ready}")
        return validation_ready, current_gaps
        
    except Exception as e:
        logger.warning(f"[VALIDATION] Check failed with error: {e}")
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
        import traceback
        
        # Top-level error wrapper - catches ALL errors and shows them in chat
        try:
            await self._handle_messages_inner(messages, ctx)
        except Exception as e:
            error_msg = (
                f" **WORKFLOW ERROR**\n\n"
                f"**Type:** `{type(e).__name__}`\n"
                f"**Message:** `{str(e)[:500]}`\n\n"
                f"**Traceback:**\n```\n{traceback.format_exc()[:1500]}\n```\n\n"
                f"_Type 'reset' to start over_"
            )
            logger.error(f" Top-level error: {type(e).__name__}: {e}")
            logger.error(traceback.format_exc())
            
            try:
                await emit_response(ctx, error_msg, self.id)
            except:
                # If even error reporting fails, try direct emit
                try:
                    error_update = AgentRunResponseUpdate(
                        contents=[TextContent(text=error_msg[:2000])],
                        role=Role.ASSISTANT,
                        author_name=self.id,
                        response_id=str(uuid.uuid4()),
                        message_id=str(uuid.uuid4()),
                        created_at=datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                    )
                    await ctx.add_event(AgentRunUpdateEvent(executor_id=self.id, data=error_update))
                except:
                    pass  # Truly stuck
    
    async def _handle_messages_inner(self, messages: List[ChatMessage], ctx: WorkflowContext) -> None:
        """Inner handler - all the actual logic."""
        
        # Get conversation_id for state persistence
        conversation_id = get_conversation_id_from_context()
        is_global_session = (conversation_id == "global_session")
        session_mode = "🌍 Global" if is_global_session else "🔒 Personal"
        logger.info(f"Conversation: {conversation_id[:20]}... ({session_mode})")
        
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
- Gaps: {len(conv_state.gaps)}
- Q&A history: {len(conv_state.qna_history)} turns

**Memory:**
- Total sessions: {len(_conversation_store)}
- Seen conv IDs: {len(seen_ids)}

**Diagnosis:**
{" Personal session via request_context" if not is_global_session else "⚠️ Global fallback (single user)"}{context_reminder}"""
            await emit_response(ctx, debug_msg, self.id)
            return
        
        # Check for status command - tells user which mode
        if user_input.lower().strip() == 'status':
            status_msg = f"""**Session Status**
- Mode: {session_mode} session
- Conversation ID: `{conversation_id[:20]}...` 
- State: {conv_state.state}
- CV: {' Received' if conv_state.cv_text else '❌ Not yet'}
- Job: {' Received' if conv_state.job_text else '❌ Not yet'}

{" Personal mode = multi-user supported" if not is_global_session else "⚠️ Global mode = single user only"}"""
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
        
        # Check for reset profile command - clears application history
        if user_input.lower().strip() in ['reset profile', 'clear profile', 'delete profile']:
            delete_user_profile(conversation_id)
            await emit_response(
                ctx,
                "🗑️ **Profile cleared!** Your application history has been deleted.\n\n"
                "Your current conversation is still active. Type **'reset'** if you also want to start a new conversation.",
                self.id
            )
            return
        
        logger.info(f"User input ({len(user_input)} chars): {user_input[:100]}...")
        
        # Route based on state
        if conv_state.state == "collecting":
            await self._handle_collecting(ctx, conv_state, user_input, conversation_id, messages)
        
        elif conv_state.state == "waiting_confirmation":
            await self._handle_confirmation(ctx, conv_state, user_input, conversation_id)
        
        elif conv_state.state == "analyzing":
            # This shouldn't normally be hit (analysis is triggered automatically)
            # but handle it just in case
            await self._run_analysis(ctx, conv_state, conversation_id)
        
        elif conv_state.state == "qna":
            await self._handle_qna(ctx, conv_state, user_input, conversation_id)
        
        elif conv_state.state == "viewing_recommendation":
            await self._handle_viewing_recommendation(ctx, conv_state, user_input, conversation_id)
        
        elif conv_state.state == "complete":
            # After recommendation, allow user to try another job or update CV
            await self._handle_post_recommendation(ctx, conv_state, user_input, conversation_id)
    
    async def _handle_collecting(
        self, 
        ctx: WorkflowContext, 
        conv_state: ConversationState, 
        user_input: str,
        conversation_id: str,
        messages: List[ChatMessage] = None
    ) -> None:
        """Brain handles conversation while collecting CV and job."""
        
        # Ensure we have a Brain thread for memory
        if conv_state.brain_thread is None:
            conv_state.brain_thread = self._brain.get_new_thread()
            logger.info("Created new Brain thread")
        
        # Check for PDF attachment (CV upload) before processing text
        if conv_state.cv_text is None:
            try:
                # Pass user_input to extract base64-encoded PDFs from Streamlit
                pdf_bytes = await extract_pdf_from_messages(messages or [], user_input)
                
                if pdf_bytes:
                    logger.info("[PDF] Processing PDF CV attachment...")
                    await emit_response(ctx, " **Got your CV!** Processing the PDF and removing personal contact info for privacy...", self.id)
                    
                    # Process PDF: extract text + remove PII
                    from document_processor import get_document_processor
                    config = Config()
                    
                    # Check if document processor is configured
                    if not config.doc_intelligence_endpoint or not config.language_endpoint:
                        await emit_response(
                            ctx,
                            " PDF processing isn't configured yet. Please **copy-paste your CV text** instead.\n\n"
                            "_(Admin: Set DOC_INTELLIGENCE_ENDPOINT/KEY and LANGUAGE_ENDPOINT/KEY in .env)_",
                            self.id
                        )
                        return
                    
                    processor = get_document_processor(config)
                    extracted_cv = await processor.process_cv_pdf(pdf_bytes)
                    
                    if extracted_cv and len(extracted_cv.strip()) > 100:
                        conv_state.cv_text = extracted_cv
                        logger.info(f"[PDF] CV extracted and cleaned: {len(extracted_cv)} chars")
                        
                        # Ask for job description
                        await emit_response(
                            ctx, 
                            f" **CV received!** Extracted {len(extracted_cv):,} characters.\n\n"
                            "Personal contact details (phone, email, address) have been removed for privacy - your name and professional info are kept.\n\n"
                            "Now, please share the **job description** you'd like me to analyze against your CV.",
                            self.id
                        )
                        return
                    else:
                        await emit_response(
                            ctx,
                            " I couldn't extract much text from that PDF. It might be a scanned image.\n\n"
                            "Could you try **copy-pasting your CV text** instead?",
                            self.id
                        )
                        return
                        
            except Exception as e:
                logger.error(f"[PDF] Error processing PDF: {e}", exc_info=True)
                await emit_response(
                    ctx,
                    f"⚠️ Had trouble processing that PDF. Could you try **copy-pasting your CV text** instead?\n\n"
                    f"_(Error: {str(e)[:100]})_",
                    self.id
                )
                return
        
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
            # Ensure we have a valid Brain thread (might be None after Playground migration)
            if conv_state.brain_thread is None:
                conv_state.brain_thread = self._brain.get_new_thread()
                logger.info("[CONFIRMATION] Created new Brain thread (was None after migration)")
            
            # Let the Brain agent decide if we should start analysis
            # Brain will output [START_ANALYSIS] if user wants to proceed
            logger.info(f"[CONFIRMATION] User said: {user_input[:100]}")
            result = await self._brain.run(user_input, thread=conv_state.brain_thread)
            response = result.messages[-1].text
            logger.info(f"[CONFIRMATION] Brain response: {response[:200]}...")
            
            # Check if Brain decided to trigger analysis
            if "[START_ANALYSIS]" in response:
                logger.info("[CONFIRMATION] Brain triggered [START_ANALYSIS]")
                
                # Make the waiting step feel natural - like a conversation pause
                await emit_response(
                    ctx, 
                    "**Got it!** Looks like a detailed CV and job posting - this analysis might take a little longer. Ready when you are! Just say **'go'** and I'll dive in.", 
                    self.id
                )
                
                # Update state - next user message will trigger analysis
                conv_state.state = "analyzing"
                return
                
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
                    # Q&A agent generates first question - give context but NOT gaps
                    # Q&A should explore naturally; Validation tracks gaps separately
                    
                    # Truncate CV and job for context (not full text)
                    cv_summary = conv_state.cv_text[:1200] + "..." if len(conv_state.cv_text) > 1200 else conv_state.cv_text
                    job_summary = conv_state.job_text[:800] + "..." if len(conv_state.job_text) > 800 else conv_state.job_text
                    
                    qna_prompt = f"""You're having a career chat with someone interested in a role.

CANDIDATE'S BACKGROUND (from their CV):
{cv_summary}

JOB THEY'RE EXPLORING:
{job_summary}

YOUR APPROACH:
- You KNOW their background - reference it naturally, don't ask them to repeat it
- Have a genuine conversation about their experience and interests
- Ask follow-up questions that dig deeper into what they've done
- Be curious about their projects, motivations, and career goals
- Don't interrogate or run through a checklist
- Let the conversation flow naturally

Start with something specific from their CV that caught your attention, then explore from there."""
                    
                    qna_result = await self._qna_agent.run(qna_prompt, thread=conv_state.qna_thread)
                    first_question = qna_result.messages[-1].text
                    conv_state.qna_history.append(f"Advisor: {first_question}")
                    
                    # ONE COMBINED MESSAGE - avoids 400 error from multiple emit_response calls
                    combined_response = (
                        f" **Analysis Complete!** Areas to explore: **{len(gaps)}**\n\n"
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
            await emit_response(ctx, f" Error during analysis. Type 'reset' to try again.", self.id)
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
        
        # Every 4 exchanges, Validation tells us which gap to explore next
        user_exchanges = len([h for h in conv_state.qna_history if h.startswith("User:")])
        should_target_gap = (user_exchanges > 0 and user_exchanges % 4 == 0 and conv_state.gaps)
        
        if should_target_gap:
            # Get next gap from validation's remaining list
            target_gap = conv_state.gaps[0]
            qna_prompt = f"""The user just responded: "{user_input}"

Acknowledge their response briefly, then naturally steer to explore: {target_gap}

Don't mention 'gaps' or 'requirements' - just ask about related experiences. Be conversational and brief."""
            logger.info(f"[Q&A] Steering toward gap: {target_gap}")
        else:
            # Normal turn - Q&A just continues natural conversation (no gap knowledge)
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
        
        # Track which gaps were addressed (removed from remaining)
        newly_addressed = [g for g in conv_state.gaps if g not in updated_gaps]
        conv_state.addressed_gaps.extend(newly_addressed)
        conv_state.gaps = updated_gaps
        conv_state.validation_ready = validation_ready
        logger.info(f"[VALIDATION] Ready: {validation_ready}, Remaining gaps: {len(updated_gaps)}, Addressed: {len(conv_state.addressed_gaps)}")
        
        # Check if all gaps are covered - ask user if ready for recommendation
        if validation_ready or len(updated_gaps) == 0:
            logger.info("[VALIDATION] All gaps addressed - asking user if ready for recommendation")
            response_msg = (
                f"**[Q&A Agent]** {response}\n\n"
                "---\n\n"
                " **Great conversation!** I think we've covered all the key areas.\n\n"
                "Ready for your recommendation? Just type **'done'** and I'll give you my assessment!"
            )
        else:
            # Still have gaps to explore - continue Q&A
            response_msg = f"**[Q&A Agent]** {response}\n\n*(Type 'done' anytime for your recommendation)*"
        
        await emit_response(ctx, response_msg, self.id)
    
    async def _generate_recommendation(
        self,
        ctx: WorkflowContext,
        conv_state: ConversationState,
        qna_insights: str
    ) -> None:
        """Generate final recommendation and send as multiple messages."""
        
        logger.info("[RECOMMENDER] Generating final recommendation...")
        
        # Build comprehensive gap coverage summary
        initial_gaps = conv_state.initial_gaps if conv_state.initial_gaps else []
        addressed_gaps = conv_state.addressed_gaps if conv_state.addressed_gaps else []
        remaining_gaps = conv_state.gaps if conv_state.gaps else []
        
        # Format gaps with their status
        gap_summary = f"""**GAP COVERAGE SUMMARY:**

**Total Gaps Identified:** {len(initial_gaps)}
**Gaps Addressed in Q&A:** {len(addressed_gaps)}
**Gaps NOT Addressed:** {len(remaining_gaps)}

**ALL INITIAL GAPS (with status):**
{chr(10).join(f'-  {g} (ADDRESSED)' for g in addressed_gaps) if addressed_gaps else ''}
{chr(10).join(f'-  {g} (NOT ADDRESSED)' for g in remaining_gaps) if remaining_gaps else ''}
"""
        
        recommendation_prompt = f"""**CV:**
{conv_state.cv_text}

**JOB DESCRIPTION:**
{conv_state.job_text}

**ANALYSIS:**
{conv_state.analysis_text}

{gap_summary}

**Q&A CONVERSATION HISTORY:**
{qna_insights if qna_insights else "No Q&A conversation - high initial match score."}

Please provide your full, detailed recommendation now."""
        
        result = await self._recommender.run(recommendation_prompt)
        recommendation = result.messages[-1].text
        
        # Save this application to user profile
        try:
            user_id = get_conversation_id_from_context()
            profile = get_user_profile(user_id)
            
            # Determine recommendation category based on score and gaps
            remaining_gap_count = len(remaining_gaps)
            if conv_state.score >= 80 or remaining_gap_count == 0:
                rec_category = "apply"
            elif conv_state.score >= 60 and remaining_gap_count <= 3:
                rec_category = "apply_with_prep"
            else:
                rec_category = "consider_alternatives"
            
            # Extract job title and company from job_text (improved heuristics)
            job_lines = (conv_state.job_text or "").split('\n')[:30]
            job_title = "Unknown Position"
            company = "Unknown Company"
            
            # Skip patterns - lines that are NOT job titles
            skip_patterns = ['logo', 'compartilhar', 'exibir', 'salvar', 'candidatar', 
                           'linkedin', 'about', 'http', 'www.', '@', 'posted', 'apply',
                           'híbrido', 'remoto', 'presencial', 'estágio', 'job type',
                           'location', 'clicaram', 'pessoas', 'opções', 'correspondência']
            
            # Job title patterns - lines that ARE likely job titles
            title_keywords = ['engineer', 'developer', 'manager', 'analyst', 'designer',
                            'intern', 'specialist', 'coordinator', 'director', 'lead',
                            'architect', 'scientist', 'consultant', 'associate', 'senior',
                            'junior', 'sre', 'devops', 'software', 'data', 'product']
            
            for line in job_lines:
                line_clean = line.strip()
                line_lower = line_clean.lower()
                
                # Skip empty, too short, or too long lines
                if not line_clean or len(line_clean) < 5 or len(line_clean) > 80:
                    continue
                
                # Skip lines matching skip patterns
                if any(skip in line_lower for skip in skip_patterns):
                    continue
                
                # Look for job title (contains title keywords)
                if job_title == "Unknown Position":
                    if any(kw in line_lower for kw in title_keywords):
                        job_title = line_clean
                        continue
                
                # Look for company name (after we have title)
                if job_title != "Unknown Position" and company == "Unknown Company":
                    # Company often follows title, or has patterns like "at Company" or "Company ·"
                    if '·' in line_clean or ' at ' in line_lower or 'about ' in line_lower:
                        # Extract company name
                        if '·' in line_clean:
                            company = line_clean.split('·')[0].strip()
                        elif ' at ' in line_lower:
                            company = line_clean.split(' at ')[-1].strip()
                        break
                    # Or it's just the next reasonable line
                    elif len(line_clean) < 50 and not any(skip in line_lower for skip in skip_patterns):
                        company = line_clean
                        break
            
            app_record = ApplicationRecord(
                date=datetime.now(tz=timezone.utc).isoformat(),
                job_title=job_title[:100],  # Truncate
                company=company[:100],
                industry="",  # Could be LLM-extracted later
                score=conv_state.score,
                must_have_gaps=[g for g in initial_gaps if "must" in g.lower() or "required" in g.lower()][:5],
                nice_to_have_gaps=[g for g in initial_gaps if "nice" in g.lower() or "preferred" in g.lower()][:5],
                recommendation=rec_category
            )
            profile.applications.append(app_record)
            save_user_profile(user_id, profile)
            logger.info(f"[PROFILE] Saved application: {job_title[:30]} ({rec_category})")
        except Exception as e:
            logger.warning(f"[PROFILE] Failed to save application: {e}")
        
        # Split recommendation into sections for menu-based browsing
        import re
        sections = re.split(r'\n(?=## )', recommendation)
        # Filter out empty sections
        sections = [s.strip() for s in sections if s.strip()]
        
        # Store sections for menu navigation
        conv_state.recommendation_sections = sections
        
        if len(sections) > 1:
            # Menu-based approach: show first section + menu
            first_section = sections[0]
            if len(first_section) > 3500:
                first_section = first_section[:3500] + "..."
            
            menu = self._build_recommendation_menu(sections)
            
            first_msg = f"**[Recommendation Agent]** Here's my assessment:\n\n{first_section}\n\n---\n\n{menu}"
            await emit_response(ctx, first_msg, self.id)
            
            # Set state to viewing_recommendation for menu navigation
            conv_state.state = "viewing_recommendation"
            logger.info(f"[RECOMMENDER] Showing menu with {len(sections)} sections")
        else:
            # Single section or short recommendation - show all with follow-up
            follow_up = (
                "---\n\n"
                "🔄 **What's next?**\n\n"
                "• Try a **new job description** (just paste it)\n"
                "• Update your **CV** and try again\n"
                "• Type **'reset'** to start completely fresh"
            )
            
            full_message = f"**[Recommendation Agent]** Here's my assessment:\n\n{recommendation}\n\n{follow_up}"
            
            if len(full_message) > 3800:
                full_message = full_message[:3750] + "..."
            
            await emit_response(ctx, full_message, self.id)
            conv_state.state = "complete"
    
    def _build_recommendation_menu(self, sections: List[str]) -> str:
        """Build a numbered menu from recommendation sections, plus profile option."""
        import re
        menu_items = []
        for i, section in enumerate(sections, 1):
            # Extract first line or header as title
            lines = section.strip().split('\n')
            first_line = lines[0] if lines else f"Section {i}"
            # Clean up header (remove ##, **, emojis, etc.)
            title = re.sub(r'^[\#\*\s]+', '', first_line).strip()
            # Remove emojis (unicode emoji ranges)
            title = re.sub(r'[\U0001F300-\U0001F9FF\U00002600-\U000027BF\U0001F600-\U0001F64F]+', '', title).strip()
            if not title:
                title = f"Section {i}"
            # Truncate long titles
            if len(title) > 50:
                title = title[:47] + "..."
            menu_items.append(f"**{i}.** {title}")
        
        # Add profile as the last numbered item
        profile_num = len(sections) + 1
        menu_items.append(f"**{profile_num}.** 📊 My Profile (application history)")
        
        return "**Sections:**\n" + "\n".join(menu_items) + "\n\n_Type a number to view that section, or **'done'** when finished._"
    
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
        
        # Ensure we have a valid Brain thread (might be None after Playground migration)
        if conv_state.brain_thread is None:
            conv_state.brain_thread = self._brain.get_new_thread()
            logger.info("[POST_RECOMMENDATION] Created new Brain thread (was None)")
        
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

    async def _handle_viewing_recommendation(
        self,
        ctx: WorkflowContext,
        conv_state: ConversationState,
        user_input: str,
        conversation_id: str
    ) -> None:
        """Handle menu navigation while viewing recommendation sections."""
        
        user_lower = user_input.lower().strip()
        sections = conv_state.recommendation_sections
        profile_num = len(sections) + 1  # Profile is last item
        
        # User is done viewing - go to Brain for "what next"
        if user_lower == 'done':
            conv_state.state = "complete"
            logger.info("[VIEWING_RECOMMENDATION] User done - delegating to Brain")
            await self._handle_post_recommendation(ctx, conv_state, "I'm done reviewing the recommendation. What can I do next?", conversation_id)
            return
        
        # User wants to see a specific section or profile
        if user_lower.isdigit():
            section_num = int(user_lower)
            
            # Check if user selected profile
            if section_num == profile_num:
                await self._show_user_profile(ctx, conv_state, sections)
                return
            
            if 1 <= section_num <= len(sections):
                section = sections[section_num - 1]
                if len(section) > 3500:
                    section = section[:3500] + "..."
                
                menu = self._build_recommendation_menu(sections)
                response = f"{section}\n\n---\n\n{menu}"
                await emit_response(ctx, response, self.id)
                logger.info(f"[VIEWING_RECOMMENDATION] Showed section {section_num}/{len(sections)}")
                return
            else:
                await emit_response(ctx, f"Please enter a number between 1 and {profile_num}, or **'done'** when finished.", self.id)
                return
        
        # User typed something else - show help
        menu = self._build_recommendation_menu(sections)
        await emit_response(ctx, f"Here's your recommendation for this job! {menu}", self.id)
    
    async def _show_user_profile(
        self,
        ctx: WorkflowContext,
        conv_state: ConversationState,
        sections: List[str]
    ) -> None:
        """Show user's application history and insights."""
        user_id = get_conversation_id_from_context()
        profile = get_user_profile(user_id)
        
        if not profile.applications:
            profile_view = (
                "##  My Profile\n\n"
                "**No application history yet!**\n\n"
                "Your profile will track:\n"
                "- Jobs you've analyzed\n"
                "- Match scores over time\n"
                "- Common skill gaps\n"
                "- Recommendation patterns\n\n"
                "Keep analyzing jobs to build your profile!"
            )
        else:
            apps = profile.applications
            total = len(apps)
            avg_score = sum(a.score for a in apps) / total if total > 0 else 0
            
            # Count recommendations
            apply_count = sum(1 for a in apps if a.recommendation == "apply")
            prep_count = sum(1 for a in apps if a.recommendation == "apply_with_prep")
            alt_count = sum(1 for a in apps if a.recommendation == "consider_alternatives")
            
            # Find recurring gaps
            all_gaps = []
            for a in apps:
                all_gaps.extend(a.must_have_gaps)
                all_gaps.extend(a.nice_to_have_gaps)
            gap_counts: Dict[str, int] = {}
            for g in all_gaps:
                gap_counts[g] = gap_counts.get(g, 0) + 1
            top_gaps = sorted(gap_counts.items(), key=lambda x: -x[1])[:5]
            
            # Recent applications
            recent = apps[-5:][::-1]  # Last 5, newest first
            recent_lines = []
            for a in recent:
                emoji = "✅" if a.recommendation == "apply" else ("⚡" if a.recommendation == "apply_with_prep" else "🔄")
                recent_lines.append(f"- {emoji} **{a.job_title[:40]}** ({a.score}%)")
            
            profile_view = (
                "## 📊 My Profile\n\n"
                f"**Applications Analyzed:** {total}\n"
                f"**Average Match Score:** {avg_score:.0f}%\n\n"
                "**Recommendation Breakdown:**\n"
                f"- ✅ Apply: {apply_count}\n"
                f"- ⚡ Apply with prep: {prep_count}\n"
                f"- 🔄 Consider alternatives: {alt_count}\n\n"
            )
            
            if top_gaps:
                profile_view += "**Recurring Gaps to Address:**\n"
                for gap, count in top_gaps:
                    profile_view += f"- {gap[:50]} ({count}x)\n"
                profile_view += "\n"
            
            profile_view += "**Recent Applications:**\n" + "\n".join(recent_lines)
        
        menu = self._build_recommendation_menu(sections)
        response = f"{profile_view}\n\n---\n\n{menu}"
        await emit_response(ctx, response, self.id)
        logger.info(f"[PROFILE] Showed profile with {len(profile.applications)} applications")


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
