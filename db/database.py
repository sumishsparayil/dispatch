"""Database — JSON-based store for KLM Axiva Finvest MIS settings and run history.


SMTP password and all settings: db/panther_data.json
Branch emails (single authoritative store): db/address_book.json
"""

import json
import os
import sys
from datetime import datetime

# ── Path resolver ────────────────────────────────────────────────
def get_db_path() -> str:
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_dir = os.path.join(base, 'db')
    os.makedirs(db_dir, exist_ok=True)
    return os.path.join(db_dir, 'dispatch_data.json')

def _ensure_dir():
    os.makedirs(os.path.dirname(get_db_path()), exist_ok=True)

def _load() -> dict:
    path = get_db_path()
    if not os.path.exists(path):
        return {'settings': {}, 'runs': [], 'emails': []}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {'settings': {}, 'runs': [], 'emails': []}

def _save(data: dict):
    path = get_db_path()
    _ensure_dir()
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ── Keyring helpers ────────────────────────────────────────────────
_KEYRING_SERVICE = "Panther_KLM_Axiva"

def save_password(key: str, value: str):
    try:
        import keyring
        keyring.set_password(_KEYRING_SERVICE, key, value)
        return True
    except Exception:
        return False

def get_password(key: str) -> str:
    try:
        import keyring
        return keyring.get_password(_KEYRING_SERVICE, key) or ''
    except Exception:
        return ''

# ── Settings ───────────────────────────────────────────────────────

def get_settings() -> dict:
    """Returns all settings. smtp_pass is included.
    Note: address_book is the single authoritative store for branch emails.
    branch_mappings is NOT maintained here.
    """
    return _load().get('settings', {})

def save_settings(key: str, value):
    """Save a single setting to panther_data.json."""
    data = _load()
    data['settings'][key] = value
    _save(data)

from db.address_book import get_address_book

def save_settings_batch(raw: dict):
    """Batch save all settings to panther_data.json.
    branch_mappings is NOT saved here — address_book is the only store.
    smtp_pass is stored in plain text (internal tool behind VPN).
    """
    store = _load()
    for key, value in raw.items():
        if key != 'branch_mappings':
            store['settings'][key] = value
    _save(store)


def get_password_for_smtp() -> str:
    """Returns smtp_pass from panther_data.json."""
    return get_settings().get('smtp_pass', '')

# ── Run History ────────────────────────────────────────────────────

def log_run_start(run_id: str, filename: str, total_rows: int) -> str:
    store = _load()
    store['runs'].insert(0, {
        'run_id':           run_id,
        'started_at':       datetime.now().isoformat(),
        'completed_at':     None,
        'duration_seconds': None,
        'total_rows':       total_rows,
        'total_sent':       0,
        'total_failed':     0,
        'filename':         filename,
    })
    store['runs'] = store['runs'][:50]
    _save(store)
    return run_id

def log_run_complete(run_id: str, sent: int, failed: int):
    store = _load()
    for run in store['runs']:
        if run['run_id'] == run_id:
            run['completed_at'] = datetime.now().isoformat()
            if run.get('started_at'):
                start = datetime.fromisoformat(run['started_at'])
                duration = (datetime.now() - start).total_seconds()
                run['duration_seconds'] = round(duration, 1)
            run['total_sent']   = sent
            run['total_failed'] = failed
            break
    _save(store)

def log_email_result(
    run_id: str,
    recipient: str,
    cc: str,
    subject: str,
    branch: str,
    status: str,
    error_message: str = '',
):
    store = _load()
    store['emails'].insert(0, {
        'run_id':        run_id,
        'recipient':     recipient,
        'cc':            cc,
        'subject':       subject,
        'branch':        branch,
        'status':        status,
        'error_message': error_message,
        'sent_at':       datetime.now().isoformat(),
    })
    _save(store)

def get_run_history() -> list:
    return _load().get('runs', [])

def get_run_detail(run_id: str) -> list:
    return [e for e in _load().get('emails', []) if e['run_id'] == run_id]

def init_db():
    _ensure_dir()
    path = get_db_path()
    if not os.path.exists(path):
        _save({'settings': _default_settings(), 'runs': [], 'emails': []})

def _default_settings() -> dict:
    """Factory for fresh default settings."""
    return {
        'smtp_host':    '',
        'smtp_port':    587,
        'smtp_user':    '',
        'smtp_pass':    '',
        'from_name':    'KLM Axiva MIS',
        'use_tls':      True,
        'auto_delete':  True,
        'email_subject': 'MIS Report — {branch}',
        'email_body':   'Dear Team,\n\nPlease find attached the MIS report for {branch}.\n\nSummary:\n  Total Rows: {row_count}\n\nRegards,\nMIS Team — KLM Axiva Finvest',
        'branch_mappings': {},
    }