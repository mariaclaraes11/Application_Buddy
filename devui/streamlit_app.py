"""
Application Buddy - Simple Chat UI
"""
import streamlit as st
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
import base64

# Configuration
PROJECT_ENDPOINT = "https://ai-account-d2zwldhwlzgkg.services.ai.azure.com/api/projects/ai-project-application_buddy_env"
AGENT_NAME = "StateBasedTeamsAgent"

st.set_page_config(page_title="Application Buddy", page_icon="💼", layout="wide")

# Minimal CSS - hide file uploader cruft, make + button tiny
st.markdown("""
<style>
/* Hide default uploader text completely */
.stFileUploader > div > div {display: none !important;}
.stFileUploader label {display: none !important;}
.stFileUploader [data-testid="stFileUploaderDropzone"] {
    background: transparent !important;
    border: none !important;
    padding: 0 !important;
    min-height: 0 !important;
}
.stFileUploader [data-testid="stFileUploaderDropzone"] > div {display: none !important;}
.stFileUploader [data-testid="stFileUploaderDropzone"] > button {display: none !important;}
.stFileUploader section > button {
    background: transparent !important;
    border: none !important;
    color: #666 !important;
    font-size: 1.5rem !important;
    padding: 0.2rem 0.5rem !important;
    min-height: 0 !important;
    cursor: pointer !important;
}
.stFileUploader section > button:hover {color: #333 !important;}
/* File ready indicator */
.file-ready {
    font-size: 0.75rem;
    color: #28a745;
    padding: 2px 6px;
    background: #e8f5e9;
    border-radius: 10px;
    display: inline-block;
}
</style>
""", unsafe_allow_html=True)

@st.cache_resource
def get_clients():
    credential = DefaultAzureCredential()
    project_client = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=credential)
    openai_client = project_client.get_openai_client()
    agent = project_client.agents.get(agent_name=AGENT_NAME)
    return openai_client, agent

openai_client, agent = get_clients()

st.title("Application Buddy")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending_file" not in st.session_state:
    st.session_state.pending_file = None

# New conversation
if st.button("🔄 New Conversation"):
    try:
        openai_client.responses.create(
            input=[{"type": "message", "role": "user", "content": "reset"}],
            extra_body={"agent": {"name": agent.name, "type": "agent_reference"}},
        )
    except: pass
    st.session_state.messages = []
    st.session_state.pending_file = None
    st.rerun()

# Chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# File indicator if pending
if st.session_state.pending_file:
    col_a, col_b = st.columns([10, 1])
    with col_a:
        st.markdown(f'<span class="file-ready">📎 {st.session_state.pending_file["name"]}</span>', unsafe_allow_html=True)
    with col_b:
        if st.button("✕", key="clear"):
            st.session_state.pending_file = None
            st.rerun()

# Input row: chat input takes most space, tiny + on the right
prompt = st.chat_input("Type a message...")

# Tiny file uploader in sidebar (hidden by CSS magic)
with st.sidebar:
    st.markdown("### 📎 Attach CV")
    uploaded = st.file_uploader("Upload", type=["pdf"], label_visibility="collapsed")
    if uploaded:
        st.session_state.pending_file = {
            "name": uploaded.name,
            "data": base64.b64encode(uploaded.getvalue()).decode('utf-8')
        }
        st.success(f"✓ {uploaded.name}")

# Handle send
if prompt:
    msg_to_send = prompt
    display_msg = prompt
    
    if st.session_state.pending_file:
        pf = st.session_state.pending_file
        display_msg = f"📎 {pf['name']}\n\n{prompt}"
        msg_to_send = f"[PDF_ATTACHMENT:{pf['name']}:{pf['data']}]\n\n{prompt}"
        st.session_state.pending_file = None
    
    st.session_state.messages.append({"role": "user", "content": display_msg})
    with st.chat_message("user"):
        st.markdown(display_msg)
    
    with st.chat_message("assistant"):
        with st.spinner("..."):
            try:
                response = openai_client.responses.create(
                    input=[{"type": "message", "role": "user", "content": msg_to_send}],
                    extra_body={"agent": {"name": agent.name, "type": "agent_reference"}},
                )
                reply = response.output_text
                st.markdown(reply)
                st.session_state.messages.append({"role": "assistant", "content": reply})
            except Exception as e:
                st.error(str(e))
    st.rerun()
