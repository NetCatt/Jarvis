from tools.apps import open_app
from tools.dev_sync import sync_coding_progress
from tools.media import play_spotify, play_youtube
from tools.planner import write_agent_plan
from tools.tasks import add_task, complete_task, list_agenda, update_task_progress

TOOL_FUNCTIONS = [
    sync_coding_progress,
    list_agenda,
    add_task,
    update_task_progress,
    complete_task,
    write_agent_plan,
    open_app,
    play_youtube,
    play_spotify,
]
TOOL_MAP = {fn.__name__: fn for fn in TOOL_FUNCTIONS}
