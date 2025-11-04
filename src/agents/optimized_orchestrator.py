# Copyright (c) Microsoft. All rights reserved.

"""
Foundry-Integrated orchestration using Agent Framework GroupChat pattern.
Automatically creates agents in Azure AI Foundry using your sophisticated prompts,
then orchestrates them with intelligent GroupChat coordination.
"""

import asyncio
import json
import logging
from typing import AsyncIterator, Dict, Any

from agent_framework import ChatAgent, GroupChatBuilder, ChatMessage, Role
from agent_framework.azure import AzureAIAgentClient
from azure.identity.aio import DefaultAzureCredential
from azure.ai.projects.aio import AIProjectClient

from ..config import Config
from .agent_definitions import AgentDefinitions

logger = logging.getLogger(__name__)


class FoundryIntegratedOrchestrator:
    """
    Best of both worlds: Agent Framework orchestration + Foundry visibility.
    
    This approach:
    - Automatically creates agents in Azure AI Foundry using your sophisticated prompts
    - Uses Agent Framework GroupChat for intelligent coordination
    - Agents appear in Foundry dashboard with full conversation history
    - No separate deployment step needed
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.foundry_agents = {}  # Cache for created Foundry agents
        self.workflow = None
        self.project_client = None
        self.credential = None
    
    async def _ensure_foundry_agents(self) -> Dict[str, Any]:
        """Create agents in Azure AI Foundry if they don't exist, or reuse existing ones."""
        if self.foundry_agents:
            return self.foundry_agents
            
        # Initialize clients that will stay alive for the session
        if not self.credential:
            self.credential = DefaultAzureCredential()
            
        if not self.project_client:
            self.project_client = AIProjectClient(
                endpoint=self.config.azure_ai_foundry_endpoint,
                credential=self.credential
            )
                
        logger.info("Checking for existing agents in Azure AI Foundry...")
        agents_config = AgentDefinitions.get_all_agents()
        
        # Get list of existing agents
        existing_agents = []
        async for agent in self.project_client.agents.list_agents():
            existing_agents.append(agent)
        existing_by_name = {agent.name: agent for agent in existing_agents}
        
        # Find or create analyzer agent
        analyzer_config = agents_config["analyzer"]
        if analyzer_config["name"] in existing_by_name:
            logger.info(f"Reusing existing {analyzer_config['name']}")
            analyzer_agent = existing_by_name[analyzer_config["name"]]
        else:
            logger.info(f"Creating new {analyzer_config['name']}")
            analyzer_agent = await self.project_client.agents.create_agent(
                model=self.config.model_deployment_name,
                name=analyzer_config["name"],
                instructions=analyzer_config["instructions"],
                description=analyzer_config["description"]
            )
        
        # Find or create Q&A agent
        qna_config = agents_config["qna"]
        if qna_config["name"] in existing_by_name:
            logger.info(f"Reusing existing {qna_config['name']}")
            qna_agent = existing_by_name[qna_config["name"]]
        else:
            logger.info(f"Creating new {qna_config['name']}")
            qna_agent = await self.project_client.agents.create_agent(
                model=self.config.model_deployment_name,
                name=qna_config["name"],
                instructions=qna_config["instructions"],
                description=qna_config["description"]
            )
        
        # Find or create recommendation agent
        rec_config = agents_config["recommendation"]
        if rec_config["name"] in existing_by_name:
            logger.info(f"Reusing existing {rec_config['name']}")
            rec_agent = existing_by_name[rec_config["name"]]
        else:
            logger.info(f"Creating new {rec_config['name']}")
            rec_agent = await self.project_client.agents.create_agent(
                model=self.config.model_deployment_name,
                name=rec_config["name"],
                instructions=rec_config["instructions"],
                description=rec_config["description"]
            )
        
        self.foundry_agents = {
            "analyzer": analyzer_agent,
            "qna": qna_agent,
            "recommendation": rec_agent,
            "project_client": self.project_client
        }
        
        logger.info(f"Ready with 3 agents in Foundry")
        return self.foundry_agents
    
    async def analyze_and_check_qna_needed(self, cv_text: str, job_description: str) -> dict:
        """
        First step: analyze CV/job match and determine if Q&A is needed.
        Returns analysis results and whether interactive Q&A should be started.
        """
        try:
            # Ensure agents are available
            await self._ensure_foundry_agents()
            
            # Create analyzer agent
            foundry_agents = self.foundry_agents
            project_client = foundry_agents["project_client"]
            
            from agent_framework import ChatAgent
            from agent_framework.azure import AzureAIAgentClient
            
            analyzer = ChatAgent(
                name="analyzer",
                chat_client=AzureAIAgentClient(
                    project_client=project_client,
                    agent_id=foundry_agents["analyzer"].id
                )
            )
            
            # Run analysis
            analysis_prompt = f"""Please analyze this CV vs job match:

**CANDIDATE CV:**
{cv_text}

**JOB DESCRIPTION:**
{job_description}

Please provide detailed JSON analysis with gaps prioritized as "high", "med", or "low"."""

            logger.info("Running CV analysis...")
            analysis_result = await analyzer.run(analysis_prompt)
            analysis_text = analysis_result.messages[-1].text
            
            # Check if Q&A is needed
            needs_qna = self._should_run_qna(analysis_text)
            
            return {
                "analysis": analysis_text,
                "needs_qna": needs_qna,
                "cv_text": cv_text,
                "job_description": job_description
            }
            
        except Exception as e:
            logger.error(f"Error in analysis: {e}")
            return {"error": str(e)}
    
    async def interactive_qna_session(self, analysis_data: dict) -> str:
        """
        Start an interactive Q&A session with the user.
        Returns the Q&A agent's first question to start the conversation.
        """
        try:
            foundry_agents = self.foundry_agents
            project_client = foundry_agents["project_client"]
            
            from agent_framework import ChatAgent
            from agent_framework.azure import AzureAIAgentClient
            
            # Create Q&A agent
            qna_agent = ChatAgent(
                name="qna",
                chat_client=AzureAIAgentClient(
                    project_client=project_client,
                    agent_id=foundry_agents["qna"].id
                )
            )
            
            # Start the Q&A session
            analysis_text = analysis_data["analysis"]
            cv_text = analysis_data["cv_text"]
            job_description = analysis_data["job_description"]
            
            qna_start_prompt = f"""Based on this CV analysis, start a natural, friendly conversation with the applicant to understand their background better:

**ANALYSIS:**
{analysis_text}

**CV:** {cv_text}
**JOB:** {job_description}

Start the conversation naturally - be genuinely curious about them as a person and professional. Ask ONE conversational question to get to know them better. Focus on their interests, experiences, or what excites them about their field."""

            logger.info("Starting interactive Q&A session...")
            qna_result = await qna_agent.run(qna_start_prompt)
            
            # Store the agent for continued conversation
            self.qna_agent = qna_agent
            
            # Return the first Q&A response to start the conversation
            return qna_result.messages[-1].text
            
        except Exception as e:
            logger.error(f"Error starting Q&A: {e}")
            return f"Error starting Q&A: {str(e)}"
    
    async def continue_qna(self, user_response: str) -> str:
        """
        Continue the Q&A conversation with user response.
        """
        try:
            if not hasattr(self, 'qna_agent'):
                return "Error: Q&A session not initialized"
            
            # Continue conversation with context reminder
            contextual_response = f"User response: {user_response}\n\nPlease continue the conversation naturally based on their response. Remember you are helping them assess their fit for the SRE role and exploring areas that weren't clear from their CV."
            
            qna_result = await self.qna_agent.run(contextual_response)
            return qna_result.messages[-1].text
            
        except Exception as e:
            logger.error(f"Error continuing Q&A: {e}")
            return f"Error: {str(e)}"
    
    async def finalize_recommendation(self, analysis_data: dict, qna_summary: str = None) -> str:
        """
        Generate final recommendation based on analysis and optional Q&A insights.
        """
        try:
            foundry_agents = self.foundry_agents
            project_client = foundry_agents["project_client"]
            
            from agent_framework import ChatAgent
            from agent_framework.azure import AzureAIAgentClient
            
            recommendation_agent = ChatAgent(
                name="recommendation",
                chat_client=AzureAIAgentClient(
                    project_client=project_client,
                    agent_id=foundry_agents["recommendation"].id
                )
            )
            
            analysis_text = analysis_data["analysis"]
            cv_text = analysis_data["cv_text"]
            job_description = analysis_data["job_description"]
            
            if qna_summary:
                recommendation_prompt = f"""Based on this analysis and Q&A insights:

**ANALYSIS:**
{analysis_text}

**Q&A INSIGHTS:**
{qna_summary}

**CV:** {cv_text}
**Job:** {job_description}

Provide final recommendation for the candidate about whether they should apply."""
                workflow_path = "Analyzer → Interactive Q&A → Recommendation"
            else:
                recommendation_prompt = f"""Based on this analysis:

**ANALYSIS:**
{analysis_text}

**CV:** {cv_text}
**Job:** {job_description}

Provide final recommendation for the candidate about whether they should apply. The analysis shows good fit with minimal gaps."""
                workflow_path = "Analyzer → Recommendation (Q&A skipped)"
            
            logger.info("Generating final recommendation...")
            recommendation_result = await recommendation_agent.run(recommendation_prompt)
            recommendation_text = recommendation_result.messages[-1].text
            
            # Build final report
            qna_section = qna_summary if qna_summary else "Q&A skipped - analysis showed good fit with minimal critical gaps"
            
            final_report = f"""# CV/Job Analysis Report
**Workflow:** {workflow_path}

## Analysis Results
{analysis_text}

---

## Q&A Session
{qna_section}

---

## Final Recommendations
{recommendation_text}

---
✅ **Analysis Complete**"""

            return final_report
            
        except Exception as e:
            logger.error(f"Error in final recommendation: {e}")
            return f"Error: {str(e)}"
    
    async def _build_workflow(self):
        """Build GroupChat workflow using Foundry-created agents."""
        foundry_agents = await self._ensure_foundry_agents()
        project_client = foundry_agents["project_client"]
        
        # Create Agent Framework agents that connect to Foundry agents
        cv_analyzer = ChatAgent(
            name="resume_analysis",
            chat_client=AzureAIAgentClient(
                project_client=project_client,
                agent_id=foundry_agents["analyzer"].id
            )
        )
        
        qna_agent = ChatAgent(
            name="qna",
            chat_client=AzureAIAgentClient(
                project_client=project_client,
                agent_id=foundry_agents["qna"].id
            )
        )
        
        recommendation_agent = ChatAgent(
            name="recommendation",
            chat_client=AzureAIAgentClient(
                project_client=project_client,
                agent_id=foundry_agents["recommendation"].id
            )
        )
        
        # Build GroupChat with intelligent orchestrator logic
        workflow = (
            GroupChatBuilder()
            .set_prompt_based_manager(
                chat_client=AzureAIAgentClient(
                    project_client=project_client,
                    agent_id=foundry_agents["analyzer"].id  # Use any agent for manager client
                ),
                display_name="CVJobOrchestrator",
                instructions="""You coordinate CV/job analysis. Follow this sequence:

1. First call: 'resume_analysis' - to analyze the CV vs job
2. After analysis: Look at the score and gaps
   - High score (80+) and few gaps → call 'recommendation' 
   - Medium score (60-79) with gaps → call 'qna' then 'recommendation'
   - Low score (<60) → call 'recommendation'
3. After recommendation → END

Always choose next agent based on what's been completed. Never repeat calls to the same agent."""
            )
            .participants([cv_analyzer, qna_agent, recommendation_agent])
            .with_max_rounds(6)  # Increased to allow for proper workflow
            .build()
        )
        
        return workflow
    
    async def analyze_cv_job_match(self, cv_text: str, job_description: str) -> AsyncIterator[str]:
        """
        Analyze CV and job match using Foundry-integrated GroupChat workflow.
        
        Args:
            cv_text: The candidate's CV content
            job_description: The job posting description
            
        Yields:
            str: Analysis updates and results from the orchestration
        """
        try:
            # Ensure workflow is built
            if self.workflow is None:
                self.workflow = await self._build_workflow()
            
            # Create the combined input for analysis
            analysis_request = f"""Please analyze this job matching scenario:

**CANDIDATE CV:**
{cv_text}

**JOB DESCRIPTION:**
{job_description}

**TASK:**
Please provide a comprehensive analysis of how well this candidate matches the job requirements, including specific recommendations for improvement."""

            logger.info("Starting Foundry-integrated CV/job analysis workflow")
            
            # Run the GroupChat workflow - accumulate complete responses
            current_agent = None
            accumulated_content = ""
            
            async for event in self.workflow.run_stream(analysis_request):
                # Handle AgentRunUpdateEvent - these contain streaming tokens
                if hasattr(event, 'executor_id') and hasattr(event, 'messages'):
                    # Extract agent name from executor_id
                    executor_parts = event.executor_id.split(':')
                    agent_name = executor_parts[-1] if len(executor_parts) > 1 else "Agent"
                    
                    # If we switched to a new agent, yield the previous agent's complete content
                    if current_agent and current_agent != agent_name and accumulated_content.strip():
                        yield f"## {current_agent.replace('_', ' ').title()}\n\n{accumulated_content.strip()}\n\n---\n\n"
                        accumulated_content = ""
                    
                    current_agent = agent_name
                    
                    # Accumulate the streaming tokens
                    if hasattr(event, 'messages') and event.messages:
                        accumulated_content += str(event.messages)
                        
                # Handle completion events - agent finished
                elif hasattr(event, 'executor_id') and 'Completed' in str(type(event)):
                    executor_parts = event.executor_id.split(':')
                    agent_name = executor_parts[-1] if len(executor_parts) > 1 else "Agent"
                    
                    # Output the complete response for this agent
                    if accumulated_content.strip():
                        yield f"## {agent_name.replace('_', ' ').title()}\n\n{accumulated_content.strip()}\n\n---\n\n"
                        accumulated_content = ""
                        current_agent = None
                        
                # Handle workflow completion
                elif 'WorkflowStatus' in str(type(event)):
                    # Output any remaining content
                    if current_agent and accumulated_content.strip():
                        yield f"## {current_agent.replace('_', ' ').title()}\n\n{accumulated_content.strip()}\n\n---\n\n"
                    
                    # Check if workflow is done
                    if hasattr(event, 'state') and 'IDLE' in str(event.state):
                        yield "✅ **Analysis Complete**\n"
                        break
                        
        except Exception as e:
            logger.error(f"Error in Foundry-integrated orchestration: {e}")
            yield f"Error: {str(e)}\n"
    
    async def direct_analyze(self, cv_text: str, job_description: str) -> str:
        """
        Intelligent direct orchestration with optional Q&A based on gaps analysis.
        """
        try:
            # Get the Foundry agents
            foundry_agents = await self._ensure_foundry_agents()
            project_client = foundry_agents["project_client"]
            
            # Create individual agent connections
            from agent_framework import ChatAgent
            from agent_framework.azure import AzureAIAgentClient
            
            analyzer = ChatAgent(
                name="analyzer",
                chat_client=AzureAIAgentClient(
                    project_client=project_client,
                    agent_id=foundry_agents["analyzer"].id
                )
            )
            
            qna_agent = ChatAgent(
                name="qna",
                chat_client=AzureAIAgentClient(
                    project_client=project_client,
                    agent_id=foundry_agents["qna"].id
                )
            )
            
            recommendation = ChatAgent(
                name="recommendation", 
                chat_client=AzureAIAgentClient(
                    project_client=project_client,
                    agent_id=foundry_agents["recommendation"].id
                )
            )
            
            # Step 1: Run analysis
            analysis_prompt = f"""Please analyze this CV vs job match:

**CANDIDATE CV:**
{cv_text}

**JOB DESCRIPTION:**
{job_description}

Please provide detailed JSON analysis with gaps prioritized as "high", "med", or "low"."""

            logger.info("🔍 Running CV analysis...")
            analysis_result = await analyzer.run(analysis_prompt)
            analysis_text = analysis_result.messages[-1].text
            
            # Step 2: Intelligent decision - check for critical gaps
            needs_qna = self._should_run_qna(analysis_text)
            
            if needs_qna:
                logger.info("❓ Critical gaps found - running Q&A session...")
                
                # Run Q&A to clarify gaps
                qna_prompt = f"""Based on this CV analysis, conduct a brief Q&A session to clarify gaps:

{analysis_text}

**CV:** {cv_text}
**Job:** {job_description}

Focus on high-priority gaps that could be resolved through conversation. Provide specific questions to ask the candidate."""

                qna_result = await qna_agent.run(qna_prompt)
                qna_text = qna_result.messages[-1].text
                
                # Step 3: Final recommendation with Q&A insights
                recommendation_prompt = f"""Based on this analysis and Q&A insights:

**ANALYSIS:**
{analysis_text}

**Q&A SESSION:**
{qna_text}

Please provide comprehensive hiring recommendations."""
                
                workflow_path = "Analyzer → Q&A → Recommendation"
            else:
                logger.info("✅ No critical gaps - skipping Q&A, proceeding to recommendation...")
                qna_text = "Q&A session skipped - no critical gaps requiring clarification."
                
                # Step 3: Direct recommendation (skip Q&A)
                recommendation_prompt = f"""Based on this analysis (Q&A skipped due to strong fit):

{analysis_text}

Please provide comprehensive hiring recommendations including:
- Overall recommendation (Strong Hire/Hire/No Hire/Strong No Hire)
- Interview focus areas
- Risk factors and mitigation
- Onboarding recommendations
- Timeline"""
                
                workflow_path = "Analyzer → Recommendation (Q&A skipped)"

            logger.info("📋 Generating final recommendations...")
            recommendation_result = await recommendation.run(recommendation_prompt)
            recommendation_text = recommendation_result.messages[-1].text
            
            # Combine results
            final_report = f"""# CV/Job Analysis Report
**Workflow:** {workflow_path}

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
            logger.error(f"Error in direct analysis: {e}")
            return f"Error: {str(e)}"
    
    def _should_run_qna(self, analysis_text: str) -> bool:
        """
        Determine if Q&A session is needed based on analysis results.
        
        Args:
            analysis_text: The JSON analysis from the analyzer agent
            
        Returns:
            bool: True if Q&A is needed, False if can skip to recommendation
        """
        try:
            # Try to parse JSON to get structured gaps analysis
            if '{' in analysis_text and '}' in analysis_text:
                # Extract JSON part
                json_start = analysis_text.find('{')
                json_end = analysis_text.rfind('}') + 1
                json_str = analysis_text[json_start:json_end]
                
                try:
                    analysis_data = json.loads(json_str)
                    
                    # Check for critical gaps - both high priority AND missing "must have" requirements
                    gaps = analysis_data.get('gaps', [])
                    high_priority_gaps = [gap for gap in gaps if gap.get('priority') == 'high']
                    must_have_gaps = [gap for gap in gaps if gap.get('requirement_type') == 'must']
                    
                    # Decision criteria:
                    # - Always run Q&A if missing "must have" requirements (regardless of priority/score)
                    # - Run Q&A if score < 75
                    # - Run Q&A if high priority gaps exist
                    # - Skip Q&A only if score >= 85 AND no must-have gaps
                    
                    score = analysis_data.get('preliminary_score', 0)
                    
                    if len(must_have_gaps) > 0:
                        logger.info(f"Missing {len(must_have_gaps)} must-have requirements - Q&A needed: {[gap['name'] for gap in must_have_gaps]}")
                        return True
                    elif score < 75:
                        logger.info(f"Low score ({score}) - Q&A needed")
                        return True
                    elif len(high_priority_gaps) > 0:
                        logger.info(f"High priority gaps found - Q&A needed: {[gap['name'] for gap in high_priority_gaps]}")
                        return True
                    elif score >= 85:
                        logger.info(f"High score ({score}) with no critical gaps - skipping Q&A")
                        return False
                    else:
                        logger.info(f"Moderate score ({score}) with no critical gaps - skipping Q&A")
                        return False
                        
                except json.JSONDecodeError:
                    pass
            
            # Fallback: text-based analysis for keywords
            text_lower = analysis_text.lower()
            critical_indicators = [
                'high priority', 'critical gap', 'major gap', 'missing requirement',
                'insufficient', 'lacks', 'no evidence', 'unclear'
            ]
            
            critical_count = sum(1 for indicator in critical_indicators if indicator in text_lower)
            
            # If multiple critical indicators, run Q&A
            should_run = critical_count >= 2
            logger.info(f"Text analysis: {critical_count} critical indicators - {'Q&A needed' if should_run else 'Q&A skipped'}")
            return should_run
            
        except Exception as e:
            logger.warning(f"Error in gap analysis decision: {e} - defaulting to Q&A")
            return True  # Default to Q&A if can't determine

    async def simple_analyze(self, cv_text: str, job_description: str) -> str:
        """
        Simple analysis method that returns complete results.
        
        Args:
            cv_text: The candidate's CV content
            job_description: The job posting description
            
        Returns:
            str: Complete analysis results
        """
        try:
            # Ensure workflow is built
            if self.workflow is None:
                self.workflow = await self._build_workflow()
            
            # Create the combined input for analysis
            analysis_request = f"""Please analyze this job matching scenario:

