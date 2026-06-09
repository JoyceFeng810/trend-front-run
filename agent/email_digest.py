"""Render and send the weekly HTML email digest via SendGrid."""

import html as html_lib
import os
from datetime import datetime

import sendgrid
from sendgrid.helpers.mail import Mail, Header, Content, MimeType


SECTOR_LABELS: dict[str, str] = {
    "beauty": "Beauty & Skincare",
    "fashion": "Fashion & Apparel",
    "tech": "Consumer Tech",
    "fintech": "Fintech",
    "wellness": "Wellness",
}

SECTOR_ORDER = ["beauty", "fashion", "tech", "fintech", "wellness"]

STAGE_STYLES: dict[str, str] = {
    "Emerging": "background:#fce7f3;color:#be185d;",
    "Accelerating": "background:#fef3c7;color:#b45309;",
    "Mainstream": "background:#dcfce7;color:#15803d;",
}

SOURCE_COLORS: dict[str, str] = {
    "TikTok": "#ff2d55",
    "YouTube": "#ff0000",
    "Reddit": "#ff4500",
    "Google Trends": "#4285f4",
    "News": "#94a3b8",
}

# Words that spam filters penalize in subject lines
_SUBJECT_BLOCKLIST = [
    "panic", "viral", "crash", "crisis", "urgent", "breaking",
    "explode", "surge", "alert", "warning", "scandal", "toxic",
    "benzene", "recall", "danger",
]

def _safe_subject(signals: list[dict], formatted_date: str) -> str:
    """Build a subject line that avoids spam-trigger words."""
    sectors = list({s.get("sector", "") for s in signals if s.get("sector")})
    sector_labels = [SECTOR_LABELS.get(s, s).split("&")[0].strip() for s in sectors[:3]]
    count = len(signals)

    # Try to use the top signal brand name (safe) instead of its title (can be alarming)
    top_brand = ""
    if signals:
        top_brand = signals[0].get("brand", "")

    if top_brand:
        subject = f"📡 Trend Brief · {formatted_date} · {top_brand} + {count - 1} more signals"
    else:
        subject = f"📡 Trend Brief · {formatted_date} · {count} signals across {', '.join(sector_labels)}"

    # Strip any blocklisted words that snuck in
    for word in _SUBJECT_BLOCKLIST:
        subject = subject.replace(word, "").replace(word.title(), "").replace(word.upper(), "")

    return subject.strip()


def _score_color(score: int) -> str:
    if score >= 8:
        return "#16a34a"
    if score >= 5:
        return "#d97706"
    return "#6b7280"


def _source_tags(sources: list[str]) -> str:
    tags = ""
    for src in sources:
        color = SOURCE_COLORS.get(src, "#94a3b8")
        label = html_lib.escape(src)
        tags += (
            f'<span style="display:inline-block;padding:1px 7px;border-radius:20px;'
            f"font-size:10px;font-family:monospace;margin-right:4px;"
            f"background:{color}18;color:{color};"
            f'border:1px solid {color}33;">{label}</span>'
        )
    return tags


