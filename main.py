#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import logging
import os
import re
import shutil
import smtplib
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import getaddresses
from pathlib import Path
from typing import Any, Callable

MISSING_DEPENDENCIES: list[str] = []

try:
    import feedparser
except ModuleNotFoundError:
    feedparser = None  # type: ignore[assignment]
    MISSING_DEPENDENCIES.append("feedparser")

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ModuleNotFoundError:
    requests = None  # type: ignore[assignment]
    HTTPAdapter = None  # type: ignore[assignment]
    Retry = None  # type: ignore[assignment]
    MISSING_DEPENDENCIES.append("requests")

try:
    from bs4 import BeautifulSoup
except ModuleNotFoundError:
    BeautifulSoup = None  # type: ignore[assignment]
    MISSING_DEPENDENCIES.append("beautifulsoup4")

try:
    from dateutil import parser as dateparser
except ModuleNotFoundError:
    dateparser = None  # type: ignore[assignment]
    MISSING_DEPENDENCIES.append("python-dateutil")

try:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.opc.constants import RELATIONSHIP_TYPE
    from docx.shared import Inches, Pt, RGBColor
except ModuleNotFoundError:
    Document = None  # type: ignore[assignment]
    WD_ALIGN_PARAGRAPH = None  # type: ignore[assignment]
    Inches = None  # type: ignore[assignment]
    OxmlElement = None  # type: ignore[assignment]
    qn = None  # type: ignore[assignment]
    RELATIONSHIP_TYPE = None  # type: ignore[assignment]
    Pt = None  # type: ignore[assignment]
    RGBColor = None  # type: ignore[assignment]
    MISSING_DEPENDENCIES.append("python-docx")

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - handled at runtime with a clear warning.
    OpenAI = None  # type: ignore[assignment]

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    load_dotenv = None  # type: ignore[assignment]
    MISSING_DEPENDENCIES.append("python-dotenv")

if load_dotenv is not None:
    load_dotenv()


LOGGER = logging.getLogger("chem_news_daily")

DEFAULT_OUTPUT_DIR = "./output"
DEFAULT_MAX_ITEMS = 30
DEFAULT_MAX_AI_ITEMS = 30
DEFAULT_OPENAI_MODEL = "gpt-5.4-mini"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_REPORT_EMAIL_TO = "2510248@mail.nankai.edu.cn"
SUPPORTED_LLM_PROVIDERS = {"openai", "deepseek"}
USER_AGENT = (
    "ChemNewsDaily/1.0 "
    "(mailto:please-set-CROSSREF_MAILTO@example.com; Python requests)"
)

FIELD_KEYWORDS: dict[str, list[str]] = {
    "有机化学": [
        "organic synthesis",
        "total synthesis",
        "asymmetric synthesis",
        "photoredox",
        "cross-coupling",
        "C-H activation",
        "organocatalysis",
        "stereoselective",
        "natural product",
        "synthetic methodology",
    ],
    "物理化学": [
        "physical chemistry",
        "spectroscopy",
        "kinetics",
        "thermodynamics",
        "photochemistry",
        "electrochemistry",
        "ultrafast",
        "surface chemistry",
        "quantum chemistry",
        "molecular dynamics",
    ],
    "材料化学": [
        "materials chemistry",
        "polymer",
        "perovskite",
        "metal-organic framework",
        "MOF",
        "COF",
        "nanomaterial",
        "2D material",
        "semiconductor",
        "self-assembly",
    ],
    "化学生物学": [
        "chemical biology",
        "bioorthogonal",
        "proteomics",
        "drug discovery",
        "enzyme",
        "protein",
        "peptide",
        "biosynthesis",
        "metabolite",
        "bioconjugation",
    ],
    "催化": [
        "catalysis",
        "catalyst",
        "electrocatalysis",
        "photocatalysis",
        "heterogeneous catalysis",
        "homogeneous catalysis",
        "single-atom catalyst",
        "organometallic",
        "activation",
    ],
    "能源化学": [
        "energy chemistry",
        "battery",
        "lithium",
        "sodium-ion",
        "hydrogen",
        "fuel cell",
        "CO2 reduction",
        "oxygen evolution",
        "solar cell",
        "water splitting",
    ],
    "计算化学": [
        "computational chemistry",
        "density functional theory",
        "DFT",
        "molecular simulation",
        "machine learning",
        "quantum computation",
        "molecular docking",
        "ab initio",
        "force field",
    ],
    "分析化学": [
        "analytical chemistry",
        "mass spectrometry",
        "chromatography",
        "sensor",
        "biosensor",
        "imaging",
        "NMR",
        "Raman",
        "fluorescence",
        "single-cell",
    ],
}

CHEMISTRY_TERMS = sorted(
    {
        keyword.lower()
        for keywords in FIELD_KEYWORDS.values()
        for keyword in keywords
    }
    | {
        "chemistry",
        "chemical",
        "molecule",
        "molecular",
        "reaction",
        "synthesis",
        "catalytic",
        "polymerization",
        "electrolyte",
        "redox",
    }
)

LEARNING_VALUE_TERMS: dict[str, float] = {
    "review": 8.0,
    "perspective": 7.0,
    "viewpoint": 5.0,
    "tutorial": 6.0,
    "mechanism": 5.0,
    "mechanistic": 5.0,
    "design principle": 5.0,
    "benchmark": 4.5,
    "platform": 4.0,
    "general method": 4.0,
    "scalable": 3.5,
    "selective": 3.0,
    "high-throughput": 3.0,
    "structure-property": 3.0,
    "insight": 2.5,
    "framework": 2.5,
    "strategy": 2.0,
    "methodology": 2.0,
}

ARXIV_QUERY_TERMS = [
    "chemistry",
    "catalysis",
    "electrochemistry",
    "organic synthesis",
    "materials chemistry",
    "chemical biology",
    "computational chemistry",
    "physical chemistry",
    "analytical chemistry",
    "battery",
    "polymer",
    "perovskite",
]

PUBMED_QUERY_TERMS = [
    "chemical biology",
    "medicinal chemistry",
    "organic synthesis",
    "catalysis",
    "analytical chemistry",
    "mass spectrometry",
    "metabolomics",
    "drug discovery",
    "bioorthogonal chemistry",
    "chemical proteomics",
]

CROSSREF_JOURNALS: list[dict[str, Any]] = [
    {"source": "JACS", "issns": ["0002-7863", "1520-5126"], "broad": False},
    {
        "source": "Angewandte Chemie",
        "issns": ["1433-7851", "1521-3773"],
        "broad": False,
    },
    {"source": "Nature Chemistry", "issns": ["1755-4330", "1755-4349"], "broad": False},
    {"source": "Science", "issns": ["0036-8075", "1095-9203"], "broad": True},
    {"source": "ACS Catalysis", "issns": ["2155-5435"], "broad": False},
    {"source": "ACS Energy Letters", "issns": ["2380-8195"], "broad": False},
    {"source": "ACS Materials Letters", "issns": ["2639-4979"], "broad": False},
    {"source": "ACS Central Science", "issns": ["2374-7943"], "broad": False},
    {"source": "Organic Letters", "issns": ["1523-7060", "1523-7052"], "broad": False},
    {
        "source": "The Journal of Organic Chemistry",
        "issns": ["0022-3263", "1520-6904"],
        "broad": False,
    },
    {"source": "Analytical Chemistry", "issns": ["0003-2700", "1520-6882"], "broad": False},
    {
        "source": "The Journal of Physical Chemistry Letters",
        "issns": ["1948-7185"],
        "broad": False,
    },
    {"source": "Chemical Science", "issns": ["2041-6520", "2041-6539"], "broad": False},
    {
        "source": "Chemical Society Reviews",
        "issns": ["0306-0012", "1460-4744"],
        "broad": False,
    },
    {
        "source": "Journal of Materials Chemistry A",
        "issns": ["2050-7488", "2050-7496"],
        "broad": False,
    },
    {
        "source": "Energy & Environmental Science",
        "issns": ["1754-5692", "1754-5706"],
        "broad": False,
    },
    {
        "source": "Catalysis Science & Technology",
        "issns": ["2044-4753", "2044-4761"],
        "broad": False,
    },
    {
        "source": "Physical Chemistry Chemical Physics",
        "issns": ["1463-9076", "1463-9084"],
        "broad": False,
    },
]

