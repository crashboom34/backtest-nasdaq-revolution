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
import sys
import subprocess
import uuid
import json
import math
import datetime
import urllib.parse
import history_store as hs
import optimization_store as opt_store
from optimizer import (
    ParamRange, ScoreWeights, FilterConfig, TrainTestConfig,
    OptimizationConfig, count_combinations, benchmark_speed,
    estimate_duration, format_duration,
)
from report_generator import generate_report
from path_resolver import to_relative_path

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
        run_btn = st.button("▶  LANCER LE BACKTEST", use_container_width=True)

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
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    with c2:
        pf = min(s["profit_factor"], 10)
        fig = make_donut(
            pf, 10,
            GREEN if pf >= 1 else RED, "#1e1e48",
            f"{s['profit_factor']:.2f}",
            "Ratio Gains / Pertes",
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

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
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

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
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    # ── Ligne 3 : Equity curve + Drawdown ────────────────────
    c1, c2 = st.columns([1, 1])

    with c1:
        st.markdown("<div class='section-title'>Performance brute — Transactions (equity)</div>", unsafe_allow_html=True)
        fig = make_equity_curve(equity_df, initial_capital)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.markdown("<div class='section-title' style='margin-top:8px'>Drawdown historique</div>", unsafe_allow_html=True)
        fig = make_dd_chart(equity_df)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

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
            use_container_width=True,
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
                if st.button("👁  Voir", key=f"view_{run['id']}", use_container_width=True, type="secondary"):
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
                if st.button("✏️  Renommer", key=f"rn_{run['id']}", use_container_width=True, type="secondary"):
                    st.session_state[f"renaming_{run['id']}"] = True
            with cols[2]:
                if st.button("🗑  Supprimer", key=f"del_{run['id']}", use_container_width=True, type="secondary"):
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
                    if st.button("OK", key=f"rn_ok_{run['id']}", use_container_width=True):
                        hs.rename_run(run["id"], new_name)
                        st.session_state.pop(f"renaming_{run['id']}", None)
                        st.rerun()
                with rc3:
                    if st.button("Annuler", key=f"rn_cancel_{run['id']}", use_container_width=True, type="secondary"):
                        st.session_state.pop(f"renaming_{run['id']}", None)
                        st.rerun()

            # Inline delete confirmation
            if st.session_state.get(f"confirm_del_{run['id']}"):
                st.warning(f"Supprimer définitivement **{run['name']}** ?")
                dc1, dc2, _ = st.columns([1.4, 1.4, 5])
                with dc1:
                    if st.button("Confirmer", key=f"del_ok_{run['id']}", use_container_width=True):
                        hs.delete_run(run["id"])
                        st.session_state.pop(f"confirm_del_{run['id']}", None)
                        st.rerun()
                with dc2:
                    if st.button("Annuler", key=f"del_cancel_{run['id']}", use_container_width=True, type="secondary"):
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
            label="",
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
        if st.button("📋  Copier le prompt", use_container_width=True, key="copy_prompt"):
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

def _make_run_id() -> str:
    from datetime import datetime
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    uid = str(uuid.uuid4())[:4]
    return f"opt_{ts}_{uid}"


def _launch_optimizer(run_id: str, config_dict: dict) -> subprocess.Popen:
    """Lance optimizer_process.py en subprocess et retourne le handle."""
    base       = os.path.dirname(os.path.abspath(__file__))
    opt_dir    = os.path.join(base, "optimization_history")
    os.makedirs(opt_dir, exist_ok=True)

    config_file = os.path.join(opt_dir, f"{run_id}.config.json")
    opt_store.atomic_write_json(config_file, config_dict)

    python_exe  = sys.executable
    script_path = os.path.join(base, "optimizer_process.py")
    proc = subprocess.Popen(
        [python_exe, script_path, run_id, config_file],
        cwd=base,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc


def _score_color(score: float) -> str:
    if score >= 70:
        return GREEN
    elif score >= 50:
        return "#f59e0b"
    else:
        return RED


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

    base      = os.path.dirname(os.path.abspath(__file__))
    data_file = os.path.join(base, "nasdaq_3m.csv")

    # ── Sous-onglets internes ──────────────────────────────────
    sub_config, sub_progress, sub_results, sub_history = st.tabs([
        "⚙️ Configuration",
        "⏳ Progression",
        "📊 Résultats",
        "📂 Historique Runs",
    ])

    # ════════════════════════════════════════════════════════════
    # SOUS-ONGLET A : CONFIGURATION
    # ════════════════════════════════════════════════════════════
    with sub_config:
        _render_config_tab(mod, params, initial_capital, spread, slip_in, slip_out,
                           data_file, strategies)

    # ════════════════════════════════════════════════════════════
    # SOUS-ONGLET B : PROGRESSION
    # ════════════════════════════════════════════════════════════
    with sub_progress:
        _render_progress_tab()

    # ════════════════════════════════════════════════════════════
    # SOUS-ONGLET C : RÉSULTATS
    # ════════════════════════════════════════════════════════════
    with sub_results:
        _render_results_tab()

    # ════════════════════════════════════════════════════════════
    # SOUS-ONGLET D : HISTORIQUE
    # ════════════════════════════════════════════════════════════
    with sub_history:
        _render_opt_history_tab()


# ── Sous-onglet Configuration ──────────────────────────────────────

def _render_config_tab(mod, params, initial_capital, spread, slip_in, slip_out,
                       data_file, strategies):

    schema       = getattr(mod, "PARAM_SCHEMA", {})
    default_params = dict(getattr(mod, "DEFAULT_PARAMS", params))

    # ── Mode validation rapide (F2) ───────────────────────────
    quick_mode = st.toggle(
        "⚡ Mode validation rapide",
        value=False,
        key="opt_quick_mode",
        help=(
            "Presets automatiques : 100 000 lignes max · 16 combinaisons max · "
            "1 worker · 3 échantillons benchmark · train/test désactivé. "
            "Idéal pour vérifier que le pipeline fonctionne avant un long run."
        ),
    )
    if quick_mode:
        st.warning(
            "⚡ **Mode validation rapide activé** — Ce mode sert à valider "
            "techniquement l'optimisateur, **pas à trouver le meilleur réglage final**. "
            "Les presets (100k lignes, 16 combos max, 1 worker, benchmark×3) sont appliqués automatiquement.",
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
            mn   = float(meta.get("min", 0))
            mx   = float(meta.get("max", dval * 3 or 10))
            stp  = float(meta.get("step", 1.0 if typ == "int" else 0.1))

            c0, c1, c2, c3, c4, c5 = st.columns([0.3, 2, 1, 1, 1, 1])
            with c0:
                enabled = st.checkbox("", value=False, key=f"opt_en_{k}")
            with c1:
                st.markdown(
                    f"<div style='padding-top:8px;font-size:12px;color:{TEXT}'>{lbl}</div>",
                    unsafe_allow_html=True,
                )
            with c2:
                min_v = st.number_input(
                    "", value=mn, key=f"opt_min_{k}", label_visibility="collapsed",
                    format="%.2f" if typ == "float" else "%d",
                )
            with c3:
                max_v = st.number_input(
                    "", value=mx, key=f"opt_max_{k}", label_visibility="collapsed",
                    format="%.2f" if typ == "float" else "%d",
                )
            with c4:
                step_v = st.number_input(
                    "", value=stp, key=f"opt_step_{k}", label_visibility="collapsed",
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
            st.markdown(
                f"<div style='font-size:11px;color:{TEXT_MUTED};font-style:italic'>"
                "Aucun filtre actif — jeu de données complet utilisé.</div>",
                unsafe_allow_html=True,
            )

    # ── Override mode validation rapide ──────────────────────
    _QUICK_MAX_COMBOS   = 16
    _QUICK_MAX_ROWS     = 100_000
    _QUICK_BENCHMARK    = 3
    _QUICK_N_WORKERS    = 1
    if quick_mode:
        # Remplacer les valeurs par les presets
        n_workers         = _QUICK_N_WORKERS
        benchmark_n_sample = _QUICK_BENCHMARK
        if opt_max_rows is None or opt_max_rows > _QUICK_MAX_ROWS:
            opt_max_rows  = _QUICK_MAX_ROWS

    enabled_ranges = [pr for pr in param_ranges if pr.enabled]

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
        status = opt_store.get_run_status(current_run_id)
        is_running = (status == "running")

    if not enabled_ranges:
        st.button("▶  Lancer l'optimisation", disabled=True,
                  use_container_width=True, key="opt_launch_disabled")
        st.info("Sélectionnez au moins un paramètre à optimiser.")
    elif is_running:
        st.button("▶  Optimisation en cours…", disabled=True,
                  use_container_width=True, key="opt_running_btn")
        if st.button("⏹  Arrêter proprement", use_container_width=True, key="opt_stop_btn"):
            opt_store.write_stop_flag(current_run_id)
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
                      use_container_width=True, key="opt_launch_blocked")
        elif st.button("▶  Lancer l'optimisation", use_container_width=True, key="opt_launch"):

            run_id = _make_run_id()
            st.session_state["opt_current_run_id"] = run_id

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
                "run_id":          run_id,
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
                "data_file":       to_relative_path(os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), "nasdaq_3m.csv")),
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

            _launch_optimizer(run_id, config_dict)
            st.success(f"✅ Optimisation lancée ! ID : `{run_id}`")
            st.toast("Passe sur l'onglet ⏳ Progression pour suivre l'avancement.", icon="🔬")


# ── Sous-onglet Progression ────────────────────────────────────────

def _render_progress_tab():
    run_id = st.session_state.get("opt_current_run_id")

    if not run_id:
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

    progress = opt_store.read_progress(run_id)
    if not progress:
        st.info(f"En attente des données pour `{run_id}`…")
        st.rerun()
        return

    status = progress.get("status", "unknown")

    # ── Header état ───────────────────────────────────────────
    status_colors = {
        "running":     ("#f59e0b", "⚙️ En cours"),
        "benchmarking": (ACCENT,   "📏 Benchmark…"),
        "completed":   (GREEN,     "✅ Terminé"),
        "stopped":     (TEXT_DIM,  "⏹ Arrêté"),
        "error":       (RED,       "❌ Erreur"),
    }
    sc, sl = status_colors.get(status, (TEXT_DIM, status))

    completed  = progress.get("completed", 0)
    total      = progress.get("total_combinations", 1)
    pct        = progress.get("progress_pct", 0.0)
    failed     = progress.get("failed", 0)
    best_score = progress.get("best_score", 0.0)
    elapsed    = progress.get("elapsed_seconds", 0)
    eta        = progress.get("eta_seconds")
    workers    = progress.get("workers_used", 1)
    bms        = progress.get("benchmark_ms_per_backtest", 0)

    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px">
      <span style="font-size:14px;font-weight:700;color:{sc}">{sl}</span>
      <span style="font-size:12px;color:{TEXT_DIM};font-family:'JetBrains Mono',monospace">{run_id}</span>
    </div>
    """, unsafe_allow_html=True)

    # Barre de progression
    if status == "running":
        st.progress(max(0.0, min(1.0, pct / 100)))

    # Métriques temps réel
    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.markdown(card("Terminés", f"{completed:,}", "white",
                         sub=f"/ {total:,} total"), unsafe_allow_html=True)
    with m2:
        st.markdown(card("Filtrés", f"{failed:,}", "accent"), unsafe_allow_html=True)
    with m3:
        st.markdown(card("Meilleur score", f"{best_score:.1f}", _score_color(best_score)[:7]),
                    unsafe_allow_html=True)
    with m4:
        st.markdown(card("Écoulé", format_duration(elapsed), "white"), unsafe_allow_html=True)
    with m5:
        eta_str = format_duration(eta) if eta else "—"
        st.markdown(card("ETA", eta_str, "white",
                         sub=f"{workers} worker{'s' if workers > 1 else ''} · {bms:.0f} ms/bt"),
                    unsafe_allow_html=True)

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
        if status == "running":
            if st.button("⏹  Arrêter proprement", use_container_width=True, key="prog_stop"):
                opt_store.write_stop_flag(run_id)
                st.toast("Signal d'arrêt envoyé…", icon="⏹")
        elif status in ("completed", "stopped"):
            if st.button("📊  Voir les résultats", use_container_width=True, key="prog_results"):
                st.session_state["opt_view_run_id"] = run_id
    with btn_c2:
        if st.button("🔄  Actualiser", use_container_width=True, key="prog_refresh"):
            st.rerun()

    # Auto-refresh si en cours
    if status in ("running", "benchmarking"):
        import time
        time.sleep(0.1)
        st.rerun()

    # Erreur éventuelle
    err = progress.get("error_message")
    if err:
        st.error(f"❌ Erreur : {err}")


# ── Sous-onglet Résultats ───────────────────────────────────────────

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

    meta = opt_store.load_meta(run_id)
    if not meta:
        st.info(f"Run `{run_id}` non encore terminé ou introuvable.")
        return

    top_100 = meta.get("top_100", [])
    if not top_100:
        st.warning("Aucun résultat valide dans ce run.")
        return

    report  = meta.get("report", {})
    sens    = meta.get("sensitivity", {})

    # ── Résumé header ─────────────────────────────────────────
    status_str  = meta.get("status", "completed")
    n_tested    = meta.get("combinations_tested", 0)
    n_filtered  = meta.get("combinations_filtered_out", 0)
    duration    = meta.get("duration_seconds", 0)
    mode        = meta.get("mode", "")
    best        = top_100[0]
    best_score  = best.get("score", 0)
    best_stats  = best.get("stats", {})

    st.markdown(f"""
    <div class="dash-header" style="margin-bottom:16px">
      <div>
        <div class="dash-title">🔬 {meta.get('strategy_name', '')} — Run {run_id[-8:]}</div>
        <div class="dash-subtitle">
          Mode {mode} · {n_tested:,} tests · {n_filtered:,} filtrés · {format_duration(duration)}
          &nbsp;·&nbsp; {len(top_100)} résultats valides
        </div>
      </div>
      <div style="text-align:right">
        <div style="font-size:34px;font-weight:800;color:{_score_color(best_score)};letter-spacing:-1px">
          {best_score:.1f}
        </div>
        <div style="font-size:11px;color:{TEXT_DIM}">Score meilleur réglage</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    res_top10, res_all, res_report = st.tabs(["🥇 Top 10", "📋 Tous les résultats", "📝 Rapport"])

    # ── Top 10 ────────────────────────────────────────────────
    with res_top10:
        _render_top10(top_100[:10], sens, meta)

    # ── Tous les résultats ────────────────────────────────────
    with res_all:
        df_results = opt_store.load_results_csv(run_id)
        if df_results.empty:
            st.info("CSV de résultats non disponible.")
        else:
            st.dataframe(df_results, use_container_width=True, height=400, hide_index=True)
            csv_bytes = df_results.to_csv(index=False).encode("utf-8")
            st.download_button(
                "⬇ Télécharger tous les résultats (.csv)",
                csv_bytes, f"{run_id}_results.csv", "text/csv",
            )

    # ── Rapport ────────────────────────────────────────────────
    with res_report:
        if report:
            _render_report(report, sens)
        else:
            st.info("Rapport non disponible pour ce run.")


def _render_top10(top10: list, sens: dict, meta: dict):
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
                key=f"rerun_top_{rank}",
                use_container_width=False,
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
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
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

def _render_opt_history_tab():
    runs = opt_store.list_runs()

    st.markdown(f"""
    <div style="margin-bottom:20px">
      <div style="font-size:18px;font-weight:700;color:white;margin-bottom:4px">
        📂 Historique des Optimisations
      </div>
      <div style="font-size:13px;color:{TEXT_DIM}">
        {len(runs)} run{'s' if len(runs) != 1 else ''} sauvegardé{'s' if len(runs) != 1 else ''}
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
                if st.button("📊 Voir", key=f"opt_view_{run_id}", use_container_width=True, type="secondary"):
                    st.session_state["opt_view_run_id"] = run_id
                    st.toast(f"Run {run_id[-8:]} chargé — passe sur l'onglet 📊 Résultats", icon="📊")
            with bc2:
                if st.button("🗑 Supprimer", key=f"opt_del_{run_id}", use_container_width=True, type="secondary"):
                    st.session_state[f"opt_confirm_del_{run_id}"] = True

            if st.session_state.get(f"opt_confirm_del_{run_id}"):
                st.warning(f"Supprimer définitivement `{run_id}` ?")
                dc1, dc2, _ = st.columns([1, 1, 5])
                with dc1:
                    if st.button("Confirmer", key=f"opt_del_ok_{run_id}", use_container_width=True):
                        opt_store.delete_run(run_id)
                        st.session_state.pop(f"opt_confirm_del_{run_id}", None)
                        st.rerun()
                with dc2:
                    if st.button("Annuler", key=f"opt_del_cancel_{run_id}",
                                  use_container_width=True, type="secondary"):
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
