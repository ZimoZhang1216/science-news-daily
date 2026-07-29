"""Page renderers for the local research-daily operations dashboard."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

import streamlit as st

import main
from personalization.github import DispatchSettings, dispatch_command
from personalization.models import RecommendationRequest, ResearchProfileInput, ScheduleInput, UserInput
from personalization.recommender import RecommendationError, recommend_profile
from personalization.repository import PersonalizationRepository


BASE_PROFILE_LABELS = main.PROFILE_LABELS
USER_STATUS_LABELS = {"active": "已启用", "paused": "已暂停", "expired": "已到期"}
DELIVERY_STATUS_LABELS = {
    "queued": "等待执行",
    "claimed": "执行中",
    "sending": "正在发送",
    "preview_ready": "预览已生成",
    "sent": "已发送",
    "retryable_failed": "等待重试",
    "failed": "执行失败",
    "cancelled": "已取消",
}
FREQUENCY_LABELS = {"daily": "每天", "weekdays": "工作日", "weekly": "每周"}
PREFERENCE_LABELS = {
    "review": "综述 / 观点",
    "mechanism": "机制研究",
    "methodology": "方法学 / 平台",
    "experiment": "实验研究",
}
WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
SOURCE_LABELS = {
    "arxiv": "arXiv 预印本",
    "pubmed": "PubMed",
    "crossref": "Crossref 期刊元数据",
    "rss": "期刊 / 学术 RSS",
    "openalex": "OpenAlex 学术索引",
    "official_rss": "官方 RSS",
    "hackernews": "Hacker News 社区信号",
    "github_releases": "GitHub Releases 社区信号",
}
EVENT_TYPE_LABELS = {
    "delivery_queued": "自动投递已进入队列",
    "preview_queued": "手动预览已进入队列",
    "delivery_claimed": "任务已领取",
    "automatic_retry_claimed": "自动重试已领取",
    "preview_ready": "预览已生成",
    "delivery_sent": "邮件已发送",
    "delivery_failed": "投递失败",
    "delivery_retry_queued": "已进入重试队列",
    "delivery_lease_expired": "执行超时，等待重试",
    "delivery_cancelled": "任务已终止",
}
EVENT_MESSAGE_LABELS = {
    "Automatic delivery queued": "自动投递任务已进入队列",
    "Manual preview queued": "手动预览任务已进入队列",
    "Delivery claimed": "任务已开始执行",
    "Automatic retry claimed": "自动重试已开始执行",
    "Execution lease expired before completion": "任务执行超时，等待重新执行",
    "Preview generated": "日报预览已生成",
    "Email delivered": "邮件已成功发送",
    "Retry queued for preview": "已进入预览重试队列",
    "Cancelled by operator": "任务已终止",
}
VALIDATION_ERROR_LABELS = {
    "timezone must be a valid IANA timezone": "时区无效，请使用 IANA 时区名称，例如 Asia/Shanghai。",
    "email must be a valid email address": "请输入有效的邮箱地址。",
    "display_name is required": "请填写用户名称。",
    "research_topic is required": "请填写研究方向或当前课题。",
    "max_items must be between 1 and 50": "每份日报条目数需要在 1 到 50 之间。",
    "llm_model is required": "请填写模型名称。",
    "local_send_time must use HH:MM": "发送时间请使用 HH:MM 格式，例如 07:30。",
}

def _label(mapping: dict[str, str], value: str) -> str:
    return mapping.get(value, value)


def _validation_message(exc: ValueError) -> str:
    message = str(exc)
    return VALIDATION_ERROR_LABELS.get(message, "输入不符合要求，请检查必填项、邮箱、时区和发送时间。")


def redact_email(value: str) -> str:
    local, _, domain = value.partition("@")
    if not local or not domain:
        return "已隐藏"
    return f"{local[:1]}***@{domain}"


def _dispatch_settings_or_none() -> DispatchSettings | None:
    repository = os.getenv("PERSONAL_ADMIN_GITHUB_REPOSITORY", "").strip()
    token = os.getenv("GITHUB_DISPATCH_TOKEN", "").strip()
    if not repository or not token:
        return None
    return DispatchSettings(repository, token)


def _artifact_url(artifact_run_id: str) -> str:
    repository = os.getenv("PERSONAL_ADMIN_GITHUB_REPOSITORY", "").strip()
    if not repository or not artifact_run_id:
        return ""
    return f"https://github.com/{repository}/actions/runs/{artifact_run_id}#artifacts"


_ONBOARDING_RECOMMENDATION_KEY = "onboarding_recommendation"
_ONBOARDING_SUGGESTION_KEYS = (
    "onboarding_base_profile",
    "onboarding_include_keywords",
    "onboarding_exclude_keywords",
    "onboarding_source_ids",
    "onboarding_journal_ids",
    "onboarding_preferences",
    "onboarding_max_items",
    "onboarding_provider",
    "onboarding_model",
    "onboarding_output_formats",
    "onboarding_frequency",
    "onboarding_weekday",
    "onboarding_timezone",
    "onboarding_local_send_time",
)


def _clear_onboarding_suggestions() -> None:
    for key in _ONBOARDING_SUGGESTION_KEYS:
        st.session_state.pop(key, None)


def _clear_completed_onboarding() -> None:
    for key in (
        _ONBOARDING_RECOMMENDATION_KEY,
        "onboarding_display_name",
        "onboarding_email",
        "onboarding_topic",
        *_ONBOARDING_SUGGESTION_KEYS,
    ):
        st.session_state.pop(key, None)


def _format_local_next_run(next_run_at: datetime, timezone_name: str) -> str:
    local_time = next_run_at.astimezone(ZoneInfo(timezone_name))
    return f"{local_time:%Y年%m月%d日 %H:%M}（{timezone_name}）"


def render_operations(repository: PersonalizationRepository | None) -> None:
    st.markdown('<div class="eyebrow">运营概览</div>', unsafe_allow_html=True)
    st.title("科研日报运营面板")
    st.caption("查看用户专属日报、投递状态和数据源健康情况。")
    if repository is None:
        st.info("尚未配置 Turso 连接。请在“设置”页面查看所需变量。")
        return

    snapshot = repository.operations_snapshot()
    metrics = st.columns(4)
    metrics[0].metric("用户数", snapshot["total_users"])
    metrics[1].metric("待处理", snapshot["pending"])
    metrics[2].metric("已发送", snapshot["sent"])
    metrics[3].metric("需要处理", snapshot["retryable_failed"])

    st.subheader("最近活动")
    events = repository.list_recent_events()
    if events:
        st.dataframe(
            [
                {
                    "用户": event["display_name"],
                    "事件": _label(EVENT_TYPE_LABELS, event["event_type"]),
                    "说明": _label(EVENT_MESSAGE_LABELS, event["message"]),
                    "发生时间（UTC）": event["created_at"],
                }
                for event in events
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("暂时没有专属日报活动记录。")

    st.subheader("用户列表")
    users = repository.list_users()
    if users:
        st.dataframe(
            [
                {
                    "名称": user.display_name,
                    "研究主题": user.research_topic,
                    "状态": (
                        "等待预览确认"
                        if user.status == "active" and not user.schedule_enabled
                        else _label(USER_STATUS_LABELS, user.status)
                    ),
                    "下次运行（UTC）": user.next_run_at.isoformat() if user.next_run_at else "",
                }
                for user in users
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("请在“用户画像”页面创建第一个用户。")


def _profile_form(repository: PersonalizationRepository) -> None:
    completion = st.session_state.pop("onboarding_completion", None)
    if st.session_state.pop("onboarding_reset_pending", False):
        _clear_completed_onboarding()

    st.subheader("创建用户科研画像")
    if completion is not None:
        level, message = completion
        getattr(st, level)(message)
    st.markdown("#### 必须填写")
    st.caption(
        "先填写接收人；再用一段话描述用户想追踪的研究兴趣。AI 会提炼学科、关键词和信源建议，"
        "但不会自动保存或发送。"
    )
    with st.form("recommend-profile"):
        left, right = st.columns(2)
        display_name = left.text_input("用户名称", key="onboarding_display_name")
        email = right.text_input("日报接收邮箱", key="onboarding_email")
        topic = st.text_area("用一段话描述用户想追踪的研究兴趣", key="onboarding_topic")
        recommend_submitted = st.form_submit_button("生成建议", type="primary")

    if recommend_submitted:
        try:
            request = RecommendationRequest.from_form(display_name, email, topic)
            st.session_state[_ONBOARDING_RECOMMENDATION_KEY] = recommend_profile(request)
            _clear_onboarding_suggestions()
        except (RecommendationError, ValueError) as exc:
            st.error(_validation_message(exc) if isinstance(exc, ValueError) else "系统建议生成失败，请检查模型配置后重试。")

    recommendation = st.session_state.get(_ONBOARDING_RECOMMENDATION_KEY)
    if recommendation is None:
        return

    profile_recommendation = recommendation.profile
    schedule_recommendation = recommendation.schedule
    st.markdown("#### 可修改的系统建议")
    st.caption(profile_recommendation.research_topic)
    st.info(f"推荐理由：{recommendation.rationale}\n\n不确定性：{recommendation.uncertainty}")
    base_profile = st.selectbox(
        "基础学科",
        sorted(main.REPORT_PROFILES),
        index=sorted(main.REPORT_PROFILES).index(profile_recommendation.base_profile),
        format_func=lambda value: _label(BASE_PROFILE_LABELS, value),
        key="onboarding_base_profile",
    )
    available_sources = list(main.available_source_ids(base_profile))
    with st.form("save-recommended-profile"):
        include_keywords = st.text_area(
            "包含关键词",
            value="; ".join(profile_recommendation.include_keywords),
            key="onboarding_include_keywords",
        )
        exclude_keywords = st.text_area(
            "排除关键词",
            value="; ".join(profile_recommendation.exclude_keywords),
            key="onboarding_exclude_keywords",
        )
        source_ids = st.multiselect(
            "数据来源",
            available_sources,
            default=[
                source_id
                for source_id in profile_recommendation.source_ids
                if source_id in available_sources
            ],
            format_func=lambda value: _label(SOURCE_LABELS, value),
            key="onboarding_source_ids",
        )
        journal_options = sorted(
            {
                issn
                for journal in main.resolve_profile(base_profile)["crossref_journals"]
                for issn in journal["issns"]
            }
        )
        journal_ids = st.multiselect(
            "指定期刊 ISSN",
            journal_options,
            default=[
                journal_id
                for journal_id in profile_recommendation.journal_ids
                if journal_id in journal_options
            ],
            key="onboarding_journal_ids",
        )
        preferences = st.multiselect(
            "内容偏好",
            ["review", "mechanism", "methodology", "experiment"],
            default=list(profile_recommendation.content_preferences),
            format_func=lambda value: _label(PREFERENCE_LABELS, value),
            key="onboarding_preferences",
        )
        max_items = st.slider(
            "每份日报条目数",
            min_value=1,
            max_value=50,
            value=profile_recommendation.max_items,
            key="onboarding_max_items",
        )
        output_formats = st.multiselect(
            "输出格式",
            ["docx", "pdf"],
            default=list(profile_recommendation.output_formats),
            key="onboarding_output_formats",
        )
        model_left, model_right = st.columns(2)
        provider_options = ["openai", "deepseek"]
        provider = model_left.selectbox(
            "模型服务商",
            provider_options,
            index=provider_options.index(profile_recommendation.llm_provider),
            key="onboarding_provider",
        )
        model = model_right.text_input(
            "模型名称", value=profile_recommendation.llm_model, key="onboarding_model"
        )
        schedule_left, schedule_middle, schedule_right = st.columns(3)
        frequency_options = ["daily", "weekdays", "weekly"]
        frequency = schedule_left.selectbox(
            "发送频率",
            frequency_options,
            index=frequency_options.index(schedule_recommendation.frequency),
            format_func=lambda value: _label(FREQUENCY_LABELS, value),
            key="onboarding_frequency",
        )
        weekday = schedule_middle.selectbox(
            "每周发送日",
            list(range(7)),
            index=schedule_recommendation.weekday or 0,
            format_func=lambda index: WEEKDAY_LABELS[index],
            disabled=frequency != "weekly",
            key="onboarding_weekday",
        )
        timezone_name = schedule_right.text_input(
            "时区", value=schedule_recommendation.timezone, key="onboarding_timezone"
        )
        local_send_time = st.text_input(
            "当地发送时间",
            value=schedule_recommendation.local_send_time.strftime("%H:%M"),
            key="onboarding_local_send_time",
        )
        save_submitted = st.form_submit_button("保存并生成预览", type="primary")

    if not save_submitted:
        return
    try:
        user = UserInput.from_form(
            st.session_state["onboarding_display_name"],
            st.session_state["onboarding_email"],
            "active",
        )
        profile = ResearchProfileInput.from_form(
            base_profile=base_profile,
            research_topic=st.session_state["onboarding_topic"],
            include_keywords=include_keywords,
            exclude_keywords=exclude_keywords,
            source_ids=source_ids,
            journal_ids=journal_ids,
            content_preferences=preferences,
            max_items=max_items,
            llm_provider=provider,
            llm_model=model,
            output_formats=output_formats,
        )
        schedule = ScheduleInput.from_form(
            frequency,
            weekday if frequency == "weekly" else None,
            timezone_name,
            local_send_time,
            False,
        )
        user_id = repository.create_user_with_profile(user, profile, schedule)
        preview = repository.create_manual_preview(user_id, date.today())
    except ValueError as exc:
        st.error(_validation_message(exc))
        return
    except Exception:
        st.error("保存到 Turso 暂时失败，未生成预览。请检查网络后重试。")
        return

    settings = _dispatch_settings_or_none()
    if settings is None:
        completion = (
            "warning",
            "画像和预览任务已写入 Turso；尚未配置 GitHub 触发条件，因此不会发送邮件。",
        )
    else:
        try:
            dispatch_command(settings, "preview", preview.delivery_id)
        except Exception as exc:
            completion = ("error", f"预览任务已进入队列，但 GitHub Actions 触发失败：{type(exc).__name__}")
        else:
            completion = ("success", "画像已保存，已在 GitHub Actions 中开始生成预览；预览不会发送邮件。")
    st.session_state["onboarding_completion"] = completion
    st.session_state["onboarding_reset_pending"] = True
    st.rerun()


def _edit_profile_form(repository: PersonalizationRepository, user_id: str, display_name: str) -> None:
    current = repository.get_current_profile(user_id).input
    schedule = repository.get_schedule(user_id)
    all_sources = list(main.available_source_ids(current.base_profile))
    preference_options = ["review", "mechanism", "methodology", "experiment"]
    with st.expander(f"编辑科研画像：{display_name}"):
        st.caption(
            "每次保存都会创建不可变更的画像版本；已经生成的日报会保留当时使用的配置。"
        )
        with st.form(f"edit-profile-{user_id}"):
            topic = st.text_input("研究方向或当前课题", value=current.research_topic)
            include_keywords = st.text_area(
                "包含关键词", value="; ".join(current.include_keywords)
            )
            exclude_keywords = st.text_area(
                "排除关键词", value="; ".join(current.exclude_keywords)
            )
            source_ids = st.multiselect(
                "数据来源",
                all_sources,
                default=list(current.source_ids),
                format_func=lambda value: _label(SOURCE_LABELS, value),
            )
            journal_ids = st.text_area(
                "指定期刊 ISSN", value="; ".join(current.journal_ids)
            )
            preferences = st.multiselect(
                "内容偏好",
                preference_options,
                default=list(current.content_preferences),
                format_func=lambda value: _label(PREFERENCE_LABELS, value),
            )
            max_items = st.slider("每份日报条目数", 1, 50, current.max_items)
            model_left, model_right = st.columns(2)
            provider = model_left.selectbox(
                "模型服务商",
                ["openai", "deepseek"],
                index=["openai", "deepseek"].index(current.llm_provider),
            )
            model = model_right.text_input("模型名称", value=current.llm_model)
            output_formats = st.multiselect(
                "输出格式", ["docx", "pdf"], default=list(current.output_formats)
            )
            schedule_left, schedule_middle, schedule_right = st.columns(3)
            frequency = schedule_left.selectbox(
                "发送频率",
                ["daily", "weekdays", "weekly"],
                index=["daily", "weekdays", "weekly"].index(schedule.frequency),
                format_func=lambda value: _label(FREQUENCY_LABELS, value),
            )
            weekday = schedule_middle.selectbox(
                "每周发送日",
                list(range(7)),
                index=schedule.weekday or 0,
                format_func=lambda index: WEEKDAY_LABELS[index],
                disabled=frequency != "weekly",
            )
            timezone = schedule_right.text_input("时区", value=schedule.timezone)
            local_send_time = st.text_input("当地发送时间", value=schedule.local_send_time)
            submitted = st.form_submit_button("保存画像", type="primary")

        if not submitted:
            return
        try:
            profile = ResearchProfileInput.from_form(
                base_profile=current.base_profile,
                research_topic=topic,
                include_keywords=include_keywords,
                exclude_keywords=exclude_keywords,
                source_ids=source_ids,
                journal_ids=journal_ids,
                content_preferences=preferences,
                max_items=max_items,
                llm_provider=provider,
                llm_model=model,
                output_formats=output_formats,
            )
            updated_schedule = ScheduleInput.from_form(
                frequency,
                weekday if frequency == "weekly" else None,
                timezone,
                local_send_time,
                schedule.enabled,
            )
            version = repository.save_profile_version(user_id, profile)
            repository.update_schedule(user_id, updated_schedule)
        except ValueError as exc:
            st.error(_validation_message(exc))
            return
        except Exception:
            st.error("保存到 Turso 暂时失败，请检查网络后重试。")
            return
        st.success(f"科研画像已保存为版本 {version}，云端计划已更新。")


def render_users(repository: PersonalizationRepository | None) -> None:
    st.markdown('<div class="eyebrow">用户科研画像</div>', unsafe_allow_html=True)
    st.title("用户管理")
    if repository is None:
        st.info("尚未配置 Turso 连接，暂时无法保存用户科研画像。")
        return
    deletion_completion = st.session_state.pop("user_deletion_completion", None)
    if deletion_completion:
        st.success(deletion_completion)
    _profile_form(repository)
    st.subheader("已有用户")
    users = repository.list_users()
    if not users:
        st.caption("暂时还没有用户科研画像。")
        return
    pending_deletion_id = st.session_state.get("pending_user_deletion_id")
    for user in users:
        left, middle, right = st.columns([4, 3, 2])
        left.markdown(f"**{user.display_name}** · {user.research_topic}")
        middle.caption(
            f"{redact_email(user.email)} · {_label(BASE_PROFILE_LABELS, user.base_profile)} · "
            f"{'等待预览确认' if user.status == 'active' and not user.schedule_enabled else _label(USER_STATUS_LABELS, user.status)}"
        )
        action = "恢复启用" if user.status != "active" else "暂停"
        if right.button(action, key=f"status-{user.id}"):
            try:
                repository.set_user_status(user.id, "active" if action == "恢复启用" else "paused")
            except Exception:
                st.error("更新用户状态失败，请检查网络后重试。")
            else:
                st.rerun()
        if right.button("删除用户", key=f"delete-{user.id}"):
            st.session_state["pending_user_deletion_id"] = user.id
            st.rerun()
        if pending_deletion_id != user.id:
            continue

        st.warning(
            f"确认永久删除“{user.display_name}”：其画像、计划、预览和投递历史将无法恢复。"
        )
        confirm_column, cancel_column = st.columns(2)
        if confirm_column.button("确认永久删除", key=f"confirm-delete-{user.id}", type="primary"):
            try:
                deleted = repository.delete_user(user.id)
            except Exception:
                st.error("删除用户失败，请检查网络后重试。")
            else:
                st.session_state.pop("pending_user_deletion_id", None)
                if deleted:
                    st.session_state["user_deletion_completion"] = f"已永久删除用户“{user.display_name}”。"
                else:
                    st.session_state["user_deletion_completion"] = "该用户已不存在，面板已刷新。"
                st.rerun()
        if cancel_column.button("取消", key=f"cancel-delete-{user.id}"):
            st.session_state.pop("pending_user_deletion_id", None)
            st.rerun()
    selected_user = st.selectbox(
        "选择要编辑的用户", users, format_func=lambda user: user.display_name
    )
    _edit_profile_form(repository, selected_user.id, selected_user.display_name)


def render_reports(repository: PersonalizationRepository | None) -> None:
    st.markdown('<div class="eyebrow">预览与投递</div>', unsafe_allow_html=True)
    st.title("日报与投递")
    if repository is None:
        st.info("尚未配置 Turso 连接，暂时无法创建日报任务。")
        return
    settings = _dispatch_settings_or_none()
    users = repository.list_users()
    if users:
        selected = st.selectbox("用户", users, format_func=lambda user: user.display_name)
        report_date = st.date_input("日报日期", value=date.today())
        if st.button("生成手动预览", type="primary"):
            try:
                delivery = repository.create_manual_preview(selected.id, report_date)
            except Exception:
                st.error("创建预览任务失败，请检查网络后重试。")
                return
            if settings is None:
                st.warning("预览任务已写入 Turso，但尚未在“设置”中配置 GitHub 触发条件。")
            else:
                try:
                    dispatch_command(settings, "preview", delivery.delivery_id)
                except Exception as exc:
                    st.error(f"预览任务已进入队列，但 GitHub Actions 触发失败：{type(exc).__name__}")
                else:
                    st.success("已在 GitHub Actions 中开始生成预览。")
    else:
        st.caption("请先创建用户科研画像，再生成日报预览。")

    st.subheader("最近投递")
    deliveries = repository.list_recent_deliveries()
    if not deliveries:
        st.caption("暂时还没有日报投递记录。")
        return
    for delivery in deliveries:
        st.markdown(
            f"**{delivery['display_name']}** · {delivery['report_date']} · "
            f"`{_label(DELIVERY_STATUS_LABELS, delivery['status'])}`"
        )
        if delivery["artifact_name"]:
            artifact_url = _artifact_url(delivery["artifact_run_id"])
            if artifact_url:
                st.link_button("打开预览文件", artifact_url, key=f"artifact-{delivery['id']}")
        if delivery["status"] == "preview_ready" and not delivery["schedule_enabled"]:
            if st.button("启用固定频率计划", key=f"activate-{delivery['id']}", type="primary"):
                try:
                    schedule = repository.activate_schedule_after_preview(
                        delivery["user_id"], delivery["id"], datetime.now(UTC)
                    )
                except ValueError:
                    st.warning("这个预览已不再处于可确认状态。")
                except Exception:
                    st.error("启用固定频率计划失败，请检查网络后重试。")
                else:
                    if schedule.next_run_at is None:
                        st.success("固定频率计划已启用；面板状态将在下次同步后刷新。")
                    else:
                        st.success(
                            "固定频率计划已启用；下一次自动发送日报："
                            f"{_format_local_next_run(schedule.next_run_at, schedule.timezone)}。"
                            "面板状态将在下次同步后刷新。"
                        )
        if delivery["status"] == "retryable_failed" and delivery["mode"] == "manual":
            if st.button("重新执行", key=f"retry-{delivery['id']}"):
                if settings is None:
                    st.error("尚未在“设置”中配置 GitHub 触发条件。")
                else:
                    try:
                        dispatch_command(settings, "retry", delivery["id"])
                    except Exception as exc:
                        st.error(f"重试任务已进入队列，但 GitHub Actions 触发失败：{type(exc).__name__}")
                    else:
                        st.success("已开始重新执行。")
        if delivery["status"] in {"queued", "claimed", "retryable_failed"}:
            if st.button("终止任务", key=f"cancel-{delivery['id']}"):
                try:
                    cancelled = repository.cancel_delivery(delivery["id"], datetime.now(UTC))
                except Exception:
                    st.error("终止任务失败，请检查网络后重试。")
                else:
                    if cancelled:
                        st.success("任务已终止；面板状态将在下次同步后刷新。")
                    else:
                        st.warning("任务状态已变化，无法安全终止。")
        elif delivery["status"] == "sending":
            st.caption("邮件正在发送，无法安全终止。")
        if delivery["last_error"]:
            st.caption(f"最近错误：{delivery['last_error']}")


def render_sources(repository: PersonalizationRepository | None) -> None:
    st.markdown('<div class="eyebrow">运行健康度</div>', unsafe_allow_html=True)
    st.title("数据源与指标")
    if repository is None:
        st.info("尚未配置 Turso 连接，暂时没有可用的数据源指标。")
        return
    metrics = repository.list_source_metrics()
    if metrics:
        st.dataframe(
            [
                {
                    "数据源": _label(SOURCE_LABELS, metric["source_name"]),
                    "状态": "成功" if metric["success"] else "失败",
                    "条目数": metric["item_count"],
                    "耗时（毫秒）": metric["duration_ms"],
                    "错误信息": metric["error_summary"],
                    "发生时间（UTC）": metric["created_at"],
                }
                for metric in metrics
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("首次运行专属日报后，这里会显示数据源指标。")


def render_settings(repository: PersonalizationRepository | None) -> None:
    st.markdown('<div class="eyebrow">本地配置</div>', unsafe_allow_html=True)
    st.title("设置")
    turso_ready = bool(os.getenv("TURSO_DATABASE_URL", "").strip() and os.getenv("TURSO_AUTH_TOKEN", "").strip())
    local_sqlite_ready = bool(os.getenv("PERSONAL_ADMIN_LOCAL_DB", "").strip())
    dispatch_ready = _dispatch_settings_or_none() is not None
    st.dataframe(
        [
            {"项目": "Turso 数据库", "状态": "已就绪" if turso_ready else "未配置"},
            {"项目": "本地 SQLite 开发模式", "状态": "已就绪" if local_sqlite_ready else "未配置"},
            {"项目": "GitHub Actions 触发", "状态": "已就绪" if dispatch_ready else "未配置"},
            {"项目": "当前数据库连接", "状态": "已就绪" if repository is not None else "未连接"},
        ],
        use_container_width=True,
        hide_index=True,
    )
    if repository is None:
        st.info(
            "尚未配置 Turso 连接。请设置 TURSO_DATABASE_URL 和 TURSO_AUTH_TOKEN；"
            "本地开发也可以设置 PERSONAL_ADMIN_LOCAL_DB。"
        )
    st.caption("此页面只显示配置就绪状态，不会展示任何密钥内容。")


PAGE_RENDERERS: dict[str, Callable[[PersonalizationRepository | None], None]] = {
    "运营总览": render_operations,
    "用户画像": render_users,
    "日报与投递": render_reports,
    "数据源与指标": render_sources,
    "设置": render_settings,
}
