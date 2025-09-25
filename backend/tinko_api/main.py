from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .db import init_db, close_db, get_db
from .auth import require_merchant

app = FastAPI(title="Tinko API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def _startup():
    await init_db()

@app.on_event("shutdown")
async def _shutdown():
    await close_db()

@app.get("/api/health")
async def health():
    return {"ok": True}

# ---------- Products ----------
class ProductIn(BaseModel):
    name: str
    price_cents: int = Field(ge=0)

@app.get("/api/products")
async def list_products(ctx = Depends(require_merchant), db = Depends(get_db)):
    rows = await db.fetch(
        "SELECT id, name, price_cents, created_at FROM products WHERE merchant_id = $1 ORDER BY created_at DESC",
        ctx["merchant_id"],
    )
    return {"ok": True, "merchant": ctx["merchant_name"], "products": [dict(r) for r in rows]}

@app.post("/api/products")
async def create_product(payload: ProductIn, ctx = Depends(require_merchant), db = Depends(get_db)):
    row = await db.fetchrow(
        "INSERT INTO products (merchant_id, name, price_cents) VALUES ($1, $2, $3) RETURNING id, name, price_cents, created_at",
        ctx["merchant_id"], payload.name, payload.price_cents
    )
    if not row:
        raise HTTPException(500, "Create failed")
    return {"ok": True, "product": dict(row), "merchant": ctx["merchant_name"]}

@app.post("/api/rotate-key")
async def rotate_key(ctx = Depends(require_merchant), db = Depends(get_db)):
    # Rotates ONLY the calling merchant's key
    row = await db.fetchrow(
        "UPDATE merchants "
        "SET api_key = encode(gen_random_bytes(16), 'hex') "
        "WHERE id = $1 "
        "RETURNING api_key",
        ctx["merchant_id"],
    )
    if not row:
        raise HTTPException(500, "Key rotation failed")
    return {"ok": True, "new_api_key": row["api_key"]}
