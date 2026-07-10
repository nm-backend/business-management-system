import os
import psycopg2
from decouple import config

try:
    print(f"DB_NAME: {config('DB_NAME')}")
    print(f"DB_USER: {config('DB_USER')}")
    print(f"DB_PASSWORD: {config('DB_PASSWORD')}")
    print(f"DB_HOST: {config('DB_HOST')}")
    print(f"DB_PORT: {config('DB_PORT')}")
    
    conn = psycopg2.connect(
        dbname=config('DB_NAME'),
        user=config('DB_USER'),
        password=config('DB_PASSWORD'),
        host=config('DB_HOST'),
        port=config('DB_PORT', cast=int)
    )
    print("Connected successfully!")
    conn.close()
except Exception as e:
    print("Error:", type(e))
    import traceback
    traceback.print_exc()
