"""
Application Buddy - HTTP Chat UI
Professional Teams-like interface that calls the deployed Foundry agent via SDK.

Session Management:
- Each Streamlit browser session gets a unique session_id (uuid4)
- Session ID is prepended to messages as [session:xxx] for multi-user support
- The deployed agent extracts this prefix to maintain separate conversation states
"""
import streamlit as st
import os
import json
import uuid
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

# Load environment variables
env_path = "/home/clara/projects/application_buddy/Application_Buddy/.env"
loaded = load_dotenv(env_path, override=True)
print(f"Loaded .env: {loaded}, path exists: {os.path.exists(env_path)}")

# Configuration
PROJECT_ENDPOINT = os.getenv("AZURE_EXISTING_AIPROJECT_ENDPOINT", "").rstrip("/")
# AZURE_EXISTING_AGENT_ID format is "AgentName:version" - we need just the name
AGENT_ID = os.getenv("AZURE_EXISTING_AGENT_ID", "StateBasedTeamsAgent:16")
AGENT_NAME = AGENT_ID.split(":")[0] if ":" in AGENT_ID else AGENT_ID

print(f"PROJECT_ENDPOINT: {PROJECT_ENDPOINT}")
print(f"AGENT_NAME: {AGENT_NAME}")

# ============================================================================
# Page Config & Professional CSS (Microsoft Teams-inspired)
# ============================================================================

