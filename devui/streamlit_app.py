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

@st.cache_resource
def get_clients():
    credential = DefaultAzureCredential()
    project_client = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=credential)
    openai_client = project_client.get_openai_client()
    agent = project_client.agents.get(agent_name=AGENT_NAME)
    return openai_client, agent

openai_client, agent = get_clients()

st.title("Application Buddy")

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending_file" not in st.session_state:
    st.session_state.pending_file = None
if "file_already_sent" not in st.session_state:
    st.session_state.file_already_sent = False
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

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
    st.session_state.file_already_sent = False
    st.session_state.uploader_key += 1
    st.rerun()

# Chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Sidebar for file upload
with st.sidebar:
    st.markdown("### 📎 Attach CV")
    
    # File uploader with dynamic key
    uploaded = st.file_uploader(
        "Browse files", 
        type=["pdf"], 
        key=f"uploader_{st.session_state.uploader_key}"
    )
    
    # Only set pending_file if:
    # 1. A file is uploaded
    # 2. We haven't already sent this file
    # 3. The file name is different (new file)
    if uploaded and not st.session_state.file_already_sent:
        new_file = {
            "name": uploaded.name,
            "data": base64.b64encode(uploaded.getvalue()).decode('utf-8')
        }
        # Check if it's actually a new file
        if st.session_state.pending_file is None or st.session_state.pending_file["name"] != uploaded.name:
            st.session_state.pending_file = new_file
    
    # Show status
    if st.session_state.pending_file and not st.session_state.file_already_sent:
        st.success(f"✓ {st.session_state.pending_file['name']}")
        st.caption("Will be sent with your next message")
        if st.button("✕ Remove", key="clear_file"):
            st.session_state.pending_file = None
            st.session_state.uploader_key += 1
            st.rerun()
    elif st.session_state.file_already_sent:
        st.info("CV already sent ✓")
        if st.button("📎 Attach new CV"):
            st.session_state.file_already_sent = False
            st.session_state.pending_file = None
            st.session_state.uploader_key += 1
            st.rerun()

# Chat input
prompt = st.chat_input("Type a message...")

# Handle send
if prompt:
    msg_to_send = prompt
    display_msg = prompt
    
    # Only attach PDF if pending AND not already sent
    if st.session_state.pending_file and not st.session_state.file_already_sent:
        pf = st.session_state.pending_file
        display_msg = f"📎 {pf['name']}\n\n{prompt}"
        msg_to_send = f"[PDF_ATTACHMENT:{pf['name']}:{pf['data']}]\n\n{prompt}"
        st.session_state.file_already_sent = True  # Mark as sent
    
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
