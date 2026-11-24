import os
import re
import time
import requests
import xml.etree.ElementTree as ET
from urllib.parse import quote
from google import genai
from groq import Groq

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_KEY = os.environ["GEMINI_KEY"]
GROQ_KEY = os.environ.get("GROQ_KEY", "")

# ---------- Germany + Austria only. Switzerland removed. ----------
DACH_CITIES = [
    "germany", "deutschland", "berlin", "münchen", "munich", "hamburg",
    "frankfurt", "köln", "cologne", "düsseldorf", "dusseldorf", "stuttgart",
    "leipzig", "dresden", "hannover", "nürnberg", "nuremberg", "bremen",
    "essen", "dortmund", "bonn", "mainz", "wiesbaden", "karlsruhe",
    "mannheim", "augsburg", "aachen", "münster", "muenster", "freiburg",
    "kiel", "rostock", "potsdam", "erfurt", "magdeburg", "saarbrücken",
    "krefeld", "wolfsburg", "ingolstadt", "regensburg", "ulm", "heilbronn",
    "paderborn", "bielefeld", "göttingen", "kassel", "würzburg",
    "verl", "gütersloh", "guetersloh", "espelkamp",
    "österreich", "austria", "wien", "vienna", "graz", "linz",
    "salzburg", "innsbruck", "klagenfurt",
]

def is_dach(location):
    loc = (location or "").lower()
    return any(c in loc for c in DACH_CITIES)

SWITZERLAND_RE = re.compile(
    r"\b(switzerland|schweiz|zürich|zurich|basel|bern|genf|geneva|"
    r"luzern|lausanne|winterthur|st\.?\s*gallen|ch-)\b",
    re.IGNORECASE,
)

def is_switzerland(location):
    return bool(SWITZERLAND_RE.search(location or ""))

# ---------- Hard reject titles ----------
# NOTE: "experte|spezialist" below BLOCKS thesis-relevant roles like
#       "Prüfmittel Spezialist", "FAIR Data Specialist", "Messtechnik Spezialist".
#       The new domain-specific rejects (compliance, kyc, aml, data steward,
#       stammdaten) already catch the bad ones. Delete that line for the
#       laser-sharp version.
HARD_REJECT_TITLE_RE = re.compile(
    r"\b("
    r"werkstudent|working.?student|praktikant|praktikum|ausbildung|"
    r"auszubildende|azubi|dual(es)? studium|internship|intern|"
    r"senior|sr|lead|head.?of|director|vp|chief|principal|staff|"
    r"managing.?director|geschäftsführer|leitung|führungskraft|"
    r"teamleiter|teamleiterin|projektleiter|"
    r"experte|spezialist|"                                # <-- delete this line to unblock Prüfmittel/FAIR specialists
    r"developer|entwickler|full.?stack|fullstack|"
    r"backend|back.?end|frontend|front.?end|devops|site.?reliability|"
    r"cloud.?engineer|mobile.?developer|ios.?developer|android.?developer|"
    r"machine.?learning|ml.?engineer|ml.?ops|ai.?engineer|platform.?engineer|"
    r"engineering.?manager|product.?manager|program.?manager|"
    r"account.?manager|account.?executive|sales.?manager|"
    r"marketing.?manager|hr.?manager|hr.?generalist|it.?manager|"
    r"office.?manager|backoffice.?manager|"
    r"supplier.?development|lieferantenmanager|"
    r"sales.?engineer|vertriebsingenieur|außendienst|aussendienst|"
    r"controller|fp.?&.?a|accounting|buchhaltung|bilanzbuchhalter|"
    r"ui.?ux|designer|grafiker|graphic|"
    r"iot|embedded|sentinel|quality.?inspector|optical|thermal|"
    r"vehicle|forward.?deployed|"
    r"customer.?success|customer.?service|kundendienst|"
    r"kundenbetreuer|kundenberater|call.?center|telefonist|"
    r"systemadministrator|system.?administrator|it.?systemadmin|"
    r"generalist|generalistin|recruiter|recruiting|"
    r"pflege|nursing|krankenpflege|"
    r"gastronomie|restaurant|hotel|kellner|koch|küche|"
    # NEW: financial crime / compliance / data governance — reject at TITLE level
    r"kyc|aml|geldwäsche|geldwaesche|"
    r"compliance|compliance.?manager|compliance.?analyst|"
    r"bankkaufmann|bankkauffrau|banking.?operations|"
    r"data.?steward|data.?governance|data.?quality|"
    r"master.?data|stammdaten|stammdatenmanagement|"
    r"sanctions|transaction.?monitoring|financial.?crime|"
    r"audit\w*|revision\w*|"
    r"datenschutz\w*|data.?protection|"
    r"risk.?management|risikomanagement|"
    r"regulator\w*"
    r")\b",
    re.IGNORECASE,
)

