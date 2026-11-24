import os
import re
import time
import requests
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
    "verl", "gütersloh", "guetersloh", "espelkamp",
    "österreich", "austria", "wien", "vienna", "graz", "linz",
    "salzburg", "innsbruck", "klagenfurt",
]

def is_dach(location):
    loc = (location or "").lower()
    return any(c in loc for c in DACH_CITIES)

# ---------- Hard reject titles ----------
HARD_REJECT_TITLE_RE = re.compile(
    r"\b("
    r"werkstudent|working.?student|praktikant|praktikum|ausbildung|"
    r"auszubildende|azubi|dual(es)? studium|internship|intern|"
    r"senior|sr|lead|head.?of|director|vp|chief|principal|staff|"
    r"managing.?director|geschäftsführer|leitung|führungskraft|"
    r"teamleiter|teamleiterin|projektleiter|"
    r"experte|spezialist|"
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
    r"gastronomie|restaurant|hotel|kellner|koch|küche"
    r")\b",
    re.IGNORECASE,
)

HARD_REJECT_BODY_RE = re.compile(
    r"\b("
    r"c1|c2|verhandlungssicher|muttersprache|"
    r"fließend.?deutsch|fliessend.?deutsch|"
    r"native.?german|deutsch.?als.?muttersprache|"
    r"mehrjährige.?erfahrung|mehrjaehrige.?erfahrung|"
    r"mindestens.?\d.?jahre|"
    r"französisch|french|spanisch|italienisch|niederländisch|"
    r"maternity.?cover|temporary.?contract|befristet.?auf|"
    r"kyc|aml|geldwäsche|compliance|bankkaufmann|bankkauffrau|"
    r"data steward|master data|stammdaten"
    r")\b",
    re.IGNORECASE,
)

# ---------- TIER 1: Pure Technical Engineering + Thesis + Research data ----------
TIER1 = [
    # Hardware/Software Integration (existing)
    "systemintegration", "system integration", "system engineer", "systems engineer",
    "schnittstelle", "schnittstellen", "interface", "hardware",
    "messtechnik", "measurement", "sensor", "prüfstand", "teststand",
    # Testing (existing)
    "test engineer", "testingenieur", "test automation", "software tester",
    "testautomatisierung", "prüfmittel", "qualitätssicherung",
    # Automation / Robotics (existing)
    "automatisierung", "automation", "cobot", "robotics", "roboter",
    # Tech Writing / Documentation (existing)
    "technischer redakteur", "technical writer", "technische dokumentation",
    "technical documentation", "din iso", "din en iso",
    # Engineering / Python (existing)
    "industrialingenieur", "industrial engineer", "wirtschaftsingenieur", "wirtschaftsingenieurwesen",
    "python", "api", "rest",
    # --- NEW: thesis-specific technical terms ---
    "json-ld", "jsonld", "json ld",
    "docker", "git",
    "measurement system", "positioning system", "positioning",
    "hardware-software", "hardware software", "hardware/software",
    "omron", "tm5", "tm5-900",
    "sensor integration",
    "serial communication", "serial interface",
    "rest api", "restapi",
    "data pipeline", "datenpipeline",
    "metadata", "metadaten",
    # --- NEW: research-data lane ---
    "fair data", "fair-data", "research data", "forschungsdaten",
    "forschungsdatenmanagement",
]

# ---------- TIER 2: Soft signals ----------
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

CV_SUMMARY = """
M.Sc. Advanced Industrial Engineering (Wirtschaftsingenieurwesen, Grade 1.9), TH Rosenheim.
B.Tech Mechanical Engineering.

BAM Berlin Master's Thesis (Technical):
Developed a modular Python application to automate a measurement and positioning system.
Integrated hardware (sensors, measurement devices) with software via REST APIs and serial communication.
Built data pipelines, handled JSON-LD metadata, and used Docker/Git for testing and documentation.

Cobot Project:
Programmed an Omron TM5-900 collaborative robot, integrating sensors, pneumatics, and digital I/O.

Professional Experience:
6 years at Federal Bank. Focused on requirements analysis, project coordination, and system rollouts.

Languages: English C1, German B2. Work permit Section 18b.
"""

