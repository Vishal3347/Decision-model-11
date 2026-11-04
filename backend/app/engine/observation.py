"""Stage 1 – Observation: deterministic extraction of facts from an email (no LLM involved)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from ..schemas import Amount, Observation

LEXICON: dict[str, list[str]] = {
    "outage": ["unavailable", "503", "outage", "down", "cannot access", "sev-1", "production services"],
    "security": ["unusual login", "failed login", "mfa", "credential", "suspicious", "unfamiliar ip", "unauthorized", "breach"],
    "financial": ["payment", "invoice", "wire", "transfer", "release", "vendor"],
    "contract": ["contract", "agreement", "signature"],
    "deletion": ["purge", "permanent deletion", "delete", "deletion"],
    "meeting": ["meeting", "sync", "workshop"],
    "reminder": ["reminder"],
    "reschedule": ["reschedule", "clashes", "move to"],
    "leave": ["leave request", "leave from", "days of leave", "time off", "vacation"],
    "complaint": ["failing", "complaint", "critical issue", "sla breach", "blocking us"],
    "demo": ["demo", "demonstration"],
    "followup": ["not responded", "follow up", "follow-up", "no response", "heard nothing"],
    "newsletter": ["unsubscribe", "digest", "newsletter", "webinar"],
    "urgent": ["immediate", "immediately", "asap", "urgent", "critical", "today", "deadline"],
}

_AMOUNT_RE = re.compile(r"(?:₹|\brs\.?|\binr)\s*([\d,]+(?:\.\d+)?)\s*(lakhs?|crores?|cr)?", re.I)
_FIELD_RE = re.compile(r"^\s*([A-Za-z][A-Za-z ]{1,24}):\s*(.+?)\s*$", re.M)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_DAY_RE = re.compile(r"\b(tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I)
_TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", re.I)
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_DEADLINE_WORDS = ["deadline", "by friday", "by monday", "due", "before the due date", "today", "immediately", "end of this week"]


def _kw_match(text: str, kw: str) -> bool:
    pattern = r"(?<![a-z0-9])" + re.escape(kw)
    if len(kw) <= 4:
        pattern += r"(?![a-z0-9])"
    return re.search(pattern, text) is not None


def find_signals(text: str) -> dict[str, list[str]]:
    lowered = text.lower()
    found: dict[str, list[str]] = {}
    for name, words in LEXICON.items():
        hits = [w for w in words if _kw_match(lowered, w)]
        if hits:
            found[name] = hits
    return found


def parse_amounts(text: str) -> list[Amount]:
    out: list[Amount] = []
    for m in _AMOUNT_RE.finditer(text):
        try:
            value = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        unit = (m.group(2) or "").lower()
        if unit.startswith("lakh"):
            value *= 100_000
        elif unit.startswith("cr"):
            value *= 10_000_000
        out.append(Amount(value=value, raw=m.group(0).strip()))
    return out


def resolve_day(word: str, ref: datetime) -> datetime:
    w = word.lower()
    if w == "today":
        return ref
    if w == "tomorrow":
        return ref + timedelta(days=1)
    target = _WEEKDAYS.index(w)
    delta = (target - ref.weekday()) % 7 or 7
    return ref + timedelta(days=delta)


def extract_datetimes(text: str, ref: datetime) -> tuple[list[str], list[str]]:
    """Pair day words with time-of-day mentions in order of appearance."""
    days = [m.group(1) for m in _DAY_RE.finditer(text)]
    times = []
    for m in _TIME_RE.finditer(text):
        hour = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "pm" else 0)
        times.append((hour, int(m.group(2) or 0)))
    isos: list[str] = []
    for day, (h, mi) in zip(days, times):
        dt = resolve_day(day, ref).replace(hour=h, minute=mi, second=0, microsecond=0)
        isos.append(dt.isoformat(timespec="seconds"))
    return days, isos


def observe(email: dict, ref: datetime) -> Observation:
    subject, body = email["subject"], email["body"]
    text = f"{subject}\n{body}"
    day_mentions, datetimes = extract_datetimes(text, ref)
    fields = {k.strip().lower(): v for k, v in _FIELD_RE.findall(body)}
    lowered = text.lower()
    return Observation(
        email_id=email["id"],
        sender_name=email["sender_name"],
        sender_email=email["sender_email"],
        sender_type=email["sender_type"],
        subject=subject,
        category=email["category"],
        word_count=len(body.split()),
        amounts=parse_amounts(text),
        fields=fields,
        emails_found=[e for e in _EMAIL_RE.findall(body) if e.lower() != email["sender_email"].lower()],
        day_mentions=day_mentions,
        datetimes=datetimes,
        signals=find_signals(text),
        has_deadline=any(w in lowered for w in _DEADLINE_WORDS),
        excerpt=" ".join(body.split())[:220],
    )
