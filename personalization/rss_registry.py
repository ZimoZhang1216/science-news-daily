"""RSS feed URLs for every collectable public_rss source in the source catalogue.

Each value is a list of feed configs compatible with ``main.fetch_rss()``.
Add or update URLs here; the collector and dashboard consume them automatically.
"""

from __future__ import annotations

from typing import Any

RSS_FEED_REGISTRY: dict[str, list[dict[str, Any]]] = {
    # ── Chemistry ──
    "acs": [
        {
            "source": "ACS Publications (JACS)",
            "url": "https://feeds.feedburner.com/jacsat",
            "broad": False,
        },
        {
            "source": "ACS Publications (Chemical Reviews)",
            "url": "https://feeds.feedburner.com/chreay",
            "broad": False,
        },
        {
            "source": "ACS Publications (ACS Central Science)",
            "url": "https://feeds.feedburner.com/acscii",
            "broad": False,
        },
        {
            "source": "ACS Publications (ACS Catalysis)",
            "url": "https://feeds.feedburner.com/accacs",
            "broad": False,
        },
    ],
    "rsc": [
        {
            "source": "RSC (Chemical Science)",
            "url": "https://www.rsc.org/journals-books-databases/about-journals/chemical-science/feed/",
            "broad": False,
        },
        {
            "source": "RSC (Chemical Communications)",
            "url": "https://www.rsc.org/journals-books-databases/about-journals/chem-commun/feed/",
            "broad": False,
        },
        {
            "source": "RSC (Chemical Society Reviews)",
            "url": "https://www.rsc.org/journals-books-databases/about-journals/csr/feed/",
            "broad": False,
        },
        {
            "source": "RSC (Green Chemistry)",
            "url": "https://www.rsc.org/journals-books-databases/about-journals/green-chemistry/feed/",
            "broad": False,
        },
    ],
    "nature_chemistry": [
        {
            "source": "Nature Chemistry",
            "url": "https://www.nature.com/nchem.rss",
            "broad": False,
        },
    ],
    "chemistry_world": [
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
    ],

    # ── Physics ──
    "aps": [
        {
            "source": "APS (Physical Review Letters)",
            "url": "https://journals.aps.org/prl/rss/recent.xml",
            "broad": False,
        },
        {
            "source": "APS (Physical Review X)",
            "url": "https://journals.aps.org/prx/rss/recent.xml",
            "broad": False,
        },
        {
            "source": "APS (Reviews of Modern Physics)",
            "url": "https://journals.aps.org/rmp/rss/recent.xml",
            "broad": False,
        },
    ],
    "aip": [
        {
            "source": "AIP (Applied Physics Letters)",
            "url": "https://pubs.aip.org/aip/apl/rss",
            "broad": False,
        },
        {
            "source": "AIP (Journal of Applied Physics)",
            "url": "https://pubs.aip.org/aip/jap/rss",
            "broad": False,
        },
    ],

    # ── Biology / Medicine ──
    "biorxiv": [
        {
            "source": "bioRxiv (New Articles)",
            "url": "https://connect.biorxiv.org/biorxiv_xml.php?subject=all",
            "broad": True,
        },
    ],
    "medrxiv": [
        {
            "source": "medRxiv (New Articles)",
            "url": "https://connect.medrxiv.org/medrxiv_xml.php?subject=all",
            "broad": True,
        },
    ],
    "cdc": [
        {
            "source": "CDC Newsroom",
            "url": "https://tools.cdc.gov/api/v2/resources/media/feed.rss",
            "broad": True,
        },
    ],
    "nih": [
        {
            "source": "NIH News Releases",
            "url": "https://www.nih.gov/news-events/news-releases/feed",
            "broad": True,
        },
    ],

    # ── Computer Science ──
    "usenix": [
        {
            "source": "USENIX News",
            "url": "https://www.usenix.org/news/feed",
            "broad": True,
        },
    ],
    "ietf": [
        {
            "source": "IETF News",
            "url": "https://www.ietf.org/blog/feed/",
            "broad": True,
        },
    ],

    # ── Space / Earth Science ──
    "nasa": [
        {
            "source": "NASA Breaking News",
            "url": "https://www.nasa.gov/feeds/breaking-news/feed/",
            "broad": True,
        },
    ],
    "esa": [
        {
            "source": "ESA News",
            "url": "https://www.esa.int/Space_in_Member_States/Spain/RSS_Feed",
            "broad": True,
        },
    ],
    "cern": [
        {
            "source": "CERN News",
            "url": "https://home.cern/api/news/rss",
            "broad": True,
        },
    ],
    "wmo": [
        {
            "source": "WMO News",
            "url": "https://public.wmo.int/en/rss.xml",
            "broad": True,
        },
    ],

    # ── Statistics ──
    "ims": [
        {
            "source": "IMS Bulletin",
            "url": "https://imstat.org/feed/",
            "broad": True,
        },
    ],
    "asa": [
        {
            "source": "ASA (AmStat News)",
            "url": "https://magazine.amstat.org/feed/",
            "broad": True,
        },
    ],

    # ── Economics / Finance ──
    "nber_working_papers": [
        {
            "source": "NBER New Working Papers",
            "url": "https://www.nber.org/rss/new.xml",
            "broad": False,
        },
    ],
    "cepr": [
        {
            "source": "CEPR Discussion Papers",
            "url": "https://cepr.org/rss.xml",
            "broad": True,
        },
    ],
    "central_banks": [
        {
            "source": "Federal Reserve (FEDS Notes)",
            "url": "https://www.federalreserve.gov/feeds/fedsnotes.xml",
            "broad": True,
        },
        {
            "source": "ECB Research Bulletin",
            "url": "https://www.ecb.europa.eu/rss/resbull.html",
            "broad": True,
        },
        {
            "source": "Bank of England News",
            "url": "https://www.bankofengland.co.uk/rss/news",
            "broad": True,
        },
        {
            "source": "People's Bank of China News",
            "url": "https://www.bis.org/cbanks/rss/cb_rss_feeds.htm",
            "broad": True,
        },
    ],
    "fiscal_regulators": [
        {
            "source": "SEC Press Releases",
            "url": "https://www.sec.gov/news/pressreleases.rss",
            "broad": True,
        },
        {
            "source": "CFTC Press Releases",
            "url": "https://www.cftc.gov/PressRoom/PressReleases?format=rss",
            "broad": True,
        },
    ],

    # ── UN Agencies ──
    "united_nations": [
        {
            "source": "UN News",
            "url": "https://news.un.org/feed/subscribe/en/news/all/rss.xml",
            "broad": True,
        },
    ],
    "unesco": [
        {
            "source": "UNESCO News",
            "url": "https://www.unesco.org/en/rss.xml",
            "broad": True,
        },
    ],
    "unicef": [
        {
            "source": "UNICEF Press Centre",
            "url": "https://www.unicef.org/media/rss.xml",
            "broad": True,
        },
    ],
    "unep": [
        {
            "source": "UNEP News and Stories",
            "url": "https://www.unep.org/news-and-stories/rss.xml",
            "broad": True,
        },
    ],
    "wto": [
        {
            "source": "WTO News",
            "url": "https://www.wto.org/english/news_e/rss_e/rss_e.xml",
            "broad": True,
        },
    ],

    # ── Agriculture ──
    "cgiar": [
        {
            "source": "CGIAR News",
            "url": "https://www.cgiar.org/feed/",
            "broad": True,
        },
    ],

    # ── Climate / Environment ──
    "ipcc": [
        {
            "source": "IPCC News",
            "url": "https://www.ipcc.ch/feed/",
            "broad": True,
        },
    ],
    "energy_agencies": [
        {
            "source": "IEA Newsroom",
            "url": "https://www.iea.org/feeds/data-and-statistics",
            "broad": True,
        },
        {
            "source": "IRENA News",
            "url": "https://www.irena.org/newsroom/pressreleases/rss",
            "broad": True,
        },
    ],

    # ── Telecom / Standards ──
    "itu": [
        {
            "source": "ITU Newsroom",
            "url": "https://www.itu.int/en/newsroom/rss/Pages/default.aspx",
            "broad": True,
        },
    ],

    # ── Aviation ──
    "faa": [
        {
            "source": "FAA News",
            "url": "https://www.faa.gov/news/feed",
            "broad": True,
        },
    ],

    # ── MIT CSAIL ──
    "mit_csail_news": [
        {
            "source": "MIT CSAIL News",
            "url": "https://news.mit.edu/rss/topic/csail",
            "broad": True,
        },
    ],

    # ── Stock Exchanges ──
    "exchanges": [
        {
            "source": "NYSE Press Releases",
            "url": "https://www.nyse.com/rss/news",
            "broad": True,
        },
        {
            "source": "NASDAQ News",
            "url": "https://www.nasdaq.com/feed/rssoutbound?category=News",
            "broad": True,
        },
    ],

    # ── Transport ──
    "transport_departments": [
        {
            "source": "US DOT News",
            "url": "https://www.transportation.gov/feed/latest",
            "broad": True,
        },
    ],
    "transport_associations": [
        {
            "source": "TRB News",
            "url": "https://www.nationalacademies.org/trb/rss/news",
            "broad": True,
        },
    ],

    # ── Industry ──
    "industrial_automation_associations": [
        {
            "source": "IEEE Spectrum Automation",
            "url": "https://spectrum.ieee.org/feeds/topic/robotics.rss",
            "broad": True,
        },
    ],
}


