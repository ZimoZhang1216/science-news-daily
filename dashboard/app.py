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


def _default_replica_path() -> Path:
    configured = os.getenv("PERSONAL_ADMIN_REPLICA_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "ScienceNewsDaily"
        / "personalization-replica.db"
    )


@st.cache_resource(show_spinner=False)
def _open_repository(
    mode: str, database_path: str, sync_url: str
) -> PersonalizationRepository:
    """Open one long-lived local store instead of reconnecting on every Streamlit rerun."""

    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode == "local":
        repository = PersonalizationRepository.for_sqlite(path)
        repository.initialize()
        return repository
    return PersonalizationRepository.for_local_replica(
        path,
        sync_url,
        os.getenv("TURSO_AUTH_TOKEN", "").strip(),
    )


def get_repository_or_none() -> PersonalizationRepository | None:
    local_database = os.getenv("PERSONAL_ADMIN_LOCAL_DB", "").strip()
    if local_database:
        return _open_repository("local", str(Path(local_database).expanduser()), "")
    turso_url = os.getenv("TURSO_DATABASE_URL", "").strip()
    if not turso_url or not os.getenv("TURSO_AUTH_TOKEN", "").strip():
        return None
    return _open_repository("replica", str(_default_replica_path()), turso_url)


def apply_style() -> None:
    css_path = Path(__file__).with_name("style.css")
    st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def _render_sync_controls(repository: PersonalizationRepository | None) -> None:
    if repository is None or not repository.is_local_replica:
        return

    st.sidebar.divider()
    st.sidebar.caption("数据模式：本地副本")
    if st.sidebar.button("同步当前状态", use_container_width=True):
        with st.spinner("正在从 Turso 拉取当前状态…"):
            try:
                repository.sync()
            except Exception:
                st.sidebar.warning("同步暂时失败，仍在使用上次同步的数据。")
            else:
                st.sidebar.success("已同步当前状态。")
                st.rerun()

    if repository.last_sync_at is not None:
        st.sidebar.caption(f"最近同步：{repository.last_sync_at:%Y-%m-%d %H:%M UTC}")
    if not repository.is_local_data_ready:
        st.sidebar.caption("尚未同步到可读取的数据。")
    if repository.last_sync_error:
        st.sidebar.caption("最近一次同步未完成，可稍后重试。")


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
    _render_sync_controls(repository)
    if repository is not None and repository.is_local_replica and not repository.is_local_data_ready:
        st.info("本地副本尚未准备好。请点击侧栏“同步当前状态”后再查看或编辑数据。")
        return
    PAGE_RENDERERS[page](repository)


if __name__ == "__main__":
    main()
