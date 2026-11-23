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


HARD_REJECT_TITLE_RE = re.compile(
    r"\b("
    r"werkstudent|working.?student|praktikant|praktikum|ausbildung|"
    r"auszubildende|azubi|dual(es)? studium|internship|intern|"
    r"senior|sr|lead|head.?of|director|vp|chief|principal|staff|"
    r"managing.?director|geschäftsführer|leitung|führungskraft|"
    r"teamleiter|teamleiterin|projektleiter|"
    r"developer|entwickler|software.?engineer|full.?stack|fullstack|"
    r"backend|back.?end|frontend|front.?end|devops|site.?reliability|"
    r"cloud.?engineer|mobile.?developer|ios.?developer|android.?developer|"
    r"data.?engineer|machine.?learning|ml.?engineer|ml.?ops|"
    r"ai.?engineer|platform.?engineer|infrastructure.?engineer|"
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
    r"maternity.?cover|temporary.?contract|befristet.?auf"
    r")\b",
    re.IGNORECASE,
)

TIER1 = [
    "kyc", "know your customer", "compliance", "aml",
    "anti money laundering", "anti-money laundering",
    "geldwäsche", "geldwaesche", "sanction", "sanktion",
    "due diligence", "sorgfaltspflicht",
    "regulatory reporting", "meldewesen", "regulatorik",
    "prozessmanager", "prozessmanagement", "prozessanalyse",
    "prozessoptimierung", "process manager", "process management",
    "data steward", "research data", "forschungsdaten", "fair data",
    "data management", "datenmanagement", "metadaten", "metadata",
    "data governance", "data quality", "datenqualität",
    "requirements engineer", "requirements analysis", "anforderungsmanager",
    "technical writer", "technischer redakteur", "technische dokumentation",
]

TIER2 = [
    "berufseinsteiger", "berufseinstieg", "quereinsteiger", "quereinstieg",
    "absolvent", "junior", "trainee", "graduate",
    "prozess", "requirements", "anforderung",
    "dokumentation", "documentation",
    "reporting", "kpi", "zahlungsabwicklung", "payment",
    "reconciliation", "forderungsmanagement",
    "testing", "validierung", "quality assurance",
    "integration", "schnittstelle", "api",
]

MAX_SCORE = 15
MIN_MATCH = 50

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
            timeout=30,
        )
        r.raise_for_status()
        data = r.json().get("data", [])
        return [{
            "title": j.get("title", ""),
            "company": j.get("company_name", ""),
            "location": j.get("location", ""),
            "description": j.get("description", ""),
            "url": j.get("url", ""),
            "source": "arbeitnow",
        } for j in data]
    except Exception as e:
        print(f"Arbeitnow error: {e}")
        return []


def fetch_bundesagentur():
    headers = {"X-API-Key": "jobboerse-jobsuche"}
    queries = ["KYC Compliance", "Prozessmanager", "Data Steward",
               "Regulatory Reporting", "Geldwäsche"]
    jobs = []
    seen = set()
    dumped = False

    for q in queries:
        params = {"was": q, "size": 40, "page": 1, "veroeffentlichtseit": 14}
        try:
            r = requests.get(
                "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs",
                headers=headers, params=params, timeout=30,
            )
            if r.status_code != 200:
                print(f"  BA '{q}': HTTP {r.status_code}, skipped")
                continue

            data = r.json()
            results = data.get("ergebnisliste") or data.get("ergebnisse") or []
            print(f"  BA '{q}': {len(results)} results")

            for j in results:
                if not isinstance(j, dict):
                    continue

                if not dumped:
                    print(f"    FIRST JOB keys: {list(j.keys())}")
                    print(f"    FIRST JOB sample: {str(j)[:400]}")
                    dumped = True

                t = (
                    j.get("titel")
                    or j.get("beruf")
                    or j.get("stellenangebotsTitel")
                    or j.get("berufsbezeichnung")
                    or j.get("hauptberuf")
                    or ""
                )
                if not isinstance(t, str):
                    t = ""
                t = t.strip()

                if not t or t in seen:
                    continue
                seen.add(t)

                loc = ""
                ao = j.get("arbeitsort")
                if isinstance(ao, dict):
                    loc = ao.get("ort", "") or ""
                elif isinstance(ao, str):
                    loc = ao

                desc = j.get("beschreibung") or ""
                if not isinstance(desc, str):
                    desc = ""

                jobs.append({
                    "title": t,
                    "company": j.get("arbeitgeber", "") or "",
                    "location": loc or "Germany",
                    "description": desc,
                    "url": f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{j.get('refnr','')}",
                    "source": "bundesagentur",
                })

        except Exception as e:
            print(f"  BA '{q}' exception: {e}")

    return jobs