**CANDIDATE CV:**
{cv_text}

**JOB DESCRIPTION:**
{job_description}

**TASK:**
Please provide a comprehensive analysis of how well this candidate matches the job requirements, including specific recommendations for improvement."""

            logger.info("Starting Foundry-integrated CV/job analysis workflow (simple)")
            
            # Use run() instead of run_stream() to get complete results
            result = await self.workflow.run(analysis_request)
            
            # Extract the final message content from WorkflowOutputEvent
            for event in reversed(result):  # Look from the end for the final output
                if 'WorkflowOutput' in str(type(event)) and hasattr(event, 'data'):
                    final_message = event.data
                    if hasattr(final_message, 'text') and final_message.text:
                        return final_message.text
                    elif hasattr(final_message, 'contents') and final_message.contents:
                        # Extract text from contents if it's a list of content objects
                        content_parts = []
                        for content in final_message.contents:
                            if hasattr(content, 'text'):
                                content_parts.append(content.text)
                        return "\n".join(content_parts)
                    else:
                        return str(final_message)
            
            # If no WorkflowOutputEvent found, look for AgentRunEvent data
            agent_results = []
            for event in result:
                if 'AgentRun' in str(type(event)) and hasattr(event, 'data'):
                    agent_results.append(str(event.data))
            
            if agent_results:
                return "\n\n".join(agent_results)
            
            return "No analysis results generated."
            
        except Exception as e:
            logger.error(f"Error in simple analysis: {e}")
            return f"Error: {str(e)}"


async def main():
    """Test the Foundry-integrated orchestrator."""
    config = Config()
    orchestrator = FoundryIntegratedOrchestrator(config)
    
    # Test with sample data
    cv_sample = """
    John Doe
    Software Engineer
    
    Experience:
    - 5 years Python development
    - 3 years machine learning projects
    - Led team of 4 developers
    
    Skills: Python, SQL, Docker, AWS, TensorFlow
    Education: BS Computer Science
    """
    
    job_sample = """
    Senior Python Developer
    
    Requirements:
    - 5+ years Python experience
    - Machine learning background
    - Team leadership experience
    - Cloud platforms (AWS/Azure)
    - Bachelor's degree in Computer Science
    """
    
    print("=== Optimized Agent Framework Orchestration ===")
    result = await orchestrator.simple_analyze(cv_sample, job_sample)
    print(result)


if __name__ == "__main__":
    asyncio.run(main())