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

        # Format for alternating rows
        alt_format = workbook.add_format({'bg_color': '#E8F2FF', 'border': 1})
        base_format = workbook.add_format({'bg_color': '#FFFFFF', 'border': 1})
        
        # Specialized Number Formats
        currency_format = workbook.add_format({'num_format': '৳ #,##0', 'border': 1})
        percent_format = workbook.add_format({'num_format': '0.0%', 'border': 1})

        for sheet_name, df in df_dict.items():
            if df.empty:
                continue
                
            # Detect column types for formatting
            currency_cols = [c for c in df.columns if any(kw in str(c).lower() for kw in ["amount", "revenue", "cost", "price", "value"])]
            percent_cols = [c for c in df.columns if any(kw in str(c).lower() for kw in ["rate", "percentage", "yield"])]
                
            df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
            worksheet = writer.sheets[sheet_name[:31]]
            
            # Apply header formatting and auto-fit
            for idx, col in enumerate(df.columns):
                worksheet.write(0, idx, str(col), header_format)
                max_len = max(df[col].astype(str).map(len).max(), len(str(col))) + 2
                worksheet.set_column(idx, idx, min(max_len, 60))
            
            # Apply alternating row colors if a grouping column is provided
            if group_by_col and group_by_col in df.columns:
                col_idx = df.columns.get_loc(group_by_col)
                current_group_val = None
                use_alt = False
                
                # Row 0 is header, data starts at Row 1
                for row_num in range(len(df)):
                    val = df.iloc[row_num, col_idx]
                    
                    # Toggle color when group value changes
                    if val != current_group_val:
                        current_group_val = val
                        use_alt = not use_alt
                    
                    fmt = alt_format if use_alt else base_format
                    
                    # Apply specialized formatting to specific columns while keeping row color
                    for c_idx, col_name in enumerate(df.columns):
                        cell_val = df.iloc[row_num, c_idx]
                        target_fmt = fmt
                        if col_name in currency_cols: target_fmt = currency_format
                        elif col_name in percent_cols: target_fmt = percent_format
                        
                        if use_alt and target_fmt == fmt: target_fmt = alt_format
                        worksheet.write(row_num + 1, c_idx, cell_val, target_fmt)
            else:
                # Standard border for all rows if no grouping
                for row_num in range(len(df)):
                    worksheet.set_row(row_num + 1, None, base_format)
                
    return output.getvalue()