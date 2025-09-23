import os
from datetime import datetime, timedelta
from urllib.parse import quote
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler

from message_providers.whatsapp_gupshup import send_whatsapp_message


load_dotenv()

def generate_retry_link(payment_details, merchant):
    """Create a UPI deep link using the merchant's VPA (fallback safe)."""
    vpa = merchant.get("upi_vpa") or os.getenv("DEFAULT_UPI_VPA", "demo@okhdfcbank")
    amount = payment_details["amount"] / 100  # paise → ₹
    order_id = payment_details["razorpay_payment_id"]
    pn = quote(merchant.get("name", "Merchant"))
    tn = quote(f"Retry Payment {order_id}")
    return f"upi://pay?pa={vpa}&pn={pn}&tid={order_id}&am={amount}&cu=INR&tn={tn}"

def compute_delay_seconds(failure_reason: str) -> int:
    fr = (failure_reason or "unknown").lower()
    if "pin" in fr:
        return 0
    if "timeout" in fr or "network" in fr:
        return 60
    if "funds" in fr or "insufficient" in fr or "balance" in fr:
        return 12 * 60 * 60
    # default: gentle nudge after 10 minutes
    return 10 * 60

def _send_retry_message(payment_details, merchant):
    customer_phone = payment_details.get("customer_phone")
    if not customer_phone:
        print(f"No phone for payment {payment_details['razorpay_payment_id']}; skipping.")
        return

    customer_name = (payment_details.get("customer_email") or "Customer").split("@")[0]
    amount_str = f"₹{payment_details['amount'] / 100:.2f}"
    retry_link = generate_retry_link(payment_details, merchant)

    template_id = os.getenv("GUPSHUP_TEMPLATE_ID", "payment_failed_retry")
    params = [customer_name, amount_str, retry_link]  # must match approved template

    print(f"[ReCart] Sending retry to {customer_phone} for {payment_details['razorpay_payment_id']}")
    send_whatsapp_message(customer_phone, template_id, str(params))

def enqueue_retry(scheduler: BackgroundScheduler, payment_details, merchant):
    delay = compute_delay_seconds(payment_details.get("failure_reason"))
    run_at = datetime.utcnow() + timedelta(seconds=delay)
    scheduler.add_job(
        _send_retry_message,
        "date",
        run_date=run_at,
        args=[payment_details, merchant],
        id=f"retry-{payment_details['razorpay_payment_id']}",
        replace_existing=True,
    )
    print(f"[ReCart] Retry scheduled in {delay}s at {run_at.isoformat()} for {payment_details['razorpay_payment_id']}")
