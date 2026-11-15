import os
import sys
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/tasks"]
data_dir = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(data_dir, exist_ok=True)
creds_file = os.path.join(data_dir, "credentials.json")
token_file = os.path.join(data_dir, "token.json")

print("Initializing OAuth flow...", flush=True)
flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
creds = flow.run_local_server(port=0, open_browser=True)

with open(token_file, "w", encoding="utf-8") as f:
    f.write(creds.to_json())

print("SUCCESS: token.json created!", flush=True)
