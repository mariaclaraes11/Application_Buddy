import os
from typing import Optional
from pydantic_settings import BaseSettings


class Config(BaseSettings):
    """Configuration for Azure AI Foundry and Agent Framework"""
    
    # Azure AI Foundry Configuration - required
    azure_ai_foundry_endpoint: str
    model_deployment_name: str = "gpt-4o"
    
    # Agent Framework Azure integration
    chat_completion_deployment: str = "gpt-4o"  # Same as model_deployment_name typically
    api_version: str = "2024-02-01"
    endpoint_url: str = ""  # Will be derived from azure_ai_foundry_endpoint
    
    # Optional Azure configuration
    azure_subscription_id: Optional[str] = None
    azure_resource_group: Optional[str] = None
    
    # Workflow settings
    max_workflow_turns: int = 15
    similarity_threshold: float = 0.7
    
    def __post_init__(self):
        """Set derived values after initialization"""
        if not self.endpoint_url and self.azure_ai_foundry_endpoint:
            # Extract base endpoint for Agent Framework
            self.endpoint_url = self.azure_ai_foundry_endpoint.replace('/api/projects/', '/').replace('/workspace', '').replace('/project', '')
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"