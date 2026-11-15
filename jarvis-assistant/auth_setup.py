import os
import sys
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/tasks"]
creds_file = os.path.join(os.path.dirname(__file__), "credentials.json")
token_file = os.path.join(os.path.dirname(__file__), "token.json")

print("Initializing OAuth flow...", flush=True)
flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
creds = flow.run_local_server(port=0, open_browser=True)

with open(token_file, "w", encoding="utf-8") as f:
    f.write(creds.to_json())

print("SUCCESS: token.json created!", flush=True)
