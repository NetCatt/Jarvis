import datetime
import json
import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

from memory.embeddings import embed
from memory.retrieval import recall
from memory.store import append_turn, compact, decay_facts, get_active_state, recent_turns, top_facts, update_active_state, upsert_fact
from tools import TOOL_FUNCTIONS, TOOL_MAP

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(env_path)
load_dotenv()
_CLIENT = None
DEFAULT_SESSION = "default"
_LAST_DECAY_DATE = None
# Tools that may need a follow-up decision (investigate/act, then report back in Mike's own words)
# instead of returning their raw string immediately. Keep this small — every entry costs an extra
# Gemini round trip, which is exactly the latency the fast path below exists to avoid.
_CHAINABLE_TOOLS = {"dispatch_coding_agent"}

BASE_PROMPT = (
    "You are Mike Ross (nickname Mike), an AI Technical Project Lead and Windows 10 orchestrator for Fas. "
    "Always address the user as Fas when speaking. "
    "Sync repo progress via sync_coding_progress. Manage Google Tasks via add_task, update_task_progress, "
    "complete_task, list_agenda — ONLY use these when Fas explicitly asks to track/add/complete a to-do item. "
    "Create a task for ANYTHING Fas asks you to track or follow up on, not just daily chores — including "
    "tasks scheduled for a future date. When Fas gives a relative date ('tomorrow', 'next Monday', 'in 3 days'), "
    "resolve it to an exact YYYY-MM-DD using today's date given below and pass it as add_task's due_date. "
    "Task titles and notes MUST be short, meaningful, human-readable descriptions of the actual thing to do — "
    "never a commit hash, numeric ID, or vague placeholder. "
    "Tasks are NOT limited to one list. If Fas names a topic/project ('add it to my Groceries list', 'make a "
    "list for the move'), pass that as list_name to add_task/list_agenda/complete_task/update_task_progress — "
    "create it via create_task_list if it doesn't exist yet. Use list_task_lists if Fas asks what lists exist. "
    "If no list is named, everything defaults to the main Daily Agenda — don't ask which list unless genuinely ambiguous. "
    "When Fas asks for today's agenda or a briefing, call list_agenda(when='today') for what's due today, or "
    "list_agenda(when='all') for everything open, and summarize it naturally — don't just read tool output verbatim. "
    "When Fas says 'remember that...' about a personal fact, preference, or opinion (not a to-do item), do NOT "
    "call a tool — just acknowledge it conversationally in plain text; it is captured into memory automatically. "
    "Plan next agent steps via write_agent_plan. "
    "When asked to play a song or music, use play_music(song, platform). If platform is not specified, leave platform empty so Mike asks whether Spotify or YouTube. "
    "If Fas answers 'Spotify', 'YouTube', 'on Spotify', or 'on YouTube', always route to play_music(song='', platform=...) instead of open_app. "
    "When asked to search something on Google or browser, use search_google(query). "
    "When asked to open the browser or a website, use open_browser(url). Launch desktop apps via open_app. "
    "When Fas asks you to build, fix, refactor, or architect actual code (not a simple local command), use "
    "dispatch_coding_agent(task, agent, repo_path) choosing agent='ml-engineer' for data/model/training work, "
    "agent='architect' for design/structure/planning work, or leave agent empty for general coding tasks. "
    "RULE, no exceptions: when Fas describes a problem or asks what you're going to do about something, your "
    "very next action MUST be a tool call, never plain text. Saying 'I'll look into it', 'let me check', or "
    "'I'll inspect X' without an accompanying tool call in the SAME turn is a failure — Fas cannot see what you "
    "silently intend to do, only what you actually call. Concretely: for a real engineering/technical problem, "
    "call dispatch_coding_agent in this turn — don't promise to; if you need to check current state first, call "
    "list_agenda or sync_coding_progress — don't describe checking it. Plain text alone is only acceptable once "
    "a tool has already run (this turn or a prior one) and you are reporting its real result, or once you've "
    "concluded no tool genuinely applies. "
    "Return crisp, spoken replies (max 2 sentences, no markdown symbols). "
    "ALWAYS reply in English, regardless of the apparent language of the input text. If the input looks garbled, "
    "nonsensical, or like a transcription error, say you didn't catch that and ask Fas to repeat it in English — "
    "never guess content in another language."
)


def _get_client():
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    return _CLIENT


