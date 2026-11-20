from tools.apps import open_app, open_folder, search_files
from tools.dev_sync import sync_coding_progress
from tools.dispatch import dispatch_coding_agent
from tools.media import change_volume, get_volume, open_browser, play_music, play_spotify, play_youtube, search_google, set_volume
from tools.planner import write_agent_plan
from tools.tasks import add_task, complete_task, create_task_list, list_agenda, list_task_lists, update_task_progress

TOOL_FUNCTIONS = [
    sync_coding_progress,
    list_agenda,
    add_task,
    update_task_progress,
    complete_task,
    create_task_list,
    list_task_lists,
    write_agent_plan,
    dispatch_coding_agent,
    open_app,
    open_folder,
    search_files,
    open_browser,
    search_google,
    play_music,
    play_youtube,
    play_spotify,
    get_volume,
    set_volume,
    change_volume,
]
TOOL_MAP = {fn.__name__: fn for fn in TOOL_FUNCTIONS}
