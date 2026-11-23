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

# ---------- HARD REJECT: titles ----------
HARD_REJECT_TITLE = [
    # Student / intern
    "werkstudent", "working student", "praktikant", "praktikum",
    "ausbildung", "auszubildende", "azubi", "duales studium", "dual studium",
    "internship", "intern ",
    # Senior / lead
    "senior", "sr.", "sr ", "lead ", "head of", "director", "vp ", "chief",
    "principal", "staff ", "managing director", "geschäftsführer", "leitung",
    "führungskraft", "teamleiter", "teamleiterin",
    # Software developer roles - the user is not a dev
    "developer", "entwickler", "software engineer", "full stack", "full-stack",
    "fullstack", "backend", "back-end", "back end", "frontend", "front-end",
    "front end", "devops", "site reliability", "cloud engineer",
    "mobile developer", "ios developer", "android developer",
    "data engineer", "machine learning engineer", "ml engineer",
    "ai engineer", "platform engineer", "infrastructure engineer",
    # Management that is not process/project
    "engineering manager", "product manager", "program manager",
    "account manager", "sales manager", "marketing manager",
    "hr manager", "it manager", "office manager", "backoffice manager",
    # Other wrong domains
    "sales engineer", "vertriebsingenieur", "außendienst", "aussendienst",
    "callcenter", "call center", "telefonist",
    "pflege", "nursing", "krankenpflege",
    "gastronomie", "restaurant", "hotel",
    "kellner", "koch", "küche",
]

# ---------- HARD REJECT: body phrases ----------
HARD_REJECT_BODY = [
    "c1 ", "c2 ", "verhandlungssicher", "muttersprache",
    "fließend deutsch", "fliessend deutsch",
    "native german", "german native", "deutsch als muttersprache",
    "mehrjährige erfahrung", "mindestens 3 jahre", "mindestens 5 jahre",
    "5+ jahre erfahrung", "3+ jahre erfahrung",
    "französisch", "french", "spanisch", "italienisch", "niederländisch",
    "maternity cover", "temporary contract", "befristet auf",
    "callcenter", "call center",
]

# ---------- POSITIVE signals ----------
POSITIVE_TITLE = [
    "berufseinsteiger", "berufseinstieg", "quereinsteiger", "quereinstieg",
    "absolvent", "einstieg", "einsteiger", "junior", "trainee", "graduate",
    "ingenieur", "ingenieurwesen", "wirtschaftsingenieur", "maschinenbau",
    "industrial engineering", "mechanical engineering",
    "prozessmanager", "prozessmanagement", "projektmanager", "projektmanagement",
    "compliance", "kyc", "aml", "regulatory", "meldewesen",
    "dokumentation", "technical writer", "technischer redakteur",
    "testingenieur", "test engineer", "integration engineer",
    "data steward", "research data", "datenmanager",
]

POSITIVE_BODY = [
    "berufseinsteiger", "willkommen", "ohne berufserfahrung",
    "erste berufserfahrung", "quereinsteiger", "absolvent", "junior",
    "englisch", "english", "international",
    "ingenieurwesen", "wirtschaftsingenieurwesen", "maschinenbau", "mint",
    "compliance", "kyc", "know your customer", "aml", "geldwäsche",
    "sanktion", "sanction", "regulatorik", "regulatory", "meldewesen",
    "sorgfaltspflicht", "due diligence",
    "prozess", "prozessanalyse", "prozessoptimierung", "process management",
    "project management", "projektmanagement", "anforderung", "requirements",
    "datenmanagement", "datenanalyse", "data management", "data analysis",
    "forschungsdaten", "research data", "fair data", "metadata", "metadaten",
    "data steward", "data quality", "data governance",
    "dokumentation", "documentation", "technical writer",
    "finanz", "finance", "financial", "zahlungsabwicklung", "payment",
    "reconciliation", "forderungsmanagement", "reporting", "banking",
    "testing", "testingenieur", "quality", "qualität", "validierung",
    "schnittstelle", "schnittstellen", "systemintegration",
]

