import hmac, hashlib

# 🔑 Use your merchant's secret from the DB (razorpay_webhook_secret column)
secret = b"rzp_test_webhook_secret"

# Read raw bytes of the JSON body
with open("body_captured.json", "rb") as f:
    body = f.read()

# Compute HMAC SHA256 signature
sig = hmac.new(secret, body, hashlib.sha256).hexdigest()
print(sig)
