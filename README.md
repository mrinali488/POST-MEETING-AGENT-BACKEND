# Post-Meeting Agent

This milestone adds an **agentic orchestration** layer using **LangGraph**.  
When you **upload an audio file** to `/ingest_audio`, a **Master Agent** runs this flow:

```
MasterAgent
  ├─ TranscriberAgent  (Whisper -> transcript)
  ├─ AnalyzerAgent     (Azure Open AI -> insights) 
  └─ TaskCalendarAgent (github issue + .ics event)
```

> Works : the analyzer is a stub Azure OpenAI. You will need Azure Open ai keys for this

---

## Quickstart

```bash
#create virutal environmnt
python -m venv .venv
#Activate vrtual environment
#for Windows: .venv\Scripts\activate
#for mac: source .venv/bin/activate
#Install requirments
pip install -r requirements.txt
#create .env file with the azure open ai ,github task keys and values
#start the app
uvicorn app.main:app --reload
```

**ffmpeg** is recommended for audio handling; install via your package manager if you don't have it.

### Health check
```bash
curl -s http://127.0.0.1:8000/health
```

### Upload audio (WAV/MP3/MP4/…)
```bash
curl -s -X POST "http://127.0.0.1:8000/ingest_audio"   -F "file=@/path/to/your/meeting.wav" | jq
```

### Fallback: Text-only endpoints
```bash
curl -s -X POST http://127.0.0.1:8000/analyze_text   -H "Content-Type: application/json" -d @synthetic_transcript.json | jq

curl -s -X POST http://127.0.0.1:8000/act_on_text   -H "Content-Type: application/json" -d @synthetic_transcript.json | jq
```

### What you’ll see
- `transcript` from Whisper
- `insights` with `summary`, `decisions[]`, `action_items[]`
- `actions[]` where each item has a create Option. Once Created`issue_url` will be displayed and an `ics_path` saved under `app/tmp/`

---

## Next milestones
- Add persistence (SQLite + Chroma) for memory.
