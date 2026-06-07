import pandas as pd
from io import BytesIO

class ExcelFormatter:
    """Encapsulates Excel formatting logic and caching."""
    def __init__(self, workbook):
        self.workbook = workbook
        self.format_cache = {}
        self.header_format = workbook.add_format({
            'bold': True, 
            'bg_color': '#4F81BD', 
            'font_color': 'white', 
            'border': 1
        })

    def get_fmt(self, bg_color, is_top, is_bottom, is_left, is_right, is_currency=False, is_percent=False, is_low_stock=False):
        key = (bg_color, is_top, is_bottom, is_left, is_right, is_currency, is_percent, is_low_stock)
        if key in self.format_cache:
            return self.format_cache[key]
        
        props = {
            'bg_color': '#FFEBE6' if is_low_stock else bg_color,
            'top': 2 if is_top else 1,
            'bottom': 2 if is_bottom else 1,
            'left': 2 if is_left else 1,
            'right': 2 if is_right else 1
        }
        if is_low_stock:
            props['font_color'] = '#D92D20'
            props['bold'] = True
        
        if is_currency:
            props['num_format'] = '#,##0'
        elif is_percent:
            props['num_format'] = '0.0%'
            
        fmt = self.workbook.add_format(props)
        self.format_cache[key] = fmt
        return fmt

def _detect_column_types(df: pd.DataFrame):
    """Identifies columns that need specific formatting based on heuristics."""
    currency_cols = [c for c in df.columns if any(kw in str(c).lower() for kw in ["amount", "revenue", "cost", "price", "value"])]
    percent_cols = [c for c in df.columns if any(kw in str(c).lower() for kw in ["rate", "percentage", "yield"])]
    stock_cols = [c for c in df.columns if str(c) in ["Ecom-Mirpur", "Wari", "Cumilla", "Sylhet", "Mirpur", "Ecom"]]
    return currency_cols, percent_cols, stock_cols

def _write_headers_and_autofit(worksheet, df: pd.DataFrame, header_format):
    """Writes headers and auto-fits column widths to the data contents."""
    for idx, col in enumerate(df.columns):
        worksheet.write(0, idx, str(col), header_format)
        max_len = max(df[col].astype(str).map(len).max(), len(str(col))) + 2
        worksheet.set_column(idx, idx, min(max_len, 60))

def _add_dispatch_validation(worksheet, df: pd.DataFrame):
    """Adds dropdown validations to the worksheet if Dispatch columns are present."""
    if "Dispatch Suggestion" in df.columns:
        ds_idx = df.columns.get_loc("Dispatch Suggestion")
        worksheet.data_validation(
            1, ds_idx, len(df), ds_idx,
            {
                'validate': 'list',
                'source': ['Ecom-Mirpur', 'Wari', 'Cumilla', 'Sylhet', 'Multiple / Split', 'OOS / Unfulfillable']
            }
        )

def _get_group_boundaries(df: pd.DataFrame, group_col: str) -> list[tuple[int, int]]:
    """Calculates row boundaries (start, end) for visually grouping column values."""
    col_idx = df.columns.get_loc(group_col)
    boundaries = []
    start_row = 0
    current_val = df.iloc[0, col_idx] if not df.empty else None
    
    for i in range(len(df)):
        val = df.iloc[i, col_idx]
        if val != current_val:
            boundaries.append((start_row, i - 1))
            current_val = val
            start_row = i
            
    if not df.empty:
        boundaries.append((start_row, len(df) - 1))
    return boundaries

def _write_row(worksheet, df: pd.DataFrame, row_num: int, curr_cols, perc_cols, stock_cols, bg_col, is_top, is_bottom, formatter: ExcelFormatter):
    """Writes a single row with the appropriate styling."""
    for c_idx, col_name in enumerate(df.columns):
        is_left = (c_idx == 0)
        is_right = (c_idx == len(df.columns) - 1)
        is_curr = col_name in curr_cols
        is_perc = col_name in perc_cols
        
        val = df.iloc[row_num, c_idx]
        is_low_stock = False
        if col_name in stock_cols and isinstance(val, (int, float)) and pd.notna(val):
            if 0 < val <= 2:
                is_low_stock = True
                
        fmt = formatter.get_fmt(bg_col, is_top, is_bottom, is_left, is_right, is_curr, is_perc, is_low_stock)
        
        # Safely handle NAs
        if pd.isna(val):
            val = ""
            
        worksheet.write(row_num + 1, c_idx, val, fmt)

def export_to_styled_excel(df_dict: dict[str, pd.DataFrame], group_by_col: str | None = None) -> bytes:
    """
    Standardized Excel exporter with DEEN-OPS styling.
    df_dict: Mapping of {SheetName: DataFrame}
    """
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        formatter = ExcelFormatter(writer.book)

        for sheet_name, df in df_dict.items():
            if df.empty:
                continue
                
            curr_cols, perc_cols, stock_cols = _detect_column_types(df)
                
            sheet_title = sheet_name[:31]
            df.to_excel(writer, index=False, sheet_name=sheet_title)
            worksheet = writer.sheets[sheet_title]
            
            _write_headers_and_autofit(worksheet, df, formatter.header_format)
            _add_dispatch_validation(worksheet, df)
            
            # Auto-detect group column if not provided
            group_col_sheet = group_by_col
            if not group_col_sheet:
                for c in ["Order Number", "Order ID", "Order #", "Phone (Billing)", "Phone", "Cons. ID"]:
                    if c in df.columns:
                        group_col_sheet = c
                        break

            if group_col_sheet and group_col_sheet in df.columns:
                group_boundaries = _get_group_boundaries(df, group_col_sheet)
                use_alt = False
                
                for start_idx, end_idx in group_boundaries:
                    use_alt = not use_alt
                    bg_col = '#E8F2FF' if use_alt else '#FFFFFF'
                    
                    for row_num in range(start_idx, end_idx + 1):
                        is_top = (row_num == start_idx)
                        is_bottom = (row_num == end_idx)
                        _write_row(worksheet, df, row_num, curr_cols, perc_cols, stock_cols, bg_col, is_top, is_bottom, formatter)
            else:
                for row_num in range(len(df)):
                    _write_row(worksheet, df, row_num, curr_cols, perc_cols, stock_cols, '#FFFFFF', False, False, formatter)
                
    return output.getvalue()