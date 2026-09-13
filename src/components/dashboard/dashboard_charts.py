"""Chart rendering for the dashboard — pie, bar, spotlight, and copy buttons."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from src.utils.display import truncate_label


def get_short_category_label(name: str) -> str:
    """Return concise short descriptor (e.g. 'Denim', 'Flannel', 'Corduroy', 'Cuban') instead of long prefixes."""
    if not isinstance(name, str) or not name:
        return ""
    name_str = name.strip()
    lower_n = name_str.lower()

    if "denim" in lower_n:
        return "Denim"
    if "flannel" in lower_n:
        return "Flannel"
    if "casual" in lower_n:
        return "Casual"
    if "corduroy" in lower_n:
        return "Corduroy"
    if "cuban" in lower_n:
        return "Cuban"
    if "panjabi" in lower_n or "punjabi" in lower_n:
        return "Panjabi"
    if "formal" in lower_n or "executive" in lower_n:
        return "Formal"
    if "sweatshirt" in lower_n or "sweat shirt" in lower_n:
        return "Sweatshirt"
    if "jeans" in lower_n:
        return "Jeans"
    if "pajama" in lower_n or "payjama" in lower_n:
        return "Pajama"
    if "polo" in lower_n:
        return "Polo"
    if "cargo" in lower_n:
        return "Cargo"
    if "full sleeve shirt" in lower_n or lower_n == "fs shirt":
        return "FS Shirt"
    if "half sleeve shirt" in lower_n or lower_n == "hs shirt":
        return "HS Shirt"

    for prefix in [
        "FS Shirt - ",
        "HS Shirt - ",
        "FS T-Shirt - ",
        "HS T-Shirt - ",
        "FS Shirt ",
        "HS Shirt ",
        "FS ",
        "HS ",
    ]:
        if name_str.startswith(prefix):
            short_ver = name_str[len(prefix) :].strip()
            if short_ver:
                return short_ver

    return name_str


def render_category_charts(
    summ: pd.DataFrame,
    display_col: str,
    color_map: dict[str, str],
    metrics_summary: dict | None = None,
    total_revenue: float | None = None,
) -> None:
    """Render the Revenue Share pie and Volume bar charts with truncated labels.

    Args:
        summ: Summary DataFrame with 'Total Amount', 'Total Qty', etc.
        display_col: Column name to use for chart grouping ('Category' or 'Sub-Category').
        color_map: Mapping of category values to hex colours.
        metrics_summary: Optional dictionary containing top revenue/volume metrics.
        total_revenue: Optional Net Realized Revenue override for exact center donut alignment.
    """
    if summ is None or summ.empty:
        return

    summ_display = summ.copy()
    if "Total Qty" in summ_display.columns:
        summ_display["Total Qty"] = (
            pd.to_numeric(summ_display["Total Qty"], errors="coerce")
            .fillna(0)
            .astype(float)
        )
    else:
        summ_display["Total Qty"] = 0.0

    if "Total Amount" in summ_display.columns:
        summ_display["Total Amount"] = (
            pd.to_numeric(summ_display["Total Amount"], errors="coerce")
            .fillna(0.0)
            .astype(float)
        )
    else:
        summ_display["Total Amount"] = 0.0

    summ_display["Display_Label"] = summ_display[display_col].apply(
        lambda x: truncate_label(get_short_category_label(x), max_len=15)
    )

    v1, v2 = st.columns(2)
    with v1:
        pie_display = summ_display.copy()
        pie_display["Pie_Name"] = pie_display[display_col].apply(
            get_short_category_label
        )

        tot_rev = pie_display["Total Amount"].sum()
        if (
            display_col == "Sub-Category"
            and "Category" in pie_display.columns
            and tot_rev > 0
        ):

            def resolve_low_share_name(row):
                sub_raw = str(row.get(display_col, ""))
                cat_raw = str(row.get("Category", ""))
                sub_short = get_short_category_label(sub_raw)
                cat_short = get_short_category_label(cat_raw)

                # If share is low (< 5%), choose whichever label is shorter between Sub-Category and Category
                if float(row.get("Total Amount", 0)) < (0.05 * tot_rev):
                    if len(sub_short) > 0 and len(sub_short) <= len(cat_short):
                        return sub_short
                    return cat_short if len(cat_short) > 0 else sub_short
                return sub_short if len(sub_short) > 0 else cat_short

            pie_display["Pie_Name"] = pie_display.apply(resolve_low_share_name, axis=1)

        # Consolidate duplicate Pie_Name rows cleanly before calculating top slices and Others
        agg_dict = {"Total Amount": "sum", "Total Qty": "sum"}
        if display_col in pie_display.columns:
            agg_dict[display_col] = "first"
        if "Category" in pie_display.columns:
            agg_dict["Category"] = "first"
        pie_display = pie_display.groupby("Pie_Name", as_index=False).agg(agg_dict)

        # Scale category amounts to match Net Realized Revenue if provided
        gross_tot = float(pie_display["Total Amount"].sum())
        if (
            total_revenue is not None
            and total_revenue > 0
            and gross_tot > 0
            and abs(gross_tot - total_revenue) > 0.01
        ):
            scale_factor = total_revenue / gross_tot
            pie_display["Total Amount"] = pie_display["Total Amount"] * scale_factor

        name_totals = (
            pie_display.groupby("Pie_Name")["Total Amount"]
            .sum()
            .sort_values(ascending=False)
        )
        total_amt = (
            float(total_revenue)
            if (total_revenue is not None and total_revenue > 0)
            else float(name_totals.sum())
        )

        top_p = name_totals[name_totals >= 0.02 * total_amt].index.tolist()

        max_pie = 12
        if len(top_p) > max_pie - 1:
            top_p = top_p[: max_pie - 1]

        if len(top_p) < len(name_totals):
            others_mask = ~pie_display["Pie_Name"].isin(top_p)
            others_rev = float(pie_display.loc[others_mask, "Total Amount"].sum())
            others_qty = float(pie_display.loc[others_mask, "Total Qty"].sum())
            if pd.isna(others_rev):
                others_rev = 0.0
            if pd.isna(others_qty):
                others_qty = 0.0

            others_row = pd.DataFrame(
                [
                    {
                        "Pie_Name": "Others",
                        display_col: "Others",
                        "Total Amount": others_rev,
                        "Total Qty": others_qty,
                    }
                ]
            )
            pie_display = pd.concat(
                [pie_display[~others_mask], others_row], ignore_index=True
            )

            if "Others" not in color_map:
                color_map = color_map.copy()
                color_map["Others"] = "#94a3b8"

            name_totals = (
                pie_display.groupby("Pie_Name")["Total Amount"]
                .sum()
                .sort_values(ascending=False)
            )

        pie_display["_Name_Total"] = pie_display["Pie_Name"].map(name_totals)
        pie_display = pie_display.sort_values(
            ["_Name_Total", "Total Amount"], ascending=[False, False]
        )
        pie_display["Display_Label"] = pie_display["Pie_Name"].apply(
            lambda x: truncate_label(x, max_len=15)
        )

        pie_display["Total Qty"] = (
            pd.to_numeric(pie_display["Total Qty"], errors="coerce")
            .fillna(0)
            .astype(float)
        )
        pie_display["Total Amount"] = (
            pd.to_numeric(pie_display["Total Amount"], errors="coerce")
            .fillna(0.0)
            .astype(float)
        )

        pie_display["Avg_Price"] = pie_display.apply(
            lambda r: (
                (r["Total Amount"] / r["Total Qty"]) if r["Total Qty"] > 0 else 0.0
            ),
            axis=1,
        )
        pie_display["Avg_Price"] = (
            pd.to_numeric(pie_display["Avg_Price"], errors="coerce")
            .fillna(0.0)
            .astype(float)
        )

        fig_pie = px.pie(
            pie_display,
            values="Total Amount",
            names="Pie_Name",
            color=display_col,
            hole=0.55,
            title="<b>💰 Revenue Share (TK)</b>",
            color_discrete_map=color_map,
        )
        # Explicit customdata in a fixed, version-independent order so the
        # texttemplate and hovertemplate indices always match:
        # [0]=Total Qty  [1]=Display_Label  [2]=Pie_Name  [3]=Avg_Price
        fig_pie.update_traces(
            customdata=pie_display[
                ["Total Qty", "Display_Label", "Pie_Name", "Avg_Price"]
            ].values
        )

        center_annotation_text = (
            f"<span style='font-size:18px;'><b>৳ {total_amt:,.0f}</b></span><br>"
            f"<span style='font-size:10px;opacity:0.75;letter-spacing:0.5px;'>TOTAL REVENUE</span>"
        )
        fig_pie.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=40, b=30, l=20, r=20),
            height=440,
            showlegend=False,
            hoverlabel=dict(
                bgcolor="#0f172a",
                font_size=12,
                font_family="Inter, sans-serif",
                font_color="#ffffff",
                bordercolor="#a855f7",
            ),
            annotations=[
                dict(
                    text=center_annotation_text,
                    x=0.5,
                    y=0.5,
                    font=dict(family="Inter, sans-serif"),
                    showarrow=False,
                    align="center",
                )
            ],
        )
        # Determine background gap color so slices do NOT join:
        # Light mode page -> #ffffff (creates a 4.5px white gap separating slices)
        # Dark mode page  -> #0f172a (creates a 4.5px dark gap separating slices)
        is_dark = (
            st.session_state.get("dark_mode", False)
            or "dark" in str(st.session_state.get("theme_mode", "")).lower()
        )
        gap_color = "#0f172a" if is_dark else "#ffffff"

        fig_pie.update_traces(
            sort=False,
            textposition="inside",
            texttemplate="%{customdata[1]}<br>%{percent:.0%}",
            textfont_size=11,
            marker=dict(line=dict(color=gap_color, width=4.5)),
            hovertemplate=(
                "<b>%{customdata[2]}</b><br>"
                "💰 Revenue: <b>৳ %{value:,.0f}</b> (%{percent:.1%})<br>"
                "📦 Volume Sold: <b>%{customdata[0]:,.0f} Units</b><br>"
                "🏷️ Avg Item Price: <b>৳ %{customdata[3]:,.0f} / unit</b>"
                "<extra></extra>"
            ),
        )
        st.plotly_chart(
            fig_pie, use_container_width=True, config={"displayModeBar": False}
        )

    with v2:
        bar_axis = "Sub-Category" if "Sub-Category" in summ.columns else display_col
        bar_display = summ_display.copy()

        bar_display["Bar_X"] = bar_display[bar_axis].apply(get_short_category_label)

        if (
            display_col == "Sub-Category"
            and len(bar_display) > 12
            and "Category" in bar_display.columns
        ):
            jeans_mask = bar_display["Category"] == "Jeans"
            bar_display.loc[jeans_mask, "Bar_X"] = "Jeans"

        x_totals = (
            bar_display.groupby("Bar_X")["Total Qty"].sum().sort_values(ascending=False)
        )

        max_bars = 12
        if len(x_totals) > max_bars:
            top_x = x_totals.index[: max_bars - 1].tolist()
            bar_display.loc[~bar_display["Bar_X"].isin(top_x), "Bar_X"] = "Others"

            x_totals = (
                bar_display.groupby("Bar_X")["Total Qty"]
                .sum()
                .sort_values(ascending=False)
            )
            sorted_bars = [x for x in x_totals.index if x != "Others"] + ["Others"]
        else:
            sorted_bars = x_totals.index.tolist()

        bar_display["Total Qty"] = (
            pd.to_numeric(bar_display["Total Qty"], errors="coerce")
            .fillna(0)
            .astype(float)
        )
        bar_display["Total Amount"] = (
            pd.to_numeric(bar_display["Total Amount"], errors="coerce")
            .fillna(0.0)
            .astype(float)
        )
        bar_display = bar_display.sort_values("Total Qty", ascending=False)
        bar_display["Avg_Unit_Price"] = bar_display.apply(
            lambda r: (
                (r["Total Amount"] / r["Total Qty"]) if r["Total Qty"] > 0 else 0.0
            ),
            axis=1,
        )
        bar_display["Avg_Unit_Price"] = (
            pd.to_numeric(bar_display["Avg_Unit_Price"], errors="coerce")
            .fillna(0.0)
            .astype(float)
        )

        unique_bars = pd.DataFrame({"Bar_X": sorted_bars})
        unique_bars["Bar_Label"] = unique_bars["Bar_X"].apply(
            lambda x: truncate_label(get_short_category_label(x), max_len=15)
        )

        fig_bar = px.bar(
            bar_display,
            x="Bar_X",
            y="Total Qty",
            color=display_col,
            title="<b>📦 Sales Volume by Category</b>",
            text_auto=".0f",
            color_discrete_map=color_map,
            category_orders={"Bar_X": sorted_bars},
        )
        # Explicit customdata in a fixed order so the hovertemplate indices are
        # version-independent: [0]=Bar_X  [1]=Total Amount  [2]=Avg_Unit_Price
        fig_bar.update_traces(
            customdata=bar_display[["Bar_X", "Total Amount", "Avg_Unit_Price"]].values
        )

        avg_vol = bar_display["Total Qty"].mean() if not bar_display.empty else 0
        if avg_vol > 0:
            fig_bar.add_hline(
                y=avg_vol,
                line_dash="dash",
                line_color="rgba(255,255,255,0.4)",
                annotation_text=f"Avg: {avg_vol:.1f} units",
                annotation_position="top right",
                annotation_font=dict(size=10, color="rgba(255,255,255,0.7)"),
            )

        fig_bar.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=40, b=30, l=20, r=20),
            height=440,
            xaxis_title="",
            yaxis_title="Units Sold",
            showlegend=False,
            hoverlabel=dict(
                bgcolor="#0f172a",
                font_size=12,
                font_family="Inter, sans-serif",
                font_color="#ffffff",
                bordercolor="#3b82f6",
            ),
        )
        fig_bar.update_xaxes(
            showgrid=False,
            automargin=True,
            tickmode="array",
            tickvals=unique_bars["Bar_X"],
            ticktext=unique_bars["Bar_Label"],
            tickangle=-45,
        )
        fig_bar.update_yaxes(
            showgrid=True,
            gridwidth=1,
            gridcolor="rgba(255,255,255,0.06)",
            zeroline=False,
            automargin=True,
        )
        fig_bar.update_traces(
            cliponaxis=False,
            marker=dict(line=dict(color="rgba(255,255,255,0.2)", width=1)),
            hovertemplate="<b>%{x}</b><br>📦 Volume: %{y:,.0f} Units<br>💰 Net Revenue: ৳ %{customdata[1]:,.0f}<br>🏷️ Avg Price: ৳ %{customdata[2]:,.0f}/unit",
        )
        st.plotly_chart(
            fig_bar, use_container_width=True, config={"displayModeBar": False}
        )


def render_spotlight(
    top: pd.DataFrame, color_map: dict[str, str], prev_top: pd.DataFrame | None = None
) -> None:
    """Render the Products Spotlight bar chart with velocity arrows and stock alerts.

    Args:
        top: Top-items DataFrame with 'Product Name', 'SKU', 'Category', 'Total Qty', 'Total Amount'.
        color_map: Mapping of category values to hex colours.
        prev_top: Optional previous-period top-items for velocity calculation.
    """
    if top is None or top.empty:
        return

    # Apply size-agnostic grouping (aggregate by Clean_Product)
    top = top.copy()
    if "Clean_Product" in top.columns:
        group_cols = ["Clean_Product"]
        if "SKU" in top.columns:
            group_cols.append("SKU")

        agg_dict = {"Total Qty": "sum", "Total Amount": "sum", "Category": "first"}
        if "Sub-Category" in top.columns:
            agg_dict["Sub-Category"] = "first"

        top = top.groupby(group_cols, as_index=False).agg(agg_dict)
        top.rename(columns={"Clean_Product": "Product Name"}, inplace=True)

        if (
            prev_top is not None
            and not prev_top.empty
            and "Clean_Product" in prev_top.columns
        ):
            prev_group_cols = ["Clean_Product"]
            if "SKU" in prev_top.columns:
                prev_group_cols.append("SKU")
            prev_top = prev_top.groupby(prev_group_cols, as_index=False).agg(agg_dict)
            prev_top.rename(columns={"Clean_Product": "Product Name"}, inplace=True)

    st.subheader("🔥 Products Spotlight")
    sc1, sc2 = st.columns([1, 1])
    with sc1:
        strat_opts = [
            "Top 10",
            "Top 20",
            "Last 10",
            "Last 20",
            "Underperformers",
            "Custom Range",
            "Custom Order",
        ]
        if hasattr(st, "pills"):
            strategy = st.pills(
                "Spotlight Strategy",
                strat_opts,
                default="Top 10",
                key="spotlight_strat_pills",
                selection_mode="single",
            )
            if not strategy:
                strategy = "Top 10"
        else:
            strategy = st.radio(
                "Spotlight Strategy",
                strat_opts,
                index=0,
                key="spotlight_strat_radio",
                horizontal=True,
            )

    limit = 10
    ascending = False
    if strategy == "Top 10":
        limit = 10
        ascending = False
    elif strategy == "Top 20":
        limit = 20
        ascending = False
    elif strategy in ["Last 10", "Underperformers"]:
        limit = 10
        ascending = True
    elif strategy == "Last 20":
        limit = 20
        ascending = True

    # Ensure top is sorted descending by amount so custom range and limits slice correctly
    top = top.sort_values("Total Amount", ascending=False).reset_index(drop=True)

    if strategy in ["Custom Range", "Custom Order"] and not top.empty:
        with sc2:
            c_range = st.slider(
                "Select Rank Range", 1, len(top), (1, min(10, len(top)))
            )
            spotlight = top.iloc[c_range[0] - 1 : c_range[1]].sort_values(
                "Total Amount", ascending=True
            )
    else:
        spotlight = (
            top.sort_values("Total Amount", ascending=ascending)
            .head(limit)
            .sort_values("Total Amount", ascending=True)
        )

    spotlight = spotlight.copy()

    # v15.0: Calculate Velocity and Stock Intelligence
    stock_df = st.session_state.get("wc_stock_df")

    def get_velocity_and_stock_label(row):
        has_sku = (
            "SKU" in row
            and pd.notna(row["SKU"])
            and str(row["SKU"]).strip() not in ["", "N/A", "nan"]
        )
        product_name = str(row["Product Name"])
        label = f"{product_name} [{row['SKU']}]" if has_sku else f"{product_name}"

        # 🟢 Velocity Logic
        if prev_top is not None and not prev_top.empty:
            if has_sku and "SKU" in prev_top.columns:
                prev_row = prev_top[prev_top["SKU"] == row["SKU"]]
            elif "Product Name" in prev_top.columns:
                prev_row = prev_top[prev_top["Product Name"] == row["Product Name"]]
            else:
                prev_row = pd.DataFrame()

            if not prev_row.empty:
                curr_q = row["Total Qty"]
                prev_q = prev_row.iloc[0]["Total Qty"]
                if curr_q > prev_q:
                    label = f"<span style='color:#10b981'>🔼</span> {label}"
                elif curr_q < prev_q:
                    label = f"<span style='color:#ef4444'>🔽</span> {label}"

        # 🔴 Safety Stock Logic
        if stock_df is not None and not stock_df.empty:
            sku_stock = pd.DataFrame()
            if has_sku and "SKU" in stock_df.columns:
                sku_stock = stock_df[stock_df["SKU"] == row["SKU"]]
            elif "Clean_Product" in stock_df.columns:
                sku_stock = stock_df[stock_df["Clean_Product"] == row["Product Name"]]
            elif "Product" in stock_df.columns:
                sku_stock = stock_df[stock_df["Product"] == row["Product Name"]]

            if not sku_stock.empty:
                stock_qty = sku_stock["Stock"].sum()
                # Trigger earlier: if stock is under absolute minimum (10) OR less than 3x current shift sales
                if stock_qty <= 10 or stock_qty <= (row["Total Qty"] * 3.0):
                    label = f"<span style='color:#f59e0b'>⚠️</span> {label}"

        return label

    spotlight["Label"] = spotlight.apply(get_velocity_and_stock_label, axis=1)

    hover_data_dict = {
        "Label": False,
        "Product Name": True,
        "Sub-Category": True if "Sub-Category" in spotlight.columns else False,
        "Total Qty": ":.0f",
        "Total Amount": ":,.0f",
    }
    if "SKU" in spotlight.columns:
        hover_data_dict["SKU"] = True

    fig_top = px.bar(
        spotlight,
        x="Total Amount",
        y="Label",
        orientation="h",
        color="Category",
        title=f"Spotlight: {strategy}",
        text_auto=".2s",
        color_discrete_map=color_map,
        hover_data=hover_data_dict,
    )
    fig_top.update_layout(
        margin=dict(t=50, b=20, l=10, r=20),
        yaxis_title="",
        xaxis_title="Revenue (TK)",
        showlegend=False,
    )
    fig_top.update_yaxes(automargin=True)
    fig_top.update_xaxes(automargin=True)
    st.plotly_chart(fig_top, use_container_width=True, config={"displayModeBar": False})
