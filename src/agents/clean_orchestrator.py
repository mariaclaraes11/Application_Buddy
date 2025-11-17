"""
Clean Orchestrator - Local Agents Version

This orchestrator does ONE thing well:
- Takes CV + Job Description  
- Runs analysis → optional Q&A → recommendation
- Returns complete results

Uses LOCAL Agent Framework agents (no Azure dependencies)
"""

import asyncio
import json
import logging
from typing import Dict, Any

from agent_framework import ChatAgent
from agent_framework.azure import AzureOpenAIChatClient
from azure.identity import DefaultAzureCredential  # Synchronous version

from ..config import Config
from .agent_definitions import AgentDefinitions

logger = logging.getLogger(__name__)


class CleanOrchestrator:
    """
    Simple, clean orchestrator with local agents.
    Does ONE thing: CV + Job → Analysis → Optional Q&A → Recommendation
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.agents = {}
    
    async def _setup_agents(self) -> Dict[str, ChatAgent]:
        """Create local agents using Agent Framework."""
        if self.agents:
            return self.agents
            
        logger.info("Setting up local agents...")
        
        # Get agent definitions
        agents_config = AgentDefinitions.get_all_agents()
        
        # Extract Azure endpoint from Foundry endpoint
        # From: https://smart-application-buddy.services.ai.azure.com/api/projects/firstProject
        # To: https://smart-application-buddy.services.ai.azure.com/
        azure_endpoint = self.config.azure_ai_foundry_endpoint.split('/api/projects/')[0]
        
        # Create async credential
        credential = DefaultAzureCredential()
        
        # Create local agents
        for agent_type, config in agents_config.items():
            logger.info(f"Creating local {config['name']} agent")
            
            # Create Azure OpenAI chat client pointing to your deployment
            chat_client = AzureOpenAIChatClient(
                deployment_name=self.config.model_deployment_name,
                endpoint=azure_endpoint,
                api_version=self.config.api_version,
                credential=credential,
            )
            
            # Create agent with instructions
            agent = ChatAgent(
                name=config["name"],
                chat_client=chat_client,
                instructions=config["instructions"]
            )
            
            self.agents[agent_type] = agent
        
        logger.info(f"Created {len(self.agents)} local agents")
        return self.agents
    
    def _get_agent(self, agent_type: str) -> ChatAgent:
        """Get a local agent by type."""
        if agent_type not in self.agents:
            raise ValueError(f"Agent type '{agent_type}' not found. Available: {list(self.agents.keys())}")
        return self.agents[agent_type]
    
    def _should_run_qna(self, analysis_text: str) -> bool:
        """Decide if Q&A is needed based on analysis."""
        try:
            # Parse JSON analysis
            if '{' in analysis_text and '}' in analysis_text:
                json_start = analysis_text.find('{')
                json_end = analysis_text.rfind('}') + 1
                json_str = analysis_text[json_start:json_end]
                
                try:
                    analysis_data = json.loads(json_str)
                    gaps = analysis_data.get('gaps', [])
                    must_have_gaps = [gap for gap in gaps if gap.get('requirement_type') == 'must']
                    score = analysis_data.get('preliminary_score', 0)
                    
                    # Simple decision logic
                    if len(must_have_gaps) > 0:
                        logger.info(f"Missing must-have requirements - Q&A needed")
                        return True
                    elif score < 75:
                        logger.info(f"Low score ({score}) - Q&A needed")
                        return True
                    else:
                        logger.info(f"Good score ({score}) - skipping Q&A")
                        return False
                        
                except json.JSONDecodeError:
                    pass
            
            # Fallback: default to Q&A if can't parse
            logger.info("Could not parse analysis - defaulting to Q&A")
            return True
            
        except Exception as e:
            logger.warning(f"Error in decision logic: {e} - defaulting to Q&A")
            return True

    async def analyze(self, cv_text: str, job_description: str) -> str:
        """
        Main method: CV + Job → Complete analysis report
        """
        try:
            # Setup agents
            await self._setup_agents()
            
            # Step 1: Analysis
            logger.info(" Running analysis...")
            analyzer = self._get_agent("analyzer")
            analysis_result = await analyzer.run(f"""**CANDIDATE CV:**
{cv_text}

**JOB DESCRIPTION:**
{job_description}""")
            analysis_text = analysis_result.messages[-1].text
            
            # Step 2: Decide on Q&A
            needs_qna = self._should_run_qna(analysis_text)
            
            # Step 3: Optional Q&A
            if needs_qna:
                logger.info(" Running Q&A...")
                qna_agent = self._get_agent("qna")
                qna_result = await qna_agent.run(f"""**ANALYSIS:**
{analysis_text}

