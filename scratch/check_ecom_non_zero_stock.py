import pandas as pd
from src.processing.categorization import get_category_for_sales
from src.processing.stock_categorization import map_to_csv_category

df = pd.read_csv("resources/last_stock.csv")
df["Stock"] = pd.to_numeric(df["Stock"], errors="coerce").fillna(0)
nonzero = df[df["Stock"] > 0]

print(f"Total non-zero stock rows: {len(nonzero)}")
rows = []
for idx, r in nonzero.iterrows():
    p = r["Product"]
    sku = r["SKU"]
    stock = r["Stock"]
    cat_csv = r["Category"]
    cat_sales = get_category_for_sales(p)
    cat_stock = map_to_csv_category(p)
    rows.append({
        "Product": p,
        "SKU": sku,
        "Stock": stock,
        "CSV_Cat": cat_csv,
        "Sales_Cat": cat_sales,
        "Stock_Cat": cat_stock
    })

df_res = pd.DataFrame(rows)
print(df_res.to_string(max_rows=100))
