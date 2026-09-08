# import os
# import logging
# import json


# def get_all_ipmi_devices(file_path=None):
#     if file_path is None:
#         file_path = os.getenv("IPMI_DEVICES_FILE", "IPMI_devices.json")
#     try:
#         with open(file_path, "r") as f:
#             devices = json.load(f)
#         logging.info(f"Loaded {len(devices)} IPMI devices from file.")
#         return devices
#     except Exception as e:
#         logging.error(f"Failed to load IPMI devices from file: {e}")
#         return []

import os
import logging
import psycopg2
from psycopg2.extras import RealDictCursor


def get_db_connection():
    try:
        connection = psycopg2.connect(
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT", 5432),
            database=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            connect_timeout=10
        )
        return connection
    except Exception as e:
        logging.error(f"Database connection failed: {e}")
        return None


def get_all_ipmi_devices():
    connection = get_db_connection()
    if not connection:
        return []

    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT id, name, ipmi_server_ip, username, password FROM ipmi_servers;")
            devices = cursor.fetchall()
            logging.info(f"Loaded {len(devices)} IPMI devices from database.")
            return devices

    except Exception as e:
        logging.error(f"Failed to fetch IPMI devices: {e}")
        return []

    finally:
        connection.close()
