"""Panther — MIS Email Dispatch Application (v4).

Architecture (v4):
  - Excel upload contains ONLY raw data (no Mail List sheet)
  - Branch names extracted from 'Branch' column in the Data sheet
  - Email config: recipient mapping + subject/body template → stored in db/dispatch_data.json
  - Settings tab: SMTP config + Email template editor + Branch mapping table
  - Engine pulls email config from JSON store, not from Excel
  - Address Book: persistent branch email/CC store at db/address_book.json
"""

import gc
import os
import sys
import json
import time as _time
import threading
import queue

# ── App directory (dev vs bundled exe) ─────────────────────────
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

os.chdir(APP_DIR)

from flask import Flask, render_template, request, jsonify, Response
from werkzeug.utils import secure_filename
import pandas as pd
import uuid

from core.parser import PantherParser
from core.engine import PantherEngine
from core.mailer import PantherMailer
from core.exporter import PantherExporter
from db.database import (
    init_db, get_settings, save_settings_batch, get_password_for_smtp,
    get_run_history, log_run_start, log_run_complete, log_email_result,
    get_run_detail,
)
from db.address_book import (
    get_address_book, save_address_book,
    add_branch, update_branch, delete_branch,
    import_from_excel, export_to_excel,
)

# ── Default from name (single source of truth) ─────────────────
DEFAULT_FROM_NAME = 'KLM Axiva MIS'

