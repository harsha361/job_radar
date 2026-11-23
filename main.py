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
]

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
    prompt = f"""Score this job from 0 to 100 against the candidate CV.
Return ONLY the integer, nothing else, no explanation.

JOB TITLE: {title}
JOB DESCRIPTION: {description[:3000]}

CANDIDATE CV:
{CV_SUMMARY}
"""
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        text = response.text.strip()
        nums = re.findall(r"\d+", text)
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
    matches = []

    for job in all_jobs:
        title = job["title"]
        blob = (title + " " + job["description"]).lower()

        if not any(k in blob for k in KEYWORDS):
            continue
        if title in seen:
            continue
        seen.add(title)

        pct = score_job(title, job["description"])
        print(f"{pct:>3}%  {title}")

        if pct >= 60:
            matches.append({**job, "pct": pct})

    matches.sort(key=lambda x: x["pct"], reverse=True)

    if not matches:
        send_telegram("🎯 Job Radar: no jobs above 60% today.")
        return

    lines = [f"<b>🎯 Job Radar — {len(matches)} matches</b>\n"]
    for m in matches[:10]:
        lines.append(
            f"<b>{m['pct']}%</b> — <a href=\"{m['url']}\">{m['title']}</a>\n"
            f"{m['company']} · {m['location']}"
        )
    send_telegram("\n\n".join(lines))


if __name__ == "__main__":
    main()
