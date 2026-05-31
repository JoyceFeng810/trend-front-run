# trend-front-run

Weekly AI-powered trend intelligence agent that scans TikTok, YouTube, and Reddit to surface early consumer signals in beauty, fashion, consumer tech, fintech, and wellness — before they show up in earnings calls.

Delivers a Monday morning email digest: each signal includes a title, brand, ticker, stage (Emerging / Accelerating / Mainstream), trend score (1–10), catalyst, and risk.

---

## How It Works

1. **GitHub Actions** triggers the agent every Monday at ~9 am PT via cron
2. **Claude Opus 4.8** (`claude-opus-4-8`) searches the live web for each of 5 sectors using the built-in `web_search` server-side tool
3. Each signal is scored and structured as JSON
4. **SendGrid** delivers a formatted HTML digest to your inbox
5. Signals are saved to a local **SQLite** database (`briefings.db`)

---

## Project Structure

```
agent/
  agent.py          # Orchestrator — 5-sector scan via Anthropic SDK + web_search
  email_digest.py   # Renders HTML email cards and sends via SendGrid
  storage.py        # SQLite briefing history (briefings.db)
.github/
  workflows/
    weekly_brief.yml  # Cron: every Monday ~9 am PT
requirements.txt
```

---

## Setup

### 1. Clone & install

```bash
git clone https://github.com/YOUR_USERNAME/trend-front-run.git
cd trend-front-run
pip install -r requirements.txt
```

### 2. GitHub Secrets (for the automated workflow)

In your repository go to **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret | Where to get it |
|--------|-----------------|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) → API Keys |
| `SENDGRID_API_KEY` | [app.sendgrid.com](https://app.sendgrid.com/settings/api_keys) → Create key with **Mail Send** permission only |
| `DIGEST_EMAIL` | Your email address — must be [verified as a SendGrid sender](https://docs.sendgrid.com/ui/sending-email/sender-verification) |

> **Security note:** GitHub Actions secrets are encrypted at rest and are never printed in workflow logs. Even if a step accidentally echoes an environment variable, GitHub automatically redacts known secret values. The `briefings.db` database created at runtime is discarded after each job — nothing sensitive is written to the repository. See [GitHub docs on encrypted secrets](https://docs.github.com/en/actions/security-guides/encrypted-secrets) for details.

### 3. Run locally

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export SENDGRID_API_KEY="SG...."
export DIGEST_EMAIL="you@example.com"

python -m agent.agent
```

For a one-off test without sending email, you can comment out the `email_digest.send_digest(...)` line in `agent/agent.py`.

---

## Trend Score Reference

| Score | Stage | Meaning |
|-------|-------|---------|
| 9–10 | Emerging | Breaking signal (<48 h), multi-platform, clear earnings catalyst |
| 7–8 | Emerging / Accelerating | Strong (1–3 days), traceable to specific creator / product |
| 5–6 | Accelerating | Moderate, one primary platform, indirect brand connection |
| 3–4 | Accelerating / Mainstream | Weak, limited breadth, speculative thesis |
| 1–2 | Mainstream | Priced in, informational only |

---

## Notes

- **Secrets never leave GitHub Actions.** All three secrets are injected as environment variables and automatically redacted in logs. No secret is committed to the repository or written to any file on disk.
- **Database persistence.** `briefings.db` is created in the project root during each run. In GitHub Actions the workspace is ephemeral, so history does not persist between runs. To persist it, add a step to commit the file back to the repo (with caution) or push it to an external store.
- **Cron timing.** The workflow runs at `0 17 * * 1` (17:00 UTC). That's ~9 am PT during standard time (UTC−8) and ~10 am PT during daylight saving time (UTC−7).
- **Sender verification.** `DIGEST_EMAIL` is used as both the sender and recipient address. It must be [verified in SendGrid](https://docs.sendgrid.com/ui/sending-email/sender-verification). If you want a different from address, set `FROM_EMAIL` as an additional secret.
- **Not investment advice.** Signals are for informational purposes only.
