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

DACH_CITIES = [
    "germany", "deutschland", "berlin", "münchen", "munich", "hamburg",
    "frankfurt", "köln", "cologne", "düsseldorf", "dusseldorf", "stuttgart",
    "leipzig", "dresden", "hannover", "nürnberg", "nuremberg", "bremen",
    "essen", "dortmund", "bonn", "mainz", "wiesbaden", "karlsruhe",
    "mannheim", "augsburg", "aachen", "münster", "muenster", "freiburg",
    "kiel", "rostock", "potsdam", "erfurt", "magdeburg", "saarbrücken",
    "krefeld", "wolfsburg", "ingolstadt", "regensburg", "ulm", "heilbronn",
    "paderborn", "bielefeld", "göttingen", "kassel", "würzburg",
    "verl", "gütersloh", "guetersloh", "espelkamp", "ichtershausen",
    "österreich", "austria", "wien", "vienna", "graz", "linz",
    "salzburg", "innsbruck", "klagenfurt",
]

def is_dach(location):
    loc = (location or "").lower()
    return any(c in loc for c in DACH_CITIES)

HARD_REJECT_TITLE_RE = re.compile(
    r"\b("
    r"werkstudent|working.?student|praktikant|praktikum|ausbildung|"
    r"auszubildende|azubi|dual(es)? studium|internship|intern|"
    r"senior|sr|lead|head.?of|director|vp|chief|principal|staff|"
    r"managing.?director|geschäftsführer|leitung|führungskraft|"
    r"teamleiter|teamleiterin|projektleiter|"
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
    r"embedded|sentinel|quality.?inspector|optical|thermal|"
    r"vehicle|forward.?deployed|"
    r"customer.?success|customer.?service|kundendienst|"
    r"kundenbetreuer|kundenberater|call.?center|telefonist|"
    r"systemadministrator|system.?administrator|it.?systemadmin|"
    r"generalist|generalistin|recruiter|recruiting|"
    r"pflege|nursing|krankenpflege|"
    r"gastronomie|restaurant|hotel|kellner|koch|küche|"
    r"kyc|aml|geldwäsche|geldwaesche|"
    r"compliance|compliance.?manager|compliance.?analyst|"
    r"bankkaufmann|bankkauffrau|banking.?operations|"
    r"data.?steward|data.?governance|data.?quality|"
    r"master.?data|stammdaten|stammdatenmanagement|"
    r"sanctions|transaction.?monitoring|financial.?crime|"
    r"audit\w*|revision\w*|datenschutz\w*|data.?protection|"
    r"risk.?management|risikomanagement|regulator\w*|"
    r"it.?systemintegrator|it.?systemintegration|fachinformatiker|"
    r"no.?code|low.?code|saas|crm.?manager|it.?support|"
    r"it.?workplace|netzwerk|firewall|"
    r"schweißer|schlosser|elektriker|elektroniker|elektromonteur|"
    r"industrieelektroniker|monteur|montagemitarbeiter|montagefachkraft|"
    r"produktionsmitarbeiter|produktionsfachkraft|fertigungsmitarbeiter|"
    r"zerspanungsmechaniker|zerspanungsprogrammierer|fräser|cnc|"
    r"industriemechaniker|anlagenmechaniker|servicetechniker|"
    r"chemikant|mikrotechnologe|werkzeugmechaniker|schreiner|"
    r"konstrukteur|konstruktionsingenieur|bim|revit|technischer.?zeichner|"
    r"trafomonteur|verdrahter|elektromaschinenmonteur|"
    r"teamassistenz|personalsachbearbeiter|speditionskaufmann|"
    r"lagerlogistik|kommissionierer|ressourcenplaner|terminplaner|"
    r"logistikplaner|kaufm\w*"
    r")\b", re.IGNORECASE)

