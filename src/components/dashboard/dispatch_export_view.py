"""Dispatch and completed orders export component.

Provides product-wise everyday shipped and completed orders export with date picker,
category breakdown, exchange order segregation, XLSX, and CSV downloads.
"""

from datetime import timedelta
import pandas as pd
import streamlit as st

from src.config.constants import bd_now, bd_today
from src.processing.categorization import (
    get_category_for_sales,
    get_sub_category_for_sales,
)
from src.processing.completed_analytics import filter_shipped_order_items
from src.processing.data_processing import (
    get_previous_working_day,
    safe_coerce_datetime_naive,
)
from src.processing.selects_analytics import classify_product_line
from src.services.exports.excel_exporter import export_to_styled_excel
from src.utils.logging import log_system_event


def render_dispatch_export(
    selected_view: str | None = None,
    raw_df: pd.DataFrame | None = None,
) -> None:
    """Render product-wise everyday shipped and completed orders export with date picker, XLSX and CSV."""
    if raw_df is None or raw_df.empty:
        raw_df = st.session_state.get("wc_full_df")
    if raw_df is None or raw_df.empty:
        raw_df = st.session_state.get("wc_curr_df")
    if raw_df is None or raw_df.empty:
        return

    today_bd = bd_today()
    prev_work_bd = get_previous_working_day(today_bd)
    prev_day_name = prev_work_bd.strftime("%A")
    prev_label = (
        f"Previous Working Day ({prev_day_name[:3]})"
        if today_bd.weekday() == 5
        else "Yesterday"
    )

    # Determine default date based on selected_view
    if selected_view in {"Last Day Shipped", "Last Day"}:
        default_preset = prev_label
    else:
        default_preset = "Today"

    st.divider()
    with st.expander(
        "📦 Daily Shipped & Completed Orders (Product-Wise Export)",
        expanded=(
            selected_view in {"Today Shipped", "Today", "Last Day Shipped", "Last Day"}
        ),
    ):
        st.caption(
            "Export product line items for orders shipped or completed on any selected date. "
            "Includes SKU, Quantity, Item Price, and Customer details in styled Excel (.xlsx) and CSV."
        )

        col_preset, col_date, col_source = st.columns([1.5, 2, 1.5])
        with col_preset:
            date_preset = st.radio(
                "Date Selection",
                ["Today", prev_label, "Custom Date"],
                index=0 if default_preset == "Today" else 1,
                horizontal=True,
                key="shipped_export_date_preset",
            )

        with col_date:
            if date_preset == "Today":
                if today_bd.weekday() == 5:
                    start_date = today_bd - timedelta(days=1)
                    end_date = today_bd
                    st.caption(
                        f"🗓️ Active Days: **{start_date.strftime('%Y-%m-%d (%a)')}** to **{end_date.strftime('%Y-%m-%d (%a)')}** (Includes Friday off-day)"
                    )
                else:
                    start_date = today_bd
                    end_date = today_bd
                    st.caption(
                        f"🗓️ Active Day: **{today_bd.strftime('%Y-%m-%d (%A)')}**"
                    )
            elif date_preset == prev_label:
                start_date = prev_work_bd
                end_date = prev_work_bd
                st.caption(
                    f"🗓️ Active Day: **{prev_work_bd.strftime('%Y-%m-%d (%A)')}** (Skipping Friday off-day)"
                )
            else:
                custom_range = st.date_input(
                    "Select Date or Range",
                    value=(prev_work_bd, today_bd),
                    max_value=today_bd,
                    key="shipped_export_custom_range",
                )
                if isinstance(custom_range, (list, tuple)):
                    if len(custom_range) > 0:
                        start_date = custom_range[0]
                        end_date = (
                            custom_range[-1]
                            if len(custom_range) > 1
                            else custom_range[0]
                        )
                    else:
                        start_date = today_bd
                        end_date = today_bd
                elif custom_range:
                    start_date = custom_range
                    end_date = custom_range
                else:
                    start_date = today_bd
                    end_date = today_bd

        with col_source:
            source_filter = st.radio(
                "Order Source",
                ["Online", "Both", "Outlet"],
                index=0,
                horizontal=True,
                key="shipped_export_source_filter",
            )

        # Filter items using completed_analytics
        filtered_items = filter_shipped_order_items(
            raw_df,
            start_date=start_date,
            end_date=end_date,
            source_filter=source_filter,
        )

        date_label = (
            start_date.strftime("%Y-%m-%d")
            if start_date == end_date
            else f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
        )

        if filtered_items.empty:
            st.info(
                f"ℹ️ No shipped or completed items found for **{date_label}** ({source_filter} orders)."
            )
            return

        export_df = filtered_items.copy()

        # Identify columns defensively
        status_col = (
            "Order Status"
            if "Order Status" in export_df.columns
            else "Status"
            if "Status" in export_df.columns
            else None
        )
        prod_col = (
            "Item Name"
            if "Item Name" in export_df.columns
            else "Product Name"
            if "Product Name" in export_df.columns
            else None
        )
        sku_col = "SKU" if "SKU" in export_df.columns else None
        qty_col = "Quantity" if "Quantity" in export_df.columns else None
        cost_col = (
            "Item Cost"
            if "Item Cost" in export_df.columns
            else "Price"
            if "Price" in export_df.columns
            else None
        )

        # Ensure numeric Quantity and Cost
        if qty_col:
            export_df[qty_col] = (
                pd.to_numeric(export_df[qty_col], errors="coerce").fillna(1).astype(int)
            )
        else:
            export_df["Quantity"] = 1
            qty_col = "Quantity"

        if cost_col:
            export_df[cost_col] = pd.to_numeric(
                export_df[cost_col], errors="coerce"
            ).fillna(0.0)
        else:
            export_df["Item Cost"] = 0.0
            cost_col = "Item Cost"

        export_df["Line Total"] = (export_df[qty_col] * export_df[cost_col]).round(2)

        # ── Enrich with Category, Sub-Category & Product Line ─────────────
        if prod_col and prod_col in export_df.columns:
            _names = export_df[prod_col].astype(str)
            _cats = _names.map(get_category_for_sales)
            export_df["Category"] = _cats
            export_df["Sub-Category"] = _names.apply(
                lambda n: get_sub_category_for_sales(n, get_category_for_sales(n))
            )
            sku_series = (
                export_df[sku_col].astype(str)
                if sku_col and sku_col in export_df.columns
                else [""] * len(export_df)
            )
            export_df["Product Line"] = [
                classify_product_line(str(n), str(s), str(c))
                for n, s, c in zip(_names, sku_series, _cats)
            ]
        else:
            export_df["Category"] = "Unknown"
            export_df["Sub-Category"] = "Unknown"
            export_df["Product Line"] = "DEEN Regular"

        # ── Sub-Category Summary ─────────────────────────────────────────────
        _subcat_summary = (
            export_df.groupby(["Category", "Sub-Category"], sort=False)
            .agg(
                _units=(qty_col, "sum"),
                _amt=("Line Total", "sum"),
            )
            .reset_index()
            .sort_values("_amt", ascending=False)
            .rename(columns={"_units": "Units Sold", "_amt": "Sales Amount (৳)"})
        )
        _subcat_summary["Sales Amount (৳)"] = _subcat_summary["Sales Amount (৳)"].round(
            2
        )
        _sc_total_units = int(_subcat_summary["Units Sold"].sum())
        _sc_total_amt = float(_subcat_summary["Sales Amount (৳)"].sum())
        _subcat_summary["Share (%)"] = (
            (_subcat_summary["Sales Amount (৳)"] / _sc_total_amt * 100)
            .round(1)
            .astype(str)
            + "%"
            if _sc_total_amt > 0
            else "0%"
        )

        # Format dates
        if "mod_dt_parsed" in export_df.columns:
            export_df["Shipped Date"] = safe_coerce_datetime_naive(
                export_df["mod_dt_parsed"]
            ).dt.strftime("%Y-%m-%d %I:%M %p")
        elif "Order Date Modified" in export_df.columns:
            export_df["Shipped Date"] = safe_coerce_datetime_naive(
                export_df["Order Date Modified"]
            ).dt.strftime("%Y-%m-%d %I:%M %p")
        else:
            export_df["Shipped Date"] = ""

        if "dt_parsed" in export_df.columns:
            export_df["Order Placed"] = safe_coerce_datetime_naive(
                export_df["dt_parsed"]
            ).dt.strftime("%Y-%m-%d %I:%M %p")
        elif "Order Date" in export_df.columns:
            export_df["Order Placed"] = safe_coerce_datetime_naive(
                export_df["Order Date"]
            ).dt.strftime("%Y-%m-%d %I:%M %p")
        else:
            export_df["Order Placed"] = ""

        if "_order_source" in export_df.columns:
            export_df["Order Source"] = export_df["_order_source"]

        # Detect exchange orders for visual distinction
        fee_notes_col = "Fee Notes" if "Fee Notes" in export_df.columns else None
        status_col_check = status_col if status_col else None
        if fee_notes_col and fee_notes_col in export_df.columns:
            export_df["Is Exchange"] = (
                export_df[fee_notes_col]
                .astype(str)
                .str.lower()
                .str.contains("exchange credit", na=False)
            )
        elif status_col_check and status_col_check in export_df.columns:
            export_df["Is Exchange"] = (
                export_df[status_col_check]
                .astype(str)
                .str.lower()
                .str.contains("exchange", na=False)
            )
        else:
            export_df["Is Exchange"] = False

        # Map customer and order fields
        field_mapping = {
            "Order ID": "Order ID",
            prod_col: "Product Name",
            sku_col: "SKU",
            "Product Line": "Product Line",
            qty_col: "Quantity",
            cost_col: "Item Cost",
            "Line Total": "Line Total",
            "Category": "Category",
            "Sub-Category": "Sub-Category",
            status_col: "Status",
            "Order Source": "Source",
            "Shipped Date": "Shipped Date",
            "Order Placed": "Order Placed",
            "Full Name (Billing)": "Customer",
            "Phone (Billing)": "Phone",
            "Shipping City": "City",
            "Shipping Address 1": "Address",
            "Pathao Consignment ID": "Consignment ID",
            "Is Exchange": "Exchange",
        }

        # Build column ordering
        export_cols = [
            field_mapping[k] for k in field_mapping if k and k in export_df.columns
        ]

        # Rename to clean target headers
        clean_df = export_df.rename(
            columns={
                k: v for k, v in field_mapping.items() if k and k in export_df.columns
            }
        )

        # Sort chronologically by Order ID / Shipped Date
        sort_candidates = [
            c
            for c in ["Shipped Date", "Order Placed", "Order ID"]
            if c in clean_df.columns
        ]
        if sort_candidates:
            clean_df = clean_df.sort_values(
                by=sort_candidates, ascending=False, na_position="last"
            ).reset_index(drop=True)

        final_cols = [c for c in export_cols if c in clean_df.columns]
        display_df = clean_df[final_cols].copy()

        # Split into regular and exchange orders — exchanges are replacements,
        # not new sales, so they go in their own tab and are excluded from the
        # main KPIs / download.
        is_exchange_col = "Exchange" if "Exchange" in display_df.columns else None
        if is_exchange_col is not None:
            regular_df = display_df[~display_df[is_exchange_col].astype(bool)].copy()
            exchange_df = display_df[display_df[is_exchange_col].astype(bool)].copy()
        else:
            regular_df = display_df.copy()
            exchange_df = pd.DataFrame(columns=display_df.columns)

        # Summary KPIs — regular (non-exchange) orders only
        total_items = (
            int(regular_df["Quantity"].sum())
            if "Quantity" in regular_df.columns
            else len(regular_df)
        )
        total_orders = (
            int(regular_df["Order ID"].nunique())
            if "Order ID" in regular_df.columns
            else len(regular_df)
        )
        total_rev = (
            float(regular_df["Line Total"].sum())
            if "Line Total" in regular_df.columns
            else 0.0
        )
        unique_skus = (
            int(regular_df["SKU"].nunique()) if "SKU" in regular_df.columns else 0
        )

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("📦 Units Shipped", f"{total_items:,}")
        m2.metric("📋 Orders", f"{total_orders:,}")
        m3.metric("৳ Shipped Revenue", f"৳ {total_rev:,.0f}")
        m4.metric("🏷️ Unique SKUs", f"{unique_skus:,}")

        # ── Tabs: Product Lines | Sub-Category Summary | Exchange Orders ──────────────────────
        tab_items, tab_subcat, tab_exchange = st.tabs(
            ["📋 Product Line Items", "📊 Sub-Category Summary", "🔄 Exchange Orders"]
        )

        with tab_items:
            search_q = st.text_input(
                "🔍 Search by Order ID, Product Name, SKU, Customer, or Phone",
                key="shipped_product_export_search",
            ).strip()

            view_df = regular_df.copy()
            if search_q:
                mask = pd.Series(False, index=view_df.index)
                for c in [
                    "Order ID",
                    "Product Name",
                    "Product Line",
                    "SKU",
                    "Customer",
                    "Phone",
                    "City",
                ]:
                    if c in view_df.columns:
                        mask = mask | view_df[c].astype(str).str.contains(
                            search_q, case=False, na=False
                        )
                view_df = view_df[mask]

            st.dataframe(
                view_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Order ID": st.column_config.NumberColumn("Order ID", format="%d"),
                    "Quantity": st.column_config.NumberColumn("Qty", format="%d"),
                    "Product Line": st.column_config.TextColumn("Product Line"),
                    "Item Cost": st.column_config.NumberColumn(
                        "Price (৳)", format="%.2f"
                    ),
                    "Line Total": st.column_config.NumberColumn(
                        "Total (৳)", format="%.2f"
                    ),
                },
            )

        with tab_subcat:
            # ── Elegant styled HTML table (tr/td only — Streamlit strips thead/tfoot) ──
            # Header row
            _hdr = (
                '<tr style="background:linear-gradient(135deg,#1e3a8a 0%,#3730a3 100%);">'
                '<td style="padding:11px 14px;color:#fff;font-size:12px;font-weight:700;'
                'letter-spacing:.05em;text-transform:uppercase;">Category</td>'
                '<td style="padding:11px 14px;color:#c7d2fe;font-size:12px;font-weight:700;'
                'letter-spacing:.05em;text-transform:uppercase;">Sub-Category</td>'
                '<td style="padding:11px 14px;color:#c7d2fe;font-size:12px;font-weight:700;'
                'letter-spacing:.05em;text-transform:uppercase;text-align:right;">Units Sold</td>'
                '<td style="padding:11px 14px;color:#c7d2fe;font-size:12px;font-weight:700;'
                'letter-spacing:.05em;text-transform:uppercase;text-align:right;">Sales Amount</td>'
                '<td style="padding:11px 14px;color:#c7d2fe;font-size:12px;font-weight:700;'
                'letter-spacing:.05em;text-transform:uppercase;">Share</td>'
                "</tr>"
            )
            # Data rows
            _rows_html = ""
            for _i, _row in _subcat_summary.iterrows():
                _bg = "#f9fafb" if _i % 2 == 0 else "#ffffff"
                _units = int(_row["Units Sold"])
                _amt = float(_row["Sales Amount (৳)"])
                _share_str = str(_row["Share (%)"])
                try:
                    _share_val = float(_share_str.replace("%", ""))
                except ValueError:
                    _share_val = 0.0
                _bar_w = max(2, min(100, round(_share_val)))
                _rows_html += (
                    f'<tr style="background:{_bg};">'
                    f'<td style="padding:9px 14px;color:#374151;font-size:13px;border-bottom:1px solid #f0f0f0;">{_row["Category"]}</td>'
                    f'<td style="padding:9px 14px;color:#6b7280;font-size:13px;border-bottom:1px solid #f0f0f0;">{_row["Sub-Category"]}</td>'
                    f'<td style="padding:9px 14px;text-align:right;font-weight:600;color:#1d4ed8;font-size:13px;border-bottom:1px solid #f0f0f0;">{_units:,}</td>'
                    f'<td style="padding:9px 14px;text-align:right;font-weight:600;color:#065f46;font-size:13px;border-bottom:1px solid #f0f0f0;">৳ {_amt:,.0f}</td>'
                    f'<td style="padding:9px 14px;border-bottom:1px solid #f0f0f0;">'
                    f'<div style="display:flex;align-items:center;gap:6px;">'
                    f'<div style="flex:1;background:#e5e7eb;border-radius:4px;height:6px;">'
                    f'<div style="width:{_bar_w}%;background:linear-gradient(90deg,#6366f1,#8b5cf6);border-radius:4px;height:6px;"></div>'
                    f"</div>"
                    f'<span style="font-size:12px;color:#6b7280;min-width:36px;text-align:right;">{_share_str}</span>'
                    f"</div></td></tr>"
                )
            # Total row — plain tr/td so Streamlit renders it
            _total_row_html = (
                '<tr style="background:linear-gradient(135deg,#fef3c7 0%,#fde68a 100%);'
                'border-top:2px solid #f59e0b;">'
                '<td style="padding:12px 14px;font-weight:700;color:#92400e;font-size:13px;'
                'letter-spacing:.02em;" colspan="2">🏆 GRAND TOTAL</td>'
                f'<td style="padding:12px 14px;text-align:right;font-weight:800;color:#92400e;font-size:14px;">{_sc_total_units:,}</td>'
                f'<td style="padding:12px 14px;text-align:right;font-weight:800;color:#065f46;font-size:14px;">৳ {_sc_total_amt:,.0f}</td>'
                '<td style="padding:12px 14px;font-weight:700;color:#92400e;font-size:13px;">100%</td>'
                "</tr>"
            )
            _table_html = (
                '<div style="border:1px solid #e5e7eb;border-radius:12px;overflow:hidden;'
                'box-shadow:0 1px 4px rgba(0,0,0,.06);margin-top:8px;">'
                '<table style="border-collapse:collapse;width:100%;font-family:Inter,sans-serif;">'
                f"{_hdr}{_rows_html}{_total_row_html}"
                "</table></div>"
            )
            st.markdown(_table_html, unsafe_allow_html=True)

        file_tag = (
            start_date.strftime("%Y%m%d")
            if start_date == end_date
            else f"{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}"
        )
        now_str = bd_now().strftime("%H%M")
        base_filename = f"DEEN_Shipped_Products_{file_tag}_{now_str}"

        # ── Regular orders export (excludes exchanges) ─────────────────────────────
        c_down1, c_down2 = st.columns(2)
        with c_down1:
            try:
                _sheet_tag = f"Shipped_{file_tag}"[:31]
                _sc_sheet_tag = f"SubCat_{file_tag}"[:31]
                # Include the GRAND TOTAL row in the exported sheet
                _subcat_export = pd.concat(
                    [
                        _subcat_summary,
                        pd.DataFrame(
                            [
                                {
                                    "Category": "GRAND TOTAL",
                                    "Sub-Category": "",
                                    "Units Sold": _sc_total_units,
                                    "Sales Amount (৳)": round(_sc_total_amt, 2),
                                    "Share (%)": "100%",
                                }
                            ]
                        ),
                    ],
                    ignore_index=True,
                )
                excel_bytes = export_to_styled_excel(
                    {
                        _sheet_tag: regular_df,
                        _sc_sheet_tag: _subcat_export,
                    },
                    group_by_col="Order ID"
                    if "Order ID" in regular_df.columns
                    else None,
                )
                st.download_button(
                    label=f"⬇️ Download Excel (.xlsx) — {len(regular_df)} items",
                    data=excel_bytes,
                    file_name=f"{base_filename}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                    use_container_width=True,
                    key="shipped_product_download_excel",
                )
            except Exception as e:
                log_system_event("EXCEL_EXPORT_ERROR", str(e))
                st.warning("Excel formatting unavailable, use CSV download.")

        with c_down2:
            csv_bytes = regular_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label=f"⬇️ Download CSV (.csv) — {len(regular_df)} items",
                data=csv_bytes,
                file_name=f"{base_filename}.csv",
                mime="text/csv",
                type="secondary",
                use_container_width=True,
                key="shipped_product_download_csv",
            )

        # ── Exchange orders tab: separate view + download ──────────────────────────
        with tab_exchange:
            if exchange_df.empty:
                st.info("No exchange/returned orders found for this period.")
            else:
                ex_total_items = (
                    int(exchange_df["Quantity"].sum())
                    if "Quantity" in exchange_df.columns
                    else len(exchange_df)
                )
                ex_total_orders = (
                    int(exchange_df["Order ID"].nunique())
                    if "Order ID" in exchange_df.columns
                    else len(exchange_df)
                )
                ex_total_rev = (
                    float(exchange_df["Line Total"].sum())
                    if "Line Total" in exchange_df.columns
                    else 0.0
                )
                st.caption(
                    f"🔄 **{ex_total_orders} exchange order(s)** · {ex_total_items} items · ৳ {ex_total_rev:,.0f}"
                )

                st.dataframe(
                    exchange_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Order ID": st.column_config.NumberColumn(
                            "Order ID", format="%d"
                        ),
                        "Quantity": st.column_config.NumberColumn("Qty", format="%d"),
                        "Product Line": st.column_config.TextColumn("Product Line"),
                        "Item Cost": st.column_config.NumberColumn(
                            "Price (৳)", format="%.2f"
                        ),
                        "Line Total": st.column_config.NumberColumn(
                            "Total (৳)", format="%.2f"
                        ),
                    },
                )

                ex_base_filename = f"DEEN_Exchange_Products_{file_tag}_{now_str}"
                c_ex1, c_ex2 = st.columns(2)
                with c_ex1:
                    try:
                        _ex_sheet_tag = f"Exchange_{file_tag}"[:31]
                        _ex_subcat = (
                            exchange_df.groupby(
                                ["Category", "Sub-Category"], sort=False
                            )
                            .agg(
                                _units=("Quantity", "sum"),
                                _amt=("Line Total", "sum"),
                            )
                            .reset_index()
                            .rename(
                                columns={
                                    "_units": "Units Sold",
                                    "_amt": "Sales Amount (৳)",
                                }
                            )
                            .sort_values("_amt", ascending=False)
                        )
                        _ex_subcat["Sales Amount (৳)"] = _ex_subcat[
                            "Sales Amount (৳)"
                        ].round(2)
                        _ex_total_units = int(_ex_subcat["Units Sold"].sum())
                        _ex_total_amt = float(_ex_subcat["Sales Amount (৳)"].sum())
                        _ex_subcat["Share (%)"] = (
                            (_ex_subcat["Sales Amount (৳)"] / _ex_total_amt * 100)
                            .round(1)
                            .astype(str)
                            + "%"
                            if _ex_total_amt > 0
                            else "0%"
                        )
                        _ex_subcat_export = pd.concat(
                            [
                                _ex_subcat,
                                pd.DataFrame(
                                    [
                                        {
                                            "Category": "GRAND TOTAL",
                                            "Sub-Category": "",
                                            "Units Sold": _ex_total_units,
                                            "Sales Amount (৳)": round(_ex_total_amt, 2),
                                            "Share (%)": "100%",
                                        }
                                    ]
                                ),
                            ],
                            ignore_index=True,
                        )
                        ex_excel_bytes = export_to_styled_excel(
                            {
                                _ex_sheet_tag: exchange_df,
                                f"ExSubCat_{file_tag}"[:31]: _ex_subcat_export,
                            },
                            group_by_col="Order ID"
                            if "Order ID" in exchange_df.columns
                            else None,
                        )
                        st.download_button(
                            label=f"⬇️ Download Excel (.xlsx) — {len(exchange_df)} items",
                            data=ex_excel_bytes,
                            file_name=f"{ex_base_filename}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            type="primary",
                            use_container_width=True,
                            key="exchange_product_download_excel",
                        )
                    except Exception as e:
                        log_system_event("EXCEL_ERROR", str(e))
                        st.warning("Excel formatting unavailable, use CSV download.")

                with c_ex2:
                    ex_csv_bytes = exchange_df.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        label=f"⬇️ Download CSV (.csv) — {len(exchange_df)} items",
                        data=ex_csv_bytes,
                        file_name=f"{ex_base_filename}.csv",
                        mime="text/csv",
                        type="secondary",
                        use_container_width=True,
                        key="exchange_product_download_csv",
                    )
