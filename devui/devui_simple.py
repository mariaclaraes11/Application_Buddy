"""
Simple DevUI Launcher for Application Buddy
Uses your existing workflow with zero code duplication.
"""
import os
from dotenv import load_dotenv
from agent_framework.devui import serve
from workflows.main_workflow_v2 import devui_workflow

def main():
    """Launch DevUI - dead simple version!"""
    print("🚀 Application Buddy DevUI")
    
    load_dotenv()
    if not os.getenv("AZURE_AI_FOUNDRY_ENDPOINT"):
        print("❌ Set up your .env file first")
        return
    
    print("✅ Loading your workflow...")
    workflow = devui_workflow()
    
    print("🌐 Starting DevUI at http://localhost:8080")
    serve(entities=[workflow], port=8080, auto_open=True)

if __name__ == "__main__":
    main()