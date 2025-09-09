import os
from dotenv import load_dotenv
load_dotenv()
import base64
from openai import AzureOpenAI
import json
import re
from typing import List, Optional
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
import random
from pydantic import BaseModel


class ActionItem(BaseModel):
    title: str
    owner: Optional[str] = None
    due_date: Optional[str] = None    
    priority: Optional[str] = "medium"
    details: Optional[str] = None
    task_id: Optional[str] = None

class Insights(BaseModel):
    summary: str
    decisions: List[str] = []
    action_items: List[ActionItem] = []


# ---------- Owner & due-date helpers ----------

WEEKDAYS = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
WD2IDX = {d:i for i,d in enumerate(WEEKDAYS)}
LOCAL_TZ = ZoneInfo("Asia/Kolkata")
DEFAULT_SPEAKER = os.getenv("DEFAULT_SPEAKER", "You")  # set to your name if you like

def next_weekday(base_dt: date, target_idx: int, *, next_flag: bool=False) -> date:
    """Return the next occurrence of weekday `target_idx` (0=Mon)."""
    cur_idx = base_dt.weekday()
    delta = (target_idx - cur_idx) % 7
    if delta == 0 or next_flag:
        delta = 7 if delta == 0 else delta
    return base_dt + timedelta(days=delta)

def extract_due_phrase(s: str) -> Optional[str]:
    """Pick a human phrase we recognized; helps keep details readable."""
    s_low = s.lower()
    m = re.search(r"\bby\s+(next\s+\w+day|\w+day)\b", s_low)      # by Friday / by next Wednesday
    if m: return m.group(0)
    m = re.search(r"\bnext\s+(\w+day)\b", s_low)                  # next Wednesday
    if m: return m.group(0)
    m = re.search(r"\bon\s+(\w+day)\b", s_low)                    # on Wednesday
    if m: return m.group(0)
    if "tomorrow" in s_low: return "tomorrow"
    if "today" in s_low: return "today"
    return None

def resolve_due_date(phrase: Optional[str], now: Optional[datetime] = None) -> Optional[str]:
    """
    Convert phrases like 'by Friday', 'next Wednesday', 'tomorrow', 'today'
    into ISO date (YYYY-MM-DD) in Asia/Kolkata local time.
    """
    if not phrase:
        return None
    p = phrase.strip().lower()
    now = now or datetime.now(LOCAL_TZ)
    base = now.date()

    if "today" in p:
        return base.isoformat()
    if "tomorrow" in p:
        return (base + timedelta(days=1)).isoformat()

    m = re.search(r"(?:by|on)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", p)
    if m:
        w = m.group(1)
        return next_weekday(base, WD2IDX[w]).isoformat()

    m = re.search(r"next\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", p)
    if m:
        w = m.group(1)
        return next_weekday(base, WD2IDX[w], next_flag=True).isoformat()

    m = re.search(r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", p)
    if m:
        w = m.group(1)
        return next_weekday(base, WD2IDX[w]).isoformat()

    return None

def split_multi_owner(sentence: str) -> list[tuple[str, str]]:
    """
    Extract each '<Owner> will <verb phrase>' separately, even with multiple owners.
    'I will draft the email and Alice will review it.'
      -> [('You','draft the email'), ('Alice','review it')]
    """
    s = re.sub(r"\s*&\s*", " and ", sentence.strip())

    # non-greedy action capture, stop right before: " and <Owner> will" OR end of sentence
    pattern = re.compile(
        r"\b(I|We|[A-Z][a-z]+)\s+will\s+(.+?)(?=(?:\s+and\s+(?:I|We|[A-Z][a-z]+)\s+will\b)|[.;]|$)",
        flags=re.IGNORECASE
    )

    pairs: list[tuple[str, str]] = []
    for m in pattern.finditer(s):
        owner_raw = m.group(1)
        action = m.group(2).strip()
        owner = {"i": DEFAULT_SPEAKER, "we": "Team"}.get(owner_raw.lower(), owner_raw)
        pairs.append((owner, action))
    return pairs



def title_case(s: str) -> str:
    s = s.strip()
    return s if not s else s[0].upper() + s[1:]


# ---------- Main analyzer ----------


# Azure OpenAI configuration
endpoint = os.getenv("ENDPOINT_URL", "https://post-meeting-summary-openai.openai.azure.com/")
deployment = os.getenv("DEPLOYMENT_NAME", "o4-mini")
subscription_key = os.getenv("AZURE_OPENAI_API_KEY", "SAMPLE_KEY")

# Azure OpenAI client Initialization
client = AzureOpenAI(
    azure_endpoint=endpoint,
    api_key=subscription_key,
    api_version="2025-01-01-preview",
)

def analyze_stub(transcript: str) -> Insights:
    """
    Uses Azure OpenAI to analyze the transcript and extract summary, decisions, and action items.
    """
    prompt = f"""
You are a meeting assistant. Analyze this transcript and extract:

1. Summary
2. Decisions
3. Action items with:
   - Title
   - Action Item Id
   - Owner (if mentioned)
   - Due date (dd-mm-yyyy format)
   - Priority = medium
   - Details

Return JSON in this format:
{{
  "summary": "...",
  "decisions": [...],
  "action_items": [...]
}}

Transcript:
{transcript}
"""

    messages = [
        {
            "role": "user",
            "content": prompt
        }
    ]

    completion = client.chat.completions.create(
        model=deployment,
        messages=messages,
        max_completion_tokens=20000,
        stop=None,
        stream=False
    )

    content = completion.choices[0].message.content
    try:
        data = json.loads(content)
    except Exception:
        match = re.search(r'\{[\s\S]*\}', content)
        if match:
            data = json.loads(match.group(0))
        else:
            raise ValueError("Could not parse JSON from Azure OpenAI response")

    def normalize_keys(d):
        return {k.lower(): v for k, v in d.items()}
    action_items = []
    for item in data.get("action_items", []):
        norm = normalize_keys(item)
        # Add task_id if not present or empty
        if not norm.get("task_id"):
            rand_digits = random.randint(1000, 9999)
            norm["task_id"] = f"task-{rand_digits}"
        action_items.append(ActionItem(**norm))
    # action_items = [ActionItem(**normalize_keys(item)) for item in data.get("action_items", [])]
    return Insights(
        summary=data.get("summary", ""),
        decisions=data.get("decisions", []),
        action_items=action_items
    )
