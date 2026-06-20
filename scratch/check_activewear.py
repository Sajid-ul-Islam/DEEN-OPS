import pandas as pd
df = pd.read_csv("resources/last_stock.csv")
active = df[df["Product"].str.contains("Active", case=False, na=False) | df["Product"].str.contains("Wear", case=False, na=False)]
print(active)
