import pandas as pd

# Load 12-month matrix
df = pd.read_excel("palhoca_12m.xlsx")

MONTHS = [
    "11/2024","12/2024","01/2025","02/2025","03/2025","04/2025",
    "05/2025","06/2025","07/2025","08/2025","09/2025","10/2025",
]

# Ensure numeric
for m in MONTHS:
    df[m] = pd.to_numeric(df[m], errors="coerce").fillna(0)

# Totals
df["kwh_12m"] = df[MONTHS].sum(axis=1)

# Summary by category (B3/A4/IP)
by_cat = df.groupby("categoria", dropna=False)["kwh_12m"].sum().reset_index()
total_12m = df["kwh_12m"].sum()

# ----- Assumptions (edit these) -----
# Typical yield in SC often ~1200–1500 kWh/kWp/year depending on site, losses, tilt, shading, etc.
# Put YOUR chosen value here when you have it.
KWH_PER_KWP_YEAR_BASE = 1350

# Scenarios: conservative / base / optimistic
scenarios = [
    ("Conservador", 1250),
    ("Base", 1350),
    ("Otimista", 1450),
]


rows = []
for name, kwh_per_kwp_year in scenarios:
    kwp_needed = total_12m / kwh_per_kwp_year
    mwp_needed = kwp_needed / 1000
    rows.append({
        "Cenário": name,
        "Produtividade (kWh/kWp.ano)": kwh_per_kwp_year,
        "Consumo 12m (kWh)": round(total_12m, 3),
        "Potência Necessária (kWp)": round(kwp_needed, 3),
        "Potência Necessária (MWp)": round(mwp_needed, 6),
    })

dim = pd.DataFrame(rows)

# Also calculate per-category sizing (optional but great for report)
cat_dim = []
for cat in sorted(df["categoria"].dropna().unique()):
    cat_total = df.loc[df["categoria"] == cat, "kwh_12m"].sum()
    for name, kwh_per_kwp_year in scenarios:
        kwp = cat_total / kwh_per_kwp_year
        cat_dim.append({
            "Categoria": cat,
            "Cenário": name,
            "Consumo 12m (kWh)": round(cat_total, 3),
            "Produtividade (kWh/kWp.ano)": kwh_per_kwp_year,
            "kWp": round(kwp, 3),
            "MWp": round(kwp/1000, 6),
        })
cat_dim = pd.DataFrame(cat_dim)

# Save outputs
with pd.ExcelWriter("palhoca_dimensionamento_ufv.xlsx", engine="openpyxl") as writer:
    df.to_excel(writer, sheet_name="UC_12M", index=False)
    by_cat.to_excel(writer, sheet_name="Resumo_por_Grupo", index=False)
    dim.to_excel(writer, sheet_name="Dimensionamento_Total", index=False)
    cat_dim.to_excel(writer, sheet_name="Dimensionamento_por_Grupo", index=False)

print("DONE ✅ created palhoca_dimensionamento_ufv.xlsx")
print("Total 12m (kWh):", total_12m)
print(by_cat.to_string(index=False))
print(dim.to_string(index=False))