**CV:** {cv_text}
**JOB:** {job_description}""")
                qna_text = qna_result.messages[-1].text
                workflow = "Analysis → Q&A → Recommendation"
            else:
                logger.info(" Skipping Q&A")
                qna_text = "Q&A skipped - good fit detected"
                workflow = "Analysis → Recommendation"
            
            # Step 4: Final recommendation
            logger.info(" Generating recommendation...")
            rec_agent = self._get_agent("recommendation")
            
            rec_prompt = f"""**CV:** {cv_text}
**JOB:** {job_description}
**ANALYSIS:**
{analysis_text}"""
            
            if needs_qna:
                rec_prompt += f"""

**Q&A INSIGHTS:**
{qna_text}"""
            
            rec_result = await rec_agent.run(rec_prompt)
            recommendation_text = rec_result.messages[-1].text
            
            # Combine results
            final_report = f"""# CV/Job Analysis Report
**Workflow:** {workflow}

## Analysis Results
{analysis_text}

---

## Q&A Session
{qna_text}

---

## Final Recommendations
{recommendation_text}

---
✅ **Analysis Complete**"""

            return final_report
            
        except Exception as e:
            logger.error(f"Error in analysis: {e}")
            return f"Error: {str(e)}"

    # Interactive methods for main_file_based.py compatibility
    async def analyze_and_check_qna_needed(self, cv_text: str, job_description: str) -> dict:
        """Compatibility method for interactive workflow."""
        try:
            await self._setup_agents()
            analyzer = self._get_agent("analyzer")
            
            analysis_result = await analyzer.run(f"""**CANDIDATE CV:**
{cv_text}

**JOB DESCRIPTION:**
{job_description}""")
            analysis_text = analysis_result.messages[-1].text
            
            needs_qna = self._should_run_qna(analysis_text)
            
            return {
                "analysis": analysis_text,
                "needs_qna": needs_qna,
                "cv_text": cv_text,
                "job_description": job_description
            }
        except Exception as e:
            return {"error": str(e)}
    
    async def interactive_qna_session(self, analysis_data: dict) -> str:
        """Start interactive Q&A session."""
        try:
            qna_agent = self._get_agent("qna")
            
            qna_result = await qna_agent.run(f"""**ANALYSIS:**
{analysis_data["analysis"]}

**CV:** {analysis_data["cv_text"]}
**JOB:** {analysis_data["job_description"]}""")
            
            self.qna_agent = qna_agent  # Store for continuation
            return qna_result.messages[-1].text
        except Exception as e:
            return f"Error: {str(e)}"
    
    async def continue_qna(self, user_response: str) -> str:
        """Continue Q&A conversation."""
        try:
            if not hasattr(self, 'qna_agent'):
                return "Error: Q&A session not initialized"
            
            qna_result = await self.qna_agent.run(f"User response: {user_response}")
            return qna_result.messages[-1].text
        except Exception as e:
            return f"Error: {str(e)}"
    
    async def finalize_recommendation(self, analysis_data: dict, qna_summary: str = None) -> str:
        """Generate final recommendation."""
        try:
            rec_agent = self._get_agent("recommendation")
            
            rec_prompt = f"""**CV:** {analysis_data["cv_text"]}
**JOB:** {analysis_data["job_description"]}
**ANALYSIS:**
{analysis_data["analysis"]}"""
            
            if qna_summary:
                rec_prompt += f"""

**Q&A INSIGHTS:**
{qna_summary}"""
                workflow = "Analyzer → Interactive Q&A → Recommendation"
            else:
                workflow = "Analyzer → Recommendation"
            
            rec_result = await rec_agent.run(rec_prompt)
            recommendation_text = rec_result.messages[-1].text
            
            qna_section = qna_summary if qna_summary else "Q&A skipped"
            
            return f"""# CV/Job Analysis Report
**Workflow:** {workflow}

## Analysis Results
{analysis_data["analysis"]}

---

## Q&A Session  
{qna_section}

---

## Final Recommendations
{recommendation_text}

---
✅ **Analysis Complete**"""
        except Exception as e:
            return f"Error: {str(e)}"

    # Alias for backward compatibility
    async def direct_analyze(self, cv_text: str, job_description: str) -> str:
        """Alias for the main analyze method."""
        return await self.analyze(cv_text, job_description)


async def main():
    """Test the clean orchestrator."""
    print("Use main_file_based.py instead - this orchestrator is designed to work with your CV and job files.")


if __name__ == "__main__":
    asyncio.run(main())