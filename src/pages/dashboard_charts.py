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
        )
        fig_pie.update_layout(margin=dict(l=10, r=10, t=50, b=10), showlegend=False)
        fig_pie.update_traces(
            textposition="inside",
            textinfo="label+percent",
            textfont_size=11,
            hovertemplate="%{label}: %{value:,.0f} (%{percent})",
        )
        st.plotly_chart(fig_pie, use_container_width=True, config={"displayModeBar": False})
        _rev_tsv = summ[[display_col, "Total Amount"]].sort_values("Total Amount", ascending=False).to_csv(sep="\t", index=False)
        render_copy_button(_rev_tsv, "Copy Revenue Data")

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
            title="Volume by Fit/Type Breakdown",
            text_auto=".0f",
            color_discrete_map=color_map,
            category_orders={"Bar_Label": sorted_bars},
        )
        fig_bar.update_layout(
            margin=dict(l=50, r=10, t=50, b=40),
            xaxis_title="",
            yaxis_title="Quantity Sold",
            showlegend=False,
        )
        fig_bar.update_traces(hovertemplate="%{x}: %{y:,.0f}")
        st.plotly_chart(fig_bar, use_container_width=True, config={"displayModeBar": False})
        _vol_tsv = summ[[display_col, "Total Qty"]].sort_values("Total Qty", ascending=False).to_csv(sep="\t", index=False)
        render_copy_button(_vol_tsv, "Copy Volume Data")


def render_spotlight(
    top: pd.DataFrame,
    color_map: dict[str, str],
) -> None:
    """Render the Products Spotlight bar chart with truncated labels and copy button.

    Args:
        top: Top-items DataFrame with 'Product Name', 'SKU', 'Category', 'Total Qty', 'Total Amount'.
        color_map: Mapping of category values to hex colours.
    """
    if top is None or top.empty:
        return

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
    elif strategy == "Top 20":
        limit = 20
    elif strategy == "Underperformers":
        limit = 10
        ascending = True

    if strategy == "Custom Range" and not top.empty:
        with sc2:
            c_range = st.slider("Select Rank Range", 1, len(top), (1, min(10, len(top))))
            spotlight = top.iloc[c_range[0] - 1 : c_range[1]].sort_values("Total Amount", ascending=True)
    else:
        spotlight = (
            top.sort_values("Total Amount", ascending=not ascending)
            .head(limit)
            .sort_values("Total Amount", ascending=True)
        )

    spotlight = spotlight.copy()
    spotlight["Display_Name"] = spotlight.apply(
        lambda r: f"{r['Product Name']} [{r['SKU']}]", axis=1
    )
    spotlight["Label"] = spotlight["Display_Name"]

    if not ascending:
        top_indices = spotlight.tail(3).index if len(spotlight) >= 3 else spotlight.index
        spotlight.loc[top_indices, "Label"] = "\U0001f525 " + spotlight.loc[top_indices, "Label"]
    else:
        bot_indices = spotlight.head(3).index if len(spotlight) >= 3 else spotlight.index
        spotlight.loc[bot_indices, "Label"] = "\u26a0\ufe0f " + spotlight.loc[bot_indices, "Label"]

    fig_top = px.bar(
        spotlight,
        x="Total Amount",
        y="Label",
        orientation="h",
        color="Category",
        title=f"Spotlight: {strategy}",
        text_auto=".2s",
        color_discrete_map=color_map,
        hover_data={
            "Label": False,
            "Display_Name": True,
            "Product Name": True,
            "SKU": True,
            "Sub-Category": True,
            "Total Qty": ":.0f",
            "Total Amount": ":,.0f",
        },
    )
    fig_top.update_layout(
        margin=dict(l=12, r=12, t=50, b=12),
        yaxis_title="",
        xaxis_title="Revenue (TK)",
        showlegend=False,
    )
    st.plotly_chart(fig_top, use_container_width=True, config={"displayModeBar": False})
    _spot_tsv = spotlight[["Product Name", "SKU", "Category", "Total Qty", "Total Amount"]].to_csv(
        sep="\t", index=False
    )
    render_copy_button(_spot_tsv, "Copy Spotlight Data")
