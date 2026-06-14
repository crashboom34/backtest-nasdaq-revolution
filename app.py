"""
Backtest Pro — Interface Streamlit
Dashboard inspiré de ProRealTime
"""

import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go
import pandas as pd
import numpy as np
import importlib.util
import glob
import os
import subprocess
import json
import math
import datetime
import urllib.parse
import html
import history_store as hs
import optimization_store as opt_store
from job_launcher import launch_optimizer_job
from optimizer import (
    ParamRange, ScoreWeights, FilterConfig, TrainTestConfig,
    OptimizationConfig, count_combinations, benchmark_speed,
    estimate_duration, format_duration,
)
from report_generator import generate_report
from path_resolver import (
    DEFAULT_ASSET, DEFAULT_TIMEFRAME,
    list_available_assets, list_available_timeframes,
    resolve_data_csv, to_relative_path,
)

# ── Config page ───────────────────────────────────────────────────
st.set_page_config(
    page_title="Backtest Pro",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Design System (Linear / Vercel inspired) ─────────────────────
BG          = "#08090c"   # near-black background
BG_ALT      = "#0c0d11"   # subtle alt section
CARD_BG     = "#0f1015"   # cards primary
CARD_BG2    = "#13141a"   # cards hover/secondary
BORDER      = "rgba(255,255,255,0.06)"
BORDER_HOV  = "rgba(255,255,255,0.12)"
TEXT        = "#e4e4e7"   # zinc-200
TEXT_DIM    = "#71717a"   # zinc-500
TEXT_MUTED  = "#52525b"   # zinc-600
GREEN       = "#10b981"   # emerald-500
GREEN_SOFT  = "rgba(16,185,129,0.12)"
RED         = "#f43f5e"   # rose-500
RED_SOFT    = "rgba(244,63,94,0.12)"
ACCENT      = "#6366f1"   # indigo-500
ACCENT_HOV  = "#7c7dff"
ACCENT_SOFT = "rgba(99,102,241,0.15)"
PURPLE      = "#a855f7"

# ── Bloc 1 : fonts Google + variables CSS (court, interpolation Python) ──
st.markdown(f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg:           {BG};
    --bg-alt:       {BG_ALT};
    --card:         {CARD_BG};
    --card-2:       {CARD_BG2};
    --border:       {BORDER};
    --border-hov:   {BORDER_HOV};
    --text:         {TEXT};
    --text-dim:     {TEXT_DIM};
    --text-muted:   {TEXT_MUTED};
    --green:        {GREEN};
    --green-soft:   {GREEN_SOFT};
    --red:          {RED};
    --red-soft:     {RED_SOFT};
    --accent:       {ACCENT};
    --accent-hov:   {ACCENT_HOV};
    --accent-soft:  {ACCENT_SOFT};
  }}
</style>
""", unsafe_allow_html=True)

# ── Bloc 2 : tout le CSS (statique, pas de f-string, utilise les variables) ──
st.markdown("""
<style>
  /* ── Reset / Global ── */
  html, body, [data-testid="stApp"] {
    background-color: var(--bg);
    color: var(--text);
    font-family: 'Inter', system-ui, -apple-system, sans-serif;
    font-feature-settings: 'cv02','cv03','cv04','cv11','ss01';
    -webkit-font-smoothing: antialiased;
  }
  [data-testid="stSidebar"] {
    background-color: var(--bg-alt);
    border-right: 1px solid var(--border);
  }
  [data-testid="stSidebar"] * { color: var(--text) !important; }

  /* ── Sidebar sections ── */
  .sidebar-section {
    color: var(--text-muted);
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    padding: 16px 0 8px 0;
    margin-top: 4px;
    border-top: 1px solid var(--border);
  }
  .sidebar-section:first-of-type { border-top: none; margin-top: 0; }

  /* ── Metric cards ── */
  .metric-card {
    background: linear-gradient(180deg, var(--card) 0%, var(--bg-alt) 100%);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px 18px;
    text-align: left;
    height: 100%;
    transition: border-color 0.15s ease, transform 0.15s ease;
    position: relative;
    overflow: hidden;
  }
  .metric-card:hover { border-color: var(--border-hov); }
  .metric-card::before {
    content: "";
    position: absolute;
    inset: 0;
    background: radial-gradient(600px at 0% 0%, rgba(99,102,241,0.06), transparent 40%);
    pointer-events: none;
  }
  .metric-label {
    color: var(--text-dim);
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.3px;
    margin-bottom: 8px;
    position: relative;
  }
  .metric-value {
    font-size: 26px;
    font-weight: 700;
    line-height: 1.1;
    letter-spacing: -0.5px;
    position: relative;
    font-variant-numeric: tabular-nums;
  }
  .metric-sub {
    color: var(--text-muted);
    font-size: 11.5px;
    margin-top: 6px;
    font-weight: 500;
    position: relative;
    font-variant-numeric: tabular-nums;
  }
  .green  { color: var(--green); }
  .red    { color: var(--red); }
  .white  { color: #f4f4f5; }
  .accent { color: var(--accent); }

  /* ── Header dashboard ── */
  .dash-header {
    background: linear-gradient(135deg, var(--card) 0%, var(--bg-alt) 100%);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 20px 28px;
    margin-bottom: 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    position: relative;
    overflow: hidden;
  }
  .dash-header::before {
    content: "";
    position: absolute;
    inset: 0;
    background: radial-gradient(1000px at 100% 0%, var(--accent-soft), transparent 50%);
    pointer-events: none;
  }
  .dash-title {
    font-size: 17px;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: -0.3px;
    position: relative;
  }
  .dash-subtitle {
    font-size: 12.5px;
    color: var(--text-dim);
    margin-top: 4px;
    font-variant-numeric: tabular-nums;
    position: relative;
  }
  .dash-gain-big {
    font-size: 34px;
    font-weight: 800;
    text-align: right;
    letter-spacing: -1px;
    line-height: 1;
    position: relative;
    font-variant-numeric: tabular-nums;
  }

  /* ── Stats table ── */
  .stats-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 9px 0;
    border-bottom: 1px solid var(--border);
    font-size: 13px;
  }
  .stats-row:last-child { border-bottom: none; }
  .stats-key   { color: var(--text-dim); font-weight: 500; }
  .stats-val   { font-weight: 600; color: var(--text); font-variant-numeric: tabular-nums; }

  /* ── Section titles ── */
  .section-title {
    color: var(--text-dim);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    margin-bottom: 12px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 8px;
  }

  /* ── Buttons ── */
  .stButton > button {
    background: var(--accent);
    color: white;
    border: 1px solid var(--accent);
    border-radius: 10px;
    font-weight: 600;
    font-size: 13.5px;
    padding: 11px 0;
    width: 100%;
    letter-spacing: 0.1px;
    transition: all 0.15s ease;
    box-shadow: 0 1px 0 0 rgba(255,255,255,0.06) inset;
    font-family: 'Inter', sans-serif;
  }
  .stButton > button:hover {
    background: var(--accent-hov);
    border-color: var(--accent-hov);
    transform: translateY(-1px);
    box-shadow: 0 4px 16px rgba(99,102,241,0.25);
  }
  .stButton > button:focus { box-shadow: 0 0 0 3px var(--accent-soft); outline: none; }

  /* ── Inputs ── */
  div[data-testid="stNumberInput"] input,
  div[data-testid="stTextInput"] input {
    background: var(--card) !important;
    border: 1px solid var(--border) !important;
    color: var(--text) !important;
    border-radius: 8px !important;
    font-size: 13px !important;
    font-family: 'Inter', sans-serif !important;
    font-variant-numeric: tabular-nums !important;
    transition: border-color 0.15s ease !important;
  }
  div[data-testid="stNumberInput"] input:focus,
  div[data-testid="stTextInput"] input:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px var(--accent-soft) !important;
  }
  .stCheckbox label { color: var(--text) !important; font-size: 13px !important; }
  .stSlider [data-testid="stTickBar"] { display: none; }
  div[data-testid="stNumberInput"] label,
  div[data-testid="stSlider"] label,
  div[data-testid="stSelectbox"] label {
    color: var(--text-dim) !important;
    font-size: 12px !important;
    font-weight: 500 !important;
  }

  /* ── Selectbox ── */
  div[data-testid="stSelectbox"] > div[data-baseweb="select"] > div {
    background: var(--card) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
  }

  /* ── Hide chrome ── */
  #MainMenu, footer, header { visibility: hidden; }
  .block-container { padding-top: 1.5rem; padding-bottom: 1.5rem; max-width: 100%; }

  /* ── Scrollbars ── */
  ::-webkit-scrollbar { width: 10px; height: 10px; }
  ::-webkit-scrollbar-track { background: var(--bg); }
  ::-webkit-scrollbar-thumb { background: var(--card-2); border-radius: 5px; }
  ::-webkit-scrollbar-thumb:hover { background: var(--border-hov); }

  /* ── Tabs ── */
  [data-testid="stTabs"] { margin-top: -4px; }
  div[data-baseweb="tab-list"] {
    border-bottom: 1px solid var(--border) !important;
    gap: 4px !important;
  }
  button[data-baseweb="tab"] {
    background: transparent !important;
    color: var(--text-dim) !important;
    font-weight: 500 !important;
    font-size: 13.5px !important;
    border-bottom: 2px solid transparent !important;
    padding: 12px 18px !important;
    transition: color 0.15s ease, border-color 0.15s ease !important;
    font-family: 'Inter', sans-serif !important;
  }
  button[data-baseweb="tab"]:hover { color: var(--text) !important; }
  button[data-baseweb="tab"][aria-selected="true"] {
    color: white !important;
    border-bottom: 2px solid var(--accent) !important;
    font-weight: 600 !important;
  }
  [data-testid="stTabContent"] { padding-top: 20px; }

  /* ── Step cards ── */
  .step-card {
    background: linear-gradient(180deg, var(--card) 0%, var(--bg-alt) 100%);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 22px 18px;
    text-align: center;
    height: 100%;
    transition: border-color 0.15s ease, transform 0.15s ease;
  }
  .step-card:hover { border-color: var(--border-hov); transform: translateY(-2px); }
  .step-num {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px; height: 32px;
    background: var(--accent-soft);
    border: 1px solid var(--accent);
    border-radius: 50%;
    color: var(--accent);
    font-size: 13px;
    font-weight: 700;
    margin-bottom: 12px;
  }
  .step-title {
    color: white;
    font-size: 13.5px;
    font-weight: 600;
    margin-bottom: 6px;
    letter-spacing: -0.1px;
  }
  .step-desc {
    color: var(--text-dim);
    font-size: 12px;
    line-height: 1.55;
  }

  /* ── Text area (ProRealCode input) ── */
  .stTextArea textarea {
    background: var(--bg) !important;
    border: 1px solid var(--border) !important;
    color: var(--text) !important;
    font-family: 'JetBrains Mono', 'Consolas', monospace !important;
    font-size: 12px !important;
    border-radius: 10px !important;
    line-height: 1.6 !important;
    transition: border-color 0.15s ease !important;
  }
  .stTextArea textarea:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px var(--accent-soft) !important;
  }
  .stTextArea label { color: var(--text-dim) !important; font-size: 12px !important; }

  /* ── Code blocks ── */
  pre, code { font-family: 'JetBrains Mono', 'Consolas', monospace !important; }
  [data-testid="stCodeBlock"] { border-radius: 10px !important; }
  [data-testid="stCodeBlock"] code { font-size: 11.5px !important; }

  /* ── Outlined button (Open Claude.ai) ── */
  .open-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    color: var(--text) !important;
    border: 1px solid var(--border-hov);
    border-radius: 10px;
    padding: 11px 20px;
    font-weight: 600;
    font-size: 13.5px;
    cursor: pointer;
    text-decoration: none !important;
    transition: all 0.15s ease;
    width: 100%;
    box-sizing: border-box;
    font-family: 'Inter', sans-serif;
  }
  .open-btn:hover {
    background: var(--card);
    border-color: var(--accent);
    color: var(--accent) !important;
    transform: translateY(-1px);
  }

  /* ── Historique ── */
  .history-card {
    background: linear-gradient(180deg, var(--card) 0%, var(--bg-alt) 100%);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 20px 24px;
    margin-bottom: 12px;
    transition: border-color 0.15s ease, transform 0.15s ease;
    position: relative;
    overflow: hidden;
  }
  .history-card:hover { border-color: var(--border-hov); }
  .history-card::before {
    content: "";
    position: absolute;
    inset: 0;
    background: radial-gradient(600px at 100% 0%, rgba(99,102,241,0.04), transparent 50%);
    pointer-events: none;
  }
  .h-name {
    font-size: 15px;
    font-weight: 600;
    color: white;
    letter-spacing: -0.2px;
    margin-bottom: 2px;
  }
  .h-meta {
    font-size: 11.5px;
    color: var(--text-dim);
    font-variant-numeric: tabular-nums;
  }
  .h-stat { display: flex; flex-direction: column; gap: 2px; }
  .h-stat-label {
    font-size: 10.5px;
    color: var(--text-muted);
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .h-stat-value {
    font-size: 15px;
    font-weight: 600;
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  .h-badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: 999px;
    background: var(--accent-soft);
    color: var(--accent);
    border: 1px solid rgba(99,102,241,0.25);
  }
  .h-badge-green { background: var(--green-soft); color: var(--green); border-color: rgba(16,185,129,0.25); }
  .h-badge-red   { background: var(--red-soft);   color: var(--red);   border-color: rgba(244,63,94,0.25); }
  .h-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 80px 20px;
    text-align: center;
    color: var(--text-dim);
    border: 1px dashed var(--border);
    border-radius: 14px;
    background: var(--card);
  }

  /* ── Toolbar buttons (secondary) ── */
  div[data-testid="column"] .stButton > button[kind="secondary"] {
    background: transparent;
    color: var(--text-dim);
    border: 1px solid var(--border);
    font-weight: 500;
    font-size: 12px;
    padding: 7px 0;
    box-shadow: none;
  }
  div[data-testid="column"] .stButton > button[kind="secondary"]:hover {
    background: var(--card);
    color: var(--text);
    border-color: var(--border-hov);
    transform: none;
    box-shadow: none;
  }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def fmt_money(v, sign=True):
    prefix = "+" if (sign and v > 0) else ""
    return f"{prefix}{v:,.2f} $"

def fmt_pct(v, sign=True):
    prefix = "+" if (sign and v > 0) else ""
    return f"{prefix}{v:.2f} %"

def color_cls(v):
    return "green" if v >= 0 else "red"

def card(label, value, color="white", sub=""):
    return f"""
    <div class="metric-card">
      <div class="metric-label">{label}</div>
      <div class="metric-value {color}">{value}</div>
      {"<div class='metric-sub'>" + sub + "</div>" if sub else ""}
    </div>"""

def plotly_cfg():
    return dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT, family="Inter, sans-serif", size=11),
        margin=dict(l=8, r=8, t=28, b=8),
        xaxis=dict(showgrid=False, zeroline=False, color=TEXT_DIM, tickfont=dict(size=10)),
        yaxis=dict(showgrid=True, gridcolor=BORDER, zeroline=False, color=TEXT_DIM, tickfont=dict(size=10)),
    )

def make_donut(value, max_val, color_on, color_off, center_text, title):
    safe_val = max(0, min(value, max_val))
    fig = go.Figure(go.Pie(
        values=[safe_val, max(0.001, max_val - safe_val)],
        hole=0.72,
        marker=dict(colors=[color_on, color_off], line=dict(width=0)),
        showlegend=False,
        textinfo="none",
        direction="clockwise",
        sort=False,
    ))
    fig.add_annotation(
        text=center_text,
        x=0.5, y=0.5,
        showarrow=False,
        font=dict(size=20, color="white", family="Inter"),
    )
    cfg = plotly_cfg()
    cfg["margin"] = dict(l=4, r=4, t=30, b=4)
    cfg["title"]  = dict(text=title, font=dict(size=11, color=TEXT_DIM), x=0.5, y=0.96)
    cfg["height"] = 170
    fig.update_layout(**cfg)
    return fig

