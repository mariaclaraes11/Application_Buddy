# buddy/buddy/agentframework/agent.py

import os
from typing import Optional

from dotenv import load_dotenv

from src.config import Config
from src.agents.clean_orchestrator import CleanOrchestrator

load_dotenv()

# Load Buddy configuration (Azure AI Foundry, etc.)
config = Config()
orchestrator = CleanOrchestrator(config=config)

# Use the same CV source as main_mvp.py, but allow override via env
CV_FILE_PATH = os.getenv("BUDDY_CV_FILE", "text_examples/my_cv.txt")


def _read_cv_file() -> Optional[str]:
    """Read CV content from the same file used by main_mvp.py."""
    try:
        with open(CV_FILE_PATH, "r", encoding="utf-8") as f:
            content = f.read().strip()
            return content or None
    except FileNotFoundError:
        return None


def clear_conversation_history(conversation_id: str) -> None:
    """
    Required by agentsdk.agent; Buddy is stateless per Teams conversation for now.

    CleanOrchestrator itself does not keep per-conversation state that needs clearing,
    so this is a no-op. If you later add persistent state, plug it in here.
    """
    return None


async def send_message(input: str, conversation_id: Optional[str] = None) -> str:
    """
    Entry point used by the M365 Agents SDK adapter.

    For now:
    - The incoming Teams message text is treated as the job description.
    - The CV is loaded from text_examples/my_cv.txt (same as the CLI MVP).
    """
    cv_text = _read_cv_file()
    if not cv_text:
        return (
            "CV file is missing or empty. Make sure 'text_examples/my_cv.txt' exists "
            "and contains your CV, or set BUDDY_CV_FILE to another path."
        )

    result = await orchestrator.analyze(
        cv_text=cv_text,
        job_description=input,
    )
    return result