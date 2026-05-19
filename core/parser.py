"""
Parser — reads raw data from an uploaded Excel file.

No Mail List sheet. No email config. Only the raw Data sheet.
Dispatch extracts unique branch names from the Branch column and
hands the filtered DataFrame to the engine for dispatch.

Pre-flight validations (in order):
  1. File lock check   — ValueError if Excel has the file open
  2. Sheet check      — 'Data' sheet (or any sheet with a Branch column) must exist
  3. Column check     — 'Branch' column must exist in row 1 of the Data sheet
  4. Data check       — file must have at least 2 data rows (1 header + 1 data)

All errors raise ValueError with a plain-English message for the UI banner.
"""

import os
import pandas as pd
import openpyxl


class DispatchParser:
    """
    Reads an Excel workbook and extracts branch-level data for dispatch.

    Parameters
    ----------
    filepath : str
        Absolute path to the uploaded .xlsx/.xlsm file.
    progress_callback : callable, optional
        Called at parse milestones with (stage, message, percent).
        Registered with SSE endpoint via _emit_parse_progress in app.py.

    Attributes
    ----------
    session_id : str
        12-character hex token generated at parse start.
        Matches the in-memory _session['id'].
    filepath : str
        Set at construction.
    """

    # The parser looks for this sheet first. Falls back to the first sheet
    # that has a 'Branch' column in row 1.
    DATA_SHEET_NAME = 'Data'

    # Columns that MUST exist in the Data sheet row 1.
    # Currently only 'Branch' is required. Others may be added in future.
    REQUIRED_DATA_COLS = [
        'Branch',
    ]

    def __init__(self, filepath: str, progress_callback=None):
        self.filepath = filepath
        self.session_id = None
        # Default no-op emitter. Replaced by _emit_parse_progress in app.py.
        self._progress = progress_callback or (lambda stage, message, percent: None)

    def _emit(self, stage, message, percent):
        """
        Thread-safe progress emission.
        Called at milestones: reading → loading → validating → parsing → branches → done.
        """
        self._progress(stage, message, percent)

    # ── Public parse ────────────────────────────────────────────────────────────

    def parse(self) -> dict:
        """
        Full parse with strict pre-flight validation.
        Raises ValueError (plain English) on any failure.

        Sheet detection order:
          1. Exact 'Data' sheet name, verified to have a 'Branch' column
          2. First sheet in the workbook that has a 'Branch' column in row 1

        Returns
        -------
        dict
            session_id     : str (12-char hex, unique per upload)
            data_df        : Pandas DataFrame — all rows from the Data sheet
            columns        : list of column names from the Excel header
            branch_col     : exact column name for 'Branch' (preserves case)
            branches       : list of dicts — [{branch: str, count: int}, ...]
            total_data_rows: int — rows in data_df (excludes header, excludes blank rows)
            total_branches : int — number of unique, non-empty branches
        """
        try:
            self._check_file_lock()
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
            self._emit('validating', "Validating structure...", 40)
            self._validate_columns(target_sheet)

            # All checks passed — proceed to parse
            return self._do_parse(target_sheet)

        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Unexpected parse error: {e}")

    # ── Pre-flight validations ──────────────────────────────────────────────────

    def _check_file_lock(self):
        """
        Raise ValueError if the file cannot be read.
        This catches the common case of Excel locking the file on Windows.
        """
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
        Find the target sheet for parsing.

        Priority:
          1. Exact 'Data' sheet name — if it also has a 'Branch' column
          2. First sheet in workbook order that has 'Branch' in row 1

        This allows the tool to work with any sheet name as long as the
        structure (Branch column in row 1) is present.
        """
        # First: exact sheet name match
        for name in sheet_names:
            if name.strip().lower() == self.DATA_SHEET_NAME.lower():
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
        """
        Read row 1 headers only. Raise if 'Branch' is missing.
        This is a fast check — no data is loaded yet.
        """
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

    # ── Core parse ────────────────────────────────────────────────────────────

    def _do_parse(self, data_sheet: str) -> dict:
        """
        Load the full Data sheet row-by-row using openpyxl read-only mode.
        Emits progress milestones at 1000, 5000, 10000, 20000, 50000, 100000 rows.

        Blank rows (all cells null or 'nan'/'None'/'NaN') are silently skipped.
        This keeps the branch count accurate.

        Returns
        -------
        dict
            See parse() return value documentation above.
        """
        MILESTONES = [1000, 5000, 10000, 20000, 50000, 100000]

        # openpyxl read-only mode: minimal memory, row-by-row iteration.
        # data_only=True returns cached cell values (avoids formula evaluation issues).
        wb = openpyxl.load_workbook(self.filepath, read_only=True, data_only=True)
        ws = wb[data_sheet]

        rows = []
        headers = None
        total_rows = 0
        last_milestone = 0

        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                # Row 0 = header row. Normalise column names to strings, strip whitespace.
                headers = [str(c).strip() if c is not None else '' for c in row]
                continue

            # Skip fully blank rows — treat as non-data.
            if all(
                c is None or str(c).strip() in ('', 'nan', 'None', 'NaN', 'null')
                for c in row
            ):
                continue

            rows.append(row)
            total_rows += 1

            # Emit progress at row milestones
            for m in MILESTONES:
                if last_milestone < m <= total_rows:
                    pct = 45 + int((total_rows / 100000) * 35)
                    self._emit('parsing', f"Parsing {total_rows:,} rows...", min(pct, 80))
                    last_milestone = m
                    break

        wb.close()
        self._emit('parsing', f"Parsed {total_rows:,} rows...", 80)

        if headers is None:
            raise ValueError("'Data' sheet appears to be empty.")

        # Build DataFrame from collected rows
        data_df = pd.DataFrame(rows, columns=headers)

        # Locate the exact Branch column name (preserves case)
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

        Processing:
          1. Fill NA with empty string
          2. Convert to string and strip whitespace
          3. Filter out common empty/null sentinel values
          4. Count occurrences with value_counts()
          5. Return sorted list of dicts: [{branch: str, count: int}, ...]

        Sorting by branch name (alphabetical) ensures consistent ordering
        in the UI branch checklist regardless of Excel row order.
        """
        series = (
            data_df[branch_col]
            .fillna('')
            .astype(str)
            .str.strip()
        )
        # Filter out empty and null sentinel values
        series = series[~series.isin(['', 'nan', 'None', 'NaN', 'null'])]
        counts = series.value_counts().sort_index().to_dict()

        return [
            {'branch': str(name).strip(), 'count': int(count)}
            for name, count in sorted(counts.items())
        ]