"""
Weekly trend intelligence agent.

Scans five consumer sectors using Claude claude-opus-4-8 + web_search, scores each
viral signal, saves to SQLite, and emails a digest via SendGrid.

Usage (from project root):
    python -m agent.agent
"""

import datetime
import json
import os
import re
import sys

import anthropic

from . import email_digest
from . import storage


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a proactive trend-to-alpha investment intelligence analyst. Your edge is \
spotting consumer viral moments on TikTok, YouTube, Reddit, and Google Trends \
BEFORE Wall Street prices them in.

Your audience is a quant/MLE in fintech risk with deep domain knowledge in \
beauty, fashion, tech, and data. Write with precision — specific view counts, \
creator handles, subreddit names, and ticker symbols wherever available.

SIGNAL METHODOLOGY
Find the moment when a brand, product, or consumer behaviour transitions from \
viral social media phenomenon to earnings impact. Look for:
  - TikTok videos (>500K views), YouTube trending, top Reddit posts in \
consumer subreddits (r/beauty, r/malegrooming, r/investing, r/personalfinance)
  - A specific, traceable catalyst: creator handle, post title, view count
  - A publicly traded parent company that stands to benefit or be hurt

SIGNAL STAGES
  Emerging    — viral <48-72 h, not yet in financial media
  Accelerating — growing 1-3 days, appearing in niche finance blogs
  Mainstream  — already in WSJ/Bloomberg/CNBC, likely priced in

TREND SCORE (1-10)
  9-10  Breaking (<48 h), multi-platform, clear earnings catalyst
  7-8   Strong (1-3 days), traceable to specific brand / creator
  5-6   Moderate, single platform, indirect brand link
  3-4   Weak, limited breadth, speculative thesis
  1-2   Mainstream, informational only