EXPERIENCE_HARD_RE = re.compile(
    r"("
    r"(?:mindestens|mind\.?|min\.?|minimum|wenigstens)\s*"
    r"(?:\d+|zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn)\s*"
    r"j(?:ahre|ahren|ahr)\b|"
    r"\bab\s+(?:\d+|zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn)\s+"
    r"j(?:ahre|ahren|ahr)\b|"
    r"(?:über|ueber|mehr\s+als)\s+\d+\s+j(?:ahre|ahren|ahr)\b|"
    r"\d+\+?\s*j(?:ahre|ahren|ahr)\s+(?:berufs)?erfahrung\b|"
    r"\d+\s*-?\s*jährige?\s+(?:berufs)?erfahrung\b|"
    r"(?:zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn)\s*-?\s*jährige?\s+"
    r"(?:berufs)?erfahrung\b|"
    r"\d+\s*(?:-|–|bis)\s*\d+\s*j(?:ahre|ahren|ahr)\s+(?:berufs)?erfahrung\b|"
    r"(?:berufs)?erfahrung\s*:?\s*\d+\s*(?:-|–|bis)?\s*\d*\s*jahre?\b|"
    r"sie\s+(?:haben|verfügen\s+über|verfuegen\s+ueber|bringen)\s+"
    r".{0,20}?\d+\s*j(?:ahre|ahren|ahr)\b|"
    r"einschlägige\s+(?:berufs)?erfahrung|"
    r"einschlaegige\s+(?:berufs)?erfahrung|"
    r"(?:berufs)?erfahrung\s+(?:erforderlich|vorausgesetzt|zwingend|notwendig|"
    r"ist\s+voraussetzung|wird\s+erwartet)|"
    r"(?:berufs)?erfahrung\s+wird\s+vorausgesetzt|"
    r"(?:mehrjährige|mehrjaehrige|langjährige|langjaehrige|"
    r"fundierte|ausgeprägte|ausgepraegte|nachweisbare)\s+(?:berufs)?erfahrung|"
    r"mehrere\s+jahre\s+(?:berufs)?erfahrung|"
    r"mehrere\s+jahre\s+erfahrung|"
    r"langjährige\s+erfahrung"
    r")", re.IGNORECASE)

HARD_REJECT_BODY_RE = re.compile(
    r"("
    r"\bc1\b|\bc2\b|muttersprache|"
    r"fließend.?deutsch|fliessend.?deutsch|"
    r"native.?german|deutsch.?als.?muttersprache|"
    r"französisch|french|spanisch|italienisch|niederländisch|"
    r"maternity.?cover|temporary.?contract|befristet.?auf|"
    r"kyc|aml|geldwäsche|compliance|bankkaufmann|bankkauffrau|"
    r"data.?steward|master.?data|stammdaten|"
    r"hochspannung|freileitung|schaltanlage"
    r")", re.IGNORECASE)

ANCHOR_TERMS = [
    "pyironflow", "electrochemical", "electrochemistry", "elektrochemie",
    "elektrochemisch", "potentiostat", "palmsens", "emstat",
    "ender3", "ender 3", "positioniersystem",
    "lab automation", "laboratory automation", "laborautomation",
    "laborautomatisierung", "laborinformatik", "lab informatics",
    "material acceleration", "self-driving lab", "self driving lab",
    "autonomous lab", "autonomes labor",
    "json-ld", "jsonld", "prov-o", "provo", "opmw", "ro-crate",
    "provenance", "provenienz", "fair data", "fair-data",
    "research data", "forschungsdaten", "forschungsdatenmanagement",
    "messsystem", "mess- und positioniersystem", "messsystemanalyse",
    "msa", "gage r&r", "gr&r", "kalibrierung", "kalibrierroutine",
    "prüfmittel", "pruefmittel", "prüfmittelmanagement",
    "prüfmittelüberwachung", "prüfstand", "teststand", "prüflabor",
    "messtechnik", "messtechniker", "messingenieur", "measurement engineer",
    "measurement system", "sensorintegration", "sensor integration",
    "schnittstellentest", "interface testing",
    "cobot", "kollaborativer roboter", "collaborative robot",
    "omron", "tm5", "tmflow", "imbus", "imb-io",
    "induktive wegaufnehmer", "induktiver wegaufnehmer", "inductive probe",
    "wellenmessung", "shaft measurement",
    "testingenieur", "test engineer", "testautomatisierung",
    "test automation", "test bench", "prüfstandsentwickler",
    "technischer redakteur", "technical writer",
    "technische dokumentation", "technical documentation",
]

