import pandas as pd
df = pd.read_csv("resources/last_stock.csv")
print("Unique Category values in last_stock.csv:")
print(df["Category"].unique())
print("\nSum of Stock by Category in last_stock.csv:")
print(df.groupby("Category")["Stock"].sum())
