# EFS Ad Generator

Reads a franchise consultant's Franchise Expansion Workbook and generates Meta ad copy and audience targeting recommendations using Claude.

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
python app.py
```

Open http://localhost:5000
