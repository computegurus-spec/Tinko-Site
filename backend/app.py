import os, hmac, hashlib, json, secrets
from fastapi import FastAPI, Request, Header, HTTPException, status, Body
from fastapi.middleware.cors import CORSMiddleware
from threading import Lock
from apscheduler.schedulers.background import BackgroundScheduler
import razorpay

# ---- Local imports ----
from db import execute_query, get_merchant_by_api_key
from retry_engine import enqueue_retry

app = FastAPI(title="ReCart Backend")

# ---- CORS ----
_allowed = [o.strip() for o in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Scheduler ----
scheduler = BackgroundScheduler(timezone=os.getenv("SCHED_TZ", "UTC"))
_sched_lock = Lock()

@app.on_event("startup")
def _start_sched():
    with _sched_lock:
        if not scheduler.running:
            scheduler.start()
            print("[ReCart] Scheduler started.")

@app.on_event("shutdown")
def _stop_sched():
    with _sched_lock:
        if scheduler.running:
            scheduler.shutdown(wait=False)
            print("[ReCart] Scheduler stopped.")

# ---- Helpers ----
def verify_razorpay_signature(body_bytes: bytes, signature: str, secret: str) -> bool:
    mac = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, signature or "")

def get_rzp_client(merchant: dict):
    return razorpay.Client(auth=(
        merchant["razorpay_key_id"],
        merchant["razorpay_key_secret"]
    ))

# ---- Health ----
@app.get("/api/health")
def health():
    return {"ok": True}

@app.get("/")
def root():
    return {"message": "ReCart Backend is running"}

# ---- Merchant Registration ----
@app.post("/api/register_merchant")
async def register_merchant(
    name: str = Body(...),
    upi_vpa: str = Body(...),
    razorpay_key_id: str = Body(...),
    razorpay_key_secret: str = Body(...),
    razorpay_webhook_secret: str = Body(...),
    address: str = Body(...),
    city: str = Body(...),
    state: str = Body(...),
    country: str = Body(...),
    pincode: str = Body(...)
):
    api_key = secrets.token_hex(16)  # random merchant API key

    row = execute_query(
        """
        INSERT INTO merchants
          (name, api_key, upi_vpa, razorpay_key_id, razorpay_key_secret,
           razorpay_webhook_secret, address, city, state, country, pincode)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id, name, api_key;
        """,
        (name, api_key, upi_vpa, razorpay_key_id, razorpay_key_secret,
         razorpay_webhook_secret, address, city, state, country, pincode),
        fetch="one",
    )

    return {
        "message": "Merchant registered successfully",
        "merchant_id": row["id"],
        "api_key": row["api_key"]
    }

# ---- Create Order ----
@app.post("/api/create_order")
async def create_order(
    amount: int = Body(..., embed=True),
    currency: str = Body(default="INR", embed=True),
    receipt: str = Body(default="recart_demo", embed=True),
    x_api_key: str = Header(None, alias="X-API-Key")
):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")

    merchant = get_merchant_by_api_key(x_api_key)
    if not merchant:
        raise HTTPException(status_code=403, detail="Invalid merchant API key")

    client = get_rzp_client(merchant)
    order = client.order.create({
        "amount": amount * 100,  # paise
        "currency": currency,
        "receipt": receipt,
        "payment_capture": 1
    })

    return {"order": order}

# ---- Razorpay Webhook ----
@app.post("/webhooks/razorpay/{merchant_api_key}")
async def razorpay_webhook(
    merchant_api_key: str,
    request: Request,
    x_razorpay_signature: str = Header(None, alias="X-Razorpay-Signature"),
):
    if not x_razorpay_signature:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing X-Razorpay-Signature")

    merchant = get_merchant_by_api_key(merchant_api_key)
    if not merchant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merchant not found")
    if not merchant.get("razorpay_webhook_secret"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Merchant webhook secret not configured")

    body = await request.body()
    if not verify_razorpay_signature(body, x_razorpay_signature, merchant["razorpay_webhook_secret"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature")

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body")

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

        execute_query(
            """
            INSERT INTO payment_events
              (merchant_id, razorpay_payment_id, customer_email, customer_phone, amount, currency, status, failure_reason)
            VALUES (%s,%s,%s,%s,%s,%s,'failed',%s)
            ON CONFLICT (razorpay_payment_id) DO NOTHING;
            """,
            (merchant["id"], pid, email, phone, amount, currency, reason),
        )

        payment_details = {
            "razorpay_payment_id": pid,
            "customer_email": email,
            "customer_phone": phone,
            "amount": amount,
            "currency": currency,
            "failure_reason": reason,
        }
        enqueue_retry(scheduler, payment_details, merchant)

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

    return {"status": "ok"}

# ---- Merchant Stats ----
@app.get("/api/stats")
async def get_stats(x_api_key: str = Header(None, alias="X-API-Key")):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")

    merchant = get_merchant_by_api_key(x_api_key)
    if not merchant:
        raise HTTPException(status_code=403, detail="Invalid API key")

    row = execute_query(
        """
        SELECT
          COUNT(*) AS failed_count,
          COUNT(*) FILTER (WHERE status='recovered') AS recovered_count,
          COALESCE(SUM(CASE WHEN status='recovered' THEN amount ELSE 0 END), 0) / 100.0 AS total_recovered_amount
        FROM payment_events
        WHERE merchant_id = %s;
        """,
        (merchant["id"],),
        fetch="one",
    ) or {"failed_count": 0, "recovered_count": 0, "total_recovered_amount": 0.0}

    failed = row.get("failed_count") or 0
    recovered = row.get("recovered_count") or 0
    rec_amt = float(row.get("total_recovered_amount") or 0.0)
    pct = round((recovered / failed * 100.0), 2) if failed else 0.0

    return {
        "failed_count": failed,
        "recovered_count": recovered,
        "total_recovered_amount": rec_amt,
        "recovery_percentage": pct,
    }
