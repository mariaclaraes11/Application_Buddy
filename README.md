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

### 2. Choose Your Experience
```bash
# MVP Version - Proven, stable experience
python main_mvp.py

# WorkflowBuilder V1 - Enhanced with streaming conversation
python main_workflow_v1.py
```

That's it! The system automatically reads your files and provides complete analysis with optional interactive Q&A.

## 📋 Available Implementations

### 1. `main_mvp.py` - **MVP Version** ✅ (Stable & Proven)
**What it does:** Original proven implementation with Group Chat orchestration
- Automatic file-based CV and job loading
- Multi-job description support  
- Interactive Q&A when gaps are detected
- Clean Group Chat orchestrator pattern
- Battle-tested and reliable

**Usage:**
```bash
python main_mvp.py
```

### 2. `main_workflow_v1.py` - **WorkflowBuilder Version** ⭐ (Enhanced Experience)
**What it does:** Modern Agent Framework WorkflowBuilder with enhanced features
- **Letter-by-letter streaming** for natural conversation experience
- **Thread-based conversation memory** - no repeated questions
- **Enhanced role understanding** - helps you understand what jobs actually involve
- **Improved Q&A targeting** - focuses on exploring identified gaps
- Pure WorkflowBuilder orchestration with conditional routing
- Same reliable analysis as MVP with better user experience

**Usage:**
```bash
python main_workflow_v1.py
```

**New Features in V1:**
- ✨ **Streaming responses** - Career advisor types responses like a real person
- 🧠 **Conversation memory** - Agent remembers what you've discussed
- 🎯 **Gap-focused Q&A** - Naturally explores your missing skills through stories
- 📚 **Role education** - Explains what jobs actually involve day-to-day
- 🔗 **Better insights** - "New Things Found During Our Conversation" section

### 3. `main_interactive.py` - **Manual Input with Q&A** 
**What it does:** Original manual conversation approach
- Manual CV and job description entry
- Interactive Q&A conversation
- Good for single job analysis

**Usage:**
```bash
python main_interactive.py
```

### 4. `main.py` - **Basic Demo** 
**What it does:** Original demonstration script
- Basic agent interaction example
- No file loading or Q&A features

**Usage:**
```bash
python main.py
```

## 🏗️ Architecture

### Agent Definitions (`src/agents/agent_definitions.py`)
Three specialized agents work together:

1. **CV Analysis Agent** - Extracts skills and experiences from your CV
2. **Job Analysis Agent** - Analyzes job requirements and expectations  
3. **Recommendation Agent** - Synthesizes insights and provides personalized advice

### Orchestration Patterns

**MVP (Group Chat):**
- Uses Microsoft Agent Framework Group Chat pattern
- Sequential agent execution with message passing
- Proven and reliable orchestration

**WorkflowBuilder V1:**
- Pure Microsoft Agent Framework WorkflowBuilder
- `@executor` functions with conditional routing
- Enhanced user experience features:
  - Thread-based conversation memory
  - Streaming responses with `agent.run_stream()`
  - Dynamic routing based on Q&A needs

## 📁 File Structure

```
Application_Buddy/
├── main_mvp.py                 # MVP Group Chat implementation
├── main_workflow_v1.py         # WorkflowBuilder V1 with streaming
├── main_interactive.py         # Original manual conversation
├── main.py                     # Basic demo
├── requirements.txt            # Dependencies
└── src/
    ├── agents/
    │   ├── agent_definitions.py    # Enhanced agent prompts
    │   └── optimized_orchestrator.py  # MVP orchestrator
    └── config.py               # Configuration
```

## 💡 Usage Tips

**Which version should you use?**
- 🎯 **New users:** Start with `main_workflow_v1.py` for the best experience
- 🛡️ **Stability-first:** Use `main_mvp.py` for proven reliability  
- 📝 **Single job focus:** Try `main_interactive.py` for hands-on conversation
- 🔬 **Development/Demo:** Use `main.py` for basic agent testing

**Preparing your files:**
- **CV file:** Include your complete work history, skills, education, projects
- **Job descriptions:** Copy full job postings, not just bullet points
- **Multiple jobs:** Separate job descriptions with clear headers in the file

## 🔧 Technical Details

**Dependencies:** Microsoft Agent Framework, Azure AI Foundry
**Python Version:** 3.8+
**AI Models:** Uses Azure-hosted models via Agent Framework
**File Support:** Plain text files for CV and job descriptions

## 🤝 Contributing

This project uses Microsoft Agent Framework best practices:
- Agent prompts in dedicated definition files
- Clean separation of orchestration and agent logic  
- Thread-based conversation memory for Q&A continuity
- Streaming responses for enhanced user experience

## 🎯 Example Workflow

1. **Setup:** Fill `text_examples/my_cv.txt` and `text_examples/job_descriptions.txt`
2. **Analysis:** Run `python main_workflow_v1.py`  
3. **Review:** Get comprehensive match analysis
4. **Q&A:** If gaps found, engage in streaming conversation about your experiences
5. **Decision:** Receive personalized recommendation on whether to apply

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
