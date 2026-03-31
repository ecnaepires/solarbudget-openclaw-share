from __future__ import annotations

from html import escape

import streamlit as st


def apply_style(theme: str = "forest") -> None:
    themes = {
        "forest": {
            "bg": "#f4f7f5",
            "bg_alt": "#edf3f0",
            "surface": "#ffffff",
            "surface_alt": "#f8fbf9",
            "surface_tint": "#eef5f1",
            "text": "#112019",
            "text_soft": "#2f4339",
            "muted": "#55675e",
            "border": "#d9e4de",
            "border_strong": "#c4d3ca",
            "primary": "#1d7a63",
            "primary_hover": "#18634f",
            "primary_soft": "#e7f3ee",
            "accent": "#176087",
            "accent_soft": "#e8f1f7",
            "warning": "#b7791f",
            "warning_soft": "#f9f1df",
            "danger": "#c2414d",
            "danger_soft": "#fdecef",
            "sidebar_bg": "#eef3f0",
            "sidebar_surface": "#f7faf8",
            "sidebar_border": "#d3ddd7",
            "sidebar_text": "#163026",
            "topbar": "rgba(244, 247, 245, 0.86)",
            "shadow_sm": "0 2px 8px rgba(16, 24, 40, 0.04)",
            "shadow_md": "0 14px 36px rgba(16, 24, 40, 0.08)",
            "shadow_lg": "0 22px 54px rgba(16, 24, 40, 0.10)",
            "ring": "rgba(29, 122, 99, 0.16)",
            "overlay": "rgba(17, 32, 25, 0.04)",
            "header_orb": "rgba(29, 122, 99, 0.08)",
            "is_light": True,
        },
        "slate": {
            "bg": "#0f1724",
            "bg_alt": "#131d2c",
            "surface": "#172233",
            "surface_alt": "#1c293d",
            "surface_tint": "#1d2d42",
            "text": "#eef4fb",
            "text_soft": "#d7e2f1",
            "muted": "#afbdd0",
            "border": "#2b3a52",
            "border_strong": "#3a4c68",
            "primary": "#6cb892",
            "primary_hover": "#5aa17e",
            "primary_soft": "#1f372f",
            "accent": "#7fb4ff",
            "accent_soft": "#213556",
            "warning": "#d3a551",
            "warning_soft": "#332a19",
            "danger": "#f28b95",
            "danger_soft": "#3a1f28",
            "sidebar_bg": "#0d1522",
            "sidebar_surface": "#141f30",
            "sidebar_border": "#253449",
            "sidebar_text": "#eef4fb",
            "topbar": "rgba(15, 23, 36, 0.82)",
            "shadow_sm": "0 3px 12px rgba(0, 0, 0, 0.24)",
            "shadow_md": "0 18px 42px rgba(0, 0, 0, 0.28)",
            "shadow_lg": "0 28px 64px rgba(0, 0, 0, 0.34)",
            "ring": "rgba(108, 184, 146, 0.18)",
            "overlay": "rgba(255, 255, 255, 0.04)",
            "header_orb": "rgba(127, 180, 255, 0.10)",
            "is_light": False,
        },
    }

    t = themes.get(theme, themes["forest"])
    color_scheme = "light" if t["is_light"] else "dark"
    button_text = "#ffffff" if t["is_light"] else "#0d1522"
    icon_text = "#ffffff" if t["is_light"] else "#0d1522"

    st.markdown(
        f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap');

:root {{
  color-scheme: {color_scheme};
  --bg: {t["bg"]};
  --bg-alt: {t["bg_alt"]};
  --surface: {t["surface"]};
  --surface-alt: {t["surface_alt"]};
  --surface-tint: {t["surface_tint"]};
  --text: {t["text"]};
  --text-soft: {t["text_soft"]};
  --muted: {t["muted"]};
  --border: {t["border"]};
  --border-strong: {t["border_strong"]};
  --primary: {t["primary"]};
  --primary-hover: {t["primary_hover"]};
  --primary-soft: {t["primary_soft"]};
  --accent: {t["accent"]};
  --accent-soft: {t["accent_soft"]};
  --warning: {t["warning"]};
  --warning-soft: {t["warning_soft"]};
  --danger: {t["danger"]};
  --danger-soft: {t["danger_soft"]};
  --sidebar-bg: {t["sidebar_bg"]};
  --sidebar-surface: {t["sidebar_surface"]};
  --sidebar-border: {t["sidebar_border"]};
  --sidebar-text: {t["sidebar_text"]};
  --topbar: {t["topbar"]};
  --shadow-sm: {t["shadow_sm"]};
  --shadow-md: {t["shadow_md"]};
  --shadow-lg: {t["shadow_lg"]};
  --ring: {t["ring"]};
  --overlay: {t["overlay"]};
  --header-orb: {t["header_orb"]};
  --radius-xs: 8px;
  --radius-sm: 12px;
  --radius-md: 18px;
  --radius-lg: 24px;
  --content-max: 1320px;
  --transition: 0.18s ease;
}}

html, body, [class*="css"], [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {{
  font-family: "Plus Jakarta Sans", "Segoe UI", sans-serif;
}}

body {{
  color: var(--text);
}}

[data-testid="stAppViewContainer"] {{
  background:
    radial-gradient(circle at top right, var(--header-orb), transparent 24%),
    radial-gradient(circle at top left, var(--overlay), transparent 24%),
    linear-gradient(180deg, var(--bg) 0%, var(--bg-alt) 100%);
  color: var(--text);
}}

[data-testid="stHeader"] {{
  background: var(--topbar);
  border-bottom: 1px solid var(--border);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
}}

.main .block-container {{
  max-width: var(--content-max);
  padding-top: 1.35rem;
  padding-bottom: 3rem;
  padding-left: 1.4rem;
  padding-right: 1.4rem;
}}

h1, h2, h3, h4, h5, h6 {{
  font-family: "Space Grotesk", "Plus Jakarta Sans", sans-serif;
  color: var(--text);
  letter-spacing: -0.03em;
  line-height: 1.12;
}}

h1 {{
  font-size: clamp(2rem, 2.8vw, 2.55rem);
  font-weight: 700;
}}

h2 {{
  font-size: clamp(1.4rem, 2vw, 1.75rem);
  font-weight: 700;
}}

h3 {{
  font-size: 1.05rem;
  font-weight: 700;
}}

p, li, label, .stMarkdown, [data-testid="stMarkdownContainer"] {{
  color: var(--text-soft);
  line-height: 1.68;
  font-size: 0.94rem;
}}

[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
.stMarkdown p,
.stMarkdown li {{
  color: var(--text-soft);
  line-height: 1.7;
}}

small, .stCaption {{
  color: var(--muted) !important;
  font-size: 0.8rem !important;
  line-height: 1.6 !important;
}}

a {{
  color: var(--primary);
}}

[data-testid="stSidebar"] {{
  background: linear-gradient(180deg, var(--sidebar-bg) 0%, var(--sidebar-surface) 100%);
  border-right: 1px solid var(--sidebar-border);
}}

[data-testid="stSidebar"] * {{
  color: var(--sidebar-text);
}}

[data-testid="stSidebar"] hr {{
  border-color: var(--sidebar-border) !important;
  margin: 0.9rem 0 !important;
}}

[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h3 {{
  margin-top: 0.95rem;
  margin-bottom: 0.45rem;
  font-size: 0.72rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
}}

.sidebar-brand {{
  display: flex;
  align-items: center;
  gap: 0.9rem;
  padding: 0.25rem 0 1rem;
  margin-bottom: 0.8rem;
  border-bottom: 1px solid var(--sidebar-border);
}}

.sidebar-brand-icon {{
  width: 2.7rem;
  height: 2.7rem;
  border-radius: 0.95rem;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, var(--primary) 0%, var(--accent) 100%);
  color: {icon_text};
  box-shadow: var(--shadow-sm);
  flex-shrink: 0;
}}

.sidebar-brand-icon svg {{
  width: 1.25rem;
  height: 1.25rem;
}}

.sidebar-brand-text {{
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
  min-width: 0;
}}

.sidebar-brand-name {{
  color: var(--sidebar-text);
  font-family: "Space Grotesk", "Plus Jakarta Sans", sans-serif;
  font-size: 1rem;
  font-weight: 700;
  letter-spacing: -0.02em;
}}

.sidebar-brand-tag {{
  color: var(--muted);
  font-size: 0.72rem;
  font-weight: 600;
}}

.sidebar-session {{
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin-top: 0.9rem;
  padding: 0.8rem 0.9rem;
  border: 1px solid var(--sidebar-border);
  border-radius: var(--radius-sm);
  background: rgba(255, 255, 255, 0.03);
}}

.sidebar-session-dot {{
  width: 0.55rem;
  height: 0.55rem;
  border-radius: 999px;
  background: var(--primary);
  flex-shrink: 0;
}}

.sidebar-session-text {{
  color: var(--muted);
  font-size: 0.73rem;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}}

.page-header {{
  position: relative;
  overflow: hidden;
  margin: 0 0 1.5rem;
  padding: 1.8rem 2rem 1.7rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background:
    radial-gradient(circle at top right, var(--header-orb), transparent 34%),
    linear-gradient(180deg, var(--surface) 0%, var(--surface-alt) 100%);
  box-shadow: var(--shadow-md);
}}

.page-header::after {{
  content: "";
  position: absolute;
  inset: auto 0 0 0;
  height: 1px;
  background: linear-gradient(90deg, transparent 0%, var(--border-strong) 25%, var(--border-strong) 75%, transparent 100%);
}}

.page-header-eyebrow {{
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 0.9rem;
  padding: 0.42rem 0.7rem;
  border-radius: 999px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 0.72rem;
  font-weight: 800;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}}

.page-header-title {{
  position: relative;
  max-width: 880px;
  margin-bottom: 0.45rem;
  color: var(--text);
  font-size: clamp(1.9rem, 2.5vw, 2.45rem);
  font-weight: 700;
}}

.page-header-sub {{
  position: relative;
  max-width: 920px;
  color: var(--text-soft);
  font-size: 1rem;
  font-weight: 600;
  line-height: 1.7;
}}

.page-header-pills {{
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem;
  margin-top: 1rem;
}}

.page-header-pill {{
  display: inline-flex;
  align-items: center;
  padding: 0.42rem 0.72rem;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.5);
  color: var(--text);
  font-size: 0.74rem;
  font-weight: 700;
}}

.section-card {{
  margin: 0 0 1.2rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: linear-gradient(180deg, var(--surface) 0%, var(--surface-alt) 100%);
  box-shadow: var(--shadow-sm);
}}

.section-card-solid {{
  background: linear-gradient(180deg, var(--surface-alt) 0%, var(--surface) 100%);
  box-shadow: var(--shadow-md);
}}

.section-head {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 1.1rem 1.35rem 0.95rem;
  border-bottom: 1px solid var(--border);
}}

.section-title {{
  color: var(--text);
  font-family: "Space Grotesk", "Plus Jakarta Sans", sans-serif;
  font-size: 1.03rem;
  font-weight: 700;
  line-height: 1.2;
}}

.section-chip {{
  display: inline-flex;
  align-items: center;
  padding: 0.35rem 0.65rem;
  border-radius: 999px;
  background: var(--surface-tint);
  border: 1px solid var(--border);
  color: var(--muted);
  font-size: 0.72rem;
  font-weight: 700;
  white-space: nowrap;
}}

.section-body {{
  padding: 1.25rem 1.35rem 0.55rem;
}}

.dash-stats {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 0.95rem;
  margin: 1rem 0 1.35rem;
}}

