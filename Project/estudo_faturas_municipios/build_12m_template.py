import pandas as pd

df = pd.read_csv("palhoca_master.csv")
df["kwh_total_te"] = pd.to_numeric(df["kwh_total_te"], errors="coerce").fillna(0)

# Define the 12-month cycle you want (edit if needed)
MONTHS = [
    "11/2024","12/2024","01/2025","02/2025","03/2025","04/2025",
    "05/2025","06/2025","07/2025","08/2025","09/2025","10/2025",
]

# Keep only months in the cycle (optional)
df = df[df["referencia"].isin(MONTHS)]

pivot = df.pivot_table(
    index=["uc","categoria","grupo_tensao","subgrupo","nome","endereco"],
    columns="referencia",
    values="kwh_total_te",
    aggfunc="sum",
    fill_value=0,
).reset_index()

# ensure all month columns exist
for m in MONTHS:
    if m not in pivot.columns:
        pivot[m] = 0

# order columns
pivot = pivot[["uc","categoria","grupo_tensao","subgrupo","nome","endereco"] + MONTHS]

pivot.to_csv("palhoca_12m.tsv", sep="\t", index=False, encoding="utf-8-sig")
pivot.to_excel("palhoca_12m.xlsx", index=False)

print("DONE ✅ created palhoca_12m.tsv and palhoca_12m.xlsx")

