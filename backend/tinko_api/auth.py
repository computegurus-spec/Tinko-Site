from fastapi import Header, HTTPException, Depends
from .db import get_db

async def require_merchant(x_api_key: str = Header(None), db = Depends(get_db)):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing API key")
    row = await db.fetchrow("SELECT id, name FROM merchants WHERE api_key = $1", x_api_key)
    if not row:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return {"merchant_id": row["id"], "merchant_name": row["name"]}
