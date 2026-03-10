import pandas as pd

files = [
    "palhoca_1.csv",
    "palhoca_2.csv",
    "palhoca_3.csv",
    "palhoca_ip.csv",
]

df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)

# Keep only the categories we care about
df = df[df["categoria"].isin(["B3", "A4", "IP"])]

# Remove exact duplicate rows
df = df.drop_duplicates()

# Save master
df.to_csv("palhoca_master.csv", index=False, encoding="utf-8-sig")
df.to_csv("palhoca_master.tsv", index=False, sep="\t", encoding="utf-8-sig")

# Build UC x month matrix (great for your final template)
pivot = df.pivot_table(
    index=["uc", "categoria", "grupo_tensao", "subgrupo", "nome", "endereco"],
    columns="referencia",
    values="kwh_total_te",
    aggfunc="sum",
    fill_value=0,
).reset_index()

pivot.to_excel("palhoca_master_uc_x_mes.xlsx", index=False)

print("DONE ✅")
print("Created: palhoca_master.csv, palhoca_master.tsv, palhoca_master_uc_x_mes.xlsx")
