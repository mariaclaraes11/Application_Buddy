# Application Buddy

A sophisticated CV/Job matching system powered by Microsoft Agent Framework and Azure AI Foundry. This system helps **job applicants** decide whether they should apply for a position by providing intelligent analysis and personalized recommendations.

## Purpose

**For Job Applicants Only** - This tool helps candidates:
- Analyze their CV against job requirements
- Understand their strengths and gaps
- Get personalized application advice
- Make informed decisions about whether to apply
- Avoid mass-applying to unsuitable positions



##  Available Scripts

### 1. `main.py` - **Agent Orchestrator Mode** (Recommended but can't get it to work)
**What it does:** Uses Agent Framework's GroupChat for automatic multi-agent coordination
- Agents automatically decide when to pass control to each other
- Full streaming conversation between agents
- Most sophisticated orchestration approach
- Ideal for complex analysis scenarios

**Usage:**
```bash
python main.py
```

### 2. `main_interactive.py` - **Interactive Q&A Mode** (only way icna get QA to be an actual QA without skipping user's input)
**What it does:** Provides real human-agent conversation when gaps are detected
- Analyzes CV vs job first
- If critical gaps found, starts natural conversation with user
- User can actually respond to questions and have back-and-forth dialogue
- More personal and conversational approach

**Usage:**
```bash
python main_interactive.py
```

### 3. `test_vague_job.py` - **Testing Script For Vgaue Job Scenario**
**What it does:** Tests how the system handles vague job postings
- Uses sample CV and deliberately vague job description
- Helps validate the analysis logic
- Useful for development and debugging

**Usage:**
```bash
python test_vague_job.py
```

##  Multi-Agent Architecture

The system deploys 3 specialized agents to Azure AI Foundry:

**CV Job Analyzer Agent** - Technical analysis specialist
- Extracts explicit requirements from job postings
- Matches CV evidence against requirements with structured JSON output
- Identifies gaps with priorities (high/med/low) and requirement types (must/nice)
- Computes preliminary fit scores (0-100)
- Handles vague job postings by defaulting to "must have" requirements

**CV Job Q&A Agent** - Conversational career advisor
- Conducts natural, friendly conversations with applicants
- Discovers hidden strengths not obvious from CV
- Explores working style, interests, and motivations
- Uses conversational techniques instead of direct questioning
- Provides insights that inform the final recommendation

**CV Job Recommendation Agent** - Application advisor
- Provides applicant-focused recommendations (STRONG APPLY/APPLY/CAUTIOUS APPLY/SKIP)
- Suggests how to strengthen applications
- Offers realistic expectations about competitiveness
- Gives actionable next steps for career development

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation & Setup](#installation--setup)
- [Environment Configuration](#environment-configuration)
- [Usage](#usage)
- [Architecture Details](#architecture-details)
- [Troubleshooting](#troubleshooting)

## Prerequisites

Before you begin, ensure you have:

- **Python 3.8+** installed
- **Azure CLI** installed and configured (`az login`)
- **Azure AI Foundry project** with a deployed model (GPT-4, GPT-4o, etc.)
- **Git** for version control
- **VS Code** (recommended, especially with Remote-WSL extension for WSL users)

## Installation & Setup

### Step 1: Clone the Repository

```bash
git clone https://github.com/mariaclaraes11/Application_Buddy.git
cd Application_Buddy
```

### Step 2: Create Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Environment Configuration

Create your environment configuration:

```bash
cp .env.example .env
```

Edit `.env` with your Azure AI Foundry details:

```env
# Azure AI Foundry Configuration
AZURE_AI_FOUNDRY_ENDPOINT=https://your-project.swedencentral.ai.azure.com
MODEL_DEPLOYMENT_NAME=gpt-4o

# Optional: Specific subscription (if you have multiple)
AZURE_SUBSCRIPTION_ID=your-subscription-id
```

### Step 5: Azure Authentication

Ensure you're logged into Azure CLI:

```bash
az login
# If you have multiple subscriptions:
az account set --subscription "your-subscription-name-or-id"
```

## Environment Configuration

### Required Environment Variables

Create a `.env` file in the project root with these variables:

| Variable | Description | Example |
|----------|-------------|---------|
| `AZURE_AI_FOUNDRY_ENDPOINT` | Your Azure AI Foundry project endpoint | `https://app-buddy-resource.swedencentral.ai.azure.com` |
| `MODEL_DEPLOYMENT_NAME` | Name of your deployed model | `gpt-4o` |
| `AZURE_SUBSCRIPTION_ID` | (Optional) Specific subscription ID | `12345678-1234-1234-1234-123456789012` |


## Usage

### Quick Start

1. **Activate your virtual environment:**
   ```bash
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

2. **Run the main application:**
   ```bash
   python main.py
   ```

3. **What happens on first run:**
   - ✅ Agents are automatically created in your Azure AI Foundry project
   - ✅ Agent Framework GroupChat orchestration is set up
   - ✅ All conversations appear in Foundry dashboard for monitoring
   - ✅ No separate deployment step needed!

4. **Usage:**
   - Paste CV text when prompted (it will ask if you want to past all in one line, YES YOU DO)
   - Paste job description when prompted
   - System analyzes and provides recommendation
   - View results in both terminal and Azure AI Foundry dashboard

### Choosing the Right Script

**Use `main.py` when:**
- You want the most sophisticated analysis
- You prefer automatic agent coordination
- You want to see streaming agent conversations
- You don't need to interact during the Q&A phase

**Use `main_interactive.py` when:**
- You want to have real conversations with the Q&A agent
- You prefer more control over the analysis process
- You want to provide additional context through dialogue
- You want a more personal, conversational experience


## Dependencies

This project uses the following key dependencies:

```
agent-framework-azure-ai --pre   # Microsoft Agent Framework (preview)
azure-ai-projects                # Azure AI Foundry integration
azure-identity                   # Azure authentication
python-dotenv                    # Environment variable management
pydantic-settings                # Configuration management
```

Install all dependencies with:
```bash
pip install -r requirements.txt
```
