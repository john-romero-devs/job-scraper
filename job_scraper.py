import requests
import json
import gspread
import yagmail
import re
import feedparser
import hashlib
import pytz
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time

# === CONFIG ===
GOOGLE_SHEET_NAME = '[YOUR_GOOGLE_SHEET_NAME_HERE]'
EMAIL_TO = '[YOUR_EMAIL_HERE]'
# ⚠️ Adjust your timezone if not in Pacific Time
local_tz = pytz.timezone('[YOUR_TIMEZONE_HERE]')  # e.g., 'America/New_York'
EMAIL_SUBJECT = f"📣 New Job Listings - job-scraper - {datetime.now(local_tz).strftime('%b %d, %Y %I:%M %p')}"

# === TIMESTAMP HELPER FUNCTION ===
def time_ago(posted_time):
    if isinstance(posted_time, str):
        try:
            posted_time = datetime.fromisoformat(posted_time)
        except:
            posted_time = datetime.now()

    if posted_time.tzinfo is None:
        posted_time = local_tz.localize(posted_time)
    else:
        posted_time = posted_time.astimezone(local_tz)

    now = datetime.now(local_tz)
    delta = now - posted_time

    seconds = int(delta.total_seconds())
    minutes = seconds // 60
    hours = minutes // 60
    days = hours // 24

    if seconds < 60:
        return "Just now"
    elif minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    else:
        return f"{days} day{'s' if days != 1 else ''} ago"

# === Setup Google Sheets ===
def get_gsheet_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name('[YOUR_CREDENTIALS_JSON_PATH_HERE]', scope)
    return gspread.authorize(creds)

# === Load or Create Known Job IDs ===
def load_known_ids(filepath='known_jobs.json'):
    try:
        with open(filepath, 'r') as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()

def save_known_ids(ids, filepath='known_jobs.json'):
    with open(filepath, 'w') as f:
        json.dump(list(ids), f)

# === Fetch Jobs from RemoteOK.com ===
def fetch_remoteok_jobs():
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get('https://remoteok.com/api', headers=headers, timeout=10)
        raw_jobs = res.json()[1:]  # first item is metadata
        print(f"✅ RemoteOK: Fetched {len(raw_jobs)} jobs")

        jobs = []
        for job in raw_jobs:
            job_id = hashlib.md5(f"{job.get('url', '')}{job.get('position', '')}".encode()).hexdigest()
            posted_dt = datetime.fromtimestamp(job.get("epoch", time.time()))
            jobs.append({
                "id": job_id,
                "position": job.get("position", "Unknown"),
                "company": job.get("company", "Unknown"),
                "location": job.get("location", "Remote"),
                "url": job.get("url", ""),
                "date": posted_dt
            })

        return jobs

    except Exception as e:
        print(f"❌ RemoteOK error: {e}")
        return []

# === Fetch all jobs from multiple sources ===
def fetch_all_jobs_working():
    print("🚀 Starting job fetch from RemoteOK...")
    all_jobs = fetch_remoteok_jobs()
    print(f"📊 Total jobs fetched: {len(all_jobs)}")
    return all_jobs

# === Filter Jobs by Keywords ===
def filter_jobs(jobs, include_keywords, exclude_keywords=None):
    if exclude_keywords is None:
        exclude_keywords = []

    filtered = []
    for job in jobs:
        title = job.get('position', '').lower()

        include_hit = any(kw.lower() in title for kw in include_keywords)
        exclude_hit = any(bad_kw.lower() in title for bad_kw in exclude_keywords)

        if include_hit and not exclude_hit:
            filtered.append(job)

    return filtered

# === Write to Google Sheet ===
def write_to_sheet(jobs, client):
    sheet = client.open(GOOGLE_SHEET_NAME).sheet1

    rows = []
    for job in jobs:
        rows.append([
            job.get('date', datetime.now()).isoformat(),
            job.get('position', 'No Title'),
            job.get('company', 'No Company'),
            job.get('location', 'Unknown'),
            job.get('url', '')
        ])
    
    sheet.append_rows(rows, value_input_option='USER_ENTERED')

# === Send Email Digest ===
def send_email(jobs):
    if not jobs:
        return
    body_lines = []
    for job in jobs:
        posted_dt = job.get('date', datetime.now())

        if isinstance(posted_dt, str):
            try:
                posted_dt = datetime.fromisoformat(posted_dt)
            except ValueError:
                try:
                    posted_dt = datetime.strptime(posted_dt, "%Y-%m-%d %H:%M:%S")
                except:
                    posted_dt = datetime.now()
        elif isinstance(posted_dt, time.struct_time):
            posted_dt = datetime.fromtimestamp(time.mktime(posted_dt))

        print(f"📅 Parsed job time: {posted_dt} for job: {job['position']}")

        ago = time_ago(posted_dt)
        body_lines.append(f"- {job['position']} at {job['company']} - {ago}\n  {job['url']}")

    body = "Here are your new matching jobs:\n\n" + "\n\n".join(body_lines)
    yag = yagmail.SMTP('[YOUR_GMAIL_USERNAME_HERE]', '[YOUR_APP_PASSWORD_HERE]')
    yag.send(to=EMAIL_TO, subject=EMAIL_SUBJECT, contents=body)

# === Main Script ===
def main():
    print("🔍 Fetching and filtering jobs...")
    known_ids = load_known_ids()
    client = get_gsheet_client()

    # Fetch jobs from multiple sources (no WeWorkRemotely)
    jobs = fetch_all_jobs_working()
    
    INCLUDE_KEYWORDS = ['ui/ux', 'ux/ui', 'ui', 'ux', 'ui designer', 'ux designer', 'interface artist', 'interface designer', 'graphic designer', 'graphic artist', 'ui artist', 'visual', 'interface', 'designer', 'web designer', 'unity']
    EXCLUDE_KEYWORDS = ['software', 'engineer', 'developer', 'backend', 'fullstack']
    
    new_jobs = filter_jobs(jobs, INCLUDE_KEYWORDS, EXCLUDE_KEYWORDS)

    unseen_jobs = [job for job in new_jobs if job['id'] not in known_ids]
    if unseen_jobs:
        print(f"✨ Found {len(unseen_jobs)} new matching jobs!")

        write_to_sheet(unseen_jobs, client)
        send_email(unseen_jobs)

        known_ids.update(job['id'] for job in unseen_jobs)
        save_known_ids(known_ids)
    else:
        print("📭 No new jobs found.")

if __name__ == '__main__':
    main()