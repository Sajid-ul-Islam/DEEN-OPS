"""Delivery Health and WC Notes Sync tabs."""

from __future__ import annotations

import plotly.express as px
import streamlit as st

from src.components.ui.widgets import section_card
from src.services.woocommerce.orders import extract_order_id, update_order_status


def _render_delivery_health_tab():
    """Feature #2: Delivery Health Dashboard — return rates, delivery rates, district breakdown."""
    section_card(
        "Delivery Health Dashboard",
        "Analyze delivery rates, return rates, and average delivery time from your bulk tracking history.",
    )

    bulk_df_key = "pathao_bulk_result_df"
    bulk_df = st.session_state.get(bulk_df_key)

    if bulk_df is None:
        st.info(
            "📊 No bulk tracking data available. Run a Bulk Status Check in the **Order Tracking** tab first."
        )
        if st.button("📡 Go to Order Tracking", key="health_goto_tracking_btn"):
            st.session_state["orders_sub_feature"] = "Order Tracking"
            st.rerun()
        return

    if "Live Status" not in bulk_df.columns:
        st.warning(
            "⚠️ The loaded data doesn't have a 'Live Status' column. Please run a fresh bulk check."
        )
        return

    total = len(bulk_df)
    status_series = bulk_df["Live Status"].astype(str).str.lower()

    delivered = status_series.str.contains("delivered").sum()
    returned = status_series.str.contains("return").sum()
    failed = status_series.str.contains("fail|cancel").sum()
    in_transit = total - delivered - returned - failed

    delivery_rate = delivered / total * 100 if total > 0 else 0
    return_rate = returned / total * 100 if total > 0 else 0

    # KPI Cards
    health_html = (
        '<div class="metric-container metric-container-4">'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">DELIVERY RATE</div>'
        f'<div class="metric-value" style="color:#10b981;">{delivery_rate:.1f}%</div></div><div class="metric-icon">✅</div></div>'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">RETURN RATE</div>'
        f'<div class="metric-value" style="color:#ef4444;">{return_rate:.1f}%</div></div><div class="metric-icon">🔄</div></div>'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">IN TRANSIT</div>'
        f'<div class="metric-value" style="color:#3b82f6;">{in_transit}</div></div><div class="metric-icon">🚚</div></div>'
        f'<div class="metric-card"><div class="metric-content"><div class="metric-label">TOTAL TRACKED</div>'
        f'<div class="metric-value">{total}</div></div><div class="metric-icon">📦</div></div>'
        "</div>"
    )
    st.markdown(health_html, unsafe_allow_html=True)

    # Status Donut
    import plotly.graph_objects as go

    fig_donut = go.Figure(
        go.Pie(
            labels=["Delivered", "Returned", "Failed/Cancelled", "In Transit"],
            values=[delivered, returned, failed, in_transit],
            hole=0.55,
            marker_colors=["#10b981", "#ef4444", "#f59e0b", "#3b82f6"],
            textinfo="label+percent",
            hovertemplate="%{label}: %{value} orders (%{percent})<extra></extra>",
        )
    )
    fig_donut.update_layout(
        title="Dispatch Status Breakdown",
        margin=dict(l=10, r=10, t=40, b=10),
        height=320,
        showlegend=False,
    )

    d1, d2 = st.columns(2)
    with d1:
        st.plotly_chart(
            fig_donut, use_container_width=True, config={"displayModeBar": False}
        )

    with d2:
        # District breakdown if address / district col is available
        dist_col = next(
            (
                c
                for c in bulk_df.columns
                if any(kw in str(c).lower() for kw in ["city", "district", "zone"])
            ),
            None,
        )
        if dist_col:
            dist_df = (
                bulk_df.groupby(dist_col)["Live Status"]
                .agg(
                    total="count",
                    delivered=lambda s: (
                        s.astype(str).str.lower().str.contains("delivered").sum()
                    ),
                    returned=lambda s: (
                        s.astype(str).str.lower().str.contains("return").sum()
                    ),
                )
                .reset_index()
            )
            dist_df["Delivery Rate %"] = (
                dist_df["delivered"] / dist_df["total"] * 100
            ).round(1)
            dist_df = dist_df.sort_values("total", ascending=False).head(10)
            fig_dist = px.bar(
                dist_df,
                x=dist_col,
                y=["delivered", "returned"],
                title="Delivery vs Return by District",
                color_discrete_sequence=["#10b981", "#ef4444"],
                barmode="stack",
            )
            fig_dist.update_layout(
                margin=dict(l=10, r=10, t=40, b=30), height=320, showlegend=True
            )
            st.plotly_chart(
                fig_dist, use_container_width=True, config={"displayModeBar": False}
            )
        else:
            st.info("No city/district column detected for district-level breakdown.")

    # Action: Flag high-return orders
    if return_rate > 15:
        st.error(
            f"⚠️ High Return Rate Detected: {return_rate:.1f}%. Review addresses and product quality."
        )

    with st.expander("📊 Full Health Report"):
        st.dataframe(bulk_df, use_container_width=True)