.dash-stat {{
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: linear-gradient(180deg, var(--surface) 0%, var(--surface-alt) 100%);
  padding: 1.15rem 1.2rem;
  box-shadow: var(--shadow-sm);
  min-height: 120px;
}}

.dash-stat-accent {{
  border-color: var(--primary);
  box-shadow: 0 0 0 1px var(--ring), var(--shadow-md);
}}

.dash-stat-label {{
  margin-bottom: 0.55rem;
  color: var(--muted);
  font-size: 0.73rem;
  font-weight: 800;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}}

.dash-stat-value {{
  color: var(--text);
  font-family: "Space Grotesk", "Plus Jakarta Sans", sans-serif;
  font-size: 1.55rem;
  font-weight: 700;
  line-height: 1.1;
}}

.dash-stat-sub {{
  margin-top: 0.45rem;
  color: var(--text-soft);
  font-size: 0.8rem;
}}

.dash-stat {{
  transition: transform var(--transition), box-shadow var(--transition), border-color var(--transition);
}}

.dash-stat:hover {{
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
  border-color: var(--border-strong);
}}

.status-badge {{
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.3rem 0.55rem;
  border-radius: 999px;
  font-size: 0.68rem;
  font-weight: 800;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}}

.status-badge-green {{
  background: var(--primary-soft);
  color: var(--primary);
}}

