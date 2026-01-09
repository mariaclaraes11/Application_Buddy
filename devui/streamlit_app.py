"""
Application Buddy - Simple Chat UI
"""
import streamlit as st
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
import base64
import json
import os
from datetime import datetime, timezone

# Configuration
PROJECT_ENDPOINT = "https://ai-account-d2zwldhwlzgkg.services.ai.azure.com/api/projects/ai-project-application_buddy_env"
AGENT_NAME = "StateBasedTeamsAgent"
APPINSIGHTS_CONNECTION_STRING = "InstrumentationKey=71316b67-c79b-4f9d-bbde-16abece892fa;IngestionEndpoint=https://northcentralus-0.in.applicationinsights.azure.com/;LiveEndpoint=https://northcentralus.livediagnostics.monitor.azure.com/;ApplicationId=a0a2f9d5-e5e9-4c10-ae58-e6a2b2e00d74"

st.set_page_config(page_title="Application Buddy", page_icon="💼", layout="wide")

# Custom CSS for subtle feedback expander and wider sidebar
st.markdown("""
<style>
    /* Use sans-serif font throughout */
    html, body, [class*="css"] {
        font-family: 'Myriad Pro', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }
    /* Make sidebar wider */
    [data-testid="stSidebar"] {
        min-width: 350px;
        max-width: 400px;
    }
    /* Make feedback expander more subtle */
    [data-testid="stExpander"] {
        background-color: transparent;
        border: 1px solid rgba(128, 128, 128, 0.2);
    }
    [data-testid="stExpander"] summary {
        font-size: 0.85em;
        color: rgba(128, 128, 128, 0.7);
    }
    /* LinkedIn-style job cards */
    .job-card {
        display: flex;
        align-items: center;
        padding: 12px 16px;
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        background: white;
        margin-bottom: 8px;
        cursor: pointer;
        transition: background-color 0.2s;
    }
    .job-card:hover {
        background-color: #f5f5f5;
    }
    .job-card-icon {
        color: #666;
        margin-right: 12px;
        font-size: 18px;
    }
    .job-card-text {
        color: #333;
        font-size: 14px;
        font-weight: 500;
    }
</style>
""", unsafe_allow_html=True)

