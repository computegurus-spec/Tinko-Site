import os, hmac, hashlib, json, time, uuid, csv, io, logging
from threading import Lock

from fastapi import FastAPI, Request, Header, HTTPException, status, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from apscheduler.schedulers.background import BackgroundScheduler

# ---- Local modules (keep these filenames in backend/) ----
from db import execute_query, get_merchant_by_api_key
from retry_engine import enqueue_retry

# -----------------------------------------------------------------------------
# App & Config
# -----------------------------------------------------------------------------
app = FastAPI(title="Tinko Backend")

_allowed = [o.strip() for o in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tinko")

# -----------------------------------------------------------------------------
# Scheduler (thread-safe)
# -----------------------------------------------------------------------------
scheduler = BackgroundScheduler(timezone=os.getenv("SCHED_TZ", "UTC"))
_sched_lock = Lock()

@app.on_event("startup")
def _start_sched():
    with _sched_lock:
        if not scheduler.running:
            scheduler.start()
            logger.info("[Tinko] Scheduler started.")

@app.on_event("shutdown")
def _stop_sched():
    with _sched_lock:
        if scheduler.running:
            scheduler.shutdown(wait=False)
            logger.info("[Tinko] Scheduler stopped.")

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def verify_razorpay_signature(body_bytes: bytes, signature: str, secret: str) -> bool:
    mac = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, signature or "")

def fetch_all(query, params=None):
    rows = execute_query(query, params, fetch="all") or []
    # psycopg2 DictRows -> dict
    return [dict(r) for r in rows]

def fetch_one(query, params=None):
    r = execute_query(query, params, fetch="one")
    return dict(r) if r else None

# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------
class RegisterMerchantIn(BaseModel):
    name: str
    upi_vpa: str
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    razorpay_webhook_secret: str

class CreateOrderIn(BaseModel):
    amount: int = Field(..., gt=0, description="Amount in paise")
    currency: str = "INR"
    receipt: str | None = None
    notes: dict | None = None

class CreateOrderOut(BaseModel):
    id: str
    amount: int
    currency: str
    receipt: str | None = None
    status: str = "created"

# -----------------------------------------------------------------------------
# Health & Root
# -----------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"ok": True}

@app.get("/")
def root():
    return {"message": "Tinko Backend is running"}

# -----------------------------------------------------------------------------
# Merchant Registration (returns merchant_id + api_key)
# -----------------------------------------------------------------------------
@app.post("/api/register_merchant")
def register_merchant(payload: RegisterMerchantIn):
    # Generate API key (32 hex chars)
    api_key = uuid.uuid4().hex
    row = fetch_one(
        """
        INSERT INTO merchants (name, api_key, upi_vpa, razorpay_webhook_secret, razorpay_key_id, razorpay_key_secret)
        VALUES (%s,%s,%s,%s,%s,%s)
        RETURNING id, api_key;
        """,
        [
            payload.name,
            api_key,
            payload.upi_vpa,
            payload.razorpay_webhook_secret,
            payload.razorpay_key_id,
            payload.razorpay_key_secret,
        ],
    )
    if not row:
        raise HTTPException(status_code=500, detail="Failed to register merchant")
    return {
        "message": "Merchant registered successfully",
        "merchant_id": row["id"],
        "api_key": row["api_key"],
    }

# -----------------------------------------------------------------------------
# Razorpay Webhook (per-merchant via API key in path)
# Configure in Razorpay as: https://<host>/webhooks/razorpay/<MERCHANT_API_KEY>
# -----------------------------------------------------------------------------
@app.post("/webhooks/razorpay/{merchant_api_key}")
async def razorpay_webhook(
    merchant_api_key: str,
    request: Request,
    x_razorpay_signature: str = Header(None, alias="X-Razorpay-Signature"),
):
    if not x_razorpay_signature:
        raise HTTPException(status_code=400, detail="Missing X-Razorpay-Signature")

    merchant = get_merchant_by_api_key(merchant_api_key)
    if not merchant or not merchant.get("razorpay_webhook_secret"):
        raise HTTPException(status_code=404, detail="Merchant or secret not found")

    body = await request.body()

    # Verify HMAC signature
    if not verify_razorpay_signature(body, x_razorpay_signature, merchant["razorpay_webhook_secret"]):
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    event = data.get("event")
    payment = data.get("payload", {}).get("payment", {}).get("entity", {})

    if event == "payment.failed":
        pid = payment.get("id")
        if not pid:
            return {"status": "ignored", "reason": "no payment id"}

        email = payment.get("email")
        phone = (payment.get("contact") or "").replace("+", "")
        amount = payment.get("amount")
        currency = payment.get("currency")
        reason = payment.get("error_description") or payment.get("error_reason") or "N/A"

        # Store failed payment (idempotent)
        execute_query(
            """
            INSERT INTO payment_events
              (merchant_id, razorpay_payment_id, customer_email, customer_phone, amount, currency, status, failure_reason, raw_payload, gateway)
            VALUES (%s,%s,%s,%s,%s,%s,'failed',%s,%s,'razorpay')
            ON CONFLICT (razorpay_payment_id) DO NOTHING;
            """,
            (merchant["id"], pid, email, phone, amount, currency, reason, json.dumps(data)),
        )

        # Enqueue retries (WhatsApp/Email) via your retry engine
        payment_details = {
            "razorpay_payment_id": pid,
            "customer_email": email,
            "customer_phone": phone,
            "amount": amount,
            "currency": currency,
            "failure_reason": reason,
        }
        try:
            enqueue_retry(scheduler, payment_details, merchant)
        except Exception as e:
            logger.exception("enqueue_retry failed: %s", e)

    elif event == "payment.captured":
        pid = payment.get("id")
        if pid:
            execute_query(
                """
                UPDATE payment_events
                   SET status='recovered'
                 WHERE razorpay_payment_id=%s
                   AND merchant_id=%s
                   AND status='failed';
                """,
                (pid, merchant["id"]),
            )

    # Other events can be ignored/logged
    return {"status": "ok"}

