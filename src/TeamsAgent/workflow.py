"""
CV Analysis Workflow - Native HITL Pattern for Hosted Agent Deployment

Architecture:
Input → Analyzer → (Conditional) → Q&A (HITL) + Validation → Recommendation
                               ↘ Recommendation (skip Q&A if score ≥ 80)

Uses ctx.request_info() for human-in-the-loop pauses.
"""
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
load_dotenv()

from agent_framework import (
    ChatAgent,
    ChatMessage,
    Executor,
    Role,
    WorkflowBuilder,
    WorkflowContext,
    handler,
    response_handler,
)
from agent_framework._workflows._edge import Case, Default
from agent_framework.azure import AzureOpenAIChatClient
from azure.identity import DefaultAzureCredential

from config import Config
from agent_definitions import AgentDefinitions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# Message Types
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
class QnAQuestion:
    """Request for human input during Q&A (HITL pause)."""
    question: str
    gaps_remaining: List[str]
    exchange_count: int
    in_wrap_up_mode: bool


@dataclass
class QnAAnswer:
    """Human's answer to Q&A question."""
    answer: str


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
# Helper Functions (unchanged from original)
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
        'before we wrap up'
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
        
        # Print gap tracking updates
        if removed_gaps:
            print(f"\n✅ Gaps addressed: {', '.join(removed_gaps)}")
            print(f"📋 Remaining gaps: {len(remaining_gaps)}")
        
        return validation_ready, remaining_gaps
    except Exception as e:
        logger.warning(f"Validation check failed: {e}")
        return False, current_gaps


# ============================================================================
# Condition Functions for Routing
# ============================================================================

def needs_qna_condition(message: Any) -> bool:
    """Route to Q&A if score < 80 or has must-have gaps."""
    return isinstance(message, AnalysisResult) and message.needs_qna


def skip_qna_condition(message: Any) -> bool:
    """Skip Q&A if score >= 80 and no must-have gaps."""
    return isinstance(message, AnalysisResult) and not message.needs_qna


# ============================================================================
# Analyzer Executor
# ============================================================================

class AnalyzerExecutor(Executor):
    """Analyzes CV against job description."""
    
    def __init__(self, analyzer_agent: ChatAgent):
        super().__init__(id="analyzer-executor")
        self._analyzer = analyzer_agent
    
    @handler
    async def handle_chat_messages(self, messages: list[ChatMessage], ctx: WorkflowContext) -> None:
        """Handle input from agent interface (list[ChatMessage]).
        
        Expected format in first message:
        CV: <cv_text>
        ---
        JOB: <job_description>
        """
        logger.info("Received chat messages, parsing CV and job description...")
        
        # Get the last user message
        user_text = ""
        for msg in reversed(messages):
            if msg.text:
                user_text = msg.text
                break
        
        # Parse CV and job description from message
        if "---" in user_text:
            parts = user_text.split("---", 1)
            cv_text = parts[0].replace("CV:", "").strip()
            job_description = parts[1].replace("JOB:", "").strip()
        else:
            # Assume whole message is CV + job description
            cv_text = user_text
            job_description = ""
        
        input_data = CVInput(cv_text=cv_text, job_description=job_description)
        await self.analyze(input_data, ctx)
    
    @handler
    async def analyze(self, input_data: CVInput, ctx: WorkflowContext) -> None:
        """Analyze CV and determine if Q&A is needed."""
        logger.info("Starting CV analysis...")
        
        result = await self._analyzer.run(f"""**CANDIDATE CV:**
{input_data.cv_text}

**JOB DESCRIPTION:**
{input_data.job_description}""")
        
        analysis_text = result.messages[-1].text
        needs_qna, score, gaps = should_run_qna(analysis_text)
        
        analysis_result = AnalysisResult(
            analysis_json=analysis_text,
            cv_text=input_data.cv_text,
            job_description=input_data.job_description,
            needs_qna=needs_qna,
            score=score,
            gaps=gaps
        )
        
        logger.info(f"Analysis complete. Score: {score}, Needs Q&A: {needs_qna}, Gaps: {len(gaps)}")
        
        # Print full analysis output
        print("\n" + "=" * 60)
        print("📊 FULL ANALYSIS OUTPUT")
        print("=" * 60)
        print(analysis_text)
        print("\n" + "=" * 60)
        print("📋 SUMMARY")
        print("=" * 60)
        print(f"📈 Preliminary Score: {score}/100")
        print(f"🔍 Identified Gaps ({len(gaps)}):")
        for i, gap in enumerate(gaps, 1):
            print(f"   {i}. {gap}")
        print(f"\n➡️  {'Proceeding to Q&A...' if needs_qna else 'Skipping Q&A (high score!)'}")
        print("=" * 60 + "\n")
        
        # Send to next executor (routing handled by conditional edges)
        await ctx.send_message(analysis_result)


