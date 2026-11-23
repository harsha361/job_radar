import os
import re
import time
import requests
from google import genai
from groq import Groq

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_KEY = os.environ["GEMINI_KEY"]
GROQ_KEY = os.environ.get("GROQ_KEY", "")

# ---------- Hard reject titles ----------
HARD_REJECT_TITLE = [
    "werkstudent", "working student", "praktikant", "praktikum",
    "ausbildung", "auszubildende", "azubi", "duales studium", "dual studium",
    "internship", "intern ",
    "senior", "sr.", "sr ", "lead ", "head of", "director", "vp ", "chief",
    "principal", "staff ", "managing director", "geschäftsführer", "leitung",
    "führungskraft", "teamleiter", "teamleiterin", "projektleiter",
    "developer", "entwickler", "software engineer", "full stack", "full-stack",
    "fullstack", "backend", "back-end", "back end", "frontend", "front-end",
    "front end", "devops", "site reliability", "cloud engineer",
    "mobile developer", "ios developer", "android developer",
    "data engineer", "machine learning", "ml engineer", "ml ops",
    "ai engineer", "platform engineer", "infrastructure engineer",
    "engineering manager", "product manager", "program manager",
    "account manager", "account executive", "sales manager",
    "marketing manager", "hr manager", "it manager", "office manager",
    "backoffice manager", "supplier development", "lieferantenmanager",
    "sales engineer", "vertriebsingenieur", "außendienst", "aussendienst",
    "controller", "fp&a", "accounting", "buchhaltung", "bilanzbuchhalter",
    "ui/ux", "ui designer", "ux designer", "designer", "grafiker",
    "iot", "embedded", "sentinel", "quality inspector",
    "callcenter", "call center", "telefonist",
    "pflege", "nursing", "krankenpflege",
    "gastronomie", "restaurant", "hotel", "kellner", "koch", "küche",
]

HARD_REJECT_BODY = [
    "c1 ", "c2 ", "verhandlungssicher", "muttersprache",
    "fließend deutsch", "fliessend deutsch",
    "native german", "german native", "deutsch als muttersprache",
    "mehrjährige erfahrung", "mindestens 3 jahre", "mindestens 5 jahre",
    "5+ jahre erfahrung", "3+ jahre erfahrung",
    "französisch", "french", "spanisch", "italienisch", "niederländisch",
    "maternity cover", "temporary contract", "befristet auf",
]

# ---------- TIER 1: exact target roles (weight 5) ----------
TIER1_SPECIFIC = [
    "kyc", "know your customer", "compliance", "aml", "anti money laundering",
    "geldwäsche", "geldwaesche", "sanction", "sanktion",
    "due diligence", "sorgfaltspflicht", "regulatory reporting", "meldewesen",
    "regulatorik", "prozessmanager", "prozessmanagement", "prozessanalyse",
    "prozessoptimierung", "process manager", "process management",
    "data steward", "research data", "forschungsdaten", "fair data",
    "data management", "datenmanagement", "metadaten", "metadata",
    "data governance", "data quality", "datenqualität",
    "requirements engineer", "requirements analysis", "anforderungsmanager",
    "technical writer", "technischer redakteur", "technische dokumentation",
    "integration engineer", "systemintegration", "schnittstellenmanager",
]

# ---------- TIER 2: adjacent (weight 2) ----------
TIER2_ADJACENT = [
    "berufseinsteiger", "berufseinstieg", "quereinsteiger", "quereinstieg",
    "absolvent", "junior", "trainee", "graduate",
    "prozess", "requirements", "anforderung",
    "dokumentation", "documentation",
    "reporting", "kpi", "zahlungsabwicklung", "payment",
    "reconciliation", "forderungsmanagement",
    "testing", "validierung", "quality assurance",
    "integration", "schnittstelle", "api",
]

# ---------- TIER 3: generic engineering (weight 1, does not pass alone) ----------
TIER3_GENERIC = [
    "ingenieur", "engineer", "engineering", "finance", "financial",
    "banking", "bank", "qualität", "quality", "testing", "test",
    "digitalisierung", "digitalization", "automatisierung", "automation",
]

POSITIVE_TITLE = [
    "berufseinsteiger", "berufseinstieg", "quereinsteiger", "quereinstieg",
    "absolvent", "junior", "trainee", "graduate",
    "prozessmanager", "prozessmanagement", "projektmanager",
    "compliance", "kyc", "aml", "regulatory", "meldewesen",
    "dokumentation", "technical writer", "technischer redakteur",
    "testingenieur", "test engineer", "integration engineer",
    "data steward", "research data", "datenmanager",
    "ingenieur", "ingenieurwesen", "wirtschaftsingenieur", "maschinenbau",
]

MAX_SCORE = 15
MIN_MATCH = 45

CV_SUMMARY = """
M.Sc. Advanced Industrial Engineering (Wirtschaftsingenieurwesen), TH Rosenheim.
6 years Federal Bank India: KYC, due diligence, payment reconciliation,
compliance controls, requirements analysis, process analysis, reporting,
project coordination, user training.
BAM Berlin thesis: Python, data pipelines, REST APIs, JSON-LD, FAIR data,
metadata, Docker, testing, DIN/ISO documentation.
Languages: English C1, German B2. Work permit Section 18b.
"""

groq_client = Groq(api_key=GROQ_KEY) if GROQ_KEY else None
gemini_client = genai.Client(api_key=GEMINI_KEY)


