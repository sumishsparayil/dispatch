"""
Database — JSON-based settings and run history store.

Primary store: db/dispatch_data.json
  - SMTP config (host, port, username, password, TLS flag)
  - Email template (subject line and body with {branch}, {row_count}, {COLUMN} placeholders)
  - Run history (timestamps, sent/failed counts, attachments)
  - App settings (auto_delete, default_cc)

Address Book: db/address_book.json
  - Branch email/CC mappings — single authoritative store
"""

import json
import os
import sys
from datetime import datetime

# ── Path resolver ─────────────────────────────────────────────────────────────

def get_db_path() -> str:
    """
    Return the absolute path to the settings JSON file.
    In development: resolves relative to this file's directory.
    In bundled exe:  resolves relative to the executable directory.
    """
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
    """Load the full JSON store. Returns an empty shell if the file does not exist."""
    path = get_db_path()
    if not os.path.exists(path):
        return {'settings': {}, 'runs': [], 'emails': []}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {'settings': {}, 'runs': [], 'emails': []}


def _save(data: dict):
    """Atomically write data to the JSON store."""
    path = get_db_path()
    _ensure_dir()
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Keyring helpers ─────────────────────────────────────────────────────────────
# Used only when keyring is available (Linux/Windows desktop environments).
# Stores SMTP credentials in the OS credential store.

_KEYRING_SERVICE = "Dispatch_MIS"


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


# ── Settings ───────────────────────────────────────────────────────────────────

def get_settings() -> dict:
    """
    Returns all settings. smtp_pass is included.
    Note: branch_mappings are stored in address_book.json — never here.
    """
    return _load().get('settings', {})


def save_settings(key: str, value):
    """Save a single setting to dispatch_data.json."""
    store = _load()
    store['settings'][key] = value
    _save(store)


def save_settings_batch(raw: dict):
    """
    Batch-save settings to dispatch_data.json.
    branch_mappings is silently dropped — address_book.json is the only store.
    smtp_pass is stored in plain text (acceptable for an internal tool behind a VPN).
    """
    store = _load()
    for key, value in raw.items():
        if key != 'branch_mappings':
            store['settings'][key] = value
    _save(store)


def get_password_for_smtp() -> str:
    """Return smtp_pass from dispatch_data.json."""
    return get_settings().get('smtp_pass', '')


# ── Run History ────────────────────────────────────────────────────────────────

def log_run_start(run_id: str, filename: str, total_rows: int) -> str:
    """
    Record the start of a dispatch run.
    Keeps the 50 most recent runs ( FIFO ).
    """
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
    """Record run completion with sent/failed counts and elapsed time."""
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
    """
    Log a single email result (sent or failed) for a given run.
    Appended in reverse-chronological order. Unbounded — older entries
    are pruned only when the run log itself is truncated.
    """
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
    """Return all past runs, most recent first."""
    return _load().get('runs', [])


def get_run_detail(run_id: str) -> list:
    """Return all email records for a specific run."""
    return [e for e in _load().get('emails', []) if e['run_id'] == run_id]


def init_db():
    """Create the db/ directory and dispatch_data.json on first run."""
    _ensure_dir()
    path = get_db_path()
    if not os.path.exists(path):
        _save({'settings': _default_settings(), 'runs': [], 'emails': []})


def _default_settings() -> dict:
    """
    Factory for fresh default settings.
    These are used when dispatch_data.json does not yet exist.
    Modify these to change the factory defaults for new installs.
    """
    return {
        'smtp_host':    '',
        'smtp_port':    587,
        'smtp_user':    '',
        'smtp_pass':    '',
        'from_name':    'Dispatch MIS',
        'use_tls':      True,
        'auto_delete':  True,
        'email_subject': 'MIS Report — {branch}',
        'email_body':   (
            'Dear Team,\n\n'
            'Please find attached the MIS report for {branch}.\n\n'
            'Summary:\n'
            '  Total Rows: {row_count}\n\n'
            'Regards,\n'
            'MIS Team'
        ),
    }