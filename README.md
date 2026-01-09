# Application Buddy 🎯

**Stop mass-applying. Start strategically applying.**

Application Buddy is an AI-powered job application assistant that helps you make smarter decisions about which jobs to apply for. Instead of the "spray and pray" approach of mass applications, Application Buddy analyzes your CV against each job posting and tells you honestly whether it's worth your time.

[![Azure](https://img.shields.io/badge/Azure-AI%20Foundry-0078D4?logo=microsoft-azure)](https://ai.azure.com)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-UI-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io)

---

## 📋 Table of Contents

- [The Problem](#the-problem-with-mass-applications)
- [How It Helps](#how-application-buddy-helps)
- [Architecture Overview](#-architecture-overview)
- [Azure Services](#-azure-services)
- [Agent Orchestration](#-agent-orchestration)
- [User Interface](#-user-interface)
- [LinkedIn Integration](#-linkedin-integration)
- [Getting Started](#-getting-started)
- [Monitoring & Logs](#-monitoring--logs)

---

## The Problem with Mass Applications

Modern job seekers face a paradox:
- Job platforms make it easy to apply with one click
- Applicant Tracking Systems (ATS) filter out most applications automatically  
- Mass-applying leads to low response rates and wasted effort
- You end up applying for jobs you're not qualified for, missing jobs you'd be great at

**The result:** Hours spent on applications that never get seen, burnout, and no strategic improvement in your job search.

---

## How Application Buddy Helps

Application Buddy acts as your personal job search strategist:

| Feature | Description |
|---------|-------------|
|  **Analyzes Fit** | Compares your CV against job requirements using AI |
|  **Identifies Gaps** | Shows exactly which skills/experiences you're missing |
|  **Asks Clarifying Questions** | Discovers hidden qualifications not on your CV |
|  **Gives Honest Recommendations** | Tells you whether to apply, prepare first, or skip |
|  **Tracks Your Profile** | Builds a pattern of your applications to give better advice over time |
|  **LinkedIn Integration** | Syncs your saved jobs directly from LinkedIn |

---

##  Architecture Overview

### High-Level System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    APPLICATION BUDDY                                        │
│                              AI-Powered Job Application Assistant                           │
└─────────────────────────────────────────────────────────────────────────────────────────────┘

┌──────────────────┐     ┌─────────────────────────────────────────────────────────────────────┐
│                  │     │                         AZURE CLOUD                                 │
│   USER DEVICE    │     │  ┌─────────────────────────────────────────────────────────────┐   │
│                  │     │  │                    AZURE AI FOUNDRY                         │   │
│  ┌────────────┐  │     │  │  ┌─────────────────────────────────────────────────────┐   │   │
│  │            │  │     │  │  │              MULTI-AGENT SYSTEM                     │   │   │
│  │ Streamlit  │◄─┼─────┼──┼──┤  ┌─────────┐  ┌──────────┐  ┌─────────┐            │   │   │
│  │    UI      │  │     │  │  │  │  BRAIN  │  │ ANALYZER │  │   Q&A   │            │   │   │
│  │            │  │     │  │  │  │  Agent  │─►│  Agent   │─►│  Agent  │            │   │   │
│  └─────┬──────┘  │     │  │  │  └─────────┘  └──────────┘  └────┬────┘            │   │   │
│        │         │     │  │  │                                  │                  │   │   │
│        │         │     │  │  │  ┌────────────┐  ┌───────────────┴───┐             │   │   │
│        │         │     │  │  │  │ VALIDATION │  │   RECOMMENDER     │             │   │   │
│  ┌─────▼──────┐  │     │  │  │  │   Agent    │  │      Agent        │             │   │   │
│  │  LinkedIn  │  │     │  │  │  └────────────┘  └───────────────────┘             │   │   │
│  │   Login    │  │     │  │  └─────────────────────────────────────────────────────┘   │   │
│  │(Playwright)│  │     │  │                           │                                │   │
│  └────────────┘  │     │  │                           ▼                                │   │
│                  │     │  │               ┌───────────────────────┐                    │   │
└──────────────────┘     │  │               │   Azure OpenAI (GPT)  │                    │   │
                         │  │               │     gpt-4o model      │                    │   │
                         │  │               └───────────────────────┘                    │   │
                         │  └─────────────────────────────────────────────────────────────┘   │
                         │                                                                    │
                         │  ┌─────────────────────────────────────────────────────────────┐   │
                         │  │                    AZURE SERVICES                           │   │
                         │  │                                                             │   │
                         │  │  ┌───────────────┐  ┌────────────────┐  ┌───────────────┐  │   │
                         │  │  │   Document    │  │    Language    │  │    Blob       │  │   │
                         │  │  │ Intelligence  │  │    Service     │  │   Storage     │  │   │
                         │  │  │  (PDF Parse)  │  │  (Text NLP)    │  │ (User Data)   │  │   │
                         │  │  └───────────────┘  └────────────────┘  └───────────────┘  │   │
                         │  │                                                             │   │
                         │  │  ┌───────────────┐  ┌────────────────┐  ┌───────────────┐  │   │
                         │  │  │  Application  │  │ Log Analytics  │  │    Azure      │  │   │
                         │  │  │   Insights    │  │   Workspace    │  │    Search     │  │   │
                         │  │  │  (Telemetry)  │  │    (Logs)      │  │   (Index)     │  │   │
                         │  │  └───────────────┘  └────────────────┘  └───────────────┘  │   │
                         │  └─────────────────────────────────────────────────────────────┘   │
                         └────────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    DATA FLOW                                                │
└─────────────────────────────────────────────────────────────────────────────────────────────┘

  ┌──────────┐          ┌──────────────┐          ┌───────────────┐          ┌─────────────┐
  │   User   │          │   Streamlit  │          │  Azure AI     │          │   Azure     │
  │          │          │      UI      │          │   Foundry     │          │  Services   │
  └────┬─────┘          └──────┬───────┘          └───────┬───────┘          └──────┬──────┘
       │                       │                          │                         │
       │  1. Upload CV (PDF)   │                          │                         │
       │──────────────────────►│                          │                         │
       │                       │  2. Parse PDF            │                         │
       │                       │─────────────────────────────────────────────────────►
       │                       │                          │    Document Intelligence
       │                       │◄─────────────────────────────────────────────────────
       │                       │  3. Extracted Text       │                         │
       │                       │                          │                         │
       │  4. Paste Job URL     │                          │                         │
       │  (or sync LinkedIn)   │                          │                         │
       │──────────────────────►│                          │                         │
       │                       │  5. Send to Agent        │                         │
       │                       │─────────────────────────►│                         │
       │                       │                          │  6. Analyze with GPT    │
       │                       │                          │─────────────────────────►
       │                       │                          │◄─────────────────────────
       │                       │                          │                         │
       │                       │  7. Analysis Results     │                         │
       │                       │◄─────────────────────────│                         │
       │  8. Q&A + Recommend   │                          │                         │
       │◄──────────────────────│                          │                         │
       │                       │                          │                         │
       │  9. Save Profile      │                          │                         │
       │                       │─────────────────────────────────────────────────────►
       │                       │                          │        Blob Storage     │
       │                       │                          │                         │
       │  10. Log Feedback     │                          │                         │
       │──────────────────────►│─────────────────────────────────────────────────────►
       │                       │                          │    Application Insights │
       └───────────────────────┴──────────────────────────┴─────────────────────────┘
```

---

##  Azure Services

Application Buddy leverages the following Azure services:

| Service | Purpose | Resource Name |
|---------|---------|---------------|
| **Azure AI Foundry** | Multi-agent orchestration & hosting | `ai-project-application_buddy_env` |
| **Azure OpenAI** | GPT-4o model for intelligent analysis | Deployed in AI Foundry |
| **Azure AI Content Safety** | Guardrails & content filtering (see below) | Foundry built-in |
| **Document Intelligence** | PDF parsing and text extraction from CVs | Cognitive Services |

### Azure AI Content Safety (Guardrails)

The application uses Azure AI Foundry's built-in content safety to protect against:

| Protection | Description |
|------------|-------------|
| **Jailbreak Attempts** | Detects and blocks attempts to bypass system instructions |
| **Prompt Injection** | Prevents malicious prompts from manipulating agent behavior |
| **Violence** | Filters violent content and threats |
| **Self-Harm** | Blocks content promoting self-harm or suicide |
| **Sexual Content** | Filters inappropriate sexual material |
| **Hate Speech** | Detects and blocks discriminatory content |

These guardrails are automatically applied to all agent interactions through Azure AI Foundry's content filtering pipeline.
| **Language Service** | NLP for skill extraction and text analysis | Cognitive Services |
| **Blob Storage** | User profile persistence across sessions | Storage Account |
| **Azure Search** | Indexing and retrieval (future: job matching) | AI Search |
| **Application Insights** | Telemetry, user feedback, error tracking | `appi-*` |
| **Log Analytics** | Centralized logging and diagnostics | Workspace |
| **Container Registry** | Docker images for agent deployment | ACR |

### Infrastructure as Code

All Azure resources are defined in Bicep templates under `/infra`:

```
infra/
├── main.bicep                    # Main orchestration
├── main.parameters.json          # Environment parameters
├── abbreviations.json            # Resource naming conventions
└── core/
    ├── ai/
    │   ├── ai-project.bicep      # Azure AI Foundry project
    │   └── connection.bicep      # Service connections
    ├── host/
    │   └── acr.bicep             # Container Registry
    ├── monitor/
    │   ├── applicationinsights.bicep
    │   ├── applicationinsights-dashboard.bicep
    │   └── loganalytics.bicep
    ├── search/
    │   ├── azure_ai_search.bicep
    │   ├── bing_grounding.bicep
    │   └── bing_custom_grounding.bicep
    └── storage/
        └── storage.bicep
```

---

##  Agent Orchestration

Application Buddy uses a **state-based multi-agent workflow** with 5 specialized AI agents:

### Agent Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                              MULTI-AGENT WORKFLOW                                           │
└─────────────────────────────────────────────────────────────────────────────────────────────┘

                                    ┌─────────────────┐
                                    │      USER       │
                                    │   (Streamlit)   │
                                    └────────┬────────┘
                                             │
                                             ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│  STATE: COLLECTING                                                                          │
│  ┌────────────────────────────────────────────────────────────────────────────────────────┐ │
│  │                           🧠 BRAIN AGENT                                               │ │
│  │  • Role: Conversational Interface                                                      │ │
│  │  • Greets user warmly                                                                  │ │
│  │  • Collects CV (PDF upload or paste)                                                   │ │
│  │  • Collects Job Description (URL or paste)                                             │ │
│  │  • Handles natural conversation flow                                                   │ │
│  └────────────────────────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────┬────────────────────────────────────────────────┘
                                             │ Both CV & JD collected
                                             ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│  STATE: ANALYZING                                                                           │
│  ┌────────────────────────────────────────────────────────────────────────────────────────┐ │
│  │                           🔬 ANALYZER AGENT                                            │ │
│  │  • Role: Deep Analysis Engine                                                          │ │
│  │  • Extracts skills from CV (technical, soft, certifications)                           │ │
│  │  • Parses job requirements (must-have vs nice-to-have)                                 │ │
│  │  • Calculates match score (0-100%)                                                     │ │
│  │  • Identifies skill gaps                                                               │ │
│  │  • Outputs structured JSON analysis                                                    │ │
│  └────────────────────────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────┬────────────────────────────────────────────────┘
                                             │ Analysis complete
                                             ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│  STATE: Q&A                                                                                 │
│  ┌──────────────────────────────────────┐  ┌────────────────────────────────────────────┐  │
│  │           Q&A AGENT                  │  │          VALIDATION AGENT                 │  │
│  │  • Role: Gap Investigator            │  │  • Role: Real-time Gap Tracker            │  │
│  │  • Asks about identified gaps        │  │  • Monitors user responses                │  │
│  │  • Probes for hidden skills         ◄┼──┼─►• Evaluates "Did this fill gap?"         │  │
│  │  • Uncovers unlisted certs           │  │  • Updates gap list dynamically           │  │
│  │  • Natural conversation style        │  │  • Tracks must-have vs nice-to-have       │  │
│  └──────────────────────────────────────┘  └────────────────────────────────────────────┘  │
└────────────────────────────────────────────┬────────────────────────────────────────────────┘
                                             │ User says "done" or all gaps addressed
                                             ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│  STATE: VIEWING_RECOMMENDATION                                                              │
│  ┌────────────────────────────────────────────────────────────────────────────────────────┐ │
│  │                              RECOMMENDER AGENT                                         │ │
│  │  • Role: Strategic Advisor                                                             │ │
│  │  • Synthesizes all gathered information                                                │ │
│  │  • Makes APPLY / PREPARE / SKIP recommendation                                         │ │
│  │  • Provides reasoning and action items                                                 │ │
│  │  • Suggests resume improvements                                                        │ │
│  │  • Offers interview preparation tips                                                   │ │
│  └────────────────────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

### State Machine

```
┌───────────┐     ┌───────────┐     ┌─────┐     ┌────────────────────────┐     ┌──────────┐
│ COLLECTING│────►│ ANALYZING │────►│ Q&A │────►│ VIEWING_RECOMMENDATION │────►│ COMPLETE │
└───────────┘     └───────────┘     └──┬──┘     └────────────────────────┘     └──────────┘
      ▲                                │                                             │
      │                                │                                             │
      └────────────────────────────────┴─────────────────────────────────────────────┘
                              (user can analyze another job)
```

| State | Description | Active Agent(s) |
|-------|-------------|-----------------|
| `collecting` | Natural conversation to gather CV and job posting | Brain Agent |
| `analyzing` | Deep comparison, extracts structured data | Analyzer Agent |
| `qna` | Asks about gaps, validates answers in real-time | Q&A + Validation Agents |
| `viewing_recommendation` | User browses recommendation via numbered menu | Recommender Agent |
| `complete` | Session finished, can start new analysis | - |

### The Validation Agent Innovation

The **Validation Agent** makes the Q&A phase intelligent by tracking gap resolution in real-time:

```python
# Validation Agent Output Schema
{
    "addressed_gap": "Docker experience",           # Which gap was filled
    "remaining_must_have_gaps": [...],              # Updated list
    "remaining_nice_to_have_gaps": [...],           # Updated list  
    "user_answer_summary": "5 years Docker in prod" # What user said
}
```

---

##  LinkedIn Integration

Application Buddy includes a **LinkedIn Saved Jobs Scraper** that syncs your bookmarked jobs directly into the app.

### LinkedIn Scraper Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                              LINKEDIN INTEGRATION                                           │
└─────────────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│   Streamlit     │      │   Playwright    │      │    LinkedIn     │      │   Job Cards     │
│   Sidebar       │─────►│   Browser       │─────►│   Website       │─────►│   Display       │
│   "Sync" btn    │      │  (Chromium)     │      │  /my-items/     │      │   in UI         │
└─────────────────┘      └────────┬────────┘      └─────────────────┘      └─────────────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │  Session State  │
                         │  (state.json)   │
                         │  Persists login │
                         └─────────────────┘
```

### Features

| Feature | Description |
|---------|-------------|
| **Persistent Login** | Saves LinkedIn session to avoid repeated logins |
| **Two-Phase Scraping** | Quick list sync, then fetch full description on click |
| **Visible Browser** | Uses non-headless mode (LinkedIn blocks headless) |
| **Job Card Display** | Shows title, company, location styled like LinkedIn |

### How It Works

1. **Click "Sync from LinkedIn"** in the sidebar
2. **Browser opens** - log in if needed (first time only)
3. **Jobs appear** in the sidebar as clickable cards
4. **Click a job** to fetch full description and analyze it

### Files

```
devui/
├── linkedin_savedjobs.py   # Playwright scraper
├── linkedin_auth.py        # Authentication helper
└── streamlit_app.py        # UI integration
```

---

##  User Interface

### Streamlit UI Pattern

The Streamlit UI (`devui/streamlit_app.py`) provides:

- **Chat interface** - Natural conversation with the agent
- **PDF upload** - Attach your CV directly (sidebar)
- **Quick reply buttons** - Contextual buttons like "Go" and "Done" appear when relevant
- **Per-message feedback** - Rate each response (saved to Application Insights)
- **Reset controls** - New conversation / Reset profile buttons

### How to Upload Your CV

1. Click the **sidebar** (left panel) or look for "📎 Attach CV"
2. Click **"Browse files"** and select your PDF
3. You'll see a confirmation: "✓ filename.pdf - Will be sent with your next message"
4. Type any message (e.g., "hi" or "here's my CV") and send
5. The CV will be automatically attached and parsed

### Quick Reply Buttons

The UI detects conversation context and shows helpful buttons:

| Context | Button |
|---------|--------|
| "Just say 'go' and I'll dive in" | 🚀 **Go** |
| "Type 'done' when finished" | ✓ **Done** |

### Feedback System

After each assistant message, you'll see a collapsible "How did I do?" section:
- ⭐ Star rating (1-5)
- Optional comment
- Click "Send" to submit

Feedback is sent to **Azure Application Insights** for analysis.

---

##  Monitoring & Logs

### Application Insights

All telemetry flows to Application Insights resource: `appi-d2zwldhwlzgkg`

#### Viewing Feedback

1. Go to [Azure Portal](https://portal.azure.com) → Application Insights → `appi-d2zwldhwlzgkg`
2. Click **Logs** in the left sidebar
3. Run this query:

```kusto
customEvents
| where name == "UserFeedback"
| extend rating = toint(customDimensions.rating)
| extend comment = tostring(customDimensions.comment)
| project timestamp, rating, comment
| order by timestamp desc
```

#### Useful Queries

**Average rating over time:**
```kusto
customEvents
| where name == "UserFeedback"
| extend rating = toint(customDimensions.rating)
| summarize avg(rating), count() by bin(timestamp, 1d)
| render timechart
```

**Low ratings with comments (for improvement):**
```kusto
customEvents
| where name == "UserFeedback"
| extend rating = toint(customDimensions.rating)
| extend comment = tostring(customDimensions.comment)
| where rating <= 2 and comment != ""
| project timestamp, rating, comment
```

### Agent Logs

The deployed agent logs to the Foundry workspace. To view:

1. Go to [Azure AI Foundry](https://ai.azure.com)
2. Navigate to your project: `ai-project-application_buddy_env`
3. Go to **Agents** → `StateBasedTeamsAgent`
4. Click on a deployment version to see logs

---

## �� Getting Started

### Prerequisites

- [Azure CLI](https://docs.microsoft.com/cli/azure/install-azure-cli)
- [Azure Developer CLI (azd)](https://aka.ms/install-azd)
- Python 3.11+
- An Azure subscription

### Local Development

1. **Clone and setup:**
   ```bash
   git clone <repo-url>
   cd Application_Buddy
   python -m venv venv
   source venv/bin/activate  # or venv\Scripts\activate on Windows
   pip install -r requirements.txt
   ```

2. **Login to Azure:**
   ```bash
   az login
   azd auth login
   ```

3. **Provision infrastructure:**
   ```bash
   azd provision
   ```

4. **Deploy the agent:**
   ```bash
   azd deploy
   ```

5. **Run the Streamlit UI:**
   ```bash
   cd devui
   streamlit run streamlit_app.py
   ```

6. **Open browser:** http://localhost:8501

### Environment Variables

| Variable | Description |
|----------|-------------|
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint |
| `AZURE_OPENAI_DEPLOYMENT` | Model deployment name (e.g., gpt-4o) |
| `AZURE_STORAGE_ACCOUNT_NAME` | Storage account for user profiles (optional) |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | App Insights for telemetry |

---

##  Project Structure

```
Application_Buddy/
├── azure.yaml                      # Azure Developer CLI configuration
├── requirements.txt                # Python dependencies
├── README.md                       # This file
│
├── infra/                          # 🏗️ Infrastructure as Code (Bicep)
│   ├── main.bicep                  # Main orchestration template
│   ├── main.parameters.json        # Environment parameters
│   ├── abbreviations.json          # Azure resource naming conventions
│   └── core/
│       ├── ai/
│       │   ├── ai-project.bicep    # Azure AI Foundry project
│       │   └── connection.bicep    # Service connections
│       ├── host/
│       │   └── acr.bicep           # Azure Container Registry
│       ├── monitor/
│       │   ├── applicationinsights.bicep
│       │   ├── applicationinsights-dashboard.bicep
│       │   └── loganalytics.bicep
│       ├── search/
│       │   ├── azure_ai_search.bicep
│       │   ├── bing_grounding.bicep
│       │   └── bing_custom_grounding.bicep
│       └── storage/
│           └── storage.bicep
│
├── src/                            # 🤖 Agent Source Code
│   ├── __init__.py
│   ├── config.py                   # Shared configuration
│   └── StateBasedTeamsAgent/       # Main multi-agent system
│       ├── agent.yaml              # Agent manifest for deployment
│       ├── main.py                 # Entry point
│       ├── workflow.py             # State machine & agent orchestration
│       ├── agent_definitions.py    # Agent prompts, instructions & schemas
│       ├── document_processor.py   # PDF/document handling
│       ├── config.py               # Agent-specific config
│       ├── requirements.txt        # Agent dependencies
│       └── Dockerfile              # Container image definition
│
├── devui/                          # 🖥️ Development UI (Streamlit)
│   ├── streamlit_app.py            # Main UI application
│   ├── linkedin_savedjobs.py       # LinkedIn scraper (Playwright)
│   ├── linkedin_auth.py            # LinkedIn authentication helper
│   └── feedback_log.json           # Local feedback storage
│
├── playwright/                     # 🌐 Browser Automation
│   └── .auth/
│       └── state.json              # Persisted LinkedIn session
│
├── text_examples/                  # 📄 Sample Data
│   ├── my_cv.txt                   # Example CV for testing
│   └── job_descriptions.txt        # Example job postings
│
└── docs/                           # 📚 Documentation
    └── azd-files/
        ├── CHANGELOG.md
        ├── CONTRIBUTING.md
        ├── LICENSE.md
        ├── SECURITY.md
        └── SUPPORT.md
```

---

## 🔧 Commands Reference

### Azure Developer CLI (azd)

| Command | Description |
|---------|-------------|
| `azd provision` | Create/update Azure infrastructure |
| `azd deploy` | Deploy agent to Azure AI Foundry |
| `azd up` | Provision + Deploy in one command |
| `azd down` | Delete all Azure resources |
| `azd env list` | List environments |
| `azd env select <name>` | Switch environment |

### Local Development

| Command | Description |
|---------|-------------|
| `streamlit run devui/streamlit_app.py` | Run the UI locally |
| `python devui/linkedin_auth.py` | Test LinkedIn authentication |
| `az login` | Refresh Azure CLI credentials |
| `azd auth login` | Refresh AZD credentials |

### In-App Commands

| Command | Description |
|---------|-------------|
| `reset` | Start a new conversation |
| `reset profile` | Clear your application history |
| `done` | Skip remaining Q&A and get recommendation |
| `profile` | View your application history and patterns |
| `1`, `2`, `3`... | Select menu items in recommendation view |

---

## 🛡️ Security

| Feature | Implementation |
|---------|----------------|
| **Managed Identity** | Keyless authentication between Azure services |
| **No secrets in code** | All credentials via `DefaultAzureCredential` |
| **Data isolation** | User profiles keyed by conversation ID |
| **Session persistence** | LinkedIn auth stored locally, not in cloud |

---

## 🚀 Deployment

### Prerequisites

- [Azure CLI](https://docs.microsoft.com/cli/azure/install-azure-cli)
- [Azure Developer CLI (azd)](https://aka.ms/install-azd)
- Python 3.11+
- An Azure subscription with appropriate permissions

### Quick Start

```bash
# 1. Clone the repository
git clone <repo-url>
cd Application_Buddy

# 2. Login to Azure
az login
azd auth login

# 3. Provision and deploy (one command)
azd up

# 4. Run the UI locally
streamlit run devui/streamlit_app.py
```

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint | Yes |
| `AZURE_OPENAI_DEPLOYMENT` | Model deployment name (e.g., gpt-4o) | Yes |
| `AZURE_STORAGE_ACCOUNT_NAME` | Storage account for user profiles | Optional |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | App Insights for telemetry | Optional |

---

## 📄 License

See [LICENSE.md](docs/azd-files/LICENSE.md)

---

## 🙏 Acknowledgments

Built with:
- [Azure AI Foundry](https://ai.azure.com) - Multi-agent orchestration
- [Azure Agent Framework](https://github.com/microsoft/agent-framework) - Agent SDK
- [Streamlit](https://streamlit.io) - Web UI framework
- [Playwright](https://playwright.dev) - Browser automation for LinkedIn
- [Azure Developer CLI](https://aka.ms/azd) - Infrastructure deployment

---

## 📞 Support

- **Issues**: Open a GitHub issue
- **Questions**: See [SUPPORT.md](docs/azd-files/SUPPORT.md)
- **Contributing**: See [CONTRIBUTING.md](docs/azd-files/CONTRIBUTING.md)