# ---------- NEW: thesis keywords for Telegram fit line ----------
THESIS_KEYWORDS = [
    "json-ld", "jsonld", "docker", "git", "python",
    "rest api", "rest", "serial", "measurement", "messtechnik",
    "positioning", "sensor", "hardware", "cobot", "omron", "tm5",
    "data pipeline", "metadata", "api", "interface", "schnittstelle",
]

# ---------- NEW: language-primary detection ----------
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
        # --- Existing German queries (kept) ---
        "Systemintegration", "Testingenieur", "Messtechnik",
        "Automatisierung Ingenieur", "Technischer Redakteur",
        # --- NEW English queries ---
        "System Integration Engineer", "Test Engineer", "Automation Engineer",
        "Research Data", "FAIR data", "Metadata", "Python Engineer",
        "Requirements Engineer", "Hardware Software Integration",
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
    """NEW: best-effort scrape of academics.de for research-data / FAIR roles."""
    jobs = []
    seen_urls = set()
    queries = ["FAIR data", "research data management", "metadata", "Python data", "data engineer"]
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
                # only keep detail pages (slug ends with numeric id)
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
- "Automation Engineer / Automatisierungsingenieur" (Cobot) = 80
- "Research Data / FAIR Data / Metadata Engineer" = 80
- "Technical Writer" (Engineering, DIN/ISO) = 75
- "Requirements Engineer" = 70
- "Prozessmanager" in IT or Engineering = 60

NOT A FIT (0-25 ONLY, NEVER HIGHER):
- KYC / AML / Compliance / Bankkaufmann = 0 (Candidate is pivoting away)
- Data Steward / Master Data / SAP Stammdaten = 10 (Not technical enough)
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
    stats = {"title": 0, "body": 0, "no_tier1": 0, "kept": 0}

    for job in jobs:
        title = job["title"].strip()
        if not title or title in seen:
            continue
        seen.add(title)

        tl = title.lower()
        bl = job["description"].lower()
        body_head = bl[:400]

        if HARD_REJECT_TITLE_RE.search(tl):
            stats["title"] += 1
            continue
        if HARD_REJECT_BODY_RE.search(bl):
            stats["body"] += 1
            continue

        t1_title = sum(1 for p in TIER1 if p in tl)
        t1_head = sum(1 for p in TIER1 if p in body_head)
        t1_body = sum(1 for p in TIER1 if p in bl)
        if t1_title == 0 and t1_head == 0:
            stats["no_tier1"] += 1
            continue

        t2 = sum(1 for p in TIER2 if p in (tl + " " + body_head))
        rank = 10 * t1_title + 3 * t1_head + 1 * t1_body + 1 * t2

        # NEW: English-primary boost / German-only penalty
        if ENGLISH_PRIMARY_RE.search(bl):
            rank += 5
        if GERMAN_ONLY_RE.search(bl) and not ENGLISH_PRIMARY_RE.search(bl):
            rank -= 3
        # NEW: research-source boost
        if job.get("source") == "academics_de":
            rank += 4

        stats["kept"] += 1
        out.append((rank, job))

    out.sort(key=lambda x: x[0], reverse=True)
    print(f"Rejected (title): {stats['title']}")
    print(f"Rejected (body): {stats['body']}")
    print(f"Rejected (no TIER1 in title/lead): {stats['no_tier1']}")
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


def main():
    print("=== Fetching ===")
    arbeitnow_raw = fetch_arbeitnow()
    ba_raw = fetch_bundesagentur()
    academics_raw = fetch_academics_de()  # NEW

    arbeitnow_dach = [j for j in arbeitnow_raw if is_dach(j["location"])]

    all_jobs = arbeitnow_dach + ba_raw + academics_raw
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

    source_label = {"arbeitnow": "arbeitnow", "bundesagentur": "BA", "academics_de": "academics.de"}
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