def fetch_arbeitnow():
    try:
        r = requests.get(
            "https://www.arbeitnow.com/api/job-board-api",
            params={"location": "Germany"}, timeout=30,
        )
        r.raise_for_status()
        return [{
            "title": j.get("title", ""),
            "company": j.get("company_name", ""),
            "location": j.get("location", ""),
            "description": j.get("description", ""),
            "url": j.get("url", ""),
        } for j in r.json().get("data", [])]
    except Exception as e:
        print(f"Arbeitnow error: {e}")
        return []


def fetch_bundesagentur():
    headers = {"X-API-Key": "jobboerse-jobsuche"}
    queries = ["KYC Compliance", "Prozessmanager", "Data Steward",
               "Regulatory Reporting", "Technischer Redakteur"]
    jobs = []
    seen = set()
    for q in queries:
        params = {"was": q, "size": 30, "page": 1, "veroeffentlichtseit": 7}
        try:
            r = requests.get(
                "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs",
                headers=headers, params=params, timeout=30,
            )
            r.raise_for_status()
            for j in (r.json().get("ergebnisse") or r.json().get("ergebnisliste") or []):
                t = j.get("titel") or j.get("beruf", "")
                if t and t not in seen:
                    seen.add(t)
                    jobs.append({
                        "title": t,
                        "company": j.get("arbeitgeber", ""),
                        "location": j.get("arbeitsort", {}).get("ort", "") if isinstance(j.get("arbeitsort"), dict) else "",
                        "description": j.get("beschreibung") or "",
                        "url": f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{j.get('refnr','')}",
                    })
        except Exception as e:
            print(f"BA error ({q}): {e}")
    return jobs


def build_prompt(job):
    return f"""Score this job 0-100 for the candidate. Return ONLY the integer.

CANDIDATE:
{CV_SUMMARY}

JOB:
Title: {job['title']}
Description: {job['description'][:2500]}

EXAMPLES:
- "KYC Analyst" entry-level, English OK = 85
- "Junior Compliance Manager" "Berufseinsteiger willkommen" = 80
- "Data Steward" research institute = 75
- "Technical Writer" engineering = 65
- "Prozessmanager" 3+ years required = 50
- "Integration and Test Engineer" 0-2 years = 55
- "Controller" accounting = 20
- "Full Stack Developer" = 5
- "Senior Engineering Manager" = 0
- "Sales Engineer" = 15
- "UI/UX Designer" = 5
- "Account Executive" = 5
- "Supplier Development Manager" = 15
- "Quality Inspector" factory = 25

RULES:
Software developer/engineer roles: 5-15 max.
Any title with Senior/Lead/Head/Director/Manager (except Prozessmanager/Projektmanager/Product Owner): 0-15.
C1 German required: cap 40.
More than 2 years experience required: cap 50.
Low-level backoffice without compliance/process content: 15-30.
French/Spanish/Italian/Dutch required: 0-10.

Answer:"""


def parse_score(text):
    if not text:
        return None
    m = re.search(r"\b(\d{1,3})\b", text.strip())
    if m:
        n = int(m.group(1))
        if 0 <= n <= 100:
            return n
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
            print(f"    parse failed: {r.choices[0].message.content[:80]!r}")
        except Exception as e:
            msg = str(e)
            if "429" in msg or "rate_limit" in msg:
                wait = 45
                mm = re.search(r"try again in ([\d.]+)s", msg)
                if mm:
                    wait = min(float(mm.group(1)) + 3, 120)
                print(f"    rate limit, wait {wait:.0f}s")
                time.sleep(wait)
            else:
                print(f"    groq error: {e}")
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
    """Tiered ranking: TIER1 >> TIER2 > TIER3. Requires TIER1 or TIER2 to pass."""
    out = []
    seen = set()
    rejected = 0
    for job in jobs:
        title = job["title"].strip()
        if not title or title in seen:
            continue
        seen.add(title)
        tl = title.lower()
        bl = job["description"].lower()
        blob = tl + " " + bl

        if any(x in tl for x in HARD_REJECT_TITLE):
            rejected += 1
            continue
        if any(x in bl for x in HARD_REJECT_BODY):
            rejected += 1
            continue

        t1 = sum(1 for p in TIER1_SPECIFIC if p in blob)
        t2 = sum(1 for p in TIER2_ADJACENT if p in blob)
        t3 = sum(1 for p in TIER3_GENERIC if p in blob)
        title_boost = 2 * sum(1 for p in POSITIVE_TITLE if p in tl)

        # Must have at least one TIER1 or TIER2 hit
        if t1 == 0 and t2 == 0:
            rejected += 1
            continue

        rank = 5 * t1 + 2 * t2 + 1 * t3 + title_boost
        out.append((rank, job))

    out.sort(key=lambda x: x[0], reverse=True)
    print(f"Rejected: {rejected}, Surviving: {len(out)}")
    return [x[1] for x in out]


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
    jobs = fetch_arbeitnow() + fetch_bundesagentur()
    print(f"Total fetched: {len(jobs)}")

    candidates = rank_and_filter(jobs)[:MAX_SCORE]
    print(f"Will score: {len(candidates)}\n")

    matches = []
    for i, job in enumerate(candidates, 1):
        print(f"[{i}/{len(candidates)}] {job['title']}")
        pct = score_groq(job)
        if pct is None:
            print(f"  fallback to gemini")
            pct = score_gemini(job)
        if pct is None:
            print(f"  skipped")
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

    lines = [f"<b>🎯 Job Radar — {len(matches)} matches</b>"]
    for m in matches:
        lines.append(
            f"<b>{m['pct']}%</b> — <a href=\"{m['url']}\">{m['title']}</a>\n"
            f"{m['company']} · {m['location']}"
        )
    send_tg("\n\n".join(lines))


if __name__ == "__main__":
    main()
