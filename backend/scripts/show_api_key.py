# backend/scripts/show_api_key.py
import sys
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from db import execute_query

q = """
SELECT name, id, api_key, created_at
FROM merchants
{where}
ORDER BY created_at DESC
LIMIT 20;
"""
where = ""
params = ()
if len(sys.argv) > 1:
    where = "WHERE name ILIKE %s OR api_key = %s"
    params = (f"%{sys.argv[1]}%", sys.argv[1])

rows = execute_query(q.format(where=where), params, fetch="all")
if not rows:
    print("No merchants found.")
else:
    for r in rows:
        print(f"{r['name']} | {r['id']} | {r['api_key']} | {r['created_at']}")
