import json
import os
import logging
from fastapi import APIRouter, HTTPException, Body, BackgroundTasks
import requests
from service.IPMI import get_first_system_url, redfish_get, collect_and_push_device_data, SESSION, DEFAULT_TIMEOUT
from service.IpmiServer import get_all_ipmi_devices

router = APIRouter()
logging.basicConfig(level=logging.INFO)

def get_ipmi_creds(device_id):
    devices = get_all_ipmi_devices()
    logging.info(f"Retrieved {len(devices)} devices from file")
    for dev in devices:
        if str(dev["id"]) == str(device_id):
            return (
                dev["ipmi_server_ip"],
                dev["username"],
                dev["password"]
            )
    raise HTTPException(status_code=404, detail="Device not found in file")

@router.get("/powerstate/{device_id}")
def get_system_power_state(device_id: int):
    ip, user, password = get_ipmi_creds(device_id)
    redfish_root = f"https://{ip}/redfish/v1"
    try:
        system_url = get_first_system_url(redfish_root, user, password)
    except HTTPException as e:
        return {"power_state": None, "error": e.detail}
    system = redfish_get(system_url, user, password)
    if not system:
        return {"power_state": None, "error": "Unable to retrieve system data"}
    power_state = system.get("PowerState", "Unknown")
    return {"power_state": power_state}

@router.post("/powercontrol/{device_id}")
async def set_power_action(
    device_id: int, 
    action: str = Body(..., embed=True), 
    background_tasks: BackgroundTasks = None
):
    ip, user, password = get_ipmi_creds(device_id)
    redfish_root = f"https://{ip}/redfish/v1"
    system_url = get_first_system_url(redfish_root, user, password)
    system = redfish_get(system_url, user, password)
    if not system:
        raise HTTPException(status_code=404, detail="Unable to retrieve system data")
    actions = system.get("Actions", {})
    reset_action = actions.get("#ComputerSystem.Reset", {})
    reset_url = reset_action.get("target")
    if not reset_url:
        raise HTTPException(status_code=404, detail="No power control endpoint found")
    scheme_host = system_url.split("/redfish/v1")[0]
    if reset_url.startswith("/"):
        reset_url = scheme_host + reset_url

    action_map = {
        "Power Off": "ForceOff",
        "Power On": "On",
        "Power Cycle": "PushPowerButton",
        "Hard Reset": "ForceRestart",
        "ACPI Shutdown": "GracefulShutdown",
        "NMI": "Nmi"
    }
    reset_type = action_map.get(action)
    if not reset_type:
        raise HTTPException(status_code=400, detail=f"Invalid action '{action}'")

    try:
        resp = SESSION.post(reset_url, json={"ResetType": reset_type}, auth=(user, password), verify=False, timeout=DEFAULT_TIMEOUT)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Redfish action request failed: {e}")
    if resp.status_code in [200, 202, 204]:
        # On-demand collect/push for just this device (background, non-blocking)
        devices = get_all_ipmi_devices()
        device = next((d for d in devices if str(d["id"]) == str(device_id)), None)
        if device and background_tasks:
            background_tasks.add_task(collect_and_push_device_data, device)
        return {"status": "success", "action": action, "reset_type": reset_type}
    else:
        raise HTTPException(status_code=resp.status_code, detail=f"Redfish action failed: {resp.text}")

@router.get("/IndicatorLEDState/{device_id}")
def get_uid_state(device_id: int):
    ip, user, password = get_ipmi_creds(device_id)
    redfish_root = f"https://{ip}/redfish/v1"
    try:
        system_url = get_first_system_url(redfish_root, user, password)
    except HTTPException as e:
        return {"uid_state": None, "error": e.detail}
    system = redfish_get(system_url, user, password)
    if not system:
        return {"uid_state": None, "error": "Unable to retrieve system data"}
    uid_state = system.get("IndicatorLED", None)
    uid_allowable = system.get("IndicatorLED@Redfish.AllowableValues", [])
    return {
        "uid_state": uid_state,
        "uid_allowable": uid_allowable
    }

@router.post("/IndicatorLED/{device_id}")
async def set_uid_action(
    device_id: int, 
    uid_action: str = Body(..., embed=True), 
    background_tasks: BackgroundTasks = None
):
    ip, user, password = get_ipmi_creds(device_id)
    redfish_root = f"https://{ip}/redfish/v1"
    chassis_url = f"{redfish_root}/Chassis/Self"
    try:
        resp = SESSION.get(chassis_url, auth=(user, password), verify=False, timeout=DEFAULT_TIMEOUT)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Failed to get chassis: {e}")
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=f"Failed to get chassis: {resp.text}")
    data = resp.json()
    etag = data.get("@odata.etag")
    if not etag:
        raise HTTPException(status_code=400, detail="ETag not found in chassis resource.")
    uid_map = {
        "Turn On": "Lit",
        "Temporary On": "Blinking",
        "Turn Off": "Off"
    }
    indicator_value = uid_map.get(uid_action)
    allowable = data.get("IndicatorLED@Redfish.AllowableValues", ["Lit", "Blinking", "Off"])
    if indicator_value not in allowable:
        raise HTTPException(status_code=400, detail=f"UID value '{indicator_value}' not allowed. Allowed: {allowable}")

    patch_headers = {
        "Content-Type": "application/json",
        "If-Match": etag
    }
    try:
        patch_resp = SESSION.patch(
            chassis_url,
            json={"IndicatorLED": indicator_value},
            auth=(user, password),
            verify=False,
            headers=patch_headers,
            timeout=DEFAULT_TIMEOUT
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Redfish UID PATCH failed: {e}")
    if patch_resp.status_code in [200, 202, 204]:
        # On-demand collect/push for just this device (background, non-blocking)
        devices = get_all_ipmi_devices()
        device = next((d for d in devices if str(d["id"]) == str(device_id)), None)
        if device and background_tasks:
            background_tasks.add_task(collect_and_push_device_data, device)
        return {"status": "success", "action": uid_action, "indicator_value": indicator_value}
    else:
        raise HTTPException(status_code=patch_resp.status_code, detail=f"Redfish UID action failed: {patch_resp.text}")
