import pandas as pd

url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQ4j3i94IWVlVYI5gErxzfmmaYNiirGqnrncRKrDCbHvmLYpzH9l4_etjYmfCoDj_Gv-_mps2gnufXE/pubhtml?gid=0&single=true"
dfs = pd.read_html(url)
print(dfs[0].head())