def build_prompt(job):
    return f"""Score this job 0-100 for the candidate. Return ONLY the integer.

CANDIDATE:
{CV_SUMMARY}

JOB:
Title: {job['title']}
Location: {job['location']}
Description: {job['description'][:2500]}

SCORING EXAMPLES:
- "KYC Analyst" entry-level, English OK = 85
- "Junior Compliance Manager", "Berufseinsteiger willkommen" = 80
- "Data Steward" research institute = 75
- "Technical Writer" engineering = 65
- "Prozessmanager" requiring 3+ years = 50
- "Integration and Test Engineer" 0-2 years = 55

NOT A FIT (0-25 ONLY, NEVER HIGHER):
- Customer Success, Kundendienst, Kundenbetreuung = 15
- Sales / Account Manager / Account Executive = 5
- Full Stack / Backend / Frontend / DevOps = 5
- Senior / Lead / Head of / Director = 0
- Controller / FP&A / Accounting = 15
- UI/UX / Designer = 5
- IT-Systemadministrator / System Engineer = 25
- HR Generalist / Recruiter = 5
- Quantitative Researcher = 10
- Any role requiring French/Spanish/Italian/Dutch = 0

RULES:
Software developer/engineer roles: 5-15 max.
Any Senior/Lead/Head/Director title: 0-15.
C1 German required: cap 40.
More than 2 years experience required: cap 50.
Low-level backoffice without compliance/process content: 15-30.

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
        if t1_title == 0 and t1_head == 0:
            stats["no_tier1"] += 1
            continue

        t2 = sum(1 for p in TIER2 if p in (tl + " " + body_head))
        rank = 10 * t1_title + 3 * t1_head + 1 * t2
        stats["kept"] += 1
        out.append((rank, job))

    out.sort(key=lambda x: x[0], reverse=True)
    print(f"Rejected (title): {stats['title']}")
    print(f"Rejected (body): {stats['body']}")
    print(f"Rejected (no TIER1 in title/lead): {stats['no_tier1']}")
    print(f"Surviving: {stats['kept']}")
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
    print("=== Fetching ===")
    arbeitnow_raw = fetch_arbeitnow()
    print(f"Arbeitnow raw: {len(arbeitnow_raw)}")

    print("\n=== Bundesagentur ===")
    ba_raw = fetch_bundesagentur()
    print(f"Bundesagentur raw: {len(ba_raw)}\n")

    arbeitnow_dach = [j for j in arbeitnow_raw if is_dach(j["location"])]
    print(f"Arbeitnow DACH-filtered: {len(arbeitnow_dach)}")

    all_jobs = arbeitnow_dach + ba_raw
    print(f"Total usable: {len(all_jobs)}\n")

    candidates = rank_and_filter(all_jobs)[:MAX_SCORE]
    print(f"\nWill score: {len(candidates)}\n")

    if len(candidates) < 3:
        print("WARNING: fewer than 3 candidates. Check the Bundesagentur debug output above.")

    matches = []
    for i, job in enumerate(candidates, 1):
        print(f"[{i}/{len(candidates)}] ({job['source']}) {job['title']} — {job['location']}")
        pct = score_groq(job)
        if pct is None:
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
