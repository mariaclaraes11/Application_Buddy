"""
File-Based Interactive Application Buddy - Multi-Agent Orchestration System

This version automatically reads CV and job descriptions from text files,
AND includes the full interactive Q&A functionality for comprehensive analysis.

Architecture:
- Reads CV from my_cv.txt
- Reads job descriptions from job_descriptions.txt
- Step 1: Analyze CV vs Job match
- Step 2: If gaps found, start interactive Q&A with user
- Step 3: Generate final application recommendation
- Supports multiple job descriptions in the same file

Usage:
1. Fill in text_examples/my_cv.txt with your CV content
2. Fill in text_examples/job_descriptions.txt with job descriptions 
3. Run: python main_file_based.py
"""

import asyncio
import os
import re
import sys
from dotenv import load_dotenv

# Add parent directory to Python path so we can import from src
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agents.clean_orchestrator import CleanOrchestrator
from src.config import Config


def read_cv_file():
    """Read CV content from text_examples/my_cv.txt"""
    try:
        with open('text_examples/my_cv.txt', 'r', encoding='utf-8') as file:
            cv_content = file.read().strip()
            if not cv_content:
                print(" CV file is empty. Please fill in text_examples/my_cv.txt with your CV content.")
                return None
            return cv_content
    except FileNotFoundError:
        print(" CV file not found. Please create text_examples/my_cv.txt with your CV content.")
        return None
    except Exception as e:
        print(f" Error reading CV file: {str(e)}")
        return None


def parse_job_descriptions():
    """Parse job descriptions from text_examples/job_descriptions.txt"""
    try:
        with open('text_examples/job_descriptions.txt', 'r', encoding='utf-8') as file:
            content = file.read().strip()
            
        if not content:
            print(" Job descriptions file is empty. Please fill in text_examples/job_descriptions.txt.")
            return []
        
        # Split by job separators (---JOB X--- format or similar patterns)
        job_sections = re.split(r'---\s*JOB\s*\d*\s*---', content, flags=re.IGNORECASE)
        
        # If no job separators found, treat entire content as one job
        if len(job_sections) <= 1:
            # Check if it's just template content
            if "JOB DESCRIPTION TEMPLATE" in content or "[JOB TITLE]" in content:
                print(" Please replace the template content in text_examples/job_descriptions.txt with actual job descriptions.")
                return []
            # Return as a dictionary with proper structure
            job_title = extract_job_title(content)
            return [{
                'number': 1,
                'title': job_title or "Job Description",
                'content': content
            }]
        
        # Clean up job sections and filter out empty ones
        jobs = []
        for i, section in enumerate(job_sections):
            cleaned_section = section.strip()
            if cleaned_section and len(cleaned_section) > 100:  # Minimum length for a real job description
                # Add job number for identification
                job_title = extract_job_title(cleaned_section)
                jobs.append({
                    'number': i,
                    'title': job_title or f"Job {i}",
                    'content': cleaned_section
                })
        
        return jobs
        
    except FileNotFoundError:
        print(" text_examples/job_descriptions.txt not found. Please create this file with job descriptions.")
        return []
    except Exception as e:
        print(f" Error reading job descriptions file: {str(e)}")
        return []


def extract_job_title(job_content):
    """Extract job title from job description content"""
    lines = job_content.split('\n')
    for line in lines[:10]:  # Check first 10 lines
        line = line.strip()
        if line and not line.startswith('Logo') and not line.startswith('Compartilhar'):
            # Look for common job title patterns
            if any(keyword in line.lower() for keyword in ['engineer', 'developer', 'analyst', 'manager', 'intern', 'specialist']):
                return line[:80]  # Limit length
    
    # Fallback: return first non-empty line
    for line in lines[:5]:
        line = line.strip()
        if line and len(line) < 100:
            return line
    
    return "Job Description"


def display_job_options(jobs):
    """Display available job options for selection"""
    print("\n Available Job Descriptions:")
    print("=" * 40)
    
    for i, job in enumerate(jobs):
        print(f"{i + 1}. {job['title']}")
    
    print(f"{len(jobs) + 1}. Analyze all jobs")
    print("0. Exit")


