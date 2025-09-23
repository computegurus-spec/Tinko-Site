# sign.py
import hmac, hashlib, sys, json
secret = b"rzp_test_webhook_secret"   # <-- use the value from merchants.razorpay_webhook_secret
body = open("body.json", "rb").read()
sig = hmac.new(secret, body, hashlib.sha256).hexdigest()
print(sig)