# ---------- Hard reject body ----------
HARD_REJECT_BODY_RE = re.compile(
    r"\b("
    r"c1|c2|verhandlungssicher|muttersprache|"
    r"fließend.?deutsch|fliessend.?deutsch|"
    r"native.?german|deutsch.?als.?muttersprache|"
    r"mehrjährige\s*(?:berufs)?erfahrung|mehrjaehrige\s*(?:berufs)?erfahrung|"
    r"mindestens\s*\d+\s*jahre|mind\.\s*\d+\s*jahre|"
    r"mindestens\s+(?:zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn)\s+jahre|"
    r"französisch|french|spanisch|italienisch|niederländisch|"
    r"maternity.?cover|temporary.?contract|befristet.?auf|"
    r"kyc|aml|geldwäsche|compliance|bankkaufmann|bankkauffrau|"
    r"data steward|master data|stammdaten"
    r")\b",
    re.IGNORECASE,
)

# ---------- Entry-level signals ----------
ENTRY_LEVEL_PHRASES = [
    "berufseinsteiger", "berufseinsteigerin", "berufseinsteigerinnen",
    "berufseinsteiger:innen", "berufseinsteiger*innen",
    "berufseinstieg",
    "berufsanfänger", "berufsanfaenger", "berufsanfängerin", "berufsanfängerinnen",
    "berufsanfänger:innen", "berufsanfänger*innen",
    "hochschulabsolvent", "hochschulabsolventen", "hochschulabsolventin",
    "hochschulabsolventinnen", "hochschulabsolvent:innen", "hochschulabsolvent*innen",
    "absolvent", "absolventen", "absolventin", "absolventinnen",
    "absolvent:innen", "absolvent*innen",
    "trainee", "traineeprogramm", "trainee-programm", "trainee programm",
    "graduate", "graduates",
    "einsteiger", "einsteigerin", "einsteigerinnen", "einsteiger:innen",
    "junior", "juniorstelle", "junior-stelle",
    "quereinsteiger", "quereinsteigerin", "quereinsteigerinnen",
    "quereinsteiger:innen", "quereinsteiger*innen", "quereinstieg",
    "keine berufserfahrung", "ohne berufserfahrung",
    "keine vorkenntnisse", "ohne vorkenntnisse",
    "erfahrung ist egal", "berufserfahrung ist egal", "erfahrung egal",
    "erfahrung: egal", "berufserfahrung: egal",
    "berufserfahrung nicht erforderlich", "erfahrung nicht erforderlich",
    "berufserfahrung nicht zwingend", "erfahrung nicht zwingend",
    "vorkenntnisse nicht erforderlich", "vorkenntnisse nicht zwingend",
    "auch berufseinsteiger willkommen", "berufseinsteiger willkommen",
    "berufseinsteiger sind auch willkommen",
    "berufseinsteiger:innen sind auch willkommen",
    "auch berufseinsteiger:innen willkommen",
    "auch ohne berufserfahrung", "auch ohne erfahrung",
    "auch quereinsteiger willkommen", "quereinsteiger willkommen",
    "auch quereinsteiger:innen willkommen",
    "wir freuen uns auf berufseinsteiger", "wir freuen uns über berufseinsteiger",
    "0-1 jahre", "0 bis 1 jahre", "0-2 jahre", "0 bis 2 jahre",
    "0-3 jahre", "0 bis 3 jahre", "1-2 jahre", "1 bis 2 jahre",
    "1-3 jahre", "1 bis 3 jahre", "bis zu 2 jahre", "bis zu 3 jahre",
    "maximal 2 jahre", "maximal 3 jahre",
    "erste berufserfahrung", "erste erfahrung", "erste praktische erfahrung",
    "1 jahr erfahrung", "1 jahr berufserfahrung",
]

MID_LEVEL_PENALTY_RE = re.compile(
    r"("
    r"erfahrene[rn]?\s+(?:persönlichkeit|fachkraft|ingenieur|entwickler|mitarbeiter)|"
    r"mehrere\s+jahre\s+(?:berufs)?erfahrung|"
    r"langjährige\s+(?:berufs)?erfahrung|"
    r"fundierte\s+(?:berufs)?erfahrung|"
    r"(?:[3-9]|\d{2,})\s*[-–]\s*\d+\s*jahre\s*(?:berufs)?erfahrung|"
    r"(?:[3-9]|\d{2,})\+?\s*jahre\s*(?:berufs)?erfahrung"
    r")",
    re.IGNORECASE,
)