def save_feedback(rating: int, comment: str, message_index: int, message_content: str) -> bool:
    """Save feedback to Application Insights via direct HTTP POST."""
    try:
        import requests
        
        # Extract instrumentation key from connection string
        ikey = "71316b67-c79b-4f9d-bbde-16abece892fa"
        ingestion_endpoint = "https://northcentralus-0.in.applicationinsights.azure.com/v2/track"
        
        payload = [{
            "name": "AppEvents",
            "time": datetime.now(tz=timezone.utc).isoformat(),
            "iKey": ikey,
            "data": {
                "baseType": "EventData",
                "baseData": {
                    "name": "UserFeedback",
                    "properties": {
                        "rating": str(rating),
                        "comment": comment[:500] if comment else "",
                        "message_index": str(message_index),
                        "message_preview": message_content[:200] if message_content else ""
                    }
                }
            }
        }]
        
        response = requests.post(
            ingestion_endpoint,
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        
        return response.status_code in [200, 202]
    except Exception as e:
        st.error(f"Failed to save feedback: {e}")
        return False

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
if "feedback_given" not in st.session_state:
    st.session_state.feedback_given = set()  # Track which messages have feedback
if "quick_reply" not in st.session_state:
    st.session_state.quick_reply = None

def get_quick_reply_suggestion(last_message: str) -> tuple[str, str] | None:
    """Check if the last message suggests a quick reply. Returns (button_label, command) or None."""
    if not last_message:
        return None
    
    msg_lower = last_message.lower()
    
    # Pattern 1: "Type a number to view that section, or 'done' when finished"
    if "type a number to view" in msg_lower and "done" in msg_lower and "finished" in msg_lower:
        return ("✓ Done", "done")
    
    # Pattern 2: "(Type 'done' anytime for your recommendation)"
    if "done" in msg_lower and "recommendation" in msg_lower:
        return ("✓ Done - Get Recommendation", "done")
    
    # Pattern 3: "Just say 'go' and I'll dive in" (handle curly quotes too)
    if "go" in msg_lower and "dive in" in msg_lower:
        return ("🚀 Go", "go")
    
    return None

def send_message(msg: str):
    """Send a message to the agent."""
    st.session_state.messages.append({"role": "user", "content": msg})
    try:
        response = openai_client.responses.create(
            input=[{"type": "message", "role": "user", "content": msg}],
            extra_body={"agent": {"name": agent.name, "type": "agent_reference"}},
        )
        st.session_state.messages.append({"role": "assistant", "content": response.output_text})
    except Exception as e:
        st.session_state.messages.append({"role": "assistant", "content": f"Error: {e}"})

# Chat history with inline feedback
for i, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        
        # Add feedback widget after assistant messages
        if msg["role"] == "assistant":
            # Check if feedback already given for this message
            if i in st.session_state.feedback_given:
                st.caption("Thanks for your feedback")
            else:
                # Use columns to make the expander narrower
                col1, col2 = st.columns([1, 3])
                with col1:
                    with st.expander("How did I do?", expanded=False):
                        rating = st.feedback("stars", key=f"rating_{i}")
                        comment = st.text_area(
                            "More information (optional)", 
                            key=f"comment_{i}",
                            placeholder="Tell us more...",
                            height=68
                        )
                        
                        if st.button("Send", key=f"send_{i}"):
                            if rating is not None:
                                star_rating = rating + 1  # Convert 0-4 to 1-5
                                if save_feedback(star_rating, comment, i, msg["content"]):
                                    st.session_state.feedback_given.add(i)
                                    st.rerun()
                            else:
                                st.warning("Please select a rating")

# Quick reply button (appears after chat history, before input)
if st.session_state.messages:
    last_assistant_msg = next(
        (m["content"] for m in reversed(st.session_state.messages) if m["role"] == "assistant"), 
        None
    )
    suggestion = get_quick_reply_suggestion(last_assistant_msg)
    if suggestion:
        label, command = suggestion
        if st.button(label, type="primary", use_container_width=False):
            send_message(command)
            st.rerun()

# Sidebar for file upload and controls
with st.sidebar:
    # Conversation controls at top
    col1, col2 = st.columns(2)
    with col1:
        if st.button("↶ New", use_container_width=True):
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
            st.session_state.feedback_given = set()
            st.rerun()
    with col2:
        if st.button("⟳ Reset Profile", use_container_width=True):
            try:
                response = openai_client.responses.create(
                    input=[{"type": "message", "role": "user", "content": "reset profile"}],
                    extra_body={"agent": {"name": agent.name, "type": "agent_reference"}},
                )
                st.session_state.messages.append({"role": "assistant", "content": response.output_text})
            except Exception as e:
                st.error(f"Failed to reset profile: {e}")
            st.rerun()
    
    st.markdown("---")
    st.markdown("### + Attach CV")
    
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
        if st.button("Attach new CV"):
            st.session_state.file_already_sent = False
            st.session_state.pending_file = None
            st.session_state.uploader_key += 1
            st.rerun()
    
    # Saved Jobs section
    st.markdown("---")
    # Bookmark icon as inline SVG (small, grey)
    bookmark_svg = '''<svg width="14" height="18" viewBox="0 0 24 32" fill="#888" xmlns="http://www.w3.org/2000/svg" style="vertical-align: middle; margin-right: 6px;"><path d="M0 0h24v32l-12-8-12 8V0z"/></svg>'''
    st.markdown(f"### {bookmark_svg} Saved Jobs", unsafe_allow_html=True)
    
    # Initialize saved jobs in session state
    if "saved_jobs" not in st.session_state:
        st.session_state.saved_jobs = []
    
    # Sync button
    if st.button("Sync from LinkedIn", help="Opens browser to scrape your saved jobs"):
        with st.spinner("Opening LinkedIn..."):
            try:
                from linkedin_savedjobs import scrape_jobs_sync
                jobs = scrape_jobs_sync(max_jobs=10)
                st.session_state.saved_jobs = jobs
                st.success(f"Synced {len(jobs)} jobs!")
            except Exception as e:
                st.error(f"Error: {e}")
    
    # Display job cards
    if st.session_state.saved_jobs:
        for i, job in enumerate(st.session_state.saved_jobs):
            # Create a container that looks like LinkedIn job card
            with st.container():
                # Use HTML for cleaner styling
                card_html = f"""
                <div style="padding: 12px 0; border-bottom: 1px solid #eee; cursor: pointer;">
                    <div style="font-weight: 600; font-size: 14px; color: #000;">{job['title']}</div>
                    <div style="font-size: 13px; color: #666;">{job['company']}</div>
                    <div style="font-size: 12px; color: #888;">{job.get('location', '')}</div>
                </div>
                """
                st.markdown(card_html, unsafe_allow_html=True)
                
                if st.button("Select", key=f"job_{i}", type="secondary"):
                    # Fetch full description when clicked
                    with st.spinner("Loading job details..."):
                        try:
                            from linkedin_savedjobs import fetch_job_description_sync
                            full_desc = fetch_job_description_sync(job.get('url', ''))
                            if full_desc:
                                job['description'] = full_desc
                        except Exception as e:
                            st.warning(f"Could not fetch full description: {e}")
                    
                    # Send job to chat
                    job_text = f"**{job['title']}** at **{job['company']}**\n\nLocation: {job.get('location', 'N/A')}\n\n{job['description']}"
                    st.session_state.pending_job = job_text
                    st.rerun()
    else:
        st.caption("Click Sync to load your saved jobs")

# Check if a job was selected from sidebar
if "pending_job" in st.session_state and st.session_state.pending_job:
    job_text = st.session_state.pending_job
    st.session_state.pending_job = None
    
    # Send to agent
    st.session_state.messages.append({"role": "user", "content": f"📋 Job from LinkedIn:\n\n{job_text[:500]}..."})
    with st.chat_message("user"):
        st.markdown(f"📋 Job loaded from LinkedIn")
    
    with st.chat_message("assistant"):
        with st.spinner("..."):
            try:
                response = openai_client.responses.create(
                    input=[{"type": "message", "role": "user", "content": job_text}],
                    extra_body={"agent": {"name": agent.name, "type": "agent_reference"}},
                )
                reply = response.output_text
                st.markdown(reply)
                st.session_state.messages.append({"role": "assistant", "content": reply})
            except Exception as e:
                st.error(str(e))
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