DOMAIN_BOOST_TERMS = [
    "automatisierung", "automation", "automatisierungsingenieur",
    "systemintegration", "system integration", "systemintegrator",
    "inbetriebnahme", "commissioning", "robotik", "robotics", "roboter",
    "qualitätssicherung", "quality assurance", "qualitätsmanagement",
    "validierung", "validation", "prüfbericht", "prüfplan",
    "sensorik", "sensor", "hardware", "interface", "schnittstelle",
    "din iso", "din en iso", "iso 9001", "iatf", "vda",
    "python", "matlab", "labview", "vba",
    "api", "rest", "docker", "git", "sql", "linux",
    "anforderungsanalyse", "requirements engineer", "anforderungsmanagement",
    "messsoftware", "datenerfassung", "datenauswertung",
]

WEAK_TERMS = ["prozess", "process", "projekt", "project",
              "dokumentation", "documentation", "team", "analytisch"]

ENTRY_LEVEL_PHRASES = [
    "berufseinsteiger", "berufseinstieg", "einstiegsposition",
    "berufsanfänger", "berufsanfaenger", "hochschulabsolvent",
    "absolvent", "trainee", "graduate", "entry level", "entry-level",
    "young professional", "einsteiger", "junior", "juniorstelle",
    "quereinsteiger", "quereinstieg",
    "keine berufserfahrung", "ohne berufserfahrung",
    "keine vorkenntnisse", "ohne vorkenntnisse",
    "erfahrung ist egal", "erfahrung egal",
    "berufserfahrung nicht erforderlich", "erfahrung nicht erforderlich",
    "berufserfahrung nicht zwingend", "erfahrung nicht zwingend",
    "berufserfahrung von vorteil", "erfahrung von vorteil",
    "erste berufserfahrung", "erste erfahrung",
    "erste berührungspunkte", "erste kenntnisse",
    "bereitschaft zur einarbeitung", "einarbeitung",
    "0-1 jahre", "0-2 jahre", "0-3 jahre", "1-2 jahre", "1-3 jahre",
    "bis zu 2 jahre", "bis zu 3 jahre", "maximal 2 jahre", "maximal 3 jahre",
    "auch berufseinsteiger", "berufseinsteiger willkommen",
    "berufseinsteiger sind auch willkommen",
    "auch ohne berufserfahrung", "auch quereinsteiger",
]

ENTRY_TITLE_TERMS = ["junior", "trainee", "absolvent", "einsteiger",
                     "graduate", "berufseinsteiger", "hochschulabsolvent",
                     "entry level", "entry-level", "young professional",
                     "quereinsteiger"]

MAX_SCORE = 15
MIN_MATCH = 55
ENTRY_RESERVE_NON_ENTRY = 4

CV_SUMMARY = """
M.Sc. Advanced Industrial Engineering (Grade 1.9), TH Rosenheim. B.Tech Mechanical Engineering.

BAM Berlin Master's Thesis: "Visual Programming Workflow for Electrochemical Automation"
- Node-based automation workflow in PyironFlow (Python) for electrochemical measurements.
- Integrated Ender3 positioning unit with PalmSens potentiostat via serial communication and REST APIs.
- Calibration and validation: positional accuracy, timing, data integrity.
- FAIR data: JSON-LD metadata, PROV-O / OPMW provenance, RO-Crate.
- Docker / Git for reproducible test environments.

Cobot Project (Omron TM5-900, TH Rosenheim):
- Automated shaft measurement: inductive probes, IMBus I/O modules, digital I/O.
- Custom workpiece carriers and gripper jaws (additive manufacturing).
- Calibration routine every 100 parts / 1 hour.

Professional Experience: 6 years Federal Bank — requirements analysis, project coordination, system rollouts, regulated documentation.

Languages: English C1, German B2. Work permit Section 18b.
"""

groq_client = Groq(api_key=GROQ_KEY) if GROQ_KEY else None
gemini_client = genai.Client(api_key=GEMINI_KEY)

def fetch_arbeitnow():
    try:
        r = requests.get("https://www.arbeitnow.com/api/job-board-api", timeout=30)
        r.raise_for_status()
        return [{"title": j.get("title", ""), "company": j.get("company_name", ""),
                 "location": j.get("location", ""), "description": j.get("description", ""),
                 "url": j.get("url", ""), "source": "arbeitnow"}
                for j in r.json().get("data", [])]
    except Exception as e:
        print(f"Arbeitnow error: {e}"); return []

