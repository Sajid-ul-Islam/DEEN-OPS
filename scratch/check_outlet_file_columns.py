import pandas as pd
import sys
df = pd.read_excel("src/inventory/Mir.xlsx")
print("Columns in Mir.xlsx:", df.columns)
# Print to stdout forcing utf-8 encoding
sys.stdout.reconfigure(encoding='utf-8')
print(df.head(10).to_string())