.status-badge-orange {{
  background: var(--warning-soft);
  color: var(--warning);
}}

.status-badge-red {{
  background: var(--danger-soft);
  color: var(--danger);
}}

.stepper {{
  display: flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.2rem 0 0.35rem;
  overflow-x: auto;
  scrollbar-width: none;
}}

.stepper::-webkit-scrollbar {{
  display: none;
}}

.stepper-item {{
  display: flex;
  align-items: center;
  gap: 0.55rem;
  min-width: max-content;
  padding: 0.4rem 0.55rem;
  border-radius: var(--radius-sm);
}}

.stepper-node {{
  width: 1.85rem;
  height: 1.85rem;
  border-radius: 0.8rem;
  border: 1px solid var(--sidebar-border);
  background: transparent;
  color: var(--muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.7rem;
  font-weight: 800;
}}

.stepper-name {{
  color: var(--muted);
  font-size: 0.73rem;
  font-weight: 700;
  white-space: nowrap;
}}

.stepper-arrow {{
  color: var(--muted);
  font-size: 0.8rem;
  opacity: 0.7;
}}

.stepper-item.completed .stepper-node {{
  border-color: var(--primary);
  background: var(--primary-soft);
  color: var(--primary);
}}

.stepper-item.completed .stepper-name {{
  color: var(--sidebar-text);
}}

.stepper-item.active {{
  background: rgba(255, 255, 255, 0.05);
}}

.stepper-item.active .stepper-node {{
  border-color: var(--primary);
  background: var(--primary);
  color: {button_text};
}}

.stepper-item.active .stepper-name {{
  color: var(--sidebar-text);
}}

[data-testid="stFileUploaderDropzone"] {{
  background: var(--surface-alt);
  border: 1.5px dashed var(--border-strong);
  border-radius: var(--radius-md);
  min-height: 184px;
  padding: 1.2rem 1.1rem;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
}}

[data-testid="stFileUploaderDropzone"]:hover {{
  border-color: var(--primary);
  background: var(--primary-soft);
}}

[data-testid="stFileUploaderDropzone"] > div,
[data-testid="stFileUploaderDropzone"] section {{
  width: 100%;
}}

[data-testid="stFileUploaderDropzone"] section {{
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.7rem;
}}

[data-testid="stFileUploaderDropzone"] [data-testid="stMarkdownContainer"] p {{
  color: var(--text-soft) !important;
  font-size: 0.92rem !important;
  font-weight: 600 !important;
  text-align: center !important;
}}

[data-testid="stFileUploaderDropzone"] small {{
  color: var(--muted) !important;
  text-align: center !important;
}}

[data-testid="stFileUploaderDropzone"] button {{
  width: auto !important;
  min-width: 0 !important;
  min-height: 38px !important;
  margin: 0.1rem auto 0 !important;
  padding: 0.52rem 0.92rem !important;
  border-radius: 999px !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  box-shadow: var(--shadow-sm) !important;
}}

div[data-baseweb="input"] > div,
div[data-baseweb="select"] > div,
div[data-baseweb="textarea"] > div,
div[data-baseweb="base-input"] > div {{
  background: var(--surface) !important;
  border: 1px solid var(--border) !important;
  border-radius: 14px !important;
  box-shadow: none !important;
  min-height: 46px;
}}

div[data-baseweb="input"] > div:focus-within,
div[data-baseweb="select"] > div:focus-within,
div[data-baseweb="textarea"] > div:focus-within,
div[data-baseweb="base-input"] > div:focus-within {{
  border-color: var(--primary) !important;
  box-shadow: 0 0 0 4px var(--ring) !important;
}}

input, textarea {{
  color: var(--text) !important;
}}

label[data-testid="stWidgetLabel"] p,
.stNumberInput label p,
.stSelectbox label p,
.stTextInput label p,
.stDateInput label p,
.stTextArea label p,
.stMultiSelect label p,
.stFileUploader label p {{
  color: var(--text) !important;
  font-size: 0.88rem !important;
  font-weight: 700 !important;
}}

div.stButton > button,
div.stDownloadButton > button {{
  min-height: 42px;
  padding: 0.7rem 1rem;
  border-radius: 13px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  font-weight: 700;
  box-shadow: var(--shadow-sm);
  transition: all 0.18s ease;
}}

div.stButton > button:hover,
div.stDownloadButton > button:hover {{
  border-color: var(--border-strong);
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}}

button[kind="primary"],
[data-testid="stBaseButton-primary"] {{
  background: var(--primary) !important;
  border-color: var(--primary) !important;
  color: {button_text} !important;
}}

button[kind="primary"]:hover,
[data-testid="stBaseButton-primary"]:hover {{
  background: var(--primary-hover) !important;
  border-color: var(--primary-hover) !important;
}}

button[kind="secondary"],
[data-testid="stBaseButton-secondary"] {{
  background: var(--surface) !important;
  border-color: var(--border) !important;
  color: var(--text) !important;
}}

[data-testid="stMetric"] {{
  padding: 1rem 1.1rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: linear-gradient(180deg, var(--surface) 0%, var(--surface-alt) 100%);
  box-shadow: var(--shadow-sm);
}}

[data-testid="stMetricLabel"] {{
  color: var(--muted) !important;
  font-weight: 800 !important;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}}

[data-testid="stMetricValue"] {{
  color: var(--text) !important;
  font-family: "Space Grotesk", "Plus Jakarta Sans", sans-serif;
  font-weight: 700 !important;
}}

[data-testid="stExpander"] {{
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-md) !important;
  background: linear-gradient(180deg, var(--surface) 0%, var(--surface-alt) 100%) !important;
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}}