def _render_wc_notes_tab():
    """Feature #9: Write WooCommerce order notes/status updates from within DEEN OPS."""
    section_card(
        "WooCommerce Order Notes Sync",
        "Write dispatch notes or update order statuses directly back to WooCommerce without opening the admin portal.",
    )

    nc1, nc2 = st.columns(2)
    with nc1:
        order_id_note = st.text_input(
            "WooCommerce Order ID", placeholder="e.g. 4821", key="wc_note_order_id"
        )
    with nc2:
        new_status = st.selectbox(
            "New Status (optional)",
            [
                "— Don't change status —",
                "processing",
                "completed",
                "on-hold",
                "cancelled",
            ],
            key="wc_note_status_sel",
        )

    note_text = st.text_area(
        "Note / Message",
        placeholder="e.g. Dispatched via Pathao. Consignment: DD0001234. ETA: 2 days.",
        height=100,
        key="wc_note_text",
    )

    col_send, col_quick = st.columns(2)
    with col_send:
        can_post = bool(order_id_note.strip())
        if not can_post:
            st.caption("Enter an Order ID above to enable posting.")
        if st.button(
            "💬 Post Note to WooCommerce",
            type="primary",
            use_container_width=True,
            key="wc_note_send_btn",
            disabled=not can_post,
        ):
            target_status = None if new_status.startswith("—") else new_status
            with st.spinner("Posting to WooCommerce..."):
                ok, msg = update_order_status(
                    order_id_note.strip(),
                    target_status or "processing",
                    note=note_text.strip() or None,
                )
                if ok:
                    st.toast(f"✅ Note posted to Order #{order_id_note} successfully.")
                else:
                    st.error(f"❌ Failed: {msg}")

    with col_quick:
        # Quick dispatch note from Pathao result

        result_df_n = st.session_state.get("pathao_res_df")
        if result_df_n is not None and not result_df_n.empty:
            if st.button(
                "🚚 Bulk: Post Dispatch Notes",
                type="secondary",
                use_container_width=True,
                key="wc_bulk_notes_btn",
            ):
                ok_count = 0
                fail_count = 0
                progress_n = st.progress(0)
                total_n = len(result_df_n)
                for i, (_, row) in enumerate(result_df_n.iterrows()):
                    wc_id = str(row.get("Order ID", "")).strip()
                    if not wc_id or wc_id.lower() in {"nan", "none"}:
                        continue
                    parsed_id = extract_order_id(wc_id)
                    if not parsed_id:
                        continue
                    note_auto = f"Dispatched via Pathao. Items: {row.get('ItemDesc', 'N/A')}. COD: ৳{row.get('COD', 0)}."
                    ok_n, _ = update_order_status(
                        parsed_id, "processing", note=note_auto
                    )
                    if ok_n:
                        ok_count += 1
                    else:
                        fail_count += 1
                    progress_n.progress((i + 1) / total_n)
                st.toast(f"✅ {ok_count} notes posted. {fail_count} failed.")
        else:
            st.caption(
                "💡 Process orders in the Order Processing tab to enable bulk dispatch notes."
            )

    st.divider()
    st.markdown("#### 🗒️ Quick Note Templates")
    templates = [
        (
            "🚚 Dispatched",
            "Dispatched via Pathao. Expected delivery: 2-3 business days.",
        ),
        ("❌ Cancelled", "Order cancelled per customer request. Refund initiated."),
        ("🔄 On Hold", "Order placed on hold pending stock confirmation."),
        ("✅ Delivered", "Order delivered successfully. Payment collected."),
    ]
    for label, tmpl in templates:
        if st.button(label, key=f"wc_tmpl_{label}", use_container_width=True):
            st.session_state["wc_note_text"] = tmpl
            st.rerun()
