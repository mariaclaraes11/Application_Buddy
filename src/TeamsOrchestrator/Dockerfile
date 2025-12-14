FROM python:3.11-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the agent code
COPY . .

# Apply SDK patches for HITL support
# These fix bugs in azure-ai-agentserver and agent_framework SDKs
RUN cp patched_sdk/agent_framework_output_streaming_converter.py \
       /usr/local/lib/python3.11/site-packages/azure/ai/agentserver/agentframework/models/agent_framework_output_streaming_converter.py && \
    cp patched_sdk/agent_framework_input_converters.py \
       /usr/local/lib/python3.11/site-packages/azure/ai/agentserver/agentframework/models/agent_framework_input_converters.py && \
    cp patched_sdk/_agent.py \
       /usr/local/lib/python3.11/site-packages/agent_framework/_workflows/_agent.py && \
    cp patched_sdk/_workflow.py \
       /usr/local/lib/python3.11/site-packages/agent_framework/_workflows/_workflow.py

# Set the entry point
CMD ["python", "main.py"]