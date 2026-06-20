import pandas as pd
df = pd.read_csv("resources/last_stock.csv")
keywords = ["active", "denim", "flannel", "bag", "panjabi", "sweatshirt", "tank", "twill", "wallet"]
for kw in keywords:
    matches = df[df["Product"].str.contains(kw, case=False, na=False)]
    print(f"Keyword '{kw}': {len(matches)} rows, sum of Stock = {matches['Stock'].sum()}")
