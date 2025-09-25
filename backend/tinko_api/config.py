import os

# Set this in PowerShell: $env:DATABASE_URL="postgres://postgres:<PWD>@localhost:5432/tinko"
DATABASE_URL = os.environ.get("DATABASE_URL", "postgres://postgres:YOURPWD@localhost:5432/tinko")

# In dev, allow your local frontend
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