def rss_feeds_for_source(source_id: str) -> list[dict[str, Any]]:
    """Return the RSS feed configs for a catalogue source ID, with provenance."""

    feeds = RSS_FEED_REGISTRY.get(source_id, [])
    return [
        {
            **feed_config,
            "source_id": source_id,
            "source_kind": _source_kind_for_id(source_id),
        }
        for feed_config in feeds
    ]


def _source_kind_for_id(source_id: str) -> str:
    official = frozenset({
        "who", "cdc", "nih", "nasa", "esa", "faa", "wmo", "noaa",
        "ipcc", "united_nations", "unesco", "unicef", "unep", "wto",
        "itu", "energy_agencies", "transport_departments",
        "central_banks", "fiscal_regulators", "national_science_agencies",
        "national_statistics", "international_statistics", "government_legislation",
        "judicial_opinions", "copernicus", "usgs", "usda", "fao", "clinical_trials",
        "official_rss",
    })
    return "official" if source_id in official else "academic"

# ── Additional RSS entries for sources not yet covered ──
# Extended: dblp (standalone RSS feed), usgs, usda, fao, fred, imf, oecd
#           bis, repec, jstor_metadata, project_euclid, eric, ssrn
#           openreview (blog RSS), semantic_scholar (blog RSS)
#           national_statistics, international_statistics

