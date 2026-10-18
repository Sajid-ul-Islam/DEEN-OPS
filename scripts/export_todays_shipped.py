import pandas as pd
import re
import os


def clean_phone(p):
    if pd.isna(p):
        return ""
    s = re.sub(r"\D", "", str(p))
    if s.startswith("880"):
        s = "0" + s[3:]
    elif s.startswith("88"):
        s = s[2:]
    elif len(s) == 10 and s.startswith("1"):
        s = "0" + s
    if len(s) == 11 and s.startswith("01"):
        return s
    return s


def run_export():
    source_path = "D:/Repo/DEEN-OPS/DEEN_OPS_Daily_Report_2026-10-17.xlsx"
    if not os.path.exists(source_path):
        print(f"File not found: {source_path}")
        return

    df = pd.read_excel(
        source_path,
        sheet_name="Raw Shift Data",
        dtype={"Phone (Billing)": str, "Order ID": str},
    )
    df["Clean_Phone"] = df["Phone (Billing)"].apply(clean_phone)
    df["Clean_Customer"] = (
        df["Full Name (Billing)"].fillna("Customer").astype(str).str.strip()
    )
    df["Order_Num"] = (
        pd.to_numeric(df["Order ID"].str.extract(r"(\d+)")[0], errors="coerce")
        .fillna(0)
        .astype(int)
    )

    # Sort in natural numerical order
    df = df.sort_values(by=["Order_Num", "Line Item Index"], ascending=[True, True])

    # 1. Line Items Sheet
    line_items_df = pd.DataFrame(
        {
            "Order ID": df["Order ID"].astype(str),
            "Customer Name": df["Clean_Customer"],
            "Phone Number": df["Clean_Phone"].astype(str),
            "Shipping City": df["Shipping City"]
            .fillna(df["Billing City"])
            .fillna("Dhaka")
            .astype(str),
            "Shipping Address": df["Shipping Address 1"]
            .fillna(df["Billing Address 1"])
            .fillna("")
            .astype(str),
            "Product Name": df["Clean_Product"],
            "SKU": df["SKU"].fillna("N/A").astype(str),
            "Category": df["Category"].fillna("Uncategorized").astype(str),
            "Quantity": df["Quantity"].astype(int),
            "Line Total (৳)": df["Total Amount"],
            "Order Total (৳)": df["Order Total Amount"],
            "Payment Method": df["Payment Method Title"]
            .fillna("Cash on Delivery")
            .astype(str),
            "Status": df["Order Status"].astype(str),
            "Date Modified": df["Order Date Modified"].astype(str),
        }
    )

    # 2. Orders Summary Sheet
    order_groups = []
    for oid, group in df.groupby("Order ID", sort=False):
        first = group.iloc[0]
        items_summary = "; ".join(
            [
                f"{row['Clean_Product']} [{row['SKU'] or 'N/A'}] (x{int(row['Quantity'])})"
                for _, row in group.iterrows()
            ]
        )
        order_groups.append(
            {
                "Order ID": str(first["Order ID"]),
                "Customer Name": str(first["Clean_Customer"]),
                "Phone Number": str(first["Clean_Phone"]),
                "Shipping City": str(
                    first["Shipping City"]
                    if pd.notna(first["Shipping City"])
                    else (
                        first["Billing City"]
                        if pd.notna(first["Billing City"])
                        else "Dhaka"
                    )
                ),
                "Shipping Address": str(
                    first["Shipping Address 1"]
                    if pd.notna(first["Shipping Address 1"])
                    else (
                        first["Billing Address 1"]
                        if pd.notna(first["Billing Address 1"])
                        else ""
                    )
                ),
                "Total Items": int(group["Quantity"].sum()),
                "Products List": items_summary,
                "Order Total (৳)": float(first["Order Total Amount"]),
                "Payment Method": str(
                    first["Payment Method Title"] or "Cash on Delivery"
                ),
                "Order Status": str(first["Order Status"]),
                "Date Modified": str(first["Order Date Modified"]),
            }
        )

    order_summary_df = pd.DataFrame(order_groups)
    order_summary_df["Order_Num"] = (
        pd.to_numeric(
            order_summary_df["Order ID"].astype(str).str.extract(r"(\d+)")[0],
            errors="coerce",
        )
        .fillna(0)
        .astype(int)
    )
    order_summary_df = order_summary_df.sort_values("Order_Num", ascending=True).drop(
        columns=["Order_Num"]
    )

    target_files = [
        "D:/Repo/DEEN-OPS/DEEN_Shipped_Orders_2026-10-17.xlsx",
        "D:/Repo/DEEN Sales Analysis/public/DEEN_Shipped_Orders_2026-10-17.xlsx",
    ]

    for target in target_files:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with pd.ExcelWriter(target, engine="xlsxwriter") as writer:
            order_summary_df.to_excel(writer, sheet_name="Orders Summary", index=False)
            line_items_df.to_excel(writer, sheet_name="Line Items Detail", index=False)

            wb = writer.book
            text_fmt = wb.add_format({"num_format": "@"})

            ws_summary = writer.sheets["Orders Summary"]
            ws_summary.set_column("C:C", 16, text_fmt)
            ws_summary.set_column("A:A", 12, text_fmt)

            ws_detail = writer.sheets["Line Items Detail"]
            ws_detail.set_column("C:C", 16, text_fmt)
            ws_detail.set_column("A:A", 12, text_fmt)

        print(f"Exported: {target}")

    print(
        f"Successfully processed {len(order_summary_df)} unique orders with {len(line_items_df)} line items."
    )


if __name__ == "__main__":
    run_export()