async def analyze_single_job(orchestrator, cv_content, job):
    """Analyze CV against a single job with interactive Q&A"""
    print(f"\n Analyzing: {job['title']}")
    print("=" * 50)
    
    try:
        # Step 1: Analyze and check if Q&A is needed
        print("Analyzing your CV against the job requirements...")
        analysis_data = await orchestrator.analyze_and_check_qna_needed(cv_content, job['content'])
        
        if "error" in analysis_data:
            print(f"Error: {analysis_data['error']}")
            return None
        
        print("\nInitial Analysis Complete!")
        print("=" * 40)
        print(analysis_data["analysis"])
        print("=" * 40)
        
        qna_summary = None
        
        if analysis_data["needs_qna"]:
            print("\nLet's have a conversation to better understand your background.")
            print("=" * 50)
            
            # Start interactive Q&A
            qna_response = await orchestrator.interactive_qna_session(analysis_data)
            print(f"\nCareer Advisor: {qna_response}")
            
            # Interactive conversation loop
            conversation_complete = False
            conversation_turns = 0
            # Trust the Q&A agent to end naturally - no artificial limits
            
            while not conversation_complete:
                print(f"\nYour response (or type 'done' to finish):")
                user_input = input().strip()
                
                if user_input.lower() in ['done', 'finished', 'complete', 'end', 'skip']:
                    conversation_complete = True
                    qna_summary = "Conversation completed - user indicated they were ready to proceed with recommendation"
                    print("\nMoving to final recommendation...")
                else:
                    # Continue Q&A conversation
                    qna_response = await orchestrator.continue_qna(user_input)
                    print(f"\nCareer Advisor: {qna_response}")
                    
                    # Check if the agent provided a final JSON assessment (natural ending)
                    if ('discovered_strengths' in qna_response and 'conversation_notes' in qna_response) or \
                       ('final assessment' in qna_response.lower()) or \
                       ('{' in qna_response and '}' in qna_response and 'discovered_strengths' in qna_response):
                        print("\nQ&A session complete!")
                        qna_summary = qna_response
                        conversation_complete = True
                    
                    conversation_turns += 1
                
        else:
            print("\nAnalysis shows a strong fit - no additional questions needed")
        
        # Step 2: Generate final recommendation
        print("\nGenerating your personalized application recommendation...")
        final_result = await orchestrator.finalize_recommendation(analysis_data, qna_summary)
        
        print("\n" + "=" * 60)
        print(f"YOUR PERSONALIZED APPLICATION RECOMMENDATION")
        print(f"Job: {job['title']}")
        print("=" * 60)
        print(final_result)
        
        return final_result
        
    except Exception as e:
        print(f" Error analyzing {job['title']}: {str(e)}")
        return None


async def analyze_all_jobs(orchestrator, cv_content, jobs):
    """Analyze CV against all available jobs with interactive Q&A for each"""
    print(f"\n Analyzing CV against {len(jobs)} job(s) with full interactive analysis...")
    print("=" * 70)
    
    results = []
    
    for i, job in enumerate(jobs, 1):
        print(f"\n Job {i}/{len(jobs)}: {job['title']}")
        print("=" * 60)
        
        try:
            # Use the full interactive analysis for each job
            result = await analyze_single_job(orchestrator, cv_content, job)
            if result:
                results.append({
                    'job_title': job['title'],
                    'analysis': result
                })
                print(f" Completed: {job['title']}")
                
                # Ask if user wants to continue to next job (if not last job)
                if i < len(jobs):
                    continue_choice = input(f"\nContinue to next job? (y/n): ").strip().lower()
                    if continue_choice not in ['y', 'yes', '']:
                        print("Stopping analysis at user request.")
                        break
                        
        except Exception as e:
            print(f" Error with {job['title']}: {str(e)}")
            continue
    
    # Summary if multiple jobs were analyzed
    if len(results) > 1:
        print(f"\n SUMMARY: Analyzed {len(results)} job(s)")
        print("=" * 50)
        for i, result in enumerate(results, 1):
            print(f"{i}. {result['job_title']} - Analysis completed")
    
    return results


async def main():
    """
    File-based CV/Job matching system
    """
    # Load environment variables
    load_dotenv()
    
    # Check if configuration is set up
    if not os.getenv("AZURE_AI_FOUNDRY_ENDPOINT"):
        print("  Configuration Setup Required")
        print("=" * 50)
        print("Please set up your configuration:")
        print("1. Copy .env.example to .env")
        print("2. Fill in your Azure AI Foundry endpoint and model deployment name")
        print("3. Ensure you're authenticated with Azure (az login)")
        return
    
    print(" File-Based CV/Job Matching System")
    print("=" * 45)
    
    try:
        # Read CV content
        print(" Reading your CV...")
        cv_content = read_cv_file()
        if not cv_content:
            return
        
        print(" CV loaded successfully")
        
        # Parse job descriptions
        print(" Loading job descriptions...")
        jobs = parse_job_descriptions()
        if not jobs:
            return
        
        print(f" Found {len(jobs)} job description(s)")
        
        # Initialize orchestrator
        config = Config()
        orchestrator = CleanOrchestrator(config)
        
        # Handle single job vs multiple jobs
        if len(jobs) == 1:
            print(f"\n Found 1 job description: {jobs[0]['title']}")
            response = input("Analyze this job? (y/n): ").strip().lower()
            if response in ['y', 'yes', '']:
                await analyze_single_job(orchestrator, cv_content, jobs[0])
        else:
            # Multiple jobs - show selection menu
            while True:
                display_job_options(jobs)
                
                try:
                    choice = input(f"\nSelect option (1-{len(jobs) + 1}, 0 to exit): ").strip()
                    
                    if choice == '0':
                        print(" Goodbye!")
                        break
                    elif choice == str(len(jobs) + 1):
                        # Analyze all jobs
                        await analyze_all_jobs(orchestrator, cv_content, jobs)
                        break
                    else:
                        job_index = int(choice) - 1
                        if 0 <= job_index < len(jobs):
                            await analyze_single_job(orchestrator, cv_content, jobs[job_index])
                            
                            # Ask if they want to continue
                            continue_choice = input(f"\nAnalyze another job? (y/n): ").strip().lower()
                            if continue_choice not in ['y', 'yes']:
                                break
                        else:
                            print(" Invalid selection. Please try again.")
                            
                except ValueError:
                    print(" Please enter a valid number.")
                except KeyboardInterrupt:
                    print("\n Goodbye!")
                    break
        
    except KeyboardInterrupt:
        print("\n Goodbye!")
    except Exception as e:
        print(f" Error: {str(e)}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n Application terminated by user.")
    except Exception as e:
        print(f" Fatal error: {str(e)}")
        print("Please check your configuration and try again.")