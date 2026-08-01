"""Immutable, policy-first definitions for personalised research sources.

The catalogue intentionally contains both sources with a registered collector
and sources that are visible to operators but require an authenticated index,
manual review, or a future adapter.  ``collectable`` means that the source has
a public, policy-approved acquisition route; it does not register a second
collection pipeline.  ``main.collect_items`` remains the sole orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Collection


TRUSTED_SOURCE_LAYERS = (
    "official_data_policy",
    "academic_research",
    "institutional_research",
    "industry_engineering",
    "community_signal",
)

ALL_PROFILE_KEYS = (
    "chemistry",
    "organic_chemistry",
    "biology",
    "statistics",
    "business_management",
    "philosophy",
    "economics",
    "law",
    "education",
    "literature",
    "history",
    "natural_sciences",
    "engineering",
    "agriculture",
    "medicine",
    "management",
    "arts",
    "interdisciplinary_studies",
    "military_science",
    "computer_science",
)

ARXIV_PROFILE_KEYS = (
    "chemistry", "organic_chemistry", "biology", "statistics", "business_management",
    "economics", "natural_sciences", "engineering", "agriculture", "medicine",
    "interdisciplinary_studies", "computer_science",
)
PUBMED_PROFILE_KEYS = (
    "chemistry", "organic_chemistry", "biology", "statistics", "natural_sciences",
    "agriculture", "medicine",
)


@dataclass(frozen=True)
class SourceDefinition:
    """A stable source contract shown in profile selection and report metrics."""

    id: str
    chinese_name: str
    layer: str
    profile_scope: tuple[str, ...]
    topic_scope: tuple[str, ...]
    acquisition_method: str
    key_requirement: str
    update_cadence: str
    credibility: int
    access_label: str
    access_notice: str
    collectable: bool
    default_enabled: bool
    fallback: str

    @property
    def profile_keys(self) -> tuple[str, ...]:
        """Compatibility-friendly explicit name for the applicable profiles."""

        return self.profile_scope

    @property
    def topics(self) -> tuple[str, ...]:
        """Return the source's declared subject scope."""

        return self.topic_scope

    @property
    def cadence(self) -> str:
        """Short alias used by compact dashboard renderers."""

        return self.update_cadence


def _source(
    id: str,
    chinese_name: str,
    layer: str,
    profile_scope: tuple[str, ...],
    topic_scope: tuple[str, ...],
    acquisition_method: str,
    key_requirement: str,
    update_cadence: str,
    credibility: int,
    access_label: str,
    access_notice: str,
    collectable: bool,
    default_enabled: bool,
    fallback: str,
) -> SourceDefinition:
    if layer not in TRUSTED_SOURCE_LAYERS:
        raise ValueError(f"unknown trusted source layer: {layer}")
    if not 1 <= credibility <= 5:
        raise ValueError("credibility must be between 1 and 5")
    if default_enabled and not collectable:
        raise ValueError("a non-collectable source cannot be enabled by default")
    return SourceDefinition(
        id=id,
        chinese_name=chinese_name,
        layer=layer,
        profile_scope=profile_scope,
        topic_scope=topic_scope,
        acquisition_method=acquisition_method,
        key_requirement=key_requirement,
        update_cadence=update_cadence,
        credibility=credibility,
        access_label=access_label,
        access_notice=access_notice,
        collectable=collectable,
        default_enabled=default_enabled,
        fallback=fallback,
    )


