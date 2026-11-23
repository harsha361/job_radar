import os
import re
import json
import requests
from google import genai
from groq import Groq

# ---------- Secrets ----------
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_KEY = os.environ["GEMINI_KEY"]
GROQ_KEY = os.environ.get("GROQ_KEY", "")

# ============ FILTER TIERS ============

HARD_REJECT_TITLE = [
    "werkstudent", "working student", "praktikant", "praktikum",
    "ausbildung", "auszubildende", "azubi", "duales studium",
    "dual studium", "internship", "intern ",
    "senior", "lead ", "head of", "director", "vp ", "chief",
    "geschäftsführer", "geschaeftsfuehrer", "leitung", "führungskraft",
    "principal", "staff ", "managing director",
]

HARD_REJECT_BODY = [
    "c1 ", "c2 ", "verhandlungssicher", "muttersprache",
    "fließend deutsch", "fliessend deutsch", "deutsch auf muttersprach",
    "native german", "german native",
    "mehrjährige erfahrung", "mehrjaehrige erfahrung",
    "mindestens 3 jahre", "mindestens 5 jahre", "5+ jahre erfahrung",
    "callcenter", "call center", "telefonist",
    "pflege", "nursing", "krankenpflege",
    "gastronomie", "restaurant", "hotel",
]

SOFT_PENALTY = [
    "vertrieb", "sales", "kundenberatung", "kundenbetreuung",
    "außendienst", "aussendienst", "kundendienst",
    "mehrere jahre", "3-5 jahre",
]

POSITIVE_TITLE = [
    "berufseinsteiger", "berufseinstieg", "quereinsteiger", "quereinstieg",
    "absolvent", "absolventin", "absolventen", "einstieg", "einsteiger",
    "junior", "trainee", "graduate", "entry level", "entry-level",
    "ingenieur", "ingenieurwesen", "ingenieurwissenschaften",
    "wirtschaftsingenieur", "wirtschaftsingenieurwesen",
    "maschinenbau", "industrial engineering", "mechanical engineering",
]

POSITIVE_BODY = [
    "berufseinsteiger sind willkommen", "berufseinsteiger willkommen",
    "auch willkommen", "herzlich willkommen", "sind willkommen",
    "ohne berufserfahrung", "keine berufserfahrung", "erste berufserfahrung",
    "berufseinsteiger", "berufseinstieg", "quereinsteiger", "quereinstieg",
    "absolvent", "einsteiger", "junior", "trainee",
    "englisch", "english", "englischkenntnisse", "international",
    "internationale", "internationales", "internationalen",
    "englischsprachig", "english speaking", "english-speaking",
    "ingenieurwesen", "wirtschaftsingenieurwesen", "maschinenbau",
    "industrial engineering", "mechanical engineering", "mint",
    "compliance", "kyc", "know your customer", "aml", "geldwäsche",
    "geldwaesche", "sanktion", "sanction", "regulatorik", "regulatory",
    "meldewesen", "regulatory reporting", "sorgfaltspflicht", "due diligence",
    "prozess", "prozessmanager", "prozessmanagement", "prozessanalyse",
    "prozessoptimierung", "process management", "process analysis",
    "project management", "projektmanagement", "projektkoordination",
    "requirements", "anforderung", "anforderungsmanagement",
    "datenmanagement", "datenanalyse", "data management", "data analysis",
    "forschungsdaten", "research data", "fair data", "metadaten", "metadata",
    "data steward", "datenqualität", "data quality", "data governance",
    "dokumentation", "documentation", "technischer redakteur",
    "technische dokumentation", "technical writer", "technical writing",
    "finanz", "finance", "financial", "zahlungsabwicklung", "payment",
    "reconciliation", "forderungsmanagement", "reporting", "banking",
    "bank", "finanzdienstleistung", "financial services",
    "testing", "tester", "testingenieur", "test engineer", "qualität",
    "quality", "prüfung", "validation", "validierung",
    "schnittstelle", "schnittstellen", "integration", "systemintegration",
    "system integration", "interface", "api",
    "python", "sql", "software", "digitalisierung", "digitalization",
    "automatisierung", "automation", "ki", "ai",
]

MAX_SCORE = 40
MIN_MATCH = 50
BATCH_SIZE = 10

