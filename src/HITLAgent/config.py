import os
from typing import Optional
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# Load .env file before Config is instantiated
load_dotenv()


class Config(BaseSettings):
    """Configuration for Azure AI Foundry and Agent Framework"""
    
    # Azure AI Foundry Configuration
    # Accepts both AZURE_AI_PROJECT_ENDPOINT (from agent.yaml) and AZURE_AI_FOUNDRY_ENDPOINT
    azure_ai_foundry_endpoint: str = ""
    # Accepts both AZURE_AI_MODEL_DEPLOYMENT_NAME (from agent.yaml) and MODEL_DEPLOYMENT_NAME
    model_deployment_name: str = ""
    
    # Agent Framework Azure integration
    chat_completion_deployment: str = ""  # Same as model_deployment_name typically
    api_version: str = "2024-02-01"
    endpoint_url: str = ""  # Will be derived from azure_ai_foundry_endpoint
    
    # Optional Azure configuration
    azure_subscription_id: Optional[str] = None
    azure_resource_group: Optional[str] = None
    
    # Workflow settings
    max_workflow_turns: int = 15
    similarity_threshold: float = 0.7
    
    def model_post_init(self, __context):
        """Set derived values after initialization"""
        # If azure_ai_foundry_endpoint not set, try various endpoint env vars
        if not self.azure_ai_foundry_endpoint:
            self.azure_ai_foundry_endpoint = (
                os.getenv("AZURE_AI_PROJECT_ENDPOINT") or 
                os.getenv("AZURE_AI_FOUNDRY_ENDPOINT") or
                os.getenv("AZURE_OPENAI_ENDPOINT", "")  # From agent.yaml
            )
        
        # If model_deployment_name not set, try AZURE_AI_MODEL_DEPLOYMENT_NAME, else default to gpt-4o
        if not self.model_deployment_name:
            self.model_deployment_name = os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME") or os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-4o")
        
        # Sync chat_completion_deployment with model_deployment_name
        if not self.chat_completion_deployment:
            self.chat_completion_deployment = self.model_deployment_name
        
        if not self.endpoint_url and self.azure_ai_foundry_endpoint:
            # Extract base endpoint for Agent Framework
            self.endpoint_url = self.azure_ai_foundry_endpoint.replace('/api/projects/', '/').replace('/workspace', '').replace('/project', '')
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"