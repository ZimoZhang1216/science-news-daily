from __future__ import annotations

import argparse
import csv
import os
import smtplib
import sys
from email.message import EmailMessage
from email.utils import getaddresses
from pathlib import Path


PROFILE_LABELS = {
    "chemistry": "化学日报",
    "organic_chemistry": "有机化学日报",
    "biology": "生物日报",
    "statistics": "统计学日报",
}

EXIT_CODE_MEANINGS = {
    "0": "成功",
    "1": "没有可写入日报的资讯或部分来源失败",
    "2": "全部来源抓取失败",
    "3": "邮件发送失败",
    "4": "AI 总结不完整或未通过必须 AI 生成校验",
}


def parse_recipients(value: str) -> list[str]:
    normalized = value.replace(";", ",").replace("\n", ",").replace("\r", ",")
    recipients: list[str] = []
    seen: set[str] = set()
    for _, address in getaddresses([normalized]):
        address = address.strip()
        if not address or "@" not in address:
            continue
        key = address.lower()
        if key in seen:
            continue
        recipients.append(address)
        seen.add(key)
    return recipients


def read_status_rows(status_file: Path) -> list[dict[str, str]]:
    if not status_file.exists():
        return []
    with status_file.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def status_text(row: dict[str, str]) -> str:
    exit_code = row.get("exit_code", "").strip()
    status = row.get("status", "").strip().lower()
    if status == "success" and exit_code == "0":
        return "成功"
    meaning = EXIT_CODE_MEANINGS.get(exit_code, "未知错误")
    return f"失败（exit {exit_code or '?'}：{meaning}）"


def build_body(args: argparse.Namespace, rows: list[dict[str, str]]) -> str:
    overall_exit_code = str(args.overall_exit_code or "").strip()
    overall_text = "成功" if overall_exit_code == "0" else f"失败（exit {overall_exit_code or '?'}）"
    lines = [
        "science-news-daily 自动运行日志",
        "",
        f"日期：{args.report_date}",
        f"整体状态：{overall_text}",
        f"触发来源：{args.event_name}",
        f"Workflow：{args.workflow_name}",
    ]
    if args.run_url:
        lines.append(f"GitHub Actions：{args.run_url}")
    lines.extend(["", "各日报状态："])
    if not rows:
        lines.append("- 未找到状态记录，请查看 GitHub Actions 日志。")
    for row in rows:
        profile = row.get("profile", "")
        label = PROFILE_LABELS.get(profile, profile or "未知日报")
        started_at = row.get("started_at", "")
        ended_at = row.get("ended_at", "")
        lines.append(f"- {label}：{status_text(row)}")
        if started_at or ended_at:
            lines.append(f"  开始：{started_at or '-'}；结束：{ended_at or '-'}")
    lines.extend(
        [
            "",
            "状态码说明：",
            "- 0：成功",
            "- 1：没有可写入日报的资讯或部分来源失败",
            "- 2：全部来源抓取失败",
            "- 3：邮件发送失败",
            "- 4：AI 总结不完整或未通过必须 AI 生成校验",
            "",
            "本邮件由 science-news-daily 自动发送。",
        ]
    )
    return "\n".join(lines)


def send_log_email(args: argparse.Namespace, body: str, status_file: Path) -> bool:
    if args.dry_run:
        print(body)
        return True

    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_username = os.getenv("SMTP_USERNAME", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    smtp_from = os.getenv("SMTP_FROM", "").strip() or smtp_username
    smtp_security = os.getenv("SMTP_SECURITY", "").strip().lower() or "ssl"
    smtp_port_raw = os.getenv("SMTP_PORT", "").strip()
    smtp_port = int(smtp_port_raw) if smtp_port_raw else (587 if smtp_security in {"starttls", "tls"} else 465)
    recipients = parse_recipients(os.getenv("REPORT_EMAIL_TO", ""))

    missing = [
        name
        for name, value in {
            "SMTP_HOST": smtp_host,
            "SMTP_USERNAME": smtp_username,
            "SMTP_PASSWORD": smtp_password,
            "SMTP_FROM or SMTP_USERNAME": smtp_from,
            "REPORT_EMAIL_TO": recipients,
        }.items()
        if not value
    ]
    if missing:
        print(f"Run log email not sent; missing config: {', '.join(missing)}", file=sys.stderr)
        return False

    message = EmailMessage()
    message["Subject"] = f"science-news-daily 运行日志 - {args.report_date}"
    message["From"] = smtp_from
    message["To"] = ", ".join(recipients)
    message.set_content(body)
    if status_file.exists():
        message.add_attachment(
            status_file.read_bytes(),
            maintype="text",
            subtype="tab-separated-values",
            filename=status_file.name,
        )

    if smtp_security == "ssl":
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as smtp:
            smtp.login(smtp_username, smtp_password)
            refused = smtp.send_message(message)
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as smtp:
            if smtp_security in {"starttls", "tls"}:
                smtp.starttls()
            smtp.login(smtp_username, smtp_password)
            refused = smtp.send_message(message)
    if refused:
        print(f"Run log email sent with refused recipients: {refused}", file=sys.stderr)
        return False
    print(f"Sent run log email to {', '.join(recipients)}")
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Send science-news-daily cronjob run status email.")
    parser.add_argument("--status-file", required=True, help="TSV file with per-profile run status.")
    parser.add_argument("--report-date", required=True, help="Report date in YYYY-MM-DD format.")
    parser.add_argument("--workflow-name", default="Cronjob Daily Research News")
    parser.add_argument("--run-url", default="")
    parser.add_argument("--event-name", default="")
    parser.add_argument("--overall-exit-code", default="")
    parser.add_argument("--dry-run", action="store_true", help="Print email body without sending SMTP mail.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    status_file = Path(args.status_file)
    rows = read_status_rows(status_file)
    body = build_body(args, rows)
    try:
        return 0 if send_log_email(args, body, status_file) else 1
    except Exception as exc:  # noqa: BLE001 - this is a CLI notifier; print clear failure.
        print(f"Run log email failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
