import argparse
import os
from dotenv import load_dotenv


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Jarvis Project Lead CLI")
    parser.add_argument("--sync-git", action="store_true", help="Sync latest Git status/diff")
    parser.add_argument("--agent-report", type=str, default="", help="Summary from Claude/Gemini agent")
    parser.add_argument("--repo", type=str, default="", help="Target repo path")
    parser.add_argument("--ask", type=str, default="", help="Natural language query")
    parser.add_argument("--silent", action="store_true", help="Mute spoken TTS")
    return parser.parse_args()


def main() -> None:
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    load_dotenv(env_path)
    load_dotenv()
    from brain import route_command
    from main import speak
    from tools.dev_sync import sync_coding_progress

    args = _parse_args()
    if args.sync_git or args.agent_report:
        reply = sync_coding_progress(agent_note=args.agent_report, repo_path=args.repo)
    elif args.ask:
        reply = route_command(args.ask)
    else:
        reply = sync_coding_progress(repo_path=args.repo)
    print(f"[Mike]: {reply}")
    if not args.silent:
        speak(reply)


if __name__ == "__main__":
    main()