def make_equity_curve(equity_df, initial_capital):
    y = equity_df["capital"].values.astype(float) - initial_capital
    x = list(range(len(y)))
    pos_y = np.where(y >= 0, y, 0)
    neg_y = np.where(y <  0, y, 0)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x, y=pos_y,
        fill="tozeroy", mode="none",
        fillcolor="rgba(0,208,132,0.15)",
        name="",
    ))
    fig.add_trace(go.Scatter(
        x=x, y=neg_y,
        fill="tozeroy", mode="none",
        fillcolor="rgba(255,64,96,0.15)",
        name="",
    ))
    line_color = GREEN if y[-1] >= 0 else RED
    fig.add_trace(go.Scatter(
        x=x, y=y,
        mode="lines",
        line=dict(color=line_color, width=1.5),
        name="",
        hovertemplate="%{y:+,.2f} $<extra></extra>",
    ))
    cfg = plotly_cfg()
    cfg["margin"] = dict(l=8, r=8, t=10, b=24)
    cfg["height"] = 200
    cfg["showlegend"] = False
    cfg["yaxis"]["tickprefix"] = "$"
    fig.update_layout(**cfg)
    return fig

def make_dow_chart(dow_pnl):
    order  = ["Lun", "Mar", "Mer", "Jeu", "Ven"]
    vals   = [dow_pnl.get(d, 0) for d in order]
    colors = [GREEN if v >= 0 else RED for v in vals]

    fig = go.Figure(go.Bar(
        y=order,
        x=vals,
        orientation="h",
        marker=dict(color=colors, line=dict(width=0)),
        text=[fmt_money(v) for v in vals],
        textposition="auto",
        textfont=dict(size=10, color="white"),
        hovertemplate="%{y}: %{x:+,.2f} $<extra></extra>",
    ))
    cfg = plotly_cfg()
    cfg["margin"] = dict(l=8, r=8, t=28, b=8)
    cfg["height"] = 200
    cfg["title"]  = dict(text="Répartition / Jour de semaine", font=dict(size=11, color=TEXT_DIM), x=0.5)
    cfg["yaxis"]["showgrid"] = False
    cfg["xaxis"]["tickprefix"] = "$"
    fig.update_layout(**cfg)
    return fig

def make_yearly_chart(yearly_pnl):
    years  = sorted(yearly_pnl.keys())
    vals   = [yearly_pnl[y] for y in years]
    colors = [GREEN if v >= 0 else RED for v in vals]

    fig = go.Figure(go.Bar(
        x=[str(y) for y in years],
        y=vals,
        marker=dict(color=colors, line=dict(width=0)),
        text=[fmt_money(v, sign=True) for v in vals],
        textposition="auto",
        textfont=dict(size=10, color="white"),
        hovertemplate="%{x}: %{y:+,.2f} $<extra></extra>",
    ))
    cfg = plotly_cfg()
    cfg["margin"] = dict(l=8, r=8, t=28, b=8)
    cfg["height"] = 200
    cfg["title"]  = dict(text="Performance brute / Année", font=dict(size=11, color=TEXT_DIM), x=0.5)
    cfg["yaxis"]["tickprefix"] = "$"
    fig.update_layout(**cfg)
    return fig

def make_dd_chart(equity_df):
    dd = equity_df["drawdown"].values.astype(float)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=list(range(len(dd))), y=-dd,
        fill="tozeroy", mode="none",
        fillcolor="rgba(255,64,96,0.25)",
        name="",
    ))
    fig.add_trace(go.Scatter(
        x=list(range(len(dd))), y=-dd,
        mode="lines", line=dict(color=RED, width=1),
        hovertemplate="DD: %{y:.2f}%<extra></extra>",
    ))
    cfg = plotly_cfg()
    cfg["margin"] = dict(l=8, r=8, t=10, b=24)
    cfg["height"] = 120
    cfg["showlegend"] = False
    cfg["yaxis"]["ticksuffix"] = "%"
    fig.update_layout(**cfg)
    return fig


# ═══════════════════════════════════════════════════════════════════
# CHARGEMENT DES STRATÉGIES
# ═══════════════════════════════════════════════════════════════════

@st.cache_data
def load_csv():
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "nasdaq_3m.csv")
    if not os.path.exists(path):
        return None
    from engine import load_data
    return load_data(path)

def load_strategies():
    base  = os.path.dirname(os.path.abspath(__file__))
    files = glob.glob(os.path.join(base, "strategies", "*.py"))
    strats = {}
    for f in files:
        if f.endswith("__init__.py"):
            continue
        name = os.path.splitext(os.path.basename(f))[0]
        spec = importlib.util.spec_from_file_location(name, f)
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        strats[mod.STRATEGY_NAME] = mod
    return strats


# ═══════════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════════