[data-testid="stExpander"] details summary {{
  padding: 0.95rem 1rem !important;
  background: transparent !important;
  color: var(--text) !important;
  font-weight: 700 !important;
}}

[data-testid="stExpander"] details > div {{
  border-top: 1px solid var(--border) !important;
}}

form[data-testid="stForm"] {{
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 1.1rem 1rem 0.25rem;
  background: var(--surface-alt);
}}

[data-testid="stTabs"] [data-baseweb="tab-list"] {{
  gap: 0.5rem;
  padding-bottom: 0.2rem;
}}

[data-testid="stTabs"] button[role="tab"] {{
  height: 40px;
  border-radius: 999px;
  border: 1px solid transparent;
  padding: 0 1rem;
  background: transparent;
  color: var(--muted);
  font-weight: 700;
}}

[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {{
  background: var(--surface);
  border-color: var(--border);
  color: var(--text);
  box-shadow: var(--shadow-sm);
}}

[data-testid="stAlert"] {{
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
}}

[data-testid="stAlert"][kind="success"] {{
  background: var(--primary-soft);
  border-color: rgba(29, 122, 99, 0.28);
}}

[data-testid="stAlert"][kind="warning"] {{
  background: var(--warning-soft);
  border-color: rgba(183, 121, 31, 0.24);
}}

[data-testid="stAlert"][kind="error"] {{
  background: var(--danger-soft);
  border-color: rgba(194, 65, 77, 0.24);
}}

[data-testid="stDataFrame"],
.stTable {{
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
  background: var(--surface);
  box-shadow: var(--shadow-sm);
}}

[data-testid="stDataFrame"] [role="grid"],
.stTable table {{
  color: var(--text);
}}

[data-testid="stDataFrame"] [role="columnheader"],
.stTable thead tr th {{
  background: var(--surface-tint) !important;
  color: var(--text) !important;
  font-weight: 800 !important;
  border-bottom: 1px solid var(--border) !important;
}}

[data-testid="stDataFrame"] [role="gridcell"],
.stTable tbody tr td {{
  border-top: 1px solid rgba(0, 0, 0, 0.04) !important;
}}

[data-testid="stSidebar"] div[data-baseweb="select"] > div,
[data-testid="stSidebar"] div[data-baseweb="input"] > div {{
  background: rgba(255, 255, 255, 0.04) !important;
  border-color: var(--sidebar-border) !important;
}}

[data-testid="stSidebar"] div.stButton > button,
[data-testid="stSidebar"] div.stDownloadButton > button {{
  width: 100%;
}}

[data-testid="stSidebar"] [role="radiogroup"] {{
  gap: 0.45rem;
}}

[data-testid="stSidebar"] [role="radiogroup"] label {{
  border: 1px solid var(--sidebar-border);
  border-radius: 12px;
  padding: 0.55rem 0.65rem;
  background: rgba(255, 255, 255, 0.03);
}}

[data-testid="stSidebar"] [role="radiogroup"] label:hover {{
  border-color: var(--primary);
}}

[data-testid="stSidebar"] .stToggle {{
  padding: 0.35rem 0.1rem 0.6rem;
}}

.adapter-mapper-preview {{
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface-alt);
  padding: 1rem;
}}

