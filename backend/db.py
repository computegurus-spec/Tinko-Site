import os
import psycopg2
from psycopg2.extras import DictCursor
from dotenv import load_dotenv

load_dotenv()

def get_db_connection():
    try:
        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "db"),
            database=os.getenv("POSTGRES_DB"),
            user=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD"),
        )
        return conn
    except psycopg2.OperationalError as e:
        print(f"Error connecting to database: {e}")
        return None

def execute_query(query, params=None, fetch=None):
    conn = get_db_connection()
    if conn is None:
        return None
    try:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute(query, params)
            if fetch == "one":
                row = cur.fetchone()
            elif fetch == "all":
                row = cur.fetchall()
            else:
                row = None
        conn.commit()
        return row
    except Exception as e:
        print(f"Database query failed: {e}")
        if conn:
            conn.rollback()
        return None
    finally:
        if conn:
            conn.close()

def get_merchant_by_api_key(api_key: str):
    return execute_query(
        "SELECT * FROM merchants WHERE api_key = %s LIMIT 1;",
        (api_key,),
        fetch="one",
    )

def get_merchant_by_id(mid):
    return execute_query(
        "SELECT * FROM merchants WHERE id = %s LIMIT 1;",
        (mid,),
        fetch="one",
    )
