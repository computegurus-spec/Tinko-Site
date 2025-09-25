# backend/retry_engine.py
import os
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Tuple, Optional

from apscheduler.schedulers.base import BaseScheduler

from db import execute_query

# Optional WhatsApp provider (Gupshup). Keep import guarded.
try:
    from message_providers.whatsapp_gupshup import send_whatsapp_message
    HAS_WHATSAPP = True
except Exception:  # Module might not exist yet; we still want backend to run.
    HAS_WHATSAPP = False

logger = logging.getLogger("tinko.retry")

# --------------------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------------------

def _tz() -> ZoneInfo:
    return ZoneInfo(os.getenv("SCHED_TZ", "UTC"))

def _parse_schedule(env_val: Optional[str]) -> List[timedelta]:
    """
    Parse RECOVERY_SCHEDULE like: "15m,2h,24h" into [timedelta(...)]
    Supported units: s, m, h, d
    """
    default = ["15m", "2h", "24h"]
    tokens = (env_val or "").strip().split(",") if env_val else default
    delays: List[timedelta] = []
    for t in tokens:
        t = t.strip().lower()
        if not t:
            continue
        try:
            unit = t[-1]
            num = float(t[:-1])
            if unit == "s":
                delays.append(timedelta(seconds=num))
            elif unit == "m":
                delays.append(timedelta(minutes=num))
            elif unit == "h":
                delays.append(timedelta(hours=num))
            elif unit == "d":
                delays.append(timedelta(days=num))
            else:
                logger.warning("Unknown schedule unit in %s; skipping", t)
        except Exception:
            logger.warning("Invalid schedule token %r; skipping", t)
    return delays or [timedelta(minutes=15), timedelta(hours=2), timedelta(hours=24)]

RECOVERY_SCHEDULE: List[timedelta] = _parse_schedule(os.getenv("RECOVERY_SCHEDULE"))
DEFAULT_CHANNEL = os.getenv("DEFAULT_CHANNEL", "whatsapp")  # 'whatsapp' | 'email' | 'sms' (only WA + email stub here)

# --------------------------------------------------------------------------------------
# Data structures
# --------------------------------------------------------------------------------------

@dataclass
class PaymentCtx:
    merchant_id: str
    razorpay_payment_id: str
    customer_email: Optional[str]
    customer_phone: Optional[str]
    amount: Optional[int]            # paise
    currency: Optional[str]
    failure_reason: Optional[str]

# --------------------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------------------

def enqueue_retry(scheduler: BaseScheduler, payment_details: dict, merchant: dict) -> None:
    """
    Schedule retries for a failed payment event.
    - Inserts rows into recovery_attempts (attempt_no 1..N)
    - Schedules APScheduler jobs to run at those times
    """
    tz = _tz()
    merchant_id = str(merchant["id"])
    pid = str(payment_details["razorpay_payment_id"])

    # Channel selection (env or default WA if phone exists; else email)
    phone = (payment_details.get("customer_phone") or "").strip()
    email = (payment_details.get("customer_email") or "").strip()
    if DEFAULT_CHANNEL == "whatsapp" and not phone:
        channel = "email"
    else:
        channel = DEFAULT_CHANNEL

    logger.info("Enqueueing retries for merchant=%s pid=%s channel=%s schedule=%s",
                merchant_id, pid, channel, RECOVERY_SCHEDULE)

    for idx, delay in enumerate(RECOVERY_SCHEDULE, start=1):
        scheduled_at = datetime.now(tz=tz) + delay

        # Insert attempt & get its UUID back
        row = execute_query(
            """
            INSERT INTO recovery_attempts
              (merchant_id, razorpay_payment_id, channel, attempt_no, scheduled_at, status)
            VALUES (%s,%s,%s,%s,%s,'scheduled')
            RETURNING id;
            """,
            (merchant_id, pid, channel, idx, scheduled_at),
            fetch="one",
        )
        if not row:
            logger.error("Failed to insert recovery_attempts for pid=%s (attempt=%s)", pid, idx)
            continue

        attempt_id = row["id"]
        # Schedule job
        scheduler.add_job(
            func=_run_attempt_job,
            trigger="date",
            run_date=scheduled_at,
            kwargs={"attempt_id": str(attempt_id)},
            id=str(attempt_id),  # unique job id
            replace_existing=True,
        )
        logger.info("Scheduled attempt_id=%s at %s (attempt_no=%s)", attempt_id, scheduled_at.isoformat(), idx)

