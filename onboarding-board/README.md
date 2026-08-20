# Client Onboarding Board

Internal ops dashboard for Excelsior Franchise Solutions. Tracks every client
from onboarding forms through to fully live, fed automatically by a
GoHighLevel webhook.

Replaces the color-coded onboarding spreadsheet. Runs as its own service,
separate from anything client-facing.

---

## Setup (one time, about 5 minutes)

### 1. Deploy it

In Railway: **New Project → Deploy from GitHub repo →** pick `efs-ad-generator`.

Then open the new service → **Settings → Source → Root Directory** and set it to:

```
onboarding-board
```

That tells Railway to build only this folder, so the board runs as its own
service with its own URL, completely separate from the ad generator. They share
a repository but nothing else — separate deploys, separate uptime.

### 2. Add a database

In the same project: **⌘K → Add PostgreSQL**.

Railway connects it automatically. Do this before you add real clients —
without it, the board is wiped on every redeploy.

### 3. Set three variables

Click the app service → **Variables**:

| Variable | Value |
|----------|-------|
| `DASHBOARD_PASSWORD` | The password your team types to get in |
| `WEBHOOK_SECRET` | Any long random string. Goes in the GHL webhook URL. |
| `SECRET_KEY` | Any long random string. Keeps people signed in across deploys. |

That's it. Open the Railway URL and you are on the board.

Optional: `STUCK_AFTER_DAYS` (defaults to 7) sets how many days without
movement before a client is flagged as stuck.

---

## Connect GoHighLevel

1. Open the workflow that fires when a client submits their onboarding form.
2. Add a **Webhook** action, method **POST**, URL:

```
https://your-app.up.railway.app/webhook/ghl?token=YOUR_WEBHOOK_SECRET
```

3. Send whatever contact fields you have.

A new contact becomes a new row with stage 1 marked done. The endpoint reads
any nesting depth and recognises the usual GHL field names (`full_name`,
`first_name`/`last_name`, `contact.email`, `company_name`,
`customData.website`, `account_manager`, `contact_id`, `locationId`), so you
rarely have to rename anything. Both JSON and form-encoded bodies work.
Anything it does not recognise is stored and shown on the client's detail
panel, so nothing submitted is lost.

Clients are matched by email, then GHL contact id, then name, so repeat
submissions update the same row instead of creating a duplicate. Webhook
updates only fill in blank fields — they never overwrite a manual edit.

### Advancing stages from GHL (optional)

Add a `stage` field to any webhook and the board moves that client along
without anyone clicking:

```json
{ "email": "jane@acme.com", "stage": "A2P Complete" }
```

`stage` accepts the label or the key. `stage_status` accepts done, in_progress,
or blocked plus common synonyms; it defaults to done. An unrecognised stage is
ignored rather than erroring, so a misconfigured workflow never drops a contact.

The same reference is in the **Webhook setup** button in the board's top bar.

---

## The pipeline

| # | Stage | Meaning |
|---|-------|---------|
| 1 | Contract Signed | Deal closed. Creating the client here means the wait before they start is measured, not hidden. |
| 2 | Onboarding Forms Complete | They submitted their onboarding forms |
| 3 | Onboarding Call | Kickoff call happened |
| 4 | GHL Account Set Up | Their GoHighLevel sub-account is built |
| 5 | Website Updates Made | Their site is updated for A2P registration |
| 6 | A2P Submitted | 10DLC registration submitted to the carriers |
| 7 | A2P Complete | Registration came back approved |
| 8 | Workbook Complete | Their workbook is finished |
| 9 | Ads Created | Ads are built |
| 10 | CloseBot Set Up | CloseBot is configured and connected |
| 11 | Final Review Complete | Internal review signed off |
| 12 | All Systems Live | Everything is running |

The first three stages come straight from GoHighLevel, which already knows all
of them — see **Connect GoHighLevel** below. They give you three measures that
are otherwise invisible: how long clients take to do their homework
(contract to forms), booking lag (forms to call), and delivery speed (call to
live).

Every cell is **not started**, **in progress**, **blocked**, or **done**.
Click a cell to change it.

To rename, add, or remove a stage, edit `STAGES` at the top of `db.py`. Add the
old key to `RENAMED_STAGE_KEYS` in the same file and existing history carries
over instead of resetting.

---

## What it measures

- **Median and average time to live**, plus fastest and slowest client
- **Average and median days per stage**, with the slowest stage flagged —
  this is the bottleneck answer
- **Here now** — how many clients sit on each stage and the longest wait
- **Stuck list** — anyone who has not moved in `STUCK_AFTER_DAYS` days
- **Where is client X** — search, then read their stage timeline with the
  actual days each step took

Stage timings come from completion timestamps: a stage's duration is the time
between the previous stage completing and this one completing. The team only
marks things done — the metrics fall out of that.

`GET /api/export.csv` gives you the whole board including per-stage day counts.

---

## Local testing

```
pip install -r requirements.txt
export DEV_INSECURE_COOKIES=1
python app.py
```

Open http://localhost:5000

Without `DATABASE_URL` it uses a local SQLite file (`onboarding.db`, override
with `DB_PATH`). On Railway, always use Postgres.