def build_sidebar(strategies):
    with st.sidebar:
        st.markdown("## 📈 Backtest Pro")
        st.markdown(f"<div style='color:{TEXT_DIM};font-size:12px;margin-bottom:16px'>Moteur ProRealCode → Python</div>", unsafe_allow_html=True)

        # Sélection stratégie
        strategy_name = st.selectbox("Stratégie", list(strategies.keys()), key="sel_strat")
        mod = strategies[strategy_name]

        # ── Paramètres globaux ──────────────────────────────
        st.markdown("<div class='sidebar-section'>⚙️ Paramètres Globaux</div>", unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            initial_capital = st.number_input("Capital ($)", value=10000, step=1000, min_value=100)
        with col2:
            spread = st.number_input("Spread (pts)", value=1.0, step=0.5, min_value=0.0, format="%.1f")

        col1, col2 = st.columns(2)
        with col1:
            slip_in  = st.number_input("Slip. entrée", value=0.5, step=0.1, min_value=0.0, format="%.1f")
        with col2:
            slip_out = st.number_input("Slip. sortie", value=0.5, step=0.1, min_value=0.0, format="%.1f")

        # ── Paramètres stratégie ────────────────────────────
        params = dict(mod.DEFAULT_PARAMS)
        schema = mod.PARAM_SCHEMA

        for section, fields in schema.items():
            st.markdown(f"<div class='sidebar-section'>{section}</div>", unsafe_allow_html=True)
            for key, meta in fields.items():
                typ = meta["type"]
                lbl = meta["label"]
                val = params[key]

                if typ == "bool":
                    params[key] = st.checkbox(lbl, value=val, key=f"p_{key}")
                elif typ == "int":
                    params[key] = st.number_input(
                        lbl, value=int(val),
                        min_value=meta.get("min", 0),
                        max_value=meta.get("max", 9999),
                        step=1, key=f"p_{key}",
                    )
                elif typ == "float":
                    params[key] = st.number_input(
                        lbl, value=float(val),
                        min_value=float(meta.get("min", 0.0)),
                        max_value=float(meta.get("max", 9999.0)),
                        step=float(meta.get("step", 0.1)),
                        format="%.2f", key=f"p_{key}",
                    )

        st.markdown("<br>", unsafe_allow_html=True)
        run_btn = st.button("▶  LANCER LE BACKTEST", width="stretch")

    return mod, params, initial_capital, spread, slip_in, slip_out, run_btn


# ═══════════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════════

def render_dashboard(trades_df, equity_df, stats, strategy_name, initial_capital, params):
    s = stats
    net_usd = s["net_ret_usd"]
    net_pct = s["net_ret_pct"]
    color   = color_cls(net_usd)

    # ── Header ────────────────────────────────────────────────
    first_date = pd.to_datetime(equity_df["date"].iloc[0], utc=True).strftime("%d %b %Y")
    last_date  = pd.to_datetime(equity_df["date"].iloc[-1], utc=True).strftime("%d %b %Y")

    st.markdown(f"""
    <div class="dash-header">
      <div>
        <div class="dash-title">📊 {strategy_name}</div>
        <div class="dash-subtitle">
          Début {first_date} [{initial_capital:,.0f} $]
          &nbsp;→&nbsp;
          Actuel {last_date} [{s['final_capital']:,.0f} $]
        </div>
      </div>
      <div class="dash-gain-big {color}">
        {fmt_money(net_usd)}
        <div style="font-size:14px;font-weight:400;text-align:right;color:{TEXT_DIM}">
          {fmt_pct(net_pct)}
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Ligne 1 : Donuts + métriques clés + jour de semaine ──
    c1, c2, c3, c4, c5 = st.columns([1.4, 1.4, 1.4, 1.4, 2.4])

    with c1:
        fig = make_donut(
            s["win_rate"], 100,
            GREEN, "#1e1e48",
            f"{s['win_rate']:.1f}%",
            "% Trades gagnants",
        )
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    with c2:
        pf = min(s["profit_factor"], 10)
        fig = make_donut(
            pf, 10,
            GREEN if pf >= 1 else RED, "#1e1e48",
            f"{s['profit_factor']:.2f}",
            "Ratio Gains / Pertes",
        )
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    with c3:
        st.markdown(card(
            "Gain moyen / trade",
            fmt_money(s["avg_win"], sign=True),
            color_cls(s["avg_win"]),
            sub=f"Perte moy. {fmt_money(s['avg_loss'])}",
        ), unsafe_allow_html=True)
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        st.markdown(card(
            "Gain max",
            fmt_money(s["biggest_win"], sign=True),
            "green",
            sub=f"Perte max {fmt_money(s['biggest_loss'])}",
        ), unsafe_allow_html=True)

    with c4:
        st.markdown(card("Trades total",    str(s["n_trades"]), "white"), unsafe_allow_html=True)
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        st.markdown(card("Gagnants",  str(s["n_win"]),  "green"), unsafe_allow_html=True)
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        st.markdown(card("Perdants",  str(s["n_loss"]), "red"),   unsafe_allow_html=True)

    with c5:
        fig = make_dow_chart(s["dow_pnl"])
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    # ── Ligne 2 : Stats détaillées + Performance annuelle ────
    c1, c2, c3 = st.columns([1.6, 1.6, 4.8])

    def stat_row(label, value, color=""):
        return f"""<div class="stats-row">
          <span class="stats-key">{label}</span>
          <span class="stats-val {'green' if color=='g' else 'red' if color=='r' else ''}">{value}</span>
        </div>"""

    with c1:
        st.markdown(f"<div class='section-title'>Répartition des trades</div>", unsafe_allow_html=True)
        st.markdown(
            stat_row("Total",      s["n_trades"]) +
            stat_row("Gagnants",   s["n_win"],  "g") +
            stat_row("Perdants",   s["n_loss"], "r") +
            stat_row("Consec. pertes max", s["max_consec_loss"]),
            unsafe_allow_html=True,
        )
        st.markdown(f"<div class='section-title' style='margin-top:14px'>Brut</div>", unsafe_allow_html=True)
        st.markdown(
            stat_row("Gain brut",     fmt_money(s["gross_win"]),  "g") +
            stat_row("Perte brute",   fmt_money(-s["gross_loss"]), "r"),
            unsafe_allow_html=True,
        )

    with c2:
        st.markdown(f"<div class='section-title'>Drawdown & Risque</div>", unsafe_allow_html=True)
        st.markdown(
            stat_row("DD max (%)",      fmt_pct(-s["max_dd_pct"]),  "r") +
            stat_row("DD max ($)",      fmt_money(-s["max_dd_usd"], sign=False), "r") +
            stat_row("DD journalier max", fmt_pct(-s["max_daily_dd"]), "r") +
            stat_row("Runup max",       fmt_money(s["max_runup"]),  "g"),
            unsafe_allow_html=True,
        )
        st.markdown(f"<div class='section-title' style='margin-top:14px'>Sessions</div>", unsafe_allow_html=True)
        st.markdown(
            stat_row("Temps marché",    f"{s['time_in_market']:.1f}%") +
            stat_row("Trades / jour",   f"{s['avg_trades_per_day']:.2f}"),
            unsafe_allow_html=True,
        )

    with c3:
        fig = make_yearly_chart(s["yearly_pnl"])
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    # ── Ligne 3 : Equity curve + Drawdown ────────────────────
    c1, c2 = st.columns([1, 1])

    with c1:
        st.markdown("<div class='section-title'>Performance brute — Transactions (equity)</div>", unsafe_allow_html=True)
        fig = make_equity_curve(equity_df, initial_capital)
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        st.markdown("<div class='section-title' style='margin-top:8px'>Drawdown historique</div>", unsafe_allow_html=True)
        fig = make_dd_chart(equity_df)
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    with c2:
        st.markdown("<div class='section-title'>Détail des trades</div>", unsafe_allow_html=True)

        disp = trades_df[[
            "date_entree", "sens", "prix_entree", "prix_sortie",
            "raison_sortie", "resultat_net", "capital_apres", "drawdown_pct",
        ]].copy()
        disp["resultat_net"]  = disp["resultat_net"].apply(lambda x: f"{x:+.2f}")
        disp["capital_apres"] = disp["capital_apres"].apply(lambda x: f"{x:,.2f}")
        disp["drawdown_pct"]  = disp["drawdown_pct"].apply(lambda x: f"{x:.2f}%")
        disp.columns = ["Entrée", "Sens", "Prix E.", "Prix S.", "Raison", "P&L net", "Capital", "DD%"]

        st.dataframe(
            disp,
            width="stretch",
            height=340,
            hide_index=True,
        )

        col1, col2 = st.columns(2)
        with col1:
            csv_trades = trades_df.to_csv(index=False).encode("utf-8")
            st.download_button("⬇ trades.csv",      csv_trades, "trades.csv",      "text/csv")
        with col2:
            csv_equity = equity_df.to_csv(index=False).encode("utf-8")
            st.download_button("⬇ equity_curve.csv", csv_equity, "equity_curve.csv","text/csv")


# ═══════════════════════════════════════════════════════════════════
# ONGLET HISTORIQUE
# ═══════════════════════════════════════════════════════════════════

def _fmt_date(iso_str):
    try:
        dt = pd.to_datetime(iso_str)
        return dt.strftime("%d %b %Y · %H:%M")
    except Exception:
        return iso_str


def render_history_tab():
    st.markdown(f"""
    <div style="margin-bottom:24px">
      <div style="font-size:22px;font-weight:700;color:white;letter-spacing:-0.4px;margin-bottom:6px">
        📂 Historique des Backtests
      </div>
      <div style="font-size:13px;color:{TEXT_DIM}">
        Tous tes backtests sont sauvegardés automatiquement. Tu peux les consulter, renommer ou supprimer.
      </div>
    </div>
    """, unsafe_allow_html=True)

    runs = hs.list_runs()

    if not runs:
        st.markdown(f"""
        <div class="h-empty">
          <div style="font-size:48px;margin-bottom:14px;opacity:0.5">📭</div>
          <div style="font-size:15px;font-weight:600;color:{TEXT};margin-bottom:6px">
            Aucun backtest sauvegardé
          </div>
          <div style="font-size:13px;max-width:380px;line-height:1.55">
            Lance un backtest depuis l'onglet <strong style="color:white">📊 Backtest</strong>
            — il apparaîtra ici automatiquement.
          </div>
        </div>
        """, unsafe_allow_html=True)
        return

    # ── Toolbar ────────────────────────────────────────────────
    c_count, c_clear = st.columns([6, 1])
    with c_count:
        st.markdown(
            f"<div style='color:{TEXT_DIM};font-size:13px;padding-top:6px'>"
            f"<strong style='color:{TEXT}'>{len(runs)}</strong> backtest"
            f"{'s' if len(runs)>1 else ''} sauvegardé{'s' if len(runs)>1 else ''}"
            f"</div>",
            unsafe_allow_html=True,
        )
    with c_clear:
        if st.button("Tout supprimer", key="hist_clear_all", type="secondary"):
            st.session_state["confirm_clear_all"] = True

    if st.session_state.get("confirm_clear_all"):
        st.warning("⚠️  Tu vas supprimer **tous** les backtests. Cette action est irréversible.")
        cc1, cc2 = st.columns([1, 6])
        with cc1:
            if st.button("Confirmer la suppression", key="confirm_yes"):
                for r in runs:
                    hs.delete_run(r["id"])
                st.session_state.pop("confirm_clear_all", None)
                st.rerun()
        with cc2:
            if st.button("Annuler", key="confirm_no", type="secondary"):
                st.session_state.pop("confirm_clear_all", None)
                st.rerun()

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ── Liste des backtests ────────────────────────────────────
    for run in runs:
        s = run["stats"]
        net_usd = s.get("net_ret_usd", 0)
        net_pct = s.get("net_ret_pct", 0)
        win_rate = s.get("win_rate", 0)
        n_trades = s.get("n_trades", 0)
        max_dd = s.get("max_dd_pct", 0)
        pf = s.get("profit_factor", 0)
        badge_cls = "h-badge-green" if net_usd >= 0 else "h-badge-red"
        badge_arrow = "↑" if net_usd >= 0 else "↓"

        with st.container():
            st.markdown(f"""
            <div class="history-card">
              <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px;position:relative">
                <div>
                  <div class="h-name">{run['name']}</div>
                  <div class="h-meta">
                    {run['strat_name']} · {_fmt_date(run['timestamp'])}
                  </div>
                </div>
                <span class="h-badge {badge_cls}">
                  {badge_arrow} {net_pct:+.2f}%
                </span>
              </div>
              <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:18px;position:relative">
                <div class="h-stat">
                  <div class="h-stat-label">Capital</div>
                  <div class="h-stat-value">${run['initial_cap']:,.0f}</div>
                </div>
                <div class="h-stat">
                  <div class="h-stat-label">P&L net</div>
                  <div class="h-stat-value {('green' if net_usd>=0 else 'red')}">{net_usd:+,.0f} $</div>
                </div>
                <div class="h-stat">
                  <div class="h-stat-label">Trades</div>
                  <div class="h-stat-value">{n_trades}</div>
                </div>
                <div class="h-stat">
                  <div class="h-stat-label">Win Rate</div>
                  <div class="h-stat-value">{win_rate:.1f}%</div>
                </div>
                <div class="h-stat">
                  <div class="h-stat-label">Max DD</div>
                  <div class="h-stat-value red">−{max_dd:.2f}%</div>
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)

            # Actions (Streamlit buttons en colonnes serrées)
            cols = st.columns([1.2, 1.2, 1.2, 5])
            with cols[0]:
                if st.button("👁  Voir", key=f"view_{run['id']}", width="stretch", type="secondary"):
                    full = hs.load_run(run["id"])
                    st.session_state["results"] = {
                        "trades_df":   full["trades_df"],
                        "equity_df":   full["equity_df"],
                        "stats":       full["stats"],
                        "strat_name":  full["strat_name"],
                        "initial_cap": full["initial_cap"],
                        "params":      full["params"],
                    }
                    st.session_state["jump_to_backtest"] = True
                    st.rerun()
            with cols[1]:
                if st.button("✏️  Renommer", key=f"rn_{run['id']}", width="stretch", type="secondary"):
                    st.session_state[f"renaming_{run['id']}"] = True
            with cols[2]:
                if st.button("🗑  Supprimer", key=f"del_{run['id']}", width="stretch", type="secondary"):
                    st.session_state[f"confirm_del_{run['id']}"] = True

            # Inline rename form
            if st.session_state.get(f"renaming_{run['id']}"):
                rc1, rc2, rc3 = st.columns([5, 1, 1])
                with rc1:
                    new_name = st.text_input(
                        "Nouveau nom", value=run["name"],
                        key=f"rn_input_{run['id']}", label_visibility="collapsed",
                    )
                with rc2:
                    if st.button("OK", key=f"rn_ok_{run['id']}", width="stretch"):
                        hs.rename_run(run["id"], new_name)
                        st.session_state.pop(f"renaming_{run['id']}", None)
                        st.rerun()
                with rc3:
                    if st.button("Annuler", key=f"rn_cancel_{run['id']}", width="stretch", type="secondary"):
                        st.session_state.pop(f"renaming_{run['id']}", None)
                        st.rerun()

            # Inline delete confirmation
            if st.session_state.get(f"confirm_del_{run['id']}"):
                st.warning(f"Supprimer définitivement **{run['name']}** ?")
                dc1, dc2, _ = st.columns([1.4, 1.4, 5])
                with dc1:
                    if st.button("Confirmer", key=f"del_ok_{run['id']}", width="stretch"):
                        hs.delete_run(run["id"])
                        st.session_state.pop(f"confirm_del_{run['id']}", None)
                        st.rerun()
                with dc2:
                    if st.button("Annuler", key=f"del_cancel_{run['id']}", width="stretch", type="secondary"):
                        st.session_state.pop(f"confirm_del_{run['id']}", None)
                        st.rerun()

            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════
# ONGLET NOUVELLE STRATÉGIE
# ═══════════════════════════════════════════════════════════════════

PROMPT_TEMPLATE = """Traduis ce code ProRealCode en Python pour mon moteur de backtest.

Le fichier Python doit OBLIGATOIREMENT respecter cette structure exacte :

```python
STRATEGY_NAME = "Nom de la stratégie"
WARMUP = 130  # ajuste selon les indicateurs les plus lents

DEFAULT_PARAMS = {{
    # tous les paramètres avec leurs valeurs par défaut
}}

PARAM_SCHEMA = {{
    "Nom Section": {{
        "nom_param": {{"type": "bool"|"int"|"float", "label": "...", "min": ..., "max": ..., "step": ...}},
    }},
}}

class Strategy:
    def __init__(self): self.reset()
    def reset(self): ...          # réinitialise l'état journalier
    def prepare(self, df, params): return df   # calcule les indicateurs
    def on_bar(self, i, df, context, params):  # retourne None ou dict action
        # context contient : in_pos, position, capital, strat_profit, initial_capital, last_exit_bar
        # Retourner None = rien
        # Retourner {{"action":"enter","direction":"long","stop_pct":...,"target_pct":...,"use_trailing":...,"trail_start_pct":...,"trail_pts":...,"max_bars":...,"nb_contracts":1}}
        # Retourner {{"action":"exit","at":"next_open","reason":"..."}}
        ...
```

Règles de traduction :
- Signaux évalués sur bougie FERMÉE (barre i), exécution à l'OPEN de la barre i+1
- AllowShort=0 => direction "long" uniquement
- UseCompounding=0 => nb_contracts=1 fixe
- TrailPts en unités de prix (pas en MT5 points)
- La méthode on_bar gère : reset journalier, OR, filtres temps, flat-time (exit next_open)
- L'engine gère automatiquement : stop/target intra-barre, trailing update, time-stop, P&L

Voici le code ProRealCode à traduire :

{code}"""


def render_new_strategy_tab():
    st.markdown(f"""
    <div style="margin-bottom:24px">
      <div style="font-size:20px;font-weight:700;color:white;margin-bottom:6px">
        ➕ Ajouter une nouvelle stratégie
      </div>
      <div style="font-size:13px;color:{TEXT_DIM}">
        Colle ton code ProRealCode ci-dessous, copie le prompt généré, et envoie-le à Claude Pro.
        Il te retourne un fichier <code style="color:{ACCENT}">.py</code> à déposer dans le dossier
        <code style="color:{ACCENT}">strategies/</code>.
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Les 4 étapes ──────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    steps = [
        ("1", "Colle ton code", "Paste ton ProRealCode dans la zone de texte ci-dessous"),
        ("2", "Copie le prompt", "Clique sur 'Copier le prompt' pour copier le message formaté"),
        ("3", "Envoie à Claude", "Ouvre Claude.ai et colle le prompt dans une nouvelle conversation"),
        ("4", "Dépose le fichier", f"Claude génère un fichier .py → dépose-le dans<br><code>strategies/</code>"),
    ]
    for col, (num, title, desc) in zip([c1, c2, c3, c4], steps):
        with col:
            st.markdown(f"""
            <div class="step-card">
              <div class="step-num">{num}</div>
              <div class="step-title">{title}</div>
              <div class="step-desc">{desc}</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)

    # ── Zone de saisie ProRealCode ────────────────────────────
    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.markdown(f"<div class='section-title'>Code ProRealCode à traduire</div>", unsafe_allow_html=True)
        prc_code = st.text_area(
            label="Code ProRealCode",
            placeholder="// Colle ton code ProRealCode ici...\nDEFPARAM CumulateOrders = False\n...",
            height=380,
            key="prc_input",
            label_visibility="collapsed",
        )

    with col_right:
        st.markdown(f"<div class='section-title'>Prompt prêt à envoyer à Claude</div>", unsafe_allow_html=True)

        code_to_show = prc_code.strip() if prc_code and prc_code.strip() else "// Ton code ProRealCode apparaîtra ici..."
        full_prompt  = PROMPT_TEMPLATE.format(code=code_to_show)

        # Affichage du prompt dans une zone copiable
        st.code(full_prompt, language=None)

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    # ── Boutons d'action ──────────────────────────────────────
    btn_col1, btn_col2, btn_col3 = st.columns([2, 2, 4])

    with btn_col1:
        # Copier dans le presse-papier via JavaScript
        if st.button("📋  Copier le prompt", width="stretch", key="copy_prompt"):
            escaped = full_prompt.replace("`", "\\`").replace("$", "\\$")
            components.html(f"""
            <script>
            (async () => {{
                try {{
                    await navigator.clipboard.writeText(`{escaped}`);
                }} catch(e) {{
                    // fallback
                    const el = document.createElement('textarea');
                    el.value = `{escaped}`;
                    document.body.appendChild(el);
                    el.select();
                    document.execCommand('copy');
                    document.body.removeChild(el);
                }}
            }})();
            </script>
            """, height=0)
            st.success("✅ Prompt copié ! Colle-le maintenant sur Claude.ai")

    with btn_col2:
        st.markdown(
            f'<a href="https://claude.ai" target="_blank" class="open-btn">🌐  Ouvrir Claude.ai</a>',
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)

    # ── Instructions dépôt ────────────────────────────────────
    base_dir = os.path.dirname(os.path.abspath(__file__))
    strat_dir = os.path.join(base_dir, "strategies")

    st.markdown(f"""
    <div style="background:{CARD_BG};border:1px solid {BORDER};border-radius:10px;padding:20px;">
      <div style="font-size:13px;font-weight:700;color:white;margin-bottom:12px">
        📁 Où déposer le fichier généré par Claude
      </div>
      <div style="font-family:'Consolas','Courier New',monospace;font-size:12px;
                  color:{GREEN};background:#050510;border-radius:6px;padding:12px;margin-bottom:12px">
        {strat_dir}
      </div>
      <div style="font-size:12px;color:{TEXT_DIM};line-height:1.8">
        1. Claude génère un fichier <code style="color:{ACCENT}">nom_strategie.py</code><br>
        2. Copie ce fichier dans le dossier <code style="color:{ACCENT}">strategies/</code> ci-dessus<br>
        3. Retourne sur l'onglet <strong style="color:white">📊 Backtest</strong><br>
        4. La nouvelle stratégie apparaît automatiquement dans le menu déroulant
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Stratégies actuellement chargées ─────────────────────
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    st.markdown(f"<div class='section-title'>Stratégies actuellement disponibles</div>", unsafe_allow_html=True)

    py_files = [f for f in os.listdir(strat_dir) if f.endswith(".py") and f != "__init__.py"]
    if py_files:
        for f in py_files:
            st.markdown(f"""
            <div style="display:flex;align-items:center;gap:10px;
                        padding:8px 12px;background:{CARD_BG};border:1px solid {BORDER};
                        border-radius:6px;margin-bottom:6px;font-size:12px">
              <span style="color:{GREEN}">✓</span>
              <code style="color:{ACCENT}">{f}</code>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.markdown(f"<div style='color:{TEXT_DIM};font-size:12px'>Aucune stratégie trouvée.</div>",
                    unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════
# ONGLET OPTIMISATION
# ═══════════════════════════════════════════════════════════════════

def _launch_optimizer(config_dict: dict):
    """Lance optimizer_process.py en mode job results/job_xxx/."""
    return launch_optimizer_job(
        config_dict,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _score_color(score: float) -> str:
    if score >= 70:
        return GREEN
    elif score >= 50:
        return "#f59e0b"
    else:
        return RED


def _score_class(score: float) -> str:
    if score >= 70:
        return "green"
    if score >= 50:
        return "accent"
    return "red"


_ACTIVE_REFRESH_STATUSES = {"created", "benchmarking", "running"}
_TERMINAL_STATUSES = {"completed", "stopped", "failed", "error"}


_STATUS_UI = {
    "created": {
        "label": "Préparation",
        "icon": "🕓",
        "color": TEXT_DIM,
        "description": "Le job est créé et attend le démarrage du process.",
    },
    "benchmarking": {
        "label": "Benchmark en cours",
        "icon": "📏",
        "color": ACCENT,
        "description": "Le système mesure la vitesse avant l'optimisation.",
    },
    "running": {
        "label": "Optimisation en cours",
        "icon": "⚙️",
        "color": "#f59e0b",
        "description": "Les combinaisons sont en cours de test.",
    },
    "completed": {
        "label": "Terminé",
        "icon": "✅",
        "color": GREEN,
        "description": "Le job est terminé et les fichiers peuvent être consultés.",
    },
    "stopped": {
        "label": "Arrêté",
        "icon": "⏹",
        "color": TEXT_DIM,
        "description": "Le job a reçu un signal d'arrêt propre.",
    },
    "failed": {
        "label": "Erreur",
        "icon": "❌",
        "color": RED,
        "description": "Le job s'est terminé avec une erreur.",
    },
    "error": {
        "label": "Erreur",
        "icon": "❌",
        "color": RED,
        "description": "Le job s'est terminé avec une erreur.",
    },
}


def _status_ui(status: str) -> dict:
    return _STATUS_UI.get(str(status or "").lower(), {
        "label": str(status or "Inconnu"),
        "icon": "•",
        "color": TEXT_DIM,
        "description": "Statut non reconnu.",
    })


def _status_badge(status: str) -> str:
    info = _status_ui(status)
    color = info["color"]
    return (
        f'<span style="display:inline-flex;align-items:center;gap:6px;'
        f'color:{color};font-size:12px;font-weight:700">'
        f'{info["icon"]} {_safe_html(info["label"])}</span>'
    )


def _is_active_status(status: str) -> bool:
    return str(status or "").lower() in _ACTIVE_REFRESH_STATUSES


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "oui", "on")
    return False


def _is_quick_validation(config: dict = None, meta: dict = None) -> bool:
    for source in (config or {}, meta or {}):
        if not isinstance(source, dict):
            continue
        if _as_bool(source.get("quick_validation_mode")):
            return True
        nested = source.get("config")
        if isinstance(nested, dict) and _as_bool(nested.get("quick_validation_mode")):
            return True
    return False


def _score_verdict(score: float, status: str = "completed", valid_count: int = 0,
                   quick_validation: bool = False) -> str:
    if _is_active_status(status):
        return "En cours"
    if quick_validation:
        return "Pipeline validé" if str(status or "").lower() == "completed" else "Test technique"
    if valid_count <= 0:
        return "Aucun champion"
    if score >= 70:
        return "Prometteur"
    if score >= 50:
        return "À étudier"
    return "Faible"


def _format_processed_total(processed, total) -> tuple[str, str]:
    processed = int(processed or 0)
    total = int(total or 0)
    if total <= 0:
        return f"{processed:,}", ""
    if processed > total:
        return f"{processed:,}", ""
    return f"{processed:,}", f"sur {total:,} prévus"


def _count_filtered_rows(df: pd.DataFrame) -> int:
    if df is None or df.empty:
        return 0
    for col in ("filtered_out", "is_filtered", "filtered"):
        if col in df.columns:
            return int(df[col].fillna(False).astype(bool).sum())
    for col in ("filter_reason", "rejection_reason", "reason"):
        if col in df.columns:
            return int(df[col].fillna("").astype(str).str.len().gt(0).sum())
    return 0


def _reason_count(df: pd.DataFrame, patterns: tuple[str, ...]) -> int:
    if df is None or df.empty:
        return 0
    cols = [c for c in ("filter_reason", "rejection_reason", "reason", "status") if c in df.columns]
    if not cols:
        return 0
    text = df[cols].fillna("").astype(str).agg(" ".join, axis=1).str.lower()
    mask = False
    for pattern in patterns:
        mask = mask | text.str.contains(pattern, regex=False)
    return int(mask.sum())


def _diagnostic_card(title: str, body: str, tone: str = "warning") -> None:
    color = {
        "info": ACCENT,
        "warning": "#f59e0b",
        "error": RED,
        "success": GREEN,
    }.get(tone, "#f59e0b")
    st.markdown(f"""
    <div style="padding:16px 18px;border:1px solid rgba({_hex_to_rgb(color)},0.35);
                background:rgba({_hex_to_rgb(color)},0.09);border-radius:8px;margin:10px 0 16px">
      <div style="font-size:15px;font-weight:750;color:white;margin-bottom:6px">
        {_safe_html(title)}
      </div>
      <div style="font-size:13px;color:{TEXT_DIM};line-height:1.55">
        {_safe_html(body)}
      </div>
    </div>
    """, unsafe_allow_html=True)


def _category_badge(categorie: str) -> str:
    colors = {
        "Réglage recommandé": (GREEN,  "#10b981"),
        "Réglage agressif":   ("#f59e0b", "#f59e0b"),
        "Réglage défensif":   (ACCENT,   ACCENT),
        "Réglage à éviter":   (RED,      RED),
    }
    c, border = colors.get(categorie, (TEXT_DIM, TEXT_DIM))
    return (
        f'<span style="background:rgba({_hex_to_rgb(c)},0.12);'
        f'border:1px solid rgba({_hex_to_rgb(border)},0.4);'
        f'color:{c};border-radius:999px;padding:3px 12px;font-size:12px;font-weight:600">'
        f'{categorie}</span>'
    )


def _hex_to_rgb(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    if len(h) == 6:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"{r},{g},{b}"
    return "255,255,255"


def render_optimization_tab(strategies: dict, mod, params: dict,
                             initial_capital, spread, slip_in, slip_out):
    """Onglet complet d'optimisation."""

    st.markdown(f"""
    <div style="margin-bottom:20px">
      <div style="font-size:22px;font-weight:700;color:white;letter-spacing:-0.4px;margin-bottom:6px">
        🔬 Optimisateur de Stratégie
      </div>
      <div style="font-size:13px;color:{TEXT_DIM}">
        Teste automatiquement des centaines de combinaisons de paramètres et classe les meilleurs
        réglages par score de robustesse.
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Sous-onglets internes ──────────────────────────────────
    subtab_labels = [
        "⚙️ Configuration",
        "⏳ Progression",
        "📊 Résultats",
        "📂 Historique Runs",
    ]
    if st.session_state.pop("opt_focus_results_tab", False):
        st.session_state["opt_subtabs"] = "📊 Résultats"
    elif st.session_state.get("opt_subtabs") not in subtab_labels:
        st.session_state["opt_subtabs"] = "⚙️ Configuration"

    sub_config, sub_progress, sub_results, sub_history = st.tabs(
        subtab_labels,
        default=st.session_state.get("opt_subtabs", "⚙️ Configuration"),
        key="opt_subtabs",
        on_change="rerun",
    )

    # ════════════════════════════════════════════════════════════
    # SOUS-ONGLET A : CONFIGURATION
    # ════════════════════════════════════════════════════════════
    with sub_config:
        if getattr(sub_config, "open", True):
            _render_config_tab(mod, params, initial_capital, spread, slip_in, slip_out,
                               strategies)

    # ════════════════════════════════════════════════════════════
    # SOUS-ONGLET B : PROGRESSION
    # ════════════════════════════════════════════════════════════
    with sub_progress:
        if getattr(sub_progress, "open", False):
            _render_progress_tab()

    # ════════════════════════════════════════════════════════════
    # SOUS-ONGLET C : RÉSULTATS
    # ════════════════════════════════════════════════════════════
    with sub_results:
        if getattr(sub_results, "open", False):
            _render_results_tab()

    # ════════════════════════════════════════════════════════════
    # SOUS-ONGLET D : HISTORIQUE
    # ════════════════════════════════════════════════════════════
    with sub_history:
        if getattr(sub_history, "open", False):
            _render_opt_history_tab()


# ── Sous-onglet Configuration ──────────────────────────────────────

def _render_config_tab(mod, params, initial_capital, spread, slip_in, slip_out,
                       strategies):

    schema       = getattr(mod, "PARAM_SCHEMA", {})
    default_params = dict(getattr(mod, "DEFAULT_PARAMS", params))

    active_jobs = _list_active_jobs()
    if active_jobs:
        _render_active_jobs_reconnect_panel(active_jobs, key_prefix="cfg_reconnect")
        st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)

    # ── Données de marché ─────────────────────────────────────
    st.markdown("<div class='section-title'>Données de marché</div>", unsafe_allow_html=True)
    st.caption(
        "Préparation multi-actifs : les CSV peuvent être placés dans "
        "`data/ACTIF/TIMEFRAME/`. L'ancien `nasdaq_3m.csv` reste compatible."
    )

    available_assets = list_available_assets()
    if st.session_state.get("opt_asset") not in available_assets:
        st.session_state["opt_asset"] = (
            DEFAULT_ASSET if DEFAULT_ASSET in available_assets else available_assets[0]
        )

    dc1, dc2 = st.columns(2)
    with dc1:
        selected_asset = st.selectbox(
            "Actif",
            options=available_assets,
            key="opt_asset",
            help="Exemple futur : NASDAQ, SP500, DAX.",
        )

    available_timeframes = list_available_timeframes(selected_asset)
    if st.session_state.get("opt_timeframe") not in available_timeframes:
        st.session_state["opt_timeframe"] = (
            DEFAULT_TIMEFRAME if DEFAULT_TIMEFRAME in available_timeframes else available_timeframes[0]
        )

    with dc2:
        selected_timeframe = st.selectbox(
            "Timeframe",
            options=available_timeframes,
            key="opt_timeframe",
            help="Exemple futur : M3, M15, H1.",
        )

    data_resolution = resolve_data_csv(selected_asset, selected_timeframe)
    data_ready = data_resolution.exists
    if data_ready:
        st.success(
            f"CSV sélectionné : `{data_resolution.relative_path}` "
            f"({data_resolution.asset}/{data_resolution.timeframe})",
            icon=None,
        )
        if data_resolution.source == "legacy":
            st.caption(
                "Compatibilité legacy : le fichier racine `nasdaq_3m.csv` est utilisé. "
                f"Plus tard, tu pourras copier ce CSV dans `data/{data_resolution.asset}/{data_resolution.timeframe}/`."
            )
    else:
        st.error(data_resolution.message, icon=None)

    # ── Mode validation rapide (F2) ───────────────────────────
    st.info(
        "Pour un premier test sur PC lent, active **Mode validation rapide**. "
        "Il sert à vérifier le pipeline complet sans lancer un calcul trop long.",
        icon=None,
    )
    quick_mode = st.toggle(
        "⚡ Mode validation rapide (PC lent)",
        value=False,
        key="opt_quick_mode",
        help=(
            "Presets automatiques : 20 000 lignes max · 12 combinaisons max · "
            "1 worker · 1 échantillon benchmark · train/test désactivé. "
            "Idéal pour vérifier que le pipeline fonctionne avant un long run."
        ),
    )
    if quick_mode:
        st.warning(
            "⚡ **Mode validation rapide activé** — Ce mode sert à valider "
            "techniquement l'optimisateur, **pas à trouver le meilleur réglage final**. "
            "Les presets (20 000 lignes, 12 combos max, 1 worker, benchmark×1) sont appliqués automatiquement.",
            icon=None,
        )

    # ── Mode d'optimisation ───────────────────────────────────
    st.markdown("<div class='section-title'>Mode d'optimisation</div>", unsafe_allow_html=True)
    mode_labels = {
        "single_var": "1 — Variable par variable (rapide, ~80 tests)",
        "cross_zone":  "2 — Croisée autour des meilleures zones",
        "grid":        "3 — Grille complète (teste tout)",
        "general":     "4 — Intelligent (auto selon N)",
    }
    mode_keys = list(mode_labels.keys())
    mode_idx  = st.radio(
        "Mode", options=mode_keys,
        format_func=lambda k: mode_labels[k],
        index=3, key="opt_mode",
        horizontal=False,
    )

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ── Tableau des variables à optimiser ─────────────────────
    st.markdown("<div class='section-title'>Paramètres à optimiser</div>", unsafe_allow_html=True)
    st.markdown(
        f"<div style='font-size:12px;color:{TEXT_DIM};margin-bottom:10px'>"
        "Cochez les variables à faire varier. Ajustez min / max / step selon vos besoins."
        "</div>", unsafe_allow_html=True
    )

    param_ranges = []
    total_combos = 1

    # Aplatir le schéma pour avoir une liste de (key, meta) sans sections
    flat_params = {}
    for section, fields in schema.items():
        for k, meta in fields.items():
            flat_params[k] = meta

    # Récupérer les paramètres "float" et "int" uniquement (optimisables)
    optimizable = {
        k: m for k, m in flat_params.items()
        if m.get("type") in ("float", "int")
    }

    if not optimizable:
        st.warning("Aucun paramètre numérique trouvé dans le schéma de cette stratégie.")
    else:
        cols_header = st.columns([0.3, 2, 1, 1, 1, 1])
        for h, w in zip(["", "Paramètre", "Min", "Max", "Step", "Valeurs"], cols_header):
            w.markdown(f"<div style='font-size:11px;color:{TEXT_DIM};font-weight:600'>{h}</div>",
                       unsafe_allow_html=True)

        for k, meta in optimizable.items():
            typ  = meta["type"]
            lbl  = meta["label"]
            dval = default_params.get(k, 0)
            if typ == "int":
                mn = int(meta.get("min", 0))
                mx = int(meta.get("max", int(dval) * 3 or 10))
                stp = int(meta.get("step", 1)) or 1
            else:
                mn = float(meta.get("min", 0))
                mx = float(meta.get("max", dval * 3 or 10))
                stp = float(meta.get("step", 0.1))

            c0, c1, c2, c3, c4, c5 = st.columns([0.3, 2, 1, 1, 1, 1])
            with c0:
                enabled = st.checkbox(
                    f"Optimiser {lbl}",
                    value=False,
                    key=f"opt_en_{k}",
                    label_visibility="collapsed",
                )
            with c1:
                st.markdown(
                    f"<div style='padding-top:8px;font-size:12px;color:{TEXT}'>{lbl}</div>",
                    unsafe_allow_html=True,
                )
            with c2:
                min_v = st.number_input(
                    f"Minimum {lbl}", value=mn, key=f"opt_min_{k}", label_visibility="collapsed",
                    format="%.2f" if typ == "float" else "%d",
                )
            with c3:
                max_v = st.number_input(
                    f"Maximum {lbl}", value=mx, key=f"opt_max_{k}", label_visibility="collapsed",
                    format="%.2f" if typ == "float" else "%d",
                )
            with c4:
                step_v = st.number_input(
                    f"Pas {lbl}", value=stp, key=f"opt_step_{k}", label_visibility="collapsed",
                    format="%.3f" if typ == "float" else "%d",
                )
            with c5:
                if enabled and step_v > 0:
                    n_vals = max(1, int((max_v - min_v) / step_v) + 1)
                    total_combos *= n_vals
                    st.markdown(
                        f"<div style='padding-top:8px;font-size:12px;color:{ACCENT}'>"
                        f"{n_vals}</div>", unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"<div style='padding-top:8px;font-size:12px;color:{TEXT_MUTED}'>"
                        f"—</div>", unsafe_allow_html=True,
                    )

            if enabled:
                param_ranges.append(ParamRange(
                    name=k, param_type="number", label=lbl,
                    min_val=float(min_v), max_val=float(max_v),
                    step=float(step_v), enabled=True,
                ))

    # Ajouter les paramètres bool comme fixes
    for k, meta in flat_params.items():
        if meta.get("type") == "bool":
            param_ranges.append(ParamRange(
                name=k, param_type="bool", label=meta["label"],
                options=[bool(params.get(k, False))], enabled=False,
            ))

    # Sauvegarder les ranges dans session_state
    st.session_state["opt_param_ranges"] = param_ranges

    # ── Compteur de combinaisons ─────────────────────────────
    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    wc1, wc2 = st.columns([2, 1])
    with wc1:
        n_workers_default = max(1, min(os.cpu_count() or 4, 8))
        n_workers = st.slider(
            "Nombre de workers (CPU)", 1, os.cpu_count() or 8,
            value=n_workers_default, key="opt_workers",
        )
    with wc2:
        benchmark_n_sample = st.selectbox(
            "Échantillons benchmark",
            options=[1, 3, 5, 10, 15],
            index=2,              # défaut = 5
            key="opt_benchmark_n_sample",
            help=(
                "Nombre de backtests pour mesurer la vitesse avant l'optimisation. "
                "Moins = démarrage plus rapide mais estimation moins précise."
            ),
        )

    gp = {
        "initial_capital": float(initial_capital),
        "spread":          float(spread),
        "slip_in":         float(slip_in),
        "slip_out":        float(slip_out),
    }

    # ── Période d'optimisation (réduction de données) ─────────
    with st.expander("📅 Période d'optimisation (réduction de données)", expanded=False):
        st.markdown(
            f"<div style='font-size:12px;color:{TEXT_DIM};margin-bottom:10px'>"
            "Limitez l'optimisation à une sous-période ou un nombre de lignes réduit. "
            "Utile pour valider rapidement le pipeline avant un run complet sur l'ensemble des données."
            "</div>", unsafe_allow_html=True
        )
        pc1, pc2, pc3 = st.columns(3)
        with pc1:
            use_start = st.checkbox("Date de début", value=False, key="opt_use_start")
            if use_start:
                _d_start = st.date_input(
                    "Début", value=datetime.date(2022, 1, 1),
                    key="opt_start_date_widget",
                )
                opt_start_date_str = _d_start.isoformat()
            else:
                opt_start_date_str = None
        with pc2:
            use_end = st.checkbox("Date de fin", value=False, key="opt_use_end")
            if use_end:
                _d_end = st.date_input(
                    "Fin", value=datetime.date(2024, 12, 31),
                    key="opt_end_date_widget",
                )
                opt_end_date_str = _d_end.isoformat()
            else:
                opt_end_date_str = None
        with pc3:
            use_maxrows = st.checkbox("Limiter les lignes", value=False, key="opt_use_maxrows")
            if use_maxrows:
                opt_max_rows = st.number_input(
                    "Nb de lignes max", value=100_000,
                    min_value=10_000, max_value=1_000_000, step=10_000,
                    key="opt_max_rows_widget",
                    help="Filtre appliqué après le filtre de date — garde les N premières lignes.",
                )
            else:
                opt_max_rows = None

        # Récapitulatif du filtrage actif
        _filter_parts = []
        if opt_start_date_str:
            _filter_parts.append(f"début **{opt_start_date_str}**")
        if opt_end_date_str:
            _filter_parts.append(f"fin **{opt_end_date_str}**")
        if opt_max_rows:
            _filter_parts.append(f"max **{opt_max_rows:,}** lignes")
        if _filter_parts:
            st.info("📅 Filtrage actif : " + " · ".join(_filter_parts))
        else:
            if quick_mode:
                st.info("⚡ Mode rapide actif : une limite de 20 000 lignes sera appliquée automatiquement.")
            else:
                st.warning(
                    "Aucun filtre actif : l'optimisation utilisera tout l'historique. "
                    "Sur un PC lent, active le mode validation rapide ou limite le nombre de lignes.",
                    icon=None,
                )

    # ── Override mode validation rapide ──────────────────────
    _QUICK_MAX_COMBOS   = 12
    _QUICK_MAX_ROWS     = 20_000
    _QUICK_BENCHMARK    = 1
    _QUICK_N_WORKERS    = 1
    if quick_mode:
        # Remplacer les valeurs par les presets
        n_workers         = _QUICK_N_WORKERS
        benchmark_n_sample = _QUICK_BENCHMARK
        if opt_max_rows is None or opt_max_rows > _QUICK_MAX_ROWS:
            opt_max_rows  = _QUICK_MAX_ROWS

    enabled_ranges = [pr for pr in param_ranges if pr.enabled]
    raw_total_combos = total_combos
    max_combinations_limit = _QUICK_MAX_COMBOS if quick_mode else None

    # Limiter le nb de combinaisons en mode validation rapide
    if quick_mode and total_combos > _QUICK_MAX_COMBOS:
        total_combos = _QUICK_MAX_COMBOS

    if enabled_ranges:
        ms_per_bt      = st.session_state.get("opt_benchmark_ms", 500.0)
        eta_s_opt      = estimate_duration(total_combos, ms_per_bt, n_workers)
        # Durée benchmark (benchmark_n_sample backtests séquentiels)
        eta_s_bench    = benchmark_n_sample * ms_per_bt / 1000.0
        # Train/test : lire la valeur du widget (pas encore instancié → session_state)
        _tt_on         = st.session_state.get("tt_enabled", False)
        eta_s_tt_extra = eta_s_opt if _tt_on else 0.0   # validation sur top_k ≈ 1× opt
        eta_s_total    = eta_s_bench + eta_s_opt + eta_s_tt_extra

        color_combo = RED if total_combos > 100_000 else (
            "#f59e0b" if total_combos > 10_000 else GREEN)
        color_total = RED if eta_s_total > 3600 else (
            "#f59e0b" if eta_s_total > 600 else GREEN)

        # Détail rows
        _rows_detail = ""
        if opt_max_rows or opt_start_date_str or opt_end_date_str:
            _rows_parts = []
            if opt_start_date_str:
                _rows_parts.append(f"depuis {opt_start_date_str}")
            if opt_end_date_str:
                _rows_parts.append(f"jusqu'au {opt_end_date_str}")
            if opt_max_rows:
                _rows_parts.append(f"max {opt_max_rows:,} lignes")
            _rows_detail = f"<div style='font-size:10px;color:{TEXT_MUTED};margin-top:2px'>" \
                           + " · ".join(_rows_parts) + "</div>"

        # Détail durée
        _bench_detail = (
            f"benchmark {benchmark_n_sample}×: ~{format_duration(eta_s_bench)} + "
            f"optim: ~{format_duration(eta_s_opt)}"
        )
        if _tt_on:
            _bench_detail += f" + validation: ~{format_duration(eta_s_tt_extra)}"

        st.markdown(f"""
        <div style="background:{CARD_BG2};border:1px solid {BORDER};border-radius:10px;padding:16px 20px;margin-bottom:16px">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div>
              <div style="font-size:11px;color:{TEXT_DIM};font-weight:600;text-transform:uppercase;letter-spacing:0.5px">
                Combinaisons à tester
              </div>
              <div style="font-size:28px;font-weight:700;color:{color_combo};font-variant-numeric:tabular-nums">
                {total_combos:,}
              </div>
              {_rows_detail}
            </div>
            <div style="text-align:right">
              <div style="font-size:11px;color:{TEXT_DIM};font-weight:600;text-transform:uppercase;letter-spacing:0.5px">
                Durée totale estimée
              </div>
              <div style="font-size:20px;font-weight:600;color:{color_total}">
                ~{format_duration(eta_s_total)}
              </div>
              <div style="font-size:10px;color:{TEXT_MUTED}">
                {_bench_detail}
              </div>
              <div style="font-size:10px;color:{TEXT_MUTED}">
                {n_workers} worker{'s' if n_workers > 1 else ''} · bench {benchmark_n_sample}×
              </div>
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        if total_combos > 100_000:
            st.warning(
                f"⚠️ **{total_combos:,} combinaisons** détectées. "
                "L'estimation peut dépasser 30 minutes. "
                "Le **Mode 4 (Intelligent)** est recommandé pour ce volume."
            )
    else:
        st.info("💡 Sélectionnez au moins un paramètre à optimiser ci-dessus.")

    # ── Scoring ────────────────────────────────────────────────
    with st.expander("⚖️ Pondération du score", expanded=False):
        st.markdown(
            f"<div style='font-size:12px;color:{TEXT_DIM};margin-bottom:10px'>"
            "Ajustez l'importance relative de chaque métrique dans le score global."
            "</div>", unsafe_allow_html=True
        )
        c1, c2, c3 = st.columns(3)
        with c1:
            w_pf   = st.slider("Profit Factor",          0.0, 5.0, 3.0, 0.5, key="sw_pf")
            w_dd   = st.slider("Max Drawdown",           0.0, 5.0, 3.0, 0.5, key="sw_dd")
            w_nt   = st.slider("Nb Trades",              0.0, 5.0, 2.0, 0.5, key="sw_nt")
        with c2:
            w_mc   = st.slider("Pertes consécutives",    0.0, 5.0, 2.0, 0.5, key="sw_mc")
            w_gain = st.slider("% de gain",              0.0, 5.0, 2.0, 0.5, key="sw_gain")
            w_wr   = st.slider("Win Rate",               0.0, 5.0, 1.0, 0.5, key="sw_wr")
        with c3:
            w_ratio = st.slider("Ratio Gain/Perte",      0.0, 5.0, 1.5, 0.5, key="sw_ratio")
            w_eq    = st.slider("Régularité Equity",     0.0, 5.0, 1.5, 0.5, key="sw_eq")
            w_rf    = st.slider("Recovery Factor",       0.0, 5.0, 1.0, 0.5, key="sw_rf")

    score_weights = ScoreWeights(
        profit_factor=w_pf, max_drawdown=w_dd, total_trades=w_nt,
        max_consecutive_losses=w_mc, pct_gain=w_gain, win_rate=w_wr,
        avg_win_loss_ratio=w_ratio, equity_regularity=w_eq, recovery_factor=w_rf,
    )

    # ── Filtres ───────────────────────────────────────────────
    with st.expander("🚧 Filtres éliminatoires", expanded=False):
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            f_trades = st.number_input("Trades min",        value=30,  min_value=1,   step=5,   key="f_trades")
            f_dd     = st.number_input("DD max (%)",         value=25.0, min_value=0.0, step=1.0, key="f_dd")
        with fc2:
            f_pf     = st.number_input("PF min",            value=1.1,  min_value=0.5, step=0.1, key="f_pf")
            f_consec = st.number_input("Pertes consec max", value=12,   min_value=1,   step=1,   key="f_consec")
        with fc3:
            f_wr     = st.number_input("Win Rate min (%)",  value=35.0, min_value=0.0, step=1.0, key="f_wr")

    filters = FilterConfig(
        min_trades=int(f_trades),
        max_drawdown_pct=float(f_dd),
        min_profit_factor=float(f_pf),
        max_consecutive_losses=int(f_consec),
        min_win_rate=float(f_wr),
    )

    # ── Train / Test ──────────────────────────────────────────
    with st.expander("🔀 Split Train / Test (anti-overfitting)", expanded=False):
        tt_enabled = st.toggle("Activer le split train/test", value=False, key="tt_enabled")
        if tt_enabled:
            tt_method = st.radio(
                "Méthode de split", ["ratio", "date"],
                format_func=lambda x: "Par ratio (ex: 70%/30%)" if x == "ratio" else "Par date fixe",
                key="tt_method", horizontal=True,
            )
            if tt_method == "ratio":
                tt_ratio = st.slider("Ratio d'entraînement", 0.5, 0.9, 0.7, 0.05, key="tt_ratio")
                tt_date  = None
            else:
                tt_ratio = 0.7
                tt_date  = st.text_input("Date de séparation (YYYY-MM-DD)", value="2024-01-01",
                                          key="tt_date")
            tt_alert = st.slider("Alerte dégradation (%)", 10, 60, 30, 5, key="tt_alert")
        else:
            tt_method = "ratio"
            tt_ratio  = 0.7
            tt_date   = None
            tt_alert  = 30.0

    train_test = TrainTestConfig(
        enabled=tt_enabled,
        split_method=tt_method if tt_enabled else "ratio",
        train_ratio=tt_ratio if tt_enabled else 0.7,
        split_date=tt_date if tt_enabled else None,
        alert_degradation_pct=float(tt_alert) if tt_enabled else 30.0,
    )

    # ── Bouton LANCER ─────────────────────────────────────────
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    current_run_id = st.session_state.get("opt_current_run_id")
    is_running     = False
    if current_run_id:
        status = _get_run_status(current_run_id)
        is_running = (status in ("running", "benchmarking", "created"))

    if not data_ready:
        st.button("▶  Lancer l'optimisation", disabled=True,
                  width="stretch", key="opt_launch_no_data")
        st.info("Ajoute d'abord un CSV pour l'actif et le timeframe sélectionnés.")
    elif not enabled_ranges:
        st.button("▶  Lancer l'optimisation", disabled=True,
                  width="stretch", key="opt_launch_disabled")
        st.info("Sélectionnez au moins un paramètre à optimiser.")
    elif is_running:
        st.button("▶  Optimisation en cours…", disabled=True,
                  width="stretch", key="opt_running_btn")
        if st.button("⏹  Arrêter proprement", width="stretch", key="opt_stop_btn"):
            _write_stop_flag(current_run_id)
            st.toast("Signal d'arrêt envoyé…", icon="⏹")
    else:
        # ── Anti-overload : protection avant lancement (F5) ───
        _ms_guard  = st.session_state.get("opt_benchmark_ms", 500.0)
        _eta_guard = (
            benchmark_n_sample * _ms_guard / 1000.0
            + estimate_duration(total_combos, _ms_guard, n_workers)
            * (2 if tt_enabled else 1)
        )
        _can_launch = True

        if _eta_guard > 24 * 3600:
            st.error(
                f"🚫 **Durée estimée : {format_duration(_eta_guard)}** (> 24h) — "
                "Lancement **bloqué**. Réduisez le nombre de combinaisons, "
                "activez le **Mode 4 (Intelligent)**, ou utilisez la **période réduite**."
            )
            _can_launch = False
        elif _eta_guard > 6 * 3600:
            st.warning(
                f"⚠️ Durée estimée **{format_duration(_eta_guard)}** — run de plus de 6 heures."
            )
            _c1 = st.checkbox(
                "✅ Je confirme vouloir lancer ce run (durée > 6h)",
                key="opt_confirm_6h",
            )
            _c2 = st.checkbox(
                "✅ Seconde confirmation requise (run très long)",
                key="opt_confirm_6h_2",
            )
            if not (_c1 and _c2):
                _can_launch = False
        elif _eta_guard > 3600:
            st.warning(
                f"⚠️ Durée estimée **{format_duration(_eta_guard)}** — run de plus d'1 heure."
            )
            _c1 = st.checkbox(
                "✅ Je confirme vouloir lancer ce run (durée > 1h)",
                key="opt_confirm_1h",
            )
            if not _c1:
                _can_launch = False

        if not _can_launch:
            st.button("▶  Lancer l'optimisation", disabled=True,
                      width="stretch", key="opt_launch_blocked")
        elif st.button("▶  Lancer l'optimisation", width="stretch", key="opt_launch"):

            requested_job_id = opt_store.make_job_id()

            # Sérialiser la config
            def _sw_to_dict(sw):
                return {
                    "profit_factor": sw.profit_factor,
                    "max_drawdown": sw.max_drawdown,
                    "total_trades": sw.total_trades,
                    "max_consecutive_losses": sw.max_consecutive_losses,
                    "pct_gain": sw.pct_gain,
                    "win_rate": sw.win_rate,
                    "avg_win_loss_ratio": sw.avg_win_loss_ratio,
                    "equity_regularity": sw.equity_regularity,
                    "recovery_factor": sw.recovery_factor,
                }

            def _pr_to_dict(pr):
                return {
                    "name": pr.name, "param_type": pr.param_type, "label": pr.label,
                    "min_val": pr.min_val, "max_val": pr.max_val, "step": pr.step,
                    "options": pr.options, "enabled": pr.enabled,
                }

            config_dict = {
                "run_id":          requested_job_id,
                "strategy_module": os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "strategies",
                    f"{mod.__name__.split('.')[-1]}.py"
                    if hasattr(mod, "__name__") else
                    next(
                        (f for f in os.listdir(
                            os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategies"))
                         if f.endswith(".py") and f != "__init__.py" and
                         getattr(importlib.util.module_from_spec(
                             importlib.util.spec_from_file_location("_t", os.path.join(
                                 os.path.dirname(os.path.abspath(__file__)), "strategies", f))
                         ), "STRATEGY_NAME", "") == mod.STRATEGY_NAME
                         ),
                        ""
                    )
                ),
                "strategy_name":   mod.STRATEGY_NAME,
                "data_file":       data_resolution.relative_path,
                "data_path":       data_resolution.relative_path,
                "data_source":     data_resolution.source,
                "data_legacy_fallback": data_resolution.source == "legacy",
                "asset":           data_resolution.asset,
                "timeframe":       data_resolution.timeframe,
                "base_params":     dict(params),
                "param_ranges":    [_pr_to_dict(pr) for pr in param_ranges],
                "mode":            mode_idx,
                "score_weights":   _sw_to_dict(score_weights),
                "filters": {
                    "min_trades":             filters.min_trades,
                    "max_drawdown_pct":       filters.max_drawdown_pct,
                    "min_profit_factor":      filters.min_profit_factor,
                    "max_consecutive_losses": filters.max_consecutive_losses,
                    "min_win_rate":           filters.min_win_rate,
                },
                "train_test": {
                    "enabled":              train_test.enabled,
                    "split_method":         train_test.split_method,
                    "train_ratio":          train_test.train_ratio,
                    "split_date":           train_test.split_date,
                    "alert_degradation_pct": train_test.alert_degradation_pct,
                },
                "global_params":   gp,
                "n_workers":       n_workers,
                "top_k_save":      100,
                "top_k_display":   10,
                "total_combinations": total_combos,
                "raw_total_combinations": raw_total_combos,
                "max_combinations": max_combinations_limit,
                # Période réduite (F1)
                "opt_start_date":       opt_start_date_str,
                "opt_end_date":         opt_end_date_str,
                "max_rows":             opt_max_rows,
                # Benchmark configurable (F3)
                "benchmark_n_sample":   int(benchmark_n_sample),
                # Mode validation rapide (F2)
                "quick_validation_mode": bool(quick_mode),
            }

            # Résoudre le chemin du fichier stratégie
            strat_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategies")
            for fname in os.listdir(strat_dir):
                if fname.endswith(".py") and fname != "__init__.py":
                    fpath = os.path.join(strat_dir, fname)
                    try:
                        spec = importlib.util.spec_from_file_location("_chk", fpath)
                        m    = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(m)
                        if getattr(m, "STRATEGY_NAME", "") == mod.STRATEGY_NAME:
                            config_dict["strategy_module"] = to_relative_path(fpath)
                            break
                    except Exception:
                        pass

            launched = _launch_optimizer(config_dict)
            run_id = launched.job_id
            _remember_job_for_tracking({"job_id": run_id, "job_dir": launched.job_dir})
            st.success(f"✅ Optimisation lancée ! Job : `{run_id}`")
            st.toast("Passe sur l'onglet ⏳ Progression pour suivre l'avancement.", icon="🔬")


# ── Sous-onglet Progression ────────────────────────────────────────

def _render_progress_tab():
    run_id = st.session_state.get("opt_current_run_id")

    if not run_id:
        active_jobs = _list_active_jobs()
        if active_jobs:
            _render_active_jobs_reconnect_panel(active_jobs, key_prefix="prog_reconnect")
            return

        st.markdown(f"""
        <div class="h-empty">
          <div style="font-size:48px;margin-bottom:14px;opacity:0.5">⏳</div>
          <div style="font-size:15px;font-weight:600;color:{TEXT};margin-bottom:6px">
            Aucune optimisation en cours
          </div>
          <div style="font-size:13px;max-width:380px;line-height:1.55">
            Configurez et lancez une optimisation depuis l'onglet <strong>⚙️ Configuration</strong>.
          </div>
        </div>
        """, unsafe_allow_html=True)
        return

    progress = _read_progress(run_id)
    if not progress:
        st.info(f"En attente des données pour `{run_id}`…")
        if _is_job_id(run_id):
            if st.button("🔄  Actualiser", width="content", key="prog_wait_refresh"):
                st.rerun()
            return
        st.rerun()
        return

    status = progress.get("status", "unknown")
    if _is_active_status(status):
        _render_progress_auto_fragment(run_id)
        return

    _render_progress_content(run_id, progress)


@st.fragment(run_every=2.5)
def _render_progress_auto_fragment(run_id: str) -> None:
    progress = _read_progress(run_id)
    if not progress:
        st.info(f"En attente des données pour `{run_id}`…")
        if st.button("🔄  Actualiser", width="content", key="prog_auto_wait_refresh"):
            st.rerun()
        return

    status = progress.get("status", "unknown")
    _render_progress_content(run_id, progress)
    if not _is_active_status(status):
        st.rerun()


def _render_progress_content(run_id: str, progress: dict) -> None:
    status = progress.get("status", "unknown")

    # ── Header état ───────────────────────────────────────────
    status_info = _status_ui(status)
    sc = status_info["color"]
    sl = f'{status_info["icon"]} {status_info["label"]}'

    completed  = progress.get("completed", 0)
    total      = progress.get("total_combinations", 0)
    pct        = progress.get("progress_pct", 0.0)
    failed     = progress.get("failed", 0)
    processed  = progress.get("combinations_done", completed + failed)
    best_score = progress.get("best_score", 0.0)
    elapsed    = progress.get("elapsed_seconds", 0)
    eta        = progress.get("eta_seconds")
    workers    = progress.get("workers_used", 1)
    bms        = progress.get("benchmark_ms_per_backtest", 0)
    update_label = _fmt_update_label(run_id, progress)
    processed_label, total_sub = _format_processed_total(processed, total)
    quick_validation = _is_quick_validation(_load_job_config(_job_dir_for_run(run_id)), progress)

    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px">
      <span style="font-size:14px;font-weight:700;color:{sc}">{sl}</span>
      <span style="font-size:12px;color:{TEXT_DIM};font-family:'JetBrains Mono',monospace">{run_id}</span>
      <span style="font-size:11px;color:{TEXT_MUTED}">Dernière mise à jour {update_label}</span>
    </div>
    """, unsafe_allow_html=True)

    if status == "created":
        _diagnostic_card(
            "Préparation du job",
            "Le dossier du job existe. Le process doit passer au benchmark ou à l'optimisation dans quelques instants.",
            tone="info",
        )

    if status == "benchmarking":
        _render_benchmarking_progress(run_id, progress, workers)
        return

    # Barre de progression
    if status == "running":
        st.progress(max(0.0, min(1.0, pct / 100)))

    # Métriques temps réel
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    with m1:
        st.markdown(card("Tests traités", processed_label, "white", sub=total_sub), unsafe_allow_html=True)
    with m2:
        st.markdown(card("Tests filtrés", f"{failed:,}", "accent"), unsafe_allow_html=True)
    with m3:
        st.markdown(card("Meilleur score", f"{best_score:.1f}", _score_class(best_score)), unsafe_allow_html=True)
    with m4:
        st.markdown(card("Écoulé", format_duration(elapsed), "white"), unsafe_allow_html=True)
    with m5:
        eta_str = format_duration(eta) if eta else "—"
        eta_sub = f"{workers} worker{'s' if workers > 1 else ''}"
        if bms:
            eta_sub += f" · {bms:.0f} ms/bt"
        st.markdown(card("ETA", eta_str, "white", sub=eta_sub), unsafe_allow_html=True)
    with m6:
        st.markdown(
            card(
                "Verdict",
                _score_verdict(float(best_score), status, int(completed or 0), quick_validation),
                "white",
            ),
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    # Meilleur résultat courant
    best_params = progress.get("best_params", {})
    best_stats  = progress.get("best_stats", {})
    if best_params:
        st.markdown("<div class='section-title'>Meilleur réglage actuel</div>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(
                "<div style='font-size:12px;color:{};font-weight:600;margin-bottom:6px'>Paramètres</div>".format(TEXT_DIM),
                unsafe_allow_html=True,
            )
            for k, v in list(best_params.items())[:10]:
                st.markdown(
                    f'<div class="stats-row"><span class="stats-key">{k}</span>'
                    f'<span class="stats-val">{v}</span></div>',
                    unsafe_allow_html=True,
                )
        with c2:
            st.markdown(
                "<div style='font-size:12px;color:{};font-weight:600;margin-bottom:6px'>Métriques</div>".format(TEXT_DIM),
                unsafe_allow_html=True,
            )
            display_stats = {
                "Trades":     best_stats.get("n_trades", "—"),
                "Profit Factor": f"{best_stats.get('profit_factor', 0):.2f}" if best_stats.get("profit_factor") else "—",
                "Win Rate":   f"{best_stats.get('win_rate', 0):.1f}%",
                "Max DD":     f"{best_stats.get('max_dd_pct', 0):.1f}%",
                "Gain":       f"{best_stats.get('net_ret_pct', 0):+.1f}%",
            }
            for k, v in display_stats.items():
                st.markdown(
                    f'<div class="stats-row"><span class="stats-key">{k}</span>'
                    f'<span class="stats-val">{v}</span></div>',
                    unsafe_allow_html=True,
                )

    # ── Boutons d'action ──────────────────────────────────────
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    btn_c1, btn_c2, _ = st.columns([1, 1, 4])
    with btn_c1:
        if status in ("created", "running"):
            if st.button("⏹  Arrêter proprement", width="stretch", key="prog_stop"):
                _write_stop_flag(run_id)
                st.toast("Signal d'arrêt envoyé…", icon="⏹")
        elif status in ("completed", "stopped", "failed", "error"):
            if st.button("📊  Voir les résultats", width="stretch", key="prog_results"):
                _show_results_for_run(run_id, _job_dir_for_run(run_id))
                st.rerun()
    with btn_c2:
        if st.button("🔄  Actualiser", width="stretch", key="prog_refresh"):
            st.rerun()

    # Erreur éventuelle
    err = progress.get("error_message")
    if err:
        st.error(f"❌ Erreur : {err}")


# ── Sous-onglet Résultats ───────────────────────────────────────────

_JOB_DOWNLOAD_FILES = [
    ("results.csv", "Résultats complets", "text/csv"),
    ("best_strategies.csv", "Meilleures stratégies", "text/csv"),
    ("metrics.json", "Métriques", "application/json"),
    ("report.html", "Rapport HTML", "text/html"),
    ("archive.zip", "Archive ZIP", "application/zip"),
]


def _safe_html(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _is_job_id(run_id: str) -> bool:
    return str(run_id or "").startswith("job_")


def _find_job_summary(job_id: str) -> dict:
    if not _is_job_id(job_id):
        return {}
    try:
        for job in opt_store.list_jobs():
            if job.get("job_id") == job_id:
                return job
    except Exception:
        return {}
    return {}


def _job_dir_for_run(run_id: str):
    if not _is_job_id(run_id):
        return None
    session_job_dirs = st.session_state.get("opt_job_dirs", {})
    if run_id in session_job_dirs and os.path.isdir(session_job_dirs[run_id]):
        return session_job_dirs[run_id]
    return _find_job_summary(run_id).get("job_dir")


def _read_progress(run_id: str):
    return opt_store.read_progress(run_id, job_dir=_job_dir_for_run(run_id))


def _get_run_status(run_id: str) -> str:
    return opt_store.get_run_status(run_id, job_dir=_job_dir_for_run(run_id))


def _write_stop_flag(run_id: str) -> None:
    opt_store.write_stop_flag(run_id, job_dir=_job_dir_for_run(run_id))


def _progress_updated_at(run_id: str, progress: dict):
    updated_at = progress.get("updated_at")
    if updated_at:
        try:
            return datetime.datetime.fromisoformat(str(updated_at))
        except ValueError:
            pass

    job_dir = _job_dir_for_run(run_id)
    if not job_dir:
        return None

    path = os.path.join(job_dir, "progress.json")
    if not os.path.exists(path):
        return None

    try:
        return datetime.datetime.fromtimestamp(os.path.getmtime(path))
    except OSError:
        return None


def _progress_age_seconds(run_id: str, progress: dict):
    updated = _progress_updated_at(run_id, progress)
    if not updated:
        return None
    return max(0.0, (datetime.datetime.now() - updated).total_seconds())


def _fmt_update_label(run_id: str, progress: dict) -> str:
    updated = _progress_updated_at(run_id, progress)
    if not updated:
        return "inconnue"
    return updated.strftime("%H:%M:%S")


def _render_benchmarking_progress(run_id: str, progress: dict, workers: int) -> None:
    age_seconds = _progress_age_seconds(run_id, progress)
    update_label = _fmt_update_label(run_id, progress)
    stale = age_seconds is not None and age_seconds > 120

    st.markdown(f"""
    <div style="padding:16px;border:1px solid rgba({_hex_to_rgb(ACCENT)},0.32);
                background:rgba({_hex_to_rgb(ACCENT)},0.08);border-radius:8px;margin-bottom:16px">
      <div style="font-size:15px;font-weight:700;color:white;margin-bottom:6px">
        Benchmark en cours
      </div>
      <div style="font-size:13px;color:{TEXT_DIM};line-height:1.55">
        Le système mesure la vitesse avant de lancer l'optimisation.
        La progression détaillée commencera après le benchmark.
      </div>
    </div>
    """, unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(card("Phase", "Benchmark", "accent"), unsafe_allow_html=True)
    with c2:
        st.markdown(card("Workers", f"{workers}", "white"), unsafe_allow_html=True)
    with c3:
        st.markdown(card("Dernière maj", update_label, "white"), unsafe_allow_html=True)
    with c4:
        st.markdown(card("ETA", "après benchmark", "white"), unsafe_allow_html=True)

    if stale:
        st.warning(
            "Benchmark potentiellement bloqué : aucune mise à jour récente du fichier progress.json. "
            "Le process peut être simplement lent sur un gros historique."
        )

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    btn_c1, btn_c2, _ = st.columns([1, 1, 4])
    with btn_c1:
        if st.button("⏹  Arrêter proprement", width="stretch", key="prog_bench_stop"):
            _write_stop_flag(run_id)
            st.toast("Signal d'arrêt envoyé…", icon="⏹")
    with btn_c2:
        if st.button("🔄  Actualiser", width="stretch", key="prog_bench_refresh"):
            st.rerun()


def _list_active_jobs() -> list:
    try:
        return opt_store.list_active_jobs()
    except Exception:
        return []


def _remember_job_for_tracking(job: dict) -> None:
    job_id = job.get("job_id") or job.get("run_id")
    if not job_id:
        return

    st.session_state["opt_current_run_id"] = job_id
    st.session_state["opt_view_run_id"] = job_id

    job_dir = job.get("job_dir") or _job_dir_for_run(job_id)
    if job_dir:
        st.session_state.setdefault("opt_job_dirs", {})[job_id] = job_dir


def _show_results_for_run(run_id: str, job_dir: str = None) -> None:
    if not run_id:
        return
    st.session_state["opt_view_run_id"] = run_id
    if job_dir:
        st.session_state.setdefault("opt_job_dirs", {})[run_id] = job_dir
    st.session_state["opt_focus_results_tab"] = True


def _render_active_jobs_reconnect_panel(active_jobs: list = None, key_prefix: str = "active_jobs") -> bool:
    jobs = active_jobs if active_jobs is not None else _list_active_jobs()
    if not jobs:
        return False

    title = "Un job est en cours" if len(jobs) == 1 else f"{len(jobs)} jobs sont en cours"
    st.markdown(f"""
    <div style="padding:16px;border:1px solid rgba({_hex_to_rgb(ACCENT)},0.35);
                background:rgba({_hex_to_rgb(ACCENT)},0.08);border-radius:8px;margin-bottom:14px">
      <div style="font-size:15px;font-weight:700;color:white;margin-bottom:4px">{title}</div>
      <div style="font-size:12px;color:{TEXT_DIM}">
        Suivi retrouvé depuis <code>results/job_xxx/progress.json</code>.
      </div>
    </div>
    """, unsafe_allow_html=True)

    for idx, job in enumerate(jobs):
        _render_active_job_card(job, key_prefix=f"{key_prefix}_{idx}")

    return True


def _render_active_job_card(job: dict, key_prefix: str) -> None:
    job_id   = job.get("job_id", "")
    job_dir  = job.get("job_dir", "")
    status   = job.get("status", "unknown")
    progress = float(job.get("progress_pct", 0) or 0)
    elapsed  = job.get("duration_seconds", 0) or 0
    tested   = job.get("combinations_tested", 0) or 0
    total    = job.get("total_combinations", 0) or 0
    config   = _load_job_config(job_dir)
    asset, timeframe = _infer_asset_timeframe(config)
    tested_label, tested_sub = _format_processed_total(tested, total)
    tested_text = f"{tested_label} tests traités"
    if tested_sub:
        tested_text += f" ({tested_sub})"

    st.markdown(f"""
    <div class="history-card" style="margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;position:relative">
        <div>
          <div class="h-name" style="font-family:'JetBrains Mono',monospace;font-size:13px">
            {_safe_html(job_id)}
          </div>
          <div class="h-meta" style="margin-top:4px">
            {_safe_html(_status_ui(status)["label"])} · Progression {progress:.1f}% · Écoulé {format_duration(elapsed)}
          </div>
          <div class="h-meta" style="margin-top:2px">
            Actif {_safe_html(asset)} · Timeframe {_safe_html(timeframe)} · {_safe_html(tested_text)}
          </div>
        </div>
        {_status_badge(status)}
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.progress(max(0.0, min(1.0, progress / 100)))
    c1, c2, c3, _ = st.columns([1.35, 1.25, 1.25, 4.15])
    with c1:
        if st.button("Reprendre le suivi", key=f"{key_prefix}_resume_{job_id}", width="stretch"):
            _remember_job_for_tracking(job)
            st.toast(f"Suivi repris pour {job_id[-8:]}", icon="⏳")
            st.rerun()
    with c2:
        if st.button("Voir dans Résultats", key=f"{key_prefix}_view_{job_id}", width="stretch"):
            _remember_job_for_tracking(job)
            _show_results_for_run(job_id, job_dir or _job_dir_for_run(job_id))
            st.toast("Job chargé — ouvre l'onglet Résultats.", icon="📊")
            st.rerun()
    with c3:
        if st.button("Arrêter proprement", key=f"{key_prefix}_stop_{job_id}", width="stretch"):
            opt_store.write_stop_flag(job_id, job_dir=job_dir or _job_dir_for_run(job_id))
            st.toast("Signal d'arrêt envoyé…", icon="⏹")

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)


def _read_json_file(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _load_job_config(job_dir: str) -> dict:
    if not job_dir:
        return {}
    return _read_json_file(os.path.join(job_dir, "config_used.json"))


def _infer_asset_timeframe(config: dict) -> tuple:
    asset = (
        config.get("asset")
        or config.get("symbol")
        or config.get("instrument")
        or config.get("ticker")
        or config.get("strategy_symbol")
    )
    timeframe = (
        config.get("timeframe")
        or config.get("time_frame")
        or config.get("period")
        or config.get("tf")
    )

    data_file = str(config.get("data_file", ""))
    base_name = os.path.basename(data_file)
    compact = base_name.lower().replace("_", "").replace("-", "")

    if not asset and base_name:
        if "nasdaq" in compact or "us100" in compact:
            asset = "US100 / NASDAQ"
        else:
            asset = os.path.splitext(base_name)[0]

    if not timeframe and base_name:
        if "m3" in compact or "3m" in compact:
            timeframe = "M3"

    return asset or "—", timeframe or "—"


def _load_result_context(run_id: str) -> tuple:
    """
    Retourne (meta, job_dir, config, job_summary).
    job_dir vaut None pour l'ancien mode optimization_history/.
    """
    if not _is_job_id(run_id):
        return opt_store.load_meta(run_id), None, {}, {}

    job = _find_job_summary(run_id)
    job_dir = job.get("job_dir", "")
    meta = opt_store.load_job(run_id) if job_dir else None

    if not meta and job:
        meta = {
            "run_id": run_id,
            "job_id": run_id,
            "job_dir": job_dir,
            "date": job.get("date", ""),
            "strategy_name": job.get("strategy_name", ""),
            "mode": job.get("mode", ""),
            "status": job.get("status", "unknown"),
            "total_combinations": job.get("total_combinations", 0),
            "combinations_tested": job.get("combinations_tested", 0),
            "duration_seconds": job.get("duration_seconds", 0),
            "best_score": job.get("best_score", 0),
            "workers_used": job.get("workers_used", 1),
            "progress_pct": job.get("progress_pct", 0),
            "variables_tested": job.get("variables_tested", []),
            "top_100": [],
        }

    if meta and job:
        for key in (
            "status", "progress_pct", "total_combinations", "combinations_tested",
            "duration_seconds", "best_score", "workers_used", "variables_tested",
        ):
            if key in job:
                meta[key] = job.get(key)
        meta["job_dir"] = job_dir

    config = _load_job_config(job_dir)
    return meta, job_dir, config, job


def _fmt_file_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} o"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} Ko"
    return f"{size_bytes / (1024 * 1024):.1f} Mo"


def _render_job_downloads(job_dir: str, job_id: str):
    if not job_dir or not os.path.isdir(job_dir):
        st.info("Dossier de job introuvable.")
        return

    for filename, label, mime in _JOB_DOWNLOAD_FILES:
        path = os.path.join(job_dir, filename)
        cols = st.columns([2.4, 1.1, 1.4])
        exists = os.path.exists(path)

        with cols[0]:
            st.markdown(f"**{label}**  \n`{filename}`")
        with cols[1]:
            st.caption(_fmt_file_size(os.path.getsize(path)) if exists else "Absent")
        with cols[2]:
            if exists:
                with open(path, "rb") as f:
                    data = f.read()
                st.download_button(
                    "Télécharger",
                    data,
                    file_name=filename,
                    mime=mime,
                    key=f"job_download_{job_id}_{filename.replace('.', '_')}",
                    width="stretch",
                )
            else:
                st.button(
                    "Indisponible",
                    disabled=True,
                    key=f"job_missing_{job_id}_{filename.replace('.', '_')}",
                    width="stretch",
                )


def _render_results_diagnostic(status: str, df_results: pd.DataFrame, valid_count: int,
                               n_filtered: int, best_score: float, n_tested: int,
                               quick_validation: bool = False) -> None:
    status = str(status or "").lower()
    if status in ("created", "benchmarking", "running"):
        _diagnostic_card(
            "Job encore en cours",
            "Les résultats peuvent être incomplets. La synthèse se mettra à jour quand de nouvelles combinaisons seront traitées.",
            tone="info",
        )
        return

    no_trade_count = _reason_count(df_results, ("no trade", "aucun trade", "0 trade"))

    if quick_validation:
        if no_trade_count or valid_count <= 0:
            _diagnostic_card(
                "Aucun signal exploitable",
                "Aucun signal exploitable n'a été détecté sur cet échantillon réduit. "
                "Ce n'est pas une erreur technique : le test rapide valide surtout que le pipeline fonctionne.",
                tone="info",
            )
        else:
            st.caption(
                "Mode validation rapide : les fichiers ont été générés correctement, "
                "mais les résultats ne sont pas représentatifs d'une vraie optimisation."
            )
        return

    if valid_count > 0 and best_score > 0:
        if n_filtered:
            st.caption(
                f"{n_filtered:,} test{'s' if n_filtered > 1 else ''} ont été filtrés. "
                "C'est normal si certains réglages ne génèrent pas assez de trades ou ne passent pas les critères."
            )
        return

    if no_trade_count:
        body = (
            "Les paramètres testés n'ont généré aucun trade exploitable. "
            "Ce n'est pas une erreur technique : la stratégie n'a simplement pas trouvé de signal dans ces conditions. "
            "Essaie ensuite d'élargir les paramètres ou de choisir une période différente."
        )
    elif n_filtered:
        body = (
            "Les tests ont été filtrés car ils n'ont pas passé les critères de robustesse. "
            "Ce n'est pas une erreur technique. Essaie ensuite d'élargir les paramètres ou d'assouplir les filtres."
        )
    elif n_tested and best_score <= 0:
        body = (
            "Des tests ont bien été effectués, mais aucun réglage n'a obtenu un score utile. "
            "Essaie ensuite une plage de paramètres plus large ou des filtres moins stricts."
        )
    else:
        body = (
            "Aucun résultat exploitable n'est disponible pour ce job. "
            "Vérifie le statut du job, puis ouvre les logs si le job est terminé ou en erreur."
        )

    _diagnostic_card("Aucun champion trouvé", body, tone="warning")


def _render_results_tab():
    # Quel run afficher ?
    run_id = st.session_state.get("opt_view_run_id") or st.session_state.get("opt_current_run_id")

    if not run_id:
        st.markdown(f"""
        <div class="h-empty">
          <div style="font-size:48px;margin-bottom:14px;opacity:0.5">📊</div>
          <div style="font-size:15px;font-weight:600;color:{TEXT};margin-bottom:6px">
            Aucun résultat à afficher
          </div>
          <div style="font-size:13px;max-width:380px;line-height:1.55">
            Lancez une optimisation ou chargez un run depuis
            <strong>📂 Historique Runs</strong>.
          </div>
        </div>
        """, unsafe_allow_html=True)
        return

    meta, job_dir, job_config, job_summary = _load_result_context(run_id)
    if not meta:
        st.info(f"Run ou job `{run_id}` introuvable.")
        return

    top_100 = meta.get("top_100", [])
    report  = meta.get("report", {})
    sens    = meta.get("sensitivity", {})
    asset, timeframe = _infer_asset_timeframe(job_config)
    df_results = opt_store.load_results_csv(run_id, job_dir=job_dir)
    if df_results is None:
        df_results = pd.DataFrame()

    # ── Résumé header ─────────────────────────────────────────
    status_str  = meta.get("status", "completed")
    n_total     = meta.get("total_combinations", 0)
    n_tested    = meta.get("combinations_tested", 0)
    if not n_tested and df_results is not None and not df_results.empty:
        n_tested = len(df_results)
    n_filtered  = meta.get("combinations_filtered_out", 0) or _count_filtered_rows(df_results)
    duration    = meta.get("duration_seconds", 0)
    mode        = meta.get("mode", "")
    progress    = meta.get("progress_pct", job_summary.get("progress_pct", 100 if status_str == "completed" else 0))
    best        = top_100[0] if top_100 else {}
    best_score  = best.get("score", 0)
    if not best_score:
        best_score = meta.get("best_score", job_summary.get("best_score", 0))
    best_score = float(best_score or 0)
    best_stats  = best.get("stats", {})
    valid_count = len(top_100)
    if not valid_count and df_results is not None and not df_results.empty and "score" in df_results.columns:
        valid_count = int(pd.to_numeric(df_results["score"], errors="coerce").fillna(0).gt(0).sum())
    quick_validation = _is_quick_validation(job_config, meta)
    processed_label, processed_sub = _format_processed_total(n_tested, n_total)
    verdict = _score_verdict(float(best_score or 0), status_str, valid_count, quick_validation)
    status_info = _status_ui(status_str)
    source_label = "Job" if job_dir else "Run"
    details = [
        f"Mode {mode}" if mode else "",
        f"{processed_label} tests traités",
        f"{n_filtered:,} filtrés" if n_filtered else "",
        format_duration(duration),
    ]
    if processed_sub:
        details.insert(2, processed_sub)
    if job_dir:
        details.extend([
            f"Actif {asset}",
            f"Timeframe {timeframe}",
            f"Progression {float(progress or 0):.1f}%",
        ])
    details = " · ".join(d for d in details if d)
    is_quick_completed = quick_validation and str(status_str or "").lower() == "completed"
    if is_quick_completed:
        title_text = "Test technique terminé"
        subtitle_text = (
            "Le pipeline fonctionne correctement. Les résultats ne sont pas représentatifs "
            "car le mode validation rapide était activé."
        )
    else:
        title_text = f"🔬 {_safe_html(meta.get('strategy_name', ''))} — {source_label} {_safe_html(run_id[-8:])}"
        subtitle_text = f"{_safe_html(details)} &nbsp;·&nbsp; {valid_count} résultats valides"

    st.markdown(f"""
    <div class="dash-header" style="margin-bottom:16px">
      <div>
        <div class="dash-title">{title_text}</div>
        <div class="dash-subtitle">
          {subtitle_text}
        </div>
      </div>
      <div style="text-align:right">
        <div style="font-size:34px;font-weight:800;color:{_score_color(best_score)};letter-spacing:-1px">
          {best_score:.1f}
        </div>
        <div style="font-size:11px;color:{TEXT_DIM}">Score meilleur réglage · {_safe_html(verdict)}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    s1, s2, s3, s4, s5, s6 = st.columns(6)
    with s1:
        st.markdown(card("Statut", status_info["label"], "white"), unsafe_allow_html=True)
    with s2:
        st.markdown(card("Meilleur score", f"{float(best_score or 0):.1f}", _score_class(float(best_score or 0))),
                    unsafe_allow_html=True)
    with s3:
        st.markdown(card("Tests traités", processed_label, "white", sub=processed_sub), unsafe_allow_html=True)
    with s4:
        st.markdown(card("Résultats valides", f"{valid_count:,}", "green" if valid_count else "red"),
                    unsafe_allow_html=True)
    with s5:
        st.markdown(card("Tests filtrés", f"{int(n_filtered or 0):,}", "accent" if n_filtered else "white"),
                    unsafe_allow_html=True)
    with s6:
        st.markdown(card("Verdict", verdict, "white"), unsafe_allow_html=True)

    _render_results_diagnostic(status_str, df_results, valid_count, int(n_filtered or 0),
                               float(best_score or 0), int(n_tested or 0), quick_validation)

    tabs = st.tabs(
        ["🥇 Top résultats", "📋 Données avancées", "📝 Rapport", "📦 Fichiers job"]
        if job_dir else
        ["🥇 Top résultats", "📋 Données avancées", "📝 Rapport"]
    )
    res_top10, res_all, res_report = tabs[:3]
    res_files = tabs[3] if job_dir else None

    # ── Top 10 ────────────────────────────────────────────────
    with res_top10:
        if valid_count <= 0:
            _diagnostic_card(
                "Aucun résultat valide sur ce run",
                "Consulte Données avancées pour voir les tests filtrés et les raisons de rejet.",
                tone="info",
            )
        elif top_100:
            simple_rows = []
            for entry in top_100[:10]:
                stats = entry.get("stats", {})
                simple_rows.append({
                    "Rang": entry.get("rank", ""),
                    "Score": round(float(entry.get("score", 0) or 0), 1),
                    "Trades": stats.get("total_trades", stats.get("n_trades", "—")),
                    "Win rate": f"{float(stats.get('win_rate', 0) or 0):.1f}%",
                    "Profit factor": (
                        "∞" if isinstance(stats.get("profit_factor", 0), float)
                        and math.isinf(stats.get("profit_factor", 0))
                        else f"{float(stats.get('profit_factor', 0) or 0):.2f}"
                    ),
                    "Max DD": f"{float(stats.get('max_dd_pct', 0) or 0):.1f}%",
                    "Gain": f"{float(stats.get('net_ret_pct', 0) or 0):+.1f}%",
                })
            st.dataframe(pd.DataFrame(simple_rows), width="stretch", hide_index=True)
            with st.expander("Détail technique du top", expanded=False):
                _render_top10(top_100[:10], sens, meta, key_prefix=run_id)
        elif df_results is not None and not df_results.empty:
            df_simple = df_results.copy()
            if "score" in df_simple.columns:
                df_simple["score"] = pd.to_numeric(df_simple["score"], errors="coerce").fillna(0)
                df_simple = df_simple.sort_values("score", ascending=False)
            wanted = [
                c for c in (
                    "score", "total_trades", "n_trades", "win_rate", "profit_factor",
                    "max_dd_pct", "net_ret_pct", "filter_reason", "rejection_reason"
                )
                if c in df_simple.columns
            ]
            st.dataframe(df_simple[wanted].head(10) if wanted else df_simple.head(10),
                         width="stretch", hide_index=True)
        else:
            st.info("Aucun top résultat disponible pour ce job.")

    # ── Données avancées ──────────────────────────────────────
    with res_all:
        if df_results.empty:
            st.info("CSV de résultats non disponible.")
        else:
            with st.expander("Tableau brut complet", expanded=False):
                st.dataframe(df_results, width="stretch", height=430, hide_index=True)
                csv_bytes = df_results.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "⬇ Télécharger tous les résultats (.csv)",
                    csv_bytes, f"{run_id}_results.csv", "text/csv",
                    key=f"results_csv_{run_id}",
                )

    # ── Rapport ────────────────────────────────────────────────
    with res_report:
        if report:
            _render_report(report, sens)
        else:
            st.info("Rapport non disponible pour ce run.")

    if res_files is not None:
        with res_files:
            _render_job_downloads(job_dir, run_id)


def _render_top10(top10: list, sens: dict, meta: dict, key_prefix: str = ""):
    tt_enabled = meta.get("train_test", {}).get("enabled", False)

    for entry in top10:
        rank    = entry.get("rank", 0)
        score   = entry.get("score", 0)
        stats   = entry.get("stats", {})
        params  = entry.get("params", {})
        warns   = entry.get("warnings", [])
        sc_tr   = entry.get("score_train", score)
        sc_te   = entry.get("score_test", score)
        degrad  = entry.get("degradation_pct", 0)
        ov_alert = entry.get("overfitting_alert", False)

        pf_raw = stats.get("profit_factor", 0)
        pf_str = f"{pf_raw:.2f}" if not (isinstance(pf_raw, float) and math.isinf(pf_raw)) else "∞"

        with st.container():
            hdr = st.columns([0.3, 0.7, 1, 1, 1, 1, 1, 1])
            labels = ["#", "Score", "Trades", "Win%", "PF", "MaxDD", "Gain%", "R²"]
            values = [
                str(rank),
                f"{score:.1f}",
                str(stats.get("total_trades", "—")),
                f"{stats.get('win_rate', 0):.1f}%",
                pf_str,
                f"{stats.get('max_dd_pct', 0):.1f}%",
                f"{stats.get('net_ret_pct', 0):+.1f}%",
                f"{stats.get('equity_r_squared', 0):.2f}",
            ]
            colors = [
                TEXT_DIM, _score_color(score),
                TEXT, TEXT, TEXT,
                RED if stats.get("max_dd_pct", 0) > 20 else TEXT,
                GREEN if stats.get("net_ret_pct", 0) > 0 else RED,
                TEXT,
            ]
            for col, lbl, val, clr in zip(hdr, labels, values, colors):
                with col:
                    st.markdown(
                        f'<div style="font-size:10px;color:{TEXT_DIM};font-weight:600">{lbl}</div>'
                        f'<div style="font-size:15px;font-weight:700;color:{clr}">{val}</div>',
                        unsafe_allow_html=True,
                    )

            # Train/test si activé
            if tt_enabled:
                ov_color = RED if ov_alert else GREEN
                ov_text  = "⚠️ OVERFITTING" if ov_alert else "✅ OK"
                st.markdown(
                    f'<div style="font-size:11px;color:{TEXT_DIM};margin-top:4px">'
                    f'Train: <strong style="color:{TEXT}">{sc_tr:.1f}</strong> → '
                    f'Test: <strong style="color:{TEXT}">{sc_te:.1f}</strong> · '
                    f'Dégradation: <strong style="color:{ov_color}">{degrad:.1f}% {ov_text}</strong>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            # Paramètres
            params_str = " · ".join(f"**{k}**={v}" for k, v in list(params.items())[:8])
            st.markdown(
                f'<div style="font-size:11px;color:{TEXT_DIM};margin-top:4px;margin-bottom:4px">'
                f'{params_str}</div>',
                unsafe_allow_html=True,
            )

            # Avertissements
            for w in warns[:2]:
                st.markdown(
                    f'<div style="font-size:11px;color:#f59e0b">⚠ {w}</div>',
                    unsafe_allow_html=True,
                )

            # Bouton relancer backtest
            if st.button(
                "🔁 Relancer ce backtest",
                key=f"rerun_top_{key_prefix}_{rank}",
                width="content",
            ):
                st.session_state["opt_rerun_params"] = params
                st.toast(f"Paramètres #{rank} chargés. Lance le backtest depuis la barre latérale.",
                         icon="🔁")

            st.markdown("<hr style='border-color:var(--border);margin:8px 0'>", unsafe_allow_html=True)

    # ── Analyse de sensibilité ─────────────────────────────────
    if sens:
        st.markdown("<div class='section-title' style='margin-top:16px'>Sensibilité des paramètres</div>",
                    unsafe_allow_html=True)
        sens_sorted = sorted(sens.items(), key=lambda x: x[1], reverse=True)
        names  = [k for k, _ in sens_sorted]
        values = [v for _, v in sens_sorted]
        colors = [GREEN if v >= 0.15 else TEXT_DIM for v in values]

        fig = go.Figure(go.Bar(
            x=names, y=values,
            marker=dict(color=colors, line=dict(width=0)),
            text=[f"{v:.2f}" for v in values],
            textposition="auto",
            textfont=dict(size=10, color="white"),
        ))
        cfg = go.Layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color=TEXT, family="Inter", size=11),
            margin=dict(l=8, r=8, t=10, b=8),
            height=180,
            yaxis=dict(showgrid=True, gridcolor=BORDER, zeroline=False),
            xaxis=dict(showgrid=False),
        )
        fig.update_layout(cfg)
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        st.markdown(
            f"<div style='font-size:11px;color:{TEXT_DIM}'>"
            "Score ≥ 0.15 = paramètre sensible (influence forte sur le score)"
            "</div>", unsafe_allow_html=True,
        )


def _render_report(report: dict, sens: dict):
    categorie = report.get("categorie", "")
    resume    = report.get("resume", "")

    # En-tête
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
      {_category_badge(categorie)}
    </div>
    <div style="font-size:14px;color:{TEXT};line-height:1.65;margin-bottom:20px">
      {resume}
    </div>
    """, unsafe_allow_html=True)

    # Points forts / faibles
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("<div class='section-title'>✅ Points forts</div>", unsafe_allow_html=True)
        for pt in report.get("points_forts", []):
            st.markdown(
                f'<div style="padding:6px 0;border-bottom:1px solid var(--border);'
                f'font-size:12.5px;color:{TEXT}">'
                f'<span style="color:{GREEN}">✓</span> {pt}</div>',
                unsafe_allow_html=True,
            )
    with c2:
        st.markdown("<div class='section-title'>⚠️ Points faibles</div>", unsafe_allow_html=True)
        for pt in report.get("points_faibles", []):
            st.markdown(
                f'<div style="padding:6px 0;border-bottom:1px solid var(--border);'
                f'font-size:12.5px;color:{TEXT}">'
                f'<span style="color:#f59e0b">⚠</span> {pt}</div>',
                unsafe_allow_html=True,
            )

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    # Risque d'overfitting + paper trading
    r1, r2 = st.columns(2)
    with r1:
        risk_color = {
            "Faible": GREEN, "Modéré": "#f59e0b",
            "Élevé": RED, "Non évalué": TEXT_DIM,
        }.get(report.get("risque_overfitting", ""), TEXT_DIM)
        st.markdown(
            f'<div style="background:{CARD_BG};border:1px solid {BORDER};'
            f'border-radius:10px;padding:14px 16px">'
            f'<div style="font-size:11px;color:{TEXT_DIM};font-weight:600;'
            f'text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px">Risque overfitting</div>'
            f'<div style="font-size:18px;font-weight:700;color:{risk_color}">'
            f'{report.get("risque_overfitting", "N/A")}</div>'
            f'<div style="font-size:11.5px;color:{TEXT_DIM};margin-top:6px">'
            f'{report.get("raison_overfitting", "")}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with r2:
        paper_ok    = report.get("convient_paper_trading", False)
        paper_color = GREEN if paper_ok else RED
        paper_icon  = "✅" if paper_ok else "❌"
        st.markdown(
            f'<div style="background:{CARD_BG};border:1px solid {BORDER};'
            f'border-radius:10px;padding:14px 16px">'
            f'<div style="font-size:11px;color:{TEXT_DIM};font-weight:600;'
            f'text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px">Paper Trading</div>'
            f'<div style="font-size:18px;font-weight:700;color:{paper_color}">'
            f'{paper_icon} {"Envisageable" if paper_ok else "Déconseillé"}</div>'
            f'<div style="font-size:11.5px;color:{TEXT_DIM};margin-top:6px">'
            f'{report.get("raison_paper_trading", "")}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    # Variables sensibles
    vs  = report.get("variables_sensibles", [])
    vps = report.get("variables_peu_sensibles", [])
    if vs or vps:
        st.markdown("<div class='section-title'>📊 Sensibilité des paramètres</div>", unsafe_allow_html=True)
        if vs:
            st.markdown(
                f'<div style="font-size:12px;color:{GREEN};margin-bottom:4px">'
                f'<strong>Sensibles</strong> (à ne pas modifier sans re-tester) : '
                + ", ".join(vs) + "</div>",
                unsafe_allow_html=True,
            )
        if vps:
            st.markdown(
                f'<div style="font-size:12px;color:{TEXT_DIM}">'
                f'<strong>Peu sensibles</strong> (peuvent être ajustés librement) : '
                + ", ".join(vps) + "</div>",
                unsafe_allow_html=True,
            )

    # Recommandation finale
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    reco = report.get("recommandation_finale", "")
    if reco:
        st.markdown(
            f'<div style="background:linear-gradient(135deg,{CARD_BG} 0%,{BG_ALT} 100%);'
            f'border:1px solid {BORDER};border-radius:12px;padding:18px 22px;'
            f'font-size:13.5px;color:{TEXT};line-height:1.65">'
            f'<strong style="color:white">💡 Recommandation</strong><br>'
            f'{reco}'
            f'</div>',
            unsafe_allow_html=True,
        )


# ── Sous-onglet Historique Runs ────────────────────────────────────

def _render_jobs_history_section(jobs: list):
    st.markdown("### 📦 Jobs serveur")
    st.caption(f"{len(jobs)} job{'s' if len(jobs) != 1 else ''} dans `results/job_xxx/`")

    if not jobs:
        st.markdown(f"""
        <div class="h-empty" style="margin-bottom:22px">
          <div style="font-size:40px;margin-bottom:12px;opacity:0.5">📦</div>
          <div style="font-size:14px;font-weight:600;color:{TEXT};margin-bottom:4px">
            Aucun job serveur trouvé
          </div>
          <div style="font-size:12px;color:{TEXT_DIM}">
            Les jobs lancés en CLI apparaîtront ici après création dans results/job_xxx/.
          </div>
        </div>
        """, unsafe_allow_html=True)
        return

    for job in jobs:
        job_id     = job.get("job_id", "")
        job_dir    = job.get("job_dir", "")
        status     = job.get("status", "unknown")
        best_score = job.get("best_score", 0) or 0
        n_tested   = job.get("combinations_tested", 0) or 0
        n_total    = job.get("total_combinations", 0) or 0
        duration   = job.get("duration_seconds", 0) or 0
        progress   = float(job.get("progress_pct", 0) or 0)
        mode       = job.get("mode", "")
        variables  = job.get("variables_tested", []) or []
        config     = _load_job_config(job_dir)
        asset, timeframe = _infer_asset_timeframe(config)
        quick_validation = _is_quick_validation(config, job)
        files_ok = [
            filename for filename, _, _ in _JOB_DOWNLOAD_FILES
            if job_dir and os.path.exists(os.path.join(job_dir, filename))
        ]
        try:
            is_active = opt_store.is_active_job(job)
        except Exception:
            is_active = False
        tested_label, tested_sub = _format_processed_total(n_tested, n_total)
        status_info = _status_ui(status)
        valid_hint = 1 if float(best_score or 0) > 0 else 0
        verdict = _score_verdict(float(best_score or 0), status, valid_hint, quick_validation)
        run_type = "Test local rapide" if quick_validation else "Optimisation complète"
        variables_label = ", ".join(variables[:4]) if variables else "—"
        if len(variables) > 4:
            variables_label += "…"

        with st.container(border=True):
            head_left, head_right = st.columns([5, 1.7], vertical_alignment="top")
            with head_left:
                st.markdown(f"**`{job_id}`**")
                st.caption(
                    f"{job.get('strategy_name', '') or 'Stratégie inconnue'} · "
                    f"{_fmt_date(job.get('date', ''))} · {run_type}"
                )
                st.caption(
                    f"Actif {asset} · Timeframe {timeframe} · Mode {mode or '—'} · "
                    f"Variables : {variables_label} · Fichiers : {len(files_ok)}/{len(_JOB_DOWNLOAD_FILES)}"
                )
            with head_right:
                st.markdown(f"{status_info['icon']} **{status_info['label']}**")

            m1, m2, m3, m4, m5, m6 = st.columns(6)
            with m1:
                st.metric("Type", run_type)
            with m2:
                st.metric("Verdict", verdict)
            with m3:
                st.metric("Meilleur score", f"{float(best_score):.1f}")
            with m4:
                st.metric("Tests traités", tested_label)
                if tested_sub:
                    st.caption(tested_sub)
            with m5:
                st.metric("Durée", format_duration(duration))
            with m6:
                st.metric("Workers", job.get("workers_used", 1))

            st.progress(max(0.0, min(1.0, progress / 100)), text=f"Progression {progress:.1f}%")

            if is_active:
                bc1, bc2, bc3, _ = st.columns([1, 1.35, 1.5, 4.15])
            else:
                bc1, bc2, _ = st.columns([1, 1.35, 5.65])

            with bc1:
                if st.button("Voir", key=f"job_view_{job_id}", width="stretch", type="secondary"):
                    _show_results_for_run(job_id, job_dir)
                    st.toast(f"Job {job_id[-8:]} chargé — passe sur l'onglet Résultats", icon="📊")
                    st.rerun()
            with bc2:
                archive_path = os.path.join(job_dir, "archive.zip") if job_dir else ""
                if archive_path and os.path.exists(archive_path):
                    with open(archive_path, "rb") as f:
                        archive_bytes = f.read()
                    st.download_button(
                        "Télécharger archive",
                        archive_bytes,
                        file_name="archive.zip",
                        mime="application/zip",
                        key=f"job_archive_{job_id}",
                        width="stretch",
                    )
                else:
                    st.button(
                        "Archive absente",
                        disabled=True,
                        key=f"job_archive_missing_{job_id}",
                        width="stretch",
                    )
            if is_active:
                with bc3:
                    if st.button("Reprendre le suivi", key=f"job_resume_{job_id}", width="stretch"):
                        _remember_job_for_tracking(job)
                        st.toast(f"Suivi repris pour {job_id[-8:]}", icon="⏳")
                        st.rerun()

        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)


def _render_opt_history_tab():
    jobs = opt_store.list_jobs()
    runs = opt_store.list_runs()

    _render_jobs_history_section(jobs)

    st.markdown("<hr style='border-color:var(--border);margin:18px 0 22px'>", unsafe_allow_html=True)

    st.markdown(f"""
    <div style="margin-bottom:20px">
      <div style="font-size:18px;font-weight:700;color:white;margin-bottom:4px">
        📂 Ancien historique des optimisations
      </div>
      <div style="font-size:13px;color:{TEXT_DIM}">
        {len(runs)} run{'s' if len(runs) != 1 else ''} dans <code>optimization_history/</code>
      </div>
    </div>
    """, unsafe_allow_html=True)

    if not runs:
        st.markdown(f"""
        <div class="h-empty">
          <div style="font-size:40px;margin-bottom:12px;opacity:0.5">🔬</div>
          <div style="font-size:14px;font-weight:600;color:{TEXT};margin-bottom:4px">
            Aucune optimisation sauvegardée
          </div>
          <div style="font-size:12px;color:{TEXT_DIM}">
            Lance une optimisation depuis l'onglet ⚙️ Configuration.
          </div>
        </div>
        """, unsafe_allow_html=True)
        return

    for run in runs:
        run_id     = run["run_id"]
        status     = run.get("status", "completed")
        best_score = run.get("best_score", 0)
        n_tested   = run.get("combinations_tested", 0)
        duration   = run.get("duration_seconds", 0)
        mode       = run.get("mode", "")
        variables  = run.get("variables_tested", [])

        status_colors = {
            "completed": (GREEN, "✅"),
            "stopped":   (TEXT_DIM, "⏹"),
            "running":   ("#f59e0b", "⚙️"),
            "error":     (RED, "❌"),
        }
        sc, si = status_colors.get(status, (TEXT_DIM, "?"))

        with st.container():
            st.markdown(f"""
            <div class="history-card">
              <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px;position:relative">
                <div>
                  <div class="h-name" style="font-family:'JetBrains Mono',monospace;font-size:13px">{run_id}</div>
                  <div class="h-meta">{run.get('strategy_name','')} · {run.get('date','')[:16]}</div>
                  <div class="h-meta" style="margin-top:2px">
                    Mode {mode} · Variables : {', '.join(variables[:4])}{'…' if len(variables)>4 else ''}
                  </div>
                </div>
                <span style="color:{sc};font-size:12px;font-weight:600">{si} {status}</span>
              </div>
              <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:14px;position:relative">
                <div class="h-stat">
                  <div class="h-stat-label">Meilleur score</div>
                  <div class="h-stat-value" style="color:{_score_color(best_score)}">{best_score:.1f}</div>
                </div>
                <div class="h-stat">
                  <div class="h-stat-label">Tests effectués</div>
                  <div class="h-stat-value">{n_tested:,}</div>
                </div>
                <div class="h-stat">
                  <div class="h-stat-label">Durée</div>
                  <div class="h-stat-value">{format_duration(duration)}</div>
                </div>
                <div class="h-stat">
                  <div class="h-stat-label">Workers</div>
                  <div class="h-stat-value">{run.get('workers_used', 1)}</div>
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)

            bc1, bc2, bc3 = st.columns([1, 1, 6])
            with bc1:
                if st.button("📊 Voir", key=f"opt_view_{run_id}", width="stretch", type="secondary"):
                    _show_results_for_run(run_id)
                    st.toast(f"Run {run_id[-8:]} chargé — passe sur l'onglet 📊 Résultats", icon="📊")
                    st.rerun()
            with bc2:
                if st.button("🗑 Supprimer", key=f"opt_del_{run_id}", width="stretch", type="secondary"):
                    st.session_state[f"opt_confirm_del_{run_id}"] = True

            if st.session_state.get(f"opt_confirm_del_{run_id}"):
                st.warning(f"Supprimer définitivement `{run_id}` ?")
                dc1, dc2, _ = st.columns([1, 1, 5])
                with dc1:
                    if st.button("Confirmer", key=f"opt_del_ok_{run_id}", width="stretch"):
                        opt_store.delete_run(run_id)
                        st.session_state.pop(f"opt_confirm_del_{run_id}", None)
                        st.rerun()
                with dc2:
                    if st.button("Annuler", key=f"opt_del_cancel_{run_id}",
                                  width="stretch", type="secondary"):
                        st.session_state.pop(f"opt_confirm_del_{run_id}", None)
                        st.rerun()

            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    strategies = load_strategies()
    if not strategies:
        st.error("Aucune stratégie trouvée dans le dossier `strategies/`.")
        return

    mod, params, initial_capital, spread, slip_in, slip_out, run_btn = build_sidebar(strategies)

    # ── Onglets ───────────────────────────────────────────────
    tab_backtest, tab_history, tab_new, tab_opt = st.tabs([
        "📊  Backtest",
        "📂  Historique",
        "➕  Nouvelle Stratégie",
        "🔬  Optimisation",
    ])

    # ════════════════════════════════════════════════════════════
    # ONGLET BACKTEST
    # ════════════════════════════════════════════════════════════
    with tab_backtest:

        # Placeholder si pas encore de résultats
        if "results" not in st.session_state and not run_btn:
            st.markdown(f"""
            <div style="
                display:flex; flex-direction:column; align-items:center; justify-content:center;
                height:60vh; color:{TEXT_DIM}; text-align:center;
            ">
              <div style="font-size:64px; margin-bottom:16px">📊</div>
              <div style="font-size:22px; font-weight:700; color:{TEXT}; margin-bottom:8px">
                Backtest Pro
              </div>
              <div style="font-size:14px; max-width:400px; line-height:1.6">
                Configurez vos paramètres dans la barre latérale
                et cliquez sur <strong style="color:white">▶ Lancer le Backtest</strong>.
              </div>
            </div>
            """, unsafe_allow_html=True)

        # Exécution du backtest
        if run_btn:
            df = load_csv()
            if df is None:
                st.error("Fichier nasdaq_3m.csv introuvable. Lancez d'abord get_data.py.")
                return

            strategy_instance = mod.Strategy()
            progress_bar = st.progress(0, text="Simulation en cours…")

            def update_progress(pct):
                progress_bar.progress(pct, text=f"Simulation… {pct*100:.0f}%")

            from engine import run_backtest
            trades_df, equity_df, stats = run_backtest(
                df,
                strategy_instance,
                params,
                initial_capital=float(initial_capital),
                spread=float(spread),
                slip_in=float(slip_in),
                slip_out=float(slip_out),
                progress_cb=update_progress,
            )

            progress_bar.empty()

            if stats.get("n_trades", 0) == 0:
                st.warning("Aucun trade généré. Vérifiez les paramètres.")
                return

            st.session_state["results"] = {
                "trades_df":   trades_df,
                "equity_df":   equity_df,
                "stats":       stats,
                "strat_name":  mod.STRATEGY_NAME,
                "initial_cap": initial_capital,
                "params":      params,
            }

            # ── Auto-save dans l'historique ───────────────────
            try:
                run_id = hs.save_run({
                    "strat_name":  mod.STRATEGY_NAME,
                    "initial_cap": initial_capital,
                    "spread":      spread,
                    "slip_in":     slip_in,
                    "slip_out":    slip_out,
                    "params":      params,
                    "stats":       stats,
                    "trades_df":   trades_df,
                    "equity_df":   equity_df,
                })
                st.toast(f"✓ Backtest sauvegardé dans l'historique", icon="💾")
            except Exception as e:
                st.warning(f"Sauvegarde dans l'historique impossible : {e}")

        # Affichage du dashboard
        if "results" in st.session_state:
            r = st.session_state["results"]
            render_dashboard(
                r["trades_df"],
                r["equity_df"],
                r["stats"],
                r["strat_name"],
                r["initial_cap"],
                r["params"],
            )

    # ════════════════════════════════════════════════════════════
    # ONGLET HISTORIQUE
    # ════════════════════════════════════════════════════════════
    with tab_history:
        render_history_tab()

    # ════════════════════════════════════════════════════════════
    # ONGLET NOUVELLE STRATÉGIE
    # ════════════════════════════════════════════════════════════
    with tab_new:
        render_new_strategy_tab()

    # ════════════════════════════════════════════════════════════
    # ONGLET OPTIMISATION
    # ════════════════════════════════════════════════════════════
    with tab_opt:
        render_optimization_tab(
            strategies, mod, params,
            initial_capital, spread, slip_in, slip_out,
        )


if __name__ == "__main__":
    main()