# ---------- TIER1_STRONG: at least ONE must match to survive ----------
TIER1_STRONG = [
    # Test / Prüfmittel
    "testingenieur", "test engineer", "test automation", "testautomatisierung",
    "prüfmittel", "prüfmittelentwickler", "prüfmittelplaner", "prüfingenieur",
    "prüfstand", "teststand", "prüfstandsentwickler",
    "testapplikation", "test system", "testsystem",
    "qualitätssicherung", "quality assurance",
    "produktprüfung", "produkttest",
    # Measurement / Messtechnik
    "messtechnik", "messtechniker", "measurement engineer", "measurement system",
    "kalibrierung", "calibration", "kalibriertechniker", "kalibrieringenieur",
    "sensorintegration", "sensor integration",
    "messsystem", "messstation", "prüflabor",
    # System integration
    "systemintegration", "system integration", "systemintegrator",
    "schnittstelle", "schnittstellen", "interface",
    "inbetriebnahme", "commissioning",
    "hardware-software", "hardware software", "hardware/software",
    "hardware integration", "hardware-integration",
    # Lab automation (thesis-specific)
    "laborautomation", "laborautomatisierung", "lab automation",
    "laboratory automation", "lab automation engineer",
    "pyironflow", "workflow automation", "workflow system",
    "elektrochemie", "electrochemistry", "electrochemical",
    "potentiostat", "palmsens",
    "material acceleration", "self-driving lab", "self driving lab",
    "laborinformatik", "lab informatics",
    "labor digitalisierung", "lab digitalization",
    "labor 4.0", "lab 4.0",
    # Cobot / Robotics
    "cobot", "kollaborativer roboter", "collaborative robot",
    "omron", "tm5", "tmflow",
    "robotik", "robotics", "roboter",
    "wellenmessung", "shaft measurement",
    "imbus", "imb-io",
    "induktive messung", "inductive probe",
    # Automation
    "automatisierung", "automation", "automatisierungsingenieur",
    # Technical writing
    "technischer redakteur", "technical writer", "technische dokumentation",
    "technical documentation", "din iso", "din en iso",
    # Requirements
    "requirements engineer", "anforderungsanalyse", "anforderungsmanagement",
    # FAIR / provenance (engineering context only)
    "json-ld", "jsonld", "provenance", "prov-o", "opmw", "ro-crate",
    "fair data", "fair-data", "research data management", "forschungsdaten",
    "forschungsdatenmanagement", "metadata", "metadaten",
]

# ---------- TIER1_WEAK: boost only, never the sole reason to keep ----------
TIER1_WEAK = [
    "python", "api", "rest", "rest api", "docker", "git",
    "sql", "linux", "jupyter", "csv",
    "data pipeline", "datenpipeline",
    "prozess", "process",
    "projekt", "project",
]

# Kept as alias so any other reference still works
TIER1 = TIER1_STRONG + TIER1_WEAK

TIER2 = [
    "berufseinsteiger", "berufseinstieg", "quereinsteiger", "quereinstieg",
    "absolvent", "junior", "trainee", "graduate",
    "prozess", "process", "projekt", "project",
    "dokumentation", "documentation",
    "testing", "validierung", "quality assurance",
    "ingenieur", "engineer", "mint"
]

MAX_SCORE = 15
MIN_MATCH = 50

# ---------- CV_SUMMARY updated to match the real thesis ----------
CV_SUMMARY = """
M.Sc. Advanced Industrial Engineering (Wirtschaftsingenieurwesen, Grade 1.9), TH Rosenheim.
B.Tech Mechanical Engineering.

BAM Berlin Master's Thesis: "Visual Programming Workflow for Electrochemical Automation"
- Developed a node-based automation workflow in PyironFlow (Python) for electrochemical measurements.
- Integrated Ender3 positioning unit with PalmSens potentiostat via serial communication and REST APIs.
- Built calibration and validation routines: positional accuracy, timing, data integrity.
- Implemented FAIR data handling: JSON-LD metadata, PROV-O / OPMW provenance, RO-Crate.
- Used Docker/Git for reproducible test environments.

Cobot Project (Omron TM5-900 at TH Rosenheim):
- Automated shaft measurement system integration: inductive probes, IMBus I/O modules, digital I/O.
- Designed custom workpiece carriers and gripper jaws via additive manufacturing.
- Programmed cobot, integrated sensors, pneumatics; built calibration routine (every 100 parts / 1 hour).

Professional Experience:
6 years at Federal Bank: requirements analysis, project coordination, system rollouts, regulated documentation.

Languages: English C1, German B2. Work permit Section 18b.
"""