def _signal_card(signal: dict) -> str:
    title = html_lib.escape(signal.get("title") or "Untitled")
    brand = html_lib.escape(signal.get("brand") or "")
    raw_ticker = signal.get("ticker") or ""
    stage = html_lib.escape(signal.get("stage") or "Unknown")
    score = int(signal.get("trend_score") or 0)
    signal_text = html_lib.escape(signal.get("signal") or "")
    catalyst = html_lib.escape(signal.get("catalyst") or "")
    risk = html_lib.escape(signal.get("risk") or "")
    sources: list[str] = signal.get("sources") or []

    ticker_html = ""
    if raw_ticker and raw_ticker.lower() not in ("", "private", "pre-ipo"):
        ticker_html = (
            '<span style="display:inline-block;padding:1px 7px;border-radius:4px;'
            "font-size:11px;font-weight:600;background:#f1f5f9;color:#475569;"
            f'margin-left:6px;font-family:monospace;">{html_lib.escape(raw_ticker)}</span>'
        )
    elif raw_ticker.lower() in ("private", "pre-ipo"):
        ticker_html = (
            '<span style="display:inline-block;padding:1px 7px;border-radius:4px;'
            "font-size:11px;background:#fef9c3;color:#854d0e;"
            f'margin-left:6px;">{html_lib.escape(raw_ticker)}</span>'
        )

    stage_style = STAGE_STYLES.get(stage, "background:#f1f5f9;color:#475569;")
    color = _score_color(score)
    source_html = _source_tags(sources) if sources else ""

    signal_row = ""
    if signal_text:
        signal_row = f"""
            <div style="font-size:13px;color:#374151;margin-bottom:6px;line-height:1.5;">
              {signal_text}
            </div>"""

    return f"""
<table width="100%" cellpadding="0" cellspacing="0" border="0"
       style="background:#ffffff;border-radius:10px;margin-bottom:10px;
              border:1px solid #e5e7eb;">
  <tr>
    <td style="padding:18px 20px;">
      <table width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <td width="52" valign="top" style="padding-right:14px;">
            <div style="width:48px;height:48px;background:{color};border-radius:10px;
                        text-align:center;line-height:48px;font-size:22px;
                        font-weight:800;color:#ffffff;font-family:Georgia,serif;">
              {score}
            </div>
          </td>
          <td valign="top">
            <div style="margin-bottom:4px;">
              <span style="font-weight:700;font-size:15px;color:#111827;">{title}</span>
              <span style="display:inline-block;padding:2px 8px;border-radius:20px;
                           font-size:11px;font-weight:600;margin-left:6px;{stage_style}">
                {stage}
              </span>
            </div>
            <div style="font-size:13px;color:#6b7280;margin-bottom:6px;">
              {brand}{ticker_html}
            </div>
            {f'<div style="margin-bottom:6px;">{source_html}</div>' if source_html else ""}
            {signal_row}
            <div style="font-size:13px;color:#374151;margin-bottom:5px;">
              <strong style="color:#111827;">Catalyst:</strong> {catalyst}
            </div>
            <div style="font-size:12px;color:#9ca3af;">
              <strong>Risk:</strong> {risk}
            </div>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>"""


def render_plain_text(signals: list[dict], formatted_date: str, macro_note: str = "") -> str:
    """Plain-text fallback — improves deliverability when included alongside HTML."""
    lines = [
        f"TREND INTELLIGENCE BRIEF — {formatted_date}",
        "=" * 50,
        "",
    ]
    if macro_note:
        lines += [f"MACRO: {macro_note}", ""]

    for i, s in enumerate(signals, 1):
        lines += [
            f"{i}. {s.get('title', 'Untitled')} [{s.get('stage', '')}]",
            f"   Brand: {s.get('brand', '')}  |  Ticker: {s.get('ticker', 'N/A')}",
            f"   Score: {s.get('camelio_score') or s.get('trend_score', '?')}/10",
            f"   Signal: {s.get('signal', '')}",
            f"   Catalyst: {s.get('catalyst', '')}",
            f"   Risk: {s.get('risk', '')}",
            "",
        ]

    lines += [
        "-" * 50,
        "Not investment advice. For informational purposes only.",
        "To unsubscribe, reply with UNSUBSCRIBE in the subject.",
    ]
    return "\n".join(lines)


