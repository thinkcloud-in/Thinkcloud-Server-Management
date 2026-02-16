import os
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
from fastapi import HTTPException
from service.helper import (
    escape_tag, escape_field, escape_field_powerlimit,
    flatten_json, clean_redfish_json, safeget, normalize_correction_in_ms
)

from service.IpmiServer import get_all_ipmi_devices

load_dotenv(dotenv_path=".env")
requests.packages.urllib3.disable_warnings()

# Configure a requests Session with retries and a default timeout to avoid
# blocking indefinitely when a BMC is slow or unresponsive.
SESSION = requests.Session()
RETRY_STRATEGY = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["HEAD", "GET", "POST", "PUT", "PATCH", "DELETE"]
)
ADAPTER = HTTPAdapter(max_retries=RETRY_STRATEGY)
SESSION.mount("https://", ADAPTER)
SESSION.mount("http://", ADAPTER)

DEFAULT_TIMEOUT = 10  # seconds

# --- Influx Details (still from env) ---
INFLUX_URL = os.getenv('INFLUX_URL')
INFLUX_TOKEN = os.getenv('INFLUX_TOKEN')
ORG = os.getenv('ORG')
BUCKET = os.getenv('BUCKET')
INFLUX_URL = f"https://{INFLUX_URL}/api/v2/write"

INFLUX_HEADERS = {
    "Authorization": f"Token {INFLUX_TOKEN}",
    "Content-Type": "text/plain; charset=utf-8"
}
INFLUX_PARAMS = {
    "org": ORG,
    "bucket": BUCKET,
    "precision": "s"
}

logging.basicConfig(level=logging.INFO)

