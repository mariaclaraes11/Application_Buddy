# Application Buddy

A sophisticated CV/Job matching system powered by Microsoft Agent Framework and Azure AI Foundry. This system helps **job applicants** decide whether they should apply for a position by providing intelligent analysis and personalized recommendations.

## Purpose

**For Job Applicants Only** - This tool helps candidates:
- Analyze their CV against job requirements  
- Understand their strengths and gaps
- Get personalized application advice
- Make informed decisions about whether to apply
- Avoid mass-applying to unsuitable positions

## 🚀 Quick Start

### 1. Setup Your Files
```bash
# Fill in your CV
text_examples/my_cv.txt

# Fill in job descriptions  
text_examples/job_descriptions.txt
```

### 2. Run Analysis
```bash
python main_file_based.py
```

That's it! The system automatically reads your files and provides complete analysis with optional interactive Q&A.

##  Available Scripts

### 1. `main_file_based.py` - **File-Based System** ⭐ (Recommended)
**What it does:** Automatically reads CV and job descriptions from files
- No manual copy-pasting required
- Supports multiple job descriptions
- Full interactive Q&A when gaps are detected  
- Clean, simplified orchestrator
- Best user experience

**Usage:**
```bash
python main_file_based.py
```

### 2. `main_interactive.py` - **Manual Input with Q&A**
**What it does:** Manual input with real human-agent conversation
- Requires copy-pasting CV and job description
- If critical gaps found, starts natural conversation with user
- User can actually respond to questions and have back-and-forth dialogue
- More personal and conversational approach

**Usage:**
```bash
python main_interactive.py
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

2. **Run the file-based application:**
   ```bash
   python main_file_based.py
   ```

3. **What happens on first run:**
   - ✅ Agents are automatically created in your Azure AI Foundry project  
   - ✅ CV and job descriptions are read from text files automatically
   - ✅ All conversations appear in Foundry dashboard for monitoring
   - ✅ No manual copy-pasting required!

4. **Usage:**
   - System automatically loads your CV from `text_examples/my_cv.txt`
   - System automatically loads job descriptions from `text_examples/job_descriptions.txt`  
   - System analyzes and provides recommendation
   - Interactive Q&A starts if gaps are detected
   - View results in both terminal and Azure AI Foundry dashboard

### Choosing the Right Script

**Use `main_file_based.py` when:** ⭐ (Recommended for daily use)
- You want automatic file reading (no copy-pasting)
- You have multiple job descriptions to analyze
- You want the most user-friendly experience  
- You want both analysis and interactive Q&A

**Use `main_interactive.py` when:**
- You prefer to manually input CV and job descriptions
- You want to have real conversations with the Q&A agent
- You want more control over the analysis process
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
