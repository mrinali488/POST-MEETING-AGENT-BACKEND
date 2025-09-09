from fastapi import FastAPI, UploadFile, File,HTTPException,Response
from fastapi.responses import JSONResponse,FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from pathlib import Path
import shutil, subprocess, json
from fastapi.middleware.cors import CORSMiddleware
from app.services.analysis import analyze_stub, Insights
from app.agents.tools import act_on_action_item
from app.agents.graph import build_workflow
from app.services.transcription import transcribe
from app.utils.ics import create_ics

from typing import Optional, List, Dict, Any

app = FastAPI(title="Post-Meeting Agent (Milestone 2: Master Agent)")
workflow = build_workflow()
# Allow CORS for local frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
class TranscriptIn(BaseModel):
    transcript: str = Field(..., description="Raw meeting transcript text")

# ---------- Optional models for UI action buttons ----------
class TaskIn(BaseModel):
    title: str
    due: str | None = None          
    owner: str | None = None        
    idempotency_key: str | None = None

class EventIn(BaseModel):
    subject: str
    start: str                      
    end: str | None = None
    attendees: list[str] = []
    idempotency_key: str | None = None

@app.get("/health")
def health():
    return {"ok": True, "version": "m2-hotfix2"}  

@app.post("/analyze_text", response_model=Insights)
def analyze_text(inp: TranscriptIn):
    return analyze_stub(inp.transcript)

@app.post("/act_on_text")
def act_on_text(inp: TranscriptIn):
    """
    Returns analysis + a PREVIEW of actions (no GitHub/event creation).
    Use /actions/task and /actions/event to actually create.
    """
    insights = analyze_stub(inp.transcript)

    
    preview_actions: List[Dict[str, Any]] = []
    for ai in insights.action_items:
        preview_actions.append({
            "title": ai.title,
            "issue_url": None,  
            "ics_path": None,   
        })

    return {"insights": insights.dict(), "actions": preview_actions}

@app.post("/debug_transcribe")
async def debug_transcribe(file: UploadFile = File(...)):
    try:
        path = Path("data/meetings"); path.mkdir(parents=True, exist_ok=True)
        fpath = path / file.filename
        with open(fpath, "wb") as f: shutil.copyfileobj(file.file, f)

        # quick ffprobe for visibility
        def ffprobe_json(p):
            try:
                out = subprocess.check_output([
                    "ffprobe","-hide_banner","-loglevel","error",
                    "-show_streams","-select_streams","a","-of","json", str(p)
                ], text=True)
                return json.loads(out)
            except Exception as e:
                return {"probe_error": str(e)}

        transcript = transcribe(str(fpath))
        return {"file_path": str(fpath), "probe": ffprobe_json(str(fpath)), "transcript": transcript}
    except Exception as e:
        import traceback
        return JSONResponse(status_code=500, content={"error": str(e), "traceback": traceback.format_exc()})

# ---------- Ingest audio (Transcribe + Analyze ONLY) ----------
@app.post("/ingest_audio")
async def ingest_audio(file: UploadFile = File(...)):
    """
    Decoupled pipeline:
      1) Save file
      2) Transcribe
      3) Analyze
      4) Return insights + PREVIEW actions (no creation here)
    """
    try:
        path = Path("data/meetings"); path.mkdir(parents=True, exist_ok=True)
        fpath = path / file.filename
        with open(fpath, "wb") as f: shutil.copyfileobj(file.file, f)
        transcript = transcribe(str(fpath))
        print(f"Transcript:\n{transcript}")
        insights = analyze_stub(transcript)

        preview_actions: List[Dict[str, Any]] = []
        for ai in insights.action_items:
            preview_actions.append({
                "title": ai.title,
                "issue_url": None,
                "ics_path": None,
            })

        return {
            "file_path": str(fpath),
            "transcript": transcript,
            "insights": insights.dict(),
            "actions": preview_actions,    
            "summary": insights.summary,
            "decisions": insights.decisions,
            "action_items": [ai.dict() for ai in insights.action_items],
            "task_owners": (
                [
                    {"owner": ai.owner, "github_username": getattr(ai, "github_username", None)}
                    for ai in insights.action_items if ai.owner
                ] + [{"owner": "Mrinali", "github_username": "mrinali488"}]
            )
        }
    except Exception as e:
        import traceback
        return JSONResponse(status_code=500, content={"error": str(e), "traceback": traceback.format_exc()})

def _normalize_task_result(item: TaskIn, action: Dict[str, Any]) -> Dict[str, Any]:
    
    return {
        "id": item.idempotency_key or item.title,
        "url": action.get("issue_url") or "",
        "raw": {
            "title": action.get("title", item.title),
            "issue_url": action.get("issue_url"),
            "ics_path": action.get("ics_path"),
        }
    }

@app.post("/actions/task")
def actions_task(body: TaskIn):
    """
    CREATES a GitHub Issue (via act_on_action_item) and (optionally) ICS if due is concrete.
    """
    try:
        action_dict = {
            "title": body.title,
            "details": getattr(body, "details", None), 
            "due_date": body.due,              
            "owner": body.owner,
            "idempotency_key": body.idempotency_key,
        }
        res = act_on_action_item(action_dict)      
        return _normalize_task_result(body, res)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# @app.post("/actions/tasks/bulk")
# def actions_tasks_bulk(bodies: List[TaskIn]):
#     """
#     Bulk create: calls act_on_action_item for each.
#     """
#     out = []
#     for body in bodies:
#         action_dict = {
#             "title": body.title,
#             "details": getattr(body, "details", None), 
#             "due_date": body.due,
#             "owner": body.owner,
#             "idempotency_key": body.idempotency_key,
#         }
#         res = act_on_action_item(action_dict)
#         out.append(_normalize_task_result(body, res))
#     return out


@app.post("/actions/event")
def actions_event(body: EventIn):
    """
    Creates an ICS file only (no GitHub). Keeps your existing ICS flow.
    """
    try:
        # Minimal: only start is required to make an ICS
        from datetime import datetime
        try:   
            start_dt = datetime.fromisoformat(body.start.replace("Z", "+00:00"))
        except Exception:
            start_dt = datetime.fromisoformat(body.start[:19])
        ics_path = create_ics(body.subject, start_dt)
        return {
            "id": body.idempotency_key or body.subject,
            "url": "",
            "raw": {
                "title": body.subject,
                "issue_url": None,
                "ics_path": ics_path
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
