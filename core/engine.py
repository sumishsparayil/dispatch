"""
Engine — filters raw data by branch and dispatches emails.

Orchestrates the full dispatch pipeline in a background thread:
  1. Build branch_mappings from address_book.json (the single authoritative store)
  2. For each branch: filter rows → render template → export Excel → send email
  3. Emit log entries via a shared thread-safe log
  4. Clean up exported files after sending

Supports:
  - excluded_branches  — user unchecked branches in the UI review step
  - test_only          — send to operator's own email only (first branch)
  - Dynamic {variable} injection into email subject and body
  - RAM cleanup via gc.collect() after run completes
  - Thread-safe SSE log via module-level _log with _log_lock
"""

import gc
import re
import threading
import uuid
from datetime import datetime

import pandas as pd

from core.exporter import PantherExporter
from core.mailer import PantherMailer
from db.database import log_run_start, log_run_complete, log_email_result


# ── Shared run log (thread-safe) ─────────────────────────────────────────────
# Module-level mutable list. Updated by the engine thread; polled by the SSE
# endpoint. Protected by _log_lock for thread safety.
_log = []
_log_lock = threading.Lock()

# Global stop flag. Checked between each branch. Set by /api/stop.
_stop_flag = False


# ══════════════════════════════════════════════════════════════════════════════
# PantherEngine
# ══════════════════════════════════════════════════════════════════════════════

