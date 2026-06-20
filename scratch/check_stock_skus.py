import pandas as pd
df = pd.read_csv("resources/last_stock.csv")
shirts = df[df["Product"].str.contains("Shirt", case=False, na=False) | df["Category"].str.contains("Shirt", case=False, na=False)]
print(shirts[["Category", "Product", "SKU", "Stock"]].to_string())