# ============================================================================
# Q&A Executor with HITL
# ============================================================================

class QnAExecutor(Executor):
    """Conducts Q&A with human-in-the-loop pauses."""
    
    def __init__(self, qna_agent: ChatAgent, validation_agent: ChatAgent):
        super().__init__(id="qna-executor")
        self._qna_agent = qna_agent
        self._validation_agent = validation_agent
        
        # State (persisted by framework via checkpointing)
        self._analysis_result: Optional[AnalysisResult] = None
        self._thread = None
        self._conversation_history: List[str] = []
        self._gaps: List[str] = []
        self._agent_asked_termination_question: bool = False
        self._in_wrap_up_mode: bool = False
    
    @handler
    async def start_qna(self, analysis_result: AnalysisResult, ctx: WorkflowContext) -> None:
        """Start Q&A session - ask first question."""
        logger.info(f"Starting Q&A with {len(analysis_result.gaps)} gaps to explore")
        
        self._analysis_result = analysis_result
        self._gaps = analysis_result.gaps.copy()
        self._thread = self._qna_agent.get_new_thread()
        self._conversation_history = []
        self._agent_asked_termination_question = False
        self._in_wrap_up_mode = False
        
        # Get first question from agent
        initial_prompt = f"""**ANALYSIS:**
{analysis_result.analysis_json}

**CV:**
{analysis_result.cv_text}

**JOB DESCRIPTION:**
{analysis_result.job_description}"""
        
        result = await self._qna_agent.run(initial_prompt, thread=self._thread)
        first_question = result.messages[-1].text
        self._conversation_history.append(f"Advisor: {first_question}")
        
        # Check if first response is a termination question
        self._agent_asked_termination_question = detect_termination_question(first_question)
        
        logger.info("Q&A started, waiting for human response...")
        
        # PAUSE - Wait for human response
        await ctx.request_info(
            request_data=QnAQuestion(
                question=first_question,
                gaps_remaining=self._gaps,
                exchange_count=0,
                in_wrap_up_mode=False
            ),
            response_type=QnAAnswer
        )
    
    @response_handler
    async def handle_human_answer(
        self,
        original_request: QnAQuestion,
        response: QnAAnswer,
        ctx: WorkflowContext
    ) -> None:
        """Process human's answer and either ask next question or complete."""
        user_input = response.answer
        logger.info(f"Received user input: {user_input[:50]}...")
        
        # =====================================================================
        # HANDLE 'done' COMMAND
        # =====================================================================
        if user_input.lower().strip() == 'done':
            logger.info("User requested to end conversation with 'done'")
            qna_summary = "User chose to end conversation. Based on conversation:\n" + "\n".join(self._conversation_history)
            
            await ctx.send_message(
                QnAComplete(
                    analysis_result=self._analysis_result,
                    qna_insights=qna_summary,
                    conversation_history=self._conversation_history
                )
            )
            return
        
        # Add user input to history
        self._conversation_history.append(f"User: {user_input}")
        
        user_exchanges = len([msg for msg in self._conversation_history if msg.startswith("User:")])
        current_gaps = self._gaps
        
        # =====================================================================
        # TERMINATION ATTEMPT HANDLING (user says 'n')
        # =====================================================================
        if user_input.lower().strip() == 'n' and (self._agent_asked_termination_question or self._in_wrap_up_mode):
            logger.info("User chose to end conversation with 'n'")
            
            validation_ready, updated_gaps = await check_validation_status(
                self._validation_agent, current_gaps, self._conversation_history, is_termination_attempt=True
            )
            
            # Get final summary from agent
            result = await self._qna_agent.run(
                "Please provide your final assessment based on our conversation.",
                thread=self._thread
            )
            summary = result.messages[-1].text
            self._conversation_history.append(f"Advisor: {summary}")
            
            # Complete Q&A, move to recommendation
            await ctx.send_message(
                QnAComplete(
                    analysis_result=self._analysis_result,
                    qna_insights=summary,
                    conversation_history=self._conversation_history
                )
            )
            return
        
        # =====================================================================
        # GAP TARGETING (every 5th exchange, with priority keywords)
        # =====================================================================
        should_do_gap_targeting = (user_exchanges > 0 and user_exchanges % 5 == 0 and current_gaps)
        
        if should_do_gap_targeting:
            priority_gaps = [gap for gap in current_gaps if any(keyword in gap.lower() 
                for keyword in ['networking', 'communication', 'teamwork', 'authorization', 'location'])]
            target_gap = priority_gaps[0] if priority_gaps else current_gaps[0]
            
            logger.info(f"Gap targeting: {target_gap}")
            
            gap_targeting_prompt = f"""The user just responded: "{user_input}"

Now I'd like you to acknowledge their response briefly, then naturally steer the conversation to explore their experience with: {target_gap}

Don't directly mention 'gaps' or make it obvious - just ask about related experiences, examples, or specific situations. Avoid asking 'what excites you' questions. Be conversational and focus on concrete examples."""
            
            result = await self._qna_agent.run(gap_targeting_prompt, thread=self._thread)
            agent_response = result.messages[-1].text
            self._conversation_history.append(f"Advisor: {agent_response}")
            
            # Validation check and gap update
            validation_ready, updated_gaps = await check_validation_status(
                self._validation_agent, current_gaps, self._conversation_history
            )
            self._gaps = updated_gaps
            
            self._agent_asked_termination_question = detect_termination_question(agent_response)
            if self._agent_asked_termination_question:
                self._in_wrap_up_mode = True
            
            # Ask next question
            await ctx.request_info(
                request_data=QnAQuestion(
                    question=agent_response,
                    gaps_remaining=self._gaps,
                    exchange_count=user_exchanges,
                    in_wrap_up_mode=self._in_wrap_up_mode
                ),
                response_type=QnAAnswer
            )
            return
        
        # =====================================================================
        # WRAP-UP MODE
        # =====================================================================
        if self._in_wrap_up_mode:
            wrap_up_prompt = f"""User asked: "{user_input}"

Please answer their question thoroughly, then end your response by asking if there's anything else they'd like to explore, making it clear they can answer 'n' if they feel everything has been covered."""
            
            result = await self._qna_agent.run(wrap_up_prompt, thread=self._thread)
            agent_response = result.messages[-1].text
            self._conversation_history.append(f"Advisor: {agent_response}")
            
            validation_ready, updated_gaps = await check_validation_status(
                self._validation_agent, current_gaps, self._conversation_history
            )
            self._gaps = updated_gaps
            
            self._agent_asked_termination_question = True
            
            # Ask next question
            await ctx.request_info(
                request_data=QnAQuestion(
                    question=agent_response,
                    gaps_remaining=self._gaps,
                    exchange_count=user_exchanges,
                    in_wrap_up_mode=True
                ),
                response_type=QnAAnswer
            )
            return
        
        # =====================================================================
        # NORMAL CONVERSATION FLOW
        # =====================================================================
        result = await self._qna_agent.run(f"User response: {user_input}", thread=self._thread)
        agent_response = result.messages[-1].text
        self._conversation_history.append(f"Advisor: {agent_response}")
        
        self._agent_asked_termination_question = detect_termination_question(agent_response)
        
        validation_ready, remaining_gaps = await check_validation_status(
            self._validation_agent, current_gaps, self._conversation_history
        )
        self._gaps = remaining_gaps
        
        if self._agent_asked_termination_question:
            self._in_wrap_up_mode = True
        elif validation_ready and len(self._conversation_history) >= 10 and not self._in_wrap_up_mode:
            # Trigger wrap-up
            logger.info("Validation ready, triggering wrap-up")
            ending_result = await self._qna_agent.run(
                "The conversation has covered the key areas well. Ask if there's anything specific they'd like to explore further, and make it clear they can answer 'n' if they feel everything has been covered.",
                thread=self._thread
            )
            agent_response = ending_result.messages[-1].text
            self._conversation_history.append(f"Advisor: {agent_response}")
            self._agent_asked_termination_question = True
            self._in_wrap_up_mode = True
        
        # Ask next question
        await ctx.request_info(
            request_data=QnAQuestion(
                question=agent_response,
                gaps_remaining=self._gaps,
                exchange_count=user_exchanges,
                in_wrap_up_mode=self._in_wrap_up_mode
            ),
            response_type=QnAAnswer
        )