def fetch_bundesagentur():
    headers = {"X-API-Key": "jobboerse-jobsuche"}
    queries = [
        "Laborautomation", "Laborautomatisierung", "Automatisierungsingenieur",
        "Prüfmittelentwickler", "Prüfmittelplaner", "Prüfingenieur",
        "Testingenieur", "Messtechnik Ingenieur", "Messtechniker",
        "Messingenieur", "Kalibriertechniker", "Kalibrieringenieur",
        "Systemintegrator", "Inbetriebnahmeingenieur", "Prüfstandsentwickler",
        "Laborinformatiker", "Technischer Redakteur",
        "Lab Automation Engineer", "Laboratory Automation Engineer",
        "Test Engineer", "Test Automation Engineer", "Measurement Engineer",
        "Calibration Engineer", "System Integration Engineer",
        "Scientific Software Developer", "Research Data Engineer",
        "Requirements Engineer", "PyironFlow", "electrochemical automation",
        "potentiostat", "FAIR data", "JSON-LD", "PROV-O", "metadata",
        "cobot", "collaborative robot", "Omron TM5", "IMBus", "Wellenmessung",
    ]
    jobs, seen = [], set()
    for q in queries:
        params = {"was": q, "size": 40, "page": 1, "veroeffentlichtseit": 14}
        try:
            r = requests.get(
                "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs",
                headers=headers, params=params, timeout=30)
            if r.status_code != 200:
                continue
            data = r.json()
            results = data.get("ergebnisliste") or data.get("ergebnisse") or []
            print(f"  BA '{q}': {len(results)}")
            for j in results:
                if not isinstance(j, dict):
                    continue
                t = j.get("stellenangebotsTitel") or j.get("titel") or j.get("beruf") or ""
                if not isinstance(t, str) or not t.strip() or t.strip() in seen:
                    continue
                seen.add(t.strip())
                loc = ""
                lok = j.get("stellenlokationen")
                if isinstance(lok, list) and lok and isinstance(lok[0], dict):
                    addr = lok[0].get("adresse", {})
                    if isinstance(addr, dict):
                        loc = addr.get("ort", "") or ""
                desc = j.get("beschreibung") or ""
                jobs.append({
                    "title": t.strip(), "company": j.get("firma") or j.get("arbeitgeber") or "",
                    "location": loc or "Germany", "description": desc if isinstance(desc, str) else "",
                    "url": f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{j.get('referenznummer','')}",
                    "source": "bundesagentur"})
        except Exception as e:
            print(f"  BA '{q}' exception: {e}")
    return jobs

def _html_job_fetch(base_url, queries, link_pattern, source_name,
                    default_location="Germany"):
    jobs, seen = [], set()
    headers = {"User-Agent": "Mozilla/5.0 (compatible; JobRadar/1.0)"}
    for q in queries:
        try:
            r = requests.get(f"{base_url}{quote(q)}", headers=headers, timeout=20)
            if r.status_code != 200:
                print(f"  {source_name} '{q}': HTTP {r.status_code}")
                continue
            hits = 0
            for m in re.finditer(link_pattern, r.text, re.DOTALL):
                path, inner = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
                if not inner or len(inner) < 5 or len(inner) > 140:
                    continue
                key = (path, inner)
                if key in seen:
                    continue
                seen.add(key)
                base = "/".join(base_url.split("/")[:3])
                url = path if path.startswith("http") else base + path
                jobs.append({"title": inner, "company": source_name,
                             "location": default_location, "description": "",
                             "url": url, "source": source_name})
                hits += 1
            print(f"  {source_name} '{q}': {hits}")
        except Exception as e:
            print(f"  {source_name} '{q}' exception: {e}")
    return jobs

def fetch_jobware():
    return _html_job_fetch(
        "https://www.jobware.de/jobs/?q=",
        ["Messtechnik", "Laborautomation", "Prüfmittel", "Testingenieur",
         "Automatisierung", "Kalibrierung", "Measurement Engineer",
         "Test Engineer", "Laboratory Automation"],
        r'href="(/job/[^"#?]+|/stellenangebote/[^"#?]+)"[^>]*>(.*?)</a>', "jobware")

