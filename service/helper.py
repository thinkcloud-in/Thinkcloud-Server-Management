def escape_tag(value):
    if value is None:
        return ""
    return str(value).replace(" ", r"\ ").replace(",", r"\,").replace("=", r"\=")

def escape_field(value):
    if isinstance(value, str):
        return '"' + value.replace('"', r'\"') + '"'
    elif value is None:
        return '""'
    else:
        return str(value)

def escape_field_powerlimit(value):
    if value is None or value == "":
        return '""'
    return '"' + str(value).replace('"', r'\"') + '"'

def flatten_json(obj, prefix=''):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}{k}" if prefix else k
            out.update(flatten_json(v, key + "_"))
    elif isinstance(obj, list):
        for idx, v in enumerate(obj):
            key = f"{prefix}{idx}" if prefix else str(idx)
            out.update(flatten_json(v, key + "_"))
    else:
        key = prefix[:-1] if prefix.endswith("_") else prefix
        out[key] = obj
    return out

def clean_redfish_json(obj):
    for k in ['@odata.context', '@odata.id', '@odata.type', '@odata.etag', '@Redfish.Settings']:
        obj.pop(k, None)
    return obj

def safeget(d, *keys, default=""):
    for key in keys:
        if isinstance(d, dict) and key in d:
            d = d[key]
        else:
            return default
    return d

def normalize_correction_in_ms(value):
    if value is None:
        return ""
    return str(value)