#!/usr/bin/env python3
"""
Quick connectivity tester for a Redfish host.
Usage: python3 test_redfish_conn.py 10.1.2.110 username password
"""
import sys
import socket
import ssl
import requests
from urllib.parse import urljoin
import traceback

if len(sys.argv) != 4:
    print("Usage: python3 test_redfish_conn.py <host> <user> <pass>")
    sys.exit(2)

host = sys.argv[1]
user = sys.argv[2]
pw = sys.argv[3]
addr = host
port = 443

print("1) TCP connect test to", f"{addr}:{port}")
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(5)
try:
    sock.connect((addr, port))
    print("  TCP connect: SUCCESS")
except Exception as e:
    print("  TCP connect: FAILED:", type(e).__name__, e)
    sock.close()
    # Still continue to run higher-level checks for more info
else:
    sock.close()

print("\n2) TLS handshake (openssl-style) to", f"{addr}:{port}")
context = ssl.create_default_context()
context.check_hostname = False
context.verify_mode = ssl.CERT_NONE
try:
    with socket.create_connection((addr, port), timeout=5) as s:
        with context.wrap_socket(s, server_hostname=addr) as ss:
            cert = ss.getpeercert()
            print("  TLS handshake: SUCCESS")
            print("  Peer cert subject:", cert.get('subject') if cert else "<no cert>")
except Exception as e:
    print("  TLS handshake: FAILED:", type(e).__name__, e)

print("\n3) HTTP GET to /redfish/v1 (requests, verify=False)")
url = f"https://{host}/redfish/v1"
try:
    r = requests.get(url, auth=(user, pw), verify=False, timeout=(5,10))
    print("  HTTP status:", r.status_code)
    print("  Content-Type:", r.headers.get('Content-Type'))
    print("  Body (first 400 chars):")
    print(r.text[:400])
except Exception as e:
    print("  HTTP GET: FAILED:", type(e).__name__, e)
    traceback.print_exc()