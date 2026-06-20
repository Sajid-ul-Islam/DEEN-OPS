import pandas as pd
df = pd.read_csv("resources/last_stock.csv")
bags = df[df["Product"].str.contains("bag", case=False, na=False) | df["Category"].str.contains("bag", case=False, na=False)]
print(bags[["Category", "Product", "SKU", "Stock"]].to_string())