hr,
[data-testid="stHorizontalBlock"] + hr {{
  border: none !important;
  height: 1px !important;
  background: linear-gradient(90deg, transparent 0%, var(--border-strong) 20%, var(--border-strong) 80%, transparent 100%) !important;
  margin: 1rem 0 !important;
}}

code, pre {{
  border-radius: 12px !important;
}}

* {{
  scrollbar-width: thin;
  scrollbar-color: var(--border-strong) transparent;
}}

::-webkit-scrollbar {{
  width: 8px;
  height: 8px;
}}

::-webkit-scrollbar-track {{
  background: transparent;
}}

::-webkit-scrollbar-thumb {{
  background: var(--border-strong);
  border-radius: 999px;
}}

.app-footer {{
  margin-top: 2.4rem;
  padding: 1.2rem 0 0.3rem;
  border-top: 1px solid var(--border);
  text-align: center;
}}

.app-footer-text {{
  color: var(--muted);
  font-size: 0.76rem;
  font-weight: 600;
}}

.empty-state {{
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  padding: 2.75rem 1.5rem;
  text-align: center;
  border: 1.5px dashed var(--border);
  border-radius: var(--radius-md);
  background: var(--surface-alt);
  min-height: 160px;
}}

.empty-state-icon {{
  font-size: 2.25rem;
  opacity: 0.45;
  line-height: 1;
}}