def render_html(signals: list[dict], run_date: str, macro_note: str = "") -> str:
    by_sector: dict[str, list[dict]] = {s: [] for s in SECTOR_ORDER}
    for signal in signals:
        sector = signal.get("sector", "")
        if sector in by_sector:
            by_sector[sector].append(signal)

    sector_blocks = ""
    for sector in SECTOR_ORDER:
        sector_signals = by_sector[sector]
        if not sector_signals:
            continue
        label = SECTOR_LABELS.get(sector, sector.replace("_", " ").title())
        cards = "".join(_signal_card(s) for s in sector_signals)
        sector_blocks += f"""
<table width="100%" cellpadding="0" cellspacing="0" border="0"
       style="margin-bottom:20px;">
  <tr>
    <td>
      <div style="font-size:11px;font-weight:700;letter-spacing:1.5px;
                  text-transform:uppercase;color:#9ca3af;margin-bottom:8px;">
        {html_lib.escape(label)}
      </div>
      {cards}
    </td>
  </tr>
</table>"""

    try:
        formatted_date = datetime.fromisoformat(run_date).strftime("%B %d, %Y")
    except ValueError:
        formatted_date = run_date

    total = len(signals)
    sector_count = sum(1 for s in SECTOR_ORDER if by_sector[s])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>Trend Intelligence Brief — {formatted_date}</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0"
         style="background:#f3f4f6;padding:24px 0;">
    <tr>
      <td align="center">
        <table width="640" cellpadding="0" cellspacing="0" border="0"
               style="max-width:640px;width:100%;">

          <!-- Header -->
          <tr>
            <td style="padding:0 16px 20px;">
              <table width="100%" cellpadding="0" cellspacing="0" border="0"
                     style="background:#0a0a0a;border-radius:12px;padding:28px 32px;">
                <tr>
                  <td>
                    <div style="font-size:22px;font-weight:800;color:#ffffff;
                                letter-spacing:-0.5px;margin-bottom:6px;">
                      Trend Intelligence Brief
                    </div>
                    <div style="font-size:13px;color:#6b7280;">
                      {formatted_date}&nbsp;&nbsp;&middot;&nbsp;&nbsp;{total}&nbsp;signal{'s' if total != 1 else ''}&nbsp;across&nbsp;{sector_count}&nbsp;sector{'s' if sector_count != 1 else ''}
                    </div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Score legend -->
          <tr>
            <td style="padding:0 16px 16px;">
              <table width="100%" cellpadding="0" cellspacing="0" border="0"
                     style="background:#fff;border-radius:8px;padding:10px 16px;
                            border:1px solid #e5e7eb;">
                <tr>
                  <td style="font-size:12px;color:#6b7280;">
                    Score:&nbsp;
                    <span style="color:#16a34a;font-weight:700;">8–10 high conviction</span>
                    &nbsp;&middot;&nbsp;
                    <span style="color:#d97706;font-weight:700;">5–7 moderate</span>
                    &nbsp;&middot;&nbsp;
                    <span style="color:#6b7280;font-weight:700;">1–4 watch list</span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          {f'''<!-- Macro note -->
          <tr>
            <td style="padding:0 16px 16px;">
              <table width="100%" cellpadding="0" cellspacing="0" border="0"
                     style="background:#eff6ff;border-radius:8px;padding:12px 16px;
                            border:1px solid #bfdbfe;">
                <tr>
                  <td style="font-size:13px;color:#1d4ed8;line-height:1.5;">
                    <strong>Macro:</strong> {html_lib.escape(macro_note)}
                  </td>
                </tr>
              </table>
            </td>
          </tr>''' if macro_note else ""}

          <!-- Signals -->
          <tr>
            <td style="padding:0 16px;">
              {sector_blocks}
            </td>
          </tr>

          <!-- Footer with unsubscribe -->
          <tr>
            <td style="padding:20px 16px;text-align:center;font-size:11px;
                       color:#9ca3af;line-height:1.7;">
              Signals surface TikTok, YouTube, and Reddit viral catalysts before Wall Street.<br>
              <strong>Not investment advice.</strong> For informational purposes only.<br>
              To unsubscribe, reply with UNSUBSCRIBE in the subject line.
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def send_digest(briefing: dict) -> None:
    api_key = os.environ.get("SENDGRID_API_KEY")
    digest_email = os.environ.get("DIGEST_EMAIL")
    # FROM_EMAIL should be your domain-authenticated address e.g. brief@yourdomain.com
    from_email = os.environ.get("FROM_EMAIL")

    if not api_key:
        raise RuntimeError("SENDGRID_API_KEY not set")
    if not digest_email:
        raise RuntimeError("DIGEST_EMAIL not set")
    if not from_email:
        raise RuntimeError(
            "FROM_EMAIL not set — set this to your SendGrid-authenticated sender address "
            "(e.g. brief@yourdomain.com). Do NOT use a Gmail address here."
        )

    signals = briefing.get("signals", [])
    run_date = briefing.get("timestamp", datetime.now().isoformat())
    macro_note = briefing.get("macro_note", "")

    try:
        formatted_date = datetime.fromisoformat(run_date).strftime("%b %d, %Y")
    except ValueError:
        formatted_date = run_date

    subject = _safe_subject(signals, formatted_date)
    html_body = render_html(signals, run_date, macro_note)
    plain_body = render_plain_text(signals, formatted_date, macro_note)

    message = Mail(from_email=from_email, to_emails=digest_email)
    message.subject = subject

    # Both plain-text and HTML parts — improves deliverability
    message.content = [
        Content(MimeType.text, plain_body),
        Content(MimeType.html, html_body),
    ]

    # List-Unsubscribe header — required by Gmail for automated senders since 2024
    message.header = [
        Header("List-Unsubscribe", f"<mailto:{from_email}?subject=UNSUBSCRIBE>"),
        Header("List-Unsubscribe-Post", "List-Unsubscribe=One-Click"),
        Header("X-Mailer", "trend-front-run/1.0"),
    ]

    sg = sendgrid.SendGridAPIClient(api_key=api_key)
    response = sg.send(message)

    if response.status_code not in (200, 201, 202):
        raise RuntimeError(f"SendGrid returned {response.status_code}")

    print(f"✉️  Email sent to {digest_email} (HTTP {response.status_code})")
    print(f"   Subject: {subject}")