CV_SUMMARY = """
M.Sc. Advanced Industrial Engineering (Wirtschaftsingenieurwesen, Grade 1.9),
Technical University of Applied Sciences Rosenheim, Germany.
B.Tech Mechanical Engineering.

6 years at Federal Bank Ltd, India:
- KYC and customer due diligence (customer identification, document checks,
  beneficial ownership, sanctions screening)
- Payment reconciliation, account operations, compliance controls
- Requirements analysis, process analysis, process optimization
- Reporting and KPI analysis
- Project coordination and cross-functional stakeholder management
- User training and system rollouts

BAM Berlin Master's thesis:
- Python software development, data pipelines, REST APIs, JSON-LD
- FAIR data principles, metadata modeling, PROV-O, OPMW
- Docker, Git, Linux, testing and documentation to DIN/ISO standards
- Daily use of LLMs and AI agents (Claude Code, Codex, LangChain)

Languages: English C1, German B2, Telugu/Hindi native.
Work permit: Section 18b AufenthG, Blue Card eligible.
Willing to relocate anywhere in Germany.
"""

# ============ LLM CLIENTS ============
groq_client = Groq(api_key=GROQ_KEY) if GROQ_KEY else None
gemini_client = genai.Client(api_key=GEMINI_KEY)


def _build_prompt(jobs_batch):
    job_block = "\n\n".join([
        f"JOB {i+1}:\nTitle: {j['title']}\nDescription: {j['description'][:1500]}"
        for i, j in enumerate(jobs_batch)
    ])
    return f"""You are a strict, critical recruiter. Score each job from 0-100
for this candidate.

CANDIDATE CV:
{CV_SUMMARY}

RULES:
- 80-100: Near-perfect fit. Same domain, entry-level friendly, English OK.
- 60-79: Strong fit. Adjacent domain, most requirements met.
- 40-59: Possible but stretch. Real gaps in domain or level.
- 20-39: Weak. Wrong domain or above candidate's level.
- 0-19: Not a fit.

Be harsh. A catering back-office role is 15. A Senior Engineer role is 5.
A role requiring C1 German caps at 40.
A role requiring more than 2 years experience caps at 50.

Return ONLY a JSON array of integers, one per job, in order.
Example: [72, 45, 88, 12, 60]

JOBS:
{job_block}
"""


def _parse_scores(text, expected_count):
    """Try JSON parse first, fall back to regex."""
    if not text:
        return None
    # Try to find JSON array
    m = re.search(r"\[[\d,\s]+\]", text)
    if m:
        try:
            arr = json.loads(m.group(0))
            nums = [int(x) for x in arr if isinstance(x, (int, float))]
            if len(nums) >= expected_count:
                return nums[:expected_count]
        except Exception:
            pass
    # Fallback: any 1-3 digit numbers
    nums = [int(n) for n in re.findall(r"\b(\d{1,3})\b", text)]
    # Filter out obviously wrong values (years, job numbers, etc.)
    nums = [n for n in nums if 0 <= n <= 100]
    if len(nums) >= expected_count:
        return nums[:expected_count]
    return None


def score_batch_groq(jobs_batch):
    if not groq_client:
        return None
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": _build_prompt(jobs_batch)}],
            temperature=0.1,
        )
        text = response.choices[0].message.content.strip()
        return _parse_scores(text, len(jobs_batch))
    except Exception as e:
        print(f"Groq batch error: {e}")
        return None


def score_batch_gemini(jobs_batch):
    try:
        response = gemini_client.models.generate_content(
            model="gemini-3.8-flash",
            contents=_build_prompt(jobs_batch),
        )
        return _parse_scores(response.text, len(jobs_batch))
    except Exception as e:
        print(f"Gemini batch error: {e}")
        return None


# ============ FETCHERS ============

