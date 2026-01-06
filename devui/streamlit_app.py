"""
Application Buddy - Simple Chat UI
Bare-bones Streamlit chat that calls the deployed Foundry agent.
Based on the official Azure AI Projects SDK sample.
"""
import streamlit as st
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

# Configuration - hardcoded for simplicity
PROJECT_ENDPOINT = "https://ai-account-d2zwldhwlzgkg.services.ai.azure.com/api/projects/ai-project-application_buddy_env"
AGENT_NAME = "StateBasedTeamsAgent"

st.title("Application Buddy")

# Initialize Azure clients (cached)
@st.cache_resource
def get_clients():
    """Get AIProjectClient and OpenAI client."""
    credential = DefaultAzureCredential()
    project_client = AIProjectClient(
        endpoint=PROJECT_ENDPOINT,
        credential=credential,
    )
    agent = project_client.agents.get(agent_name=AGENT_NAME)
    openai_client = project_client.get_openai_client()
    return agent, openai_client

# Get clients
agent, openai_client = get_clients()
st.caption(f"Connected to: {agent.name}")

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat messages from history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Accept user input
if prompt := st.chat_input("Type your message..."):
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    # Display user message
    with st.chat_message("user"):
        st.markdown(prompt)

    # Get response from agent
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            # Call agent - try with type: message for proper parsing
            response = openai_client.responses.create(
                input=[{"type": "message", "role": "user", "content": prompt}],
                extra_body={"agent": {"name": agent.name, "type": "agent_reference"}},
            )
            response_text = response.output_text
        
        st.markdown(response_text)
    
    # Add assistant response to chat history
    st.session_state.messages.append({"role": "assistant", "content": response_text})