def build_prompt(job):
    desc = job['description'][:2500] if job['description'].strip() else \
        "(not available — score based on title, company, location only)"
    return f"""You are a BRUTAL, STRICT technical recruiter. Do not be generous. Do not assume.
Read the FULL description. If the work is actually sales, support, or admin, score 0 regardless of title.

CANDIDATE:
{CV_SUMMARY}

JOB:
Title: {job['title']}
Location: {job['location']}
Description: {desc}

STRONG FIT (score 80-95):
- Lab automation / Laboratory automation engineer (Python, workflow)
- Electrochemical / potentiostat automation
- Measurement Engineer / Messtechniker / Messingenieur
- Test Engineer / Testingenieur / Prüfstandstechniker
- Calibration Engineer / Kalibriertechniker
- System Integration Engineer (hardware/software, sensor, measurement)
- Scientific Software Developer (workflow, provenance, Python)
- Technical Writer / Technischer Redakteur
- Research Data Engineer (FAIR data, metadata, Python)
- Requirements Engineer

HARD ZERO (score 0, never above):
- If the description mentions >50% of the time: sales, customer support, answering calls, scheduling, admin work.
- KYC / AML / Compliance / Bankkaufmann / Financial Crime / Sanctions
- Data Steward / Data Governance / Master Data / SAP Stammdaten
- IT-Systemintegrator / Fachinformatiker / No-Code / Low-Code / SaaS / CRM
- Sales / Account Manager / Account Executive / Vertrieb
- Full Stack / Backend / Frontend / DevOps / Cloud Engineer
- Senior / Lead / Head of / Director / Principal
- Audit / Risk Management / Regulatory Affairs

LOW FIT (score 5-20):
- Controller / FP&A / Accounting
- UI/UX / Designer
- IT-Systemadministrator / Network Admin
- HR Generalist / Recruiter
- Trade roles (Schweißer, Elektriker, Monteur, Zerspaner, CNC)

RULES:
- Explicit C1 German required = cap at 40.
- "Verhandlungssichere Deutschkenntnisse" = cap at 55.
- B2 German required, no English-primary = cap at 65.
- More than 3 years experience required = cap at 40.
- "Mehrjährige Berufserfahrung" or "mindestens 3 Jahre" = cap at 25.
- "Berufserfahrung erforderlich" / "nachweisbare Erfahrung" = cap at 30.
- If the description is empty, cap at 65.

Answer with ONLY the integer. No explanation.
"""

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
    
    # We use the models explicitly listed in your screenshot
    models_to_try = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    
    for model in models_to_try:
        for attempt in range(2):
            try:
                r = groq_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": build_prompt(job)}],
                    temperature=0.0, max_completion_tokens=2048,
                    reasoning_effort="low")
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
                    print(f"  Groq {model} error: {e}")
                    time.sleep(2)
    return None

def score_gemini(job):
    for model in ["gemini-2.5-flash", "gemini-2.0-flash"]:
        for attempt in range(2):
            try:
                r = gemini_client.models.generate_content(
                    model=model, contents=build_prompt(job))
                s = parse_score(r.text)
                if s is not None:
                    return s
            except Exception as e:
                if "503" in str(e):
                    time.sleep(8); continue
                break
    return None

def find_anchor(tl, bl):
    for term in ANCHOR_TERMS:
        if term in tl or term in bl:
            return term
    return None