# ``existing_collector`` entries are the legacy, executable source IDs.  The
# public API/RSS entries below remain catalogue data until their adapters are
# registered in main.collect_items by a later task.
SOURCE_DEFINITIONS = (
    _source(
        "arxiv", "arXiv 预印本", "academic_research", ARXIV_PROFILE_KEYS,
        ("跨学科预印本",), "existing_collector", "无需 API Key", "持续更新", 3,
        "公开可用", "预印本未经同行评议；应保留预印本标识。", True, True, "OpenAlex 或 Crossref 元数据",
    ),
    _source(
        "pubmed", "PubMed", "academic_research", PUBMED_PROFILE_KEYS,
        ("医学", "生命科学", "生物统计"), "existing_collector", "建议配置 NCBI_EMAIL", "每日更新", 4,
        "公开可用", "公开书目与摘要；全文版权以原出版商规则为准。", True, True, "Europe PMC 或 Crossref 元数据",
    ),
    _source(
        "crossref", "Crossref 期刊元数据", "academic_research", ALL_PROFILE_KEYS,
        ("期刊论文", "DOI 元数据"), "existing_collector", "建议配置 CROSSREF_MAILTO", "持续更新", 4,
        "公开可用", "仅采集公开元数据；摘要和全文可用性由出版商决定。", True, True, "期刊 RSS 或 OpenAlex",
    ),
    _source(
        "rss", "期刊与学会公开 RSS", "academic_research",
        ("chemistry", "organic_chemistry", "biology", "statistics", "business_management", "computer_science"),
        ("期刊动态", "学会资讯"), "existing_collector", "无需 API Key", "来源更新时", 3,
        "公开可用", "仅使用编辑维护的公开 RSS，需遵守来源站点条款。", True, True, "Crossref 元数据",
    ),
    _source(
        "openalex", "OpenAlex 学术索引", "academic_research", ALL_PROFILE_KEYS,
        ("跨学科论文发现",), "existing_collector", "需要 OPENALEX_API_KEY", "每日更新", 3,
        "需要 API Key", "学术索引不等同于同行评议；全文版权以原文来源为准。", True, False, "Crossref 或 arXiv",
    ),
    _source(
        "ccf_conferences", "CCF 推荐会议（DBLP 新收录）", "academic_research", ("computer_science",),
        ("计算机科学会议",), "existing_collector", "无需 API Key", "DBLP 收录时", 4,
        "公开可用", "目录仅用于会议范围筛选，不保证单篇论文质量。", True, True, "arXiv、OpenAlex 或 Crossref",
    ),
    _source(
        "official_rss", "官方机构公开 RSS", "official_data_policy", ("computer_science",),
        ("官方公告", "政策", "产品更新"), "existing_collector", "无需 API Key", "来源更新时", 4,
        "公开可用", "仅使用机构或项目所有者维护的公开订阅源。", True, True, "机构官网人工核验",
    ),
    _source(
        "github_releases", "GitHub 白名单项目发布", "industry_engineering", ("computer_science",),
        ("开源工程", "软件发布"), "existing_collector", "可选 GITHUB_SOURCE_TOKEN", "发布时", 3,
        "公开可用", "仅限白名单项目的发布说明，不作为学术证据。", True, False, "项目官网或官方 RSS",
    ),
    _source(
        "hackernews", "Hacker News 公开讨论", "community_signal", ("computer_science",),
        ("技术社区线索",), "existing_collector", "无需 API Key", "持续更新", 1,
        "公开可用", "仅作可追溯的社区线索，不作为证据或默认今日重点。", True, False, "官方发布或原始研究来源",
    ),
    _source(
        "europe_pmc", "Europe PMC", "academic_research", ("biology", "medicine"),
        ("生物医学论文", "开放获取全文"), "public_api", "无需 API Key", "每日更新", 4,
        "公开可用", "开放元数据与全文可用性以 Europe PMC 和原出版商标注为准。", True, True, "PubMed 或 Crossref 元数据",
    ),
    _source(
        "biorxiv", "bioRxiv 预印本", "academic_research", ("biology", "medicine", "agriculture", "natural_sciences"),
        ("生命科学预印本",), "public_rss", "无需 API Key", "每日更新", 3,
        "公开可用", "预印本未经同行评议；应保留服务器与版本信息。", True, True, "PubMed、Europe PMC 或 arXiv",
    ),
    _source(
        "medrxiv", "medRxiv 预印本", "academic_research", ("biology", "medicine"),
        ("医学预印本",), "public_rss", "无需 API Key", "每日更新", 3,
        "公开可用", "预印本未经同行评议；应保留服务器与版本信息。", True, True, "PubMed、Europe PMC 或 ClinicalTrials.gov",
    ),
    _source(
        "clinical_trials", "ClinicalTrials.gov", "official_data_policy", ("medicine",),
        ("临床试验登记",), "public_api", "无需 API Key", "持续更新", 5,
        "公开可用", "试验登记不等同于疗效结论，结果需回到原始记录核验。", True, True, "WHO ICTRP 或论文数据库",
    ),
    _source(
        "psycinfo_metadata", "APA PsycInfo 元数据", "academic_research", ("medicine", "education"),
        ("心理学", "行为科学"), "licensed_index", "机构订阅或个人授权", "数据库更新时", 4,
        "需要授权", "受订阅许可限制；未授权时不抓取、不默认选择。", False, False, "PubMed、OpenAlex 或 Crossref",
    ),
    _source(
        "nber_working_papers", "NBER Working Papers", "institutional_research", ("economics", "management", "business_management"),
        ("经济学", "管理研究工作论文"), "public_rss", "无需 API Key", "工作论文发布时", 3,
        "公开可用", "工作论文通常未经同行评议；全文访问以 NBER 条款为准。", True, True, "SSRN、期刊论文或机构报告",
    ),
    _source(
        "mit_csail_news", "MIT CSAIL 研究动态", "institutional_research", ("computer_science",),
        ("人工智能", "计算机系统", "人机交互"), "public_rss", "无需 API Key", "机构发布时", 3,
        "公开可用", "机构新闻用于发现研究线索，结论应回到论文或技术报告核验。", True, False, "arXiv、OpenAlex 或论文主页",
    ),
    _source(
        "iso_standards_metadata", "ISO 标准目录", "industry_engineering", ("engineering", "computer_science", "management"),
        ("工程标准", "管理标准"), "licensed_catalogue", "可能需要购买或机构授权", "标准发布时", 5,
        "需要授权", "标准正文受版权和购买许可限制；只可显示可公开核验的目录信息。", False, False, "官方主管部门公开标准通知",
    ),
)

