"""
ui_components.py - Petits helpers d'affichage Streamlit.

Ce module ne contient pas de logique metier. Il sert uniquement a garder des
messages, en-tetes et panneaux d'aide coherents dans l'interface.
"""

from __future__ import annotations

import streamlit as st


def page_header(title: str, subtitle: str = "", eyebrow: str = "") -> None:
    if eyebrow:
        st.caption(eyebrow)
    st.markdown(f"## {title}")
    if subtitle:
        st.caption(subtitle)


def help_panel(title: str, body: str, tone: str = "info") -> None:
    message = f"**{title}**  \n{body}"
    if tone == "success":
        st.success(message, icon=None)
    elif tone == "warning":
        st.warning(message, icon=None)
    elif tone == "error":
        st.error(message, icon=None)
    else:
        st.info(message, icon=None)


def step_title(number: int, title: str, caption: str = "") -> None:
    st.markdown(f"### {number}. {title}")
    if caption:
        st.caption(caption)


def return_home_button(callback, key: str) -> None:
    if st.button("Retour Accueil", width="stretch", key=key):
        callback()
