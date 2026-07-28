"""Local-only Streamlit entry point for personalised research daily operations."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.views import PAGE_RENDERERS
from personalization.repository import PersonalizationRepository


def get_repository_or_none() -> PersonalizationRepository | None:
    local_database = os.getenv("PERSONAL_ADMIN_LOCAL_DB", "").strip()
    if local_database:
        repository = PersonalizationRepository.for_sqlite(Path(local_database).expanduser())
        repository.initialize()
        return repository
    if not (
        os.getenv("TURSO_DATABASE_URL", "").strip()
        and os.getenv("TURSO_AUTH_TOKEN", "").strip()
    ):
        return None
    repository = PersonalizationRepository.from_environment()
    repository.initialize()
    return repository


def apply_style() -> None:
    css_path = Path(__file__).with_name("style.css")
    st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def main() -> None:
    st.set_page_config(page_title="科研日报运营面板", page_icon="🧪", layout="wide")
    apply_style()
    st.sidebar.markdown("### 科研日报")
    st.sidebar.caption("专属日报运营工作台")
    page = st.sidebar.radio("功能导航", list(PAGE_RENDERERS))
    try:
        repository = get_repository_or_none()
    except Exception as exc:
        repository = None
        st.warning(f"数据库暂时无法连接：{type(exc).__name__}")
    PAGE_RENDERERS[page](repository)


if __name__ == "__main__":
    main()