REQUIRED OUTPUT
Return ONLY valid JSON — no markdown, no prose, no explanation:
{
  "signals": [
    {
      "title":       "Short punchy title (max 8 words)",
      "brand":       "Brand or company name",
      "ticker":      "EXCH:SYMBOL, or Pre-IPO, or Private",
      "stage":       "Emerging | Accelerating | Mainstream",
      "trend_score": 9,
      "sources":     ["TikTok", "YouTube", "Reddit", "Google Trends", "News"],
      "signal":      "2-3 sentence summary of the trend and WHY it matters for investors",
      "catalyst":    "The specific viral moment — creator @handle, view count, subreddit thread",
      "risk":        "1 sentence key risk",
      "sector":      "beauty | fashion | tech | fintech | wellness"
    }
  ],
  "macro_note": "1 sentence big-picture observation across all sectors this week"
}"""

SECTOR_PROMPTS: dict[str, str] = {
    "beauty": (  # key matches dashboard sector IDs
        "Search the web for the top 2-3 viral beauty and skincare brand moments from "
        "the past 7 days on TikTok, YouTube, and Reddit. Focus on: product launches "
        "going viral, creator-driven ingredient trends (retinol, SPF, peptides, "
        "niacinamide), hero-product moments, and brand sentiment shifts. Target "
        "publicly traded parent companies: L'Oréal (EPA:OR), Estée Lauder (NYSE:EL), "
        "e.l.f. Beauty (NYSE:ELF), Coty (NYSE:COTY), Procter & Gamble (NYSE:PG), "
        "Unilever (NYSE:UL), Beiersdorf (ETR:BEI). "
        "Apply signal scoring methodology and return signals as JSON."
    ),
    "fashion": (
        "Search the web for the top 2-3 viral fashion and apparel brand moments from "
        "the past 7 days on TikTok, YouTube, and Reddit. Focus on: streetwear drops, "
        "viral fits, aesthetic micro-trends (e.g., mob wife, clean girl, gorpcore), "
        "and resale market signals (StockX velocity, GOAT listings). Target publicly "
        "traded companies: LVMH (EPA:MC), Kering (EPA:KER), Tapestry (NYSE:TPR), "
        "Capri Holdings (NYSE:CPRI), PVH (NYSE:PVH), Lululemon (NASDAQ:LULU), "
        "Gap (NYSE:GPS), Nike (NYSE:NKE), On Holding (NYSE:ONON). "
        "Apply signal scoring methodology and return signals as JSON."
    ),
    "tech": (
        "Search the web for the top 2-3 viral consumer technology product moments from "
        "the past 7 days on TikTok, YouTube, and Reddit. Focus on: unboxing viral "
        "moments, app download spikes on App Store / Play Store charts, gadget reviews "
        "going viral, AI product launches, and consumer electronics buzz. Target "
        "publicly traded companies: Apple (NASDAQ:AAPL), Meta (NASDAQ:META), "
        "Alphabet (NASDAQ:GOOGL), Sony (NYSE:SONY), Sonos (NASDAQ:SONO), "
        "GoPro (NASDAQ:GPRO), Snap (NYSE:SNAP), Spotify (NYSE:SPOT). "
        "Apply signal scoring methodology and return signals as JSON."
    ),
    "fintech": (
        "Search the web for the top 2-3 viral fintech and personal finance brand moments "
        "from the past 7 days on TikTok, YouTube, and Reddit. Focus on: viral money-tip "
        "videos naming specific apps, BNPL trend spikes, crypto sentiment shifts, "
        "neobank buzz, and investment app adoption. Target publicly traded companies: "
        "PayPal (NASDAQ:PYPL), Block (NYSE:SQ), SoFi (NASDAQ:SOFI), "
        "Robinhood (NASDAQ:HOOD), Coinbase (NASDAQ:COIN), Affirm (NASDAQ:AFRM), "
        "Upstart (NASDAQ:UPST). "
        "Apply signal scoring methodology and return signals as JSON."
    ),
    "wellness": (
        "Search the web for the top 2-3 viral health and wellness brand moments from "
        "the past 7 days on TikTok, YouTube, and Reddit. Focus on: supplement trends "
        "going viral, fitness equipment moments, biohacking trends (continuous glucose "
        "monitors, red-light therapy), wellness app adoption, and mental health platform "
        "buzz. Target publicly traded companies: Hims & Hers (NYSE:HIMS), "
        "Peloton (NASDAQ:PTON), Olaplex (NASDAQ:OLPX), Vital Farms (NASDAQ:VITL), "
        "Thorne HealthTech (NASDAQ:THRN). "
        "Apply signal scoring methodology and return signals as JSON."
    ),
}


# ---------------------------------------------------------------------------
# Signal extraction
# ---------------------------------------------------------------------------


def _parse_response(content: list, sector: str) -> tuple[list[dict], str]:
    """Parse the last text block from a response into (signals, macro_note)."""
    text = ""
    for block in content:
        if getattr(block, "type", None) == "text":
            text = block.text

    if not text.strip():
        print(f"  [warn] No text response for sector '{sector}'", file=sys.stderr)
        return [], ""

    raw = text.strip()

    # Strip markdown code fences if Claude wrapped the JSON
    fence_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
    if fence_match:
        raw = fence_match.group(1)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        obj_match = re.search(r"\{[\s\S]*\}", raw)
        if not obj_match:
            print(f"  [warn] No JSON found for sector '{sector}'", file=sys.stderr)
            return [], ""
        try:
            data = json.loads(obj_match.group(0))
        except json.JSONDecodeError as exc:
            print(
                f"  [warn] JSON parse failed for sector '{sector}': {exc}",
                file=sys.stderr,
            )
            return [], ""

    signals: list[dict] = data.get("signals", [])
    for s in signals:
        s.setdefault("sector", sector)  # use Claude's value if provided, else fallback
    macro_note: str = data.get("macro_note", "")
    return signals, macro_note


# ---------------------------------------------------------------------------
# Sector scan
# ---------------------------------------------------------------------------


def scan_sector(client: anthropic.Anthropic, sector: str) -> list[dict]:
    """Run a web-search-powered trend scan for one sector."""
    print(f"  Scanning {sector}...")

    messages: list[dict] = [{"role": "user", "content": SECTOR_PROMPTS[sector]}]

    # Agentic loop: handles pause_turn from server-side tool iteration limits
    while True:
        with client.messages.stream(
            model="claude-opus-4-8",
            max_tokens=4096,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    # Cache the system prompt — reused across all 5 sector calls
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=[{"type": "web_search_20260209", "name": "web_search"}],
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            messages=messages,
        ) as stream:
            response = stream.get_final_message()

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "pause_turn":
            # Server-side tool hit its iteration cap; re-send to continue
            messages = [
                {"role": "user", "content": SECTOR_PROMPTS[sector]},
                {"role": "assistant", "content": response.content},
            ]
            continue

        # Any other stop reason (e.g., max_tokens) — take what we have
        break

    signals, macro_note = _parse_response(response.content, sector)
    print(f"    {len(signals)} signal(s) found")
    return signals, macro_note


# ---------------------------------------------------------------------------
# Full 5-sector scan
# ---------------------------------------------------------------------------


def run_weekly_scan() -> tuple[list[dict], str]:
    """Run all five sector scans. Returns (signals sorted by score, macro_note)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set")

    client = anthropic.Anthropic(api_key=api_key)
    all_signals: list[dict] = []
    macro_note = ""

    for sector in SECTOR_PROMPTS:
        try:
            signals, note = scan_sector(client, sector)
            all_signals.extend(signals)
            if note and not macro_note:
                macro_note = note  # keep the first non-empty macro note
        except Exception as exc:  # noqa: BLE001
            print(f"  [error] Sector '{sector}' failed: {exc}", file=sys.stderr)

    all_signals.sort(key=lambda s: s.get("trend_score") or 0, reverse=True)
    return all_signals, macro_note


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    run_date = datetime.date.today().isoformat()
    print(f"Weekly trend scan — {run_date}")

    storage.init_db()

    print("Running 5-sector scan...")
    signals, macro_note = run_weekly_scan()
    print(f"Scan complete: {len(signals)} signal(s)")

    if not signals:
        print("No signals found — skipping email", file=sys.stderr)
        sys.exit(1)

    run_id = storage.save_run(run_date, len(signals))
    storage.save_signals(run_id, run_date, signals)
    print("Signals saved to briefings.db")

    email_digest.send_digest(signals, run_date, macro_note)


if __name__ == "__main__":
    main()
