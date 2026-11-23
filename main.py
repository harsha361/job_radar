import os
import re
import json
import time
import requests
from google import genai
from groq import Groq

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_KEY = os.environ["GEMINI_KEY"]
GROQ_KEY = os.environ.get("GROQ_KEY", "")

HARD_REJECT_TITLE = [
    "werkstudent", "working student", "praktikant", "praktikum",
    "ausbildung", "auszubildende", "azubi", "duales studium",
    "dual studium", "internship", "intern ",
    "senior", "lead ", "head of", "director", "vp ", "chief",
    "geschäftsführer", "leitung", "führungskraft",
    "principal", "staff ", "managing director",
]

HARD_REJECT_BODY = [
    "c1 ", "c2 ", "verhandlungssicher", "muttersprache",
    "fließend deutsch", "fliessend deutsch",
    "native german", "german native",
    "mehrjährige erfahrung", "mindestens 3 jahre", "mindestens 5 jahre",
    "callcenter", "call center", "telefonist",
    "pflege", "nursing", "krankenpflege",
    "gastronomie", "restaurant", "hotel",
]

POSITIVE_TITLE = [
    "berufseinsteiger", "berufseinstieg", "quereinsteiger", "quereinstieg",
    "absolvent", "einstieg", "einsteiger", "junior", "trainee", "graduate",
    "ingenieur", "ingenieurwesen", "wirtschaftsingenieur", "maschinenbau",
    "industrial engineering", "mechanical engineering",
]

POSITIVE_BODY = [
    "berufseinsteiger", "willkommen", "ohne berufserfahrung", "erste berufserfahrung",
    "quereinsteiger", "absolvent", "junior", "trainee",
    "englisch", "english", "international", "englischsprachig",
    "ingenieurwesen", "wirtschaftsingenieurwesen", "maschinenbau", "mint",
    "compliance", "kyc", "know your customer", "aml", "geldwäsche",
    "sanktion", "sanction", "regulatorik", "regulatory", "meldewesen",
    "sorgfaltspflicht", "due diligence",
    "prozess", "prozessmanager", "prozessmanagement", "prozessanalyse",
    "prozessoptimierung", "process management", "project management",
    "projektmanagement", "anforderung", "requirements",
    "datenmanagement", "datenanalyse", "data management", "data analysis",
    "forschungsdaten", "research data", "fair data", "metadata", "metadaten",
    "data steward", "data quality", "data governance",
    "dokumentation", "documentation", "technischer redakteur", "technical writer",
    "finanz", "finance", "financial", "zahlungsabwicklung", "payment",
    "reconciliation", "forderungsmanagement", "reporting", "banking",
    "testing", "testingenieur", "quality", "qualität", "validierung",
    "schnittstelle", "schnittstellen", "integration", "systemintegration",
    "python", "sql", "digitalisierung", "automatisierung", "automation", "ki",
]

MAX_SCORE = 15
MIN_MATCH = 50
BATCH_SIZE = 5
BATCH_SLEEP = 45

CV_SUMMARY = """
M.Sc. Advanced Industrial Engineering (Grade 1.9), TH Rosenheim, Germany.
B.Tech Mechanical Engineering.
6 years at Federal Bank India: KYC, customer due diligence, payment
reconciliation, compliance controls, requirements analysis, process analysis,
reporting, project coordination, user training.
BAM Berlin thesis: Python, data pipelines, REST APIs, JSON-LD, FAIR data,
metadata, Docker, Git, testing, documentation.
Languages: English C1, German B2. Work permit Section 18b.
"""

groq_client = Groq(api_key=GROQ_KEY) if GROQ_KEY else None
gemini_client = genai.Client(api_key=GEMINI_KEY)


def fetch_arbeitnow():
    """Germany only. The location param is the fix."""
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
    """Single precise query, Germany only."""
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


def _build_prompt(batch):
    job_block = "\n\n".join([
        f"JOB {i+1}:\nTitle: {j['title']}\nDescription: {j['description'][:1200]}"
        for i, j in enumerate(batch)
    ])
    return f"""Score each job 0-100 for this candidate. Be harsh.

CV:
{CV_SUMMARY}

RULES:
80-100 perfect fit, 60-79 strong, 40-59 stretch, 20-39 weak, 0-19 no fit.
Catering back-office = 15. Senior Engineer = 5.
C1 German required = cap 40. More than 2 years experience = cap 50.

Return ONLY a JSON array like [72, 45, 88].

JOBS:
{job_block}
"""


def _parse(text, n):
    if not text:
        return None
    m = re.search(r"\[[\d,\s]+\]", text)
    if m:
        try:
            arr = json.loads(m.group(0))
            nums = [int(x) for x in arr if isinstance(x, (int, float))]
            if len(nums) >= n:
                return nums[:n]
        except Exception:
            pass
    nums = [int(x) for x in re.findall(r"\b(\d{1,3})\b", text)]
    nums = [x for x in nums if 0 <= x <= 100]
    return nums[:n] if len(nums) >= n else None


def score_groq(batch):
    if not groq_client:
        return None
    for attempt in range(3):
        try:
            r = groq_client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=[{"role": "user", "content": _build_prompt(batch)}],
                temperature=0.1,
                max_completion_tokens=2048,
                reasoning_effort="low",
            )
            return _parse(r.choices[0].message.content.strip(), len(batch))
        except Exception as e:
            msg = str(e)
            if "429" in msg or "rate_limit" in msg:
                wait = 30
                mm = re.search(r"try again in ([\d.]+)s", msg)
                if mm:
                    wait = min(float(mm.group(1)) + 1, 90)
                print(f"  Groq rate limit, wait {wait:.0f}s")
                time.sleep(wait)
            else:
                print(f"  Groq error: {e}")
                time.sleep(2)
    return None


def score_gemini(batch):
    for model in ["gemini-2.5-flash", "gemini-2.0-flash"]:
        for attempt in range(2):
            try:
                r = gemini_client.models.generate_content(
                    model=model, contents=_build_prompt(batch),
                )
                s = _parse(r.text, len(batch))
                if s:
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

        has_pos = any(p in tl for p in POSITIVE_TITLE) or any(p in blob for p in POSITIVE_BODY)
        if not has_pos:
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
    print(f"Will score: {len(candidates)}")

    matches = []
    for i in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[i:i + BATCH_SIZE]
        print(f"\nBatch {i//BATCH_SIZE + 1}: {len(batch)} jobs")

        scores = score_groq(batch)
        if not scores:
            print("  Groq failed, trying Gemini...")
            scores = score_gemini(batch)
        if not scores:
            print("  Batch skipped")
            continue

        for job, pct in zip(batch, scores):
            print(f"  {pct}%  {job['title']}")
            if pct >= MIN_MATCH:
                matches.append({**job, "pct": pct})

        if i + BATCH_SIZE < len(candidates):
            print(f"  Sleep {BATCH_SLEEP}s")
            time.sleep(BATCH_SLEEP)

    matches.sort(key=lambda x: x["pct"], reverse=True)
    print(f"\nMatches: {len(matches)}")

    if not matches:
        send_tg(f"🎯 Job Radar: 0 matches today ({len(candidates)} scored).")
        return

    lines = [f"<b>🎯 Job Radar — {len(matches)} matches</b>"]
    for m in matches[:15]:
        lines.append(
            f"<b>{m['pct']}%</b> — <a href=\"{m['url']}\">{m['title']}</a>\n"
            f"{m['company']} · {m['location']}"
        )
    send_tg("\n\n".join(lines))


if __name__ == "__main__":
    main()
