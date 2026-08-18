# EFS Ad Generator

Two tools in one Flask app:

- **`/`** — Ad Copy Generator. Reads a franchise consultant's Franchise Expansion Workbook and generates Meta ad copy and audience targeting recommendations using Claude. Client-facing, embedded in Circle.
- **`/onboarding`** — Client Onboarding board. Internal ops dashboard that replaces the color-coded onboarding spreadsheet, fed automatically from GoHighLevel. See [Client Onboarding Dashboard](#client-onboarding-dashboard) below.

---

## Deploy to Railway (5 minutes)

### Step 1 — Create a Railway account
Go to railway.app and sign up with GitHub.

### Step 2 — Create a new project
Click "New Project" then "Deploy from GitHub repo." Connect your GitHub account and push this folder as a repo, or use "Deploy from local directory" with the Railway CLI.

**Fastest option — Railway CLI:**
```
npm install -g @railway/cli
cd efs_ad_generator
railway login
railway init
railway up
```

### Step 3 — Set your API key
In the Railway dashboard, go to your project, click "Variables," and add:

```
ANTHROPIC_API_KEY = your-key-here
```

Your key is at console.anthropic.com under API Keys.

### Step 4 — Get your URL
Railway gives you a public URL like `https://efs-ad-generator-production.up.railway.app`. That is the URL you embed in Circle.

---

## Embed in Circle

1. In your Circle community, go to the space where you want the tool
2. Create a new Custom Page
3. Paste your Railway URL as the embed URL
4. Members see the tool inside Circle without leaving the community

---

## Local Testing

```
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your-key-here
export DEV_INSECURE_COOKIES=1     # lets the dashboard login work over plain http
python app.py
```

Open http://localhost:5000 for the ad generator, http://localhost:5000/onboarding for the board.

---

# Client Onboarding Dashboard

An internal board at `/onboarding` that tracks every client from sold to live.
Same left-to-right stages as the old color-coded sheet, but the data comes in
from GoHighLevel on its own and the timings are calculated for you.

## Why not do this in Circle

Circle is a community platform — posts, spaces, courses, members. It has no
per-client pipeline object, no stage tracking, and no webhook ingest, so there
is nothing there to build this on. What Circle does have is Custom Pages that
embed an external URL, which is how the ad generator already lives inside the
community. This board deploys the same way if you want it in a private team
space, or you can just bookmark the Railway URL.

## The pipeline

| # | Stage | Meaning |
|---|-------|---------|
| 1 | Onboarding Forms Complete | They submitted their onboarding forms |
| 2 | GHL Account Set Up | Their GoHighLevel sub-account is built |
| 3 | Website Updates Made | Their site is updated for A2P registration |
| 4 | A2P Submitted | 10DLC registration submitted to the carriers |
| 5 | A2P Complete | Registration came back approved |
| 6 | Workbook Complete | Their workbook is finished |
| 7 | Ads Created | Ads are built |
| 8 | CloseBot Set Up | CloseBot is configured and connected |
| 9 | Final Review Complete | Internal review signed off |
| 10 | All Systems Live | Everything is running |

Each cell is **not started**, **in progress**, **blocked**, or **done** — one
more state than the sheet had, so a stalled client is visibly stalled rather
than just uncolored. Click any cell to change it.

## What it measures

The point of the board is the numbers down the side, not the colors:

- **Median and average time to live** — plus the fastest and slowest client, so
  one bad outlier does not distort the picture.
- **Average and median days per stage** — the "Stage performance" panel ranks
  every stage and tags the slowest one. This is the bottleneck answer.
- **Here now** — how many clients are sitting on each stage at this moment,
  and how long the longest-waiting one has been there.
- **Stuck list** — anyone who has not moved in 7+ days (tune with
  `STUCK_AFTER_DAYS`), sorted worst first.
- **Where is client X** — search by name, company, or email; the drawer shows
  their stage timeline with how many days each step actually took.

Stage timings are derived from completion timestamps: a stage's duration is the
time between the previous stage completing and this one completing. The team
only marks things done, exactly like the sheet — the metrics fall out of that.

Hit `/api/export.csv` for the whole board including per-stage day counts, if
you want to pivot it in Sheets.

## Connect GoHighLevel

1. In GHL, open the workflow that fires when a client is onboarded.
2. Add a **Webhook** action, method **POST**, URL:
   `https://your-app.up.railway.app/webhook/ghl?token=YOUR_WEBHOOK_SECRET`
3. Send whatever contact fields you have.

The endpoint reads any nesting depth and recognises the usual GHL field names
(`full_name`, `first_name`/`last_name`, `contact.email`, `company_name`,
`customData.website`, `account_manager`, `contact_id`, `locationId`, and so on),
so you rarely have to rename anything. Both JSON and form-encoded bodies work.
Anything it does not recognise is stored verbatim and shown on the client's
detail panel, so no submitted data is lost.

Matching is by email, then GHL contact id, then name — repeat submissions update
the same client instead of creating a duplicate. Webhook updates only fill in
blank fields, so they never overwrite something a person edited by hand. A new
client is automatically marked Onboarding Forms Complete, since submitting
that form is what triggered the webhook.

**Advancing stages from GHL (optional).** Add a `stage` field to any webhook and
the board moves that client along without anyone clicking:

```json
{ "email": "jane@acme.com", "stage": "A2P Complete", "stage_status": "done" }
```

`stage` accepts the label or the key. `stage_status` accepts done, in_progress,
or blocked, plus common synonyms (approved, submitted, rejected, complete); it
defaults to done. An unrecognised stage is ignored rather than erroring, so a
misconfigured workflow never drops the contact.

## Configuration

Set these in Railway under **Variables**:

| Variable | Required | Purpose |
|----------|----------|---------|
| `DATABASE_URL` | Strongly recommended | Postgres connection string. Add a Postgres service in Railway and it is injected automatically. Without it the app falls back to a local SQLite file that is **wiped on every redeploy**. |
| `DASHBOARD_PASSWORD` | Yes | Team password for `/onboarding`. Without it the board is open to anyone with the URL. |
| `WEBHOOK_SECRET` | Yes | Shared secret for `/webhook/ghl`, sent as `?token=` or an `X-Webhook-Secret` header. Without it anyone can post data in. |
| `SECRET_KEY` | Recommended | Signs session cookies. If unset a random one is generated at boot, which signs everyone out on each redeploy. |
| `STUCK_AFTER_DAYS` | No | Days of no movement before a client counts as stuck. Defaults to 7. |
| `ANTHROPIC_API_KEY` | Yes | For the ad generator. |
| `DEV_INSECURE_COOKIES` | Local only | Set to `1` to sign in over plain http while testing. |

The board warns you on screen until `DASHBOARD_PASSWORD` and `WEBHOOK_SECRET`
are set.

If you stay on SQLite, run a single gunicorn worker — concurrent writers will
contend for the file lock. Postgres has no such limit.