# -----------------------------------------------------------------------------
# Stats (per-merchant)
# -----------------------------------------------------------------------------
@app.get("/api/stats")
def get_stats(x_api_key: str = Header(None, alias="X-API-Key")):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")

    merchant = get_merchant_by_api_key(x_api_key)
    if not merchant:
        raise HTTPException(status_code=403, detail="Invalid API key")

    row = fetch_one(
        """
        SELECT
          COUNT(*)::int AS failed_count,
          COUNT(*) FILTER (WHERE status='recovered')::int AS recovered_count,
          COALESCE(SUM(CASE WHEN status='recovered' THEN amount ELSE 0 END), 0)::bigint AS total_recovered_paise
        FROM payment_events
        WHERE merchant_id = %s;
        """,
        [merchant["id"]],
    ) or {"failed_count": 0, "recovered_count": 0, "total_recovered_paise": 0}

    failed = row["failed_count"] or 0
    recovered = row["recovered_count"] or 0
    total_recovered_amount = (row["total_recovered_paise"] or 0) / 100.0
    pct = round((recovered / failed * 100.0), 2) if failed else 0.0

    return {
        "failed_count": failed,
        "recovered_count": recovered,
        "total_recovered_amount": float(total_recovered_amount),
        "recovery_percentage": pct,
    }

# -----------------------------------------------------------------------------
# Events (list) & CSV export
# -----------------------------------------------------------------------------
@app.get("/api/events")
def list_events(
    status: str | None = None,
    limit: int = 50,
    x_api_key: str = Header(None, alias="X-API-Key"),
):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")
    merchant = get_merchant_by_api_key(x_api_key)
    if not merchant:
        raise HTTPException(status_code=403, detail="Invalid API key")

    query = """
        SELECT razorpay_payment_id, status, failure_reason, amount, currency, created_at
        FROM payment_events
        WHERE merchant_id = %s
    """
    params = [merchant["id"]]
    if status:
        query += " AND status = %s"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT %s"
    params.append(limit)

    rows = fetch_all(query, params)
    return rows

@app.get("/api/export.csv")
def export_csv(x_api_key: str = Header(None, alias="X-API-Key")):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")
    merchant = get_merchant_by_api_key(x_api_key)
    if not merchant:
        raise HTTPException(status_code=403, detail="Invalid API key")

    rows = fetch_all(
        """
        SELECT razorpay_payment_id, status, failure_reason, amount, currency, created_at
        FROM payment_events
        WHERE merchant_id = %s
        ORDER BY created_at DESC
        """,
        [merchant["id"]],
    )

    def iter_csv():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["Payment ID", "Status", "Reason", "Amount (paise)", "Currency", "Created At"])
        yield buffer.getvalue(); buffer.seek(0); buffer.truncate(0)
        for r in rows:
            writer.writerow([
                r.get("razorpay_payment_id"),
                r.get("status"),
                r.get("failure_reason"),
                r.get("amount"),
                r.get("currency"),
                r.get("created_at"),
            ])
            yield buffer.getvalue(); buffer.seek(0); buffer.truncate(0)

    return StreamingResponse(
        iter_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=events.csv"},
    )

# -----------------------------------------------------------------------------
# Create Order (safe mock now; can switch to real Razorpay later)
# -----------------------------------------------------------------------------
def _mock_order_id() -> str:
    return "order_" + uuid.uuid4().hex[:24]

@app.post("/api/create_order", response_model=CreateOrderOut)
def create_order(
    payload: CreateOrderIn = Body(...),
    x_api_key: str = Header(None, alias="X-API-Key"),
):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")
    merchant = get_merchant_by_api_key(x_api_key)
    if not merchant:
        raise HTTPException(status_code=403, detail="Invalid API key")

    # MOCK order for MVP reliability (no external call => no 500s)
    oid = _mock_order_id()
    return CreateOrderOut(
        id=oid,
        amount=payload.amount,
        currency=(payload.currency or "INR").upper(),
        receipt=payload.receipt or f"rcpt_{int(time.time())}",
        status="created",
    )

    # --- To enable real Razorpay later, replace the block above with:
    # import razorpay  # pip install razorpay
    # key_id = merchant.get("razorpay_key_id"); key_secret = merchant.get("razorpay_key_secret")
    # if not key_id or not key_secret:
    #     raise HTTPException(status_code=400, detail="Razorpay keys not configured for this merchant")
    # client = razorpay.Client(auth=(key_id, key_secret))
    # r = client.order.create({"amount": payload.amount, "currency": payload.currency, "receipt": payload.receipt or f"rcpt_{int(time.time())}", "notes": payload.notes or {}})
    # return CreateOrderOut(id=r["id"], amount=r["amount"], currency=r["currency"], receipt=r.get("receipt"), status=r.get("status","created"))
