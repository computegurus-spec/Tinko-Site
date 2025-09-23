CashLift: Local Setup and Testing Guide
Follow these steps to run the CashLift application on your local machine using Docker and ngrok.

Prerequisites
Docker & Docker Compose: Install Docker Desktop.

ngrok: Install ngrok and create a free account to get an auth token.

Razorpay Account: A test account to get API keys and simulate webhooks.

Gupshup/Twilio Account: A WhatsApp Business API provider account to get API keys and set up message templates.

Step 1: Clone the Project & Configure Environment
Create a project directory named cashlift. Inside it, create backend, dashboard folders, and the other top-level files.

Create a file named .env in the root cashlift directory by copying .env.example.

Fill in .env:

POSTGRES_*: These can remain as they are for local Docker setup.

RAZORPAY_KEY_ID & RAZORPAY_KEY_SECRET: Get these from your Razorpay dashboard under Settings -> API Keys.

RAZORPAY_WEBHOOK_SECRET: Create a strong, random string. You will use this in the Razorpay dashboard later.

GUPSHUP_*: Fill in your Gupshup API key and App Name.

NEXT_PUBLIC_API_URL: Initially, leave this as http://localhost:8000/api/stats. You will update it with your ngrok URL later for webhook testing.

Step 2: Run the Backend and Database
Open your terminal in the root cashlift directory.

Build and start the services:

docker-compose up --build

This command will:

Pull the postgres:13 image.

Create a database named cashlift_db and execute models.sql to create the table.

Build a Docker image for the FastAPI backend.

Start both containers.

You can verify the backend is running by visiting http://localhost:8000 in your browser. You should see {"message":"CashLift Backend is running!"}.

Step 3: Expose Your Webhook with ngrok
In a new terminal window, authenticate ngrok (you only need to do this once):

ngrok config add-authtoken YOUR_NGROK_AUTH_TOKEN

Expose your local backend server (running on port 8000) to the internet:

ngrok http 8000

ngrok will give you a public Forwarding URL, like https://random-string.ngrok-free.app. Copy this HTTPS URL.

Step 4: Configure Razorpay Webhooks
Go to your Razorpay Test Dashboard.

Navigate to Settings -> Webhooks.

Click + Add New Webhook.

Webhook URL: Paste your ngrok URL, followed by the webhook path: https://random-string.ngrok-free.app/webhooks/razorpay.

Secret: Paste the RAZORPAY_WEBHOOK_SECRET you created in your .env file.

Alert Email: Enter your email.

Active Events: Select payment.failed and payment.captured.

Click Create Webhook.

Step 5: Run the Frontend Dashboard
In another new terminal window, navigate to the dashboard directory.

Install dependencies and start the Next.js app:

cd dashboard
npm install
# Update NEXT_PUBLIC_API_URL in your .env file to your ngrok URL if needed for CORS,
# but for local testing, localhost should work.
npm run dev

Open http://localhost:3000 in your browser. The dashboard will load but show 0 for all stats.

Step 6: Test the End-to-End Flow
Simulate a Failed Payment:

Go to Razorpay Dashboard -> Tools -> Webhook Events.

Find your webhook endpoint and click the "..." menu, then select Trigger Event.

Select the payment.failed event. You can use the default payload or customize it. Click Trigger Event.

Check the Backend:

Look at the terminal where docker-compose up is running. You should see logs like:

Processing payment.failed event...

Logged failed payment: pay_XXXXXXXXXXXXXX

Reason: Insufficient Funds. Scheduling retry after... (or another reason).

Receive WhatsApp Message:

If you configured the retry engine and Gupshup details correctly, you (or the test phone number) should receive a WhatsApp message with the retry link after the configured delay.

Check the Dashboard:

Refresh your dashboard at http://localhost:3000. You should see "Failed Payments" is now 1.

Simulate a Recovered Payment:

Trigger another event from the Razorpay dashboard, but this time select payment.captured.

Crucially, edit the payload and change the id of the payment to match the ID of the payment that just failed (e.g., pay_XXXXXXXXXXXXXX).

Click Trigger Event.

Check Backend and Dashboard Again:

The Docker logs should show Processing payment.captured event... and Marked payment as RECOVERED....

The dashboard at http://localhost:3000 will update to show:

Failed Payments: 1

Recovered Payments: 1

₹ Recovered: [The amount from the webhook payload]

Recovery Rate: 100.00%
