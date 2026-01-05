"""
Application Buddy - Streamlit UI
A clean, LinkedIn-inspired interface for CV analysis.
"""
import streamlit as st
import asyncio
import sys
import os

# Add parent directories to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'StateBasedTeamsAgent'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
# Load .env from the project root using absolute path
env_path = "/home/clara/projects/application_buddy/Application_Buddy/.env"
load_dotenv(env_path, override=True)

# Import after path setup
from agent_framework import ChatAgent, ChatMessage, Role, TextContent
from agent_framework.azure import AzureOpenAIChatClient
from azure.identity import DefaultAzureCredential

from src.StateBasedTeamsAgent.config import Config
from src.StateBasedTeamsAgent.agent_definitions import AgentDefinitions

# ============================================================================
# Page Config & Custom CSS (LinkedIn-inspired)
# ============================================================================

st.set_page_config(
    page_title="Application Buddy",
    page_icon="🎯",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# LinkedIn-inspired CSS
st.markdown("""
<style>
    /* Main container */
    .main {
        background-color: #f3f2ef;
    }
    
    /* Cards with rounded edges */
    .stCard, div[data-testid="stVerticalBlock"] > div {
        background-color: white;
        border-radius: 12px;
        padding: 1rem;
    }
    
    /* Chat messages */
    .chat-message {
        padding: 1rem 1.5rem;
        border-radius: 12px;
        margin-bottom: 1rem;
        max-width: 85%;
    }
    
    .user-message {
        background-color: #0a66c2;
        color: white;
        margin-left: auto;
        border-bottom-right-radius: 4px;
    }
    
    .bot-message {
        background-color: white;
        color: #000000e6;
        border: 1px solid #e0e0e0;
        border-bottom-left-radius: 4px;
    }
    
    /* Input fields */
    .stTextArea textarea, .stTextInput input {
        border-radius: 8px !important;
        border: 1px solid #e0e0e0 !important;
    }
    
    .stTextArea textarea:focus, .stTextInput input:focus {
        border-color: #0a66c2 !important;
        box-shadow: 0 0 0 1px #0a66c2 !important;
    }
    
    /* Buttons */
    .stButton > button {
        border-radius: 24px !important;
        padding: 0.5rem 1.5rem !important;
        font-weight: 600 !important;
        transition: all 0.2s ease !important;
    }
    
    /* Primary button (blue) */
    .stButton > button[kind="primary"], 
    .stButton > button {
        background-color: #0a66c2 !important;
        color: white !important;
        border: none !important;
    }
    
    .stButton > button:hover {
        background-color: #004182 !important;
    }
    
    /* Secondary button (outline) */
    .secondary-btn > button {
        background-color: white !important;
        color: #0a66c2 !important;
        border: 1px solid #0a66c2 !important;
    }
    
    .secondary-btn > button:hover {
        background-color: #f3f6f8 !important;
    }
    
    /* File uploader */
    .stFileUploader {
        border-radius: 12px !important;
    }
    
    /* Progress steps */
    .progress-step {
        display: inline-block;
        padding: 0.5rem 1rem;
        border-radius: 20px;
        margin-right: 0.5rem;
        font-size: 0.9rem;
    }
    
    .step-active {
        background-color: #0a66c2;
        color: white;
    }
    
    .step-complete {
        background-color: #057642;
        color: white;
    }
    
    .step-pending {
        background-color: #e0e0e0;
        color: #666;
    }
    
    /* Header */
    .header-container {
        background: linear-gradient(135deg, #0a66c2 0%, #004182 100%);
        padding: 2rem;
        border-radius: 12px;
        color: white;
        margin-bottom: 2rem;
        text-align: center;
    }
    
    .header-container h1 {
        margin: 0;
        font-size: 2rem;
    }
    
    .header-container p {
        margin: 0.5rem 0 0 0;
        opacity: 0.9;
    }
    
    /* Chat container */
    .chat-container {
        background: white;
        border-radius: 12px;
        padding: 1.5rem;
        margin-bottom: 1rem;
        border: 1px solid #e0e0e0;
        max-height: 400px;
        overflow-y: auto;
    }
    
    /* Status badge */
    .status-badge {
        display: inline-block;
        padding: 0.25rem 0.75rem;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    
    .status-collecting { background-color: #fff3cd; color: #856404; }
    .status-analyzing { background-color: #cce5ff; color: #004085; }
    .status-qna { background-color: #d4edda; color: #155724; }
    .status-complete { background-color: #057642; color: white; }
    
    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Expander styling */
    .streamlit-expanderHeader {
        border-radius: 8px !important;
        background-color: #f8f9fa !important;
    }
    
    /* Info boxes */
    .info-box {
        background-color: #e8f4fd;
        border-left: 4px solid #0a66c2;
        padding: 1rem;
        border-radius: 0 8px 8px 0;
        margin: 1rem 0;
    }
    
    /* Recommendation card */
    .recommendation-card {
        background: linear-gradient(135deg, #f8f9fa 0%, #ffffff 100%);
        border-radius: 12px;
        padding: 1.5rem;
        border: 1px solid #e0e0e0;
        box-shadow: 0 2px 8px rgba(0,0,0,0.05);
    }
</style>
""", unsafe_allow_html=True)


# ============================================================================
# Session State Initialization
# ============================================================================

def init_session_state():
    """Initialize all session state variables."""
    defaults = {
        'state': 'welcome',  # welcome, collecting_cv, collecting_job, analyzing, qna, recommendation
        'cv_text': None,
        'job_text': None,
        'analysis_text': None,
        'gaps': [],
        'initial_gaps': [],
        'score': 0,
        'qna_history': [],
        'chat_history': [],
        'recommendation': None,
        'brain_thread': None,
        'qna_thread': None,
        'agents_initialized': False,
        'chat_client': None,
        'brain_agent': None,
        'analyzer_agent': None,
        'qna_agent': None,
        'recommendation_agent': None,
        'validation_agent': None,
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# ============================================================================
# Agent Setup
# ============================================================================

@st.cache_resource
def get_chat_client():
    """Create and cache the Azure OpenAI chat client using Managed Identity."""
    # Use the same Config class as the working workflow.py
    config = Config()
    azure_endpoint = config.azure_ai_foundry_endpoint.split('/api/projects/')[0]
    
    return AzureOpenAIChatClient(
        deployment_name=config.model_deployment_name,
        endpoint=azure_endpoint,
        api_version=config.api_version,
        credential=DefaultAzureCredential(),
    )


def initialize_agents():
    """Initialize all agents if not already done."""
    if st.session_state.agents_initialized:
        return
    
    chat_client = get_chat_client()
    st.session_state.chat_client = chat_client
    
    # Brain agent
    brain_config = AgentDefinitions.get_brain_agent()
    st.session_state.brain_agent = ChatAgent(
        name=brain_config["name"],
        instructions=brain_config["instructions"],
        chat_client=chat_client,
    )
    
    # Analyzer agent  
    analyzer_config = AgentDefinitions.get_analyzer_agent()
    st.session_state.analyzer_agent = ChatAgent(
        name=analyzer_config["name"],
        instructions=analyzer_config["instructions"],
        chat_client=chat_client,
    )
    
    # Q&A agent
    qna_config = AgentDefinitions.get_qna_agent()
    st.session_state.qna_agent = ChatAgent(
        name=qna_config["name"],
        instructions=qna_config["instructions"],
        chat_client=chat_client,
    )
    
    # Recommendation agent
    rec_config = AgentDefinitions.get_recommendation_agent()
    st.session_state.recommendation_agent = ChatAgent(
        name=rec_config["name"],
        instructions=rec_config["instructions"],
        chat_client=chat_client,
    )
    
    # Validation agent
    val_config = AgentDefinitions.get_validation_agent()
    st.session_state.validation_agent = ChatAgent(
        name=val_config["name"],
        instructions=val_config["instructions"],
        chat_client=chat_client,
    )
    
    # Create threads
    st.session_state.brain_thread = st.session_state.brain_agent.get_new_thread()
    st.session_state.qna_thread = st.session_state.qna_agent.get_new_thread()
    
    st.session_state.agents_initialized = True


# ============================================================================
# Agent Interaction Functions
# ============================================================================

async def run_brain_agent(user_input: str) -> str:
    """Run the brain agent with user input."""
    result = await st.session_state.brain_agent.run(
        user_input,
        thread=st.session_state.brain_thread
    )
    return result.messages[-1].text


async def run_analyzer(cv_text: str, job_text: str) -> str:
    """Run the analyzer agent."""
    prompt = f"""**CANDIDATE CV:**
{cv_text}

**JOB DESCRIPTION:**
{job_text}"""
    
    result = await st.session_state.analyzer_agent.run(prompt)
    return result.messages[-1].text


async def run_qna_agent(user_input: str, gaps: list, analysis: str) -> str:
    """Run Q&A agent with context."""
    # First message includes context
    if len(st.session_state.qna_history) == 0:
        context = f"""ANALYSIS CONTEXT:
{analysis}

GAPS TO EXPLORE:
{', '.join(gaps)}

User message: {user_input}"""
        result = await st.session_state.qna_agent.run(
            context,
            thread=st.session_state.qna_thread
        )
    else:
        result = await st.session_state.qna_agent.run(
            user_input,
            thread=st.session_state.qna_thread
        )
    
    return result.messages[-1].text


async def run_recommendation_agent(cv_text: str, job_text: str, analysis: str, qna_history: list) -> str:
    """Run recommendation agent with full context."""
    qna_summary = "\n".join(qna_history) if qna_history else "No Q&A conducted."
    
    prompt = f"""**CV:**
{cv_text}

**JOB:**
{job_text}

**ANALYSIS:**
{analysis}

**Q&A INSIGHTS:**
{qna_summary}"""
    
    result = await st.session_state.recommendation_agent.run(prompt)
    return result.messages[-1].text


def parse_analysis(analysis_text: str) -> tuple:
    """Parse analysis JSON to extract score and gaps."""
    import json
    gaps = []
    score = 0
    
    try:
        if '{' in analysis_text and '}' in analysis_text:
            json_start = analysis_text.find('{')
            json_end = analysis_text.rfind('}') + 1
            json_str = analysis_text[json_start:json_end]
            
            analysis_data = json.loads(json_str)
            raw_gaps = analysis_data.get('gaps', [])
            gaps = [gap.get('name', str(gap)) for gap in raw_gaps]
            score = analysis_data.get('preliminary_score', 0)
    except:
        pass
    
    return score, gaps


# ============================================================================
# UI Components
# ============================================================================

def render_header():
    """Render the app header."""
    st.markdown("""
    <div class="header-container">
        <h1>🎯 Application Buddy</h1>
        <p>Your AI career advisor - honest feedback for smarter applications</p>
    </div>
    """, unsafe_allow_html=True)


def render_progress_bar():
    """Render progress indicator."""
    state = st.session_state.state
    steps = [
        ('welcome', '👋 Welcome'),
        ('collecting_cv', '📄 CV'),
        ('collecting_job', '💼 Job'),
        ('analyzing', '🔍 Analysis'),
        ('qna', '💬 Q&A'),
        ('recommendation', '✅ Result')
    ]
    
    state_order = [s[0] for s in steps]
    current_idx = state_order.index(state) if state in state_order else 0
    
    cols = st.columns(len(steps))
    for i, (step_state, step_label) in enumerate(steps):
        with cols[i]:
            if i < current_idx:
                st.markdown(f"<span class='progress-step step-complete'>{step_label}</span>", unsafe_allow_html=True)
            elif i == current_idx:
                st.markdown(f"<span class='progress-step step-active'>{step_label}</span>", unsafe_allow_html=True)
            else:
                st.markdown(f"<span class='progress-step step-pending'>{step_label}</span>", unsafe_allow_html=True)


def render_chat_history():
    """Render chat messages."""
    for msg in st.session_state.chat_history:
        if msg['role'] == 'user':
            st.markdown(f"""
            <div style="display: flex; justify-content: flex-end; margin-bottom: 1rem;">
                <div class="chat-message user-message">{msg['content'][:200]}{'...' if len(msg['content']) > 200 else ''}</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div style="display: flex; justify-content: flex-start; margin-bottom: 1rem;">
                <div class="chat-message bot-message">{msg['content']}</div>
            </div>
            """, unsafe_allow_html=True)


def add_chat_message(role: str, content: str):
    """Add a message to chat history."""
    st.session_state.chat_history.append({'role': role, 'content': content})


# ============================================================================
# Main UI Flow
# ============================================================================

def render_welcome():
    """Render welcome screen."""
    st.markdown("""
    <div class="info-box">
        <h3>👋 Welcome to Application Buddy!</h3>
        <p>I'll help you figure out if a job is really right for you - no more applying blind!</p>
        <br>
        <b>Here's how it works:</b>
        <ol>
            <li>Share your CV (paste text or upload PDF)</li>
            <li>Paste the job description you're eyeing</li>
            <li>I'll analyze the match and we'll have a quick chat</li>
            <li>You get honest advice on whether to apply</li>
        </ol>
        <br>
        <p><em>🔒 Your data is private - it's only used during this session and never stored.</em></p>
    </div>
    """, unsafe_allow_html=True)
    
    if st.button("🚀 Let's Get Started", use_container_width=True):
        st.session_state.state = 'collecting_cv'
        add_chat_message('assistant', "Great! Let's start with your CV. You can either paste the text below or upload a PDF file.")
        st.rerun()


def render_collecting_cv():
    """Render CV collection screen."""
    st.markdown("### 📄 Share Your CV")
    
    # Tabs for different input methods
    tab1, tab2 = st.tabs(["📝 Paste Text", "📎 Upload PDF"])
    
    with tab1:
        cv_text = st.text_area(
            "Paste your CV here",
            height=250,
            placeholder="Copy and paste your CV content here...",
            key="cv_input"
        )
        
        if st.button("✓ Submit CV", use_container_width=True, key="submit_cv_text"):
            if cv_text and len(cv_text) > 100:
                st.session_state.cv_text = cv_text
                st.session_state.state = 'collecting_job'
                add_chat_message('user', f"[CV submitted - {len(cv_text)} characters]")
                add_chat_message('assistant', "Thanks for sharing your CV! 📋 Now, paste the job description you're interested in.")
                st.rerun()
            else:
                st.error("Please paste a complete CV (at least 100 characters)")
    
    with tab2:
        uploaded_file = st.file_uploader("Upload your CV (PDF)", type=['pdf'])
        
        if uploaded_file:
            st.info("📄 PDF uploaded! Processing...")
            try:
                # Try to use document processor
                from src.StateBasedTeamsAgent.document_processor import CVDocumentProcessor
                
                # Load endpoints directly from env (bypass config caching issues)
                doc_intel_endpoint = os.getenv("DOC_INTELLIGENCE_ENDPOINT", "")
                lang_endpoint = os.getenv("LANGUAGE_ENDPOINT", "")
                
                if not doc_intel_endpoint or not lang_endpoint:
                    st.error("PDF processing not configured. Please paste your CV text instead.")
                else:
                    processor = CVDocumentProcessor(
                        doc_intelligence_endpoint=doc_intel_endpoint,
                        language_endpoint=lang_endpoint
                    )
                    
                    # Get PDF bytes directly from uploaded file
                    pdf_bytes = uploaded_file.getvalue()
                    
                    # Process - pass bytes directly (not file path)
                    cv_text = asyncio.run(processor.process_cv_pdf(pdf_bytes))
                    
                    if cv_text:
                        st.session_state.cv_text = cv_text
                        st.session_state.state = 'collecting_job'
                        add_chat_message('user', "[CV uploaded as PDF]")
                        add_chat_message('assistant', "Thanks for uploading your CV! 📋 I've extracted the text and removed sensitive info. Now, paste the job description you're interested in.")
                        st.rerun()
                    else:
                        st.error("Couldn't extract text from PDF. Please try pasting the text instead.")
            except Exception as e:
                st.error(f"Error processing PDF: {e}. Please try pasting the text instead.")


def render_collecting_job():
    """Render job collection screen."""
    st.markdown("### 💼 Share the Job Description")
    
    # Show CV confirmation
    with st.expander("✓ CV received", expanded=False):
        st.text(st.session_state.cv_text[:500] + "..." if len(st.session_state.cv_text) > 500 else st.session_state.cv_text)
    
    job_text = st.text_area(
        "Paste the job description here",
        height=250,
        placeholder="Copy and paste the job posting...",
        key="job_input"
    )
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        if st.button("🔍 Analyze My Fit", use_container_width=True, type="primary"):
            if job_text and len(job_text) > 50:
                st.session_state.job_text = job_text
                st.session_state.state = 'analyzing'
                add_chat_message('user', f"[Job description submitted - {len(job_text)} characters]")
                st.rerun()
            else:
                st.error("Please paste a complete job description")
    
    with col2:
        if st.button("← Back", use_container_width=True):
            st.session_state.state = 'collecting_cv'
            st.session_state.cv_text = None
            st.rerun()


def render_analyzing():
    """Render analysis in progress."""
    st.markdown("### 🔍 Analyzing Your Fit...")
    
    with st.spinner("Running AI analysis... this takes about 15-20 seconds"):
        try:
            # Run analyzer
            analysis = asyncio.run(run_analyzer(
                st.session_state.cv_text,
                st.session_state.job_text
            ))
            
            st.session_state.analysis_text = analysis
            score, gaps = parse_analysis(analysis)
            st.session_state.score = score
            st.session_state.gaps = gaps
            st.session_state.initial_gaps = gaps.copy()
            
            # Decide next step
            if score >= 80 and len(gaps) <= 2:
                # Skip Q&A, go straight to recommendation
                st.session_state.state = 'generating_recommendation'
                add_chat_message('assistant', f"Great news! Your match score is {score}% - that's strong! Let me generate your personalized recommendation...")
            else:
                st.session_state.state = 'qna'
                add_chat_message('assistant', f"I've analyzed your profile. Match score: {score}%. I have a few questions to better understand your experience. Ready to chat?")
            
            st.rerun()
            
        except Exception as e:
            st.error(f"Analysis error: {e}")
            if st.button("Try Again"):
                st.rerun()


def render_qna():
    """Render Q&A conversation."""
    st.markdown("### 💬 Quick Chat")
    
    # Show score
    score = st.session_state.score
    if score >= 70:
        st.success(f"📊 Match Score: {score}% - Looking good!")
    elif score >= 50:
        st.warning(f"📊 Match Score: {score}% - Potential with some gaps")
    else:
        st.info(f"📊 Match Score: {score}% - Let's explore your fit")
    
    # Show remaining gaps
    if st.session_state.gaps:
        with st.expander(f"📋 Areas to discuss ({len(st.session_state.gaps)} remaining)"):
            for gap in st.session_state.gaps:
                st.markdown(f"• {gap}")
    
    # Chat interface
    st.markdown("---")
    
    # Render chat history
    for msg in st.session_state.qna_history:
        if msg.startswith("User:"):
            st.markdown(f"**You:** {msg[5:]}")
        else:
            st.markdown(f"**Buddy:** {msg}")
    
    # Input
    col1, col2 = st.columns([4, 1])
    
    with col1:
        user_input = st.text_input("Your message", key="qna_input", placeholder="Type your response...")
    
    with col2:
        send_clicked = st.button("Send", use_container_width=True)
    
    # Quick response buttons
    st.markdown("**Quick responses:**")
    btn_cols = st.columns(4)
    
    quick_responses = ["Yes, I have experience", "No, but I'm learning", "Tell me more", "I'm ready for my recommendation"]
    
    for i, response in enumerate(quick_responses):
        with btn_cols[i]:
            if st.button(response, key=f"quick_{i}", use_container_width=True):
                user_input = response
                send_clicked = True
    
    # Handle send
    if send_clicked and user_input:
        # Check for "done" intent
        done_phrases = ["done", "ready", "recommendation", "finish", "that's all", "skip"]
        if any(phrase in user_input.lower() for phrase in done_phrases):
            st.session_state.state = 'generating_recommendation'
            st.rerun()
        
        st.session_state.qna_history.append(f"User: {user_input}")
        
        with st.spinner("Thinking..."):
            try:
                response = asyncio.run(run_qna_agent(
                    user_input,
                    st.session_state.gaps,
                    st.session_state.analysis_text
                ))
                st.session_state.qna_history.append(response)
                
                # Check if Q&A should end (after 5 exchanges or explicit done)
                exchanges = len([h for h in st.session_state.qna_history if h.startswith("User:")])
                if exchanges >= 5:
                    st.session_state.state = 'generating_recommendation'
                    
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")
    
    # Done button
    st.markdown("---")
    if st.button("✅ I'm ready for my recommendation", use_container_width=True, type="primary"):
        st.session_state.state = 'generating_recommendation'
        st.rerun()


def render_generating_recommendation():
    """Generate and show recommendation."""
    st.markdown("### ✨ Generating Your Recommendation...")
    
    with st.spinner("Creating personalized advice... this takes about 20-30 seconds"):
        try:
            recommendation = asyncio.run(run_recommendation_agent(
                st.session_state.cv_text,
                st.session_state.job_text,
                st.session_state.analysis_text,
                st.session_state.qna_history
            ))
            
            st.session_state.recommendation = recommendation
            st.session_state.state = 'recommendation'
            st.rerun()
            
        except Exception as e:
            st.error(f"Error generating recommendation: {e}")
            if st.button("Try Again"):
                st.rerun()


def render_recommendation():
    """Render the final recommendation."""
    st.markdown("### 🎯 Your Personalized Recommendation")
    
    # Display recommendation
    st.markdown(f"""
    <div class="recommendation-card">
        {st.session_state.recommendation}
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown(st.session_state.recommendation)
    
    st.markdown("---")
    
    # Action buttons
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("📋 Try Another Job", use_container_width=True):
            # Keep CV, clear job
            st.session_state.job_text = None
            st.session_state.analysis_text = None
            st.session_state.gaps = []
            st.session_state.qna_history = []
            st.session_state.recommendation = None
            st.session_state.state = 'collecting_job'
            # Reset Q&A thread
            st.session_state.qna_thread = st.session_state.qna_agent.get_new_thread()
            st.rerun()
    
    with col2:
        if st.button("🔄 Start Fresh", use_container_width=True):
            # Clear everything
            for key in ['cv_text', 'job_text', 'analysis_text', 'gaps', 'initial_gaps', 
                       'qna_history', 'chat_history', 'recommendation', 'score']:
                st.session_state[key] = None if 'text' in key or key == 'recommendation' else ([] if 'history' in key or 'gaps' in key else 0)
            st.session_state.state = 'welcome'
            # Reset threads
            st.session_state.brain_thread = st.session_state.brain_agent.get_new_thread()
            st.session_state.qna_thread = st.session_state.qna_agent.get_new_thread()
            st.rerun()
    
    with col3:
        # Download as text
        st.download_button(
            "📥 Download Report",
            st.session_state.recommendation,
            file_name="application_buddy_recommendation.md",
            mime="text/markdown",
            use_container_width=True
        )


# ============================================================================
# Main App
# ============================================================================

def main():
    """Main app entry point."""
    init_session_state()
    initialize_agents()
    
    render_header()
    render_progress_bar()
    
    st.markdown("---")
    
    # Route to appropriate screen
    state = st.session_state.state
    
    if state == 'welcome':
        render_welcome()
    elif state == 'collecting_cv':
        render_collecting_cv()
    elif state == 'collecting_job':
        render_collecting_job()
    elif state == 'analyzing':
        render_analyzing()
    elif state == 'qna':
        render_qna()
    elif state == 'generating_recommendation':
        render_generating_recommendation()
    elif state == 'recommendation':
        render_recommendation()
    
    # Footer
    st.markdown("---")
    st.markdown("""
    <div style="text-align: center; color: #666; font-size: 0.8rem;">
        <p>🤖 Application Buddy - AI-powered career advice</p>
        <p>Remember: I'm an AI tool to help you think through applications, not a replacement for your own judgment!</p>
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
