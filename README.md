# InboxPilot

An autonomous email triage agent powered by Claude. Connects to Gmail, classifies incoming emails, applies labels, drafts replies, and schedules follow-ups — all without human intervention.

**Primary goal:** Keep unread inbox count below 10 while ensuring no high-priority emails are missed.

---

## How it works

The agent runs a continuous loop every 5 minutes:

1. Fetch unread emails from Gmail
2. Classify each email via Claude (category + priority score 1–10)
3. Apply Gmail labels based on priority
4. Generate draft replies for emails that require a response
5. Schedule Google Calendar follow-ups for high-priority threads
6. Update sender memory in SQLite
7. Log all decisions

Every Sunday at 08:00 UTC, a reflection cycle runs — Claude reviews the week's performance and suggests improvements to the prioritization logic.

---

## Priority rules

| Score | Behaviour |
|-------|-----------|
| 8–10  | Immediate alert (console + `INBOXPILOT/IMMEDIATE` label) |
| 5–7   | Standard label applied |
| 1–4   | Auto-archived if inbox is over the unread goal |

Hard constraints:
- `internship` and `recruiter` emails: priority is always ≥ 7
- `promotional` emails: priority is always ≤ 4

---

## Project structure

```
InboxPilot/
├── main.py                     # Entry point
├── config.py                   # Settings loaded from .env
├── requirements.txt
├── .env.example
│
├── prompts/                    # Version-controlled Claude prompts
│   ├── classify.txt
│   ├── draft.txt
│   └── reflect.txt
│
├── integrations/
│   ├── claude.py               # Claude API wrapper (with retry logic)
│   ├── gmail.py                # Gmail: fetch, label, archive, draft
│   └── calendar.py             # Google Calendar: follow-up reminders
│
├── agents/
│   ├── classifier.py           # Claude Task 1 — email classification
│   ├── drafter.py              # Claude Task 2 — reply generation
│   └── reflector.py            # Claude Task 3 — weekly reflection
│
├── memory/
│   ├── models.py               # Pydantic data models
│   └── database.py             # SQLite CRUD (sender memory, logs)
│
├── scheduler/
│   ├── loop.py                 # Main agent cycle + APScheduler setup
│   └── follow_up.py            # Follow-up draft + calendar reminder
│
└── utils/
    └── logger.py               # Structured decision logging
```

---

## Setup

### 1. Prerequisites

- Python 3.10+
- A Google Cloud project with Gmail API and Google Calendar API enabled
- An Anthropic API key

### 2. Google OAuth credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project and enable **Gmail API** and **Google Calendar API**
3. Create an OAuth 2.0 Desktop App credential
4. Download the JSON file and save it as `credentials.json` in the project root

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in:

```
ANTHROPIC_API_KEY=your_key_here
GOOGLE_CREDENTIALS_FILE=credentials.json
GOOGLE_TOKEN_FILE=token.json
POLL_INTERVAL_MINUTES=5
FOLLOW_UP_HOURS=24
UNREAD_GOAL=10
DATABASE_PATH=inboxpilot.db
```

### 5. Run

```bash
python main.py
```

On first run, a browser window will open for Google OAuth authorisation. After granting access, a `token.json` file is saved and the agent starts immediately.

---

## Database

SQLite is used for all persistent state. Four tables are maintained automatically:

- `sender_memory` — per-sender importance scores and category history
- `performance_memory` — weekly accuracy and response time stats
- `action_log` — full record of every decision made
- `reflection_log` — output from each weekly Claude reflection

---

## Configuration reference

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | — | Required. Your Anthropic API key |
| `GOOGLE_CREDENTIALS_FILE` | `credentials.json` | Path to Google OAuth credentials |
| `GOOGLE_TOKEN_FILE` | `token.json` | Path where the OAuth token is saved |
| `POLL_INTERVAL_MINUTES` | `5` | How often the agent checks for new email |
| `FOLLOW_UP_HOURS` | `24` | Hours before a follow-up reminder is created |
| `UNREAD_GOAL` | `10` | Target maximum unread count |
| `DATABASE_PATH` | `inboxpilot.db` | SQLite database file path |

---

## Notes

- Emails are never sent automatically. All replies are saved as Gmail drafts only.
- Full email bodies are not stored beyond the processing window.
- All Claude calls use temperature ≤ 0.3 for deterministic outputs.
- OAuth tokens (`token.json`) and credentials (`credentials.json`) are excluded from git.