.empty-state-title {{
  color: var(--text-soft);
  font-size: 0.97rem;
  font-weight: 700;
  margin: 0;
}}

.empty-state-sub {{
  color: var(--muted);
  font-size: 0.84rem;
  max-width: 340px;
  margin: 0;
}}

@media (max-width: 960px) {{
  .main .block-container {{
    padding-left: 1rem;
    padding-right: 1rem;
  }}

  .page-header {{
    padding: 1.35rem 1.2rem 1.25rem;
    border-radius: 20px;
  }}

  .section-head {{
    flex-direction: column;
    align-items: flex-start;
  }}

  .section-body {{
    padding: 1rem 1rem 0.45rem;
  }}

  .dash-stats {{
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }}
}}

@media (max-width: 640px) {{
  .dash-stats {{
    grid-template-columns: 1fr;
  }}

  .page-header-title {{
    font-size: 1.75rem;
  }}
}}
</style>
        """,
        unsafe_allow_html=True,
    )


_SOLAR_ICON_SVG = """<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="12" cy="12" r="4.5" stroke="currentColor" stroke-width="1.8"/>
  <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.93 4.93l2.12 2.12M16.95 16.95l2.12 2.12M4.93 19.07l2.12-2.12M16.95 7.05l2.12-2.12" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
</svg>"""


def render_sidebar_brand(company_name: str = "SolarBudget", tagline: str = "Internal Tool") -> None:
    st.markdown(
        f"""
<div class="sidebar-brand">
  <div class="sidebar-brand-icon">{_SOLAR_ICON_SVG}</div>
  <div class="sidebar-brand-text">
    <span class="sidebar-brand-name">{escape(company_name)}</span>
    <span class="sidebar-brand-tag">{escape(tagline)}</span>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_session(label: str = "Session active") -> None:
    st.markdown(
        f"""
<div class="sidebar-session">
  <span class="sidebar-session-dot"></span>
  <span class="sidebar-session-text">{escape(label)}</span>
</div>
        """,
        unsafe_allow_html=True,
    )