class PantherEngine:
    """
    Runs email dispatch in a background thread after start() is called.

    Parameters
    ----------
    branches : list[dict]
        List of {branch: str, count: int} dicts from the parser.
        Represents all branches detected in the uploaded Excel file.
    data_df : pd.DataFrame
        Full parsed Pandas DataFrame from the session.
    branch_col : str
        Exact column name for 'Branch' (preserves case from the Excel file).
    settings : dict
        Full application settings. Must contain:
          - branch_mappings : {branch_name: {email, cc}}
          - email_subject    : str — template with {branch}, {row_count}, {COLUMN} placeholders
          - email_body      : str — same placeholders
          - smtp_host, smtp_port, smtp_user, smtp_pass, from_name, use_tls
    upload_folder : str
        Directory where per-branch Excel attachments are written.
    filename : str
        Original uploaded filename (for run history logging).
    test_only : bool, default False
        If True, send only to the operator's own email (smtp_user from settings).
        All other branches are skipped.
    excluded_branches : list[str], optional
        Branch names unchecked by the user in the UI review step.
        These are skipped silently (no error logged).
    """

    # Regex: matches {tag} where tag may contain letters, numbers, spaces,
    # underscores, or hyphens. Used for template variable substitution.
    VARIABLE_PATTERN = re.compile(r'\{([^}]+)\}')

    @classmethod
    def get_log(cls) -> list:
        """Return a snapshot of all log entries since engine start."""
        with _log_lock:
            return list(_log)

    @classmethod
    def clear_log(cls):
        """Clear all log entries. Called when session is cleared."""
        global _log
        with _log_lock:
            _log = []

    @classmethod
    def stop(cls):
        """
        Signal the engine to halt after the current branch.
        The engine checks _stop_flag between each branch in the run loop.
        """
        global _stop_flag
        _stop_flag = True

    def __init__(
        self,
        branches,          # list[dict] — [{branch: str, count: int}, ...]
        data_df,           # pd.DataFrame
        branch_col,        # str
        settings,          # dict
        upload_folder,     # str
        filename='',
        test_only=False,
        excluded_branches=None,
    ):
        self.branches = branches
        self.data_df = data_df
        self.branch_col = branch_col
        self.settings = settings
        self.upload_folder = upload_folder
        self.filename = filename
        self.test_only = test_only
        self.excluded_branches = set(excluded_branches or [])
        self.run_id = uuid.uuid4().hex[:12]

    def start(self):
        """
        Launch the dispatch pipeline in a daemon background thread.
        Call this after constructing the engine. Progress is emitted via get_log().
        """
        global _stop_flag
        _stop_flag = False
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

    def _run(self):
        """
        Main dispatch loop. Runs in a background thread.

        Pipeline per branch:
          1. Filter DataFrame by branch name
          2. Calculate branch metrics (row_count, totals, counts)
          3. Render email subject and body with branch-specific values
          4. Export filtered Excel attachment
          5. Send email via SMTP
          6. Log result (sent/failed) to database
          7. Auto-delete Excel attachment (if auto_delete=True in settings)

        The loop checks _stop_flag after each branch. If set, it breaks
        cleanly without raising an error.
        """
        global _stop_flag

        branch_mappings = self.settings.get('branch_mappings', {})
        email_subject_template = self.settings.get('email_subject', '')
        email_body_template = self.settings.get('email_body', '')
        from_name = self.settings.get('from_name', 'KLM Axiva MIS')
        use_tls = self.settings.get('use_tls', True)

        # Build target list: only branches with a valid email address.
        # Excluded branches are filtered out silently.
        target_list = [
            b for b in self.branches
            if b['branch'] not in self.excluded_branches
            and b['branch'] in branch_mappings
            and branch_mappings[b['branch']].get('email', '').strip()
        ]

        # Log branches with no email mapping (informational only — not an error)
        unmapped = [
            b['branch'] for b in self.branches
            if b['branch'] not in self.excluded_branches
            and b['branch'] not in branch_mappings
        ]
        for branch in unmapped:
            self._log(
                'SKIPPED',
                f'{branch} — no email mapping configured, skipped',
                'warning',
            )

        if not target_list:
            self._log(
                'COMPLETE',
                'No branches to send — add email mappings in Settings first.',
                'warning',
                total=0, sent=0, failed=0, done=True, run_id=self.run_id,
            )
            return

        total_rows = int(len(self.data_df))
        log_run_start(self.run_id, self.filename, total_rows)

        # SMTP config for the mailer
        smtp_settings = {
            'smtp_host': self.settings.get('smtp_host', ''),
            'smtp_port': int(self.settings.get('smtp_port') or 587),
            'smtp_user': self.settings.get('smtp_user', ''),
            'smtp_pass': self.settings.get('smtp_pass', ''),
            'from_name': from_name,
            'use_tls': use_tls,
        }
        mailer = PantherMailer(smtp_settings)
        exporter = PantherExporter()

        sent = 0
        failed = 0

        for i, branch_info in enumerate(target_list):
            # Check for user-initiated stop
            if _stop_flag:
                self._log(
                    'STOPPED',
                    f'Run halted by user at email {i + 1}',
                    'warning',
                    done=True,
                )
                break

            branch = branch_info['branch']
            mapping = branch_mappings.get(branch, {})
            recipient = mapping.get('email', '').strip()
            cc = mapping.get('cc', '').strip()

            self._log(
                'PROCESSING',
                f'{branch} → {recipient}',
                'info',
                email_num=i + 1,
                total=len(target_list),
                branch=branch,
            )

            try:
                # ── 1. Filter DataFrame by branch name ─────────────────────────
                filtered = self.data_df[self.data_df[self.branch_col] == branch]

                # ── 2. Calculate branch metrics ───────────────────────────────
                metrics = self._calc_branch_metrics(filtered)
                metrics['row_count'] = len(filtered)

                # ── 3. Render email template ──────────────────────────────────
                subject = self._render_template(
                    email_subject_template, branch, metrics, filtered
                )
                body = self._render_template(
                    email_body_template, branch, metrics, filtered
                )

                # ── 4. Export Excel attachment ────────────────────────────────
                attachment_path = exporter.export(
                    data=filtered,
                    subject=subject,
                    upload_folder=self.upload_folder,
                )

                # ── 5. Send email ──────────────────────────────────────────
                result = mailer.send(
                    to=recipient,
                    cc=cc,
                    subject=subject,
                    body=body,
                    attachment_path=attachment_path,
                )

                if result['ok']:
                    sent += 1
                    status = 'sent'
                    error = ''
                    self._log(
                        'SENT',
                        f'{branch} → {recipient}  ({metrics["row_count"]} rows)',
                        'success',
                        email_num=i + 1,
                        total=len(target_list),
                        branch=branch,
                    )
                else:
                    failed += 1
                    status = 'failed'
                    error = result.get('error', 'Unknown error')
                    self._log(
                        'FAILED',
                        f'{branch} → {recipient}: {error}',
                        'error',
                        email_num=i + 1,
                        total=len(target_list),
                        branch=branch,
                    )

                log_email_result(
                    self.run_id, recipient, cc, subject,
                    branch, status, error,
                )

                # ── 6. Auto-cleanup attachment ───────────────────────────────
                if self.settings.get('auto_delete', True):
                    exporter.cleanup(attachment_path)

            except Exception as e:
                failed += 1
                self._log(
                    'FAILED',
                    f'{branch} → {recipient}: {str(e)}',
                    'error',
                    email_num=i + 1,
                    total=len(target_list),
                    branch=branch,
                )
                log_email_result(
                    self.run_id, recipient, cc, subject or email_subject_template,
                    branch, 'failed', str(e),
                )

        # Record run completion
        log_run_complete(self.run_id, sent, failed)
        self._log(
            'COMPLETE',
            f'Done — {sent} sent, {failed} failed',
            'success' if failed == 0 else 'warning',
            total=len(target_list),
            sent=sent,
            failed=failed,
            done=True,
            run_id=self.run_id,
        )

        # Release memory after large dispatches
        gc.collect()

    # ── Template rendering ────────────────────────────────────────────────────

    def _render_template(self, template: str, branch: str, metrics: dict, filtered_df) -> str:
        """
        Replace {variable} placeholders in template strings.

        Built-in variables:
          {branch}              — branch display name (e.g. 'PL-ALAPPUZHA')
          {row_count}           — number of rows in branch subset
          {total_outstanding}    — sum of outstanding columns (auto-detected)
          {total_demand_loss}    — sum of demand loss columns (auto-detected)
          {total_aging}         — sum of aging columns (auto-detected)
          {npa_count}           — count of NPA rows
          {fresh_od_count}      — count of fresh OD rows
          {tenure_completed_count} — count of tenure-completed rows

        Dynamic {COLUMN NAME}:
          Any column name in curly braces is looked up in the filtered DataFrame.
          Numeric columns → sum, formatted as Indian-style comma-separated integer.
          Non-numeric columns → first non-empty value.
          Lookup is case-insensitive.
        """
        if not template:
            return template

        def replacer(match):
            raw_tag = match.group(1)
            key = raw_tag.lower().strip()

            # ── Built-in variables ─────────────────────────────────────────
            if key in ('branch_name', 'branch'):
                return str(branch)
            if key in ('row_count', 'total_rows', 'rows'):
                return str(metrics.get('row_count', 0))
            if key == 'total_outstanding':
                v = metrics.get('total_outstanding', 0)
                return f"{v:,.0f}" if v else "0"
            if key == 'total_demand_loss':
                v = metrics.get('total_demand_loss', 0)
                return f"{v:,.0f}" if v else "0"
            if key == 'total_aging':
                v = metrics.get('total_aging', 0)
                return f"{v:,.0f}" if v else "0"
            if key in ('npa_count',):
                return str(metrics.get('npa_count', 0))
            if key in ('fresh_od_count',):
                return str(metrics.get('fresh_od_count', 0))
            if key in ('tenure_completed_count',):
                return str(metrics.get('tenure_completed_count', 0))

            # ── Dynamic column variables ──────────────────────────────────
            # Case-insensitive exact match, then partial match as fallback.
            col_candidates = []
            for col in filtered_df.columns:
                cl = str(col).lower().strip()
                if cl == key and not col_candidates:
                    col_candidates = [str(col)]
                    break
                elif key in cl and not col_candidates:
                    col_candidates.append(str(col))

            if col_candidates:
                col = col_candidates[0]
                try:
                    numeric = pd.to_numeric(filtered_df[col], errors='coerce')
                    if not numeric.isna().all():
                        total = float(numeric.sum())
                        return f"{total:,.0f}" if total else "0"
                except Exception:
                    pass
                # Non-numeric: first non-empty value
                for val in filtered_df[col].fillna('').astype(str):
                    if val and val.strip() not in ('', 'nan', 'None', 'NaN'):
                        return val.strip()

            # Unknown variable: leave the literal {tag} unchanged
            return match.group(0)

        return self.VARIABLE_PATTERN.sub(replacer, template)

    @staticmethod
    def _calc_branch_metrics(filtered_df) -> dict:
        """
        Calculate summary metrics from a filtered branch DataFrame.

        Metrics:
          total_outstanding       — sum of any column with 'outstanding', 'os amount', 'balance', 'os'
          total_demand_loss       — sum of any column with 'demand loss' or 'demandloss'
          total_aging             — sum of any column with 'aging' or 'age'
          npa_count              — count of non-empty/non-zero values in any column with 'npa'
          fresh_od_count         — count in columns matching 'fresh od', 'freshod', 'new od'
          tenure_completed_count — count in columns matching 'tenure completed'

        Column lookup is case-insensitive and uses partial matching so that
        variations in column naming are tolerated.
        """
        metrics = {}
        if filtered_df.empty:
            return metrics

        def find_col(partials):
            """Return the first column whose name contains any of the given partial strings."""
            for col in filtered_df.columns:
                cl = col.lower().strip()
                if any(p in cl for p in partials):
                    return col
            return None

        def sum_col(col_name, partials):
            col = col_name or find_col(partials)
            if col is None:
                return 0
            try:
                return float(
                    pd.to_numeric(filtered_df[col], errors='coerce')
                    .fillna(0).sum()
                )
            except Exception:
                return 0

        def count_col(partials):
            col = find_col(partials)
            if col is None:
                return 0
            vals = filtered_df[col].fillna('').astype(str).str.strip()
            return int(vals[~vals.isin(['', '0', '0.0', 'nan', 'None'])].count())

        metrics['total_outstanding']       = sum_col(None, ['outstanding', 'os amount', 'balance', 'os'])
        metrics['total_demand_loss']       = sum_col(None, ['demand loss', 'demandloss'])
        metrics['total_aging']             = sum_col(None, ['aging', 'age'])
        metrics['npa_count']               = count_col(['npa'])
        metrics['fresh_od_count']          = count_col(['fresh od', 'freshod', 'new od'])
        metrics['tenure_completed_count']  = count_col(['tenure completed', 'tenurecompleted'])

        return metrics

    # ── Logging ─────────────────────────────────────────────────────────────

    def _log(self, event: str, message: str, level: str, **extra):
        """
        Append a structured entry to the shared module-level _log.
        Entries are: {event, message, level, timestamp, ...extra}
        Polled by the SSE endpoint at /api/progress.
        """
        entry = {
            'event': event,
            'message': message,
            'level': level,
            'timestamp': datetime.now().isoformat(),
            **extra,
        }
        with _log_lock:
            _log.append(entry)