"""Exporter — filters DataFrame and writes per-branch Excel attachments."""
import os
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side


class PantherExporter:
    """
    Takes a filtered DataFrame, writes it to a .xlsx file,
    returns the file path. Files are named after the email subject.
    """

    def export(self, data, subject: str, upload_folder: str) -> str:
        """
        Write data to an Excel file named from the subject.
        Returns the absolute file path.
        """
        # Sanitize filename
        safe_name = self._sanitize_filename(subject)
        filename = f"{safe_name}.xlsx"
        filepath = os.path.join(upload_folder, filename)

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Data"

        # ── Write headers ─────────────────────────────────────
        headers = list(data.columns)
        ws.append(headers)

        # Style headers: bold, light blue fill, sharp corners
        header_fill = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")
        header_font = Font(bold=True, color="1F2937", name="Calibri", size=10)
        header_alignment = Alignment(horizontal="center", vertical="center")

        thin = Side(style='thin', color="BFBFBF")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        for col_idx, cell in enumerate(ws[1], start=1):
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = border

        # ── Write data rows ─────────────────────────────────
        for row in data.itertuples(index=False, name=None):
            ws.append(row)

        # ── Auto-fit columns ─────────────────────────────────
        for col in ws.columns:
            max_length = 0
            col_letter = col[0].column_letter
            for cell in col:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            ws.column_dimensions[col_letter].width = min(max_length + 2, 40)

        # ── Freeze header row ───────────────────────────────
        ws.freeze_panes = "A2"

        wb.save(filepath)
        return filepath

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """Remove or replace characters that are invalid in filenames."""
        invalid = '<>:"/\\|?*'
        for char in invalid:
            name = name.replace(char, '_')
        name = name.strip()
        # Truncate to 100 chars
        return name[:100] if name else "attachment"

    @staticmethod
    def cleanup(filepath: str):
        """Delete a temp attachment file if it exists."""
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception:
            pass