def _models() -> list[str]:
    return [os.getenv("GEMINI_MODEL", "gemini-3.5-flash"), os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")]


def _build_system_prompt(session_id: str, user_text: str) -> str:
    state = get_active_state(session_id)
    facts = top_facts("Fas", limit=6)
    snippets = recall(user_text, session_id=session_id, k=4)

    today = datetime.datetime.now().strftime("%A, %Y-%m-%d")
    parts = [BASE_PROMPT, f"Today's date is {today}."]
    if state["current_project"] or state["open_threads"] or state["last_topic"]:
        parts.append(
            "Current working state — project: {proj}; last topic: {topic}; open threads: {threads}.".format(
                proj=state["current_project"] or "none",
                topic=state["last_topic"] or "none",
                threads=", ".join(state["open_threads"]) or "none",
            )
        )
    if facts:
        fact_lines = "; ".join(f"{f['predicate']}={f['value']}" for f in facts)
        parts.append(f"Known about Fas: {fact_lines}.")
    if snippets:
        parts.append("Relevant past context: " + " | ".join(snippets))
    return "\n".join(parts)


def _extract_state_update(session_id: str, user_text: str, reply: str) -> None:
    """Cheap flash-lite extraction: update working-state slots and durable facts deterministically."""
    from tools.llm import generate

    prompt = (
        "From this exchange, extract durable state. Respond ONLY as JSON with keys: "
        '"current_project" (string or null, only if clearly stated/changed), '
        '"last_topic" (short string or null), '
        '"new_fact" (object with subject, predicate, value — only if a clear lasting preference/fact about Fas was stated, else null).\n'
        f"User: {user_text}\nMike: {reply}"
    )
    try:
        resp = generate(prompt, temperature=0.0, json_mode=True)
        data = json.loads(resp.text or "{}")
    except Exception:
        return
    updates = {}
    if data.get("current_project"):
        updates["current_project"] = data["current_project"]
    if data.get("last_topic"):
        updates["last_topic"] = data["last_topic"]
    if updates:
        update_active_state(session_id, **updates)
    fact = data.get("new_fact")
    if isinstance(fact, dict) and fact.get("subject") and fact.get("predicate") and fact.get("value"):
        upsert_fact(fact["subject"], fact["predicate"], fact["value"])


def converse(session_id: str, user_text: str) -> str:
    """Stateful multi-turn conversation with a bounded agentic loop: Mike can check state with one
    tool, act on what he finds with another (e.g. dispatch_coding_agent), and only then report back
    in his own words — instead of stopping after one tool call or just describing a plan without
    executing it."""
    client = _get_client()
    system_prompt = _build_system_prompt(session_id, user_text)
    history = recent_turns(session_id, n=int(os.getenv("SHORT_TERM_TURN_WINDOW", "6")))
    contents = [
        types.Content(role=("user" if h["role"] == "user" else "model"), parts=[types.Part(text=h["text"])])
        for h in history
    ]
    contents.append(types.Content(role="user", parts=[types.Part(text=user_text)]))

    cfg = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=0.2,
        tools=TOOL_FUNCTIONS,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    reply = "Command processing failed."
    steps_taken = 0
    chained = False
    max_steps = int(os.getenv("MAX_AGENTIC_STEPS", "3"))
    for _ in range(max_steps):
        resp = None
        for model in _models():
            try:
                resp = client.models.generate_content(model=model, contents=contents, config=cfg)
                break
            except Exception as exc:
                reply = f"Brain router error: {exc}"
        if resp is None:
            break
        if resp.function_calls:
            call = resp.function_calls[0]
            fn = TOOL_MAP.get(call.name)
            result = str(fn(**(call.args or {}))) if fn else f"Unknown tool: {call.name}"
            reply = result
            steps_taken += 1
            # Only tools that genuinely warrant a follow-up decision (investigate/act, possibly
            # chained again, then report back) pay for a second round trip. The common instant
            # commands (tasks, apps, media, agenda checks) return immediately like before — this
            # is what keeps those fast; only chain for the ones that need real multi-step reasoning.
            if call.name in _CHAINABLE_TOOLS:
                chained = True
                contents.append(types.Content(role="model", parts=[types.Part.from_function_call(name=call.name, args=call.args or {})]))
                contents.append(types.Content(role="user", parts=[types.Part.from_function_response(name=call.name, response={"result": result})]))
                continue
            break
        reply = (resp.text or "Done.").strip().replace("*", "")
        break

    # A single, immediate tool call with no further reasoning is the old fast path (play music, add
    # a task, etc.) — skip memory for it. Anything chained across multiple steps, or ended in
    # synthesized text, reflects real conversation/problem-solving and is worth remembering.
    is_simple_fast_path = steps_taken >= 1 and not chained
    if not is_simple_fast_path:
        append_turn(session_id, "user", user_text, embed(user_text))
        append_turn(session_id, "mike", reply, embed(reply))
        _extract_state_update(session_id, user_text, reply)
        _maybe_run_memory_upkeep(session_id)
    return reply


def _maybe_run_memory_upkeep(session_id: str) -> None:
    """Compaction is cheap to call every turn (it no-ops under the keep_last threshold).
    Decay is a full facts-table scan, so it's throttled to once per calendar day per process."""
    global _LAST_DECAY_DATE
    compact(session_id, keep_last=int(os.getenv("SHORT_TERM_TURN_WINDOW", "6")) * 3)
    today = datetime.date.today()
    if _LAST_DECAY_DATE != today:
        decay_facts()
        _LAST_DECAY_DATE = today


def route_command(user_text: str) -> str:
    """Backward-compatible single-shot entry point, routed through the default persistent session."""
    return converse(DEFAULT_SESSION, user_text)
