"""Chart rendering for the dashboard — pie, bar, spotlight, and copy buttons."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from src.components.clipboard import render_copy_button
from src.utils.display import truncate_label


def render_category_charts(
    summ: pd.DataFrame,
    display_col: str,
    color_map: dict[str, str],
) -> None:
    """Render the Revenue Share pie and Volume bar charts with truncated labels.

    Args:
        summ: Summary DataFrame with 'Total Amount', 'Total Qty', etc.
        display_col: Column name to use for chart grouping ('Category' or 'Sub-Category').
        color_map: Mapping of category values to hex colours.
    """
    summ_display = summ.copy()
    summ_display["Display_Label"] = summ_display[display_col].apply(truncate_label)

    v1, v2 = st.columns(2)
    with v1:
        fig_pie = px.pie(
            summ_display,
            values="Total Amount",
            names="Display_Label",
            color=display_col,
            hole=0.6,
            title="Revenue Share (TK)",
            color_discrete_map=color_map,
            hover_data=["Total Qty"],
        )
        fig_pie.update_layout(margin=dict(t=50, b=20, l=10, r=10), showlegend=False)
        fig_pie.update_traces(
            textposition="inside",
            textinfo="label+percent",
            textfont_size=11,
            hovertemplate="<b>%{label}</b><br>Revenue: %{value:,.0f} TK (%{percent})<br>Volume: %{customdata[0]:,.0f} Units",
        )
        st.plotly_chart(fig_pie, use_container_width=True, config={"displayModeBar": False})

    with v2:
        bar_axis = "Sub-Category" if "Sub-Category" in summ.columns else display_col
        bar_display = summ_display.sort_values("Total Qty", ascending=False).copy()
        bar_display["Bar_Label"] = bar_display[bar_axis].apply(truncate_label)
        sorted_bars = bar_display["Bar_Label"].tolist()
        fig_bar = px.bar(
            bar_display,
            x="Bar_Label",
            y="Total Qty",
            color=display_col,
            title="Volume by Category",
            text_auto=".0f",
            color_discrete_map=color_map,
            category_orders={"Bar_Label": sorted_bars},
            hover_data={
                "Bar_Label": False,
                display_col: True,
                "Total Qty": ":,.0f",
                "Total Amount": ":,.0f",
            },
        )
        fig_bar.update_layout(
            margin=dict(t=50, b=20, l=10, r=10),
            xaxis_title="",
            yaxis_title="Quantity Sold",
            showlegend=False,
        )
        fig_bar.update_xaxes(automargin=True)
        fig_bar.update_yaxes(automargin=True)
        st.plotly_chart(fig_bar, use_container_width=True, config={"displayModeBar": False})


def render_spotlight(
    top: pd.DataFrame,
    color_map: dict[str, str],
    prev_top: pd.DataFrame | None = None
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
        agg_dict = {"Total Qty": "sum", "Total Amount": "sum", "Category": "first"}
        if "Sub-Category" in top.columns:
            agg_dict["Sub-Category"] = "first"
        
        top = top.groupby(group_cols, as_index=False).agg(agg_dict)
        top.rename(columns={"Clean_Product": "Product Name"}, inplace=True)
        
        if prev_top is not None and not prev_top.empty and "Clean_Product" in prev_top.columns:
            prev_top = prev_top.groupby(group_cols, as_index=False).agg(agg_dict)
            prev_top.rename(columns={"Clean_Product": "Product Name"}, inplace=True)

    st.subheader("\U0001f525 Products Spotlight")
    sc1, sc2 = st.columns([1, 1])
    with sc1:
        strategy = st.selectbox(
            "Spotlight Strategy",
            ["Top 10", "Top 20", "Underperformers", "Custom Range"],
            key="spotlight_strat",
        )

    limit = 10
    ascending = False
    if strategy == "Top 10":
        limit = 10
        ascending = False
    elif strategy == "Top 20":
        limit = 20
        ascending = False
    elif strategy == "Underperformers":
        limit = 10
        ascending = True

    # Ensure top is sorted descending by amount so custom range and limits slice correctly
    top = top.sort_values("Total Amount", ascending=False).reset_index(drop=True)

    if strategy == "Custom Range" and not top.empty:
        with sc2:
            c_range = st.slider("Select Rank Range", 1, len(top), (1, min(10, len(top))))
            spotlight = top.iloc[c_range[0] - 1 : c_range[1]].sort_values("Total Amount", ascending=True)
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
        has_sku = "SKU" in row and pd.notna(row["SKU"])
        label = f"{row['Product Name']} [{row['SKU']}]" if has_sku else f"{row['Product Name']}"
        
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