RSS_FEED_REGISTRY.update({
    "dblp": [
        {
            "source": "DBLP (New Publications)",
            "url": "https://dblp.org/feed/new.rss",
            "broad": True,
        },
    ],
    "usgs": [
        {
            "source": "USGS News Releases",
            "url": "https://www.usgs.gov/news/featured-stories/feed",
            "broad": True,
        },
    ],
    "usda": [
        {
            "source": "USDA News",
            "url": "https://www.usda.gov/rss.xml",
            "broad": True,
        },
    ],
    "fao": [
        {
            "source": "FAO News",
            "url": "https://www.fao.org/news/rss-feed/en/",
            "broad": True,
        },
    ],
    "fred": [
        {
            "source": "FRED Blog",
            "url": "https://fredblog.stlouisfed.org/feed/",
            "broad": True,
        },
    ],
    "imf": [
        {
            "source": "IMF News",
            "url": "https://www.imf.org/en/News/RSS",
            "broad": True,
        },
    ],
    "world_bank": [
        {
            "source": "World Bank News",
            "url": "https://www.worldbank.org/en/news/rss.xml",
            "broad": True,
        },
    ],
    "oecd": [
        {
            "source": "OECD Newsroom",
            "url": "https://www.oecd.org/en/newsroom/rss.html",
            "broad": True,
        },
    ],
    "bis": [
        {
            "source": "BIS Press Releases",
            "url": "https://www.bis.org/doclist/all_pressrels.rss",
            "broad": True,
        },
    ],
    "repec": [
        {
            "source": "RePEc (NEP New Papers)",
            "url": "https://nep.repec.org/rss",
            "broad": True,
        },
    ],
    "ssrn": [
        {
            "source": "SSRN Top Papers",
            "url": "https://papers.ssrn.com/sol3/Jeljour_results.cfm?form_name=journalBrowse&journal_id=0&Network=no&lim=true",
            "broad": True,
        },
    ],
    "jstor_metadata": [
        {
            "source": "JSTOR Daily",
            "url": "https://daily.jstor.org/feed/",
            "broad": True,
        },
    ],
    "project_euclid": [
        {
            "source": "Project Euclid (Latest)",
            "url": "https://projecteuclid.org/rss.xml",
            "broad": True,
        },
    ],
    "eric": [
        {
            "source": "ERIC (New Additions)",
            "url": "https://eric.ed.gov/?rss",
            "broad": True,
        },
    ],
    "openreview": [
        {
            "source": "OpenReview Blog",
            "url": "https://blog.openreview.net/feed/",
            "broad": True,
        },
    ],
    "semantic_scholar": [
        {
            "source": "Semantic Scholar Blog",
            "url": "https://blog.semanticscholar.org/feed/",
            "broad": True,
        },
    ],
    "papers_with_code": [
        {
            "source": "Papers with Code (Latest)",
            "url": "https://paperswithcode.com/feed/latest.rss",
            "broad": True,
        },
    ],
    "noaa": [
        {
            "source": "NOAA News",
            "url": "https://www.noaa.gov/news/rss.xml",
            "broad": True,
        },
    ],
    "national_statistics": [
        {
            "source": "BLS News Releases",
            "url": "https://www.bls.gov/feed/bls_latest.rss",
            "broad": True,
        },
    ],
    "national_science_agencies": [
        {
            "source": "NSF News",
            "url": "https://new.nsf.gov/news/feed",
            "broad": True,
        },
        {
            "source": "NIST News",
            "url": "https://www.nist.gov/news-events/news/feed",
            "broad": True,
        },
    ],

    # ── curated_rss treated as public_rss ──
    "think_tanks": [
        {
            "source": "Brookings Institution",
            "url": "https://www.brookings.edu/feed/",
            "broad": True,
        },
        {
            "source": "RAND Corporation",
            "url": "https://www.rand.org/latest/rss.xml",
            "broad": True,
        },
        {
            "source": "Peterson Institute (PIIE)",
            "url": "https://www.piie.com/rss.xml",
            "broad": True,
        },
    ],
    "museums_heritage": [
        {
            "source": "Smithsonian News",
            "url": "https://www.si.edu/rss/news/releases.xml",
            "broad": True,
        },
    ],

    # ── public_catalogue entries via RSS proxies ──
    "3gpp": [
        {
            "source": "3GPP News",
            "url": "https://www.3gpp.org/news-events/3gpp-news/rss",
            "broad": True,
        },
    ],
    "etsi": [
        {
            "source": "ETSI News",
            "url": "https://www.etsi.org/newsroom/rss",
            "broad": True,
        },
    ],
    "energy_standards": [
        {
            "source": "IEC News",
            "url": "https://www.iec.ch/blog/rss",
            "broad": True,
        },
    ],
    "national_libraries": [
        {
            "source": "Library of Congress Blog",
            "url": "https://blogs.loc.gov/loc/feed/",
            "broad": True,
        },
    ],

    # ── public_data sources ──
    "wvs": [
        {
            "source": "World Values Survey News",
            "url": "https://www.worldvaluessurvey.org/rss/wvs_news.xml",
            "broad": True,
        },
    ],

    # ── public_api sources with RSS alternatives ──
    "doaj": [
        {
            "source": "DOAJ News",
            "url": "https://blog.doaj.org/feed/",
            "broad": True,
        },
    ],
    "open_library": [
        {
            "source": "Internet Archive Blog",
            "url": "https://blog.archive.org/feed/",
            "broad": True,
        },
    ],
    "dpla": [
        {
            "source": "DPLA News",
            "url": "https://dp.la/news/feed",
            "broad": True,
        },
    ],
    "copernicus": [
        {
            "source": "Copernicus News",
            "url": "https://www.copernicus.eu/en/rss.xml",
            "broad": True,
        },
    ],
    "government_legislation": [
        {
            "source": "US Congress Bills",
            "url": "https://www.congress.gov/rss/most-viewed-bills.xml",
            "broad": True,
        },
    ],
    "zbmath": [
        {
            "source": "zbMATH Open (New Additions)",
            "url": "https://zbmath.org/rss/",
            "broad": True,
        },
    ],
})
