"""
Address Book — persistent branch email/CC storage.
Stored at db/address_book.json, survives app restarts.
"""

import json
import os
from datetime import datetime

ADDRESS_BOOK_PATH = os.path.join(os.path.dirname(__file__), 'address_book.json')


def _load() -> dict:
    if not os.path.exists(ADDRESS_BOOK_PATH):
        return _empty()
    try:
        with open(ADDRESS_BOOK_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return _empty()


def _save(data: dict):
    with open(ADDRESS_BOOK_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _empty() -> dict:
    return {"branches": {}, "default_cc": ""}


# ── Public API ─────────────────────────────────────────────────

def get_address_book() -> dict:
    """Returns full address book with branches + default_cc."""
    return _load()


def save_address_book(data: dict) -> None:
    """Replaces the entire address book."""
    _save({
        "branches": data.get("branches", {}),
        "default_cc": data.get("default_cc", ""),
    })


def add_branch(branch: str, email: str = "", cc: str = "") -> None:
    book = _load()
    now = datetime.now().isoformat()
    if branch not in book["branches"]:
        book["branches"][branch] = {"email": email, "cc": cc, "added_at": now, "updated_at": now}
    _save(book)


def update_branch(branch: str, email: str, cc: str = "") -> None:
    book = _load()
    now = datetime.now().isoformat()
    if branch in book["branches"]:
        book["branches"][branch]["email"] = email
        book["branches"][branch]["cc"] = cc
        book["branches"][branch]["updated_at"] = now
    else:
        book["branches"][branch] = {"email": email, "cc": cc, "added_at": now, "updated_at": now}
    _save(book)


def delete_branch(branch: str) -> None:
    book = _load()
    if branch in book["branches"]:
        del book["branches"][branch]
        _save(book)


def import_from_excel(filepath: str) -> dict:
    """
    Reads an .xlsx with 'Branch' + 'Email' + 'CC' columns.
    Returns {"added": int, "updated": int, "errors": list}.
    """
    import pandas as pd

    added = 0
    updated = 0
    errors = []

    try:
        df = pd.read_excel(filepath, sheet_name=0, dtype=str)
        df.columns = df.columns.str.strip()

        # Normalise column names
        branch_col = None
        email_col = None
        cc_col = None

        for col in df.columns:
            cl = str(col).lower().strip()
            if cl == 'branch':
                branch_col = col
            elif cl in ('email', 'gmail', 'mail', 'e_mail'):
                email_col = col
            elif cl == 'cc':
                cc_col = col

        if branch_col is None or email_col is None:
            errors.append("Excel must have 'Branch' and 'Email' columns.")
            return {"added": 0, "updated": 0, "errors": errors}

        book = _load()
        now = datetime.now().isoformat()

        for _, row in df.iterrows():
            branch = str(row.get(branch_col, '')).strip()
            email = str(row.get(email_col, '')).strip()
            cc = str(row.get(cc_col, '') if cc_col else '').strip()

            if not branch or branch in ('nan', 'None', 'NaN', ''):
                errors.append(f"Skipped row with empty branch name: {row.to_dict()}")
                continue

            if branch in book["branches"]:
                book["branches"][branch]["email"] = email
                book["branches"][branch]["cc"] = cc
                book["branches"][branch]["updated_at"] = now
                updated += 1
            else:
                book["branches"][branch] = {
                    "email": email,
                    "cc": cc,
                    "added_at": now,
                    "updated_at": now,
                }
                added += 1

        _save(book)

    except Exception as e:
        errors.append(f"Failed to read Excel file: {e}")

    return {"added": added, "updated": updated, "errors": errors}


def export_to_excel() -> bytes:
    """Returns .xlsx file bytes for download."""
    import io
    import pandas as pd

    book = _load()
    rows = []
    for branch, info in sorted(book["branches"].items()):
        rows.append({
            "Branch": branch,
            "Email": info.get("email", ""),
            "CC": info.get("cc", ""),
        })

    df = pd.DataFrame(rows, columns=["Branch", "Email", "CC"])

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Address Book', index=False)

    buf.seek(0)
    return buf.getvalue()