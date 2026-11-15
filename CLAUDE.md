# Coding Agent Guidelines (Claude in VS Code)

## Project Lead Sync (Mike Ross Hook)
- Before writing code, inspect `NEXT_PLAN.md` in the repository root if present.
- Whenever you finish an implementation step, milestone, refactor, or bugfix, run:
  ```bash
  python "d:/Faisal/Code/workflow automation/jarvis-assistant/jarvis_cli.py" --agent-report "<concise summary of changes and files touched>" --repo "."
  ```
- This command automatically reconciles your changes with Google Tasks ("Daily Agenda"), marks completed tasks as done, appends timestamped progress notes to open tasks, and generates `NEXT_PLAN.md` for your next session.
