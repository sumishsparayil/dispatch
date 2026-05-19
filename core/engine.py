"""Engine — filters raw data by branch and dispatches emails.

Architecture (v3):
  - No more Mail List sheet in the Excel file
  - Email config lives in db/panther_data.json (branch_mappings + email_template)
  - Engine receives the full data_df and list of detected branches from the parser
  - For each branch: look up recipient in branch_mappings from settings,
    render template, export attachment, send.

Supports:
  - Excluded branches list (user unchecked in the UI review step)
  - Dynamic {variable} injection into email subject and body
  - Pre-calculated branch metrics (row_count, outstanding, demand_loss, NPA, etc.)
  - Per-branch email templates from the JSON config
  - Auto-cleanup of exported Excel files
  - Thread-safe SSE logging
  - RAM cleanup (gc.collect) after run completes
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


# ── Shared run log (thread-safe) ─────────────────────────────────
_log = []
_log_lock = threading.Lock()
_stop_flag = False


class PantherEngine:

    @classmethod
    def get_log(cls) -> list:
        with _log_lock:
            return list(_log)

    @classmethod
    def clear_log(cls):
        global _log
        with _log_lock:
            _log = []

    @classmethod
    def stop(cls):
        global _stop_flag
        _stop_flag = True

    def __init__(
        self,
        branches: list,        # [{branch: str, count: int}, ...] from parser
        data_df,               # full Pandas DataFrame
        branch_col: str,       # exact column name for 'Branch' in data_df
        settings: dict,       # full app settings — includes branch_mappings, email_subject, email_body
        upload_folder: str,
        filename: str = '',
        test_only: bool = False,
        excluded_branches: list = None,
    ):
        """
        branches:       list of {branch, count} dicts detected in the Data sheet
        data_df:        the full parsed Pandas DataFrame
        branch_col:     exact column name for 'Branch' (e.g. 'Branch' or 'BRANCH')
        settings:       must contain:
                         - branch_mappings: {branch_name: {email, cc}}
                         - email_subject
                         - email_body
                         - smtp_host, smtp_port, smtp_user, smtp_pass, from_name, use_tls
        """
        self.branches = branches
        self.data_df = data_df
        self.branch_col = branch_col
        self.settings = settings
        self.upload_folder = upload_folder
        self.filename = filename
        self.test_only = test_only
        self.excluded_branches = set(excluded_branches or [])
        self.run_id = uuid.uuid4().hex[:12]
        # Build a lowercase column → actual name map for case-insensitive tag injection
        self._col_map = {str(c).lower().strip(): str(c) for c in data_df.columns}

    def start(self):
        global _stop_flag
        _stop_flag = False
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

    def _run(self):
        global _stop_flag

        branch_mappings = self.settings.get('branch_mappings', {})
        email_subject_template = self.settings.get('email_subject', '')
        email_body_template = self.settings.get('email_body', '')
        from_name = self.settings.get('from_name', 'KLM Axiva MIS')
        use_tls = self.settings.get('use_tls', True)

        # Build target list — only branches with a mapped email address
        target_list = [
            b for b in self.branches
            if b['branch'] not in self.excluded_branches
            and b['branch'] in branch_mappings
            and branch_mappings[b['branch']].get('email', '').strip()
        ]

        # Warn about branches with no email mapping
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

        # SMTP settings for the mailer
        smtp_settings = {
            'smtp_host':   self.settings.get('smtp_host', ''),
            'smtp_port':   int(self.settings.get('smtp_port') or 587),
            'smtp_user':   self.settings.get('smtp_user', ''),
            'smtp_pass':   self.settings.get('smtp_pass', ''),
            'from_name':   from_name,
            'use_tls':     use_tls,
        }
        mailer = PantherMailer(smtp_settings)
        exporter = PantherExporter()

        sent = 0
        failed = 0
        subject_default = email_subject_template

        for i, branch_info in enumerate(target_list):
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
                # ── Filter DataFrame by branch ────────────────────
                filtered = self.data_df[self.data_df[self.branch_col] == branch]

                # ── Calculate branch metrics ──────────────────────
                metrics = self._calc_branch_metrics(filtered)
                metrics['row_count'] = len(filtered)

                # ── Render email template ───────────────────────
                subject = self._render_template(email_subject_template, branch, metrics, filtered)
                body = self._render_template(email_body_template, branch, metrics, filtered)

                # ── Export attachment ────────────────────────────
                attachment_path = exporter.export(
                    data=filtered,
                    subject=subject,
                    upload_folder=self.upload_folder,
                )

                # ── Send email ──────────────────────────────────
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

                # Auto-delete attachment
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
                    self.run_id, recipient, cc, subject_default,
                    branch, 'failed', str(e),
                )

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

        gc.collect()

    # ── Template rendering ───────────────────────────────────────

    # Matches {tag} where tag may contain letters, numbers, spaces, underscores, hyphens
    VARIABLE_PATTERN = re.compile(r'\{([^}]+)\}')

    def _render_template(self, template: str, branch: str, metrics: dict, filtered_df) -> str:
        """
        Replace {variable} placeholders in template strings.

        Built-in variables:
          {branch} / {branch_name}     — branch display name
          {row_count} / {total_rows}   — number of rows in branch subset
          {total_outstanding}          — sum of outstanding columns
          {total_demand_loss}          — sum of demand loss columns
          {total_aging}                — sum of aging columns
          {npa_count}                  — count of NPA rows
          {fresh_od_count}             — count of fresh OD rows
          {tenure_completed_count}     — count of tenure-completed rows

        Any other {COLUMN NAME} that matches a column in the Data sheet
        is resolved by scanning the branch's filtered rows:
          — numeric columns → formatted sum
          — non-numeric     → first non-empty value
        Column lookup is case-insensitive.
        """
        if not template:
            return template

        def replacer(match):
            # Normalize key — strip spaces and lower
            raw_tag = match.group(1)
            key = raw_tag.lower().strip()

            # Known built-ins
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

            # Dynamic {COLUMN NAME} — look up by case-insensitive exact match
            # then partial match (first exact wins, first partial as fallback)
            col_candidates = []
            for col in filtered_df.columns:
                cl = str(col).lower().strip()
                if cl == key and col_candidates == []:
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
                # Non-numeric — first non-empty value
                for val in filtered_df[col].fillna('').astype(str):
                    if val and val.strip() not in ('', 'nan', 'None', 'NaN'):
                        return val.strip()

            # Unknown — leave literal
            return match.group(0)

        return self.VARIABLE_PATTERN.sub(replacer, template)

    @staticmethod
    def _calc_branch_metrics(filtered_df) -> dict:
        """
        Calculate summary metrics from a filtered branch DataFrame.
        Column lookup is case-insensitive and uses partial matching
        so column name variations are tolerated.
        """
        metrics = {}
        if filtered_df.empty:
            return metrics

        def find_col(partials):
            for col in filtered_df.columns:
                cl = col.lower().strip()
                for p in partials:
                    if p in cl:
                        return col
            return None

        def sum_col(col_name, partials):
            col = col_name or find_col(partials)
            if col is None:
                return 0
            try:
                return float(pd.to_numeric(filtered_df[col], errors='coerce').fillna(0).sum())
            except Exception:
                return 0

        def count_col(partials):
            col = find_col(partials)
            if col is None:
                return 0
            vals = filtered_df[col].fillna('').astype(str).str.strip()
            return int(vals[~vals.isin(['', '0', '0.0', 'nan', 'None'])].count())

        metrics['total_outstanding']       = sum_col(None, ['outstanding', 'os amount', 'balance', 'os'])
        metrics['total_demand_loss']        = sum_col(None, ['demand loss', 'demandloss'])
        metrics['total_aging']              = sum_col(None, ['aging', 'age'])
        metrics['npa_count']                = count_col(['npa'])
        metrics['fresh_od_count']           = count_col(['fresh od', 'freshod', 'new od'])
        metrics['tenure_completed_count']   = count_col(['tenure completed', 'tenurecompleted'])

        return metrics

    # ── Logging ──────────────────────────────────────────────────

    def _log(self, event: str, message: str, level: str, **extra):
        entry = {
            'event': event,
            'message': message,
            'level': level,
            'timestamp': datetime.now().isoformat(),
            **extra,
        }
        with _log_lock:
            _log.append(entry)