# These are independently addressable records, not aliases for a generic
# "web" source.  They remain catalogue-only until a later task registers a
# vetted adapter in main.collect_items.
SOURCE_DEFINITIONS += (
    _source(
        "zbmath", "zbMATH Open", "academic_research", ("statistics", "natural_sciences"),
        ("数学", "统计学"), "public_api", "无需 API Key", "持续更新", 4,
        "公开可用", "公开书目数据；全文访问以出版商许可为准。", True, True, "Project Euclid 或 Crossref",
    ),
    _source(
        "project_euclid", "Project Euclid", "academic_research", ("statistics", "natural_sciences"),
        ("数学", "统计学", "概率论"), "public_metadata", "无需 API Key", "期刊更新时", 4,
        "公开元数据；部分全文需授权", "可核验题录公开，部分全文受期刊订阅或版权限制。", True, False, "zbMATH Open 或 Crossref",
    ),
    _source(
        "ims", "Institute of Mathematical Statistics", "institutional_research", ("statistics",),
        ("统计学", "概率论"), "public_rss", "无需 API Key", "机构发布时", 4,
        "公开可用", "机构资讯用于发现学术活动，研究结论应回到论文核验。", True, False, "Project Euclid 或 ASA",
    ),
    _source(
        "asa", "American Statistical Association", "institutional_research", ("statistics",),
        ("统计方法", "官方学会资讯"), "public_rss", "无需 API Key", "机构发布时", 4,
        "公开可用", "协会资讯和政策材料不等同于同行评议论文。", True, False, "IMS 或期刊元数据",
    ),
    _source(
        "nasa_ads", "NASA ADS", "academic_research", ("natural_sciences", "engineering", "interdisciplinary_studies"),
        ("天文学", "物理学", "空间科学"), "public_api", "需要 NASA ADS API Token", "持续更新", 4,
        "需要 API Key", "书目数据可公开查询；全文和预印本链接遵循原始来源许可。", True, False, "arXiv 或 Crossref",
    ),
    _source(
        "cern", "CERN 公开研究与数据", "institutional_research", ("natural_sciences", "engineering"),
        ("高能物理", "加速器", "开放数据"), "public_rss", "无需 API Key", "机构发布时", 4,
        "公开可用", "公开资料按 CERN 开放许可和数据使用说明处理。", True, False, "arXiv 或 NASA ADS",
    ),
    _source(
        "esa", "欧洲空间局（ESA）", "official_data_policy", ("natural_sciences", "engineering"),
        ("空间科学", "地球观测"), "public_rss", "无需 API Key", "机构发布时", 5,
        "公开可用", "任务新闻与数据使用须遵守 ESA 的发布和许可说明。", True, False, "NASA 或 Copernicus",
    ),
    _source(
        "nasa", "美国国家航空航天局（NASA）", "official_data_policy", ("natural_sciences", "engineering"),
        ("空间科学", "地球科学", "航空航天"), "public_rss", "无需 API Key", "机构发布时", 5,
        "公开可用", "官方公告和开放数据的再利用以 NASA 条款为准。", True, False, "ESA 或 Earthdata",
    ),
    _source(
        "aps", "American Physical Society", "academic_research", ("natural_sciences",),
        ("物理学"), "public_rss", "无需 API Key", "期刊更新时", 4,
        "公开元数据；部分全文需授权", "期刊题录可公开核验，全文版权和订阅由 APS 管理。", True, False, "arXiv 或 AIP",
    ),
    _source(
        "aip", "AIP Publishing", "academic_research", ("natural_sciences", "engineering"),
        ("物理学", "应用物理"), "public_rss", "无需 API Key", "期刊更新时", 4,
        "公开元数据；部分全文需授权", "期刊题录可公开核验，全文版权和订阅由 AIP 管理。", True, False, "APS 或 Crossref",
    ),
    _source(
        "acs", "American Chemical Society", "academic_research", ("chemistry", "organic_chemistry"),
        ("化学", "有机化学"), "public_rss", "无需 API Key", "期刊更新时", 5,
        "公开可用", "题录/RSS 可公开核验；全文遵守 ACS 版权和订阅规则。", True, True, "Crossref 或 RSC",
    ),
    _source(
        "rsc", "Royal Society of Chemistry", "academic_research", ("chemistry", "organic_chemistry"),
        ("化学", "材料化学"), "public_rss", "无需 API Key", "期刊更新时", 5,
        "公开可用", "题录/RSS 可公开核验；全文遵守 RSC 版权和订阅规则。", True, True, "Crossref 或 ACS",
    ),
    _source(
        "nature_chemistry", "Nature Chemistry", "academic_research", ("chemistry", "organic_chemistry"),
        ("化学"), "public_rss", "无需 API Key", "期刊更新时", 5,
        "公开可用", "文章元数据公开，全文可用性依 Nature Portfolio 版权和订阅规则而定。", True, True, "Crossref、ACS 或 RSC",
    ),
    _source(
        "chemistry_world", "Chemistry World", "industry_engineering", ("chemistry", "organic_chemistry"),
        ("化学新闻", "行业动态"), "public_rss", "无需 API Key", "每日更新", 3,
        "公开可用", "行业新闻用于背景和线索，不替代原始论文或官方数据。", True, False, "ACS、RSC 或原始研究",
    ),
    _source(
        "energy_agencies", "国际与国家能源机构", "official_data_policy", ("chemistry", "organic_chemistry", "engineering", "natural_sciences", "management"),
        ("能源技术", "能源政策", "能源统计"), "public_rss", "无需 API Key", "机构发布时", 5,
        "公开可用", "仅限可核验的机构公告、数据和报告，须保留原机构出处。", True, False, "IEA、国家能源主管部门或原始论文",
    ),
    _source(
        "who", "世界卫生组织（WHO）", "official_data_policy", ("biology", "medicine", "agriculture", "economics", "law", "education", "management", "business_management", "interdisciplinary_studies"),
        ("公共卫生", "全球健康"), "public_rss", "无需 API Key", "机构发布时", 5,
        "公开可用", "官方指南和统计需注明版本、发布日期及适用范围。", True, True, "CDC、NIH 或原始研究",
    ),
    _source(
        "cdc", "美国疾病控制与预防中心（CDC）", "official_data_policy", ("biology", "medicine"),
        ("传染病", "公共卫生"), "public_rss", "无需 API Key", "机构发布时", 5,
        "公开可用", "官方监测和指南需保留发布时间与适用人群边界。", True, True, "WHO、NIH 或原始研究",
    ),
    _source(
        "nih", "美国国立卫生研究院（NIH）", "official_data_policy", ("biology", "medicine"),
        ("生物医学", "资助研究"), "public_rss", "无需 API Key", "机构发布时", 5,
        "公开可用", "机构新闻和资助信息不应被表述为独立疗效证据。", True, True, "PubMed、Europe PMC 或 CDC",
    ),
    _source(
        "cochrane", "Cochrane Library", "academic_research", ("medicine",),
        ("循证医学", "系统综述"), "licensed_index", "机构订阅或个人授权", "综述更新时", 5,
        "需要授权", "部分内容和全文受订阅许可限制；未授权时不抓取。", False, False, "PubMed、Europe PMC 或公开指南",
    ),
    _source(
        "openreview", "OpenReview", "academic_research", ("computer_science", "statistics", "interdisciplinary_studies"),
        ("计算机科学会议", "机器学习"), "public_api", "无需 API Key", "会议周期", 3,
        "公开可用", "公开评审和预印本不等同于正式同行评议结论。", True, True, "DBLP、arXiv 或会议官网",
    ),
    _source(
        "dblp", "DBLP", "academic_research", ("computer_science",),
        ("计算机科学书目", "会议论文"), "public_api", "无需 API Key", "持续更新", 4,
        "公开可用", "书目索引用于发现和核验发表信息，不保证论文质量。", True, True, "OpenReview、ACM 或 IEEE",
    ),
    _source(
        "semantic_scholar", "Semantic Scholar", "academic_research", ("computer_science", "interdisciplinary_studies", "natural_sciences"),
        ("跨学科论文发现", "引文网络"), "public_api", "需要 API Key", "持续更新", 3,
        "需要 API Key", "索引和摘要不等同于同行评议，原文和引用需回源核验。", True, False, "OpenAlex、Crossref 或 DBLP",
    ),
    _source(
        "papers_with_code", "Papers with Code", "industry_engineering", ("computer_science",),
        ("机器学习", "代码与基准"), "public_api", "无需 API Key", "项目更新时", 2,
        "公开可用", "论文—代码关联和排行榜为社区维护信息，不替代论文证据。", True, False, "原始论文、GitHub 或 OpenReview",
    ),
    _source(
        "acm", "ACM Digital Library", "academic_research", ("computer_science", "engineering"),
        ("计算机科学期刊", "会议论文"), "licensed_index", "机构订阅或个人授权", "期刊更新时", 5,
        "需要授权", "书目可核验，许多全文受 ACM 版权和订阅限制。", False, False, "DBLP、OpenReview 或 Crossref",
    ),
    _source(
        "ieee", "IEEE Xplore", "academic_research", ("computer_science", "engineering"),
        ("计算机科学", "工程"), "licensed_index", "机构订阅或个人授权", "期刊更新时", 5,
        "需要授权", "书目可核验，许多全文受 IEEE 版权和订阅限制。", False, False, "DBLP、arXiv 或 Crossref",
    ),
    _source(
        "usenix", "USENIX", "academic_research", ("computer_science",),
        ("系统", "安全", "网络"), "public_rss", "无需 API Key", "会议发布时", 4,
        "公开可用", "公开会议论文和技术资料应保留会议与版本信息。", True, True, "DBLP、OpenReview 或 ACM",
    ),
    _source(
        "3gpp", "3GPP", "industry_engineering", ("engineering", "computer_science"),
        ("通信标准", "移动通信"), "public_catalogue", "无需 API Key", "标准发布时", 5,
        "公开可用", "标准状态和版本以 3GPP 官方发布为准。", True, False, "IETF、ITU 或 ETSI",
    ),
    _source(
        "ietf", "IETF", "industry_engineering", ("engineering", "computer_science"),
        ("互联网标准", "网络协议"), "public_rss", "无需 API Key", "持续更新", 5,
        "公开可用", "Internet-Draft 不是 RFC；须显示文档状态和版本。", True, False, "RFC、3GPP 或 ITU",
    ),
    _source(
        "itu", "国际电信联盟（ITU）", "official_data_policy", ("engineering", "computer_science", "management"),
        ("通信政策", "电信标准"), "public_rss", "无需 API Key", "机构发布时", 5,
        "公开可用", "部分标准和报告可能受版权或购买限制，需按官方许可使用。", True, False, "ETSI、3GPP 或 IETF",
    ),
    _source(
        "etsi", "欧洲电信标准协会（ETSI）", "industry_engineering", ("engineering", "computer_science"),
        ("通信标准", "网络安全"), "public_catalogue", "无需 API Key", "标准发布时", 5,
        "公开可用", "标准版本和使用限制以 ETSI 官方目录为准。", True, False, "3GPP、IETF 或 ITU",
    ),
    _source(
        "asme", "美国机械工程师学会（ASME）", "industry_engineering", ("engineering",),
        ("机械工程", "工程标准"), "licensed_catalogue", "机构订阅或个人授权", "标准发布时", 5,
        "需要授权", "标准正文通常受版权和购买许可限制。", False, False, "FAA 或公开监管文件",
    ),
    _source(
        "sae", "SAE International", "industry_engineering", ("engineering",),
        ("汽车工程", "航空工程"), "licensed_catalogue", "机构订阅或个人授权", "标准发布时", 5,
        "需要授权", "标准正文通常受版权和购买许可限制。", False, False, "FAA 或公开监管文件",
    ),
    _source(
        "faa", "美国联邦航空局（FAA）", "official_data_policy", ("engineering",),
        ("航空安全", "航空监管"), "public_rss", "无需 API Key", "机构发布时", 5,
        "公开可用", "法规和安全公告需要保留适用航空器、地区和生效日期。", True, False, "NASA、SAE 或 ASME",
    ),
    _source(
        "ipcc", "政府间气候变化专门委员会（IPCC）", "official_data_policy", ("natural_sciences", "engineering", "agriculture", "interdisciplinary_studies", "management"),
        ("气候变化", "评估报告"), "public_rss", "无需 API Key", "评估周期", 5,
        "公开可用", "评估报告须注明版本、工作组和证据等级，不能外推到未覆盖情境。", True, True, "WMO、UNEP 或原始研究",
    ),
    _source(
        "unep", "联合国环境规划署（UNEP）", "official_data_policy", ("natural_sciences", "engineering", "agriculture", "interdisciplinary_studies", "management"),
        ("环境", "可持续发展"), "public_rss", "无需 API Key", "机构发布时", 5,
        "公开可用", "政策报告和环境数据需保留机构、版本和地理范围。", True, True, "IPCC、USGS 或国家环境机构",
    ),
    _source(
        "earthdata", "NASA Earthdata", "official_data_policy", ("natural_sciences", "engineering", "agriculture"),
        ("地球观测", "遥感数据"), "authenticated_api", "需要免费 Earthdata Login", "持续更新", 5,
        "需要授权", "数据访问需账户授权，并须遵守数据产品的引用和使用条款。", False, False, "Copernicus、NOAA 或 USGS",
    ),
    _source(
        "usgs", "美国地质调查局（USGS）", "official_data_policy", ("natural_sciences", "engineering", "agriculture"),
        ("地球科学", "地质", "水文"), "public_api", "无需 API Key", "持续更新", 5,
        "公开可用", "公开数据应保留产品版本、空间尺度和测量限制。", True, True, "Earthdata、NOAA 或国家机构",
    ),
    _source(
        "fao", "联合国粮食及农业组织（FAO）", "official_data_policy", ("agriculture", "economics", "management", "interdisciplinary_studies"),
        ("农业", "粮食安全"), "public_api", "无需 API Key", "持续更新", 5,
        "公开可用", "指标使用需注明地区、时间覆盖和统计口径。", True, True, "USDA、CGIAR 或 World Bank",
    ),
    _source(
        "usda", "美国农业部（USDA）", "official_data_policy", ("agriculture", "economics", "management"),
        ("农业", "农产品", "食品"), "public_api", "无需 API Key", "持续更新", 5,
        "公开可用", "统计与监管信息应保留数据发布日期和适用市场范围。", True, True, "FAO、CGIAR 或国家农业机构",
    ),
    _source(
        "cgiar", "CGIAR", "institutional_research", ("agriculture", "natural_sciences", "interdisciplinary_studies"),
        ("国际农业研究", "粮食系统"), "public_rss", "无需 API Key", "机构发布时", 4,
        "公开可用", "机构研究报告应回到原始数据、论文或项目方法说明核验。", True, True, "FAO、USDA 或同行评议研究",
    ),
    _source(
        "fred", "FRED 经济数据", "official_data_policy", ("economics", "management", "business_management"),
        ("宏观经济", "金融", "劳动力"), "public_api", "需要 FRED API Key", "持续更新", 5,
        "需要 API Key", "时间序列必须保留系列 ID、季调状态、单位和修订版本。", True, False, "IMF、World Bank 或 OECD",
    ),
    _source(
        "imf", "国际货币基金组织（IMF）", "official_data_policy", ("economics", "management", "business_management"),
        ("国际经济", "金融稳定"), "public_api", "无需 API Key", "持续更新", 5,
        "公开可用", "数据和展望需保留版本、国家覆盖和统计口径。", True, True, "World Bank、OECD 或 BIS",
    ),
    _source(
        "world_bank", "世界银行（World Bank）", "official_data_policy", ("economics", "law", "management", "business_management", "agriculture", "interdisciplinary_studies"),
        ("发展经济", "全球指标"), "public_api", "无需 API Key", "持续更新", 5,
        "公开可用", "发展指标应保留国家、年份、指标定义和修订信息。", True, True, "IMF、OECD 或 FAO",
    ),
    _source(
        "oecd", "经济合作与发展组织（OECD）", "official_data_policy", ("economics", "law", "management", "business_management", "education"),
        ("经济政策", "教育", "治理"), "public_api", "可能需要 API Key", "持续更新", 5,
        "需要 API Key", "指标与政策报告需保留数据库版本、成员范围和定义。", True, False, "IMF、World Bank 或 FRED",
    ),
    _source(
        "bis", "国际清算银行（BIS）", "official_data_policy", ("economics", "management", "business_management"),
        ("货币金融", "银行监管"), "public_api", "无需 API Key", "持续更新", 5,
        "公开可用", "金融统计需保留表号、币种、频率和修订状态。", True, True, "IMF、FRED 或 OECD",
    ),
    _source(
        "cepr", "CEPR Discussion Papers", "institutional_research", ("economics", "management", "business_management"),
        ("经济学工作论文", "政策研究"), "public_rss", "无需 API Key", "工作论文发布时", 3,
        "公开可用", "工作论文未经同行评议时必须保留该证据边界。", True, False, "RePEc、NBER 或期刊论文",
    ),
    _source(
        "repec", "RePEc", "academic_research", ("economics", "management", "business_management"),
        ("经济学书目", "工作论文"), "public_metadata", "无需 API Key", "持续更新", 3,
        "公开可用", "书目和工作论文索引不等同于同行评议结论。", True, True, "CEPR、NBER 或 Crossref",
    ),
    _source(
        "ssrn", "SSRN", "institutional_research", ("economics", "law", "management", "business_management"),
        ("工作论文", "法律与管理研究"), "public_metadata", "无需 API Key", "持续更新", 2,
        "公开可用", "预印本和工作论文需明确未经同行评议或版本状态。", True, False, "RePEc、CEPR 或期刊论文",
    ),
    _source(
        "exchanges", "主要证券交易所公告", "industry_engineering", ("economics", "management", "business_management"),
        ("公司披露", "市场规则"), "public_rss", "无需 API Key", "交易日更新", 4,
        "公开可用", "交易所公告是原始披露，不构成投资建议或因果研究证据。", True, False, "监管机构披露或公司原文",
    ),
    _source(
        "government_legislation", "政府法律法规公开库", "official_data_policy", ("law", "management", "military_science", "interdisciplinary_studies"),
        ("法律", "行政法规", "政策"), "public_api", "无需 API Key", "法律更新时", 5,
        "公开可用", "必须保留司法辖区、生效状态、修订历史和官方文本链接。", True, True, "司法机关或联合国资料库",
    ),
    _source(
        "judicial_opinions", "司法裁判公开库", "official_data_policy", ("law",),
        ("判例", "司法解释"), "public_catalogue", "无需 API Key", "裁判发布时", 5,
        "公开可用", "裁判信息需核验法院层级、程序状态、匿名化和辖区效力。", True, True, "法律法规公开库或官方法院网站",
    ),
    _source(
        "united_nations", "联合国（UN）资料库", "official_data_policy", ("law", "education", "history", "interdisciplinary_studies", "military_science"),
        ("国际法", "国际组织", "发展议程"), "public_rss", "无需 API Key", "机构发布时", 5,
        "公开可用", "文件需保留机构、文号、通过日期和适用范围。", True, True, "WTO、UNESCO 或政府公开库",
    ),
    _source(
        "wto", "世界贸易组织（WTO）", "official_data_policy", ("economics", "law", "management", "business_management"),
        ("国际贸易", "贸易规则"), "public_rss", "无需 API Key", "机构发布时", 5,
        "公开可用", "规则与争端文件需区分谈判文本、已生效规则和个案状态。", True, True, "UN、政府贸易主管部门或 World Bank",
    ),
    _source(
        "think_tanks", "可核验智库公开报告", "institutional_research", ("law", "economics", "management", "interdisciplinary_studies", "military_science"),
        ("公共政策", "战略", "治理"), "curated_rss", "无需 API Key", "机构发布时", 2,
        "公开可用", "必须标注机构、资助/立场和方法；不可与官方或同行评议证据混同。", True, False, "官方数据、法规或原始研究",
    ),
    _source(
        "eric", "ERIC", "academic_research", ("education",),
        ("教育研究", "教育政策"), "public_api", "无需 API Key", "持续更新", 4,
        "公开可用", "书目与摘要公开；全文可得性和版权依单条记录标注。", True, True, "DOAJ、UNESCO 或 Crossref",
    ),
    _source(
        "unesco", "联合国教科文组织（UNESCO）", "official_data_policy", ("education", "history", "arts", "interdisciplinary_studies"),
        ("教育", "文化", "世界遗产"), "public_rss", "无需 API Key", "机构发布时", 5,
        "公开可用", "官方统计和政策文件应保留版本、地理范围和指标定义。", True, True, "UNICEF、ERIC 或联合国资料库",
    ),
    _source(
        "unicef", "联合国儿童基金会（UNICEF）", "official_data_policy", ("education", "medicine", "interdisciplinary_studies"),
        ("儿童发展", "教育", "公共卫生"), "public_rss", "无需 API Key", "机构发布时", 5,
        "公开可用", "儿童相关数据需注明国家、年龄范围和调查方法。", True, True, "UNESCO、WHO 或 World Bank",
    ),
    _source(
        "wvs", "World Values Survey", "institutional_research", ("education", "economics", "management", "interdisciplinary_studies"),
        ("社会调查", "价值观", "比较研究"), "public_data", "无需 API Key", "波次发布时", 4,
        "公开可用", "必须保留调查波次、样本、国家覆盖和问卷版本。", True, False, "OECD、World Bank 或原始论文",
    ),
    _source(
        "doaj", "Directory of Open Access Journals", "academic_research", ("philosophy", "education", "literature", "history", "arts", "interdisciplinary_studies"),
        ("开放获取期刊", "人文社会科学"), "public_api", "无需 API Key", "持续更新", 3,
        "公开可用", "开放获取目录不等同于单篇研究质量或同行评议强度。", True, True, "Crossref、JSTOR 或图书馆目录",
    ),
    _source(
        "jstor_metadata", "JSTOR 公开元数据", "academic_research", ("philosophy", "literature", "history", "arts"),
        ("人文社会科学期刊", "档案"), "public_metadata", "无需 API Key", "期刊更新时", 4,
        "公开可用", "题录元数据可公开收集和选择；全文常受订阅、版权或机构授权限制。", True, True, "DOAJ、图书馆目录或 Open Library",
    ),
    _source(
        "open_library", "Open Library", "institutional_research", ("philosophy", "literature", "history", "arts"),
        ("图书目录", "开放图书"), "public_api", "无需 API Key", "持续更新", 2,
        "公开可用", "书目与借阅可用性应与版权状态、版本和馆藏来源分开说明。", True, False, "国家图书馆或 DPLA",
    ),
    _source(
        "dpla", "Digital Public Library of America", "institutional_research", ("philosophy", "literature", "history", "arts"),
        ("数字馆藏", "文化资料"), "public_api", "可能需要 API Key", "持续更新", 3,
        "需要 API Key", "数字化对象的版权和再利用条件以各馆藏机构标注为准。", True, False, "Open Library、国家图书馆或博物馆",
    ),
    _source(
        "national_libraries", "国家与公共图书馆目录", "institutional_research", ("literature", "history", "arts"),
        ("图书馆目录", "档案"), "public_catalogue", "无需 API Key", "馆藏更新时", 4,
        "公开可用", "馆藏元数据与数字对象权限必须按图书馆记录分别注明。", True, False, "DPLA 或 Open Library",
    ),
    _source(
        "museums_heritage", "博物馆与文化遗产机构", "institutional_research", ("history", "arts", "literature"),
        ("博物馆", "文化遗产", "档案"), "curated_rss", "无需 API Key", "机构发布时", 4,
        "公开可用", "展览新闻不能替代馆藏档案或学术研究；图像再利用需遵守机构许可。", True, False, "国家图书馆、UNESCO 或 DPLA",
    ),
    _source(
        "noaa", "美国国家海洋和大气管理局（NOAA）", "official_data_policy", ("natural_sciences", "engineering", "agriculture", "interdisciplinary_studies"),
        ("气候", "海洋", "天气"), "public_api", "无需 API Key", "持续更新", 5,
        "公开可用", "观测产品需注明数据集版本、空间时间分辨率和质量控制状态。", True, True, "WMO、Copernicus 或国家机构",
    ),
    _source(
        "wmo", "世界气象组织（WMO）", "official_data_policy", ("natural_sciences", "engineering", "agriculture", "interdisciplinary_studies"),
        ("气象", "气候服务"), "public_rss", "无需 API Key", "机构发布时", 5,
        "公开可用", "气象报告应保留发布机构、观测期和预测/观测区分。", True, True, "NOAA、IPCC 或 Copernicus",
    ),
    _source(
        "copernicus", "Copernicus", "official_data_policy", ("natural_sciences", "engineering", "agriculture"),
        ("地球观测", "遥感"), "public_api", "可能需要免费账户", "持续更新", 5,
        "公开可用", "公开服务可用；部分下载可能需要免费账户，数据产品须遵守许可和引用要求。", True, True, "Earthdata、NOAA 或 USGS",
    ),
    _source(
        "national_science_agencies", "国家科学与环境机构", "official_data_policy", ("natural_sciences", "engineering", "agriculture", "medicine"),
        ("国家数据", "科研资助", "环境监测"), "curated_rss", "无需 API Key", "机构发布时", 5,
        "公开可用", "仅接入明确身份的官方机构，需保留原机构、地区和版本信息。", True, False, "NOAA、USGS、NIH 或对应国际机构",
    ),
)

