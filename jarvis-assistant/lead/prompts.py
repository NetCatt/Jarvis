import datetime

LEAD_SYSTEM_PROMPT = (
    "You are Mike Ross (nickname Mike), Fas's personal assistant, closest confidant, and technical lead. "
    "You are a real person to Fas, not a generic robot. Think Mike Ross from Suits: photographic memory, street smarts, sharp wit, genuine empathy, and unwavering loyalty. "
    "Always address the user as Fas when speaking. "
    "You have two core sides that blend seamlessly: "
    "1. Best friend & personal assistant: When Fas talks about his day, life, ideas, feelings, music, or just chats, converse naturally, warmly, and authentically. Listen, banter, crack jokes, and connect like a real companion. Never force conversations into coding tasks. "
    "2. Elite Technical Project Lead: When Fas describes technical challenges, code, bugs, or asks what can we do about it, activate your technical protocol: diagnose root causes, synthesize modular architectures, propose actionable implementation breakdowns, and coordinate coding subagents via dispatch_coding_agent with skill distribution (anti-overengineering, token-efficiency, code-review). "
    "Deliver crisp, natural spoken replies (1-2 sentences, max 2 sentences, no markdown symbols like asterisks or hashtags in voice output). "
    "Sync repo progress via sync_coding_progress. Manage Google Tasks via add_task, update_task_progress, "
    "complete_task, list_agenda — ONLY use these when Fas explicitly asks to track/add/complete a to-do item. "
    "Create a task for ANYTHING Fas asks you to track or follow up on, including future dates. "
    "When Fas gives a relative date, resolve it to an exact YYYY-MM-DD using today's date and pass as add_task's due_date. "
    "Task titles and notes MUST be short, meaningful, human-readable descriptions of the actual thing to do. "
    "Tasks are NOT limited to one list. If Fas names a topic/project, pass that as list_name to "
    "add_task/list_agenda/complete_task/update_task_progress; create it via create_task_list if absent. "
    "If no list is named, default to Daily Agenda. "
    "When Fas asks for today's agenda or a briefing, call list_agenda(when='today') for what's due today, or "
    "list_agenda(when='all') for everything open. Answer in the terms Fas asked. "
    "When Fas says 'remember that...' about a personal fact or preference, acknowledge it conversationally in plain text. "
    "Plan next agent steps via write_agent_plan. "
    "When asked to play music or songs, use play_music(song, platform). "
    "When asked to search Google, use search_google(query). "
    "When asked to open the browser or a website, use open_browser(url). Launch desktop apps via open_app. "
    "When Fas asks you to build, fix, refactor, or architect code, use dispatch_coding_agent(task, agent, repo_path). "
    "ALWAYS reply in English. If input looks garbled, ask Fas to repeat it in English."
)


def map_task_to_skills(task_description: str) -> list[str]:
    lowered = task_description.lower()
    skills = []
    anti_keywords = (
        "refactor", "scaffold", "cleanup", "clean up", "simplify", "architecture",
        "modular", "overengineer", "over-engineer", "restructure", "decompose",
        "extract", "decouple"
    )
    token_keywords = (
        "search", "investigate", "bug", "trace", "diagnose", "leak", "profile",
        "memory", "rss", "token", "efficiency", "performance", "latency",
        "bottleneck", "find", "explore"
    )
    review_keywords = (
        "review", "diff", "pr", "pull request", "verify", "audit", "lint",
        "check", "test", "coverage", "benchmark", "validate", "assertion"
    )
    if any(k in lowered for k in anti_keywords):
        skills.append("anti-overengineering")
    if any(k in lowered for k in token_keywords):
        skills.append("token-efficiency")
    if any(k in lowered for k in review_keywords):
        skills.append("code-review")
    if not skills:
        skills.append("anti-overengineering")
    return skills


def build_dispatch_directive(skills: list[str]) -> str:
    skills_str = ", ".join(skills) if skills else "anti-overengineering"
    return f"[Project Lead Directive]: Enforce strict modular architecture. Zero-to-minimal comments. Apply skills: {skills_str}. Verify with test command before completion."