def redfish_get(url, user, password, timeout=DEFAULT_TIMEOUT):
    try:
        r = SESSION.get(url, auth=(user, password), verify=False, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logging.error(f"Redfish GET failed for {url}: {e}")
        return None

def get_first_system_url(redfish_root, user, password):
    root = redfish_get(redfish_root, user, password)
    if root is None:
        raise HTTPException(status_code=404, detail="Redfish root GET returned None")
    systems_coll_url = root.get('Systems', {}).get('@odata.id')
    if not systems_coll_url:
        raise HTTPException(status_code=404, detail="No 'Systems' key in Redfish root")
    scheme_host = redfish_root.split("/redfish/v1")[0]
    if systems_coll_url.startswith("/"):
        systems_coll_url = scheme_host + systems_coll_url
    systems_collection = redfish_get(systems_coll_url, user, password)
    if not systems_collection or "Members" not in systems_collection or not systems_collection["Members"]:
        raise HTTPException(status_code=404, detail="No systems found in Redfish")
    system_url = systems_collection["Members"][0].get("@odata.id")
    if not system_url:
        raise HTTPException(status_code=404, detail="System member missing @odata.id")
    if system_url.startswith("/"):
        system_url = scheme_host + system_url
    return system_url

def fetch_collection(base_url, collection_pointer, user, password):
    members = []
    if not collection_pointer or '@odata.id' not in collection_pointer:
        return members
    coll_url = collection_pointer['@odata.id']
    if coll_url.startswith("/"):
        scheme_host = base_url.split("/redfish/v1")[0]
        full_url = scheme_host + coll_url
    else:
        full_url = coll_url
    data = redfish_get(full_url, user, password)
    if data is None:
        logging.error(f"Redfish GET returned None for url {full_url}")
        return members
    members_list = data.get('Members') or []
    for member in members_list:
        member_url = member.get('@odata.id')
        if member_url is None:
            logging.warning(f"Member missing @odata.id in {full_url}: {member}")
            continue
        if member_url.startswith("/"):
            scheme_host = base_url.split("/redfish/v1")[0]
            member_full_url = scheme_host + member_url
        else:
            member_full_url = member_url
        member_data = redfish_get(member_full_url, user, password)
        if member_data is not None:
            members.append(member_data)
        else:
            logging.error(f"Redfish GET returned None for member {member_full_url}")
    return members

def process_bios(bios, system_id, VamanitServer):
    clean_redfish_json(bios)
    tags = {"system_id": system_id, "Id": bios.get("Id", ""), "VamanitServer": VamanitServer}
    return line_protocol_generic("Bios", bios, tags)

def process_system(system, VamanitServer):
    clean_redfish_json(system)
    tags = {"system_id": system.get("Id", ""), "Name": system.get("Name", ""), "VamanitServer": VamanitServer}
    return line_protocol_generic("System", system, tags)

def process_memory(mem, system_id, VamanitServer):
    clean_redfish_json(mem)
    tags = {"system_id": system_id, "Id": mem.get("Id", ""), "VamanitServer": VamanitServer}
    return line_protocol_generic("Memory", mem, tags)

def process_processor(proc, system_id, VamanitServer):
    clean_redfish_json(proc)
    tags = {"system_id": system_id, "Id": proc.get("Id", ""), "VamanitServer": VamanitServer}
    return line_protocol_generic("Processor", proc, tags)

def process_ethernet(iface, system_id, VamanitServer):
    clean_redfish_json(iface)
    tags = {"system_id": system_id, "Id": iface.get("Id", ""), "VamanitServer": VamanitServer}
    return line_protocol_generic("Ethernet", iface, tags)

def process_storage_drive(drive, system_id, storage_id, VamanitServer):
    clean_redfish_json(drive)
    tags = {
        "system_id": system_id,
        "storage_id": storage_id,
        "drive_id": drive.get("Id", ""),
        "VamanitServer": VamanitServer,
    }
    return line_protocol_generic("Storage", drive, tags)

def process_chassis(chassis, VamanitServer):
    clean_redfish_json(chassis)
    tags = {"chassis_id": chassis.get("Id", ""), "VamanitServer": VamanitServer}
    return line_protocol_generic("Chassis", chassis, tags)

def process_temperature(temp, system_id, chassis_id, VamanitServer):
    clean_redfish_json(temp)
    tags = {
        "system_id": system_id,
        "chassis_id": chassis_id,
        "MemberId": temp.get("MemberId", ""),
        "VamanitServer": VamanitServer,
    }
    return line_protocol_generic("Temperature", temp, tags)

def process_fan(fan, system_id, chassis_id, VamanitServer):
    clean_redfish_json(fan)
    tags = {
        "system_id": system_id,
        "chassis_id": chassis_id,
        "MemberId": fan.get("MemberId", ""),
        "VamanitServer": VamanitServer,
    }
    return line_protocol_generic("Fan", fan, tags)

def process_thermal_redundancy(red, system_id, chassis_id, VamanitServer):
    clean_redfish_json(red)
    tags = {
        "system_id": system_id,
        "chassis_id": chassis_id,
        "MemberId": red.get("MemberId", ""),
        "VamanitServer": VamanitServer,
    }
    return line_protocol_generic("ThermalRedundancy", red, tags)

def process_power_control(ctrl, system_id, chassis_id, VamanitServer):
    clean_redfish_json(ctrl)
    powerlimit = ctrl.get("PowerLimit", {})
    ctrl["PowerLimit_CorrectionInMs"] = normalize_correction_in_ms(powerlimit.get("CorrectionInMs"))
    tags = {
        "system_id": system_id,
        "chassis_id": chassis_id,
        "MemberId": ctrl.get("MemberId", ""),
        "VamanitServer": VamanitServer,
    }
    return line_protocol_generic("PowerControl", ctrl, tags)

def process_voltage(voltage, system_id, chassis_id, VamanitServer):
    clean_redfish_json(voltage)
    tags = {
        "system_id": system_id,
        "chassis_id": chassis_id,
        "MemberId": voltage.get("MemberId", ""),
        "VamanitServer": VamanitServer,
    }
    return line_protocol_generic("Voltage", voltage, tags)

def process_power_redundancy(red, system_id, chassis_id, VamanitServer):
    clean_redfish_json(red)
    tags = {
        "system_id": system_id,
        "chassis_id": chassis_id,
        "MemberId": red.get("MemberId", ""),
        "VamanitServer": VamanitServer,
    }
    return line_protocol_generic("PowerRedundancy", red, tags)

def process_pcie_device(device, system_id, VamanitServer):
    clean_redfish_json(device)
    tags = {
        "system_id": system_id,
        "pcie_device_id": device.get("Id", ""),
        "VamanitServer": VamanitServer,
    }
    return line_protocol_generic("PCIeDevice", device, tags)

def process_pcie_function(func, system_id, pcie_device_id, VamanitServer):
    clean_redfish_json(func)
    tags = {
        "system_id": system_id,
        "pcie_device_id": pcie_device_id,
        "pcie_function_id": func.get("Id", ""),
        "VamanitServer": VamanitServer,
    }
    return line_protocol_generic("PCIeFunction", func, tags)

def line_protocol_generic(measurement, record, tags_dict):
    clean_redfish_json(record)
    flat = flatten_json(record)
    tags = [f"{k}={escape_tag(v)}" for k, v in tags_dict.items()]
    fields = []
    for key, value in flat.items():
        if key in tags_dict:
            continue
        if key == "PowerLimit_LimitInWatts":
            fields.append(f"{key}={escape_field_powerlimit(value)}")
        else:
            fields.append(f"{key}={escape_field(value)}")
    return f"{measurement},{','.join(tags)} {','.join(fields)}"

def fetch_pcie_devices(system, VamanitServer, user, password):
    lines = []
    system_id = system.get('Id', '')
    pcie_devices_list = system.get('PCIeDevices') or []
    scheme_host = f"https://{VamanitServer}"
    for dev_ref in pcie_devices_list:
        dev_url = dev_ref.get('@odata.id')
        if not dev_url:
            logging.warning(f"PCIeDevice object missing @odata.id: {dev_ref}")
            continue
        dev_full_url = scheme_host + dev_url if dev_url.startswith("/") else dev_url
        device = redfish_get(dev_full_url, user, password)
        if device is None:
            logging.error(f"Redfish GET returned None for PCIeDevice {dev_full_url}")
            continue
        device_id = device.get('Id', '')
        line = process_pcie_device(device, system_id, VamanitServer)
        lines.append(line)
        functions_ptr = device.get('PCIeFunctions')
        if functions_ptr and '@odata.id' in functions_ptr:
            functions_url = functions_ptr['@odata.id']
            functions_full_url = scheme_host + functions_url if functions_url.startswith("/") else functions_url
            functions_collection = redfish_get(functions_full_url, user, password)
            if functions_collection is not None:
                functions_members = functions_collection.get('Members') or []
                for func_obj in functions_members:
                    func_url = func_obj.get('@odata.id')
                    if func_url is None:
                        logging.warning(f"PCIeFunction object missing @odata.id: {func_obj}")
                        continue
                    func_full_url = scheme_host + func_url if func_url.startswith("/") else func_url
                    func = redfish_get(func_full_url, user, password)
                    if func is not None:
                        lines.append(process_pcie_function(func, system_id, device_id, VamanitServer))
                    else:
                        logging.error(f"Redfish GET returned None for PCIeFunction {func_full_url}")
    return lines

def fetch_chassis_thermal_power(system, VamanitServer, user, password):
    lines = []
    system_id = system.get('Id', '')
    chassis_list = system.get('Links', {}).get('Chassis', [])
    scheme_host = f"https://{VamanitServer}"

    def process_endpoint(parent_obj, parent_id, endpoint_key, processors):
        endpoint_ptr = parent_obj.get(endpoint_key)
        if endpoint_ptr and '@odata.id' in endpoint_ptr:
            endpoint_url = endpoint_ptr['@odata.id']
            endpoint_full_url = scheme_host + endpoint_url if endpoint_url.startswith("/") else endpoint_url
            endpoint = redfish_get(endpoint_full_url, user, password)
            if endpoint is None:
                logging.error(f"Redfish GET returned None for endpoint {endpoint_url}")
                return
            for field, processor in processors.items():
                for item in endpoint.get(field) or []:
                    lines.append(processor(item, system_id, parent_id, VamanitServer))

    for chassis_ref in chassis_list:
        chassis_url = chassis_ref['@odata.id']
        chassis_full_url = scheme_host + chassis_url if chassis_url.startswith("/") else chassis_url
        chassis = redfish_get(chassis_full_url, user, password)
        if chassis is None:
            logging.error(f"Redfish GET returned None for chassis {chassis_url}")
            continue
        chassis_id = chassis.get('Id', '')
        lines.append(process_chassis(chassis, VamanitServer))

        contains_list = chassis.get('Links', {}).get('Contains', [])
        if contains_list:
            for contains_ref in contains_list:
                contains_url = contains_ref['@odata.id']
                contains_full_url = scheme_host + contains_url if contains_url.startswith("/") else contains_url
                contains = redfish_get(contains_full_url, user, password)
                if contains is None:
                    logging.error(f"Redfish GET returned None for contains {contains_url}")
                    continue
                contains_id = contains.get('Id', '')
                process_endpoint(contains, contains_id, 'Thermal', {
                    'Temperatures': process_temperature,
                    'Fans': process_fan,
                    'Redundancy': process_thermal_redundancy,
                })
                process_endpoint(contains, contains_id, 'Power', {
                    'PowerControl': process_power_control,
                    'Voltages': process_voltage,
                    'Redundancy': process_power_redundancy,
                })
        else:
            process_endpoint(chassis, chassis_id, 'Thermal', {
                'Temperatures': process_temperature,
                'Fans': process_fan,
                'Redundancy': process_thermal_redundancy,
            })
            process_endpoint(chassis, chassis_id, 'Power', {
                'PowerControl': process_power_control,
                'Voltages': process_voltage,
                'Redundancy': process_power_redundancy,
            })
    return lines

def collect_and_push_device_data(device):
    import logging
    import requests
    from service.helper import (
        escape_tag, escape_field, escape_field_powerlimit,
        flatten_json, clean_redfish_json, safeget, normalize_correction_in_ms
    )

    IPMI_SERVER = device["ipmi_server_ip"]
    REDFISH_USER = device["username"]
    REDFISH_PASS = device["password"]
    REDFISH_ROOT = f"https://{IPMI_SERVER}/redfish/v1"
    VamanitServer = IPMI_SERVER

    logging.info(f"On-demand Processing device: {device.get('name', IPMI_SERVER)} ({IPMI_SERVER})")

    try:
        root = redfish_get(REDFISH_ROOT, REDFISH_USER, REDFISH_PASS)
        if root is None:
            logging.error("Redfish root GET returned None")
            return False

        systems_collection = redfish_get(
            REDFISH_ROOT.split("/redfish/v1")[0] + root['Systems']['@odata.id'],
            REDFISH_USER, REDFISH_PASS
        )
        if systems_collection is None:
            logging.error("Systems collection GET returned None")
            return False

        systems_members = systems_collection.get('Members') or []
        for sys_obj in systems_members:
            sys_url = sys_obj.get('@odata.id')
            if sys_url is None:
                logging.warning(f"System object missing @odata.id: {sys_obj}")
                continue
            system = redfish_get(
                REDFISH_ROOT.split("/redfish/v1")[0] + sys_url,
                REDFISH_USER, REDFISH_PASS
            )
            if system is None:
                logging.error(f"Redfish GET returned None for system {sys_url}")
                continue
            system_id = system.get('Id', '')

            lines = [process_system(system, VamanitServer)]

            bios_ptr = system.get('Bios')
            if bios_ptr and '@odata.id' in bios_ptr:
                bios_url = bios_ptr['@odata.id']
                bios_full_url = bios_url
                if bios_url.startswith("/"):
                    scheme_host = REDFISH_ROOT.split("/redfish/v1")[0]
                    bios_full_url = scheme_host + bios_url
                bios = redfish_get(bios_full_url, REDFISH_USER, REDFISH_PASS)
                if bios is not None:
                    lines.append(process_bios(bios, system_id, VamanitServer))
                else:
                    logging.error(f"Redfish GET returned None for BIOS {bios_full_url}")

            memory_members = fetch_collection(REDFISH_ROOT, system.get('Memory'), REDFISH_USER, REDFISH_PASS)
            for mem in memory_members:
                lines.append(process_memory(mem, system_id, VamanitServer))

            processor_members = fetch_collection(REDFISH_ROOT, system.get('Processors'), REDFISH_USER, REDFISH_PASS)
            for proc in processor_members:
                lines.append(process_processor(proc, system_id, VamanitServer))

            ethernet_members = fetch_collection(REDFISH_ROOT, system.get('EthernetInterfaces'), REDFISH_USER, REDFISH_PASS)
            for iface in ethernet_members:
                lines.append(process_ethernet(iface, system_id, VamanitServer))

            storage_members = fetch_collection(REDFISH_ROOT, system.get('Storage'), REDFISH_USER, REDFISH_PASS)
            for st in storage_members:
                storage_id = st.get('Id', '')
                for drive_ref in st.get('Drives', []):
                    drive_url = drive_ref['@odata.id']
                    drive_full_url = drive_url
                    if drive_url.startswith("/"):
                        scheme_host = REDFISH_ROOT.split("/redfish/v1")[0]
                        drive_full_url = scheme_host + drive_url
                    drive = redfish_get(drive_full_url, REDFISH_USER, REDFISH_PASS)
                    if drive is not None:
                        lines.append(process_storage_drive(drive, system_id, storage_id, VamanitServer))
                    else:
                        logging.error(f"Redfish GET returned None for drive {drive_full_url}")

            lines.extend(fetch_pcie_devices(system, VamanitServer, REDFISH_USER, REDFISH_PASS))
            lines.extend(fetch_chassis_thermal_power(system, VamanitServer, REDFISH_USER, REDFISH_PASS))

            # Write to InfluxDB (use SESSION with a timeout)
            data = "\n".join(lines)
            try:
                resp = SESSION.post(INFLUX_URL, params=INFLUX_PARAMS, headers=INFLUX_HEADERS, data=data, timeout=DEFAULT_TIMEOUT, verify=False)
                if resp.status_code == 204:
                    logging.info(f"All data written to InfluxDB successfully for {IPMI_SERVER}.")
                else:
                    logging.error(f"Failed to write to InfluxDB for {IPMI_SERVER}: {resp.status_code} {resp.text}")
                    return False
            except Exception as e:
                logging.error(f"InfluxDB write failed for {IPMI_SERVER}: {e}")
                return False
        return True
    except Exception as e:
        logging.error(f"Exception during collect_and_push_device_data: {e}")
        return False

def main():
    devices = get_all_ipmi_devices()
    logging.info(f"Retrieved {len(devices)} devices from file")
    if not devices:
        logging.error("No IPMI devices found in file")
        return

    for device in devices:
        IPMI_SERVER = device["ipmi_server_ip"]
        REDFISH_USER = device["username"]
        REDFISH_PASS = device["password"]
        REDFISH_ROOT = f"https://{IPMI_SERVER}/redfish/v1"
        VamanitServer = IPMI_SERVER

        logging.info(f"Processing device: {device['name']} ({IPMI_SERVER})")

        root = redfish_get(REDFISH_ROOT, REDFISH_USER, REDFISH_PASS)
        if root is None:
            logging.error("Redfish root GET returned None")
            continue
        systems_collection = redfish_get(
            REDFISH_ROOT.split("/redfish/v1")[0] + root['Systems']['@odata.id'],
            REDFISH_USER, REDFISH_PASS
        )
        if systems_collection is None:
            logging.error("Systems collection GET returned None")
            continue
        systems_members = systems_collection.get('Members') or []
        for sys_obj in systems_members:
            sys_url = sys_obj.get('@odata.id')
            if sys_url is None:
                logging.warning(f"System object missing @odata.id: {sys_obj}")
                continue
            system = redfish_get(
                REDFISH_ROOT.split("/redfish/v1")[0] + sys_url,
                REDFISH_USER, REDFISH_PASS
            )
            if system is None:
                logging.error(f"Redfish GET returned None for system {sys_url}")
                continue
            system_id = system.get('Id', '')

            lines = [process_system(system, VamanitServer)]

            bios_ptr = system.get('Bios')
            if bios_ptr and '@odata.id' in bios_ptr:
                bios_url = bios_ptr['@odata.id']
                bios_full_url = bios_url
                if bios_url.startswith("/"):
                    scheme_host = REDFISH_ROOT.split("/redfish/v1")[0]
                    bios_full_url = scheme_host + bios_url
                bios = redfish_get(bios_full_url, REDFISH_USER, REDFISH_PASS)
                if bios is not None:
                    lines.append(process_bios(bios, system_id, VamanitServer))
                else:
                    logging.error(f"Redfish GET returned None for BIOS {bios_full_url}")

            memory_members = fetch_collection(REDFISH_ROOT, system.get('Memory'), REDFISH_USER, REDFISH_PASS)
            for mem in memory_members:
                lines.append(process_memory(mem, system_id, VamanitServer))

            processor_members = fetch_collection(REDFISH_ROOT, system.get('Processors'), REDFISH_USER, REDFISH_PASS)
            for proc in processor_members:
                lines.append(process_processor(proc, system_id, VamanitServer))

            ethernet_members = fetch_collection(REDFISH_ROOT, system.get('EthernetInterfaces'), REDFISH_USER, REDFISH_PASS)
            for iface in ethernet_members:
                lines.append(process_ethernet(iface, system_id, VamanitServer))

            storage_members = fetch_collection(REDFISH_ROOT, system.get('Storage'), REDFISH_USER, REDFISH_PASS)
            for st in storage_members:
                storage_id = st.get('Id', '')
                for drive_ref in st.get('Drives', []):
                    drive_url = drive_ref['@odata.id']
                    drive_full_url = drive_url
                    if drive_url.startswith("/"):
                        scheme_host = REDFISH_ROOT.split("/redfish/v1")[0]
                        drive_full_url = scheme_host + drive_url
                    drive = redfish_get(drive_full_url, REDFISH_USER, REDFISH_PASS)
                    if drive is not None:
                        lines.append(process_storage_drive(drive, system_id, storage_id, VamanitServer))
                    else:
                        logging.error(f"Redfish GET returned None for drive {drive_full_url}")

            lines.extend(fetch_pcie_devices(system, VamanitServer, REDFISH_USER, REDFISH_PASS))
            lines.extend(fetch_chassis_thermal_power(system, VamanitServer, REDFISH_USER, REDFISH_PASS))

            # Write to InfluxDB (use SESSION with a timeout)
            data = "\n".join(lines)
            try:
                resp = SESSION.post(INFLUX_URL, params=INFLUX_PARAMS, headers=INFLUX_HEADERS, data=data, timeout=DEFAULT_TIMEOUT, verify=False)
                if resp.status_code == 204:
                    logging.info("All data written to InfluxDB successfully.")
                else:
                    logging.error(f"Failed to write to InfluxDB: {resp.status_code} {resp.text}")
            except Exception as e:
                logging.error(f"InfluxDB write failed: {e}")

if __name__ == "__main__":
    main()