SOURCE_DEFINITIONS += (
    _source(
        "energy_standards", "能源标准与技术规范", "industry_engineering", ("chemistry", "organic_chemistry", "natural_sciences", "engineering", "management"),
        ("能源标准", "储能", "电力系统"), "public_catalogue", "可能需要购买或机构授权", "标准发布时", 5,
        "公开元数据；部分正文需授权", "目录和部分规范公开；标准正文应遵守版权、购买和引用要求。", True, False, "能源机构公告或公开监管文件",
    ),
    _source(
        "industrial_automation_associations", "工业自动化协会", "industry_engineering", ("engineering", "computer_science", "management"),
        ("工业自动化", "控制系统", "制造"), "public_rss", "无需 API Key", "机构发布时", 3,
        "公开可用", "协会资讯用于工程动态发现，技术结论应回到标准、数据或原始论文。", True, False, "工业标准或监管文件",
    ),
    _source(
        "transport_departments", "交通主管部门公开资料", "official_data_policy", ("engineering", "management", "business_management", "law"),
        ("交通运输", "基础设施", "安全监管"), "public_rss", "无需 API Key", "机构发布时", 5,
        "公开可用", "公告和统计应保留司法辖区、生效日期和适用运输方式。", True, False, "交通协会或法规公开库",
    ),
    _source(
        "transport_associations", "交通运输行业协会", "industry_engineering", ("engineering", "management", "business_management"),
        ("交通运输", "物流", "行业标准"), "public_rss", "无需 API Key", "机构发布时", 3,
        "公开可用", "协会报告不是监管结论，应与主管部门数据和原始研究区分。", True, False, "交通主管部门或官方统计",
    ),
    _source(
        "national_statistics", "国家统计机构", "official_data_policy", ("statistics", "economics", "law", "education", "agriculture", "medicine", "management", "business_management", "interdisciplinary_studies"),
        ("官方统计", "人口", "社会经济"), "public_api", "无需 API Key", "持续更新", 5,
        "公开可用", "统计指标必须保留机构、口径、时间覆盖和修订状态。", True, True, "国际统计机构或专题主管部门",
    ),
    _source(
        "international_statistics", "国际统计机构", "official_data_policy", ("statistics", "economics", "education", "management", "business_management", "interdisciplinary_studies"),
        ("国际统计", "比较数据"), "public_api", "无需 API Key", "持续更新", 5,
        "公开可用", "跨国比较须保留指标定义、国家覆盖、年份和修订版本。", True, True, "国家统计机构或 World Bank",
    ),
    _source(
        "central_banks", "中央银行公开资料", "official_data_policy", ("economics", "law", "management", "business_management"),
        ("货币政策", "金融稳定", "支付系统"), "public_rss", "无需 API Key", "机构发布时", 5,
        "公开可用", "政策声明必须区分发布时间、决议状态和适用辖区。", True, False, "BIS、IMF 或财政监管机构",
    ),
    _source(
        "fiscal_regulators", "财政与金融监管机构", "official_data_policy", ("economics", "law", "management", "business_management"),
        ("财政", "金融监管", "公司披露"), "public_rss", "无需 API Key", "机构发布时", 5,
        "公开可用", "规则和执法信息应保留辖区、生效日期与程序状态。", True, False, "中央银行、交易所或法律法规库",
    ),
)


def source_definitions_for_profile(profile_key: str) -> tuple[SourceDefinition, ...]:
    """Return the stable source records that apply to one recognised profile."""

    return tuple(source for source in SOURCE_DEFINITIONS if profile_key in source.profile_scope)


def collectable_source_ids() -> tuple[str, ...]:
    """Return all policy-approved public source IDs, in catalogue order."""

    return tuple(source.id for source in SOURCE_DEFINITIONS if source.collectable)


def default_source_ids_for_layers(profile_key: str, layers: Collection[str]) -> tuple[str, ...]:
    """Expand selected evidence layers to safe default source IDs.

    Community sources always need an explicit source-level opt-in, so selecting
    that layer alone never adds one to a new profile.
    """

    selected_layers = frozenset(layers)
    invalid_layers = selected_layers.difference(TRUSTED_SOURCE_LAYERS)
    if invalid_layers:
        raise ValueError(f"unknown trusted source layers: {', '.join(sorted(invalid_layers))}")
    return tuple(
        source.id
        for source in source_definitions_for_profile(profile_key)
        if source.layer in selected_layers
        and source.layer != "community_signal"
        and source.collectable
        and source.default_enabled
    )
