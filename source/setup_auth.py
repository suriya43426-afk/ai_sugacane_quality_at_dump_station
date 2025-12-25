# -*- coding: utf-8 -*-
"""
setup_auth.py
- Run this ONCE on your main PC to generate 'token.json'.
- Then copy 'token.json' to all factory machines.
"""
import os
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# Scopes: Read/Write Drive
SCOPES = ['https://www.googleapis.com/auth/drive']

def main():
    # Look for files relative to this script, or in CWD
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Try finding credentials in source/ or root
    creds_path = os.path.join(script_dir, "credentials.json")
    if not os.path.exists(creds_path):
        creds_path = "credentials.json" # Fallback to CWD

    token_path = os.path.join(script_dir, "token.json")
    
    if not os.path.exists(creds_path):
        print(f"[ERROR] '{creds_path}' not found!")
        print("1. Go to Google Cloud Console (APIs & Services -> Credentials)")
        print("2. Create OAuth Client ID (Desktop App)")
        print("3. Download JSON and rename to 'credentials.json'")
        input("Press Enter to exit...")
        return

    creds = None
    # Load existing
    if os.path.exists(token_path):
        print(f"[INFO] '{token_path}' already exists.")
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        except Exception:
            print("[WARN] Invalid token, re-authenticating...")

    # Refresh or Login
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("[INFO] Refreshing expired token...")
            try:
                creds.refresh(Request())
            except Exception:
                 print("[WARN] Refresh failed, need full login.")
                 flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
                 creds = flow.run_local_server(port=0)
        else:
            print("[INFO] Starting Browser Login...")
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
            
        # Save
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
        print(f"\n[SUCCESS] Generated '{token_path}'!")
        print(">> Copy this file to your factory machines alongside 'run_data_sync.py'.")

if __name__ == "__main__":
    main()
