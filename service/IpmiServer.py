import os
import logging
import json


def get_all_ipmi_devices(file_path=None):
    if file_path is None:
        file_path = os.getenv("IPMI_DEVICES_FILE", "IPMI_devices.json")
    try:
        with open(file_path, "r") as f:
            devices = json.load(f)
        logging.info(f"Loaded {len(devices)} IPMI devices from file.")
        return devices
    except Exception as e:
        logging.error(f"Failed to load IPMI devices from file: {e}")
        return []