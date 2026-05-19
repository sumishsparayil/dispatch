# Dispatch MIS

**Dispatch** automates personalised branch-wise email dispatch for any company. Upload an Excel file, Dispatch detects branches, generates a filtered spreadsheet per branch, and sends it via SMTP — all with real-time progress tracking and full run history.

---

## Overview

- **What it does:** Sends customised branch-specific MIS reports via email, with per-branch Excel attachments
- **Who uses it:** your company operations team
- **Stack:** Flask · pandas · openpyxl · SMTP TLS
- **Deployment:** Single-command install → runs as a local web app, survives reboots

---

## Quick Start

### One-line install (fresh employee machine)

```bash
curl -sSL https://raw.githubusercontent.com/sumishsparayil/dispatch/main/setup.sh | bash
```

That's it. The script handles Python, dependencies, service setup, and auto-start.

---

## How to Use

### 1. Configure SMTP

Go to **Settings** → enter your SMTP host, port, username, and password → click **Save**.

Gmail example:
- Host: `smtp.gmail.com`
- Port: `587`
- Username: `your-email@gmail.com`
- Password: Your [Google App Password](https://support.google.com/accounts/answer/185833) (enable 2FA → App Passwords)
- From name: `Dispatch MIS`

### 2. Import Branch Emails

Go to **Settings** → **Address Book** → click **Import from Excel**. Use the `mail list.xlsx` file. Columns `gmail` and `Branch` are auto-detected.

### 3. Set Your Email Template

In **Settings** → **Email Template**, customize the subject and body.

Template variables (replaced per branch):
- `{branch}` — branch name
- `{row_count}` — number of rows for that branch
- Any column name in curly braces is replaced with its sum (e.g. `{LOAN AMOUNT}`)

### 4. Upload and Send

1. Go to **Dashboard** → drag your Excel file onto the upload area
2. Wait for parsing (progress bar shows stages)
3. Review the branch list — untick any branch to skip
4. Click **Send All Emails**

---

## Architecture

```
Excel Upload  →  Parser  →  Session (DataFrame)
                              ↓
Address Book  →  Engine  →  Exporter (per-branch xlsx)
                              ↓
                          Mailer (SMTP TLS)
                              ↓
                        Per-branch email + attachment
```

### Data Stores

| File | Contents |
|---|---|
| `db/dispatch_data.json` | SMTP config, email template, run history |
| `db/address_book.json` | Branch email addresses (single authoritative store) |
| `uploads/` | Temporary Excel files (deleted after parse) |

### Core Modules

| Module | Responsibility |
|---|---|
| `core/parser.py` | Reads Excel, detects branches, emits SSE progress |
| `core/engine.py` | Orchestrates dispatch: filter, render template, export, send |
| `core/mailer.py` | SMTP TLS connectivity and sending |
| `core/exporter.py` | Writes per-branch filtered `.xlsx` attachments |

### API Routes

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/` | Dashboard |
| `GET` | `/settings` | Settings page |
| `GET` | `/history` | Run history |
| `POST` | `/api/upload` | Upload Excel file |
| `GET` | `/api/upload-progress` | SSE parse progress |
| `GET` | `/api/session` | Current session state |
| `POST` | `/api/run` | Start email dispatch |
| `GET` | `/api/progress` | SSE dispatch progress |
| `POST` | `/api/stop` | Stop dispatch |
| `GET/POST` | `/api/settings` | Get/save settings |
| `POST` | `/api/test-smtp` | Send test email |
| `GET` | `/api/address-book` | Get address book |
| `POST` | `/api/address-book/import` | Import from Excel |
| `POST` | `/api/clear` | Clear session |

---

## Management Commands

```bash
# Start / Stop / Restart
systemctl --user start dispatch.service
systemctl --user stop dispatch.service
systemctl --user restart dispatch.service

# View logs
tail -f ~/Dispatch/app.log

# Check status
systemctl --user status dispatch.service
```

### Change Port

```bash
# Default is 5000. To change:
PORT=5100 systemctl --user restart dispatch.service
```

---

## Uninstall

```bash
systemctl --user stop dispatch.service
systemctl --user disable dispatch.service
rm -rf ~/Dispatch
```

---

## For Developers

### Local Setup

```bash
git clone https://github.com/sumishsparayil/dispatch.git
cd dispatch
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-windows.txt
./start.sh
```

### Project Structure

```
dispatch/
├── app.py                  # Flask application + all API routes
├── core/
│   ├── parser.py           # Excel parsing + branch detection
│   ├── engine.py           # Dispatch orchestration
│   ├── mailer.py           # SMTP sending
│   └── exporter.py        # Per-branch Excel export
├── db/
│   ├── database.py         # JSON store for settings + history
│   └── address_book.py     # Branch email/CC storage
├── templates/
│   ├── index.html         # Dashboard UI
│   ├── settings.html      # Settings + address book UI
│   └── history.html      # Run history UI
├── static/
│   ├── style.css
│   └── logo.png
├── uploads/               # Temp Excel storage
├── install.sh             # Full TUI installer (interactive)
├── setup.sh               # One-line automated installer
└── requirements-windows.txt
```

---

*Dispatch MIS. For any company. Use freely.*