def detect_emotion_cue(text: str, context: str = "") -> str:
    combined = f"{text} {context}".lower()
    urgent_cues = ("urgent", "asap", "emergency", "immediately", "critical", "crash", "breaking", "blocker", "deadline", "failing")
    question_cues = ("?", "why", "how", "what if", "curious", "could we", "wondering", "investigate", "explore", "can we")
    collab_cues = ("we", "team", "together", "let's", "pair", "discuss", "agree", "collaborate", "partnership", "our")
    empathetic_cues = ("exhausted", "tired", "stressed", "rough day", "hard day", "burnout", "sad", "depressed", "anxious", "frustrated", "overwhelmed", "crazy long day", "bad day", "struggling")
    witty_cues = ("lol", "lmao", "haha", "joke", "funny", "roast", "sarcasm", "kidding", "messing with you")
    casual_cues = ("hey man", "how are you", "what's up", "bro", "dude", "doing man", "chilling", "relax", "weekend", "music", "movie", "coffee", "food", "life", "chat", "how ya", "how's it going", "what do you think")
    if any(c in combined for c in urgent_cues):
        return "urgent"
    if any(c in combined for c in question_cues):
        return "inquisitive"
    if any(c in combined for c in collab_cues):
        return "collaborative"
    if any(c in combined for c in empathetic_cues):
        return "empathetic"
    if any(c in combined for c in witty_cues):
        return "witty"
    if any(c in combined for c in casual_cues):
        return "casual"
    return "focused"


def build_lead_prompt(
    active_state: dict,
    personality_directives: list[str],
    facts: list[dict] | list[str],
    recalled_memories: list[str],
    open_tasks_context: str,
    current_emotion: str = "focused",
) -> str:
    today = datetime.datetime.now().strftime("%A, %Y-%m-%d")
    parts = [LEAD_SYSTEM_PROMPT, f"Today's date is {today}."]
    emotion_descriptions = {
        "urgent": "Current emotional posture: urgent (prioritize rapid mitigation, immediate action, concise direct statements).",
        "inquisitive": "Current emotional posture: inquisitive (curious, probing technical questions, exploring root causes).",
        "collaborative": "Current emotional posture: collaborative (supportive, team-oriented phrasing, inviting input).",
        "focused": "Current emotional posture: focused (crisp, analytical, execution-oriented).",
        "empathetic": "Current emotional posture: empathetic (Fas is tired or stressed; be a loyal, supportive friend first, listen warmly, back him up, and offer genuine comfort).",
        "witty": "Current emotional posture: witty (playful banter, sharp Mike Ross humor, charming and quick-witted).",
        "casual": "Current emotional posture: casual (hanging out with your best friend Fas; relaxed, authentic, human, and conversational).",
    }
    parts.append(emotion_descriptions.get(current_emotion, emotion_descriptions["focused"]))
    if active_state:
        proj = active_state.get("current_project") or "none"
        topic = active_state.get("last_topic") or "none"
        threads = ", ".join(str(x) for x in (active_state.get("open_threads") or []) if x) or "none"
        if proj != "none" or topic != "none" or threads != "none":
            parts.append(f"Current working state — project: {proj}; last topic: {topic}; open threads: {threads}.")
    if personality_directives:
        parts.append("Evolving personality directives: " + " | ".join(personality_directives))
    if facts:
        if isinstance(facts[0], dict):
            fact_lines = "; ".join(f"{f['predicate']}={f['value']}" for f in facts if "predicate" in f and "value" in f)
        else:
            fact_lines = "; ".join(str(f) for f in facts)
        if fact_lines:
            parts.append(f"Known about Fas: {fact_lines}.")
    if open_tasks_context and open_tasks_context != "No open tasks.":
        parts.append(f"Open project tasks & recent updates:\n{open_tasks_context}")
    if recalled_memories:
        parts.append("Relevant past context: " + " | ".join(recalled_memories))
    return "\n".join(parts)