MAX_SCORE = 15
MIN_MATCH = 55

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
            params={"location": "Germany"},
            timeout=30,
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
    params = {
        "was": "KYC Compliance Prozessmanager Ingenieur",
        "size": 60,
        "page": 1,
        "veroeffentlichtseit": 7,
    }
    try:
        r = requests.get(
            "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs",
            headers=headers, params=params, timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        return [{
            "title": j.get("titel") or j.get("beruf", ""),
            "company": j.get("arbeitgeber", ""),
            "location": j.get("arbeitsort", {}).get("ort", "") if isinstance(j.get("arbeitsort"), dict) else "",
            "description": j.get("beschreibung") or "",
            "url": f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{j.get('refnr','')}",
        } for j in (data.get("ergebnisse") or data.get("ergebnisliste") or [])]
    except Exception as e:
        print(f"Bundesagentur error: {e}")
        return []


def build_prompt(job):
    return f"""You are a STRICT recruiter scoring ONE job for a candidate.

CANDIDATE:
{CV_SUMMARY}

JOB:
Title: {job['title']}
Description: {job['description'][:2500]}

SCORING EXAMPLES for THIS candidate:
- "KYC Analyst" entry-level, English OK = 85
- "Junior Compliance Manager" with "Berufseinsteiger willkommen" = 80
- "Prozessmanager" requiring 3+ years = 50
- "Data Steward" at a research institute, English = 75
- "Technical Writer" in engineering = 65
- "Backoffice Manager (Quereinstieg)" low-level admin = 20
- "Controller" accounting role = 25
- "Full Stack Developer" = 5
- "Senior Engineering Manager" = 0
- "Sales Engineer" = 15

RULES:
- If the role is a software developer, backend, frontend, full-stack, DevOps,
  data engineer, ML engineer, or platform engineer: score 5-15 MAX.
- If the title contains "Senior", "Lead", "Head", "Director", "Manager"
  (unless it is "Prozessmanager", "Projektmanager", "Product Owner"):
  score 0-15.
- If the role requires C1/C2 German or "verhandlungssicher": cap at 40.
- If the role requires more than 2 years experience: cap at 50.
- If the role is low-level backoffice/Sachbearbeiter without a real process
  or compliance component: score 15-30.
- If the role requires French, Spanish, Italian or Dutch: score 0-10.

Return ONLY one integer from 0 to 100. Nothing else. No explanation.
"""


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
    for attempt in range(3):
        try:
            r = groq_client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=[{"role": "user", "content": build_prompt(job)}],
                temperature=0.0,
                max_completion_tokens=64,
                reasoning_effort="low",
            )
            return parse_score(r.choices[0].message.content)
        except Exception as e:
            msg = str(e)
            if "429" in msg or "rate_limit" in msg:
                wait = 30
                mm = re.search(r"try again in ([\d.]+)s", msg)
                if mm:
                    wait = min(float(mm.group(1)) + 2, 90)
                print(f"    rate limit, wait {wait:.0f}s")
                time.sleep(wait)
            else:
                print(f"    groq error: {e}")
                time.sleep(3)
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
                    time.sleep(5)
                    continue
                break
    return None


def pre_filter(jobs):
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
        if not (any(p in tl for p in POSITIVE_TITLE) or any(p in blob for p in POSITIVE_BODY)):
            rejected += 1
            continue

        rank = 2 * sum(1 for p in POSITIVE_TITLE if p in tl) + sum(1 for p in POSITIVE_BODY if p in blob)
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

    candidates = pre_filter(jobs)[:MAX_SCORE]
    print(f"Will score: {len(candidates)}\n")

    matches = []
    for i, job in enumerate(candidates, 1):
        print(f"[{i}/{len(candidates)}] {job['title']}")
        pct = score_groq(job)
        if pct is None:
            print(f"  groq failed, trying gemini")
            pct = score_gemini(job)
        if pct is None:
            print(f"  skipped")
            continue
        print(f"  {pct}%")
        if pct >= MIN_MATCH:
            matches.append({**job, "pct": pct})
        time.sleep(6)

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