THESIS_KEYWORDS = [
    "pyironflow", "electrochemical", "potentiostat", "palmsens", "ender3",
    "json-ld", "prov-o", "opmw", "ro-crate", "fair data",
    "workflow automation", "lab automation", "laboratory automation",
    "docker", "python", "rest api", "serial",
    "measurement", "messtechnik", "calibration", "kalibrierung",
    "validation", "positioning", "sensor", "hardware",
    "cobot", "omron", "tm5", "imbus", "inductive probe",
    "shaft measurement", "wellenmessung",
]

ENGLISH_PRIMARY_RE = re.compile(
    r"\b(english.?speaking|english.?working.?language|"
    r"working.?language.?english|project.?language.?english|"
    r"fluent.?english|business.?english|english.?required|"
    r"very.?good.?english|excellent.?english)\b",
    re.IGNORECASE,
)

GERMAN_ONLY_RE = re.compile(
    r"\b(deutschkenntnisse|german.?language|deutsch.?erforderlich|"
    r"sehr.?gute.?deutsch|gute.?deutsch)\b",
    re.IGNORECASE,
)

groq_client = Groq(api_key=GROQ_KEY) if GROQ_KEY else None
gemini_client = genai.Client(api_key=GEMINI_KEY)


# ============================================================
# FETCHERS (12 free sources)
# ============================================================

def fetch_arbeitnow():
    try:
        r = requests.get("https://www.arbeitnow.com/api/job-board-api", timeout=30)
        r.raise_for_status()
        return [{
            "title": j.get("title", ""),
            "company": j.get("company_name", ""),
            "location": j.get("location", ""),
            "description": j.get("description", ""),
            "url": j.get("url", ""),
            "source": "arbeitnow",
        } for j in r.json().get("data", [])]
    except Exception as e:
        print(f"Arbeitnow error: {e}")
        return []


def fetch_bundesagentur():
    headers = {"X-API-Key": "jobboerse-jobsuche"}
    queries = [
        # Thesis-relevant German
        "Laborautomation", "Laborautomatisierung", "Automatisierungsingenieur",
        "Prüfmittelentwickler", "Prüfmittelplaner", "Prüfingenieur",
        "Testingenieur", "Messtechnik Ingenieur", "Messtechniker",
        "Kalibriertechniker", "Kalibrieringenieur",
        "Systemintegrator", "Systemintegration", "Inbetriebnahmeingenieur",
        "Applikationsentwickler Messtechnik", "Prüfstandsentwickler",
        "Versuchsingenieur", "Softwareentwickler Mess- und Prüftechnik",
        "Laborinformatiker",
        # Thesis-relevant English
        "Lab Automation Engineer", "Laboratory Automation Engineer",
        "Test Engineer", "Test Automation Engineer",
        "Measurement Engineer", "Calibration Engineer",
        "System Integration Engineer", "Commissioning Engineer",
        "Application Engineer Measurement", "Test Bench Developer",
        "Scientific Software Developer", "Research Data Engineer",
        "Workflow Developer", "Requirements Engineer",
        # Thesis-specific research terms
        "PyironFlow", "electrochemical automation", "potentiostat",
        "FAIR data", "JSON-LD", "PROV-O", "metadata",
        "research data management", "Material Acceleration Platform",
        # Cobot-specific
        "cobot", "collaborative robot", "Omron TM5", "TMFlow",
        "IMBus", "Wellenmessung", "Prüfmittel", "Messstation",
    ]
    jobs = []
    seen = set()

    for q in queries:
        params = {"was": q, "size": 40, "page": 1, "veroeffentlichtseit": 14}
        try:
            r = requests.get(
                "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs",
                headers=headers, params=params, timeout=30,
            )
            if r.status_code != 200:
                continue

            data = r.json()
            results = data.get("ergebnisliste") or data.get("ergebnisse") or []
            print(f"  BA '{q}': {len(results)} results")

            for j in results:
                if not isinstance(j, dict):
                    continue

                t = j.get("stellenangebotsTitel") or j.get("titel") or j.get("beruf") or ""
                if not isinstance(t, str):
                    t = ""
                t = t.strip()
                if not t or t in seen:
                    continue
                seen.add(t)

                loc = ""
                lok = j.get("stellenlokationen")
                if isinstance(lok, list) and lok:
                    first = lok[0]
                    if isinstance(first, dict):
                        addr = first.get("adresse", {})
                        if isinstance(addr, dict):
                            loc = addr.get("ort", "") or ""

                desc = j.get("beschreibung") or ""
                if not isinstance(desc, str):
                    desc = ""

                jobs.append({
                    "title": t,
                    "company": j.get("firma") or j.get("arbeitgeber") or "",
                    "location": loc or "Germany",
                    "description": desc,
                    "url": f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{j.get('referenznummer','')}",
                    "source": "bundesagentur",
                })
        except Exception as e:
            print(f"  BA '{q}' exception: {e}")

    return jobs


