import pandas as pd

df = pd.read_csv("palhoca_master.csv")
df["kwh_total_te"] = pd.to_numeric(df["kwh_total_te"], errors="coerce").fillna(0)

MONTHS = [
    "11/2024","12/2024","01/2025","02/2025","03/2025","04/2025",
    "05/2025","06/2025","07/2025","08/2025","09/2025","10/2025",
]

def first_nonempty(s: pd.Series) -> str:
    s = s.dropna().astype(str).str.strip()
    s = s[s != ""]
    return s.iloc[0] if len(s) else ""

def mode_nonempty(s: pd.Series) -> str:
    s = s.dropna().astype(str).str.strip()
    s = s[s != ""]
    if len(s) == 0:
        return ""
    return s.mode().iloc[0] if not s.mode().empty else s.iloc[0]

# 1) Build a UC-level metadata table (one row per UC)
meta = (
    df.groupby("uc", as_index=False)
      .agg({
          "nome": mode_nonempty,
          "endereco": mode_nonempty,
          "categoria": mode_nonempty,
          "tipo_fornecimento": mode_nonempty,
          "page_first_seen": "min",
      })
      .rename(columns={
          "uc": "UC",
          "nome": "Nome",
          "endereco": "Endereço",
          "categoria": "CLASSIFICAÇÃO (CATEGORIA)",
          "tipo_fornecimento": "TIPO DE FORNECIMENTO",
          "page_first_seen": "PÁGINA PDF",
      })
)

# 2) Pivot ONLY by UC (one row per UC guaranteed)
pivot = df.pivot_table(
    index="uc",
    columns="referencia",
    values="kwh_total_te",
    aggfunc="sum",
    fill_value=0,
)

# ensure all month columns exist and order them
for m in MONTHS:
    if m not in pivot.columns:
        pivot[m] = 0
pivot = pivot[MONTHS]

pivot = pivot.reset_index().rename(columns={"uc": "UC"})

# 3) Merge meta + months
out = meta.merge(pivot, on="UC", how="left")
for m in MONTHS:
    out[m] = pd.to_numeric(out[m], errors="coerce").fillna(0)

def disponibilidade(tipo: str) -> int:
    t = (str(tipo) or "").upper().strip()
    if t in ("TRIFÁSICO", "TRIFASICO"):
        return 100
    if t in ("BIFÁSICO", "BIFASICO"):
        return 50
    if t in ("MONOFÁSICO", "MONOFASICO"):
        return 30
    return 0

out["DISPONIBILIDADE"] = out["TIPO DE FORNECIMENTO"].apply(disponibilidade)
out["SALDO"] = ""
out["MEDIA MENSAL"] = out[MONTHS].sum(axis=1) / 12

# Final column order
out = out[
    ["Nome","Endereço","UC","CLASSIFICAÇÃO (CATEGORIA)","TIPO DE FORNECIMENTO",
     "DISPONIBILIDADE","SALDO","PÁGINA PDF"] + MONTHS + ["MEDIA MENSAL"]
]

out.to_excel("palhoca_template_final.xlsx", index=False)
out.to_csv("palhoca_template_final.tsv", sep="\t", index=False, encoding="utf-8-sig")

print("DONE ✅ created palhoca_template_final.xlsx")
print("rows=", len(out), "unique_uc=", out["UC"].nunique())