def fetch_bundesagentur():
    headers = {"X-API-Key": "jobboerse-jobsuche"}
    queries = [
        "KYC Compliance",
        "Prozessmanager",
        "Ingenieur Junior",
        "Regulatory Reporting",
        "Technischer Redakteur",
    ]
    all_jobs = []
    for q in queries:
        params = {"was": q, "size": 30, "page": 1, "veroeffentlichtseit": 7}
        try:
            r = requests.get(
                "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs",
                headers=headers, params=params, timeout=30,
            )
            r.raise_for_status()
            data = r.json()
            for j in (data.get("ergebnisse") or data.get("ergebnisliste") or []):
                all_jobs.append({
                    "title": j.get("titel") or j.get("beruf", ""),
                    "company": j.get("arbeitgeber", ""),
                    "location": j.get("arbeitsort", {}).get("ort", "") if isinstance(j.get("arbeitsort"), dict) else "",
                    "description": j.get("beschreibung") or "",
                    "url": f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{j.get('refnr','')}",
                })
        except Exception as e:
            print(f"Bundesagentur error ({q}): {e}")
    return all_jobs


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
        } for j in r.json().get("data", [])]
    except Exception as e:
        print(f"Arbeitnow error: {e}")
        return []


# ============ FILTER ============

def pre_filter(jobs):
    candidates = []
    hard_rejected = 0
    soft_penalized = 0
    seen = set()

    for job in jobs:
        title = job["title"].strip()
        if not title or title in seen:
            continue
        seen.add(title)

        title_l = title.lower()
        body_l = job["description"].lower()
        blob_l = title_l + " " + body_l

        if any(b in title_l for b in HARD_REJECT_TITLE):
            hard_rejected += 1
            continue
        if any(b in body_l for b in HARD_REJECT_BODY):
            hard_rejected += 1
            continue

        has_positive_title = any(p in title_l for p in POSITIVE_TITLE)
        has_positive_body = any(p in blob_l for p in POSITIVE_BODY)
        if not (has_positive_title or has_positive_body):
            hard_rejected += 1
            continue

        is_soft = any(s in blob_l for s in SOFT_PENALTY)
        if is_soft:
            soft_penalized += 1

        rank = (
            2 * sum(1 for p in POSITIVE_TITLE if p in title_l)
            + sum(1 for p in POSITIVE_BODY if p in blob_l)
            - (3 if is_soft else 0)
        )
        candidates.append((rank, job))

    candidates.sort(key=lambda x: x[0], reverse=True)
    return [c[1] for c in candidates], hard_rejected, soft_penalized


# ============ TELEGRAM ============

def send_telegram_chunked(header, items, footer=""):
    """Send in chunks to respect Telegram 4096-char limit."""
    chunk = header
    for item in items:
        if len(chunk) + len(item) > 3800:
            _post(chunk)
            chunk = ""
        chunk += "\n\n" + item
    if chunk.strip():
        if footer:
            chunk += "\n\n" + footer
        _post(chunk)


def _post(text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=15,
        )
    except Exception as e:
        print(f"Telegram error: {e}")


# ============ MAIN ============

def main():
    all_jobs = fetch_bundesagentur() + fetch_arbeitnow()
    print(f"Total fetched: {len(all_jobs)}")

    candidates, hard_rejected, soft_penalized = pre_filter(all_jobs)
    print(f"Hard rejected: {hard_rejected}")
    print(f"Soft penalized: {soft_penalized}")
    print(f"Surviving candidates: {len(candidates)}")

    candidates = candidates[:MAX_SCORE]
    print(f"Will score: {len(candidates)}")

    matches = []
    for i in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[i:i + BATCH_SIZE]
        print(f"\nBatch {i//BATCH_SIZE + 1}: jobs {i+1}-{i+len(batch)}")

        scores = score_batch_groq(batch)
        if not scores or len(scores) < len(batch):
            print("  Groq failed or incomplete, trying Gemini...")
            scores = score_batch_gemini(batch)

        if not scores or len(scores) < len(batch):
            print("  All LLMs failed for this batch. Skipping.")
            continue

        for job, pct in zip(batch, scores):
            print(f"  {pct:>3}%  {job['title']}")
            if pct >= MIN_MATCH:
                matches.append({**job, "pct": pct})

    matches.sort(key=lambda x: x["pct"], reverse=True)
    print(f"\nMatches above {MIN_MATCH}%: {len(matches)}")

    if not matches:
        _post(f"🎯 Job Radar: no matches above {MIN_MATCH}% today "
              f"({len(candidates)} scored).")
        return

    header = f"<b>🎯 Job Radar — {len(matches)} matches</b>"
    items = [
        f"<b>{m['pct']}%</b> — <a href=\"{m['url']}\">{m['title']}</a>\n"
        f"{m['company']} · {m['location']}"
        for m in matches[:30]
    ]
    send_telegram_chunked(header, items)


if __name__ == "__main__":
    main()
