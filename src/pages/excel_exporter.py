import pandas as pd
from io import BytesIO

def export_to_styled_excel(df_dict: dict[str, pd.DataFrame], group_by_col: str | None = None) -> bytes:
    """
    Standardized Excel exporter with DEEN-OPS styling.
    df_dict: Mapping of {SheetName: DataFrame}
    """
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        header_format = workbook.add_format({
            'bold': True, 
            'bg_color': '#4F81BD', 
            'font_color': 'white', 
            'border': 1
        })

        format_cache = {}
        
        def get_fmt(bg_color, is_top, is_bottom, is_left, is_right, is_currency=False, is_percent=False, is_low_stock=False):
            key = (bg_color, is_top, is_bottom, is_left, is_right, is_currency, is_percent, is_low_stock)
            if key in format_cache:
                return format_cache[key]
            
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
                
            fmt = workbook.add_format(props)
            format_cache[key] = fmt
            return fmt

        for sheet_name, df in df_dict.items():
            if df.empty:
                continue
                
            # Detect column types for formatting
            currency_cols = [c for c in df.columns if any(kw in str(c).lower() for kw in ["amount", "revenue", "cost", "price", "value"])]
            percent_cols = [c for c in df.columns if any(kw in str(c).lower() for kw in ["rate", "percentage", "yield"])]
            stock_cols = [c for c in df.columns if str(c) in ["Ecom-Mirpur", "Wari", "Cumilla", "Sylhet", "Mirpur", "Ecom"]]
                
            df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
            worksheet = writer.sheets[sheet_name[:31]]
            
            # Apply header formatting and auto-fit
            for idx, col in enumerate(df.columns):
                worksheet.write(0, idx, str(col), header_format)
                max_len = max(df[col].astype(str).map(len).max(), len(str(col))) + 2
                worksheet.set_column(idx, idx, min(max_len, 60))
                
            # Add interactive dropdowns for Dispatch Suggestion column
            if "Dispatch Suggestion" in df.columns:
                ds_idx = df.columns.get_loc("Dispatch Suggestion")
                worksheet.data_validation(
                    1, ds_idx, len(df), ds_idx,
                    {
                        'validate': 'list',
                        'source': ['Ecom-Mirpur', 'Wari', 'Cumilla', 'Sylhet', 'Multiple / Split', 'OOS / Unfulfillable']
                    }
                )
            
            # Auto-detect group column if not provided
            group_col_sheet = group_by_col
            if not group_col_sheet:
                for c in ["Order Number", "Order ID", "Order #", "Phone (Billing)", "Phone", "Cons. ID"]:
                    if c in df.columns:
                        group_col_sheet = c
                        break

            if group_col_sheet and group_col_sheet in df.columns:
                col_idx = df.columns.get_loc(group_col_sheet)
                group_boundaries = []
                current_val = None
                start_row = 0
                for i in range(len(df)):
                    val = df.iloc[i, col_idx]
                    if i == 0:
                        current_val = val
                        start_row = i
                    elif val != current_val:
                        group_boundaries.append((start_row, i - 1))
                        current_val = val
                        start_row = i
                group_boundaries.append((start_row, len(df) - 1))

                use_alt = False
                for start_idx, end_idx in group_boundaries:
                    use_alt = not use_alt
                    bg_col = '#E8F2FF' if use_alt else '#FFFFFF'
                    
                    for row_num in range(start_idx, end_idx + 1):
                        is_top = (row_num == start_idx)
                        is_bottom = (row_num == end_idx)
                        
                        for c_idx, col_name in enumerate(df.columns):
                            is_left = (c_idx == 0)
                            is_right = (c_idx == len(df.columns) - 1)
                            is_curr = col_name in currency_cols
                            is_perc = col_name in percent_cols
                            
                            val = df.iloc[row_num, c_idx]
                            is_low_stock = False
                            if col_name in stock_cols and isinstance(val, (int, float)) and pd.notna(val):
                                if 0 < val <= 2:
                                    is_low_stock = True
                                    
                            fmt = get_fmt(bg_col, is_top, is_bottom, is_left, is_right, is_curr, is_perc, is_low_stock)
                            if pd.isna(val):
                                val = ""
                            worksheet.write(row_num + 1, c_idx, val, fmt)
            else:
                for row_num in range(len(df)):
                    for c_idx, col_name in enumerate(df.columns):
                        is_curr = col_name in currency_cols
                        is_perc = col_name in percent_cols
                        
                        val = df.iloc[row_num, c_idx]
                        is_low_stock = False
                        if col_name in stock_cols and isinstance(val, (int, float)) and pd.notna(val):
                            if 0 < val <= 2:
                                is_low_stock = True
                                
                        fmt = get_fmt('#FFFFFF', False, False, False, False, is_curr, is_perc, is_low_stock)
                        if pd.isna(val):
                            val = ""
                        worksheet.write(row_num + 1, c_idx, val, fmt)
                
    return output.getvalue()