def rank_and_filter(jobs):
    entry_pool, other_pool = [], []
    seen = set()
    stats = {"title": 0, "experience": 0, "body": 0,
             "no_anchor": 0, "kept": 0, "entry": 0, "other": 0}

    for job in jobs:
        title = job["title"].strip()
        if not title or title in seen:
            continue
        seen.add(title)

        tl = title.lower()
        bl = (job.get("description") or "").lower()
        body_head = bl[:500]

        if HARD_REJECT_TITLE_RE.search(tl):
            stats["title"] += 1; continue
        if EXPERIENCE_HARD_RE.search(bl):
            stats["experience"] += 1; continue
        if HARD_REJECT_BODY_RE.search(bl):
            stats["body"] += 1; continue

        anchor = find_anchor(tl, body_head) or find_anchor("", bl)
        if anchor is None:
            stats["no_anchor"] += 1; continue

        domain_hits = sum(1 for p in DOMAIN_BOOST_TERMS if p in (tl + " " + bl))
        weak_hits = sum(1 for p in WEAK_TERMS if p in (tl + " " + body_head))
        anchor_in_title = 1 if find_anchor(tl, "") else 0

        rank = 10 * anchor_in_title + 2 * domain_hits + 1 * weak_hits

        if job.get("source") in ("academics_de", "kowi", "euraxess",
                                 "jobriver", "jobs_daheim", "englishjobs",
                                 "germantechjobs", "jobvector", "jobware",
                                 "research_in_germany", "wila_bonn", "jooble",
                                 "adzuna", "google_jobs"):
            rank += 4

        entry_hits = sum(1 for p in ENTRY_LEVEL_PHRASES if p in bl)
        is_entry = entry_hits > 0 or any(k in tl for k in ENTRY_TITLE_TERMS)
        if entry_hits:
            rank += min(entry_hits * 5, 40)
        if any(k in tl for k in ENTRY_TITLE_TERMS):
            rank += 25

        job["anchor"] = anchor
        job["is_entry"] = is_entry
        stats["kept"] += 1
        if is_entry:
            stats["entry"] += 1
            entry_pool.append((rank, job))
        else:
            stats["other"] += 1
            other_pool.append((rank, job))

    entry_pool.sort(key=lambda x: x[0], reverse=True)
    other_pool.sort(key=lambda x: x[0], reverse=True)

    cap_entry = max(MAX_SCORE - ENTRY_RESERVE_NON_ENTRY, 1)
    take_entry = entry_pool[:cap_entry]
    take_other = other_pool[:MAX_SCORE - len(take_entry)]
    selected = take_entry + take_other
    selected.sort(key=lambda x: x[0], reverse=True)

    print(f"Rejected (title): {stats['title']}")
    print(f"Rejected (experience): {stats['experience']}")
    print(f"Rejected (body/domain): {stats['body']}")
    print(f"Rejected (no ANCHOR): {stats['no_anchor']}")
    print(f"Surviving: {stats['kept']} (entry: {stats['entry']}, other: {stats['other']})")
    print(f"Selected: {len(selected)} (entry: {len(take_entry)}, other: {len(take_other)})")
    return [j for _, j in selected]

def send_tg(text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True}, timeout=15)
    except Exception as e:
        print(f"Telegram error: {e}")

def main():
    print("=== Fetching ===")
    sources = [
        ("arbeitnow", fetch_arbeitnow),
        ("bundesagentur", fetch_bundesagentur),
        ("jobware", fetch_jobware),
    ]

    all_jobs = []
    for name, fn in sources:
        try:
            batch = fn()
            if name == "arbeitnow":
                batch = [j for j in batch if is_dach(j["location"])]
            all_jobs.extend(batch)
        except Exception as e:
            print(f"  {name} fatal: {e}")

    print(f"Total usable: {len(all_jobs)}\n")

    candidates = rank_and_filter(all_jobs)
    print(f"\nWill score: {len(candidates)}\n")

    matches = []
    for i, job in enumerate(candidates, 1):
        entry_tag = "🌱" if job.get("is_entry") else "  "
        print(f"[{i}/{len(candidates)}] {entry_tag} {job['title']} — "
              f"{job['location']} (anchor: {job.get('anchor','-')})")
        pct = score_groq(job)
        if pct is None:
            pct = score_gemini(job)
        if pct is None:
            time.sleep(12); continue
        print(f"  {pct}%")
        if pct >= MIN_MATCH:
            matches.append({**job, "pct": pct})
        time.sleep(12)

    matches.sort(key=lambda x: (x.get("is_entry", False), x["pct"]), reverse=True)
    print(f"\nMatches: {len(matches)}")

    if not matches:
        send_tg(f"🎯 Job Radar: 0 matches above {MIN_MATCH}% "
                f"({len(candidates)} scored)")
        return

    source_label = {
        "arbeitnow": "arbeitnow", "bundesagentur": "BA",
        "jobware": "Jobware",
    }

    lines = [f"<b>🎯 Job Radar — {len(matches)} matches</b>"]
    for m in matches:
        badge = "🌱 " if m.get("is_entry") else ""
        line = (f"<b>{m['pct']}%</b> {badge}— <a href=\"{m['url']}\">{m['title']}</a>\n"
                f"{m['company']} · {m['location']} · "
                f"{source_label.get(m['source'], m['source'])}\n"
                f"🎯 Anchor: <i>{m.get('anchor','-')}</i>")
        lines.append(line)
    send_tg("\n\n".join(lines))

if __name__ == "__main__":
    main()