# ============================================================================
# Recommendation Executor
# ============================================================================

class RecommendationExecutor(Executor):
    """Generates final recommendation."""
    
    def __init__(self, recommendation_agent: ChatAgent):
        super().__init__(id="recommendation-executor")
        self._recommender = recommendation_agent
    
    @handler
    async def generate_from_qna(self, qna_complete: QnAComplete, ctx: WorkflowContext) -> None:
        """Generate recommendation after Q&A."""
        logger.info("Generating recommendation after Q&A...")
        
        result = await self._recommender.run(f"""**INITIAL ANALYSIS:**
{qna_complete.analysis_result.analysis_json}

**Q&A INSIGHTS:**
{qna_complete.qna_insights}

**FULL CONVERSATION:**
{chr(10).join(qna_complete.conversation_history)}

**CV:**
{qna_complete.analysis_result.cv_text}

**JOB DESCRIPTION:**
{qna_complete.analysis_result.job_description}

Based on the initial analysis and the Q&A conversation insights, provide a comprehensive final recommendation.""")
        
        recommendation = result.messages[-1].text
        logger.info("Recommendation generated (from Q&A path)")
        
        # Yield as ChatMessage for agent output
        ctx.yield_output(ChatMessage(role=Role.ASSISTANT, text=recommendation))
    
    @handler
    async def generate_direct(self, analysis_result: AnalysisResult, ctx: WorkflowContext) -> None:
        """Generate recommendation without Q&A (high score path)."""
        logger.info("Generating recommendation directly (skipping Q&A)...")
        
        result = await self._recommender.run(f"""**ANALYSIS:**
{analysis_result.analysis_json}

**CV:**
{analysis_result.cv_text}

**JOB DESCRIPTION:**
{analysis_result.job_description}

Based on the analysis, provide a comprehensive final recommendation.""")
        
        recommendation = result.messages[-1].text
        logger.info("Recommendation generated (direct path)")
        
        # Yield as ChatMessage for agent output
        ctx.yield_output(ChatMessage(role=Role.ASSISTANT, text=recommendation))