def fetch_academics_de():
    jobs = []
    seen_urls = set()
    queries = [
        "Lab Automation", "Laboratory Automation", "FAIR data",
        "research data management", "metadata", "PyironFlow",
        "electrochemical", "Python data", "data engineer",
        "workflow automation", "scientific software",
        "measurement automation", "laboratory informatics",
    ]
    headers = {"User-Agent": "Mozilla/5.0 (compatible; JobRadar/1.0)"}

    for q in queries:
        try:
            url = f"https://www.academics.de/jobs?q={quote(q)}"
            r = requests.get(url, headers=headers, timeout=20)
            if r.status_code != 200:
                print(f"  academics.de '{q}': HTTP {r.status_code}")
                continue

            links = re.findall(r'href="(/jobs/[^"#?]+)"', r.text)
            print(f"  academics.de '{q}': {len(links)} links")

            for link in links:
                if not re.search(r'-\d{4,}$', link):
                    continue
                if link in seen_urls:
                    continue
                seen_urls.add(link)

                slug = link.split("/jobs/")[-1]
                title = re.sub(r'-\d+$', '', slug).replace('-', ' ').replace('/', ' ').title().strip()
                if not title or len(title) < 5:
                    continue

                jobs.append({
                    "title": title,
                    "company": "academics.de",
                    "location": "Germany",
                    "description": "",
                    "url": f"https://www.academics.de{link}",
                    "source": "academics_de",
                })
        except Exception as e:
            print(f"  academics.de '{q}' exception: {e}")

    return jobs


def _parse_rss(url, source_name, default_location="Germany / Remote", title_filter=None):
    jobs = []
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        root = ET.fromstring(r.content)
        for item in root.findall(".//item"):
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            desc = item.findtext("description", "").strip()
            if not title or not link:
                continue
            combined = (title + " " + desc).lower()
            if title_filter and not any(k in combined for k in title_filter):
                continue
            jobs.append({
                "title": title,
                "company": source_name,
                "location": default_location,
                "description": desc,
                "url": link,
                "source": source_name,
            })
        print(f"  {source_name}: {len(jobs)}")
    except Exception as e:
        print(f"  {source_name} exception: {e}")
    return jobs


def fetch_euraxess():
    return _parse_rss(
        "https://www.euraxess.ba/sr/services/jobs/rss",
        "euraxess",
        default_location="Germany / Austria / EU",
        title_filter=["germany", "austria", "deutschland", "österreich",
                      "data", "engineer", "research", "automation",
                      "laboratory", "measurement", "electrochemical"],
    )


def fetch_weworkremotely():
    return _parse_rss(
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "weworkremotely",
        default_location="Remote",
        title_filter=["python", "engineer", "integration", "test", "automation",
                      "data", "api", "lab", "workflow"],
    )


def fetch_remotive():
    return _parse_rss(
        "https://remotive.com/remote-jobs/feed/engineering",
        "remotive",
        default_location="Remote",
        title_filter=["python", "engineer", "integration", "test", "automation",
                      "data", "api", "lab", "workflow"],
    )


def fetch_berlinstartupjobs():
    return _parse_rss(
        "https://berlinstartupjobs.com/feed/",
        "berlinstartupjobs",
        default_location="Berlin, Germany",
        title_filter=["python", "engineer", "integration", "test", "automation",
                      "data", "api", "technical", "lab"],
    )


def fetch_kowi():
    jobs = []
    try:
        r = requests.get(
            "https://www.kowi.de/desktopdefault.aspx/tabid-111/",
            timeout=20, headers={"User-Agent": "Mozilla/5.0"},
        )
        r.raise_for_status()
        for m in re.finditer(r'\[([^\]]{10,180})\]\(([^)]+)\)', r.text):
            title = m.group(1).strip()
            url = m.group(2).strip()
            if not url.startswith("http"):
                url = "https://www.kowi.de" + url
            tl = title.lower()
            if any(k in tl for k in [
                "helmholtz", "leibniz", "fraunhofer", "postdoc", "phd",
                "research", "scientist", "engineer", "data", "python",
                "doktorand", "wissenschaft", "automation", "laboratory",
                "measurement", "electrochemical", "workflow",
            ]):
                jobs.append({
                    "title": title,
                    "company": "Research institute (KoWi)",
                    "location": "Germany / Austria",
                    "description": "",
                    "url": url,
                    "source": "kowi",
                })
        print(f"  KoWi: {len(jobs)}")
    except Exception as e:
        print(f"  KoWi exception: {e}")
    return jobs


