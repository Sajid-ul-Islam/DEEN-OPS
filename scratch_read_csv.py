import pandas as pd

url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQ4j3i94IWVlVYI5gErxzfmmaYNiirGqnrncRKrDCbHvmLYpzH9l4_etjYmfCoDj_Gv-_mps2gnufXE/pub?output=csv&gid=0&single=true"
df = pd.read_csv(url)
print(df.head())
print(df.columns)