# --------------------------------------------------------------------------------------
# Internal: job execution
# --------------------------------------------------------------------------------------

def _run_attempt_job(attempt_id: str) -> None:
    """
    APScheduler job entrypoint.
    Loads attempt + payment context; sends message; updates status.
    """
    tz = _tz()
    logger.info("Running attempt job id=%s", attempt_id)

    # Load attempt + join payment data
    rec = execute_query(
        """
        SELECT
          a.id,
          a.merchant_id,
          a.razorpay_payment_id,
          a.channel,
          a.attempt_no,
          a.scheduled_at,
          pe.customer_email,
          pe.customer_phone,
          pe.amount,
          pe.currency,
          pe.failure_reason
        FROM recovery_attempts a
        JOIN payment_events pe
          ON pe.merchant_id = a.merchant_id
         AND pe.razorpay_payment_id = a.razorpay_payment_id
        WHERE a.id = %s
        LIMIT 1;
        """,
        (attempt_id,),
        fetch="one",
    )

    if not rec:
        logger.error("Attempt id=%s not found; skipping", attempt_id)
        return

    attempt = dict(rec)
    ctx = PaymentCtx(
        merchant_id=str(attempt["merchant_id"]),
        razorpay_payment_id=str(attempt["razorpay_payment_id"]),
        customer_email=(attempt.get("customer_email") or None),
        customer_phone=_normalize_msisdn(attempt.get("customer_phone")),
        amount=attempt.get("amount"),
        currency=(attempt.get("currency") or "INR"),
        failure_reason=attempt.get("failure_reason"),
    )

    # Compose human message (simple template)
    text = _compose_message(ctx)

    try:
        if attempt["channel"] == "whatsapp":
            _send_whatsapp(ctx, text)
        elif attempt["channel"] == "email":
            _send_email(ctx, text)
        else:
            raise RuntimeError(f"Unsupported channel: {attempt['channel']}")

        # Mark sent
        execute_query(
            """
            UPDATE recovery_attempts
               SET status='sent', sent_at=NOW()
             WHERE id=%s;
            """,
            (attempt_id,),
        )
        logger.info("Attempt id=%s marked sent", attempt_id)

    except Exception as e:
        # Mark failed with error
        logger.exception("Attempt id=%s failed: %s", attempt_id, e)
        execute_query(
            """
            UPDATE recovery_attempts
               SET status='failed', sent_at=NOW(), error=%s
             WHERE id=%s;
            """,
            (str(e), attempt_id),
        )

# --------------------------------------------------------------------------------------
# Channels
# --------------------------------------------------------------------------------------

def _send_whatsapp(ctx: PaymentCtx, text: str) -> None:
    if not HAS_WHATSAPP:
        raise RuntimeError("WhatsApp provider unavailable; install/configure message_providers.whatsapp_gupshup")
    if not ctx.customer_phone:
        raise RuntimeError("Missing customer phone for WhatsApp")
    # Delegate to your provider wrapper (should raise on error)
    send_whatsapp_message(ctx.customer_phone, text)

def _send_email(ctx: PaymentCtx, text: str) -> None:
    """
    Minimal stub so MVP works without external email provider.
    Replace with SendGrid/Mailgun/SMTP as needed.
    """
    if not ctx.customer_email:
        raise RuntimeError("Missing customer email for Email channel")
    # For now, just log success to keep flow moving
    logger.info("EMAIL to %s :: %s", ctx.customer_email, text)

# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------

def _normalize_msisdn(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    s = "".join(ch for ch in str(raw) if ch.isdigit())
    # Basic India default: add country code if 10 digits
    if len(s) == 10:
        s = "91" + s
    return s

def _format_amount(amount_paise: Optional[int], currency: Optional[str]) -> str:
    try:
        if amount_paise is None:
            return ""
        rupees = amount_paise / 100.0
        cur = (currency or "INR").upper()
        return f"{rupees:.2f} {cur}"
    except Exception:
        return ""

def _compose_message(ctx: PaymentCtx) -> str:
    amt = _format_amount(ctx.amount, ctx.currency)
    reason = (ctx.failure_reason or "").strip()
    # You can include a smart deep link here if/when available
    parts = [
        "Hi! Your payment attempt didn’t go through last time.",
        f"Amount: {amt}" if amt else None,
        f"Reason: {reason}" if reason else None,
        "You can retry securely using the link we’ve shared with you. If you already paid, you can ignore this message.",
        "— Team Tinko",
    ]
    return "\n".join(p for p in parts if p)