def fetch_jobriver():
    jobs = []
    seen = set()
    queries = ["systemintegration", "testingenieur", "automatisierung",
               "python", "messtechnik", "daten", "laborautomation",
               "prüfmittel", "kalibrierung"]
    headers = {"User-Agent": "Mozilla/5.0 (compatible; JobRadar/1.0)"}
    try:
        for q in queries:
            r = requests.get(f"https://jobriver.de/jobs?q={quote(q)}", headers=headers, timeout=20)
            if r.status_code != 200:
                continue
            for m in re.finditer(r'href="(/job/[^"#?]+)"[^>]*>(.*?)</a>', r.text, re.DOTALL):
                path = m.group(1)
                title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
                if not title or len(title) < 5 or path in seen:
                    continue
                seen.add(path)
                jobs.append({
                    "title": title,
                    "company": "JOBRIVER",
                    "location": "Germany",
                    "description": "",
                    "url": f"https://jobriver.de{path}",
                    "source": "jobriver",
                })
        print(f"  JOBRIVER: {len(jobs)}")
    except Exception as e:
        print(f"  JOBRIVER exception: {e}")
    return jobs


def fetch_jobs_daheim():
    jobs = []
    try:
        r = requests.get(
            "https://jobs-daheim.de/",
            timeout=20, headers={"User-Agent": "Mozilla/5.0"},
        )
        if r.status_code == 200:
            for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.DOTALL):
                href = m.group(1)
                inner = re.sub(r"<[^>]+>", "", m.group(2)).strip()
                if "/job/" in href and 5 < len(inner) < 140:
                    jobs.append({
                        "title": inner,
                        "company": "Jobs-Daheim",
                        "location": "DACH (remote)",
                        "description": "",
                        "url": href if href.startswith("http") else "https://jobs-daheim.de" + href,
                        "source": "jobs_daheim",
                    })
        print(f"  Jobs-Daheim: {len(jobs)}")
    except Exception as e:
        print(f"  Jobs-Daheim exception: {e}")
    return jobs


def fetch_englishjobs():
    jobs = []
    seen = set()
    try:
        r = requests.get(
            "https://englishjobs.de/",
            timeout=20, headers={"User-Agent": "Mozilla/5.0"},
        )
        if r.status_code == 200:
            for m in re.finditer(r'href="(/job/[^"#?]+)"[^>]*>(.*?)</a>', r.text, re.DOTALL):
                path = m.group(1)
                title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
                if not title or len(title) < 5 or path in seen:
                    continue
                seen.add(path)
                jobs.append({
                    "title": title,
                    "company": "EnglishJobs.de",
                    "location": "Germany",
                    "description": "",
                    "url": f"https://englishjobs.de{path}",
                    "source": "englishjobs",
                })
        print(f"  EnglishJobs: {len(jobs)}")
    except Exception as e:
        print(f"  EnglishJobs exception: {e}")
    return jobs


def fetch_germantechjobs():
    jobs = []
    seen = set()
    try:
        r = requests.get(
            "https://germantechjobs.de/en",
            timeout=20, headers={"User-Agent": "Mozilla/5.0"},
        )
        if r.status_code == 200:
            for m in re.finditer(r'href="(/en/jobs/[^"#?]+)"[^>]*>(.*?)</a>', r.text, re.DOTALL):
                path = m.group(1)
                title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
                if not title or len(title) < 5 or path in seen:
                    continue
                seen.add(path)
                jobs.append({
                    "title": title,
                    "company": "GermanTechJobs",
                    "location": "Germany",
                    "description": "",
                    "url": f"https://germantechjobs.de{path}",
                    "source": "germantechjobs",
                })
        print(f"  GermanTechJobs: {len(jobs)}")
    except Exception as e:
        print(f"  GermanTechJobs exception: {e}")
    return jobs


# ============================================================
# SCORING
# ============================================================

