import os
import re
import requests
from google import genai

# ---------- Secrets from GitHub ----------
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_KEY = os.environ["GEMINI_KEY"]

# ---------- Your niche keywords ----------
KEYWORDS = [
    "kyc", "aml", "compliance", "sanktion", "sanction",
    "technischer redakteur", "technische dokumentation", "dokumentation",
    "prozessmanager", "prozessoptimierung", "prozessanalyse",
    "research software", "data steward", "fair data", "forschungsdaten",
    "regulatory reporting", "meldewesen", "schnittstelle", "datenintegration",
    "forderungsmanagement", "zahlungsabwicklung", "regulatorik",
]

# ---------- Hard exclusions (never score these) ----------
BLOCK = [
    "werkstudent", "working student", "praktikant", "praktikum",
    "ausbildung", "auszubildende", "dual stud", "duales studium",
    "internship", "intern ", "senior", "lead ", "head of",
    "director", "principal", "vp ", "chief", "managing director",
]

# ---------- How many jobs to score per run (quota protection) ----------
MAX_SCORE = 15
MIN_MATCH = 55

CV_SUMMARY = """
M.Sc. Advanced Industrial Engineering (Grade 1.9), TH Rosenheim.
6 years at Federal Bank: KYC, customer due diligence, payment reconciliation,
compliance controls, reporting, requirements analysis.
BAM Berlin thesis: Python software development, data pipelines, JSON-LD
metadata, FAIR data, REST APIs, Docker, testing, DIN/ISO documentation.
English C1, German B2. Work permit Section 18b.
"""

client = genai.Client(api_key=GEMINI_KEY)


def fetch_bundesagentur():
    headers = {"X-API-Key": "jobboerse-jobsuche"}
    params = {
        "was": "KYC Compliance Prozessmanager",
        "size": 40,
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
        jobs = data.get("ergebnisse") or data.get("ergebnisliste") or []
        out = []
        for j in jobs:
            out.append({
                "title": j.get("titel") or j.get("beruf", ""),
                "company": j.get("arbeitgeber", ""),
                "location": j.get("arbeitsort", {}).get("ort", "") if isinstance(j.get("arbeitsort"), dict) else "",
                "description": j.get("beschreibung") or "",
                "url": f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{j.get('refnr','')}",
            })
        return out
    except Exception as e:
        print(f"Bundesagentur error: {e}")
        return []


def fetch_arbeitnow():
    try:
        r = requests.get("https://www.arbeitnow.com/api/job-board-api", timeout=30)
        r.raise_for_status()
        out = []
        for j in r.json().get("data", []):
            out.append({
                "title": j.get("title", ""),
                "company": j.get("company_name", ""),
                "location": j.get("location", ""),
                "description": j.get("description", ""),
                "url": j.get("url", ""),
            })
        return out
    except Exception as e:
        print(f"Arbeitnow error: {e}")
        return []


def score_job(title, description):
    prompt = f"""You are a strict, critical recruiter screening a candidate.

CANDIDATE CV:
{CV_SUMMARY}

JOB:
Title: {title}
Description: {description[:3000]}

Score this job from 0 to 100 using these rules:
- 80-100: Near-perfect fit. Same domain, same level, requirements met.
- 60-79: Strong fit. Adjacent domain, most requirements met.
- 40-59: Possible but a stretch. Real gaps in domain or level.
- 20-39: Weak. Wrong domain or clearly above/below candidate's level.
- 0-19: Not a fit at all.

Be harsh.
A role requiring C1 German is capped at 40 for this candidate (B2).
A back-office or Sachbearbeiter role is 20-30, not 87.

Respond with ONLY the integer. No explanation, no text.
"""
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        nums = re.findall(r"\d+", response.text.strip())
        return int(nums[0]) if nums else 0
    except Exception as e:
        print(f"Gemini error: {e}")
        return 0


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=15,
        )
    except Exception as e:
        print(f"Telegram error: {e}")


def main():
    all_jobs = fetch_bundesagentur() + fetch_arbeitnow()
    print(f"Total fetched: {len(all_jobs)}")

    seen = set()
    candidates = []

    # Stage 1: filter without spending Gemini quota
    for job in all_jobs:
        title = job["title"]
        if not title:
            continue

        title_l = title.lower()
        blob = (title + " " + job["description"]).lower()

        # Hard blocklist - never score these
        if any(b in title_l for b in BLOCK):
            continue

        # Keyword relevance
        if not any(k in blob for k in KEYWORDS):
            continue

        if title in seen:
            continue
        seen.add(title)

        # Pre-rank by keyword density so we score the best first
        density = sum(blob.count(k) for k in KEYWORDS)
        candidates.append((density, job))

    # Sort by density, highest first
    candidates.sort(key=lambda x: x[0], reverse=True)
    print(f"Filtered to: {len(candidates)} candidates")

    # Stage 2: score only the top MAX_SCORE with Gemini
    matches = []
    scored = 0
    for _, job in candidates:
        if scored >= MAX_SCORE:
            break
        scored += 1

        pct = score_job(job["title"], job["description"])
        print(f"{pct:>3}%  {job['title']}")

        if pct >= MIN_MATCH:
            matches.append({**job, "pct": pct})

    print(f"Total scored: {scored}, matches above {MIN_MATCH}%: {len(matches)}")

    if not matches:
        send_telegram(f"🎯 Job Radar: no jobs above {MIN_MATCH}% today (scored {scored}).")
        return

    matches.sort(key=lambda x: x["pct"], reverse=True)

    lines = [f"<b>🎯 Job Radar — {len(matches)} matches</b>\n"]
    for m in matches[:10]:
        lines.append(
            f"<b>{m['pct']}%</b> — <a href=\"{m['url']}\">{m['title']}</a>\n"
            f"{m['company']} · {m['location']}"
        )
    send_telegram("\n\n".join(lines))


if __name__ == "__main__":
    main()