# ── App setup ──────────────────────────────────────────────────
app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['UPLOAD_FOLDER'] = os.path.join(APP_DIR, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024   # 200 MB limit

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Ensure DB and address book exist on first run
init_db()

# ── In-memory session ──────────────────────────────────────────
_session = {
    'data_df':      None,
    'branches':     [],
    'columns':      [],
    'branch_col':   None,   # exact 'Branch' column name from parser
    'total_rows':   0,
    'filename':     None,
    'id':           None,
}

# ── Parse progress queue ───────────────────────────────────────
_parse_progress_queue = queue.Queue()
_current_parser = [None]   # wrapped in list for mutability in closure


# ── Helpers ─────────────────────────────────────────────────────
def _smtp_settings():
    """SMTP config dict for the mailer — single source of truth."""
    s = get_settings()
    return {
        'smtp_host': s.get('smtp_host', ''),
        'smtp_port': int(s.get('smtp_port') or 587),
        'smtp_user': s.get('smtp_user', ''),
        'smtp_pass': s.get('smtp_pass') or get_password_for_smtp(),
        'from_name': s.get('from_name', DEFAULT_FROM_NAME),
        'use_tls':   s.get('use_tls', True),
    }


# ── Pages ───────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/settings')
def settings_page():
    return render_template('settings.html')


@app.route('/history')
def history_page():
    runs = get_run_history()
    return render_template('history.html', runs=runs)


# ── API: Upload & Parse ─────────────────────────────────────────
@app.route('/api/upload', methods=['POST'])
def api_upload():
    if 'file' not in request.files:
        return jsonify({'ok': False, 'error': 'No file provided.'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'ok': False, 'error': 'No file selected.'}), 400

    filename = secure_filename(file.filename or 'upload.xlsx')
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    # Clear any old progress
    while not _parse_progress_queue.empty():
        try:
            _parse_progress_queue.get_nowait()
        except queue.Empty:
            break

    def background_parse():
        def progress_callback(stage, message, percent):
            _parse_progress_queue.put({
                'status': stage,
                'message': message,
                'progress': percent,
            })

        try:
            parser = PantherParser(filepath, progress_callback=progress_callback)
            _current_parser[0] = parser
            result = parser.parse()

            _session['data_df']    = result['data_df']
            _session['branches']   = result['branches']
            _session['columns']   = result['columns']
            _session['branch_col']= result['branch_col']
            _session['total_rows']= result['total_data_rows']
            _session['filename']   = filename
            _session['id']         = result['session_id']

            # Emit done with full summary
            _parse_progress_queue.put({
                'status': 'done',
                'message': f"Ready — {result['total_branches']} branches, {result['total_data_rows']:,} rows",
                'progress': 100,
                'session': {
                    'session_id':     result['session_id'],
                    'filename':       filename,
                    'total_rows':     result['total_data_rows'],
                    'total_branches': result['total_branches'],
                    'branches':       result['branches'],
                    'columns':        result['columns'],
                    'branch_col':     result['branch_col'],
                },
            })
        except ValueError as e:
            _parse_progress_queue.put({'status': 'error', 'message': str(e), 'progress': 0})
        except Exception as e:
            _parse_progress_queue.put({'status': 'error', 'message': f'Parse error: {e}', 'progress': 0})
        finally:
            _current_parser[0] = None
            try:
                os.remove(filepath)
            except OSError:
                pass

    t = threading.Thread(target=background_parse, daemon=True)
    t.start()

    return jsonify({'ok': True})


@app.route('/api/upload-progress')
def api_upload_progress():
    def generate():
        last_heartbeat = _time.time()
        while True:
            try:
                entry = _parse_progress_queue.get(timeout=25)
                yield f"data: {json.dumps(entry)}\n\n"
                if entry.get('status') in ('done', 'error'):
                    break
            except queue.Empty:
                elapsed = _time.time() - last_heartbeat
                if elapsed >= 20:
                    yield f": heartbeat\n\n"
                    last_heartbeat = _time.time()
                continue
            else:
                last_heartbeat = _time.time()
        yield f": stream closed\n\n"

    return Response(generate(), mimetype='text/event-stream')


@app.route('/api/session', methods=['GET'])
def api_session():
    if _session['data_df'] is None:
        return jsonify({'active': False})

    return jsonify({
        'active':          True,
        'session_id':      _session['id'],
        'filename':        _session['filename'],
        'total_rows':      _session['total_rows'],
        'total_branches':  len(_session['branches']),
        'branches':        _session['branches'],
        'columns':         _session['columns'],
        'branch_col':      _session['branch_col'],
    })


# ── API: Run Dispatch ───────────────────────────────────────────
@app.route('/api/run', methods=['POST'])
def api_run():
    if _session['data_df'] is None:
        return jsonify({'error': 'No data loaded. Upload a file first.'}), 400

    settings = get_settings()
    if not settings.get('smtp_host'):
        return jsonify({'error': 'SMTP not configured. Go to Settings first.'}), 400

    json_body = request.get_json(silent=True) or {}
    excluded_branches = json_body.get('excluded_branches', [])
    test_only = json_body.get('test_only', False)

    # Build settings for the engine — address_book is the single source of truth
    ab = get_address_book()
    branch_mappings = {
        str(branch): {'email': info.get('email', ''), 'cc': info.get('cc', '')}
        for branch, info in ab.get('branches', {}).items()
        if info.get('email')
    }
    full_settings = {
        **_smtp_settings(),
        'auto_delete': settings.get('auto_delete', True),
        'branch_mappings': branch_mappings,
        'email_subject': settings.get('email_subject', ''),
        'email_body': settings.get('email_body', ''),
    }

    # Test mode: redirect first branch to operator's own email
    test_branches = _session['branches']
    if test_only:
        test_recipient = settings.get('test_recipient', '').strip()
        if not test_recipient:
            test_recipient = settings.get('smtp_user', '').strip()
        if not test_recipient:
            return jsonify({'error': 'No test recipient configured. Set a Test Recipient email in Settings, or ensure SMTP Username is set.'}), 400
        if test_branches:
            first = test_branches[0]['branch']
            bm = {**branch_mappings, first: {'email': test_recipient, 'cc': ''}}
            full_settings['branch_mappings'] = bm

    PantherEngine.clear_log()

    engine = PantherEngine(
        branches=test_branches,
        data_df=_session['data_df'],
        branch_col=_session['branch_col'],
        settings=full_settings,
        upload_folder=app.config['UPLOAD_FOLDER'],
        filename=_session['filename'],
        test_only=test_only,
        excluded_branches=excluded_branches,
    )
    engine.start()

    return jsonify({'ok': True})


@app.route('/api/progress')
def api_progress():
    def generate():
        last_len = 0
        last_heartbeat = _time.time()
        while True:
            log = PantherEngine.get_log()
            if len(log) != last_len:
                last_len = len(log)
                entry = log[-1]
                yield f"data: {json.dumps(entry)}\n\n"
                if entry.get('done'):
                    break
            elapsed = _time.time() - last_heartbeat
            if elapsed >= 15:
                yield f": heartbeat\n\n"
                last_heartbeat = _time.time()
            _time.sleep(0.4)
        yield f": stream closed\n\n"

    return Response(generate(), mimetype='text/event-stream')


@app.route('/api/stop', methods=['POST'])
def api_stop():
    PantherEngine.stop()
    return jsonify({'ok': True})


# ── API: Settings ───────────────────────────────────────────────
@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    """
    GET: returns SMTP config + email template only.
    POST: saves SMTP/email settings. branch_mappings is NOT saved here —
    use the address-book API instead.
    """
    if request.method == 'POST':
        raw = request.get_json() or {}
        # Strip branch_mappings silently — address book is the only store
        raw = {k: v for k, v in raw.items() if k != 'branch_mappings'}
        save_settings_batch(raw)
        return jsonify({'ok': True})
    return jsonify(get_settings())


@app.route('/api/test-smtp', methods=['POST'])
def api_test_smtp():
    data = request.get_json() or {}
    pass_value = data.get('smtp_pass', '') or get_password_for_smtp()
    settings = {
        'smtp_host':  data.get('smtp_host', ''),
        'smtp_port':  int(data.get('smtp_port') or 587),
        'smtp_user':  data.get('smtp_user', ''),
        'smtp_pass':  pass_value,
        'from_name':  data.get('from_name', DEFAULT_FROM_NAME),
        'use_tls':    data.get('use_tls', True),
    }
    try:
        mailer = PantherMailer(settings)
        result = mailer.send_test(to=data.get('test_recipient', ''))
        return jsonify(result)
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400


# ── API: Address Book ───────────────────────────────────────────
@app.route('/api/address-book', methods=['GET'])
def api_address_book():
    """Returns full address book."""
    return jsonify(get_address_book())


@app.route('/api/address-book/branches', methods=['POST'])
def api_address_book_add_branch():
    """Add a new branch. Payload: {branch, email, cc}"""
    data = request.get_json() or {}
    branch = str(data.get('branch', '')).strip()
    if not branch:
        return jsonify({'ok': False, 'error': 'Branch name is required'}), 400
    add_branch(branch, data.get('email', ''), data.get('cc', ''))
    return jsonify({'ok': True})


@app.route('/api/address-book/branches/<path:branch>', methods=['PUT'])
def api_address_book_update_branch(branch):
    """Update a branch. Payload: {email, cc}"""
    data = request.get_json() or {}
    update_branch(branch, data.get('email', ''), data.get('cc', ''))
    return jsonify({'ok': True})


@app.route('/api/address-book/branches/<path:branch>', methods=['DELETE'])
def api_address_book_delete_branch(branch):
    """Delete a branch from address book."""
    delete_branch(branch)
    return jsonify({'ok': True})


@app.route('/api/address-book/import', methods=['POST'])
def api_address_book_import():
    """Bulk import branches from uploaded .xlsx"""
    if 'file' not in request.files:
        return jsonify({'ok': False, 'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename.endswith('.xlsx'):
        return jsonify({'ok': False, 'error': 'Only .xlsx files are supported'}), 400

    filename = secure_filename(file.filename or 'import.xlsx')
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    try:
        result = import_from_excel(filepath)
    finally:
        try:
            os.remove(filepath)
        except OSError:
            pass

    return jsonify({'ok': True, **result})


@app.route('/api/address-book/export', methods=['GET'])
def api_address_book_export():
    """Download address_book.xlsx"""
    try:
        buf = export_to_excel()
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

    from flask import make_response
    response = make_response(buf)
    response.headers['Content-Type'] = (
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response.headers['Content-Disposition'] = (
        'attachment; filename=address_book.xlsx'
    )
    return response


@app.route('/api/address-book/fill-from-session', methods=['POST'])
def api_address_book_fill_from_session():
    """Create address book stubs for branches in the current session that don't yet exist."""
    if _session['data_df'] is None:
        return jsonify({'ok': False, 'error': 'No active session'}), 400

    added = 0
    for b in _session['branches']:
        name = b['branch']
        ab = get_address_book()
        if name not in ab['branches']:
            add_branch(name, '', '')
            added += 1

    return jsonify({'ok': True, 'added': added})


# ── API: History ───────────────────────────────────────────────
@app.route('/api/history/clear', methods=['POST'])
def api_history_clear():
    """Delete all run history and email records."""
    from db.database import _load, _save
    store = _load()
    store['runs'] = []
    store['emails'] = []
    _save(store)
    return jsonify({'ok': True, 'message': 'All history cleared'})


@app.route('/api/run-detail/<run_id>', methods=['GET'])
def api_run_detail(run_id):
    return jsonify(get_run_detail(run_id))


@app.route('/api/export-log/<run_id>', methods=['GET'])
def api_export_log(run_id):
    from io import StringIO
    import csv

    rows = get_run_detail(run_id)
    si = StringIO()
    writer = csv.writer(si)
    writer.writerow([
        'Branch', 'Recipient', 'CC', 'Subject', 'Status', 'Error', 'Sent At'
    ])
    for r in rows:
        writer.writerow([
            r.get('branch', ''),
            r.get('recipient', ''),
            r.get('cc', ''),
            r.get('subject', ''),
            r.get('status', ''),
            r.get('error_message', ''),
            r.get('sent_at', ''),
        ])

    output = Response(si.getvalue(), mimetype='text/csv')
    output.headers['Content-Disposition'] = (
        f'attachment; filename=dispatch_run_{run_id}.csv'
    )
    return output


# ── API: Clear session ─────────────────────────────────────────
@app.route('/api/clear', methods=['POST'])
def api_clear():
    # Idempotent — no error if already clear
    _session['data_df']    = None
    _session['branches']   = []
    _session['columns']    = []
    _session['branch_col'] = None
    _session['total_rows'] = 0
    _session['filename']   = None
    _session['id']         = None
    _current_parser[0] = None   # release parser reference
    while not _parse_progress_queue.empty():
        try:
            _parse_progress_queue.get_nowait()
        except queue.Empty:
            break
    PantherEngine.clear_log()
    gc.collect()
    return jsonify({'ok': True, 'message': 'Session cleared, RAM released'})


# ── API: Download reference template ──────────────────────────
@app.route('/api/download-template', methods=['GET'])
def api_download_template():
    import io
    import pandas as pd
    from flask import make_response

    cols = [
        'SL NO', 'Branch Name', 'Sangam Name', 'Center Meeting Day',
        'Demand Meeting Day', 'Payment Frequency', 'LOAN NUMBER',
        'OLD ACCOUNT NUMBER', 'CUSTOMER ID', 'CUSTOMER NAME',
        'CUSTOMER MOBILE NO', 'NOMINEE NAME', 'NOMINEE MOBILE NO',
        'LOAN DATE', 'LOAN AMOUNT', 'PRESENT OUTSTANDING',
        'PRINCIPAL OUTSTANDING', 'INTEREST OUTSTANDING', 'ARREAR AMOUNT',
        'INTEREST', 'PRINCIMFE', 'Aging Days', 'Credit Executive Name',
        'Last Paid Date', 'Prepaid Amount', 'Total Installments',
        'Current Installment No.', 'Current Schedule Date',
        'Paid Installments', 'Pending Installments',
        'First OD reflect Date', 'Installment Amount',
        'Final Installment Scheduled Date', 'Last Payment Date',
        'Paid Amount1', 'Last Payment Date 1',
        'Paid Amount2', 'Last Payment Date 2',
        'Paid Amount3', 'Last Payment Date 3', 'Paid Amount',
        'Product Code-Name', 'Scheme Code-Name', 'SMA Classification',
        'First Installment Date', 'Company', 'Area', 'Region', 'SMA',
        'Demand Slip Amount', 'Net OD', 'March SMA Status',
        'Settlement Amt', 'FY LD', 'Loan Type',
        'Nominee name', 'Nominee mobile nr', 'Bucket Movement',
        'Category', 'Slip Bucket', 'Allocation', 'Last Activate Month',
        'Last Activated Year', 'Unolo total visit', 'Visit employee ID',
        'Visit employee ID Astdail connected',
    ]

    example = {col: '' for col in cols}
    example['Branch']        = 'PL-ALAPPUZHA'
    example['CUSTOMER NAME'] = 'Sample Customer'
    example['LOAN AMOUNT']   = '50000'

    df = pd.DataFrame([example])[cols]

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Data', index=False)

        # Branch mapping reference sheet
        mapping_df = pd.DataFrame([
            {'Branch': 'PL-ALAPPUZHA', 'Email': 'mfin.alappuzha@klmaxiva.com', 'CC': ''},
            {'Branch': 'PL-ERNAKULAM', 'Email': 'mfin.ernakulam@klmaxiva.com', 'CC': ''},
        ])
        mapping_df.to_excel(writer, sheet_name='Branch Mapping', index=False)

    buf.seek(0)
    response = make_response(buf.getvalue())
    response.headers['Content-Type'] = (
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response.headers['Content-Disposition'] = (
        'attachment; filename=Panther_Reference_Template.xlsx'
    )
    return response


# ── Run ───────────────────────────────────────────────────────
if __name__ == '__main__':
    import socket

    PORT = 5000
    for attempt in range(10):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(('0.0.0.0', PORT))
            s.close()
            break
        except OSError:
            PORT += 1
    else:
        print('ERROR: Could not find a free port between 5000-5009.')
        sys.exit(1)

    print(f'Panther running on http://localhost:{PORT}')
    print(f'Network: http://0.0.0.0:{PORT}')

    from waitress import serve
    serve(app, host='0.0.0.0', port=PORT, threads=8)