def build_prompt(job):
    desc = job['description'][:2500] if job['description'].strip() else "(not available - score based on title, company, location)"
    return f"""Score this job 0-100 for the candidate. Return ONLY the integer.

CANDIDATE:
{CV_SUMMARY}

JOB:
Title: {job['title']}
Location: {job['location']}
Description: {desc}

SCORING EXAMPLES (PURE TECHNICAL FOCUS):
- "System Integration Engineer" (Hardware/Software) = 90
- "Test Engineer / Testingenieur" (Automation, Python) = 85
- "Messtechnik / Measurement Engineer" = 85
- "Lab Automation Engineer" (Python, workflow) = 90
- "Electrochemical / Potentiostat Automation Engineer" = 90
- "Automation Engineer / Automatisierungsingenieur" (Cobot) = 80
- "Research Data / FAIR Data / Metadata Engineer" = 80
- "Scientific Software Developer" (Python, workflow) = 85
- "Technical Writer" (Engineering, DIN/ISO) = 75
- "Requirements Engineer" = 70
- "Prozessmanager" in IT or Engineering = 60
- "Berufseinsteiger / Trainee / Hochschulabsolvent / Graduate role" (technical fit) = 85

NOT A FIT (0-25 ONLY, NEVER HIGHER):
- KYC / AML / Compliance / Bankkaufmann / Financial Crime / Sanctions = 0 (NEVER above 0, regardless of title)
- Data Steward / Data Governance / Master Data / SAP Stammdaten / Data Quality = 0 (NEVER above 0)
- Audit / Revision / Risk Management / Regulatory = 5
- Sales / Account Manager / Account Executive = 5
- Full Stack / Backend / Frontend / DevOps = 5
- Senior / Lead / Head of / Director = 0
- Controller / FP&A / Accounting = 15
- UI/UX / Designer = 5
- IT-Systemadministrator / Network Admin = 25
- HR Generalist / Recruiter = 5

RULES:
Software developer roles (Java, C#, React) = 15 max.
Any Senior/Lead/Head/Director title = 0-15.
C1 German required = cap at 40.
B2 German required but NOT English-primary = cap at 65.
More than 3 years experience required = cap at 50.
Low-level manual testing or basic Excel data entry = 20 max.
Entry-level / Berufseinsteiger / Trainee / Hochschulabsolvent roles = boost by +10.
Roles requiring 3+ years experience = cap at 40.
"Mehrjährige Berufserfahrung" or "mindestens 3 Jahre" = cap at 30.
If the title contains "Compliance", "KYC", "AML", "Data Steward", "Master Data", "Stammdaten", "Governance", "Audit", or "Risk" = return 0 immediately, no exceptions.

Answer:"""


def parse_score(text):
    if not text:
        return None
    nums = re.findall(r"\b(\d{1,3})\b", text)
    for n in reversed(nums):
        i = int(n)
        if 0 <= i <= 100:
            return i
    return None


def score_groq(job):
    if not groq_client:
        return None
    for attempt in range(2):
        try:
            r = groq_client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=[{"role": "user", "content": build_prompt(job)}],
                temperature=0.0,
                max_completion_tokens=2048,
                reasoning_effort="low",
            )
            s = parse_score(r.choices[0].message.content)
            if s is not None:
                return s
        except Exception as e:
            msg = str(e)
            if "429" in msg or "rate_limit" in msg:
                wait = 45
                mm = re.search(r"try again in ([\d.]+)s", msg)
                if mm:
                    wait = min(float(mm.group(1)) + 3, 120)
                time.sleep(wait)
            else:
                time.sleep(5)
    return None


def score_gemini(job):
    for model in ["gemini-2.5-flash", "gemini-2.0-flash"]:
        for attempt in range(2):
            try:
                r = gemini_client.models.generate_content(
                    model=model, contents=build_prompt(job),
                )
                s = parse_score(r.text)
                if s is not None:
                    return s
            except Exception as e:
                if "503" in str(e):
                    time.sleep(8)
                    continue
                break
    return None


def rank_and_filter(jobs):
    out = []
    seen = set()
    stats = {"title": 0, "body": 0, "no_strong": 0, "kept": 0}

    for job in jobs:
        title = job["title"].strip()
        if not title or title in seen:
            continue
        seen.add(title)

        tl = title.lower()
        bl = job["description"].lower()
        body_head = bl[:400]

        # 1) hard reject on title (now catches compliance/KYC/data steward)
        if HARD_REJECT_TITLE_RE.search(tl):
            stats["title"] += 1
            continue
        # 2) hard reject on body (empty body does NOT trigger)
        if HARD_REJECT_BODY_RE.search(bl):
            stats["body"] += 1
            continue

        # 3) require at least ONE strong term in title or body_head
        #    (empty descriptions therefore must have a strong term in the title)
        strong_title = sum(1 for p in TIER1_STRONG if p in tl)
        strong_head = sum(1 for p in TIER1_STRONG if p in body_head)
        strong_body = sum(1 for p in TIER1_STRONG if p in bl)

        if strong_title == 0 and strong_head == 0:
            stats["no_strong"] += 1
            continue

        # 4) weak terms only boost, never qualify
        weak_title = sum(1 for p in TIER1_WEAK if p in tl)
        weak_head = sum(1 for p in TIER1_WEAK if p in body_head)
        weak_body = sum(1 for p in TIER1_WEAK if p in bl)

        t2 = sum(1 for p in TIER2 if p in (tl + " " + body_head))
        rank = (
            10 * strong_title + 6 * strong_head + 2 * strong_body
            + 2 * weak_title + 1 * weak_head + 1 * weak_body
            + 1 * t2
        )

        if ENGLISH_PRIMARY_RE.search(bl):
            rank += 5
        if GERMAN_ONLY_RE.search(bl) and not ENGLISH_PRIMARY_RE.search(bl):
            rank -= 3

        if job.get("source") in ("academics_de", "kowi", "euraxess", "jobriver",
                                  "jobs_daheim", "englishjobs", "germantechjobs"):
            rank += 4

        entry_hits = sum(1 for phrase in ENTRY_LEVEL_PHRASES if phrase in bl)
        if entry_hits:
            rank += min(entry_hits * 3, 15)

        if any(k in tl for k in ["junior", "trainee", "absolvent", "einsteiger",
                                  "graduate", "berufseinsteiger", "hochschulabsolvent"]):
            rank += 5

        if MID_LEVEL_PENALTY_RE.search(bl):
            rank -= 5

        stats["kept"] += 1
        out.append((rank, job))

    out.sort(key=lambda x: x[0], reverse=True)
    print(f"Rejected (title): {stats['title']}")
    print(f"Rejected (body): {stats['body']}")
    print(f"Rejected (no STRONG term): {stats['no_strong']}")
    print(f"Surviving: {stats['kept']}")
    return [x[1] for x in out]


