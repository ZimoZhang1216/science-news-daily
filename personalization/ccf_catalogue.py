"""Versioned CCF 2026 conference-to-DBLP mapping for personalised dailies.

The catalogue is intentionally static. CCF tier assignments are editorial
metadata, not a runtime network dependency; updating them is a reviewed source
change when CCF releases a new edition.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass


CCF_CATALOGUE_VERSION = "CCF 2026 第七版"
VALID_CCF_TIERS = frozenset({"A", "B", "C"})


@dataclass(frozen=True)
class CcfConference:
    """One CCF-listed conference family that DBLP exposes under a stable path."""

    tier: str
    abbreviation: str
    dblp_path: str


# Extracted from the CCF 2026 seventh-edition recommended-conference catalogue.
# Each value is ``dblp path slug|display abbreviation``. DBLP has a catalogue
# page for each slug; proceedings-year pages beneath it are discovered via the
# DBLP update feed rather than guessed from a conference's calendar.
_RAW_CATALOGUE_BY_TIER = {
    "A": (
        "aaai|AAAI;acl|ACL;asplos|ASPLOS;cav|CAV;ccs|CCS;chi|CHI;crypto|CRYPTO;"
        "cscw|CSCW;cvpr|CVPR;dac|DAC;eurocrypt|EUROCRYPT;eurosys|EuroSys;fast|FAST;"
        "fm|FM;focs|FOCS;hpca|HPCA;hpdc|HPDC;huc|UbiComp;iccv|ICCV;icde|ICDE;"
        "iclr|ICLR;icml|ICML;icse|ICSE;infocom|INFOCOM;isca|ISCA;issta|ISSTA;"
        "kbse|ASE;kdd|SIGKDD;lics|LICS;micro|MICRO;mm|ACM MM;mobicom|MobiCom;"
        "ndss|NDSS;nips|NeurIPS;nsdi|NSDI;oopsla|OOPSLA;osdi|OSDI;pldi|PLDI;"
        "popl|POPL;ppopp|PPoPP;rtss|RTSS;sc|SC;sigcomm|SIGCOMM;sigir|SIGIR;"
        "sigmod|SIGMOD;sigsoft|FSE;soda|SODA;sosp|SOSP;sp|S&P;stoc|STOC;uist|UIST;"
        "usenix|USENIX ATC;uss|USENIX Security;vldb|VLDB;vr|VR;www|WWW"
    ),
    "B": (
        "IEEEpact|PACT;acsac|ACSAC;asiacrypt|ASIACRYPT;bibm|BIBM;cade|CADE;"
        "caise|CAiSE;cc|CC;cgo|CGO;ches|CHES;cidr|CIDR;cikm|CIKM;cloud|SoCC;"
        "cluster|CLUSTER;coco|CCC;cocoon|COCOON;cogsci|CogSci;coling|COLING;"
        "colt|COLT;compgeom|SoCG;concur|CONCUR;conext|CoNEXT;cp|CP;csfw|CSFW;"
        "dasfaa|DASFAA;date|DATE;dcc|DCC;dsn|DSN;ecai|ECAI;eccv|ECCV;ecoop|ECOOP;"
        "ecscw|ECSCW;edbt|EDBT;emnlp|EMNLP;emsoft|EMSOFT;esa|ESA;esem|ESEM;"
        "esorics|ESORICS;etaps|ETAPS;eurographics|Eurographics;europar|Euro-Par;"
        "fmcad|FMCAD;fpga|FPGA;fse|FSE;group|GROUP;hipeac|HiPEAC;hotchips|Hot Chips;"
        "hotos|HotOS;hybrid|HSCC;icalp|ICALP;icassp|ICASSP;iccad|ICCAD;iccbr|ICCBR;"
        "iccd|ICCD;icdcs|ICDCS;icdm|ICDM;icdt|ICDT;icfp|ICFP;icmcs|ICME;icnp|ICNP;"
        "icpp|ICPP;icra|ICRA;ics|ICS;icsm|ICSME;icsoc|ICSOC;icws|ICWS;icwsm|ICWSM;"
        "ijcai|IJCAI;imc|IMC;interspeech|Interspeech;ipps|IPDPS;ipsn|IPSN;iscas|ISCAS;"
        "ismar|ISMAR;ismb|ISMB;issre|ISSRE;itc|ITC;iui|IUI;iwpc|ICPC;iwqos|IWQoS;"
        "kr|KR;lctrts|LCTES;lisa|LISA;miccai|MICCAI;middleware|Middleware;mir|ICMR;"
        "mobihoc|MobiHoc;mobisys|MobiSys;models|MoDELS;mss|MSST;naacl|NAACL;"
        "nossdav|NOSSDAV;percom|PERCOM;performance|Performance;pg|PG;pkc|PKC;"
        "pkdd|ECML-PKDD;podc|PODC;pods|PODS;ppsn|PPSN;raid|RAID;re|RE;recomb|RECOMB;"
        "recsys|RecSys;rt|EGSR;rtas|RTAS;sas|SAS;sat|SAT;sca|SCA;sdm|SDM;secon|SECON;"
        "semweb|ISWC;sensys|SenSys;sgp|SGP;si3d|I3D;sigmetrics|SIGMETRICS;sma|SPM;"
        "spaa|SPAA;srds|SRDS;tabletop|ISS;tcc|TCC;uai|UAI;vee|VEE;vissym|EuroVis;"
        "vmcai|VMCAI;wcre|SANER;wine|WINE;wise|WISE;wsdm|WSDM"
    ),
    "C": (
        "3dim|3DV;ACMdis|DIS;IEEEcloud|IEEE CLOUD;IEEEscc|SSE;IEEEwisa|WISA;"
        "accv|ACCV;acisp|ACISP;acmidc|IDC;acml|ACML;acns|ACNS;adma|ADMA;aft|AFT;"
        "aistats|AISTATS;alt|ALT;amia|AMIA;ancs|ANCS;apbc|APBC;aplas|APLAS;"
        "apnet|APNet;apnoms|APNOMS;appt|APPT;apsec|APSEC;apvis|PacificVis;apweb|APWeb;"
        "asap|ASAP;aspdac|ASP-DAC;asru|ASRU;assets|ASSETS;ats|ATS;atva|ATVA;avi|AVI;"
        "bigdataconf|IEEE BigData;blocksys|BlockSys;bmvc|BMVC;ca|Extended Reality;cases|CASES;"
        "ccgrid|CCGRID;cec|IEEE CEC;cf|CF;cgi|CGI;cisc|Inscrypt;codaspy|CODASPY;"
        "colcom|CollaborateCom;compsac|COMPSAC;conll|CoNLL;coopis|CoopIS;cosit|COSIT;"
        "cscloud|CSCloud;cscwd|CSCWD;csl|CSL;ctrsa|CT-RSA;dai2|DAI;dexa|DEXA;dfrws|DFRWS;"
        "dimva|DIMVA;drm|DRM;dsaa|DSAA;ease|EASE;ecir|ECIR;er|ER;esws|ESWC;ets|ETS;"
        "eurosp|EuroS&P;faw|IJTCS-FAW;fc|FC;fccm|FCCM;fgr|FG;forte|FORTE;fpl|FPL;fpt|FPT;"
        "fsttcs|FSTTCS;gecco|GECCO;globecom|GLOBECOM;glvlsi|GLSVLSI;gmp|GMP;gpc|GPC;"
        "graphicsinterface|GI;haptics|IEEE World Haptics;hipc|HiPC;hoti|HOTI;hotnets|HotNets;"
        "hotstorage|HotStorage;hpcc|HPCC;ica3pp|ICA3PP;icann|ICANN;icb|IJCB;icc|ICC;"
        "icccn|ICCCN;icdar|ICDAR;icdf2c|ICDF2C;iceccs|ICECCS;icfem|ICFEM;icic|ICIC;"
        "icics|ICICS;icig|ICIG;icip|ICIP;icmi|ICMI;iconip|ICONIP;icpads|ICPADS;icpr|ICPR;"
        "icsr|ICSR;icst|ICST;ictac|ICTAC;ictai|ICTAI;icwe|ICWE;icxr|ICXR;ieeesec|SEC;"
        "ifip11-9|IFIP WG 11.9;ih|IH&MMSec;ijcnn|IJCNN;ilp|ILP;im|IM;interact|INTERACT;"
        "internetware|Internetware;ipccc|IPCCC;ipco|IPCO;iros|IROS;isaac|ISAAC;isbra|ISBRA;"
        "iscc|ISCC;islped|ISLPED;ispa|ISPA;ispass|ISPASS;ispd|ISPD;ispw|ICSSP;isw|ISC;"
        "itc-asia|ITC-Asia;ksem|KSEM;lcn|LCN;lopstr|LOPSTR;mascots|MASCOTS;mass|MASS;"
        "mdm|MDM;memocode|MEMOCODE;mfcs|MFCS;mobiquitous|MobiQuitous;msn|MSN;msr|MSR;"
        "mswim|MSWiM;nas|NAS;networking|Networking;nlpcc|NLPCC;nocs|NOCS;npc|NPC;nspw|NSPW;"
        "p2p|P2P;pakdd|PAKDD;pam|PAM;paste|PASTE;pepm|PEPM;pet|PETS;prcv|PRCV;pricai|PRICAI;"
        "qrs|QRS;refsq|REFSQ;rta|RTA;rv|RV;sacmat|SACMAT;sacrypt|SAC;sagt|SAGT;scam|SCAM;"
        "sec|SEC;securecomm|SecureComm;seke|SEKE;service|ICSS;setta|SETTA;slt|SLT;smc|SMC;"
        "smi|SMI;soups|SOUPS;spin|SPIN;ssd|SSTD;ssdbm|SSDBM;stacs|STACS;systor|SYSTOR;"
        "tase|TASE;trustcom|TrustCom;uic|UIC;vts|VTS;waim|WAIM;wasa|WASA;wcnc|WCNC;"
        "webdb|WebDB;wicsa|WICSA;wisec|WiSec;wowmom|WoWMoM;ccs|AsiaCCS"
    ),
}


def _build_catalogue() -> tuple[CcfConference, ...]:
    conferences: list[CcfConference] = []
    for tier, raw_entries in _RAW_CATALOGUE_BY_TIER.items():
        for raw_entry in raw_entries.split(";"):
            slug, separator, abbreviation = raw_entry.partition("|")
            if not separator or not slug or not abbreviation:
                raise RuntimeError("invalid CCF conference catalogue entry")
            conferences.append(
                CcfConference(
                    tier=tier,
                    abbreviation=abbreviation,
                    dblp_path=f"/db/conf/{slug}/",
                )
            )
    return tuple(conferences)


CCF_CONFERENCES = _build_catalogue()


def conferences_for_tiers(tiers: Collection[str]) -> tuple[CcfConference, ...]:
    """Return CCF venues in the operator-selected tier scope."""

    selected_tiers = frozenset(tiers)
    if not selected_tiers or not selected_tiers.issubset(VALID_CCF_TIERS):
        raise ValueError("tiers must be a non-empty subset of A, B, and C")
    return tuple(conference for conference in CCF_CONFERENCES if conference.tier in selected_tiers)
