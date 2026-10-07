"""DEEN Selects vs DEEN Regular Collection Analytics Dashboard View Component.

Renders side-by-side collection KPI cards, category sales comparisons, visual distribution charts,
and product drilldowns between the premium 'DEEN Selects' and core 'DEEN Regular' lines.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.processing.selects_analytics import compute_selects_regular_analytics


def render_selects_analysis_section(
    m_df: pd.DataFrame,
    raw_df: pd.DataFrame | None = None,
) -> None:
    """Render the full DEEN Selects vs DEEN Regular collection analytics section.

    Args:
        m_df: Granular filtered/standardized DataFrame.
        raw_df: Optional raw orders DataFrame.
    """
    if m_df is None or m_df.empty:
        st.info("No order line data available for DEEN Selects vs Regular analysis.")
        return

    analytics = compute_selects_regular_analytics(m_df)
    summary = analytics["summary"]
    sel_cat = analytics["selects_cat_summary"]
    reg_cat = analytics["regular_cat_summary"]
    comp_matrix = analytics["comparison_matrix"]
    sel_top = analytics["selects_top_products"]
    reg_top = analytics["regular_top_products"]

    # Header & Description
    st.markdown("### 💎 DEEN Selects vs DEEN Regular Analytics")
    st.caption(
        "Real-time comparative performance between the premium **DEEN Selects** collection "
        "(products without the DEEN brand tag, e.g. curated third-party brands) and the core "
        "**DEEN Regular** catalog (products bearing the DEEN brand tag) across revenue, volume, and category sales."
    )

    # ── Executive KPI Cards ──────────────────────────────────────────────────
    c_sel, c_reg, c_ratio = st.columns([1, 1, 1])

    with c_sel:
        st.markdown(
            f"""
            <div style="background: linear-gradient(135deg, rgba(16, 185, 129, 0.12) 0%, rgba(6, 78, 59, 0.25) 100%);
                        border: 1px solid rgba(16, 185, 129, 0.4); border-radius: 12px; padding: 18px; margin-bottom: 12px;">
                <div style="font-size: 0.85rem; font-weight: 700; color: #34d399; text-transform: uppercase; letter-spacing: 0.05em;">
                    💎 DEEN Selects (Premium)
                </div>
                <div style="font-size: 1.8rem; font-weight: 800; color: #ffffff; margin-top: 6px;">
                    ৳{summary["selects_rev"]:,.0f}
                </div>
                <div style="font-size: 0.82rem; color: #94a3b8; margin-top: 4px; display: flex; justify-content: space-between;">
                    <span><b>{summary["selects_qty"]:,}</b> pcs ({summary["selects_qty_share"]:.1f}% vol)</span>
                    <span style="color: #34d399; font-weight: 700;">{summary["selects_rev_share"]:.1f}% Rev</span>
                </div>
                <div style="font-size: 0.78rem; color: #64748b; margin-top: 4px;">
                    Avg Price: ৳{summary["selects_avg_price"]:,.0f} | In {summary["selects_orders"]:,} Orders
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c_reg:
        st.markdown(
            f"""
            <div style="background: linear-gradient(135deg, rgba(59, 130, 246, 0.12) 0%, rgba(30, 58, 138, 0.25) 100%);
                        border: 1px solid rgba(59, 130, 246, 0.4); border-radius: 12px; padding: 18px; margin-bottom: 12px;">
                <div style="font-size: 0.85rem; font-weight: 700; color: #60a5fa; text-transform: uppercase; letter-spacing: 0.05em;">
                    📦 DEEN Regular (Core)
                </div>
                <div style="font-size: 1.8rem; font-weight: 800; color: #ffffff; margin-top: 6px;">
                    ৳{summary["regular_rev"]:,.0f}
                </div>
                <div style="font-size: 0.82rem; color: #94a3b8; margin-top: 4px; display: flex; justify-content: space-between;">
                    <span><b>{summary["regular_qty"]:,}</b> pcs ({summary["regular_qty_share"]:.1f}% vol)</span>
                    <span style="color: #60a5fa; font-weight: 700;">{summary["regular_rev_share"]:.1f}% Rev</span>
                </div>
                <div style="font-size: 0.78rem; color: #64748b; margin-top: 4px;">
                    Avg Price: ৳{summary["regular_avg_price"]:,.0f} | In {summary["regular_orders"]:,} Orders
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c_ratio:
        tot_rev = summary["total_revenue"]
        st.markdown(
            f"""
            <div style="background: linear-gradient(135deg, rgba(147, 51, 234, 0.12) 0%, rgba(88, 28, 135, 0.25) 100%);
                        border: 1px solid rgba(147, 51, 234, 0.4); border-radius: 12px; padding: 18px; margin-bottom: 12px;">
                <div style="font-size: 0.85rem; font-weight: 700; color: #c084fc; text-transform: uppercase; letter-spacing: 0.05em;">
                    ⚖️ Collection Revenue Split
                </div>
                <div style="font-size: 1.8rem; font-weight: 800; color: #ffffff; margin-top: 6px;">
                    ৳{tot_rev:,.0f}
                </div>
                <div style="margin-top: 10px; background-color: #1e293b; border-radius: 6px; height: 10px; overflow: hidden; display: flex;">
                    <div style="width: {summary["selects_rev_share"]:.1f}%; background-color: #10b981;" title="Selects: {summary["selects_rev_share"]:.1f}%"></div>
                    <div style="width: {summary["regular_rev_share"]:.1f}%; background-color: #3b82f6;" title="Regular: {summary["regular_rev_share"]:.1f}%"></div>
                </div>
                <div style="font-size: 0.78rem; color: #94a3b8; margin-top: 6px; display: flex; justify-content: space-between;">
                    <span>🟢 Selects: {summary["selects_rev_share"]:.1f}%</span>
                    <span>🔵 Regular: {summary["regular_rev_share"]:.1f}%</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

    # ── Visual Distribution Charts ───────────────────────────────────────────
    c_chart1, c_chart2 = st.columns([1, 1])

    with c_chart1:
        st.markdown("##### 🥧 Revenue & Volume Split")
        pie_data = pd.DataFrame(
            [
                {
                    "Collection": "💎 DEEN Selects",
                    "Revenue": summary["selects_rev"],
                    "Quantity": summary["selects_qty"],
                },
                {
                    "Collection": "📦 DEEN Regular",
                    "Revenue": summary["regular_rev"],
                    "Quantity": summary["regular_qty"],
                },
            ]
        )
        if summary["total_revenue"] > 0:
            fig_pie = px.pie(
                pie_data,
                names="Collection",
                values="Revenue",
                hole=0.55,
                color="Collection",
                color_discrete_map={
                    "💎 DEEN Selects": "#10b981",
                    "📦 DEEN Regular": "#3b82f6",
                },
            )
            fig_pie.update_traces(
                textposition="inside",
                textinfo="percent+label",
                marker=dict(line=dict(color="#0f172a", width=2)),
            )
            fig_pie.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#e2e8f0"),
                margin=dict(l=10, r=10, t=10, b=10),
                height=260,
                showlegend=False,
            )
            st.plotly_chart(fig_pie, use_container_width=True)
        else:
            st.info("No revenue recorded for pie chart.")

    with c_chart2:
        st.markdown("##### 📊 Top Categories Comparison")
        if not comp_matrix.empty:
            top_matrix = comp_matrix.head(6)
            fig_bar = go.Figure()
            fig_bar.add_trace(
                go.Bar(
                    name="💎 Selects",
                    x=top_matrix["Category"],
                    y=top_matrix["Selects Revenue"],
                    marker_color="#10b981",
                )
            )
            fig_bar.add_trace(
                go.Bar(
                    name="📦 Regular",
                    x=top_matrix["Category"],
                    y=top_matrix["Regular Revenue"],
                    marker_color="#3b82f6",
                )
            )
            fig_bar.update_layout(
                barmode="group",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#e2e8f0"),
                margin=dict(l=10, r=10, t=10, b=10),
                height=260,
                legend=dict(
                    orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1
                ),
                xaxis=dict(showgrid=False),
                yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.08)"),
            )
            st.plotly_chart(fig_bar, use_container_width=True)
        else:
            st.info("No category data available for bar chart.")

    st.markdown("---")

    # ── Side-by-Side Category Sales Tables ───────────────────────────────────
    st.markdown("#### 📂 Category Sales Breakdown")

    tab_side, tab_comp, tab_prods = st.tabs(
        [
            "📑 Side-by-Side Categories",
            "📊 Comparative Matrix",
            "🏆 Top Selling Products",
        ]
    )

    with tab_side:
        c_left, c_right = st.columns(2)

        with c_left:
            st.markdown("##### 💎 DEEN Selects Category Sales")
            if not sel_cat.empty:
                display_sel = sel_cat.copy()
                display_sel["Total Amount"] = display_sel["Total Amount"].apply(
                    lambda x: f"৳{x:,.0f}"
                )
                display_sel["Share %"] = display_sel["Share %"].apply(
                    lambda x: f"{x:.1f}%"
                )
                display_sel["Avg Price"] = display_sel["Avg Price"].apply(
                    lambda x: f"৳{x:,.0f}"
                )
                st.dataframe(
                    display_sel[
                        [
                            "Category",
                            "Total Amount",
                            "Total Qty",
                            "Share %",
                            "Avg Price",
                            "Top Product",
                        ]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No sales recorded under DEEN Selects for this time period.")

        with c_right:
            st.markdown("##### 📦 DEEN Regular Category Sales")
            if not reg_cat.empty:
                display_reg = reg_cat.copy()
                display_reg["Total Amount"] = display_reg["Total Amount"].apply(
                    lambda x: f"৳{x:,.0f}"
                )
                display_reg["Share %"] = display_reg["Share %"].apply(
                    lambda x: f"{x:.1f}%"
                )
                display_reg["Avg Price"] = display_reg["Avg Price"].apply(
                    lambda x: f"৳{x:,.0f}"
                )
                st.dataframe(
                    display_reg[
                        [
                            "Category",
                            "Total Amount",
                            "Total Qty",
                            "Share %",
                            "Avg Price",
                            "Top Product",
                        ]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No sales recorded under DEEN Regular for this time period.")

    with tab_comp:
        st.markdown("##### 🔍 Category-Wise Comparative Matrix")
        if not comp_matrix.empty:
            m_disp = comp_matrix.copy()
            m_disp["Selects Revenue"] = m_disp["Selects Revenue"].apply(
                lambda x: f"৳{x:,.0f}"
            )
            m_disp["Regular Revenue"] = m_disp["Regular Revenue"].apply(
                lambda x: f"৳{x:,.0f}"
            )
            m_disp["Total Revenue"] = m_disp["Total Revenue"].apply(
                lambda x: f"৳{x:,.0f}"
            )
            m_disp["Selects Rev %"] = m_disp["Selects Rev %"].apply(
                lambda x: f"{x:.1f}%"
            )
            st.dataframe(m_disp, use_container_width=True, hide_index=True)
        else:
            st.info("No comparative category data available.")

    with tab_prods:
        c_p1, c_p2 = st.columns(2)
        with c_p1:
            st.markdown("##### 💎 Top DEEN Selects Products")
            if not sel_top.empty:
                disp_stp = sel_top.head(15).copy()
                disp_stp["Total Amount"] = disp_stp["Total Amount"].apply(
                    lambda x: f"৳{x:,.0f}"
                )
                disp_stp["Avg Price"] = disp_stp["Avg Price"].apply(
                    lambda x: f"৳{x:,.0f}"
                )
                st.dataframe(disp_stp, use_container_width=True, hide_index=True)
            else:
                st.info("No DEEN Selects products sold in this period.")

        with c_p2:
            st.markdown("##### 📦 Top DEEN Regular Products")
            if not reg_top.empty:
                disp_rtp = reg_top.head(15).copy()
                disp_rtp["Total Amount"] = disp_rtp["Total Amount"].apply(
                    lambda x: f"৳{x:,.0f}"
                )
                disp_rtp["Avg Price"] = disp_rtp["Avg Price"].apply(
                    lambda x: f"৳{x:,.0f}"
                )
                st.dataframe(disp_rtp, use_container_width=True, hide_index=True)
            else:
                st.info("No DEEN Regular products sold in this period.")
