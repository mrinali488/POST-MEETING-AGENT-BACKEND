from langgraph.graph import StateGraph, END
from app.services.transcription import transcribe
from app.services.analysis import analyze_stub
from app.agents.tools import act_on_action_item

def master_agent(state: dict):
    file_path = state.get("file_path") or state.get("input", {}).get("file_path")
    if not file_path:
        raise ValueError("file_path missing in initial state")
    out = dict(state)
    out["file_path"] = file_path
    return out  

def transcriber_agent(state: dict):
    file_path = state.get("file_path") or state.get("input", {}).get("file_path")
    if not file_path:
        raise ValueError("No file_path in state")
    raw = transcribe(file_path)
    text = raw
    return {**state, "transcript": text}

def analyzer_agent(state: dict):
    transcript = state.get("transcript", "")
    insights = analyze_stub(transcript).dict()
    # MERGE with previous state
    return {**state, "insights": insights}

def task_calendar_agent(state: dict):
    insights = state.get("insights") or {}
    items = insights.get("action_items") or []
    actions = [act_on_action_item(item) for item in items]
    # MERGE with previous state
    return {**state, "actions": actions}

def build_workflow():
    graph = StateGraph(dict)
    graph.add_node("MasterAgent", master_agent)
    graph.add_node("TranscriberAgent", transcriber_agent)
    graph.add_node("AnalyzerAgent", analyzer_agent)
    graph.add_node("TaskCalendarAgent", task_calendar_agent)

    graph.add_edge("MasterAgent", "TranscriberAgent")
    graph.add_edge("TranscriberAgent", "AnalyzerAgent")
    graph.add_edge("AnalyzerAgent", "TaskCalendarAgent")
    graph.add_edge("TaskCalendarAgent", END)

    graph.set_entry_point("MasterAgent")
    return graph.compile()
