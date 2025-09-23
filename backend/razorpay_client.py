import razorpay
from db import get_merchant_by_api_key

def get_rzp_client(api_key: str):
    merchant = get_merchant_by_api_key(api_key)
    if not merchant:
        raise Exception("Invalid API key")

    return razorpay.Client(auth=(
        merchant["razorpay_key_id"],
        merchant["razorpay_key_secret"]
    ))