RSS_FEEDS: list[dict[str, Any]] = [
    {
        "source": "C&EN (ACS)",
        "url": "https://feeds.feedburner.com/cen_latestnews",
        "broad": False,
    },
    {
        "source": "Nature Chemistry",
        "url": "https://www.nature.com/nchem.rss",
        "broad": False,
    },
    {
        "source": "Science",
        "url": "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science",
        "broad": True,
    },
    {
        "source": "Chemistry World News (RSC)",
        "url": "https://www.chemistryworld.com/409.rss",
        "broad": False,
    },
    {
        "source": "Chemistry World Research (RSC)",
        "url": "https://www.chemistryworld.com/410.rss",
        "broad": False,
    },
]

SOURCE_WEIGHTS = {
    "Nature Chemistry": 80,
    "JACS": 78,
    "Angewandte Chemie": 76,
    "Science": 74,
    "Chemical Science": 68,
    "Chemical Society Reviews": 68,
    "ACS Central Science": 66,
    "ACS Catalysis": 64,
    "ACS Energy Letters": 64,
    "Energy & Environmental Science": 64,
    "PubMed": 55,
    "arXiv": 48,
}


@dataclass
class NewsItem:
    title: str
    source: str
    published: datetime | None
    link: str
    abstract: str = ""
    doi: str = ""
    authors: list[str] = field(default_factory=list)
    field_name: str = "综合化学"
    item_id: str = ""
    chinese_title: str = ""
    comment: str = ""
    score: float = 0.0


@dataclass
class SourceStatus:
    name: str
    success: bool
    item_count: int = 0
    error: str = ""

    def summary(self) -> str:
        if self.success:
            return f"成功，获取 {self.item_count} 条"
        return f"失败：{self.error or '未知错误'}"


