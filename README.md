# Fitness Dashboard — Setup Guide

A private fitness dashboard that pulls from Apple Health via iOS Shortcuts,
stores data in a GitHub Gist, allows overrides via Google Sheets,
and auto-publishes to GitHub Pages 3× per day.

---

## Overview

```
Apple Watch
    │
    ▼  (iOS Shortcut runs manually or on schedule)
GitHub Gist  ◄──── workouts.json (raw Health data)
    │
    ▼  (GitHub Actions cron: 07:00 / 13:00 / 20:00 UTC)
process_health.py  ◄──── Google Sheet overrides (optional edits)
    │
    ▼
GitHub Pages  ──►  index.html + data.json  (your live dashboard)
```

---

## Step 1 — Create a private GitHub repo

1. Go to github.com → New repository
2. Name it: `fitness-dashboard`
3. Set it to **Private**
4. Upload (or copy-paste) these files:
   - `index.html`
   - `process_health.py`
   - `.github/workflows/update.yml`

---

## Step 2 — Enable GitHub Pages

1. Go to your repo → **Settings** → **Pages**
2. Source: **GitHub Actions**
3. Save. Your dashboard will be at:
   `https://YOUR-USERNAME.github.io/fitness-dashboard/`

> ⚠️ Even though the repo is private, GitHub Pages URLs are public by default.
> See "Access Control" at the bottom of this guide to add a password.

---

## Step 3 — Create a GitHub Gist for workout data

1. Go to gist.github.com
2. Create a **secret** gist (not public)
3. Filename: `workouts.json`
4. Initial content: `[]`
5. Save — copy the Gist ID from the URL:
   `https://gist.github.com/YOUR-USERNAME/`**`THIS-PART-IS-YOUR-GIST-ID`**

---

## Step 4 — Create a GitHub Personal Access Token (PAT)

The Shortcut needs permission to write to your Gist.

1. github.com → Settings → Developer Settings → Personal Access Tokens → Fine-grained tokens
2. Click **Generate new token**
3. Name: `fitness-gist-write`
4. Expiration: 1 year
5. Permissions: **Gists** → Read and Write
6. Generate and **copy the token** (you won't see it again)

---

## Step 5 — Add secrets to your GitHub repo

1. Go to your repo → **Settings** → **Secrets and variables** → **Actions**
2. Add these secrets:

| Secret name        | Value                                      |
|--------------------|--------------------------------------------|
| `GIST_ID`          | Your Gist ID from Step 3                  |
| `DATA_GITHUB_TOKEN`| Your PAT from Step 4                      |
| `SHEET_CSV_URL`    | Your Google Sheet CSV URL (see Step 7)    |

---

## Step 6 — Set up the iOS Shortcut

Create a new Shortcut in the Shortcuts app with these actions:

### Actions (in order):

**1. Find Workouts**
- Find: All Workouts
- Filter: Start Date is in the last 2 Days
- Sort by: Start Date (newest first)
- Limit: 30

**2. Repeat with each item in Workouts**

  Inside the repeat loop:

  **2a. Get Details of Workout** (repeat for each field):
  - Workout Type → save to variable `wType`
  - Duration (in minutes) → save to variable `wMins`
  - Active Energy Burned (kcal) → save to variable `wCals`
  - Start Date → save to variable `wDate`

  **2b. Dictionary** — create a dictionary:
  ```
  date          → wDate (formatted as YYYY-MM-DD)
  workout_type  → wType
  duration_minutes → wMins (as number)
  calories      → wCals (as number)
  ```

  **2c. Add Dictionary to variable** `AllWorkouts` (list)

**3. Get contents of URL** (to fetch existing Gist)
- URL: `https://api.github.com/gists/YOUR_GIST_ID`
- Method: GET
- Headers:
  - `Authorization`: `token YOUR_PAT_HERE`
  - `Accept`: `application/vnd.github+json`

**4. Get Dictionary from Input** (parse the response)

**5. Get Dictionary Value** for key `files` → then key `workouts.json` → then key `content`

**6. Get JSON from Input** → save to `ExistingWorkouts` (this is the existing array)

**7. Combine Variable** — merge `ExistingWorkouts` + `AllWorkouts`, deduplicate by date+type

  *(In practice: append AllWorkouts to ExistingWorkouts, then use a dedup step or just replace — keeping last 60 days is fine)*

**8. Get contents of URL** (to update Gist)
- URL: `https://api.github.com/gists/YOUR_GIST_ID`
- Method: PATCH
- Headers:
  - `Authorization`: `token YOUR_PAT_HERE`
  - `Content-Type`: `application/json`
- Body (JSON):
  ```json
  {
    "files": {
      "workouts.json": {
        "content": "[COMBINED_JSON_HERE]"
      }
    }
  }
  ```

> **Tip:** Run this Shortcut from your Lock Screen widget, or use the
> Automation tab to trigger it automatically when you close the Workout app.

---

## Step 7 — Set up Google Sheets overrides

1. Create a new Google Sheet
2. Row 1 headers (exactly):
   ```
   date | exercise_done | workout_type | calories | minutes | notes
   ```
3. Example override row:
   ```
   2025-03-15 | yes | Running | 450 | 38 | Ran 5k, forgot to start watch
   ```
4. Publish the sheet as CSV:
   - File → Share → Publish to web
   - Select the sheet tab → CSV format
   - Copy the URL → add as `SHEET_CSV_URL` secret in GitHub

5. Share the Google Sheet with your partner (Edit access) so they can add overrides too.

> Overrides win over Apple Health data. Leave cells blank to keep the original value.

---

## Step 8 — Access control (password protection)

GitHub Pages on a private repo are still publicly accessible by URL.
To restrict access to just you and one other person:

### Option A — Simple password overlay (easiest)
Add this to the top of `index.html` before the `<div class="page">`:

```html
<script>
  const PASSWORD = "your-secret-word-here";
  if (localStorage.getItem('auth') !== PASSWORD) {
    const p = prompt('Password:');
    if (p === PASSWORD) localStorage.setItem('auth', p);
    else { document.body.innerHTML = 'Access denied.'; }
  }
</script>
```

Share the URL + password with your partner. Simple, not cryptographically secure,
but fine for personal health data between two people.

### Option B — Netlify password protection (more secure, still free)
1. Connect your GitHub repo to Netlify (netlify.com)
2. Enable **Password Protection** under Site Settings → Access Control
3. Set one shared password
4. Netlify re-deploys automatically on every GitHub push

---

## Troubleshooting

**Dashboard shows "Could not load data.json"**
→ GitHub Actions hasn't run yet. Go to repo → Actions → run the workflow manually.

**Gist update fails in Shortcut**
→ Check your PAT hasn't expired. Regenerate and update the Shortcut.

**Overrides not showing**
→ Make sure SHEET_CSV_URL is the "Published to web" CSV link, not the normal sheet URL.

**Wrong timezone on dates**
→ The Shortcut formats dates — make sure you format wDate as `YYYY-MM-DD` in your local timezone in the Shortcut Date Formatting action.
