# Tinko – Failed Payment Recovery Platform

Tinko is a SaaS tool that helps Indian merchants recover failed online payments by connecting directly to Razorpay webhooks.  
It automatically detects failed transactions, notifies customers through WhatsApp/SMS/email, and provides a dashboard to track recovery metrics.

---

## 🚀 Features
- **Razorpay integration** – Secure webhook handler for `payment.failed` and `payment.captured` events.  
- **Smart recovery workflows** – Automated reminders with deep links for retry.  
- **Merchant dashboard** – Track failed vs. recovered payments and total recovered amount.  
- **Multi-merchant support** – Each merchant has unique API keys and webhook secrets.  
- **Compliance-ready** – Privacy policy, refund & cancellation policy, and terms included.

---

## 🏗️ Tech Stack
- **Backend:** FastAPI (Python)  
- **Database:** PostgreSQL  
- **Scheduler:** APScheduler (for retries & reminders)  
- **Messaging Providers:** WhatsApp (Gupshup/Twilio), Email (SMTP/SES)  
- **Deployment:** Uvicorn / Gunicorn  

---

## ⚙️ Local Setup

1. **Clone the repo**
   ```bash
   git clone https://github.com/computegurus-spec/tinko-site.git
   cd tinko-site
   ```

2. **Set up virtualenv & install dependencies**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   pip install -r requirements.txt
   ```

3. **Create `.env` file**
   ```env
   DATABASE_URL=postgresql://postgres:<password>@localhost:5432/recart
   POSTGRES_HOST=localhost
   POSTGRES_DB=recart
   POSTGRES_USER=postgres
   POSTGRES_PASSWORD=<password>
   CORS_ALLOWED_ORIGINS=http://localhost:3000,https://tinko.in
   ```

4. **Run locally**
   ```bash
   uvicorn app:app --reload
   ```

5. **Check health**
   ```
   http://127.0.0.1:8000/api/health
   ```

---

## 🔑 API Endpoints

- **Register Merchant**  
  `POST /api/register_merchant`  
  → Returns merchant ID + API key.

- **Razorpay Webhook**  
  `POST /webhooks/razorpay/{merchant_api_key}`  
  → Handles `payment.failed` & `payment.captured`.

- **Merchant Stats**  
  `GET /api/stats` with header `X-API-Key: <merchant_api_key>`  
  → Returns failed count, recovered count, recovered amount, recovery %.

---

## 📄 Policies
- [Privacy Policy](./privacy.html)  
- [Terms & Conditions](./terms.html)  
- [Refund & Cancellation](./refunds.html)  

---

## 📞 Contact
- **Website:** [https://tinko.in](https://tinko.in)  
- **Email:** support@tinko.in  
- **Phone:** +91 9902255878  
- **Address:** 12 MG Road, Bangalore, Karnataka, 560001, India  
