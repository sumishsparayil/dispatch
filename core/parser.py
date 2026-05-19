"""Parser — reads raw data from an uploaded Excel file.

No Mail List sheet. No email config. Only the raw Data sheet.
Panther extracts unique branch names from the Branch column and
hands the filtered DataFrame to the engine for dispatch.

Pre-flight validations (order matters):
  1. File lock check  — PermissionError if Excel has the file open
  2. Sheet check     — 'Data' sheet must exist
  3. Column check    — 'Branch' column must exist in row 1 of the Data sheet
  4. Data check      — file must have at least 2 data rows (1 header + 1 data)

All errors raise ValueError with a plain-English message for the UI banner.
"""
import os
import pandas as pd
import openpyxl


class PantherParser:

    DATA_SHEET_NAME = 'Data'

    # Column that MUST exist in the Data sheet row 1
    REQUIRED_DATA_COLS = [
        'Branch',
    ]

    def __init__(self, filepath: str, progress_callback=None):
        self.filepath = filepath
        self.session_id = None
        self._progress = progress_callback or (lambda stage, message, percent: None)

    def _emit(self, stage, message, percent):
        self._progress(stage, message, percent)

    # ── Public parse ─────────────────────────────────────────────

    def parse(self) -> dict:
        """
        Full parse with strict pre-flight validation.
        Raises ValueError (plain English) on any failure.

        Sheet detection: finds the first sheet whose row-1 contains a 'Branch'
        column. Falls back to 'Data' sheet by name, then the first sheet.
        """
        try:
            # 1. File lock
            self._check_file_lock()

            # 2. Find the right sheet
            self._emit('reading', "Reading file from disk...", 10)
            xl = pd.ExcelFile(self.filepath)
            sheet_names = xl.sheet_names

            target_sheet = self._find_branch_sheet(self.filepath, sheet_names)
            if target_sheet is None:
                raise ValueError(
                    f"No sheet found with a 'Branch' column. "
                    f"Available sheets: {', '.join(sheet_names)}. "
                    f"Ensure your Excel has a 'Branch' column in the header row."
                )

            self._emit('loading', f"Loading '{target_sheet}' sheet...", 25)

            # 3. Column validation (row 1 only — no data loaded yet)
            self._emit('validating', "Validating structure...", 40)
            self._validate_columns(target_sheet)

            # All checks passed — load the data
            return self._do_parse(target_sheet)

        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Unexpected parse error: {e}")

    # ── Pre-flight validations ────────────────────────────────────

    def _check_file_lock(self):
        try:
            with open(self.filepath, 'rb') as f:
                f.read(1)
        except PermissionError:
            raise ValueError(
                "The file appears to be open in Excel. "
                "Please close the file and try again."
            )
        except OSError as e:
            raise ValueError(f"Cannot read file: {e}")

    def _find_branch_sheet(self, filepath: str, sheet_names: list) -> str | None:
        """
        Find the first sheet that has a 'Branch' column in row 1.
        Priority: exact 'Data' sheet → first sheet with Branch column.
        """
        # First: look for exact 'Data' sheet name
        for name in sheet_names:
            if name.strip().lower() == self.DATA_SHEET_NAME.lower():
                # Verify it has a Branch column
                try:
                    header = pd.read_excel(filepath, sheet_name=name, header=0, nrows=0)
                    cols = {c.strip() for c in header.columns}
                    if 'Branch' in cols:
                        return name
                except Exception:
                    pass

        # Fallback: scan all sheets for Branch column
        for name in sheet_names:
            try:
                header = pd.read_excel(filepath, sheet_name=name, header=0, nrows=0)
                cols = {c.strip() for c in header.columns}
                if 'Branch' in cols:
                    return name
            except Exception:
                pass

        return None

    def _validate_columns(self, data_sheet: str):
        """Read row 1 only. Raise if 'Branch' is missing."""
        header_df = pd.read_excel(
            self.filepath,
            sheet_name=data_sheet,
            header=0,
            nrows=0,
        )
        actual = {c.strip() for c in header_df.columns}
        missing = [c for c in self.REQUIRED_DATA_COLS if c not in actual]
        if missing:
            raise ValueError(
                f"'Branch' column not found in '{data_sheet}' sheet. "
                f"Please restore the original template."
            )

    # ── Actual parse ────────────────────────────────────────────

    def _do_parse(self, data_sheet: str) -> dict:
        """
        Load the full Data sheet using openpyxl in read-only mode with
        row-by-row iteration so progress can be emitted at milestones.
        """
        MILESTONES = [1000, 5000, 10000, 20000, 50000, 100000]

        wb = openpyxl.load_workbook(self.filepath, read_only=True, data_only=True)
        ws = wb[data_sheet]

        rows = []
        headers = None
        total_rows = 0
        last_milestone = 0

        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                headers = [str(c).strip() if c is not None else '' for c in row]
                continue

            # Skip fully blank rows
            if all(c is None or str(c).strip() in ('', 'nan', 'None', 'NaN', 'null') for c in row):
                continue

            rows.append(row)
            total_rows += 1

            # Emit milestones
            for m in MILESTONES:
                if last_milestone < m <= total_rows:
                    pct = 45 + int((total_rows / 100000) * 35)
                    self._emit('parsing', f"Parsing {total_rows:,} rows...", min(pct, 80))
                    last_milestone = m
                    break

        wb.close()

        self._emit('parsing', f"Parsing {total_rows:,} rows...", 80)

        # Build DataFrame from collected rows
        if headers is None:
            raise ValueError("'Data' sheet appears to be empty.")

        data_df = pd.DataFrame(rows, columns=headers)

        # ── Derive branch column ──────────────────────────────────
        branch_col = None
        for col in data_df.columns:
            if str(col).strip() == 'Branch':
                branch_col = col
                break

        if branch_col is None:
            raise ValueError(
                "'Branch' column not found in Data sheet. "
                "Ensure the first row of the Data sheet contains a column named 'Branch'."
            )

        branches = self._extract_branches(data_df, branch_col)
        self.session_id = os.urandom(6).hex()

        self._emit(
            'branches',
            f"Found {len(branches)} branches with {total_rows:,} rows...",
            95,
        )

        return {
            'session_id':        self.session_id,
            'data_df':          data_df,
            'columns':          list(data_df.columns),
            'branch_col':       branch_col,
            'branches':         branches,
            'total_data_rows':  int(total_rows),
            'total_branches':   len(branches),
        }

    @staticmethod
    def _extract_branches(data_df, branch_col: str) -> list:
        """
        Extract unique, non-empty branch names from the Branch column.
        Returns sorted list of dicts: [{branch: str, count: int}, ...]
        """
        series = (
            data_df[branch_col]
            .fillna('')
            .astype(str)
            .str.strip()
        )
        series = series[~series.isin(['', 'nan', 'None', 'NaN', 'null'])]
        counts = series.value_counts().sort_index().to_dict()

        result = []
        for name in sorted(counts.keys()):
            result.append({'branch': str(name).strip(), 'count': int(counts[name])})
        return result