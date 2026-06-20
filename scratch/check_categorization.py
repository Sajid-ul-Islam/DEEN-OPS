import pandas as pd
from src.processing.categorization import get_category_for_sales, get_sub_category_for_sales

df = pd.read_csv("resources/last_stock.csv")
df["Stock"] = pd.to_numeric(df["Stock"], errors="coerce").fillna(0)
df["Category_sales"] = df["Product"].apply(get_category_for_sales)
df["SubCategory_sales"] = df.apply(lambda r: get_sub_category_for_sales(r["Product"], r["Category_sales"]), axis=1)

print("--- Category Counts ---")
print(df.groupby("Category_sales")["Stock"].sum())
print("\n--- Subcategory Counts ---")
print(df.groupby("SubCategory_sales")["Stock"].sum())
