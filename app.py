import os
import re
import requests
from flask import Flask, request, jsonify, render_template_string
import anthropic

app = Flask(__name__)

# ── HTML Template ────────────────────────────────────────────────────────────

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>EFS Ad Generator</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: 'Inter', sans-serif;
      background: #f5f7fa;
      color: #1a1a2e;
      min-height: 100vh;
      padding: 40px 20px;
    }

    .container {
      max-width: 820px;
      margin: 0 auto;
    }

    .logo {
      display: block;
      height: 36px;
      margin-bottom: 32px;
    }

    h1 {
      font-size: 28px;
      font-weight: 700;
      color: #0d1b4b;
      margin-bottom: 8px;
    }

    .subtitle {
      font-size: 15px;
      color: #5a6a85;
      margin-bottom: 32px;
    }

    .card {
      background: #fff;
      border-radius: 12px;
      padding: 32px;
      box-shadow: 0 2px 12px rgba(0,0,0,0.07);
      margin-bottom: 28px;
    }

    label {
      display: block;
      font-size: 13px;
      font-weight: 600;
      color: #0d1b4b;
      margin-bottom: 8px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }

    input[type="text"], input[type="url"], textarea {
      width: 100%;
      padding: 12px 16px;
      border: 1.5px solid #dde3ee;
      border-radius: 8px;
      font-size: 15px;
      font-family: 'Inter', sans-serif;
      color: #1a1a2e;
      background: #fafbfd;
      transition: border-color 0.2s;
      outline: none;
    }

    input[type="text"]:focus, input[type="url"]:focus, textarea:focus {
      border-color: #2563eb;
      background: #fff;
    }

    textarea {
      resize: vertical;
      min-height: 140px;
    }

    .hint {
      font-size: 12px;
      color: #8a96a8;
      margin-top: 6px;
    }

    .field {
      margin-bottom: 22px;
    }

    .divider {
      text-align: center;
      font-size: 13px;
      color: #8a96a8;
      margin: 18px 0;
      position: relative;
    }

    .divider::before, .divider::after {
      content: '';
      position: absolute;
      top: 50%;
      width: 44%;
      height: 1px;
      background: #dde3ee;
    }

    .divider::before { left: 0; }
    .divider::after { right: 0; }

    .btn {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      background: #2563eb;
      color: #fff;
      font-size: 15px;
      font-weight: 600;
      padding: 14px 32px;
      border: none;
      border-radius: 8px;
      cursor: pointer;
      width: 100%;
      justify-content: center;
      transition: background 0.2s;
    }

    .btn:hover { background: #1d4ed8; }
    .btn:disabled { background: #93b4f5; cursor: not-allowed; }

    .spinner {
      display: none;
      width: 18px;
      height: 18px;
      border: 2px solid rgba(255,255,255,0.4);
      border-top-color: #fff;
      border-radius: 50%;
      animation: spin 0.7s linear infinite;
    }

    @keyframes spin { to { transform: rotate(360deg); } }

    #output {
      display: none;
    }

    .output-section {
      margin-bottom: 28px;
    }

    .output-section h2 {
      font-size: 16px;
      font-weight: 700;
      color: #0d1b4b;
      margin-bottom: 14px;
      padding-bottom: 10px;
      border-bottom: 2px solid #e8edf5;
    }

    .ad-block {
      background: #f5f7fa;
      border-radius: 8px;
      padding: 18px 20px;
      margin-bottom: 14px;
      position: relative;
    }

    .ad-block h3 {
      font-size: 13px;
      font-weight: 600;
      color: #2563eb;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 10px;
    }

    .ad-block p, .ad-block li {
      font-size: 14px;
      line-height: 1.65;
      color: #2d3748;
    }

    .ad-block ul {
      padding-left: 18px;
    }

    .copy-btn {
      position: absolute;
      top: 14px;
      right: 14px;
      background: #fff;
      border: 1.5px solid #dde3ee;
      border-radius: 6px;
      padding: 4px 10px;
      font-size: 12px;
      font-weight: 600;
      color: #5a6a85;
      cursor: pointer;
      transition: all 0.15s;
    }

    .copy-btn:hover {
      background: #2563eb;
      color: #fff;
      border-color: #2563eb;
    }

    .error-box {
      background: #fff5f5;
      border: 1.5px solid #feb2b2;
      border-radius: 8px;
      padding: 16px 20px;
      color: #c53030;
      font-size: 14px;
      margin-top: 16px;
      display: none;
    }
  </style>
</head>
<body>
  <div class="container">
    <img src="https://assets.cdn.filesafe.space/tq6XOnCnirPu6tiBRkvb/media/67d1bf6fc9434cc05c352304.png" class="logo" alt="Excelsior Franchise Solutions" />

    <h1>Ad Copy Generator</h1>
    <p class="subtitle">Paste your Google Doc link or paste your workbook content below. We will generate your Meta ad copy and audience targeting in seconds.</p>

    <div class="card">
      <div class="field">
        <label>Google Doc Link</label>
        <input type="url" id="docUrl" placeholder="https://docs.google.com/document/d/..." />
        <p class="hint">Make sure the doc is set to "Anyone with the link can view."</p>
      </div>

      <div class="divider">or paste content directly</div>

      <div class="field">
        <label>Workbook Content</label>
        <textarea id="docText" placeholder="Paste your Franchise Expansion Workbook content here..."></textarea>
      </div>

      <button class="btn" id="generateBtn" onclick="generate()">
        <span class="spinner" id="spinner"></span>
        <span id="btnText">Generate Ad Copy</span>
      </button>

      <div class="error-box" id="errorBox"></div>
    </div>

    <div id="output">
      <div class="card output-section">
        <h2>Meta Ad Copy</h2>
        <div id="adCopy"></div>
      </div>
      <div class="card output-section">
        <h2>Audience Targeting</h2>
        <div id="audienceTargeting"></div>
      </div>
    </div>
  </div>

  <script>
    async function generate() {
      const docUrl = document.getElementById('docUrl').value.trim();
      const docText = document.getElementById('docText').value.trim();
      const btn = document.getElementById('generateBtn');
      const spinner = document.getElementById('spinner');
      const btnText = document.getElementById('btnText');
      const errorBox = document.getElementById('errorBox');

      if (!docUrl && !docText) {
        showError('Please provide a Google Doc link or paste your workbook content.');
        return;
      }

      btn.disabled = true;
      spinner.style.display = 'block';
      btnText.textContent = 'Generating...';
      errorBox.style.display = 'none';
      document.getElementById('output').style.display = 'none';

      try {
        const res = await fetch('/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ doc_url: docUrl, doc_text: docText })
        });

        const data = await res.json();

        if (!res.ok || data.error) {
          showError(data.error || 'Something went wrong. Please try again.');
          return;
        }

        renderOutput(data);
      } catch (e) {
        showError('Network error. Please check your connection and try again.');
      } finally {
        btn.disabled = false;
        spinner.style.display = 'none';
        btnText.textContent = 'Generate Ad Copy';
      }
    }

    function renderOutput(data) {
      const adCopyDiv = document.getElementById('adCopy');
      const audienceDiv = document.getElementById('audienceTargeting');

      adCopyDiv.innerHTML = '';
      audienceDiv.innerHTML = '';

      if (data.ads && data.ads.length) {
        data.ads.forEach((ad, i) => {
          const block = document.createElement('div');
          block.className = 'ad-block';
          block.innerHTML = `
            <button class="copy-btn" onclick="copyBlock(this)">Copy</button>
            <h3>Ad ${i + 1}${ad.label ? ' — ' + ad.label : ''}</h3>
            <p style="white-space: pre-wrap;">${escHtml(ad.copy)}</p>
          `;
          adCopyDiv.appendChild(block);
        });
      }

      if (data.audiences && data.audiences.length) {
        data.audiences.forEach(aud => {
          const block = document.createElement('div');
          block.className = 'ad-block';
          let listsHtml = '';
          if (aud.interests && aud.interests.length) {
            listsHtml += `<p style="margin-top:8px;font-weight:600;font-size:13px;">Interests</p><ul>${aud.interests.map(i => `<li>${escHtml(i)}</li>`).join('')}</ul>`;
          }
          if (aud.behaviors && aud.behaviors.length) {
            listsHtml += `<p style="margin-top:10px;font-weight:600;font-size:13px;">Behaviors</p><ul>${aud.behaviors.map(b => `<li>${escHtml(b)}</li>`).join('')}</ul>`;
          }
          if (aud.demographics) {
            listsHtml += `<p style="margin-top:10px;font-weight:600;font-size:13px;">Demographics</p><p>${escHtml(aud.demographics)}</p>`;
          }
          if (aud.gemini_prompt) {
            listsHtml += `<p style="margin-top:10px;font-weight:600;font-size:13px;">Gemini Creative Prompt</p><p style="white-space:pre-wrap;">${escHtml(aud.gemini_prompt)}</p>`;
          }
          block.innerHTML = `
            <button class="copy-btn" onclick="copyBlock(this)">Copy</button>
            <h3>${escHtml(aud.name || 'Audience')}</h3>
            ${listsHtml}
          `;
          audienceDiv.appendChild(block);
        });
      }

      document.getElementById('output').style.display = 'block';
      document.getElementById('output').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function copyBlock(btn) {
      const block = btn.parentElement;
      const clone = block.cloneNode(true);
      clone.querySelector('.copy-btn').remove();
      const text = clone.innerText;
      navigator.clipboard.writeText(text).then(() => {
        btn.textContent = 'Copied!';
        setTimeout(() => btn.textContent = 'Copy', 1800);
      });
    }

    function showError(msg) {
      const box = document.getElementById('errorBox');
      box.textContent = msg;
      box.style.display = 'block';
    }

    function escHtml(str) {
      return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }
  </script>
</body>
</html>
"""

# ── System Prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert direct-response copywriter and Meta Ads strategist specializing in franchise consultant lead generation.

You will receive the content of a Franchise Expansion Workbook from a franchise consultant. Your job is to extract the key information and produce two things:

1. THREE Meta ad copy variations (primary text, headline, description) optimized for lead generation. Each ad should:
   - Speak directly to the ideal candidate described in the workbook
   - Lead with a pain point or aspiration, not the brand name
   - Use plain, conversational language at a 5th grade reading level
   - Avoid the word "franchise" — use "start your own business" or "business ownership" instead
   - End with a clear call to action (Book a call, Learn more, Apply now)
   - Be formatted as: PRIMARY TEXT (up to 125 characters for feed), HEADLINE (up to 40 characters), DESCRIPTION (up to 30 characters)

2. TWO audience targeting profiles for Meta Ads Manager, each with:
   - A name for the audience
   - Specific interest targeting suggestions (exact Meta interest names where possible)
   - Behavior targeting suggestions
   - Demographics (age range, income level, location if specified)
   - A Gemini image generation prompt to create a matching ad creative

Return your response as valid JSON in this exact structure:
{
  "ads": [
    {
      "label": "Pain Point Hook",
      "copy": "PRIMARY TEXT: ...\\nHEADLINE: ...\\nDESCRIPTION: ..."
    },
    {
      "label": "Aspiration Hook",
      "copy": "PRIMARY TEXT: ...\\nHEADLINE: ...\\nDESCRIPTION: ..."
    },
    {
      "label": "Social Proof Hook",
      "copy": "PRIMARY TEXT: ...\\nHEADLINE: ...\\nDESCRIPTION: ..."
    }
  ],
  "audiences": [
    {
      "name": "Audience Name",
      "interests": ["interest 1", "interest 2"],
      "behaviors": ["behavior 1", "behavior 2"],
      "demographics": "Ages 35-55, HHI $75K+, United States",
      "gemini_prompt": "Describe the image to generate for this ad..."
    },
    {
      "name": "Audience Name 2",
      "interests": ["interest 1", "interest 2"],
      "behaviors": ["behavior 1"],
      "demographics": "Ages 40-60, HHI $100K+, United States",
      "gemini_prompt": "Describe the image to generate for this ad..."
    }
  ]
}

Return ONLY the JSON. No explanation, no markdown fences, no extra text."""

# ── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template_string(HTML)


@app.route('/generate', methods=['POST'])
def generate():
    data = request.get_json(force=True)
    doc_url = (data.get('doc_url') or '').strip()
    doc_text = (data.get('doc_text') or '').strip()

    # Fetch Google Doc content if URL provided
    if doc_url and not doc_text:
        try:
            # Convert Google Doc URL to export URL
            match = re.search(r'/document/d/([a-zA-Z0-9_-]+)', doc_url)
            if not match:
                return jsonify({'error': 'Invalid Google Doc URL. Make sure you paste the full link.'}), 400
            doc_id = match.group(1)
            export_url = f'https://docs.google.com/document/d/{doc_id}/export?format=txt'
            resp = requests.get(export_url, timeout=15)
            if resp.status_code != 200:
                return jsonify({'error': 'Could not access the Google Doc. Make sure it is set to "Anyone with the link can view."'}), 400
            doc_text = resp.text.strip()
        except Exception as e:
            return jsonify({'error': f'Failed to fetch Google Doc: {str(e)}'}), 500

    if not doc_text:
        return jsonify({'error': 'No workbook content found. Please provide a Google Doc link or paste your content.'}), 400

    # Truncate to avoid token limits
    if len(doc_text) > 12000:
        doc_text = doc_text[:12000] + '\n\n[Content truncated for processing]'

    # Call Anthropic API
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return jsonify({'error': 'API key not configured. Please set the ANTHROPIC_API_KEY environment variable.'}), 500

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model='claude-opus-4-5',
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    'role': 'user',
                    'content': f'Here is the Franchise Expansion Workbook content:\n\n{doc_text}'
                }
            ]
        )
        raw = message.content[0].text.strip()

        # Strip markdown fences if present
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'^```\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)

        import json
        result = json.loads(raw)
        return jsonify(result)

    except Exception as e:
        return jsonify({'error': f'Generation failed: {str(e)}'}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
