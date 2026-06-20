import pandas as pd
df = pd.read_csv("resources/last_stock.csv")
skus_102 = df[df["SKU"].astype(str).str.startswith("102")]
print(skus_102[["Category", "Product", "SKU", "Stock"]].to_string())