st.set_page_config(
    page_title="Application Buddy",
    page_icon="briefcase",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# Professional Microsoft-style CSS
st.markdown("""
<style>
    /* Main container - clean white background */
    .main {
        background-color: #f5f5f5;
    }
    
    /* Header styling */
    .app-header {
        background: linear-gradient(135deg, #0078d4 0%, #106ebe 100%);
        color: white;
        padding: 1.5rem 2rem;
        border-radius: 8px;
        margin-bottom: 1.5rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }
    
    .app-header h1 {
        margin: 0;
        font-size: 1.75rem;
        font-weight: 600;
    }
    
    .app-header p {
        margin: 0.5rem 0 0 0;
        opacity: 0.9;
        font-size: 0.95rem;
    }
    
    /* Chat container */
    .chat-container {
        background-color: white;
        border-radius: 8px;
        padding: 1rem;
        margin-bottom: 1rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        max-height: 500px;
        overflow-y: auto;
    }
    
    /* Message styling */
    .user-message {
        background-color: #0078d4;
        color: white;
        padding: 0.75rem 1rem;
        border-radius: 12px 12px 4px 12px;
        margin: 0.5rem 0;
        margin-left: 20%;
        text-align: left;
    }
    
    .assistant-message {
        background-color: #f0f0f0;
        color: #333;
        padding: 0.75rem 1rem;
        border-radius: 12px 12px 12px 4px;
        margin: 0.5rem 0;
        margin-right: 20%;
    }
    
    /* Input area styling */
    .stTextArea textarea {
        border-radius: 8px;
        border: 1px solid #d0d0d0;
    }
    
    .stTextArea textarea:focus {
        border-color: #0078d4;
        box-shadow: 0 0 0 2px rgba(0,120,212,0.2);
    }
    
    /* Button styling */
    .stButton > button {
        background-color: #0078d4;
        color: white;
        border: none;
        border-radius: 6px;
        padding: 0.5rem 1.5rem;
        font-weight: 500;
    }
    
    .stButton > button:hover {
        background-color: #106ebe;
    }
    
    /* File uploader */
    .stFileUploader {
        border: 2px dashed #d0d0d0;
        border-radius: 8px;
        padding: 1rem;
    }
    
    /* Status indicators */
    .status-connected {
        color: #107c10;
        font-size: 0.85rem;
    }
    
    .status-error {
        color: #d13438;
        font-size: 0.85rem;
    }
    
    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)


# ============================================================================
# Azure Authentication & Agent Client
# ============================================================================

@st.cache_resource
def get_clients():
    """Get AIProjectClient and OpenAI client for calling deployed agents."""
    credential = DefaultAzureCredential()
    project_client = AIProjectClient(
        endpoint=PROJECT_ENDPOINT,
        credential=credential
    )
    openai_client = project_client.get_openai_client()
    return project_client, openai_client


def call_agent_sync(messages: list[dict], previous_response_id: str = None) -> tuple[str, str]:
    """
    Call the deployed Foundry agent via OpenAI responses API.
    
    Args:
        messages: List of message dicts with 'role' and 'content'
        previous_response_id: Optional previous response ID for conversation continuity
        
    Returns:
        Tuple of (response_text, response_id)
    """
    project_client, openai_client = get_clients()
    
    # Get the agent
    agent = project_client.agents.get(agent_name=AGENT_NAME)
    print(f"Retrieved agent: {agent.name}")
    
    # Build input from messages
    input_messages = [{"role": msg["role"], "content": msg["content"]} for msg in messages]
    
    # Call agent via OpenAI responses API
    kwargs = {
        "input": input_messages,
        "extra_body": {"agent": {"name": agent.name, "type": "agent_reference"}}
    }
    
    if previous_response_id:
        kwargs["previous_response_id"] = previous_response_id
    
    response = openai_client.responses.create(**kwargs)
    
    # Extract response text
    response_text = response.output_text
    new_response_id = response.id
    
    return response_text, new_response_id


# ============================================================================
# Session State Initialization
# ============================================================================

def init_session_state():
    """Initialize session state variables."""
    if "messages" not in st.session_state:
        st.session_state.messages = []
    
    if "thread_id" not in st.session_state:
        st.session_state.thread_id = None
    
    if "cv_uploaded" not in st.session_state:
        st.session_state.cv_uploaded = False
    
    if "cv_text" not in st.session_state:
        st.session_state.cv_text = None
    
    # Unique session ID for this browser session (multi-user support)
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())[:8]
        print(f"🔑 New session created: {st.session_state.session_id}")


# ============================================================================
# Document Processing
# ============================================================================

def extract_text_from_file(uploaded_file) -> str:
    """Extract text from uploaded file."""
    if uploaded_file is None:
        return None
    
    file_type = uploaded_file.type
    
    if file_type == "text/plain":
        return uploaded_file.read().decode("utf-8")
    
    elif file_type == "application/pdf":
        # Use Document Intelligence for PDF
        try:
            from azure.ai.documentintelligence import DocumentIntelligenceClient
            from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
            
            doc_intel_endpoint = os.getenv("DOC_INTELLIGENCE_ENDPOINT")
            if not doc_intel_endpoint:
                st.error("Document Intelligence endpoint not configured")
                return None
            
            credential = DefaultAzureCredential()
            client = DocumentIntelligenceClient(
                endpoint=doc_intel_endpoint,
                credential=credential
            )
            
            file_bytes = uploaded_file.read()
            poller = client.begin_analyze_document(
                "prebuilt-read",
                analyze_request=file_bytes,
                content_type="application/pdf"
            )
            result = poller.result()
            
            return result.content
            
        except Exception as e:
            st.error(f"Error processing PDF: {str(e)}")
            return None
    
    else:
        st.error(f"Unsupported file type: {file_type}")
        return None


# ============================================================================
# UI Components
# ============================================================================

def render_header():
    """Render the application header."""
    st.markdown("""
    <div class="app-header">
        <h1>Application Buddy</h1>
        <p>Your AI-powered career assistant for CV analysis and job matching</p>
    </div>
    """, unsafe_allow_html=True)


def render_chat_messages():
    """Render chat message history."""
    for msg in st.session_state.messages:
        if msg["role"] == "user":
            st.markdown(f'<div class="user-message">{msg["content"]}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="assistant-message">{msg["content"]}</div>', unsafe_allow_html=True)


def render_sidebar():
    """Render sidebar with file upload and settings."""
    with st.sidebar:
        st.markdown("### Upload Documents")
        
        # CV Upload
        cv_file = st.file_uploader(
            "Upload your CV",
            type=["pdf", "txt"],
            key="cv_upload"
        )
        
        if cv_file and not st.session_state.cv_uploaded:
            with st.spinner("Processing CV..."):
                cv_text = extract_text_from_file(cv_file)
                if cv_text:
                    st.session_state.cv_text = cv_text
                    st.session_state.cv_uploaded = True
                    st.success("CV uploaded successfully")
        
        if st.session_state.cv_uploaded:
            st.markdown("CV: Uploaded")
        
        st.markdown("---")
        
        # New conversation button
        if st.button("New Conversation", use_container_width=True):
            st.session_state.messages = []
            st.session_state.thread_id = None
            st.session_state.cv_uploaded = False
            st.session_state.cv_text = None
            # Generate new session ID for fresh agent state
            st.session_state.session_id = str(uuid.uuid4())[:8]
            print(f"🔄 Session reset, new ID: {st.session_state.session_id}")
            st.rerun()
        
        st.markdown("---")
        
        # Connection status
        st.markdown("### Status")
        if PROJECT_ENDPOINT and AGENT_NAME:
            st.markdown(f'<p class="status-connected">Connected to {AGENT_NAME}</p>', unsafe_allow_html=True)
            st.markdown(f'<p style="font-size: 0.75rem; color: #666;">Session: {st.session_state.get("session_id", "unknown")}</p>', unsafe_allow_html=True)
        else:
            st.markdown('<p class="status-error">Agent not configured</p>', unsafe_allow_html=True)


# ============================================================================
# Main Application
# ============================================================================

def main():
    """Main application entry point."""
    init_session_state()
    
    render_header()
    render_sidebar()
    
    # Chat interface
    st.markdown('<div class="chat-container">', unsafe_allow_html=True)
    render_chat_messages()
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Input area using form to handle state properly
    with st.form(key="chat_form", clear_on_submit=True):
        col1, col2 = st.columns([5, 1])
        
        with col1:
            user_input = st.text_area(
                "Message",
                key="user_input",
                placeholder="Type your message here...",
                height=80,
                label_visibility="collapsed"
            )
        
        with col2:
            send_button = st.form_submit_button("Send", use_container_width=True)
    
    # Handle message send
    if send_button and user_input.strip():
        # Store the clean user message for display
        clean_message = user_input.strip()
        
        # Add user message to history (clean version for display)
        st.session_state.messages.append({
            "role": "user",
            "content": clean_message
        })
        
        # Call agent - prepend session ID for multi-user state management
        # Format: [session:xxxxxxxx] User's actual message
        session_id = st.session_state.session_id
        tagged_message = f"[session:{session_id}] {clean_message}"
        
        with st.spinner("Thinking..."):
            try:
                # Send tagged message - agent extracts session ID for state keying
                api_messages = [{"role": "user", "content": tagged_message}]
                
                # Debug: print what we're sending
                print(f"Calling agent: {AGENT_NAME}")
                print(f"Session ID: {session_id}")
                print(f"Tagged message: {tagged_message[:100]}...")
                print(f"Previous response ID: {st.session_state.thread_id}")
                
                # Call agent using SDK
                response_text, response_id = call_agent_sync(
                    api_messages, st.session_state.thread_id
                )
                
                print(f"Response: {response_text}")
                print(f"New response ID: {response_id}")
                
                st.session_state.thread_id = response_id
                
                # Add assistant response to history
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": response_text
                })
                
            except Exception as e:
                import traceback
                traceback.print_exc()
                st.error(f"Error: {str(e)}")
                # Remove the failed user message
                st.session_state.messages.pop()
        
        # Rerun to update UI
        st.rerun()


if __name__ == "__main__":
    main()