def page_header(title: str, subtitle: str = "", eyebrow: str = "Solar Budget Dashboard") -> None:
    subtitle_parts = [part.strip() for part in str(subtitle or "").split("|") if part.strip()]
    lead = subtitle_parts[0] if subtitle_parts else ""
    pills = subtitle_parts[1:] if len(subtitle_parts) > 1 else []
    if not lead and pills:
        lead, pills = pills[0], pills[1:]

    pills_html = ""
    if pills:
        pills_html = '<div class="page-header-pills">' + "".join(
            f'<span class="page-header-pill">{escape(part)}</span>' for part in pills
        ) + "</div>"

    lead_html = f'<div class="page-header-sub">{escape(lead)}</div>' if lead else ""

    st.markdown(
        f"""
<div class="page-header">
  <div class="page-header-eyebrow">{escape(eyebrow)}</div>
  <div class="page-header-title">{escape(str(title))}</div>
  {lead_html}
  {pills_html}
</div>
        """,
        unsafe_allow_html=True,
    )


def render_step_progress(step_flow: list[tuple[str, str]], current_step: str, completion: dict[str, bool]) -> None:
    total = len(step_flow)
    done = sum(1 for code, _ in step_flow if completion.get(code, False))

    items_html: list[str] = []
    for idx, (code, name) in enumerate(step_flow):
        classes = "stepper-item"
        if completion.get(code, False):
            classes += " completed"
        if code == current_step:
            classes += " active"

        check = "&#10003;" if completion.get(code, False) and code != current_step else escape(str(code))

        item_html = (
            f'<div class="{classes}" title="{escape(str(name))}">'
            f'<span class="stepper-node">{check}</span>'
            f'<span class="stepper-name">{escape(str(name))}</span>'
            "</div>"
        )
        items_html.append(item_html)
        if idx < total - 1:
            items_html.append('<span class="stepper-arrow">&#8250;</span>')

    st.markdown(f'<div class="stepper">{"".join(items_html)}</div>', unsafe_allow_html=True)
    if done > 0:
        st.caption(f"{done}/{total} concluido(s)")


def render_dash_stats(stats: list[dict]) -> None:
    cards_html = []
    for stat in stats:
        accent = " dash-stat-accent" if stat.get("accent") else ""
        sub_html = f'<div class="dash-stat-sub">{escape(str(stat.get("sub", "")))}</div>' if stat.get("sub") else ""
        cards_html.append(
            f'<div class="dash-stat{accent}">'
            f'<div class="dash-stat-label">{escape(str(stat["label"]))}</div>'
            f'<div class="dash-stat-value">{escape(str(stat["value"]))}</div>'
            f"{sub_html}"
            "</div>"
        )
    st.markdown(f'<div class="dash-stats">{"".join(cards_html)}</div>', unsafe_allow_html=True)


def render_status_badge(text: str, variant: str = "green") -> str:
    return f'<span class="status-badge status-badge-{variant}">{escape(text)}</span>'


def section_start(title: str, chip: str = "", solid: bool = False) -> None:
    card_class = "section-card section-card-solid" if solid else "section-card"
    chip_html = f'<span class="section-chip">{escape(str(chip))}</span>' if str(chip).strip() else ""
    st.markdown(
        f"""
<div class="{card_class}">
  <div class="section-head">
    <div class="section-title">{escape(str(title))}</div>
    {chip_html}
  </div>
  <div class="section-body">
        """,
        unsafe_allow_html=True,
    )


def section_end() -> None:
    st.markdown(
        """
</div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_footer(company: str = "SolarBudget") -> None:
    from datetime import datetime

    year = datetime.now().year
    st.markdown(
        f"""
<div class="app-footer">
  <div class="app-footer-text">
    &copy; {year} {escape(company)} &middot; Ferramenta interna de orcamento solar &middot; v2.0
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_empty_state(icon: str, title: str, sub: str = "") -> None:
    sub_html = f'<p class="empty-state-sub">{escape(sub)}</p>' if sub else ""
    st.markdown(
        f'<div class="empty-state">'
        f'<div class="empty-state-icon">{icon}</div>'
        f'<p class="empty-state-title">{escape(title)}</p>'
        f"{sub_html}"
        "</div>",
        unsafe_allow_html=True,
    )