def thesis_fit_line(job):
    text = (job["title"] + " " + job["description"]).lower()
    hits = [kw for kw in THESIS_KEYWORDS if kw in text]
    if not hits:
        return ""
    return "🔬 Thesis fit: " + ", ".join(hits[:4])


def send_tg(text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=15,
        )
    except Exception as e:
        print(f"Telegram error: {e}")


# ============================================================
# MAIN
# ============================================================

def main():
    print("=== Fetching (free sources only, DE + AT) ===")
    arbeitnow_raw   = fetch_arbeitnow()
    ba_raw          = fetch_bundesagentur()
    academics_raw   = fetch_academics_de()
    kowi_raw        = fetch_kowi()
    euraxess_raw    = fetch_euraxess()
    wwr_raw         = fetch_weworkremotely()
    remotive_raw    = fetch_remotive()
    berlin_raw      = fetch_berlinstartupjobs()
    jobriver_raw    = fetch_jobriver()
    daheim_raw      = fetch_jobs_daheim()
    englishjobs_raw = fetch_englishjobs()
    germantech_raw  = fetch_germantechjobs()

    arbeitnow_dach = [j for j in arbeitnow_raw if is_dach(j["location"])]

    all_jobs = (
        arbeitnow_dach + ba_raw + academics_raw
        + kowi_raw + euraxess_raw + wwr_raw + remotive_raw
        + berlin_raw + jobriver_raw + daheim_raw
        + englishjobs_raw + germantech_raw
    )

    # Switzerland removed
    all_jobs = [j for j in all_jobs if not is_switzerland(j.get("location", ""))]
    print(f"Total usable: {len(all_jobs)}\n")

    candidates = rank_and_filter(all_jobs)[:MAX_SCORE]
    print(f"\nWill score: {len(candidates)}\n")

    matches = []
    for i, job in enumerate(candidates, 1):
        print(f"[{i}/{len(candidates)}] {job['title']} — {job['location']}")
        pct = score_groq(job)
        if pct is None:
            pct = score_gemini(job)
        if pct is None:
            time.sleep(12)
            continue
        print(f"  {pct}%")
        if pct >= MIN_MATCH:
            matches.append({**job, "pct": pct})
        time.sleep(12)

    matches.sort(key=lambda x: x["pct"], reverse=True)
    print(f"\nMatches: {len(matches)}")

    if not matches:
        send_tg(f"🎯 Job Radar: 0 matches above {MIN_MATCH}% ({len(candidates)} scored).")
        return

    source_label = {
        "arbeitnow": "arbeitnow",
        "bundesagentur": "BA",
        "academics_de": "academics.de",
        "kowi": "KoWi",
        "euraxess": "EURAXESS",
        "weworkremotely": "WWR",
        "remotive": "Remotive",
        "berlinstartupjobs": "BerlinStartupJobs",
        "jobriver": "JOBRIVER",
        "jobs_daheim": "Jobs-Daheim",
        "englishjobs": "EnglishJobs.de",
        "germantechjobs": "GermanTechJobs",
    }

    lines = [f"<b>🎯 Job Radar — {len(matches)} matches</b>"]
    for m in matches:
        line = (
            f"<b>{m['pct']}%</b> — <a href=\"{m['url']}\">{m['title']}</a>\n"
            f"{m['company']} · {m['location']} · {source_label.get(m['source'], m['source'])}"
        )
        fit = thesis_fit_line(m)
        if fit:
            line += f"\n{fit}"
        lines.append(line)
    send_tg("\n\n".join(lines))


if __name__ == "__main__":
    main()