@dataclass
class LLMConfig:
    provider: str
    model: str
    api_key: str
    api_key_env: str
    base_url: str | None = None


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    if "<" in text and ">" in text and BeautifulSoup is not None:
        text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if dateparser is None:
        return None
    try:
        parsed = dateparser.parse(str(value))
    except (TypeError, ValueError, OverflowError):
        return None
    if not parsed:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def date_parts_to_datetime(value: dict[str, Any] | None) -> datetime | None:
    if not value:
        return None
    parts_list = value.get("date-parts") or []
    if not parts_list or not parts_list[0]:
        return None
    parts = parts_list[0]
    try:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 1
        day = int(parts[2]) if len(parts) > 2 else 1
        return datetime(year, month, day, tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def format_date(value: datetime | None) -> str:
    if not value:
        return "未知日期"
    return value.astimezone().strftime("%Y-%m-%d")


def truncate(text: str, limit: int) -> str:
    text = clean_text(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def build_session() -> requests.Session:
    if requests is None or Retry is None or HTTPAdapter is None:
        raise RuntimeError("requests is not installed")
    session = requests.Session()
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=0.8,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": os.getenv("CHEM_NEWS_USER_AGENT", USER_AGENT)})
    return session


def classify_field(title: str, abstract: str) -> str:
    haystack = f"{title} {abstract}".lower()
    scores: dict[str, int] = {}
    for field_name, keywords in FIELD_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            if keyword.lower() in haystack:
                score += 2 if " " in keyword else 1
        if score:
            scores[field_name] = score
    if not scores:
        return "综合化学"
    return max(scores.items(), key=lambda item: item[1])[0]


def is_chemistry_relevant(item: NewsItem) -> bool:
    haystack = f"{item.title} {item.abstract}".lower()
    return any(term in haystack for term in CHEMISTRY_TERMS)


def text_from_xml(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return clean_text("".join(element.itertext()))


def fetch_arxiv(session: requests.Session, since: datetime, until: datetime, max_items: int) -> list[NewsItem]:
    search_terms = []
    for term in ARXIV_QUERY_TERMS:
        if " " in term:
            search_terms.append(f'all:"{term}"')
        else:
            search_terms.append(f"all:{term}")
    params = {
        "search_query": " OR ".join(search_terms),
        "start": 0,
        "max_results": min(max(max_items, 10), 100),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    response = session.get("https://export.arxiv.org/api/query", params=params, timeout=30)
    response.raise_for_status()
    feed = feedparser.parse(response.text)
    items: list[NewsItem] = []
    for entry in feed.entries:
        published = parse_datetime(getattr(entry, "published", None)) or parse_datetime(
            getattr(entry, "updated", None)
        )
        if published and not (since <= published <= until):
            continue
        title = clean_text(getattr(entry, "title", ""))
        abstract = clean_text(getattr(entry, "summary", ""))
        link = clean_text(getattr(entry, "link", ""))
        authors = [clean_text(author.get("name", "")) for author in getattr(entry, "authors", [])]
        if not title or not link:
            continue
        item = NewsItem(
            title=title,
            source="arXiv",
            published=published,
            link=link,
            abstract=abstract,
            authors=[author for author in authors if author],
        )
        item.field_name = classify_field(item.title, item.abstract)
        if is_chemistry_relevant(item):
            items.append(item)
    return items


def pubmed_params(extra: dict[str, Any]) -> dict[str, Any]:
    params = {"tool": "chem_news_daily", **extra}
    if os.getenv("NCBI_EMAIL"):
        params["email"] = os.environ["NCBI_EMAIL"]
    if os.getenv("NCBI_API_KEY"):
        params["api_key"] = os.environ["NCBI_API_KEY"]
    return params


def parse_pubmed_date(article: ET.Element) -> datetime | None:
    article_date = article.find(".//ArticleDate")
    if article_date is not None:
        year = text_from_xml(article_date.find("Year"))
        month = text_from_xml(article_date.find("Month"))
        day = text_from_xml(article_date.find("Day"))
        parsed = parse_datetime("-".join(part for part in [year, month, day] if part))
        if parsed:
            return parsed

    pub_date = article.find(".//Journal/JournalIssue/PubDate")
    if pub_date is None:
        return None
    year = text_from_xml(pub_date.find("Year"))
    month = text_from_xml(pub_date.find("Month"))
    day = text_from_xml(pub_date.find("Day"))
    medline_date = text_from_xml(pub_date.find("MedlineDate"))
    raw = " ".join(part for part in [year, month, day] if part) or medline_date
    return parse_datetime(raw)


def fetch_pubmed(session: requests.Session, since: datetime, until: datetime, max_items: int) -> list[NewsItem]:
    from_date = since.strftime("%Y/%m/%d")
    to_date = until.strftime("%Y/%m/%d")
    term_query = " OR ".join(f'"{term}"[Title/Abstract]' for term in PUBMED_QUERY_TERMS)
    query = f"({term_query}) AND ({from_date}[PDAT] : {to_date}[PDAT])"
    search_response = session.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        params=pubmed_params(
            {
                "db": "pubmed",
                "term": query,
                "retmode": "json",
                "retmax": min(max(max_items, 10), 100),
                "sort": "pub date",
            }
        ),
        timeout=30,
    )
    search_response.raise_for_status()
    id_list = search_response.json().get("esearchresult", {}).get("idlist", [])
    if not id_list:
        return []

    fetch_response = session.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
        params=pubmed_params({"db": "pubmed", "id": ",".join(id_list), "retmode": "xml"}),
        timeout=45,
    )
    fetch_response.raise_for_status()
    root = ET.fromstring(fetch_response.content)
    items: list[NewsItem] = []
    for article in root.findall(".//PubmedArticle"):
        pmid = text_from_xml(article.find(".//PMID"))
        title = text_from_xml(article.find(".//ArticleTitle"))
        journal = text_from_xml(article.find(".//Journal/Title")) or "PubMed"
        published = parse_pubmed_date(article)
        if published and not (since <= published <= until):
            continue
        abstract_parts = []
        for abstract_element in article.findall(".//Abstract/AbstractText"):
            label = clean_text(abstract_element.attrib.get("Label", ""))
            text = text_from_xml(abstract_element)
            if not text:
                continue
            abstract_parts.append(f"{label}: {text}" if label else text)
        authors = []
        for author in article.findall(".//Author"):
            last_name = text_from_xml(author.find("LastName"))
            initials = text_from_xml(author.find("Initials"))
            full = " ".join(part for part in [last_name, initials] if part)
            if full:
                authors.append(full)
        doi = ""
        for article_id in article.findall(".//ArticleId"):
            if article_id.attrib.get("IdType") == "doi":
                doi = text_from_xml(article_id)
                break
        if not title or not pmid:
            continue
        item = NewsItem(
            title=title,
            source=f"PubMed: {journal}",
            published=published,
            link=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            abstract=" ".join(abstract_parts),
            doi=doi,
            authors=authors,
        )
        item.field_name = classify_field(item.title, item.abstract)
        if is_chemistry_relevant(item):
            items.append(item)
    return items


def crossref_polite_params(extra: dict[str, Any]) -> dict[str, Any]:
    params = dict(extra)
    if os.getenv("CROSSREF_MAILTO"):
        params["mailto"] = os.environ["CROSSREF_MAILTO"]
    return params


def crossref_publication_date(work: dict[str, Any]) -> datetime | None:
    for key in ["published-online", "published-print", "published", "issued", "created"]:
        published = date_parts_to_datetime(work.get(key))
        if published:
            return published
    return None


def fetch_crossref_journal(
    session: requests.Session,
    journal: dict[str, Any],
    since: datetime,
    until: datetime,
    rows_per_issn: int,
) -> list[NewsItem]:
    items: list[NewsItem] = []
    seen: set[str] = set()
    for issn in journal["issns"]:
        params = crossref_polite_params(
            {
                "filter": (
                    f"from-pub-date:{since.date().isoformat()},"
                    f"until-pub-date:{until.date().isoformat()},"
                    f"type:journal-article,issn:{issn}"
                ),
                "sort": "published",
                "order": "desc",
                "rows": min(max(rows_per_issn, 5), 50),
            }
        )
        response = session.get("https://api.crossref.org/works", params=params, timeout=30)
        response.raise_for_status()
        works = response.json().get("message", {}).get("items", [])
        for work in works:
            doi = clean_text(work.get("DOI", ""))
            if doi and doi.lower() in seen:
                continue
            title = clean_text((work.get("title") or [""])[0])
            if not title:
                continue
            container_title = clean_text((work.get("container-title") or [journal["source"]])[0])
            published = crossref_publication_date(work)
            if published and not (since <= published <= until):
                continue
            abstract = clean_text(work.get("abstract", ""))
            link = clean_text(work.get("URL", "")) or (f"https://doi.org/{doi}" if doi else "")
            author_names = []
            for author in work.get("author", [])[:8]:
                given = clean_text(author.get("given", ""))
                family = clean_text(author.get("family", ""))
                full = " ".join(part for part in [given, family] if part)
                if full:
                    author_names.append(full)
            item = NewsItem(
                title=title,
                source=journal["source"] if journal["source"] in container_title else container_title,
                published=published,
                link=link,
                abstract=abstract or "出版商元数据未提供摘要；请通过链接查看原文摘要。",
                doi=doi,
                authors=author_names,
            )
            item.field_name = classify_field(item.title, item.abstract)
            if not journal.get("broad") or is_chemistry_relevant(item):
                items.append(item)
                if doi:
                    seen.add(doi.lower())
        time.sleep(0.15)
    return items


def fetch_crossref(
    session: requests.Session, since: datetime, until: datetime, max_items: int
) -> tuple[list[NewsItem], list[SourceStatus]]:
    items: list[NewsItem] = []
    statuses: list[SourceStatus] = []
    rows_per_issn = max(5, min(20, max_items // max(len(CROSSREF_JOURNALS), 1) + 2))
    for journal in CROSSREF_JOURNALS:
        try:
            journal_items = fetch_crossref_journal(session, journal, since, until, rows_per_issn)
            LOGGER.info("%s via Crossref: %d items", journal["source"], len(journal_items))
            items.extend(journal_items)
            statuses.append(
                SourceStatus(
                    name=f"Crossref: {journal['source']}",
                    success=True,
                    item_count=len(journal_items),
                )
            )
        except Exception as exc:  # noqa: BLE001 - one journal must not stop the report.
            LOGGER.warning("Crossref source failed for %s: %s", journal["source"], exc)
            statuses.append(
                SourceStatus(
                    name=f"Crossref: {journal['source']}",
                    success=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    return items, statuses


def fetch_rss(
    session: requests.Session, since: datetime, until: datetime, max_items: int
) -> tuple[list[NewsItem], list[SourceStatus]]:
    items: list[NewsItem] = []
    statuses: list[SourceStatus] = []
    per_feed = max(10, min(40, max_items // max(len(RSS_FEEDS), 1) + 5))
    for feed_config in RSS_FEEDS:
        try:
            response = session.get(feed_config["url"], timeout=30)
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
            count = 0
            for entry in parsed.entries[:per_feed]:
                published = parse_datetime(
                    getattr(entry, "published", None) or getattr(entry, "updated", None)
                )
                if published and not (since <= published <= until):
                    continue
                title = clean_text(getattr(entry, "title", ""))
                abstract = clean_text(
                    getattr(entry, "summary", "") or getattr(entry, "description", "")
                )
                link = clean_text(getattr(entry, "link", ""))
                if not title or not link:
                    continue
                item = NewsItem(
                    title=title,
                    source=feed_config["source"],
                    published=published,
                    link=link,
                    abstract=abstract or "RSS 未提供摘要；请通过链接查看详情。",
                )
                item.field_name = classify_field(item.title, item.abstract)
                if not feed_config.get("broad") or is_chemistry_relevant(item):
                    items.append(item)
                    count += 1
            LOGGER.info("%s RSS: %d items", feed_config["source"], count)
            statuses.append(
                SourceStatus(
                    name=f"RSS: {feed_config['source']}",
                    success=True,
                    item_count=count,
                )
            )
        except Exception as exc:  # noqa: BLE001 - RSS endpoints are best-effort.
            LOGGER.warning("RSS source failed for %s: %s", feed_config["source"], exc)
            statuses.append(
                SourceStatus(
                    name=f"RSS: {feed_config['source']}",
                    success=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    return items, statuses


def dedupe_items(items: list[NewsItem]) -> list[NewsItem]:
    unique: dict[str, NewsItem] = {}
    for item in items:
        if item.doi:
            key = f"doi:{item.doi.lower()}"
        elif item.link:
            key = f"url:{item.link.rstrip('/').lower()}"
        else:
            normalized_title = re.sub(r"\W+", "", item.title.lower())
            key = f"title:{normalized_title}"
        existing = unique.get(key)
        if existing is None:
            unique[key] = item
            continue
        if len(item.abstract) > len(existing.abstract):
            unique[key] = item
    return list(unique.values())


def rank_item(item: NewsItem, now: datetime) -> float:
    source_weight = 45
    for source_prefix, weight in SOURCE_WEIGHTS.items():
        if item.source.startswith(source_prefix) or source_prefix in item.source:
            source_weight = weight
            break
    haystack = f"{item.title} {item.abstract}".lower()
    keyword_hits = sum(1 for term in CHEMISTRY_TERMS if term in haystack)
    learning_bonus = sum(weight for term, weight in LEARNING_VALUE_TERMS.items() if term in haystack)
    abstract_bonus = min(len(item.abstract) / 450, 6)
    title_bonus = 4 if any(term in item.title.lower() for term in LEARNING_VALUE_TERMS) else 0
    metadata_penalty = 5 if "未提供摘要" in item.abstract or not item.abstract else 0
    recency_bonus = 0.0
    if item.published:
        age_hours = max((now - item.published).total_seconds() / 3600, 0)
        recency_bonus = max(0, 72 - age_hours) / 72 * 10
    return (
        source_weight
        + keyword_hits * 1.4
        + learning_bonus
        + title_bonus
        + abstract_bonus
        + recency_bonus
        - metadata_penalty
    )


def prepare_items(items: list[NewsItem], max_items: int, now: datetime) -> list[NewsItem]:
    unique = dedupe_items(items)
    for item in unique:
        item.field_name = classify_field(item.title, item.abstract)
        item.score = rank_item(item, now)
    ranked = sorted(
        unique,
        key=lambda item: (
            item.score,
            item.published.timestamp() if item.published else 0,
            item.title,
        ),
        reverse=True,
    )
    for index, item in enumerate(ranked[:max_items], start=1):
        item.item_id = f"N{index:03d}"
    return ranked[:max_items]


def fallback_comment(item: NewsItem) -> str:
    abstract = truncate(item.abstract, 120)
    if abstract and "未提供摘要" not in abstract:
        return f"该条目聚焦{item.field_name}方向，摘要显示其主要内容为：{abstract}"
    return f"该条目与{item.field_name}相关；出版商元数据较少，建议打开链接核对摘要和全文。"


def apply_fallback_summaries(items: list[NewsItem]) -> None:
    for item in items:
        item.chinese_title = item.chinese_title or item.title
        item.comment = item.comment or fallback_comment(item)


def chat_response_text(response: Any) -> str:
    choices = getattr(response, "choices", []) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    if message is None:
        return ""
    content = getattr(message, "content", "")
    if isinstance(content, list):
        pieces = []
        for part in content:
            if isinstance(part, dict):
                pieces.append(str(part.get("text") or part.get("content") or ""))
            else:
                pieces.append(str(getattr(part, "text", "") or getattr(part, "content", "")))
        return "\n".join(piece for piece in pieces if piece)
    return str(content or "")


def parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def resolve_llm_config(model_override: str = "") -> LLMConfig | None:
    provider = os.getenv("LLM_PROVIDER", "openai").strip().lower() or "openai"
    if provider not in SUPPORTED_LLM_PROVIDERS:
        LOGGER.warning(
            "Unsupported LLM_PROVIDER=%s; supported values are openai or deepseek. "
            "Using fallback summaries.",
            provider,
        )
        return None

    if provider == "deepseek":
        return LLMConfig(
            provider="deepseek",
            model=model_override or os.getenv("DEEPSEEK_MODEL") or DEFAULT_DEEPSEEK_MODEL,
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            api_key_env="DEEPSEEK_API_KEY",
            base_url="https://api.deepseek.com",
        )

    return LLMConfig(
        provider="openai",
        model=model_override or os.getenv("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL,
        api_key=os.getenv("OPENAI_API_KEY", ""),
        api_key_env="OPENAI_API_KEY",
    )


def generate_ai_summaries(items: list[NewsItem], model: str, max_ai_items: int) -> dict[str, Any]:
    if not items:
        return {"top_ids": [], "field_summaries": []}
    if OpenAI is None:
        LOGGER.warning("openai package is not installed; using fallback summaries.")
        apply_fallback_summaries(items)
        return fallback_report_payload(items)

    llm_config = resolve_llm_config(model)
    if llm_config is None:
        apply_fallback_summaries(items)
        return fallback_report_payload(items)
    if not llm_config.api_key:
        LOGGER.warning("%s is not set; using fallback summaries.", llm_config.api_key_env)
        apply_fallback_summaries(items)
        return fallback_report_payload(items)

    payload = [
        {
            "id": item.item_id,
            "field": item.field_name,
            "source": item.source,
            "published": format_date(item.published),
            "title": item.title,
            "abstract": truncate(item.abstract, 900),
            "link": item.link,
        }
        for item in items[:max_ai_items]
    ]
    instructions = (
        "你是化学领域科研编辑。请基于输入论文/资讯元数据生成中文日报素材。"
        "要求准确、克制，不夸大结论；如果摘要不足，要说明信息有限。"
        "只输出 JSON，不要输出 Markdown。"
    )
    prompt = {
        "task": "生成化学科研资讯日报摘要",
        "schema": {
            "top_ids": ["N001"],
            "field_summaries": [{"field": "有机化学", "summary": "80字以内中文概述"}],
            "items": [
                {
                    "id": "N001",
                    "chinese_title": "中文标题，尽量准确翻译英文题名",
                    "comment": "80-120字中文简评，说明研究对象、方法或潜在意义",
                }
            ],
        },
        "selection_rules": [
            "top_ids 选 5 条最值得关注的条目，兼顾来源权威性、新近性和领域覆盖。",
            "items 必须覆盖输入中的每一个 id。",
            "field_summaries 只覆盖输入中实际出现的领域。",
        ],
        "items": payload,
    }

    client_kwargs = {"api_key": llm_config.api_key}
    if llm_config.base_url:
        client_kwargs["base_url"] = llm_config.base_url
    client = OpenAI(**client_kwargs)
    try:
        response = client.chat.completions.create(
            model=llm_config.model,
            messages=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            temperature=0.2,
            max_tokens=9000,
        )
        raw_response = chat_response_text(response)
        parsed = parse_json_object(raw_response)
    except Exception as exc:  # noqa: BLE001 - AI failure should not block the document.
        LOGGER.warning("%s summary generation failed: %s", llm_config.provider, exc)
        apply_fallback_summaries(items)
        return fallback_report_payload(items)

    by_id = {entry.get("id"): entry for entry in parsed.get("items", []) if isinstance(entry, dict)}
    for item in items:
        generated = by_id.get(item.item_id, {})
        item.chinese_title = clean_text(generated.get("chinese_title", "")) or item.title
        item.comment = clean_text(generated.get("comment", "")) or fallback_comment(item)
    apply_fallback_summaries(items)
    top_ids = [
        item_id
        for item_id in parsed.get("top_ids", [])
        if isinstance(item_id, str) and any(item.item_id == item_id for item in items)
    ]
    if len(top_ids) < 5:
        existing = set(top_ids)
        for item in items:
            if item.item_id not in existing:
                top_ids.append(item.item_id)
            if len(top_ids) >= 5:
                break
    field_summaries = parsed.get("field_summaries", [])
    if not isinstance(field_summaries, list):
        field_summaries = []
    return {"top_ids": top_ids[:5], "field_summaries": field_summaries}


def fallback_report_payload(items: list[NewsItem]) -> dict[str, Any]:
    top_ids = [item.item_id for item in items[:5]]
    grouped: dict[str, list[NewsItem]] = {}
    for item in items:
        grouped.setdefault(item.field_name, []).append(item)
    field_summaries = [
        {
            "field": field_name,
            "summary": f"共检索到 {len(group_items)} 条相关资讯，主要来源包括："
            f"{'、'.join(sorted({entry.source for entry in group_items})[:4])}。",
        }
        for field_name, group_items in grouped.items()
    ]
    return {"top_ids": top_ids, "field_summaries": field_summaries}


def add_hyperlink(paragraph: Any, text: str, url: str) -> None:
    if not url:
        paragraph.add_run(text)
        return
    part = paragraph.part
    relationship_id = part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), relationship_id)

    run = OxmlElement("w:r")
    properties = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "0563C1")
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    properties.append(color)
    properties.append(underline)
    run.append(properties)

    text_element = OxmlElement("w:t")
    text_element.text = text
    run.append(text_element)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)  # noqa: SLF001 - python-docx hyperlink helper requires OXML.


def set_run_font(
    run: Any,
    name: str = "Arial",
    east_asia: str = "Microsoft YaHei",
    size: float | None = None,
    color: RGBColor | None = None,
    bold: bool | None = None,
    italic: bool | None = None,
) -> None:
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:ascii"), name)  # noqa: SLF001
    run._element.rPr.rFonts.set(qn("w:hAnsi"), name)  # noqa: SLF001
    run._element.rPr.rFonts.set(qn("w:eastAsia"), east_asia)  # noqa: SLF001
    if size is not None:
        run.font.size = Pt(size)
    if color is not None:
        run.font.color.rgb = color
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic


def paragraph_border_bottom(paragraph: Any, color: str = "D9E2EC", size: str = "8") -> None:
    properties = paragraph._p.get_or_add_pPr()  # noqa: SLF001
    borders = properties.find(qn("w:pBdr"))
    if borders is None:
        borders = OxmlElement("w:pBdr")
        properties.append(borders)
    bottom = borders.find(qn("w:bottom"))
    if bottom is None:
        bottom = OxmlElement("w:bottom")
        borders.append(bottom)
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), size)
    bottom.set(qn("w:space"), "3")
    bottom.set(qn("w:color"), color)


def set_paragraph_shading(paragraph: Any, fill: str = "F6F8FA") -> None:
    properties = paragraph._p.get_or_add_pPr()  # noqa: SLF001
    shading = properties.find(qn("w:shd"))
    if shading is None:
        shading = OxmlElement("w:shd")
        properties.append(shading)
    shading.set(qn("w:fill"), fill)


def add_spacer(document: Document, points: float) -> None:
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(points)


def set_document_fonts(document: Document) -> None:
    section = document.sections[0]
    section.top_margin = Inches(0.82)
    section.bottom_margin = Inches(0.72)
    section.left_margin = Inches(0.86)
    section.right_margin = Inches(0.86)
    section.header_distance = Inches(0.36)
    section.footer_distance = Inches(0.36)

    styles = document.styles
    for style_name in ["Normal", "Title", "Heading 1", "Heading 2", "Heading 3"]:
        style = styles[style_name]
        style.font.name = "Arial"
        style._element.rPr.rFonts.set(qn("w:ascii"), "Arial")  # noqa: SLF001
        style._element.rPr.rFonts.set(qn("w:hAnsi"), "Arial")  # noqa: SLF001
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")  # noqa: SLF001
    normal = styles["Normal"]
    normal.font.size = Pt(9.6)
    normal.font.color.rgb = RGBColor(31, 41, 55)
    normal.paragraph_format.space_after = Pt(4.5)
    normal.paragraph_format.line_spacing = 1.28

    styles["Title"].font.size = Pt(22)
    styles["Title"].font.bold = True
    styles["Title"].font.color.rgb = RGBColor(17, 24, 39)
    styles["Title"].paragraph_format.space_after = Pt(4)

    styles["Heading 1"].font.size = Pt(13)
    styles["Heading 1"].font.bold = True
    styles["Heading 1"].font.color.rgb = RGBColor(15, 76, 117)
    styles["Heading 1"].paragraph_format.space_before = Pt(16)
    styles["Heading 1"].paragraph_format.space_after = Pt(7)

    styles["Heading 2"].font.size = Pt(11.5)
    styles["Heading 2"].font.bold = True
    styles["Heading 2"].font.color.rgb = RGBColor(15, 76, 117)
    styles["Heading 2"].paragraph_format.space_before = Pt(10)
    styles["Heading 2"].paragraph_format.space_after = Pt(5)

    styles["Heading 3"].font.size = Pt(10.3)
    styles["Heading 3"].font.bold = True
    styles["Heading 3"].font.color.rgb = RGBColor(17, 24, 39)
    styles["Heading 3"].paragraph_format.space_before = Pt(6)
    styles["Heading 3"].paragraph_format.space_after = Pt(2)


def add_label_value(document: Document, label: str, value: str, link: str = "") -> None:
    paragraph = document.add_paragraph()
    label_run = paragraph.add_run(f"{label}：")
    label_run.bold = True
    if link:
        add_hyperlink(paragraph, value, link)
    else:
        paragraph.add_run(value)


def add_masthead(document: Document, report_date: date, item_count: int) -> None:
    section = document.sections[0]
    header = section.header.paragraphs[0]
    header.text = ""
    header.paragraph_format.space_after = Pt(0)
    run = header.add_run("CHEM NEWS DAILY")
    set_run_font(run, size=8.5, color=RGBColor(107, 114, 128), bold=True)
    paragraph_border_bottom(header, color="E5E7EB", size="4")

    footer = section.footer.paragraphs[0]
    footer.text = ""
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = footer.add_run("Generated by chem-news-daily")
    set_run_font(run, size=8, color=RGBColor(156, 163, 175))

    kicker = document.add_paragraph()
    kicker.paragraph_format.space_before = Pt(0)
    kicker.paragraph_format.space_after = Pt(5)
    run = kicker.add_run("DAILY RESEARCH BRIEF")
    set_run_font(run, size=8.5, color=RGBColor(15, 76, 117), bold=True)

    title = document.add_paragraph()
    title.style = document.styles["Title"]
    title.paragraph_format.space_before = Pt(0)
    title.paragraph_format.space_after = Pt(7)
    run = title.add_run("化学科研资讯日报")
    set_run_font(run, size=22, color=RGBColor(17, 24, 39), bold=True)

    meta = document.add_paragraph()
    meta.paragraph_format.space_before = Pt(2)
    meta.paragraph_format.space_after = Pt(11)
    meta.paragraph_format.line_spacing = 1.2
    run = meta.add_run(f"{report_date.isoformat()}  /  精选 {item_count} 篇  /  有机、物化、材料、化学生物、催化、能源、计算、分析")
    set_run_font(run, size=9.2, color=RGBColor(75, 85, 99))
    paragraph_border_bottom(meta, color="CBD5E1", size="10")


def add_source_note(document: Document, item_count: int) -> None:
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(2)
    paragraph.paragraph_format.space_after = Pt(9)
    run = paragraph.add_run(
        f"本期收录 {item_count} 条，经来源权重、研究新近性、摘要信息量和学习价值信号排序；单源异常会在运行诊断中标记。"
    )
    set_run_font(run, size=9, color=RGBColor(75, 85, 99))


def add_top_item_block(document: Document, item: NewsItem, index: int) -> None:
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(3)
    paragraph.paragraph_format.space_after = Pt(1)
    label = paragraph.add_run(f"{index:02d}  ")
    set_run_font(label, size=9.2, color=RGBColor(15, 76, 117), bold=True)
    title_run = paragraph.add_run(item.chinese_title or item.title)
    set_run_font(title_run, size=10.2, color=RGBColor(17, 24, 39), bold=True)

    meta = document.add_paragraph()
    meta.paragraph_format.space_before = Pt(0)
    meta.paragraph_format.space_after = Pt(1)
    run = meta.add_run(f"{item.field_name}  |  {item.source}  |  {format_date(item.published)}")
    set_run_font(run, size=8.5, color=RGBColor(107, 114, 128))

    comment = document.add_paragraph()
    comment.paragraph_format.space_before = Pt(0)
    comment.paragraph_format.space_after = Pt(6)
    comment.paragraph_format.line_spacing = 1.22
    run = comment.add_run(truncate(item.comment or fallback_comment(item), 150))
    set_run_font(run, size=9, color=RGBColor(55, 65, 81))
    paragraph_border_bottom(comment, color="EEF2F7", size="4")


def add_item_block(document: Document, item: NewsItem) -> None:
    heading = document.add_paragraph()
    heading.style = document.styles["Heading 3"]
    heading.paragraph_format.keep_with_next = True
    heading.add_run(item.chinese_title or item.title)

    meta = document.add_paragraph()
    meta.paragraph_format.space_before = Pt(0)
    meta.paragraph_format.space_after = Pt(2)
    run = meta.add_run(f"{item.source}  |  {format_date(item.published)}  |  {item.field_name}")
    set_run_font(run, size=8.5, color=RGBColor(107, 114, 128))

    english = document.add_paragraph()
    english.paragraph_format.space_before = Pt(0)
    english.paragraph_format.space_after = Pt(2)
    label = english.add_run("EN  ")
    set_run_font(label, size=8.2, color=RGBColor(15, 76, 117), bold=True)
    run = english.add_run(item.title)
    set_run_font(run, size=9, color=RGBColor(55, 65, 81), italic=True)

    comment = document.add_paragraph()
    comment.paragraph_format.space_before = Pt(1)
    comment.paragraph_format.space_after = Pt(4)
    comment.paragraph_format.line_spacing = 1.24
    comment.paragraph_format.left_indent = Inches(0.06)
    set_paragraph_shading(comment, fill="F8FAFC")
    label = comment.add_run("简评  ")
    set_run_font(label, size=8.7, color=RGBColor(15, 76, 117), bold=True)
    run = comment.add_run(item.comment or fallback_comment(item))
    set_run_font(run, size=9.2, color=RGBColor(31, 41, 55))

    abstract = truncate(item.abstract, 420)
    if abstract:
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(3)
        paragraph.paragraph_format.line_spacing = 1.22
        label = paragraph.add_run("摘要  ")
        set_run_font(label, size=8.7, color=RGBColor(107, 114, 128), bold=True)
        run = paragraph.add_run(abstract)
        set_run_font(run, size=8.8, color=RGBColor(75, 85, 99))

    links = document.add_paragraph()
    links.paragraph_format.space_before = Pt(0)
    links.paragraph_format.space_after = Pt(7)
    links.paragraph_format.line_spacing = 1.18
    label = links.add_run("链接  ")
    set_run_font(label, size=8.5, color=RGBColor(107, 114, 128), bold=True)
    add_hyperlink(links, item.link, item.link)
    if item.doi:
        links.add_run("   DOI  ")
        add_hyperlink(links, item.doi, f"https://doi.org/{item.doi}")
    paragraph_border_bottom(links, color="E5E7EB", size="4")


def diagnostics_has_issue(diagnostics: Any | None) -> bool:
    return bool(diagnostics is not None and not getattr(diagnostics, "network_ok", False))


def source_has_failures(source_statuses: list[SourceStatus] | None) -> bool:
    return any(not status.success for status in source_statuses or [])


def add_run_diagnostics_section(
    document: Document,
    diagnostics: Any | None,
    source_statuses: list[SourceStatus] | None,
) -> None:
    if not diagnostics_has_issue(diagnostics) and not source_has_failures(source_statuses):
        return

    document.add_heading("运行诊断", level=1)
    if diagnostics is not None:
        if getattr(diagnostics, "network_ok", False):
            document.add_paragraph("网络诊断：DNS 与 HTTPS 探测均正常。")
        else:
            document.add_paragraph("网络诊断：发现 DNS 或 HTTPS 访问异常。")
        for line in diagnostics.summary_lines():
            document.add_paragraph(line, style=document.styles["List Bullet"])
    else:
        document.add_paragraph("网络诊断：未执行。")

    failed_statuses = [status for status in source_statuses or [] if not status.success]
    if failed_statuses:
        document.add_paragraph("失败来源：")
        for status in failed_statuses:
            document.add_paragraph(
                f"{status.name}: {status.error or '未知错误'}",
                style=document.styles["List Bullet"],
            )


def create_document(
    items: list[NewsItem],
    report_payload: dict[str, Any],
    report_date: date,
    output_dir: Path,
    diagnostics: Any | None = None,
    source_statuses: list[SourceStatus] | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    document = Document()
    set_document_fonts(document)

    add_masthead(document, report_date, len(items))
    add_source_note(document, len(items))
    add_run_diagnostics_section(document, diagnostics, source_statuses)

    by_id = {item.item_id: item for item in items}
    top_items = [by_id[item_id] for item_id in report_payload.get("top_ids", []) if item_id in by_id]
    if len(top_items) < 5:
        existing = {item.item_id for item in top_items}
        top_items.extend([item for item in items if item.item_id not in existing][: 5 - len(top_items)])

    document.add_heading("今日重点 5 条", level=1)
    for index, item in enumerate(top_items[:5], start=1):
        add_top_item_block(document, item, index)

    document.add_heading("分领域摘要", level=1)
    field_summary_map: dict[str, str] = {}
    for entry in report_payload.get("field_summaries", []):
        if isinstance(entry, dict) and entry.get("field") and entry.get("summary"):
            field_summary_map[clean_text(entry["field"])] = clean_text(entry["summary"])

    grouped: dict[str, list[NewsItem]] = {}
    for item in items:
        grouped.setdefault(item.field_name, []).append(item)

    ordered_fields = list(FIELD_KEYWORDS.keys()) + ["综合化学"]
    for field_name in ordered_fields:
        group_items = grouped.get(field_name, [])
        if not group_items:
            continue
        document.add_heading(field_name, level=2)
        summary = field_summary_map.get(
            field_name,
            f"本领域收录 {len(group_items)} 条，主要覆盖近期论文、期刊上线内容和科研资讯。",
        )
        summary_paragraph = document.add_paragraph()
        summary_paragraph.paragraph_format.space_after = Pt(6)
        summary_paragraph.paragraph_format.line_spacing = 1.25
        run = summary_paragraph.add_run(summary)
        set_run_font(run, size=9.2, color=RGBColor(55, 65, 81))
        for item in group_items:
            add_item_block(document, item)

    output_path = output_dir / f"chem_news_{report_date.isoformat()}.docx"
    document.save(output_path)
    return output_path


def source_failure_recommendations(
    diagnostics: Any | None,
    source_statuses: list[SourceStatus],
    zero_items: bool,
) -> list[str]:
    recommendations: list[str] = []
    dns_failed_hosts = getattr(diagnostics, "dns_failed_hosts", []) if diagnostics else []
    https_failed_hosts = getattr(diagnostics, "https_failed_hosts", []) if diagnostics else []
    failed_statuses = [status for status in source_statuses if not status.success]

    if dns_failed_hosts:
        recommendations.append(
            "检查 DNS、代理或 VPN 配置，确认 arxiv.org、pubmed.ncbi.nlm.nih.gov、api.crossref.org 可以解析。"
        )
    if https_failed_hosts:
        recommendations.append(
            "检查 HTTPS 出口、代理证书、公司/校园网 TLS 拦截，以及 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY 环境变量。"
        )
    if failed_statuses:
        recommendations.append(
            "查看日志中失败来源的异常信息；单个来源失败通常可以稍后重试，或暂时降低 --source-limit。"
        )
    if zero_items and not failed_statuses:
        recommendations.append(
            "网络和来源没有抛出异常但结果为 0 条时，可扩大 --days、提高 --source-limit，或稍后重试。"
        )
    recommendations.append("在项目目录运行 `.venv/bin/python network_check.py` 可单独复查网络。")
    recommendations.append("手动指定输出目录时使用 `--output-dir /path/to/output`，默认输出在项目内 `./output`。")
    return recommendations


def create_failure_report(
    report_date: date,
    output_dir: Path,
    diagnostics: Any | None,
    source_statuses: list[SourceStatus],
    reason: str,
    collected_count: int,
    prepared_count: int,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    document = Document()
    set_document_fonts(document)

    title = document.add_heading("化学科研资讯日报运行失败报告", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.runs[0].font.color.rgb = RGBColor(192, 0, 0)

    document.add_paragraph(f"日期：{report_date.isoformat()}")
    document.add_paragraph(f"失败原因：{reason}")
    document.add_paragraph(f"原始抓取条数：{collected_count}；去重过滤后条数：{prepared_count}")

    document.add_heading("DNS 是否失败", level=1)
    if diagnostics is None:
        document.add_paragraph("未执行网络诊断。")
    else:
        dns_failed_hosts = getattr(diagnostics, "dns_failed_hosts", [])
        if dns_failed_hosts:
            document.add_paragraph(f"DNS 失败主机：{'、'.join(dns_failed_hosts)}")
        else:
            document.add_paragraph("DNS 解析未发现失败。")
        document.add_heading("网络诊断详情", level=2)
        for line in diagnostics.summary_lines():
            document.add_paragraph(line, style=document.styles["List Bullet"])

    document.add_heading("哪些来源失败", level=1)
    if source_statuses:
        for status in source_statuses:
            document.add_paragraph(f"{status.name}: {status.summary()}", style=document.styles["List Bullet"])
    else:
        document.add_paragraph("没有记录到来源状态；可能在初始化阶段失败。")

    document.add_heading("建议修复动作", level=1)
    for recommendation in source_failure_recommendations(diagnostics, source_statuses, True):
        document.add_paragraph(recommendation, style=document.styles["List Bullet"])

    output_path = output_dir / "运行失败报告.docx"
    document.save(output_path)
    return output_path


def all_sources_failed(source_statuses: list[SourceStatus]) -> bool:
    return bool(source_statuses) and all(not status.success for status in source_statuses)


def resolve_output_dir(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parent / path


def env_flag(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def parse_email_recipients(value: str) -> list[str]:
    normalized = re.sub(r"[;\r\n]+", ",", value)
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


def find_libreoffice_executable() -> str | None:
    configured = os.getenv("LIBREOFFICE_PATH", "").strip()
    candidates: list[str] = []
    if configured:
        candidates.append(configured)
        resolved = shutil.which(configured)
        if resolved:
            candidates.append(resolved)

    for command in ("soffice", "libreoffice"):
        resolved = shutil.which(command)
        if resolved:
            candidates.append(resolved)

    candidates.extend(
        [
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
            "/usr/local/bin/soffice",
            "/usr/bin/soffice",
            "/usr/bin/libreoffice",
            "/snap/bin/libreoffice",
        ]
    )

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        candidate_path = Path(candidate)
        if candidate_path.exists() and os.access(candidate_path, os.X_OK):
            return str(candidate_path)
    return None


def convert_docx_to_pdf(docx_path: Path) -> Path | None:
    if not docx_path.exists():
        LOGGER.warning("PDF conversion skipped; DOCX does not exist: %s", docx_path)
        return None
    if docx_path.suffix.lower() != ".docx":
        LOGGER.warning("PDF conversion skipped; input is not a DOCX file: %s", docx_path)
        return None

    soffice = find_libreoffice_executable()
    if not soffice:
        LOGGER.warning(
            "PDF conversion skipped; LibreOffice executable was not found. "
            "Install LibreOffice or set LIBREOFFICE_PATH."
        )
        return None

    pdf_path = docx_path.with_suffix(".pdf")
    timeout_raw = os.getenv("PDF_CONVERT_TIMEOUT", "120").strip()
    try:
        timeout = max(10, int(timeout_raw))
    except ValueError:
        timeout = 120

    started_at = time.time()
    with tempfile.TemporaryDirectory(prefix="chem-news-lo-") as profile_dir:
        command = [
            soffice,
            f"-env:UserInstallation={Path(profile_dir).as_uri()}",
            "--headless",
            "--nologo",
            "--nofirststartwizard",
            "--convert-to",
            "pdf:writer_pdf_Export",
            "--outdir",
            str(docx_path.parent),
            str(docx_path),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            LOGGER.warning("PDF conversion timed out after %s seconds: %s", timeout, docx_path)
            return None
        except Exception as exc:  # noqa: BLE001 - conversion failure should not invalidate DOCX output.
            LOGGER.warning("PDF conversion failed to start: %s", exc)
            return None

    if result.returncode != 0:
        LOGGER.warning(
            "PDF conversion failed with exit code %s. stdout=%s stderr=%s",
            result.returncode,
            result.stdout.strip(),
            result.stderr.strip(),
        )
        return None

    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        LOGGER.warning("PDF conversion did not produce a valid file: %s", pdf_path)
        return None
    if pdf_path.stat().st_mtime < started_at - 2:
        LOGGER.warning("PDF conversion output appears stale and will not be sent: %s", pdf_path)
        return None

    LOGGER.info("Converted DOCX to PDF: %s", pdf_path)
    return pdf_path


def send_report_email(attachment_path: Path, report_date: date, is_failure: bool = False) -> bool:
    if not env_flag("EMAIL_ENABLED", True):
        LOGGER.info("Email sending is disabled by EMAIL_ENABLED.")
        return False

    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_username = os.getenv("SMTP_USERNAME", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    smtp_from = os.getenv("SMTP_FROM", "").strip() or smtp_username
    smtp_security = os.getenv("SMTP_SECURITY", "").strip().lower() or "ssl"
    smtp_port_raw = os.getenv("SMTP_PORT", "").strip()
    smtp_port = int(smtp_port_raw) if smtp_port_raw else (587 if smtp_security in {"starttls", "tls"} else 465)
    recipients = parse_email_recipients(os.getenv("REPORT_EMAIL_TO", DEFAULT_REPORT_EMAIL_TO))

    missing = [
        name
        for name, value in {
            "SMTP_HOST": smtp_host,
            "SMTP_USERNAME": smtp_username,
            "SMTP_PASSWORD": smtp_password,
            "SMTP_FROM or SMTP_USERNAME": smtp_from,
            "REPORT_EMAIL_TO": ",".join(recipients),
        }.items()
        if not value
    ]
    if missing:
        LOGGER.warning("Email not sent; missing SMTP config: %s", ", ".join(missing))
        return False
    if not attachment_path.exists():
        LOGGER.warning("Email not sent; attachment does not exist: %s", attachment_path)
        return False

    email_attachment_path = attachment_path
    local_docx_name = ""
    if attachment_path.suffix.lower() == ".docx":
        local_docx_name = attachment_path.name
        converted_path = convert_docx_to_pdf(attachment_path)
        if converted_path is None:
            LOGGER.warning("Email not sent; PDF conversion failed for %s", attachment_path)
            return False
        email_attachment_path = converted_path
    elif attachment_path.suffix.lower() != ".pdf":
        LOGGER.warning("Email not sent; only DOCX-to-PDF or PDF attachments are supported: %s", attachment_path)
        return False

    subject_prefix = "化学科研资讯日报运行失败" if is_failure else "化学科研资讯日报"
    message = EmailMessage()
    message["Subject"] = f"{subject_prefix} - {report_date.isoformat()}"
    message["From"] = smtp_from
    message["To"] = ", ".join(recipients)
    body_lines = [
        f"日期：{report_date.isoformat()}",
        f"PDF附件：{email_attachment_path.name}",
    ]
    if local_docx_name:
        body_lines.append(f"本地DOCX文件：{local_docx_name}")
    body_lines.extend(["", "本邮件由 chem-news-daily 自动发送。"])
    message.set_content("\n".join(body_lines))
    message.add_attachment(
        email_attachment_path.read_bytes(),
        maintype="application",
        subtype="pdf",
        filename=email_attachment_path.name,
    )

    try:
        if smtp_security == "ssl":
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as smtp:
                smtp.login(smtp_username, smtp_password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as smtp:
                if smtp_security in {"starttls", "tls"}:
                    smtp.starttls()
                smtp.login(smtp_username, smtp_password)
                smtp.send_message(message)
    except Exception as exc:  # noqa: BLE001 - email failure should not invalidate the report.
        LOGGER.warning("Email sending failed: %s", exc)
        return False

    LOGGER.info("Sent report email to %s with PDF attachment %s", ", ".join(recipients), email_attachment_path)
    return True


def collect_items(args: argparse.Namespace, since: datetime, until: datetime) -> tuple[list[NewsItem], list[SourceStatus]]:
    session = build_session()
    fetchers: list[tuple[str, Callable[[], list[NewsItem]]]] = [
        ("arXiv", lambda: fetch_arxiv(session, since, until, args.source_limit)),
        ("PubMed", lambda: fetch_pubmed(session, since, until, args.source_limit)),
    ]

    all_items: list[NewsItem] = []
    statuses: list[SourceStatus] = []
    for source_name, fetcher in fetchers:
        try:
            items = fetcher()
            LOGGER.info("%s returned %d items", source_name, len(items))
            all_items.extend(items)
            statuses.append(SourceStatus(name=source_name, success=True, item_count=len(items)))
        except Exception as exc:  # noqa: BLE001 - source isolation is required.
            LOGGER.exception("%s failed and was skipped: %s", source_name, exc)
            statuses.append(
                SourceStatus(
                    name=source_name,
                    success=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    try:
        crossref_items, crossref_statuses = fetch_crossref(session, since, until, args.source_limit)
        LOGGER.info("Crossref returned %d items", len(crossref_items))
        all_items.extend(crossref_items)
        statuses.extend(crossref_statuses)
    except Exception as exc:  # noqa: BLE001 - defensive guard around the grouped source.
        LOGGER.exception("Crossref failed and was skipped: %s", exc)
        statuses.append(
            SourceStatus(
                name="Crossref",
                success=False,
                error=f"{type(exc).__name__}: {exc}",
            )
        )

    try:
        rss_items, rss_statuses = fetch_rss(session, since, until, args.source_limit)
        LOGGER.info("RSS returned %d items", len(rss_items))
        all_items.extend(rss_items)
        statuses.extend(rss_statuses)
    except Exception as exc:  # noqa: BLE001 - defensive guard around the grouped source.
        LOGGER.exception("RSS failed and was skipped: %s", exc)
        statuses.append(
            SourceStatus(
                name="RSS",
                success=False,
                error=f"{type(exc).__name__}: {exc}",
            )
        )
    return all_items, statuses


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a Chinese chemistry research news daily DOCX.")
    parser.add_argument(
        "--days",
        type=int,
        default=int(os.getenv("CHEM_NEWS_DAYS", "3")),
        help="Lookback window in days. Use 1 for the most recent 24 hours, or 3 for a broader daily digest.",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=int(os.getenv("CHEM_NEWS_MAX_ITEMS", str(DEFAULT_MAX_ITEMS))),
        help="Maximum number of deduplicated items written to the report.",
    )
    parser.add_argument(
        "--source-limit",
        type=int,
        default=int(os.getenv("CHEM_NEWS_SOURCE_LIMIT", "80")),
        help="Maximum records requested from each API source before filtering.",
    )
    parser.add_argument(
        "--max-ai-items",
        type=int,
        default=int(os.getenv("CHEM_NEWS_MAX_AI_ITEMS", str(DEFAULT_MAX_AI_ITEMS))),
        help="Maximum records sent to the LLM provider for Chinese title/comment generation.",
    )
    parser.add_argument(
        "--model",
        default="",
        help=(
            "Override the LLM model for this run. Defaults to OPENAI_MODEL/"
            f"{DEFAULT_OPENAI_MODEL} for openai, or DEEPSEEK_MODEL/"
            f"{DEFAULT_DEEPSEEK_MODEL} for deepseek."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=os.getenv("CHEM_NEWS_OUTPUT_DIR", DEFAULT_OUTPUT_DIR),
        help=f"Output directory. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--report-date",
        default=os.getenv("CHEM_NEWS_REPORT_DATE", ""),
        help="Report date in YYYY-MM-DD format. Defaults to today's local date.",
    )
    parser.add_argument(
        "--no-openai",
        action="store_true",
        help="Skip model API calls and create the DOCX with deterministic fallback comments.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    return parser


def ensure_runtime_dependencies() -> None:
    if not MISSING_DEPENDENCIES:
        return
    missing = ", ".join(sorted(set(MISSING_DEPENDENCIES)))
    raise SystemExit(
        "Missing Python dependencies: "
        f"{missing}. Run `pip install -r requirements.txt` in this project environment."
    )


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_report_date(value: str) -> date:
    if not value:
        return datetime.now().astimezone().date()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit(f"--report-date must use YYYY-MM-DD format: {value}") from exc


def stable_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def ensure_item_ids(items: list[NewsItem]) -> None:
    used: set[str] = set()
    for index, item in enumerate(items, start=1):
        if item.item_id:
            continue
        base = f"N{index:03d}"
        if base not in used:
            item.item_id = base
        else:
            item.item_id = f"N{stable_hash(item.title)}"
        used.add(item.item_id)


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    configure_logging(args.verbose)
    ensure_runtime_dependencies()

    if args.days < 1 or args.days > 14:
        raise SystemExit("--days should be between 1 and 14.")
    if args.max_items < 1:
        raise SystemExit("--max-items must be positive.")

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=args.days)
    report_date = parse_report_date(args.report_date)
    output_dir = resolve_output_dir(args.output_dir)

    from network_check import run_network_checks

    diagnostics = run_network_checks(logger=LOGGER)
    if not diagnostics.network_ok:
        LOGGER.warning("Network is unavailable or degraded: %s", " | ".join(diagnostics.summary_lines()))

    LOGGER.info("Collecting chemistry items from %s to %s", since.isoformat(), now.isoformat())
    collected, source_statuses = collect_items(args, since, now)
    prepared = prepare_items(collected, args.max_items, now)
    ensure_item_ids(prepared)
    LOGGER.info("Prepared %d deduplicated items", len(prepared))

    if not prepared:
        reason = "抓取和过滤后没有可写入日报的资讯。"
        if all_sources_failed(source_statuses):
            reason = "全部来源抓取失败，未获得任何资讯。"
        failure_report = create_failure_report(
            report_date=report_date,
            output_dir=output_dir,
            diagnostics=diagnostics,
            source_statuses=source_statuses,
            reason=reason,
            collected_count=len(collected),
            prepared_count=len(prepared),
        )
        LOGGER.error("No reportable items; saved failure report to %s", failure_report)
        send_report_email(failure_report, report_date, is_failure=True)
        print(failure_report)
        return 2 if all_sources_failed(source_statuses) else 1

    if args.no_openai:
        apply_fallback_summaries(prepared)
        report_payload = fallback_report_payload(prepared)
    else:
        report_payload = generate_ai_summaries(prepared, args.model, args.max_ai_items)

    output_path = create_document(
        prepared,
        report_payload,
        report_date,
        output_dir,
        diagnostics=diagnostics,
        source_statuses=source_statuses,
    )
    LOGGER.info("Saved report to %s", output_path)
    send_report_email(output_path, report_date)
    print(output_path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130)
