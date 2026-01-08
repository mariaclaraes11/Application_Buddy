# Application Buddy 🎯

**Stop mass-applying. Start strategically applying.**

Application Buddy is an AI-powered job application assistant that helps you make smarter decisions about which jobs to apply for. Instead of the "spray and pray" approach of mass applications, Application Buddy analyzes your CV against each job posting and tells you honestly whether it's worth your time.

## The Problem with Mass Applications

Modern job seekers face a paradox:
- Job platforms make it easy to apply with one click
- Applicant Tracking Systems (ATS) filter out most applications automatically  
- Mass-applying leads to low response rates and wasted effort
- You end up applying for jobs you're not qualified for, missing jobs you'd be great at

**The result:** Hours spent on applications that never get seen, burnout, and no strategic improvement in your job search.

## How Application Buddy Helps

Application Buddy acts as your personal job search strategist:

1. **Analyzes fit** - Compares your CV against job requirements
2. **Identifies gaps** - Shows exactly which skills/experiences you're missing
3. **Asks clarifying questions** - Discovers hidden qualifications not on your CV
4. **Gives honest recommendations** - Tells you whether to apply, prepare first, or skip
5. **Tracks your profile** - Builds a pattern of your applications to give better advice over time

---

## 🏗️ Architecture

### Agent Orchestration

Application Buddy uses a **state-based multi-agent workflow** with 5 specialized agents:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CONVERSATION FLOW                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   User                                                              │
│     │                                                               │
│     ▼                                                               │
│  ┌──────────┐                                                       │
│  │  BRAIN   │  ← Conversational interface                           │
│  │  Agent   │    Collects CV + Job Description                      │
│  └────┬─────┘                                                       │
│       │ Both collected                                              │
│       ▼                                                             │
│  ┌──────────┐                                                       │
│  │ ANALYZER │  ← Deep CV vs Job analysis                            │
│  │  Agent   │    Extracts skills, gaps, score                       │
│  └────┬─────┘                                                       │
│       │                                                             │
│       ▼                                                             │
│  ┌──────────┐     ┌────────────┐                                    │
│  │   Q&A    │ ←──►│ VALIDATION │  ← Tracks remaining gaps           │
│  │  Agent   │     │   Agent    │    Detects when user answers gap   │
│  └────┬─────┘     └────────────┘                                    │
│       │ User says "done" or all gaps addressed                      │
│       ▼                                                             │
│  ┌──────────────┐                                                   │
│  │ RECOMMENDER  │  ← Final recommendation                           │
│  │    Agent     │    Based on updated gap analysis                  │
│  └──────────────┘                                                   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### State Machine

```
COLLECTING → ANALYZING → Q&A → VIEWING_RECOMMENDATION → COMPLETE
     ↑                    │
     └────────────────────┘  (user can analyze another job)
```

| State | Description |
|-------|-------------|
| `collecting` | Brain agent has natural conversation, collects CV and job posting |
| `analyzing` | Analyzer agent performs deep comparison, extracts structured data |
| `qna` | Q&A agent asks about gaps; Validation agent tracks which gaps are addressed |
| `viewing_recommendation` | User browses recommendation sections via numbered menu |
| `complete` | Session finished, can start new analysis |

### The Validation Agent

The **Validation Agent** is a key innovation that makes the Q&A phase intelligent:

- Receives the original gap list from the Analyzer
- After each user response, evaluates: "Did this address any gaps?"
- Updates the gap list in real-time
- Enables accurate final recommendations based on actual remaining gaps

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

## 🖥️ User Interface

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

## 📊 Monitoring & Logs

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

## 📁 Project Structure

```
Application_Buddy/
├── azure.yaml                 # azd configuration
├── infra/                     # Bicep infrastructure
│   ├── main.bicep
│   └── core/                  # Modular infrastructure
├── src/
│   └── StateBasedTeamsAgent/  # Main agent code
│       ├── agent.yaml         # Agent manifest
│       ├── workflow.py        # Multi-agent orchestration
│       ├── agent_definitions.py # Agent prompts & schemas
│       ├── config.py          # Configuration
│       └── main.py            # Entry point
├── devui/
│   └── streamlit_app.py       # Local development UI
└── text_examples/             # Sample CVs and job descriptions
```

---

## 🔧 Commands Reference

| Command | Description |
|---------|-------------|
| `azd provision` | Create/update Azure infrastructure |
| `azd deploy` | Deploy agent to Azure AI Foundry |
| `azd down` | Delete all Azure resources |
| `streamlit run devui/streamlit_app.py` | Run local UI |

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

- **Managed Identity** - Keyless authentication between Azure services
- **No secrets in code** - All credentials via Azure Identity
- **Data isolation** - User profiles keyed by conversation ID

---

## 📄 License

See [LICENSE.md](docs/azd-files/LICENSE.md)

---

## 🙏 Acknowledgments

Built with:
- [Azure AI Foundry](https://ai.azure.com)
- [Agent Framework](https://github.com/microsoft/agent-framework)
- [Streamlit](https://streamlit.io)
- [Azure Developer CLI](https://aka.ms/azd)
