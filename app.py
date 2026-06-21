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
from job_artifacts import (
    JOB_DOWNLOAD_SPECS,
    ensure_job_archive,
    list_archive_contents,
    list_job_download_files,
    read_job_file_bytes,
)
from job_annotations import (
    ANNOTATION_STATUSES,
    ANNOTATION_TAGS,
    JobAnnotation,
    clear_annotation,
    featured_jobs,
    filter_jobs_by_annotation,
    load_annotation,
    save_annotation,
)
from job_comparison import (
    best_job,
    comparison_issues,
    load_comparison_records,
    validate_selection,
)
from champion_report import (
    DECISION_REJECT,
    DECISION_RELAUNCH,
    ChampionReport,
    load_champion_report,
)
from champion_export import (
    champion_export_filename,
    render_champion_html,
    render_champion_markdown,
)
from champion_validation import (
    ChampionValidationSettings,
    VERDICT_INCOMPLETE,
    VERDICT_INSUFFICIENT,
    VERDICT_SERIOUS,
)
from validation_settings import (
    load_validation_settings,
    reset_validation_settings,
    save_validation_settings,
)
from job_launcher import (
    ActiveJobExistsError,
    clone_config_for_new_job,
    launch_optimizer_job,
)
from optimization_presets import (
    get_preset,
    is_quick_preset,
    preset_names,
)
from maintenance import (
    build_cleanup_plan,
    delete_items,
    disk_usage_for_base,
    list_job_items,
    list_pwcsv_data_items,
    select_cleanup_jobs,
)
from optimizer import (
    ParamRange, ScoreWeights, FilterConfig, TrainTestConfig,
    OptimizationConfig, count_combinations, benchmark_speed,
    estimate_duration, format_duration,
)
from report_generator import generate_report
from data_validator import validate_market_csv_bytes
from dashboard import build_dashboard_summary
from ui_components import help_panel, page_header, return_home_button, step_title
from path_resolver import (
    DEFAULT_ASSET, DEFAULT_TIMEFRAME,
    data_csv_target_path,
    list_available_assets, list_available_timeframes,
    normalize_asset, normalize_timeframe,
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

def _value_kw(key: str, value):
    return {} if key in st.session_state else {"value": value}

def _index_kw(key: str, index: int):
    return {} if key in st.session_state else {"index": index}

def _default_kw(key: str, value):
    return {} if key in st.session_state else {"default": value}

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


def _launch_config_as_new_job(config: dict, source_job_id: str = ""):
    """Relance une config existante dans un nouveau dossier job."""
    cfg = clone_config_for_new_job(config, source_job_id=source_job_id)
    return _launch_optimizer(cfg)


def _date_from_config(value):
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError:
        return None


def _load_config_into_widgets(config: dict) -> None:
    """Charge une config de job dans les widgets Optimisation sans lancer."""
    if not config:
        return

    preset_name = config.get("preset_name")
    if preset_name in preset_names(os.cpu_count()):
        st.session_state["opt_preset_name"] = preset_name
        st.session_state["_opt_last_preset_name"] = preset_name

    if config.get("asset"):
        st.session_state["opt_asset"] = config.get("asset")
    if config.get("timeframe"):
        st.session_state["opt_timeframe"] = config.get("timeframe")
    if config.get("mode"):
        st.session_state["opt_mode"] = config.get("mode")

    workers = config.get("workers", config.get("n_workers"))
    if workers is not None:
        st.session_state["opt_workers"] = int(workers)
    if config.get("benchmark_n_sample") is not None:
        st.session_state["opt_benchmark_n_sample"] = int(config.get("benchmark_n_sample"))

    max_combinations = config.get("max_combinations")
    st.session_state["opt_use_max_combinations"] = max_combinations is not None
    if max_combinations is not None:
        st.session_state["opt_max_combinations_widget"] = int(max_combinations)

    start_date = _date_from_config(config.get("opt_start_date"))
    end_date = _date_from_config(config.get("opt_end_date"))
    st.session_state["opt_use_start"] = start_date is not None
    st.session_state["opt_use_end"] = end_date is not None
    if start_date:
        st.session_state["opt_start_date_widget"] = start_date
    if end_date:
        st.session_state["opt_end_date_widget"] = end_date

    max_rows = config.get("max_rows")
    st.session_state["opt_use_maxrows"] = max_rows is not None
    if max_rows is not None:
        st.session_state["opt_max_rows_widget"] = int(max_rows)

    score_weights = config.get("score_weights", {}) or {}
    for key, widget_key in {
        "profit_factor": "sw_pf",
        "max_drawdown": "sw_dd",
        "total_trades": "sw_nt",
        "max_consecutive_losses": "sw_mc",
        "pct_gain": "sw_gain",
        "win_rate": "sw_wr",
        "avg_win_loss_ratio": "sw_ratio",
        "equity_regularity": "sw_eq",
        "recovery_factor": "sw_rf",
    }.items():
        if key in score_weights:
            st.session_state[widget_key] = float(score_weights[key])

    filters = config.get("filters", {}) or {}
    for key, widget_key, caster in (
        ("min_trades", "f_trades", int),
        ("max_drawdown_pct", "f_dd", float),
        ("min_profit_factor", "f_pf", float),
        ("max_consecutive_losses", "f_consec", int),
        ("min_win_rate", "f_wr", float),
    ):
        if key in filters:
            st.session_state[widget_key] = caster(filters[key])

    train_test = config.get("train_test", {}) or {}
    st.session_state["tt_enabled"] = bool(train_test.get("enabled", False))
    if train_test.get("split_method"):
        st.session_state["tt_method"] = train_test.get("split_method")
    if train_test.get("train_ratio") is not None:
        st.session_state["tt_ratio"] = float(train_test.get("train_ratio"))
    if train_test.get("split_date"):
        st.session_state["tt_date"] = str(train_test.get("split_date"))
    if train_test.get("alert_degradation_pct") is not None:
        st.session_state["tt_alert"] = int(train_test.get("alert_degradation_pct"))

    for pr in config.get("param_ranges", []) or []:
        name = pr.get("name")
        if not name:
            continue
        value_type = pr.get("param_type")
        numeric_values = [
            pr.get(field)
            for field in ("min_val", "max_val", "step")
            if pr.get(field) is not None
        ]
        legacy_integer_range = (
            value_type == "number"
            and numeric_values
            and all(float(value).is_integer() for value in numeric_values)
        )
        if value_type == "int" or legacy_integer_range:
            caster = int
        elif value_type in ("float", "number"):
            caster = float
        else:
            caster = lambda value: value
        st.session_state[f"opt_en_{name}"] = bool(pr.get("enabled", False))
        if pr.get("min_val") is not None:
            st.session_state[f"opt_min_{name}"] = caster(pr.get("min_val"))
        if pr.get("max_val") is not None:
            st.session_state[f"opt_max_{name}"] = caster(pr.get("max_val"))
        if pr.get("step") is not None:
            st.session_state[f"opt_step_{name}"] = caster(pr.get("step"))


def _duplicate_config_to_configuration(config: dict, source_job_id: str = "") -> None:
    _load_config_into_widgets(config)
    st.session_state["opt_focus_config_tab"] = True
    st.session_state["opt_config_loaded_from_job"] = source_job_id
    st.toast("Config dupliquée. Tu peux la modifier avant de lancer.", icon="📋")


def _render_job_config_actions(config: dict, source_job_id: str, key_prefix: str) -> None:
    if not config:
        return

    active_jobs = _list_active_jobs()
    if active_jobs:
        st.warning(
            "Un job est actif : la relance est bloquée pour éviter deux optimisations en parallèle.",
            icon=None,
        )

    a1, a2, _ = st.columns([1.35, 1.35, 4.3])
    with a1:
        if st.button(
            "Relancer même config",
            key=f"{key_prefix}_relaunch_{source_job_id}",
            width="stretch",
            disabled=bool(active_jobs),
        ):
            try:
                launched = _launch_config_as_new_job(config, source_job_id)
            except ActiveJobExistsError as exc:
                st.error(str(exc), icon=None)
                _render_active_jobs_reconnect_panel(exc.active_jobs, key_prefix=f"{key_prefix}_active")
            else:
                _remember_job_for_tracking({"job_id": launched.job_id, "job_dir": launched.job_dir})
                st.success(f"Nouveau job créé : `{launched.job_id}`")
                st.rerun()
    with a2:
        if st.button(
            "Dupliquer config",
            key=f"{key_prefix}_duplicate_{source_job_id}",
            width="stretch",
            type="secondary",
        ):
            _duplicate_config_to_configuration(config, source_job_id)
            st.rerun()


_ANNOTATION_ICONS = {
    "Champion": "🏆",
    "Favori": "⭐",
    "À revoir": "🔎",
    "Rejeté": "⛔",
}


def _annotation_label(annotation: JobAnnotation) -> str:
    if not annotation.status:
        return "Non classé"
    return f"{_ANNOTATION_ICONS.get(annotation.status, '')} {annotation.status}".strip()


def _render_annotation_summary(annotation: JobAnnotation, show_note: bool = True) -> None:
    if annotation.is_empty:
        st.caption("Aucune annotation utilisateur.")
        return
    st.markdown(f"**{_annotation_label(annotation)}**")
    if annotation.tags:
        st.caption("Tags : " + " · ".join(annotation.tags))
    if show_note and annotation.note:
        st.write(annotation.note)


def _reset_annotation_widget_state(job_id: str) -> None:
    for suffix in ("status", "tags", "note"):
        st.session_state.pop(f"annotation_{suffix}_{job_id}", None)


def _render_job_annotation_editor(job_id: str, job_dir: str, job_status: str) -> None:
    if not job_dir:
        return

    annotation = load_annotation(job_dir)
    with st.container(border=True):
        st.markdown("### Classement personnel")
        st.caption(
            "Cette information est enregistrée dans `job_notes.json`. "
            "Les résultats calculés restent inchangés."
        )
        _render_annotation_summary(annotation)

        if str(job_status or "").lower() != "completed":
            st.info("Le classement est disponible pour les jobs terminés.", icon=None)
            return

        status_key = f"annotation_status_{job_id}"
        tags_key = f"annotation_tags_{job_id}"
        note_key = f"annotation_note_{job_id}"
        status_options = list(ANNOTATION_STATUSES)

        with st.form(f"annotation_form_{job_id}"):
            status = st.selectbox(
                "Statut",
                options=status_options,
                **_index_kw(status_key, status_options.index(annotation.status)),
                format_func=lambda value: value or "Aucun statut",
                key=status_key,
            )
            tags = st.multiselect(
                "Tags",
                options=list(ANNOTATION_TAGS),
                **_default_kw(tags_key, list(annotation.tags)),
                key=tags_key,
            )
            note = st.text_area(
                "Note personnelle",
                **_value_kw(note_key, annotation.note),
                height=100,
                placeholder="Pourquoi ce job est intéressant, ou pourquoi il faut le revoir...",
                key=note_key,
            )
            save_col, clear_col, _ = st.columns([1.2, 1.2, 3.6])
            with save_col:
                save_clicked = st.form_submit_button("Enregistrer", width="stretch")
            with clear_col:
                clear_clicked = st.form_submit_button(
                    "Vider l'annotation",
                    width="stretch",
                    type="secondary",
                )

        if save_clicked:
            try:
                save_annotation(job_dir, status=status, note=note, tags=tags)
            except (OSError, ValueError) as exc:
                st.error(f"Annotation non enregistrée : {exc}", icon=None)
            else:
                _reset_annotation_widget_state(job_id)
                st.toast("Annotation enregistrée.", icon="💾")
                st.rerun()
        if clear_clicked:
            try:
                clear_annotation(job_dir)
            except (OSError, ValueError) as exc:
                st.error(f"Annotation non vidée : {exc}", icon=None)
            else:
                _reset_annotation_widget_state(job_id)
                st.toast("Annotation vidée.", icon="🧹")
                st.rerun()


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
    "stopping": {
        "label": "Arrêt demandé",
        "icon": "⏹",
        "color": "#f59e0b",
        "description": "Le signal d'arrêt propre a été envoyé. Le job va s'arrêter dès que possible.",
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
        if is_quick_preset(str(source.get("preset_name", ""))):
            return True
        if _as_bool(source.get("quick_validation_mode")):
            return True
        nested = source.get("config")
        if isinstance(nested, dict):
            if is_quick_preset(str(nested.get("preset_name", ""))):
                return True
            if _as_bool(nested.get("quick_validation_mode")):
                return True
    return False


def _preset_label(config: dict = None, meta: dict = None, fallback: str = "Ancien job") -> str:
    for source in (config or {}, meta or {}):
        if not isinstance(source, dict):
            continue
        name = source.get("preset_name")
        if name:
            return str(name)
        nested = source.get("config")
        if isinstance(nested, dict) and nested.get("preset_name"):
            return str(nested.get("preset_name"))
    if _is_quick_validation(config, meta):
        return "Test rapide local"
    return fallback


def _preset_description(config: dict = None, meta: dict = None) -> str:
    for source in (config or {}, meta or {}):
        if not isinstance(source, dict):
            continue
        desc = source.get("preset_description")
        if desc:
            return str(desc)
        nested = source.get("config")
        if isinstance(nested, dict) and nested.get("preset_description"):
            return str(nested.get("preset_description"))
    return ""


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

    page_header(
        "Optimisation",
        "Lance des jobs dans results/job_xxx/, suis la progression, puis télécharge les résultats.",
        "Moteur serveur local",
    )
    return_home_button(lambda: _switch_main_tab(MAIN_TAB_HOME), key="opt_return_home")

    # ── Sous-onglets internes ──────────────────────────────────
    subtab_labels = [
        "⚙️ Configuration",
        "⏳ Progression",
        "📊 Résultats",
        "📂 Historique Runs",
        "🏆 Champions / Favoris",
        "📋 Rapport Champion",
        "⚖️ Comparaison de jobs",
    ]
    if st.session_state.pop("opt_focus_config_tab", False):
        st.session_state["opt_subtabs"] = "⚙️ Configuration"
    elif st.session_state.pop("opt_focus_results_tab", False):
        st.session_state["opt_subtabs"] = "📊 Résultats"
    elif st.session_state.get("opt_subtabs") not in subtab_labels:
        st.session_state["opt_subtabs"] = "⚙️ Configuration"

    (
        sub_config,
        sub_progress,
        sub_results,
        sub_history,
        sub_featured,
        sub_champion_report,
        sub_comparison,
    ) = st.tabs(
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

    # ════════════════════════════════════════════════════════════
    # SOUS-ONGLET E : CHAMPIONS / FAVORIS
    # ════════════════════════════════════════════════════════════
    with sub_featured:
        if getattr(sub_featured, "open", False):
            _render_featured_jobs_tab()

    # ════════════════════════════════════════════════════════════
    # SOUS-ONGLET F : RAPPORT CHAMPION
    # ════════════════════════════════════════════════════════════
    with sub_champion_report:
        if getattr(sub_champion_report, "open", False):
            _render_champion_report_tab()

    # ════════════════════════════════════════════════════════════
    # SOUS-ONGLET G : COMPARAISON
    # ════════════════════════════════════════════════════════════
    with sub_comparison:
        if getattr(sub_comparison, "open", False):
            _render_job_comparison_tab()


# ── Sous-onglet Configuration ──────────────────────────────────────

def _render_config_tab(mod, params, initial_capital, spread, slip_in, slip_out,
                       strategies):

    schema       = getattr(mod, "PARAM_SCHEMA", {})
    default_params = dict(getattr(mod, "DEFAULT_PARAMS", params))

    active_jobs = _list_active_jobs()
    if active_jobs:
        _render_active_jobs_reconnect_panel(active_jobs, key_prefix="cfg_reconnect")
        st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)

    loaded_from_job = st.session_state.pop("opt_config_loaded_from_job", "")
    if loaded_from_job:
        st.success(
            f"Config du job `{loaded_from_job}` chargée dans le formulaire. "
            "Tu peux modifier les champs avant de lancer un nouveau job.",
            icon=None,
        )

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

    # ── Préréglage d'optimisation ─────────────────────────────
    st.markdown("<div class='section-title'>Préréglage d'optimisation</div>", unsafe_allow_html=True)
    preset_options = preset_names(os.cpu_count())
    if st.session_state.get("opt_preset_name") not in preset_options:
        st.session_state["opt_preset_name"] = preset_options[0]

    preset_name = st.selectbox(
        "Préréglage",
        options=preset_options,
        key="opt_preset_name",
        help="Choisis un niveau de calcul. Personnalisé laisse tous les champs modifiables.",
    )
    selected_preset = get_preset(preset_name, os.cpu_count())
    quick_mode = is_quick_preset(selected_preset.name)

    if st.session_state.get("_opt_last_preset_name") != selected_preset.name:
        st.session_state["_opt_last_preset_name"] = selected_preset.name
        if not selected_preset.manual_control:
            if selected_preset.workers is not None:
                st.session_state["opt_workers"] = int(selected_preset.workers)
            st.session_state["opt_benchmark_n_sample"] = int(selected_preset.benchmark_n_sample)
            st.session_state["opt_use_start"] = False
            st.session_state["opt_use_end"] = False
            st.session_state["opt_use_maxrows"] = selected_preset.max_rows is not None
            if selected_preset.max_rows is not None:
                st.session_state["opt_max_rows_widget"] = int(selected_preset.max_rows)
            st.session_state["opt_use_max_combinations"] = selected_preset.max_combinations is not None
            if selected_preset.max_combinations is not None:
                st.session_state["opt_max_combinations_widget"] = int(selected_preset.max_combinations)

    help_panel(
        selected_preset.name,
        selected_preset.description,
        "warning" if selected_preset.warning else "info",
    )
    if selected_preset.warning:
        st.warning(selected_preset.warning, icon=None)

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
        **_index_kw("opt_mode", 3),
        key="opt_mode",
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
                    **_value_kw(f"opt_en_{k}", False),
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
                    f"Minimum {lbl}",
                    **_value_kw(f"opt_min_{k}", mn),
                    key=f"opt_min_{k}", label_visibility="collapsed",
                    **({"format": "%.2f"} if typ == "float" else {}),
                )
            with c3:
                max_v = st.number_input(
                    f"Maximum {lbl}",
                    **_value_kw(f"opt_max_{k}", mx),
                    key=f"opt_max_{k}", label_visibility="collapsed",
                    **({"format": "%.2f"} if typ == "float" else {}),
                )
            with c4:
                step_v = st.number_input(
                    f"Pas {lbl}",
                    **_value_kw(f"opt_step_{k}", stp),
                    key=f"opt_step_{k}", label_visibility="collapsed",
                    **({"format": "%.3f"} if typ == "float" else {}),
                )
            if typ == "int":
                min_v = int(min_v)
                max_v = int(max_v)
                step_v = int(step_v)
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
        n_workers_max = max(os.cpu_count() or 8, int(selected_preset.workers or 1), 2)
        n_workers_initial = (
            int(selected_preset.workers)
            if selected_preset.workers is not None
            else n_workers_default
        )
        n_workers = st.slider(
            "Nombre de workers (CPU)",
            1,
            n_workers_max,
            **_value_kw("opt_workers", n_workers_initial),
            key="opt_workers",
            disabled=(
                not selected_preset.manual_control
                and not selected_preset.configurable_workers
            ),
        )
    with wc2:
        benchmark_options = [1, 3, 5, 10, 15]
        benchmark_n_sample = st.selectbox(
            "Échantillons benchmark",
            options=benchmark_options,
            **_index_kw("opt_benchmark_n_sample", benchmark_options.index(int(selected_preset.benchmark_n_sample))),
            key="opt_benchmark_n_sample",
            help=(
                "Nombre de backtests pour mesurer la vitesse avant l'optimisation. "
                "Moins = démarrage plus rapide mais estimation moins précise."
            ),
            disabled=not selected_preset.manual_control,
        )

    with st.expander("🎚️ Limite de combinaisons", expanded=False):
        st.caption(
            "Cette limite coupe le nombre de réglages testés. "
            "Elle protège le PC local contre les runs trop longs."
        )
        if "opt_use_max_combinations" not in st.session_state:
            st.session_state["opt_use_max_combinations"] = selected_preset.max_combinations is not None
        if "opt_max_combinations_widget" not in st.session_state:
            st.session_state["opt_max_combinations_widget"] = int(selected_preset.max_combinations or 100_000)

        max_combo_toggle_disabled = (
            not selected_preset.manual_control
            and not selected_preset.configurable_max_combinations
        )
        use_max_combinations = st.checkbox(
            "Limiter le nombre de combinaisons",
            key="opt_use_max_combinations",
            **_value_kw("opt_use_max_combinations", selected_preset.max_combinations is not None),
            disabled=max_combo_toggle_disabled,
        )
        if use_max_combinations:
            max_combinations_limit = int(st.number_input(
                "Combinaisons maximum",
                min_value=1,
                max_value=5_000_000,
                step=10,
                key="opt_max_combinations_widget",
                **_value_kw("opt_max_combinations_widget", int(selected_preset.max_combinations or 100_000)),
                disabled=max_combo_toggle_disabled,
            ))
        else:
            max_combinations_limit = None

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
        period_fields_disabled = not selected_preset.manual_control
        with pc1:
            use_start = st.checkbox(
                "Date de début",
                **_value_kw("opt_use_start", False),
                key="opt_use_start",
                disabled=period_fields_disabled,
            )
            if use_start:
                _d_start = st.date_input(
                    "Début",
                    **_value_kw("opt_start_date_widget", datetime.date(2022, 1, 1)),
                    key="opt_start_date_widget",
                    disabled=period_fields_disabled,
                )
                opt_start_date_str = _d_start.isoformat()
            else:
                opt_start_date_str = None
        with pc2:
            use_end = st.checkbox(
                "Date de fin",
                **_value_kw("opt_use_end", False),
                key="opt_use_end",
                disabled=period_fields_disabled,
            )
            if use_end:
                _d_end = st.date_input(
                    "Fin",
                    **_value_kw("opt_end_date_widget", datetime.date(2024, 12, 31)),
                    key="opt_end_date_widget",
                    disabled=period_fields_disabled,
                )
                opt_end_date_str = _d_end.isoformat()
            else:
                opt_end_date_str = None
        with pc3:
            use_maxrows = st.checkbox(
                "Limiter les lignes",
                **_value_kw("opt_use_maxrows", False),
                key="opt_use_maxrows",
                disabled=period_fields_disabled,
            )
            if use_maxrows:
                opt_max_rows = st.number_input(
                    "Nb de lignes max",
                    **_value_kw("opt_max_rows_widget", 100_000),
                    min_value=10_000, max_value=1_000_000, step=10_000,
                    key="opt_max_rows_widget",
                    help="Filtre appliqué après le filtre de date — garde les N premières lignes.",
                    disabled=period_fields_disabled,
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
                st.info("Mode rapide actif : une limite de 20 000 lignes sera appliquée automatiquement.")
            elif selected_preset.full_history:
                st.info("Historique complet : aucun filtre de date ou de lignes n'est appliqué.")
            else:
                st.warning(
                    "Aucun filtre actif : l'optimisation utilisera tout l'historique. "
                    "Sur un PC lent, choisis Test rapide local ou limite le nombre de lignes.",
                    icon=None,
                )

    enabled_ranges = [pr for pr in param_ranges if pr.enabled]
    raw_total_combos = total_combos

    # Limiter le nb de combinaisons selon le préréglage.
    if max_combinations_limit is not None and total_combos > max_combinations_limit:
        total_combos = max_combinations_limit

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
            w_pf   = st.slider("Profit Factor", 0.0, 5.0, **_value_kw("sw_pf", 3.0), step=0.5, key="sw_pf")
            w_dd   = st.slider("Max Drawdown", 0.0, 5.0, **_value_kw("sw_dd", 3.0), step=0.5, key="sw_dd")
            w_nt   = st.slider("Nb Trades", 0.0, 5.0, **_value_kw("sw_nt", 2.0), step=0.5, key="sw_nt")
        with c2:
            w_mc   = st.slider("Pertes consécutives", 0.0, 5.0, **_value_kw("sw_mc", 2.0), step=0.5, key="sw_mc")
            w_gain = st.slider("% de gain", 0.0, 5.0, **_value_kw("sw_gain", 2.0), step=0.5, key="sw_gain")
            w_wr   = st.slider("Win Rate", 0.0, 5.0, **_value_kw("sw_wr", 1.0), step=0.5, key="sw_wr")
        with c3:
            w_ratio = st.slider("Ratio Gain/Perte", 0.0, 5.0, **_value_kw("sw_ratio", 1.5), step=0.5, key="sw_ratio")
            w_eq    = st.slider("Régularité Equity", 0.0, 5.0, **_value_kw("sw_eq", 1.5), step=0.5, key="sw_eq")
            w_rf    = st.slider("Recovery Factor", 0.0, 5.0, **_value_kw("sw_rf", 1.0), step=0.5, key="sw_rf")

    score_weights = ScoreWeights(
        profit_factor=w_pf, max_drawdown=w_dd, total_trades=w_nt,
        max_consecutive_losses=w_mc, pct_gain=w_gain, win_rate=w_wr,
        avg_win_loss_ratio=w_ratio, equity_regularity=w_eq, recovery_factor=w_rf,
    )

    # ── Filtres ───────────────────────────────────────────────
    with st.expander("🚧 Filtres éliminatoires", expanded=False):
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            f_trades = st.number_input("Trades min", **_value_kw("f_trades", 30), min_value=1, step=5, key="f_trades")
            f_dd     = st.number_input("DD max (%)", **_value_kw("f_dd", 25.0), min_value=0.0, step=1.0, key="f_dd")
        with fc2:
            f_pf     = st.number_input("PF min", **_value_kw("f_pf", 1.1), min_value=0.5, step=0.1, key="f_pf")
            f_consec = st.number_input("Pertes consec max", **_value_kw("f_consec", 12), min_value=1, step=1, key="f_consec")
        with fc3:
            f_wr     = st.number_input("Win Rate min (%)", **_value_kw("f_wr", 35.0), min_value=0.0, step=1.0, key="f_wr")

    filters = FilterConfig(
        min_trades=int(f_trades),
        max_drawdown_pct=float(f_dd),
        min_profit_factor=float(f_pf),
        max_consecutive_losses=int(f_consec),
        min_win_rate=float(f_wr),
    )

    # ── Train / Test ──────────────────────────────────────────
    with st.expander("🔀 Split Train / Test (anti-overfitting)", expanded=False):
        tt_enabled = st.toggle("Activer le split train/test", **_value_kw("tt_enabled", False), key="tt_enabled")
        if tt_enabled:
            tt_method = st.radio(
                "Méthode de split", ["ratio", "date"],
                format_func=lambda x: "Par ratio (ex: 70%/30%)" if x == "ratio" else "Par date fixe",
                **_index_kw("tt_method", 0),
                key="tt_method", horizontal=True,
            )
            if tt_method == "ratio":
                tt_ratio = st.slider("Ratio d'entraînement", 0.5, 0.9, **_value_kw("tt_ratio", 0.7), step=0.05, key="tt_ratio")
                tt_date  = None
            else:
                tt_ratio = 0.7
                tt_date  = st.text_input("Date de séparation (YYYY-MM-DD)", **_value_kw("tt_date", "2024-01-01"),
                                          key="tt_date")
            tt_alert = st.slider("Alerte dégradation (%)", 10, 60, **_value_kw("tt_alert", 30), step=5, key="tt_alert")
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

    # ── Recapitulatif avant lancement ─────────────────────────
    with st.container(border=True):
        st.markdown("### Avant de lancer")
        st.caption("Vérifie ces points avant de créer un nouveau dossier dans `results/job_xxx/`.")
        r1, r2, r3, r4, r5 = st.columns(5)
        r1.metric("Préréglage", selected_preset.name)
        r2.metric("Combinaisons", f"{int(total_combos or 0):,}")
        r3.metric("Workers", int(n_workers or 1))
        r4.metric("Benchmark", f"{int(benchmark_n_sample or 1)}×")
        r5.metric("Lignes", f"{int(opt_max_rows):,}" if opt_max_rows else "historique complet")
        st.write(f"Fichier de données : `{data_resolution.relative_path}`")
        if quick_mode:
            st.caption(
                "Test rapide local : max 20 000 lignes, 12 combinaisons, "
                "1 worker. Résultats non représentatifs."
            )
        elif raw_total_combos > total_combos:
            st.caption(f"Combinaisons initiales : {raw_total_combos:,}; exécutées : {total_combos:,}.")
        else:
            st.caption(selected_preset.description)

    # ── Bouton LANCER ─────────────────────────────────────────
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    current_run_id = st.session_state.get("opt_current_run_id")
    is_running     = False
    if current_run_id:
        status = _get_run_status(current_run_id)
        is_running = (status in ("running", "benchmarking", "created"))
    blocking_active_jobs = _list_active_jobs()
    launch_in_flight = bool(st.session_state.get("opt_launch_in_flight"))

    if not data_ready:
        st.button("▶  Lancer l'optimisation", disabled=True,
                  width="stretch", key="opt_launch_no_data")
        st.info("Ajoute d'abord un CSV pour l'actif et le timeframe sélectionnés.")
    elif not enabled_ranges:
        st.button("▶  Lancer l'optimisation", disabled=True,
                  width="stretch", key="opt_launch_disabled")
        st.info("Sélectionnez au moins un paramètre à optimiser.")
    elif launch_in_flight:
        st.button("▶  Lancement en cours…", disabled=True,
                  width="stretch", key="opt_launch_in_flight_btn")
        st.info("Le job est en train d'être créé. Attends quelques secondes avant toute autre action.")
    elif is_running or blocking_active_jobs:
        st.button("▶  Optimisation déjà en cours", disabled=True,
                  width="stretch", key="opt_running_btn")
        st.warning(
            "Un job actif existe déjà. Pour éviter deux optimisations en parallèle, reprends le suivi "
            "ou arrête proprement le job actif avant d'en lancer un autre.",
            icon=None,
        )
        if blocking_active_jobs:
            _render_active_jobs_reconnect_panel(blocking_active_jobs, key_prefix="cfg_launch_block")
        if st.button("⏹  Arrêter proprement", width="stretch", key="opt_stop_btn"):
            target_job_id = current_run_id or (blocking_active_jobs[0].get("job_id") if blocking_active_jobs else "")
            if target_job_id:
                _write_stop_flag(target_job_id)
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
            if _list_active_jobs():
                st.error(
                    "Lancement annulé : un job actif vient d'être détecté. "
                    "Ouvre la Progression ou l'Historique pour le reprendre.",
                    icon=None,
                )
                st.rerun()

            st.session_state["opt_launch_in_flight"] = True

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
                "preset_name":     selected_preset.name,
                "preset_description": selected_preset.description,
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
                "workers":         n_workers,
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
                # Compatibilité ancien mode validation rapide.
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

            try:
                launched = _launch_optimizer(config_dict)
            except ActiveJobExistsError as exc:
                st.session_state["opt_launch_in_flight"] = False
                st.error(str(exc), icon=None)
                _render_active_jobs_reconnect_panel(exc.active_jobs, key_prefix="cfg_launch_error")
            else:
                st.session_state["opt_launch_in_flight"] = False
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

_JOB_DOWNLOAD_FILES = JOB_DOWNLOAD_SPECS


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


def _show_results_for_run(run_id: str, job_dir: str = None, focus_files: bool = False) -> None:
    if not run_id:
        return
    st.session_state["opt_view_run_id"] = run_id
    if job_dir:
        st.session_state.setdefault("opt_job_dirs", {})[run_id] = job_dir
    if focus_files:
        st.session_state["opt_focus_files_tab"] = True
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
    status_display = "stopping" if job.get("stop_requested") else status
    progress = float(job.get("progress_pct", 0) or 0)
    elapsed  = job.get("duration_seconds", 0) or 0
    tested   = job.get("combinations_tested", 0) or 0
    total    = job.get("total_combinations", 0) or 0
    config   = _load_job_config(job_dir)
    asset, timeframe = _infer_asset_timeframe(config)
    preset_label = _preset_label(config, job)
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
            {_safe_html(_status_ui(status_display)["label"])} · Progression {progress:.1f}% · Écoulé {format_duration(elapsed)}
          </div>
          <div class="h-meta" style="margin-top:2px">
            Préréglage {_safe_html(preset_label)} · Actif {_safe_html(asset)} · Timeframe {_safe_html(timeframe)} · {_safe_html(tested_text)}
          </div>
        </div>
        {_status_badge(status_display)}
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
        if st.button(
            "Arrêter proprement",
            key=f"{key_prefix}_stop_{job_id}",
            width="stretch",
            disabled=bool(job.get("stop_requested")),
        ):
            opt_store.write_stop_flag(job_id, job_dir=job_dir or _job_dir_for_run(job_id))
            st.toast("Signal d'arrêt envoyé…", icon="⏹")
            st.rerun()

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
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} Mo"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} Go"


def _render_job_downloads(job_dir: str, job_id: str):
    if not job_dir or not os.path.isdir(job_dir):
        st.info("Dossier de job introuvable.")
        return

    try:
        ensure_job_archive(job_dir)
    except OSError as exc:
        st.warning(f"Archive ZIP non régénérée : {exc}", icon=None)

    files = list_job_download_files(job_dir)
    available = [info for info in files if info.can_download]
    help_panel(
        "Fichiers du job",
        f"{len(available)}/{len(files)} fichiers sont prêts à être téléchargés. "
        "Les fichiers absents restent affichés sans bouton cassé.",
        "info",
    )

    for info in files:
        cols = st.columns([2.4, 1.1, 1.4])

        with cols[0]:
            st.markdown(f"**{info.label}**  \n`{info.filename}`")
        with cols[1]:
            if info.can_download:
                st.caption(f"Prêt · {_fmt_file_size(info.size)}")
            elif info.exists and info.error:
                st.caption("Erreur de lecture")
            else:
                st.caption("Indisponible")
        with cols[2]:
            if info.can_download:
                try:
                    data = read_job_file_bytes(info.path)
                    st.download_button(
                        "Télécharger",
                        data,
                        file_name=info.filename,
                        mime=info.mime,
                        key=f"job_download_{job_id}_{info.filename.replace('.', '_')}",
                        width="stretch",
                        on_click="ignore",
                    )
                except OSError as exc:
                    st.button(
                        "Erreur lecture",
                        disabled=True,
                        key=f"job_read_error_{job_id}_{info.filename.replace('.', '_')}",
                        width="stretch",
                    )
                    st.caption(str(exc))
            else:
                st.button(
                    "Indisponible",
                    disabled=True,
                    key=f"job_missing_{job_id}_{info.filename.replace('.', '_')}",
                    width="stretch",
                )
                if info.exists and info.error:
                    st.caption(info.error)

    archive_info = next((info for info in files if info.filename == "archive.zip" and info.can_download), None)
    if archive_info:
        try:
            contents = list_archive_contents(archive_info.path)
            st.caption("Archive ZIP : " + ", ".join(contents))
        except OSError as exc:
            st.caption(f"Archive ZIP lisible mais contenu non inspecté : {exc}")


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
    preset_label = _preset_label(job_config, meta)
    preset_desc = _preset_description(job_config, meta)
    job_annotation = load_annotation(job_dir) if job_dir else JobAnnotation()
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
        f"Préréglage {preset_label}",
        _annotation_label(job_annotation) if not job_annotation.is_empty else "",
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
        if preset_desc:
            subtitle_text += f"<br>{_safe_html(preset_desc)}"

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

    if job_dir and job_config:
        _render_job_config_actions(job_config, run_id, key_prefix="results_job_actions")
        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
    if job_dir:
        _render_job_annotation_editor(run_id, job_dir, status_str)
        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    s1, s2, s3, s4, s5, s6, s7 = st.columns(7)
    with s1:
        st.markdown(card("Statut", status_info["label"], "white"), unsafe_allow_html=True)
    with s2:
        st.markdown(card("Préréglage", _safe_html(preset_label), "white"), unsafe_allow_html=True)
    with s3:
        st.markdown(card("Meilleur score", f"{float(best_score or 0):.1f}", _score_class(float(best_score or 0))),
                    unsafe_allow_html=True)
    with s4:
        st.markdown(card("Tests traités", processed_label, "white", sub=processed_sub), unsafe_allow_html=True)
    with s5:
        st.markdown(card("Résultats valides", f"{valid_count:,}", "green" if valid_count else "red"),
                    unsafe_allow_html=True)
    with s6:
        st.markdown(card("Tests filtrés", f"{int(n_filtered or 0):,}", "accent" if n_filtered else "white"),
                    unsafe_allow_html=True)
    with s7:
        st.markdown(card("Verdict", verdict, "white"), unsafe_allow_html=True)

    _render_results_diagnostic(status_str, df_results, valid_count, int(n_filtered or 0),
                               float(best_score or 0), int(n_tested or 0), quick_validation)

    result_tab_labels = (
        ["🥇 Top résultats", "📋 Données avancées", "📝 Rapport", "📦 Fichiers job"]
        if job_dir else
        ["🥇 Top résultats", "📋 Données avancées", "📝 Rapport"]
    )
    if st.session_state.pop("opt_focus_files_tab", False) and job_dir:
        st.session_state["result_subtabs"] = "📦 Fichiers job"
    elif st.session_state.get("result_subtabs") not in result_tab_labels:
        st.session_state["result_subtabs"] = "🥇 Top résultats"

    tabs = st.tabs(
        result_tab_labels,
        default=st.session_state.get("result_subtabs", "🥇 Top résultats"),
        key="result_subtabs",
        on_change="rerun",
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
    st.markdown("### Jobs d'optimisation")
    st.caption(f"{len(jobs)} job{'s' if len(jobs) != 1 else ''} dans `results/job_xxx/`")
    help_panel(
        "Lecture depuis le disque",
        "Cette liste reflète les dossiers déjà créés dans `results/job_xxx/`. "
        "Un job terminé peut être ouvert avec Voir ou téléchargé via son archive.",
        "info",
    )

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
        annotation = load_annotation(job_dir)
        asset, timeframe = _infer_asset_timeframe(config)
        preset_label = _preset_label(config, job)
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
        status_display = "stopping" if job.get("stop_requested") else status
        status_info = _status_ui(status_display)
        valid_hint = 1 if float(best_score or 0) > 0 else 0
        verdict = _score_verdict(float(best_score or 0), status, valid_hint, quick_validation)
        run_type = preset_label
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
                if not annotation.is_empty:
                    _render_annotation_summary(annotation)
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
                bc1, bc2, bc3, bc4, bc5, bc6, _ = st.columns([1, 1.25, 1.25, 1.45, 1.25, 1.25, 1.55])
            else:
                bc1, bc2, bc4, bc5, _ = st.columns([1, 1.25, 1.35, 1.35, 3.05])

            with bc1:
                if st.button("Voir", key=f"job_view_{job_id}", width="stretch", type="secondary"):
                    _show_results_for_run(job_id, job_dir)
                    st.toast(f"Job {job_id[-8:]} chargé — passe sur l'onglet Résultats", icon="📊")
                    st.rerun()
            with bc2:
                if st.button("Fichiers job", key=f"job_files_{job_id}", width="stretch", type="secondary"):
                    _show_results_for_run(job_id, job_dir, focus_files=True)
                    st.toast(f"Fichiers du job {job_id[-8:]} ouverts", icon="📦")
                    st.rerun()
            if is_active:
                with bc3:
                    if st.button("Reprendre", key=f"job_resume_{job_id}", width="stretch"):
                        _remember_job_for_tracking(job)
                        st.toast(f"Suivi repris pour {job_id[-8:]}", icon="⏳")
                        st.rerun()
                with bc4:
                    if st.button(
                        "Arrêter",
                        key=f"job_stop_{job_id}",
                        width="stretch",
                        disabled=bool(job.get("stop_requested")),
                    ):
                        opt_store.write_stop_flag(job_id, job_dir=job_dir or _job_dir_for_run(job_id))
                        st.toast("Signal d'arrêt envoyé…", icon="⏹")
                        st.rerun()
                relaunch_col = bc5
                duplicate_col = bc6
            else:
                relaunch_col = bc4
                duplicate_col = bc5
            with relaunch_col:
                if st.button(
                    "Relancer",
                    key=f"job_relaunch_{job_id}",
                    width="stretch",
                    disabled=bool(_list_active_jobs()),
                    type="secondary",
                ):
                    try:
                        launched = _launch_config_as_new_job(config, job_id)
                    except ActiveJobExistsError as exc:
                        st.error(str(exc), icon=None)
                        _render_active_jobs_reconnect_panel(exc.active_jobs, key_prefix=f"hist_active_{job_id}")
                    else:
                        _remember_job_for_tracking({"job_id": launched.job_id, "job_dir": launched.job_dir})
                        st.success(f"Nouveau job créé : `{launched.job_id}`")
                        st.rerun()
            with duplicate_col:
                if st.button("Dupliquer", key=f"job_duplicate_{job_id}", width="stretch", type="secondary"):
                    _duplicate_config_to_configuration(config, job_id)
                    st.rerun()

        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)


def _render_opt_history_tab():
    jobs = opt_store.list_jobs()
    runs = opt_store.list_runs()

    history_filter = st.selectbox(
        "Filtrer les jobs",
        options=[
            "Tous",
            "Champions / Favoris",
            "Champion",
            "Favori",
            "À revoir",
            "Rejeté",
            "Non classés",
        ],
        key="job_annotation_filter",
    )
    if history_filter == "Champions / Favoris":
        displayed_jobs = featured_jobs(jobs)
    elif history_filter == "Non classés":
        displayed_jobs = [
            job for job in jobs
            if load_annotation(job.get("job_dir", "")).is_empty
        ]
    elif history_filter == "Tous":
        displayed_jobs = jobs
    else:
        displayed_jobs = filter_jobs_by_annotation(jobs, [history_filter])

    if history_filter != "Tous":
        st.caption(f"{len(displayed_jobs)} job(s) correspondent au filtre `{history_filter}`.")
    _render_jobs_history_section(displayed_jobs)

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


def _comparison_option_label(record) -> str:
    date_label = _fmt_date(record.date)
    annotation_label = (
        f" · {_annotation_label(record.annotation)}"
        if not record.annotation.is_empty else ""
    )
    return (
        f"{record.job_id} · {date_label} · "
        f"{record.asset}/{record.timeframe} · {record.preset}{annotation_label}"
    )


def _comparison_table_row(record, best_job_id: str) -> dict:
    return {
        "Meilleur": "Oui" if record.job_id == best_job_id else "",
        "Job": record.job_id,
        "Date": _fmt_date(record.date),
        "Actif": record.asset,
        "Timeframe": record.timeframe,
        "Preset": record.preset,
        "Classement": _annotation_label(record.annotation)
        if not record.annotation.is_empty else "Non classé",
        "Tags": " · ".join(record.annotation.tags),
        "Statut": _status_ui(record.status)["label"],
        "Score": record.score,
        "Trades": record.trades,
        "Win rate (%)": record.win_rate,
        "Drawdown (%)": record.drawdown_pct,
        "Durée": format_duration(record.duration_seconds or 0)
        if record.duration_seconds is not None else "Indisponible",
        "Combinaisons": record.combinations,
        "Fichier de données": record.data_file,
    }


def _render_comparison_job_actions(
    record,
    active_jobs: list,
    key_prefix: str = "compare",
) -> None:
    with st.container(border=True):
        title = f"`{record.job_id}`"
        if record.score is not None:
            title += f" · score {record.score:.1f}"
        st.markdown(f"**{title}**")
        st.caption(
            f"{record.asset}/{record.timeframe} · {record.preset} · "
            f"{record.data_file}"
        )
        if not record.annotation.is_empty:
            _render_annotation_summary(record.annotation)

        a1, a2, a3, a4 = st.columns(4)
        with a1:
            if st.button(
                "Voir résultats",
                key=f"{key_prefix}_view_{record.job_id}",
                width="stretch",
            ):
                _show_results_for_run(record.job_id, record.job_dir)
                st.rerun()
        with a2:
            if st.button(
                "Ouvrir fichiers",
                key=f"{key_prefix}_files_{record.job_id}",
                width="stretch",
                type="secondary",
            ):
                _show_results_for_run(record.job_id, record.job_dir, focus_files=True)
                st.rerun()
        with a3:
            if st.button(
                "Dupliquer config",
                key=f"{key_prefix}_duplicate_{record.job_id}",
                width="stretch",
                type="secondary",
                disabled=not bool(record.config),
            ):
                _duplicate_config_to_configuration(record.config, record.job_id)
                st.rerun()
        with a4:
            if st.button(
                "Relancer même config",
                key=f"{key_prefix}_relaunch_{record.job_id}",
                width="stretch",
                disabled=bool(active_jobs) or not bool(record.config),
            ):
                try:
                    launched = _launch_config_as_new_job(record.config, record.job_id)
                except ActiveJobExistsError as exc:
                    st.error(str(exc), icon=None)
                else:
                    _remember_job_for_tracking({
                        "job_id": launched.job_id,
                        "job_dir": launched.job_dir,
                    })
                    st.success(f"Nouveau job créé : `{launched.job_id}`")
                    st.rerun()


def _render_featured_jobs_tab() -> None:
    st.markdown("### Champions / Favoris")
    st.caption(
        "Retrouve ici les jobs que tu as explicitement classés Champion ou Favori."
    )
    jobs = featured_jobs(opt_store.list_jobs())
    if not jobs:
        st.info(
            "Aucun champion ou favori pour le moment. Ouvre un job terminé dans Résultats "
            "pour lui attribuer un classement.",
            icon=None,
        )
        return

    records_by_id = {
        record.job_id: record
        for record in load_comparison_records(jobs)
    }
    ordered_jobs = sorted(
        jobs,
        key=lambda job: str(job.get("date", "")),
        reverse=True,
    )
    ordered_jobs.sort(
        key=lambda job: 0 if job["annotation"].status == "Champion" else 1
    )
    active_jobs = _list_active_jobs()
    if active_jobs:
        st.warning(
            "Un job est actif : les relances sont temporairement désactivées.",
            icon=None,
        )

    for job in ordered_jobs:
        record = records_by_id.get(job.get("job_id"))
        if record is None:
            continue
        _render_comparison_job_actions(
            record,
            active_jobs,
            key_prefix="featured",
        )


def _champion_report_option_label(report: ChampionReport) -> str:
    record = report.record
    return (
        f"{_annotation_label(record.annotation)} · {record.job_id} · "
        f"{_fmt_date(record.date)} · {record.asset}/{record.timeframe}"
    )


def _format_report_metric(value, suffix: str = "", decimals: int = 1) -> str:
    if value is None:
        return "Indisponible"
    if isinstance(value, int):
        return f"{value}{suffix}"
    try:
        return f"{float(value):.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return "Indisponible"


_VALIDATION_SETTING_KEYS = (
    "champion_min_trades",
    "champion_min_score",
    "champion_watch_drawdown",
    "champion_blocking_drawdown",
    "champion_min_win_rate",
    "champion_min_combinations",
    "champion_min_rows",
    "champion_min_period_days",
    "champion_quick_non_validating",
)


def _clear_validation_setting_widgets() -> None:
    for key in _VALIDATION_SETTING_KEYS:
        st.session_state.pop(key, None)


def _render_champion_validation_settings() -> ChampionValidationSettings:
    settings = load_validation_settings()
    with st.expander("Réglages validation", expanded=False):
        st.caption(
            "Ces seuils sont globaux à l'application et enregistrés dans "
            "`settings/champion_validation.json`, jamais dans les jobs."
        )
        with st.form("champion_validation_settings_form"):
            c1, c2 = st.columns(2)
            with c1:
                min_trades = st.number_input(
                    "Trades minimum sérieux",
                    min_value=1,
                    step=1,
                    value=settings.min_trades,
                    key="champion_min_trades",
                )
                min_score = st.number_input(
                    "Score minimum",
                    step=1.0,
                    value=settings.min_score,
                    key="champion_min_score",
                )
                watch_drawdown = st.number_input(
                    "Drawdown : seuil surveillance (%)",
                    min_value=0.0,
                    max_value=100.0,
                    step=1.0,
                    value=settings.watch_drawdown_pct,
                    key="champion_watch_drawdown",
                )
                blocking_drawdown = st.number_input(
                    "Drawdown : seuil bloquant (%)",
                    min_value=0.0,
                    max_value=100.0,
                    step=1.0,
                    value=settings.blocking_drawdown_pct,
                    key="champion_blocking_drawdown",
                )
            with c2:
                min_win_rate = st.number_input(
                    "Win rate minimum exploitable (%)",
                    min_value=0.0,
                    max_value=100.0,
                    step=1.0,
                    value=settings.min_win_rate_pct,
                    key="champion_min_win_rate",
                )
                min_combinations = st.number_input(
                    "Combinaisons minimum",
                    min_value=1,
                    step=10,
                    value=settings.min_combinations,
                    key="champion_min_combinations",
                )
                min_rows = st.number_input(
                    "Lignes de données minimum",
                    min_value=1,
                    step=10_000,
                    value=settings.min_rows,
                    key="champion_min_rows",
                )
                min_period_days = st.number_input(
                    "Jours de données minimum",
                    min_value=1,
                    step=30,
                    value=settings.min_period_days,
                    key="champion_min_period_days",
                )
            quick_non_validating = st.checkbox(
                "Considérer Test rapide local comme non validant",
                value=settings.quick_preset_non_validating,
                key="champion_quick_non_validating",
            )
            save_col, reset_col, _ = st.columns([1.3, 1.5, 3.2])
            with save_col:
                save_clicked = st.form_submit_button(
                    "Enregistrer les seuils",
                    width="stretch",
                )
            with reset_col:
                reset_clicked = st.form_submit_button(
                    "Réinitialiser par défaut",
                    width="stretch",
                    type="secondary",
                )

        if save_clicked:
            try:
                save_validation_settings(ChampionValidationSettings(
                    min_trades=int(min_trades),
                    min_score=float(min_score),
                    watch_drawdown_pct=float(watch_drawdown),
                    blocking_drawdown_pct=float(blocking_drawdown),
                    min_win_rate_pct=float(min_win_rate),
                    min_combinations=int(min_combinations),
                    min_rows=int(min_rows),
                    min_period_days=int(min_period_days),
                    quick_preset_non_validating=bool(quick_non_validating),
                ))
            except (OSError, TypeError, ValueError) as exc:
                st.error(f"Seuils non enregistrés : {exc}", icon=None)
            else:
                _clear_validation_setting_widgets()
                st.toast("Seuils Champion enregistrés.", icon="💾")
                st.rerun()
        if reset_clicked:
            try:
                reset_validation_settings()
            except OSError as exc:
                st.error(f"Réinitialisation impossible : {exc}", icon=None)
            else:
                _clear_validation_setting_widgets()
                st.toast("Seuils Champion réinitialisés.", icon="↩️")
                st.rerun()

        st.caption("Fichier actif : `settings/champion_validation.json`")
    return settings


def _render_champion_report_tab() -> None:
    st.markdown("### Rapport Champion")
    st.caption(
        "Une fiche de décision pour relire rapidement un Champion ou un Favori, "
        "sans modifier ses résultats calculés."
    )
    validation_settings = _render_champion_validation_settings()

    featured = [
        job for job in featured_jobs(opt_store.list_jobs())
        if str(job.get("status", "")).lower() == "completed"
    ]
    reports = [
        report for job in featured
        if (report := load_champion_report(job, settings=validation_settings)) is not None
    ]
    reports.sort(key=lambda item: item.record.date, reverse=True)
    reports.sort(
        key=lambda item: 0 if item.record.annotation.status == "Champion" else 1
    )
    if not reports:
        st.info(
            "Aucun Rapport Champion disponible. Classe d'abord un job terminé "
            "comme Champion ou Favori depuis Résultats.",
            icon=None,
        )
        return

    reports_by_id = {report.record.job_id: report for report in reports}
    selected_id = st.selectbox(
        "Champion ou favori à analyser",
        options=list(reports_by_id),
        format_func=lambda job_id: _champion_report_option_label(reports_by_id[job_id]),
        key="champion_report_job_id",
    )
    report = reports_by_id[selected_id]
    record = report.record

    with st.container(border=True):
        title_col, status_col = st.columns([4, 1])
        with title_col:
            st.markdown(f"#### `{record.job_id}`")
            st.caption(
                f"{_fmt_date(record.date)} · {record.asset}/{record.timeframe} · "
                f"{record.preset}"
            )
        with status_col:
            st.metric("Classement", _annotation_label(record.annotation))
        if record.annotation.note:
            st.write(record.annotation.note)
        if record.annotation.tags:
            st.caption("Tags : " + " · ".join(record.annotation.tags))

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Score", _format_report_metric(record.score, decimals=2))
    k2.metric("Trades", _format_report_metric(record.trades, decimals=0))
    k3.metric("Win rate", _format_report_metric(record.win_rate, " %"))
    k4.metric("Drawdown", _format_report_metric(record.drawdown_pct, " %"))

    k5, k6, k7 = st.columns(3)
    k5.metric(
        "Durée",
        format_duration(record.duration_seconds or 0)
        if record.duration_seconds is not None else "Indisponible",
    )
    k6.metric(
        "Combinaisons testées",
        _format_report_metric(record.combinations, decimals=0),
    )
    k7.metric("Fichiers disponibles", len(report.available_files))

    st.markdown("#### Contexte du job")
    st.table(
        pd.DataFrame([{
            "Actif": record.asset,
            "Timeframe": record.timeframe,
            "Preset": record.preset,
            "Statut job": _status_ui(record.status)["label"],
            "Fichier de données": record.data_file,
        }]).set_index("Actif"),
    )

    st.markdown("#### Checklist de validation Champion")
    st.caption(
        "Cette checklist distingue un résultat sérieux d'un simple signal prometteur."
    )
    st.table(
        pd.DataFrame([
            {
                "Critère": item.label,
                "Statut": item.status,
                "Explication": item.detail,
            }
            for item in report.validation.criteria
        ]).set_index("Critère"),
    )
    validation_message = (
        f"**{report.validation.verdict}**  \n"
        f"{report.validation.recommendation}"
    )
    if report.validation.verdict == VERDICT_SERIOUS:
        st.success(validation_message, icon=None)
    elif report.validation.verdict == VERDICT_INSUFFICIENT:
        st.error(validation_message, icon=None)
    elif report.validation.verdict == VERDICT_INCOMPLETE:
        st.info(validation_message, icon=None)
    else:
        st.warning(validation_message, icon=None)

    st.markdown("#### Pourquoi ce job est intéressant")
    reason_col, caution_col = st.columns(2)
    with reason_col:
        with st.container(border=True):
            st.markdown("**Points forts détectés**")
            if report.strengths:
                for point in report.strengths:
                    st.write(f"✓ {point}")
            else:
                st.caption("Aucun point fort ne peut être confirmé avec les données disponibles.")
    with caution_col:
        with st.container(border=True):
            st.markdown("**Points faibles ou informations manquantes**")
            if report.weaknesses:
                for point in report.weaknesses:
                    st.write(f"• {point}")
            else:
                st.caption("Aucun point faible majeur détecté par les règles simples.")

    for alert in report.alerts:
        st.warning(alert, icon=None)

    st.markdown("#### Décision recommandée")
    decision_message = (
        f"**{report.decision.title}**  \n{report.decision.explanation}"
    )
    if report.decision.code == DECISION_REJECT:
        st.error(decision_message, icon=None)
    elif report.decision.code == DECISION_RELAUNCH:
        st.success(decision_message, icon=None)
    else:
        st.warning(decision_message, icon=None)
    st.caption(
        "Cette recommandation est une aide à la décision fondée sur les métriques "
        "disponibles. Elle ne garantit pas les performances futures."
    )

    st.markdown("#### Télécharger ce rapport")
    st.caption(
        "Les exports sont générés en mémoire. Aucun fichier supplémentaire n'est écrit dans le job."
    )
    markdown_export = render_champion_markdown(report)
    html_export = render_champion_html(report)
    download_md, download_html, _ = st.columns([1.4, 1.4, 3.2])
    with download_md:
        st.download_button(
            "Télécharger Markdown",
            data=markdown_export.encode("utf-8"),
            file_name=champion_export_filename(report, "md"),
            mime="text/markdown; charset=utf-8",
            key=f"champion_report_md_{record.job_id}",
            width="stretch",
            on_click="ignore",
        )
    with download_html:
        st.download_button(
            "Télécharger HTML",
            data=html_export.encode("utf-8"),
            file_name=champion_export_filename(report, "html"),
            mime="text/html; charset=utf-8",
            key=f"champion_report_html_{record.job_id}",
            width="stretch",
            on_click="ignore",
        )

    st.markdown("#### Fichiers disponibles")
    if report.available_files:
        labels = {
            filename: label
            for filename, label, _mime in JOB_DOWNLOAD_SPECS
        }
        st.table(
            pd.DataFrame([
                {
                    "Fichier": filename,
                    "Contenu": labels.get(filename, filename),
                    "État": "Disponible",
                }
                for filename in report.available_files
            ]).set_index("Fichier"),
        )
    else:
        st.info("Aucun fichier téléchargeable n'est disponible pour ce job.", icon=None)

    st.markdown("#### Actions")
    active_jobs = _list_active_jobs()
    if active_jobs:
        st.warning(
            "Un job est actif : la relance est désactivée. Les autres actions restent disponibles.",
            icon=None,
        )
    _render_comparison_job_actions(
        record,
        active_jobs,
        key_prefix="champion_report",
    )

    with st.expander("Changer l'annotation, la note ou les tags", expanded=False):
        _render_job_annotation_editor(record.job_id, record.job_dir, record.status)


def _render_job_comparison_tab() -> None:
    st.markdown("### Comparaison de jobs")
    st.caption(
        "Compare de 2 à 5 optimisations terminées. Pour une comparaison fiable, "
        "privilégie la même stratégie, le même actif, le même timeframe et le même fichier CSV."
    )

    records = load_comparison_records(opt_store.list_jobs())
    if not records:
        st.info(
            "Aucun job terminé n'est disponible. Lance d'abord une optimisation rapide, "
            "puis reviens ici.",
            icon=None,
        )
        return

    by_id = {record.job_id: record for record in records}
    historical_best = best_job(records)
    default_ids = [records[0].job_id]
    if historical_best and historical_best.job_id not in default_ids:
        default_ids.append(historical_best.job_id)
    elif len(records) > 1:
        default_ids.append(records[1].job_id)
    selected_ids = st.multiselect(
        "Jobs à comparer",
        options=list(by_id),
        default=default_ids,
        format_func=lambda job_id: _comparison_option_label(by_id[job_id]),
        max_selections=5,
        key="comparison_job_ids",
        help="Minimum 2 jobs, maximum 5.",
    )

    is_valid, selection_message = validate_selection(selected_ids)
    if not is_valid:
        st.info(selection_message, icon=None)
        return

    selected = [by_id[job_id] for job_id in selected_ids]
    winner = best_job(selected)
    winner_id = winner.job_id if winner else ""

    if winner:
        st.success(
            f"Meilleur score disponible : `{winner.job_id}` avec {winner.score:.1f}. "
            "Le score seul ne garantit pas qu'un réglage est robuste.",
            icon=None,
        )
    else:
        st.warning(
            "Aucun score exploitable n'est disponible pour les jobs sélectionnés.",
            icon=None,
        )

    for issue in comparison_issues(selected):
        st.warning(issue, icon=None)

    table = pd.DataFrame([
        _comparison_table_row(record, winner_id)
        for record in selected
    ])
    st.dataframe(
        table,
        width="stretch",
        hide_index=True,
        column_config={
            "Score": st.column_config.NumberColumn(format="%.2f"),
            "Win rate (%)": st.column_config.NumberColumn(format="%.2f"),
            "Drawdown (%)": st.column_config.NumberColumn(format="%.2f"),
            "Trades": st.column_config.NumberColumn(format="%d"),
            "Combinaisons": st.column_config.NumberColumn(format="%d"),
        },
    )

    missing = [record for record in selected if record.missing_metrics]
    if missing:
        with st.expander("Métriques manquantes", expanded=False):
            for record in missing:
                st.write(
                    f"`{record.job_id}` : "
                    + ", ".join(record.missing_metrics)
                )

    st.markdown("### Actions")
    active_jobs = _list_active_jobs()
    if active_jobs:
        st.warning(
            "Un job est actif : les boutons de relance sont désactivés. "
            "Voir, fichiers et duplication restent disponibles.",
            icon=None,
        )
    for record in selected:
        _render_comparison_job_actions(record, active_jobs, key_prefix="compare")


MAIN_TAB_HOME = "🏠  Accueil"
MAIN_TAB_BACKTEST = "📊  Backtest manuel"
MAIN_TAB_HISTORY = "📂  Historique manuel"
MAIN_TAB_NEW = "➕  Nouvelle stratégie"
MAIN_TAB_DATA = "🗄️  Données"
MAIN_TAB_MAINTENANCE = "🧹  Maintenance"
MAIN_TAB_OPTIMIZATION = "🔬  Optimisation"
OPT_SUBTAB_CONFIG = "⚙️ Configuration"
OPT_SUBTAB_HISTORY = "📂 Historique Runs"
OPT_SUBTAB_FEATURED = "🏆 Champions / Favoris"
OPT_SUBTAB_CHAMPION_REPORT = "📋 Rapport Champion"
OPT_SUBTAB_COMPARISON = "⚖️ Comparaison de jobs"


def _switch_main_tab(tab_label: str, opt_subtab: str = None) -> None:
    st.session_state["pending_main_tabs"] = tab_label
    if opt_subtab:
        st.session_state["pending_opt_subtabs"] = opt_subtab
    st.rerun()


def _fmt_dashboard_date(value: str) -> str:
    if not value:
        return "Aucun"
    return str(value).replace("T", " ")[:19]


def _fmt_dashboard_score(value) -> str:
    if value is None:
        return "Aucun"
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return "Aucun"


def _render_home_alert(alert) -> None:
    message = f"**{alert.title}**  \n{alert.message}"
    if alert.level == "error":
        st.error(message, icon=None)
    elif alert.level == "warning":
        st.warning(message, icon=None)
    elif alert.level == "success":
        st.success(message, icon=None)
    else:
        st.info(message, icon=None)


def render_home_tab():
    """Tableau de bord d'accueil : etat local, donnees, jobs et alertes."""
    summary = build_dashboard_summary()

    page_header(
        "Accueil",
        "Vue rapide de l'état local : données disponibles, jobs, espace disque et alertes importantes.",
        "Tableau de bord local",
    )
    help_panel(
        "Que faire maintenant ?",
        "Commence par importer ou vérifier tes données, puis lance une optimisation rapide. "
        "Quand un job est terminé, ouvre l'historique pour consulter les résultats et télécharger les fichiers.",
        "info",
    )

    disk_free_pct = (
        summary.disk_free_bytes / summary.disk_total_bytes * 100
        if summary.disk_total_bytes else 0
    )

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Espace libre", _fmt_file_size(summary.disk_free_bytes), f"{disk_free_pct:.0f}% libre")
    k2.metric("Jobs", summary.total_jobs, f"{summary.completed_jobs} terminés")
    k3.metric("Jobs en erreur", summary.error_jobs)
    k4.metric("Meilleur score récent", _fmt_dashboard_score(summary.best_recent_score))

    with st.container(border=True):
        st.markdown("### Derniers jobs")
        if summary.latest_job_id:
            j1, j2, j3 = st.columns(3)
            with j1:
                st.caption("Dernier job lancé")
                st.write(f"`{summary.latest_job_id}`")
                st.caption(_fmt_dashboard_date(summary.latest_job_date))
            with j2:
                st.caption("Statut")
                info = _status_ui(summary.latest_job_status)
                st.write(f"{info['icon']} {info['label']}")
            with j3:
                st.caption("Dernier job terminé")
                if summary.latest_completed_job_id:
                    st.write(f"`{summary.latest_completed_job_id}`")
                    st.caption(_fmt_dashboard_date(summary.latest_completed_job_date))
                else:
                    st.write("Aucun")
        else:
            st.info("Aucun job détecté pour le moment.", icon=None)

    champion_jobs = filter_jobs_by_annotation(
        opt_store.list_jobs(),
        ["Champion"],
    )
    champion_records = load_comparison_records(champion_jobs)
    if champion_records:
        champion = best_job(champion_records) or champion_records[0]
        with st.container(border=True):
            st.markdown("### Champion actuel")
            st.write(f"🏆 `{champion.job_id}`")
            st.caption(
                f"{champion.asset}/{champion.timeframe} · {champion.preset} · "
                f"score {champion.score:.1f}" if champion.score is not None
                else f"{champion.asset}/{champion.timeframe} · {champion.preset}"
            )
            if champion.annotation.note:
                st.write(champion.annotation.note)
            if st.button("Ouvrir Rapport Champion", key="home_open_champion_report"):
                _switch_main_tab(
                    MAIN_TAB_OPTIMIZATION,
                    opt_subtab=OPT_SUBTAB_CHAMPION_REPORT,
                )

    with st.container(border=True):
        st.markdown("### Données disponibles")
        if summary.data_sources:
            rows = []
            for source in summary.data_sources:
                if source.source == "data":
                    source_label = "data/"
                elif source.source == "legacy":
                    source_label = "fallback legacy"
                else:
                    source_label = "manquant"
                data_type = "CSV de test" if source.asset.startswith("PWCSV") else "Données utilisateur"
                rows.append({
                    "Actif": source.asset,
                    "Timeframe": source.timeframe,
                    "Type": data_type,
                    "Source": source_label,
                    "Fichier": source.relative_path,
                    "Etat": "OK" if source.exists else "Aucun CSV",
                })
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        else:
            st.warning("Aucun actif ou timeframe détecté.", icon=None)

    with st.container(border=True):
        st.markdown("### Alertes")
        if summary.alerts:
            for alert in summary.alerts:
                _render_home_alert(alert)
        else:
            st.success("Aucune alerte importante détectée.", icon=None)

    with st.container(border=True):
        st.markdown("### Actions rapides")
        a1, a2, a3, a4, a5 = st.columns(5)
        with a1:
            if st.button("Préparer un CSV", width="stretch"):
                _switch_main_tab(MAIN_TAB_DATA)
        with a2:
            if st.button("Lancer une optimisation", width="stretch"):
                _switch_main_tab(MAIN_TAB_OPTIMIZATION, opt_subtab=OPT_SUBTAB_CONFIG)
        with a3:
            if st.button("Voir les jobs", width="stretch"):
                _switch_main_tab(MAIN_TAB_OPTIMIZATION, opt_subtab=OPT_SUBTAB_HISTORY)
        with a4:
            if st.button("Comparer les jobs", width="stretch"):
                _switch_main_tab(MAIN_TAB_OPTIMIZATION, opt_subtab=OPT_SUBTAB_COMPARISON)
        with a5:
            if st.button("Nettoyer localement", width="stretch"):
                _switch_main_tab(MAIN_TAB_MAINTENANCE)


def render_data_tab():
    """Onglet d'import et validation des CSV de marche."""
    page_header(
        "Données",
        "Importe un CSV, vérifie sa qualité, puis sauvegarde-le dans data/ACTIF/TIMEFRAME/.",
        "Préparation des historiques",
    )
    return_home_button(lambda: _switch_main_tab(MAIN_TAB_HOME), key="data_return_home")
    help_panel(
        "Parcours conseillé",
        "1. Choisis l'actif et le timeframe. 2. Importe le CSV. "
        "3. Corrige les erreurs bloquantes si besoin. 4. Sauvegarde seulement quand le résumé est OK.",
        "info",
    )

    existing_assets = list_available_assets()
    selected_existing_asset = existing_assets[0] if existing_assets else DEFAULT_ASSET

    with st.container(border=True):
        step_title(1, "Choisir la destination", "C'est le dossier où le CSV sera rangé pour les prochains backtests.")
        c1, c2 = st.columns(2)
        with c1:
            selected_existing_asset = st.selectbox(
                "Actif existant",
                options=existing_assets or [DEFAULT_ASSET],
                key="data_existing_asset",
                help="Choisis un actif déjà préparé, ou saisis-en un nouveau juste dessous.",
            )
            custom_asset = st.text_input(
                "Ou nouvel actif",
                value="",
                placeholder="Exemple : SP500, DAX",
                key="data_custom_asset",
            )

        effective_asset = normalize_asset(custom_asset or selected_existing_asset)
        existing_timeframes = list_available_timeframes(effective_asset) or [DEFAULT_TIMEFRAME]

        with c2:
            selected_existing_timeframe = st.selectbox(
                "Timeframe existant",
                options=existing_timeframes,
                key="data_existing_timeframe",
                help="Choisis un timeframe déjà préparé, ou saisis-en un nouveau juste dessous.",
            )
            custom_timeframe = st.text_input(
                "Ou nouveau timeframe",
                value="",
                placeholder="Exemple : M3, M15, H1, D1",
                key="data_custom_timeframe",
            )

        effective_timeframe = normalize_timeframe(custom_timeframe or selected_existing_timeframe)
        target_path = data_csv_target_path(effective_asset, effective_timeframe)
        help_panel(
            "Destination prévue",
            f"`{to_relative_path(target_path)}`",
            "info",
        )

    uploaded_file = st.file_uploader(
        "2. Importer un fichier CSV",
        type=["csv"],
        key="data_csv_upload",
        help="Le fichier doit contenir une date/heure et les colonnes open, high, low, close.",
    )

    if uploaded_file is None:
        st.info("Aucun fichier sélectionné pour l'instant.", icon=None)
        return

    result = validate_market_csv_bytes(uploaded_file.getvalue())

    with st.container(border=True):
        step_title(3, "Résumé qualité", "La sauvegarde est désactivée tant qu'il reste une erreur bloquante.")
        if result.errors:
            help_panel("Erreurs bloquantes", "La sauvegarde est désactivée. Corrige le CSV puis importe-le à nouveau.", "error")
        elif result.warnings:
            help_panel("CSV utilisable avec avertissements", "Tu peux sauvegarder, mais lis les avertissements avant de lancer un gros job.", "warning")
        else:
            help_panel("CSV validé", "Le fichier peut être sauvegardé et utilisé dans l'optimisation.", "success")

        summary = result.summary
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Lignes", f"{int(summary.get('row_count') or 0):,}")
        m2.metric("Début", summary.get("start") or "—")
        m3.metric("Fin", summary.get("end") or "—")
        m4.metric("Doublons dates", f"{int(summary.get('duplicate_dates') or 0):,}")

        m5, m6, m7, m8 = st.columns(4)
        m5.metric("Valeurs manquantes", f"{int(summary.get('missing_values') or 0):,}")
        m6.metric("Prix <= 0", f"{int(summary.get('non_positive_prices') or 0):,}")
        m7.metric("High < Low", f"{int(summary.get('high_below_low') or 0):,}")
        m8.metric("Volume", "Détecté" if summary.get("has_volume") else "Optionnel absent")

        if result.column_map:
            with st.expander("Colonnes détectées", expanded=False):
                st.json(result.column_map)

        if result.errors:
            st.markdown("**À corriger avant sauvegarde :**")
            for err in result.errors:
                st.write(f"- {err}")

        if result.warnings:
            st.markdown("**Avertissements :**")
            for warn in result.warnings:
                st.write(f"- {warn}")

        if result.dataframe is not None:
            st.markdown("**Aperçu normalisé**")
            st.dataframe(result.dataframe.head(20), width="stretch", hide_index=True)

    with st.container(border=True):
        step_title(4, "Sauvegarder", "Les CSV sauvegardés dans data/ restent locaux et sont ignorés par Git.")
        target_exists = target_path.exists()
        overwrite = False
        if target_exists:
            st.warning(
                f"Un fichier existe déjà : `{to_relative_path(target_path)}`. "
                "Coche la case ci-dessous pour le remplacer.",
                icon=None,
            )
            overwrite = st.checkbox("Remplacer le fichier existant", key="data_overwrite_existing")

        can_save = result.can_save and (not target_exists or overwrite)
        if st.button("Sauvegarder dans data/", disabled=not can_save, width="stretch", key="data_save_csv"):
            target_path.parent.mkdir(parents=True, exist_ok=True)
            result.dataframe.to_csv(target_path, index=False)
            resolved = resolve_data_csv(effective_asset, effective_timeframe)
            if resolved.exists:
                st.session_state["opt_asset"] = resolved.asset
                st.session_state["opt_timeframe"] = resolved.timeframe
                st.success(
                    f"CSV sauvegardé et retrouvé : `{resolved.relative_path}`",
                    icon=None,
                )
                st.caption(
                    "Les fichiers CSV sous `data/` sont ignorés par Git. "
                    "Ils restent locaux tant que tu ne les copies pas ailleurs."
                )
            else:
                st.error("Le fichier a été écrit, mais la résolution ne le retrouve pas encore.", icon=None)


def _maintenance_items_dataframe(items):
    rows = []
    for item in items:
        rows.append({
            "Type": item.kind,
            "ID": item.identifier,
            "Statut": item.status or "—",
            "Date": item.date or "—",
            "Actif": item.asset or "—",
            "Timeframe": item.timeframe or "—",
            "Taille": _fmt_file_size(item.size_bytes),
            "Fichiers": item.file_count,
            "Archive": "oui" if item.archive_exists else "non",
            "Supprimable": "oui" if item.deletable and not item.active else "non",
            "Raison": item.reason,
            "Chemin": item.relative_path,
        })
    return pd.DataFrame(rows)


def render_maintenance_tab():
    """Onglet de maintenance locale, avec simulation obligatoire."""
    page_header(
        "Maintenance locale",
        "Nettoie les fichiers générés localement avec simulation obligatoire.",
        "Nettoyage sécurisé",
    )
    return_home_button(lambda: _switch_main_tab(MAIN_TAB_HOME), key="maint_return_home")
    help_panel(
        "Sécurité anti-suppression",
        "Rien n'est supprimé automatiquement. Les jobs actifs sont protégés. "
        "Une suppression réelle demande une confirmation écrite exacte.",
        "warning",
    )

    try:
        usage = disk_usage_for_base()
        total = usage["total"]
        free = usage["free"]
        used = usage["used"]
        c1, c2, c3 = st.columns(3)
        c1.metric("Disque total", _fmt_file_size(total))
        c2.metric("Utilisé", _fmt_file_size(used))
        c3.metric("Libre", _fmt_file_size(free))
    except OSError as exc:
        st.warning(f"Espace disque impossible à lire : {exc}", icon=None)

    jobs = list_job_items()
    active_jobs = [job for job in jobs if job.active]

    st.markdown("### Jobs `results/job_xxx/`")
    if active_jobs:
        st.info(f"{len(active_jobs)} job(s) actif(s) protégés : ils ne seront jamais supprimés ici.", icon=None)
    if jobs:
        st.dataframe(_maintenance_items_dataframe(jobs), width="stretch", hide_index=True)
    else:
        st.info("Aucun dossier job trouvé dans `results/`.", icon=None)

    st.markdown("#### Simulation de nettoyage jobs")
    st.caption("La simulation montre ce qui serait supprimé, sans rien toucher sur le disque.")
    f1, f2, f3, f4 = st.columns(4)
    with f1:
        include_completed = st.checkbox("Jobs terminés", value=True, key="maint_jobs_completed")
    with f2:
        include_errors = st.checkbox("Jobs erreur/arrêtés", value=True, key="maint_jobs_errors")
    with f3:
        older_than_days = st.number_input(
            "Plus vieux que X jours",
            min_value=0,
            max_value=3650,
            value=0,
            step=1,
            key="maint_jobs_age",
        )
    with f4:
        heaviest_limit = st.number_input(
            "Limiter aux plus lourds",
            min_value=0,
            max_value=500,
            value=0,
            step=1,
            help="0 = aucun plafond.",
            key="maint_jobs_heavy",
        )

    selected_jobs = select_cleanup_jobs(
        jobs,
        include_completed=include_completed,
        include_errors=include_errors,
        older_than_days=int(older_than_days),
        heaviest_limit=int(heaviest_limit),
    )
    job_plan = build_cleanup_plan(selected_jobs)
    dry_result = delete_items(selected_jobs, dry_run=True)

    p1, p2, p3 = st.columns(3)
    p1.metric("Jobs simulés", len(job_plan.items))
    p2.metric("Fichiers concernés", job_plan.total_file_count)
    p3.metric("Espace récupérable estimé", _fmt_file_size(job_plan.total_size_bytes))

    if selected_jobs:
        st.dataframe(_maintenance_items_dataframe(selected_jobs), width="stretch", hide_index=True)
        st.caption("Simulation : " + "; ".join(dry_result.skipped[:6]))
    else:
        st.info("Aucun job ne correspond aux filtres de nettoyage.", icon=None)

    with st.expander("Suppression réelle des jobs sélectionnés", expanded=False):
        help_panel(
            "Zone danger jobs",
            "Action irréversible. Les jobs actifs, chemins non autorisés et fichiers protégés restent bloqués.",
            "warning",
        )
        confirm_jobs = st.text_input(
            "Pour confirmer, tape exactement SUPPRIMER",
            value="",
            key="maint_confirm_jobs",
        )
        if st.button(
            "Supprimer les jobs sélectionnés",
            disabled=(confirm_jobs != "SUPPRIMER" or not selected_jobs),
            key="maint_delete_jobs",
            width="stretch",
        ):
            result = delete_items(selected_jobs, dry_run=False)
            if result.errors:
                st.error("Certaines suppressions ont échoué : " + " | ".join(result.errors), icon=None)
            if result.deleted:
                st.success(
                    f"{len(result.deleted)} dossier(s) supprimé(s), environ {_fmt_file_size(result.reclaimed_bytes)} récupérés.",
                    icon=None,
                )
            if result.skipped:
                st.warning("Éléments ignorés : " + " | ".join(result.skipped[:6]), icon=None)
            st.rerun()

    st.caption("Pour confirmer, tape exactement `SUPPRIMER` dans la section dédiée aux jobs.")

    st.markdown("### Dossiers de test `data/PWCSV.../`")
    pwcsv_items = list_pwcsv_data_items()
    pwcsv_plan = build_cleanup_plan(pwcsv_items)
    if pwcsv_items:
        st.info(
            "Ces dossiers ressemblent aux CSV synthétiques créés par les tests Playwright.",
            icon=None,
        )
        st.caption("Dossiers détectés : " + ", ".join(f"`{item.identifier}`" for item in pwcsv_items))
        st.dataframe(_maintenance_items_dataframe(pwcsv_items), width="stretch", hide_index=True)
        c1, c2 = st.columns(2)
        c1.metric("Dossiers PWCSV", len(pwcsv_items))
        c2.metric("Espace récupérable estimé", _fmt_file_size(pwcsv_plan.total_size_bytes))
    else:
        st.success("Aucun dossier `data/PWCSV.../` détecté.", icon=None)

    with st.expander("Suppression réelle des dossiers PWCSV", expanded=False):
        help_panel(
            "Zone danger dossiers de test",
            "Cette action ne concerne que les dossiers `data/PWCSV.../`, jamais les CSV utilisateur.",
            "warning",
        )
        confirm_pwcsv = st.text_input(
            "Pour confirmer, tape exactement SUPPRIMER PWCSV",
            value="",
            key="maint_confirm_pwcsv",
        )
        if st.button(
            "Supprimer les dossiers PWCSV",
            disabled=(confirm_pwcsv != "SUPPRIMER PWCSV" or not pwcsv_items),
            key="maint_delete_pwcsv",
            width="stretch",
        ):
            result = delete_items(pwcsv_items, dry_run=False)
            if result.errors:
                st.error("Certaines suppressions ont échoué : " + " | ".join(result.errors), icon=None)
            if result.deleted:
                st.success(
                    f"{len(result.deleted)} dossier(s) PWCSV supprimé(s), environ {_fmt_file_size(result.reclaimed_bytes)} récupérés.",
                    icon=None,
                )
            if result.skipped:
                st.warning("Éléments ignorés : " + " | ".join(result.skipped[:6]), icon=None)
            st.rerun()

    st.caption("Pour confirmer, tape exactement `SUPPRIMER PWCSV` dans la section dédiée aux dossiers PWCSV.")

    with st.expander("Zone danger CSV utilisateur", expanded=False):
        help_panel(
            "Suppression CSV utilisateur désactivée",
            "Par sécurité, cette version ne supprime aucun vrai CSV utilisateur. "
            "`nasdaq_3m.csv`, `.env`, `.venv`, `.git`, `.streamlit/credentials.toml` et `app_corrupted_backup.py` sont protégés.",
            "warning",
        )
        st.button("Suppression CSV utilisateur désactivée", disabled=True, width="stretch")


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
    main_tab_labels = [
        MAIN_TAB_HOME,
        MAIN_TAB_BACKTEST,
        MAIN_TAB_HISTORY,
        MAIN_TAB_NEW,
        MAIN_TAB_DATA,
        MAIN_TAB_MAINTENANCE,
        MAIN_TAB_OPTIMIZATION,
    ]

    pending_main_tab = st.session_state.pop("pending_main_tabs", None)
    if pending_main_tab in main_tab_labels:
        st.session_state["main_tabs"] = pending_main_tab

    pending_opt_subtab = st.session_state.pop("pending_opt_subtabs", None)
    if pending_opt_subtab:
        st.session_state["opt_subtabs"] = pending_opt_subtab

    if st.session_state.get("main_tabs") not in main_tab_labels:
        st.session_state["main_tabs"] = MAIN_TAB_HOME

    tab_home, tab_backtest, tab_history, tab_new, tab_data, tab_maintenance, tab_opt = st.tabs(
        main_tab_labels,
        default=st.session_state.get("main_tabs", MAIN_TAB_HOME),
        key="main_tabs",
        on_change="rerun",
    )

    # ════════════════════════════════════════════════════════════
    # ONGLET ACCUEIL
    # ════════════════════════════════════════════════════════════
    with tab_home:
        render_home_tab()

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
    # ONGLET DONNÉES
    # ════════════════════════════════════════════════════════════
    with tab_data:
        render_data_tab()

    # ════════════════════════════════════════════════════════════
    # ONGLET MAINTENANCE
    # ════════════════════════════════════════════════════════════
    with tab_maintenance:
        render_maintenance_tab()

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
