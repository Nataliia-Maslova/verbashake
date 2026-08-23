"""
Google Sheets connection helper.

Historically this module also wrote per-step interaction logs and a lesson
"progress" pointer to Sheets — both retired in Phase C in favour of
engine.recommender (mastery/SRS in Postgres) and engine.recommender's
lesson_pointer table. What's left is just the shared gspread auth/connection
helper, still used by engine/custom_store.py to mirror user-authored phrases.
"""
import streamlit as st

SHEET_NAME = "IMLLS_Logs"

_spreadsheet = None   # gspread Spreadsheet object


def _get_spreadsheet():
    global _spreadsheet
    if _spreadsheet is not None:
        return _spreadsheet
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds_dict = dict(st.secrets["gcp_service_account"])
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds  = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        _spreadsheet = client.open(SHEET_NAME)
        return _spreadsheet
    except Exception as e:
        print(f"[Logger] Google Sheets unavailable: {e}")
        return None
