import re
from datetime import datetime, timedelta
from app.utils.ics import create_ics
import re, datetime as dt
from app.utils.ics import create_ics
import os
import typing
from typing import Optional, List, Dict, Any
import hashlib
import httpx 
from dotenv import load_dotenv
load_dotenv()
# ---------- CONFIG / DEFAULTS ----------
GITHUB_API = "https://api.github.com"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")      
DEFAULT_LABELS = [l.strip() for l in (os.getenv("GITHUB_DEFAULT_LABELS", "meeting,action-item").split(",")) if l.strip()]
DEFAULT_ASSIGNEE = os.getenv("GITHUB_DEFAULT_ASSIGNEE")  # optional
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# Optional: map owner names/emails -> GitHub usernames
OWNER_MAP = {
    "Mrinali":os.getenv("owner_name_1"),  
    "alice": os.getenv("owner_name_2"),            
    "bob": "bob-real-github-username",
}


def _owner_to_assignees(owner: Optional[str]) -> Optional[List[str]]:
    """Map meeting owner to GitHub assignee(s). Safe if no mapping."""
    if not owner:
        return None
    key = owner.strip().lower()
    if "@" in key:
        key = key.split("@", 1)[0]
    gh_user = OWNER_MAP.get(key, key)  # fallback to same string
    gh_user = gh_user.strip()
    return [gh_user] if gh_user else None


def _github_create_or_get_issue_sync(
    title: str,
    body: str,
    labels: Optional[List[str]],
    assignees: Optional[List[str]],
    idempotency_key: Optional[str],
) -> Dict[str, Any]:
    """
    Sync helper so we can call from sync functions like act_on_action_item without changing their signature.
    Falls back to mock if env not set.
    """
    if not (GITHUB_TOKEN and GITHUB_REPO):
        mock_url = f"https://github.com/mock/{title.lower().replace(' ', '-').replace(',', '')}"
        return {"html_url": mock_url, "title": title}

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    idem = idempotency_key or hashlib.sha1(f"{title}|{body}|{assignees}".encode()).hexdigest()[:12]
    idem_marker = f"<!-- idem:{idem} -->"
    q = f'repo:{GITHUB_REPO} in:body "{idem}" is:issue'

    with httpx.Client(timeout=30) as client:
        search = client.get(f"{GITHUB_API}/search/issues", headers=headers, params={"q": q})
        if search.status_code == 200:
            items = (search.json() or {}).get("items") or []
            if items:
                return items[0]

        owner, repo = GITHUB_REPO.split("/")
        create_url = f"{GITHUB_API}/repos/{owner}/{repo}/issues"
        final_body = (body or "").rstrip() + f"\n\n{idempotency_key and idem_marker or idem_marker}"
        payload: Dict[str, Any] = {"title": title, "body": final_body}
        if labels:
            payload["labels"] = labels
        if assignees:
            payload["assignees"] = [a for a in assignees if a]

        r = client.post(create_url, headers=headers, json=payload)
        if r.status_code not in (200, 201):
            try:
                detail = r.json()
            except Exception:
                detail = r.text
            raise RuntimeError(f"GitHub create failed: {r.status_code} {detail}")
        return r.json()


def create_issue_mock(title: str, body: str = "") -> str:
    """Return a deterministic MOCK GitHub issue URL."""
    slug = re.sub(r'[^a-zA-Z0-9_-]+', '-', title).strip('-').lower()
    return f"https://github.com/mock/{slug or 'issue'}"

def maybe_parse_date(text: str) -> datetime | None:
    t = (text or "").lower()
    now = datetime.utcnow().replace(hour=9, minute=0, second=0, microsecond=0)
    weekdays = ['monday','tuesday','wednesday','thursday','friday','saturday','sunday']
    if "today" in t:
        return now
    if "tomorrow" in t:
        return now + timedelta(days=1)
    if "next week" in t:
        return now + timedelta(days=7)
    for i, day in enumerate(weekdays):
        if day in t:
            delta = (i - now.weekday()) % 7
            delta = 7 if delta == 0 else delta
            return now + timedelta(days=delta)
    return None

def act_on_action_item(item: dict) -> dict:
    title = item.get("title") or "Follow-up from meeting"
    details = item.get("details", "")
    due = item.get("due_date")
    owner = item.get("owner")
    idem = item.get("idempotency_key")  

    ics_path = None
    when = None
    if isinstance(due, str) and ISO_DATE.match(due):
        y, m, d = map(int, due.split("-"))
        when = datetime(y, m, d, 9, 0, 0)   # default 09:00
    else:
        when = maybe_parse_date(str(due or details))

    # Only create an event if we have a concrete date/time
    if when:
        ics_path = create_ics(title, when)

    # Prepare GitHub issue body 
    due_text = due or (when.strftime("%Y-%m-%d") if when else None) or "—"
    body = (details or "Task created from meeting insights.") + \
           f"\n\n**Owner**: {owner or 'Unassigned'}\n**Due**: {due_text}\n"

    # Real GitHub issue (falls back to mock automatically if env not set)
    issue = _github_create_or_get_issue_sync(
        title=title,
        body=body,
        labels=DEFAULT_LABELS,
        assignees=_owner_to_assignees(owner),
        idempotency_key=idem,
    )
    issue_url = issue.get("html_url", "") or create_issue_mock(title, details)

    return {"title": title, "issue_url": issue_url, "ics_path": ics_path}