# ============================================================================
# Agent Setup
# ============================================================================

def create_agents(config: Config) -> Dict[str, ChatAgent]:
    """Create all agents."""
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
    """Build the CV analysis workflow as an agent."""
    config = Config()
    agents = create_agents(config)
    
    workflow = (
        WorkflowBuilder()
        .register_executor(
            lambda: AnalyzerExecutor(agents["analyzer"]),
            name="analyzer"
        )
        .register_executor(
            lambda: QnAExecutor(agents["qna"], agents["validation"]),
            name="qna"
        )
        .register_executor(
            lambda: RecommendationExecutor(agents["recommendation"]),
            name="recommendation"
        )
        # Conditional routing from analyzer: if high score → skip Q&A, else do Q&A
        .add_switch_case_edge_group(
            "analyzer",
            [
                Case(skip_qna_condition, "recommendation"),  # If high score → skip to recommendation
                Default("qna"),                               # Otherwise → go to Q&A
            ]
        )
        # Q&A completion leads to recommendation
        .add_edge("qna", "recommendation")
        .set_start_executor("analyzer")
        .build()
        .as_agent()
    )
    
    logger.info("CV workflow agent built successfully")
    return workflow


# ============================================================================
# For testing locally without hosting adapter
# ============================================================================

async def test_workflow():
    """Test the workflow locally."""
    from agent_framework import ChatMessage, FunctionCallContent, FunctionResultContent, Role, WorkflowAgent
    
    agent = build_cv_workflow_agent()
    
    # Sample input
    cv_text = "Your CV text here..."
    job_text = "Your job description here..."
    
    # Start workflow
    response = await agent.run(f"Analyze this CV:\n{cv_text}\n\nFor this job:\n{job_text}")
    
    # Handle HITL loop
    while True:
        # Check for HITL request
        hitl_call = None
        for message in response.messages:
            for content in message.contents:
                if isinstance(content, FunctionCallContent) and content.name == WorkflowAgent.REQUEST_INFO_FUNCTION_NAME:
                    hitl_call = content
                    break
        
        if not hitl_call:
            # Workflow complete
            print("Final response:", response.messages[-1].text)
            break
        
        # Get user input
        user_answer = input("Your response: ")
        
        # Send back to workflow
        result = FunctionResultContent(
            call_id=hitl_call.call_id,
            result=QnAAnswer(answer=user_answer)
        )
        response = await agent.run(ChatMessage(role=Role.TOOL, contents=[result]))


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_workflow())