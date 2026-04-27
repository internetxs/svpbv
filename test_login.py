"""Standalone login diagnostic — run with: python3 test_login.py"""
import asyncio
import getpass
import json
import random
import time
from urllib.parse import unquote

import aiohttp

BASE_URL = "https://mijn.svpbv.nl/CustomerApp"
MODULE_VERSION_URL = f"{BASE_URL}/moduleservices/moduleversioninfo"
LOGIN_URL = f"{BASE_URL}/screenservices/CustomerApp/Common/Login/ActionDoLogin"

HEADERS_BASE = {
    "Content-Type": "application/json; charset=UTF-8",
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_3 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/22D63"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9",
    "OutSystems-client-env": "native",
    "outsystems-device-uuid": "HA-SVPBV-INTEGRATION-0001",
}


def _random_request_token():
    return str(random.randint(1000000000000000, 9999999999999999))


def _extract_csrf(jar):
    for cookie in jar:
        print(f"  Cookie: {cookie.key} = {cookie.value[:60]}...")
        if cookie.key == "nr2Users":
            raw = unquote(cookie.value)
            print(f"  nr2Users decoded: {raw[:120]}")
            for part in raw.split(";"):
                part = part.strip()
                if part.startswith("crf="):
                    return part[4:]
    return None


async def main():
    username = input("Username (email): ").strip()
    password = getpass.getpass("Password: ")

    jar = aiohttp.CookieJar(unsafe=True)
    async with aiohttp.ClientSession(cookie_jar=jar) as session:

        # Step 1: module version
        print("\n--- Step 1: module version ---")
        ts = int(time.time() * 1000)
        async with session.get(f"{MODULE_VERSION_URL}?{ts}", headers=HEADERS_BASE) as resp:
            print(f"Status: {resp.status}")
            data = await resp.json(content_type=None)
            print(f"Response: {json.dumps(data)[:200]}")
            version_token = data.get("versionToken", "")
            print(f"versionToken: {version_token}")

        # Step 2: check cookies after module version
        print("\n--- Cookies after module version ---")
        csrf = _extract_csrf(jar)
        print(f"CSRF token found: {csrf}")

        if not csrf:
            print("\nNo CSRF cookie set by module version endpoint.")
            print("Trying GET to app root to establish session...")
            async with session.get(
                "https://mijn.svpbv.nl/CustomerApp/",
                headers={**HEADERS_BASE, "Accept": "text/html,*/*"},
                allow_redirects=True,
            ) as resp2:
                print(f"App root status: {resp2.status}, final URL: {resp2.url}")
            csrf = _extract_csrf(jar)
            print(f"CSRF token after app root GET: {csrf}")

        # Step 3: attempt login
        print("\n--- Step 3: login POST ---")
        headers = dict(HEADERS_BASE)
        headers["outsystems-request-token"] = _random_request_token()
        if csrf:
            headers["x-csrftoken"] = csrf

        payload = {
            "versionInfo": {
                "moduleVersion": version_token,
                "apiVersion": "OW6SzyxPDcdFr8DWQcIgNA",
            },
            "viewName": "Common.Login",
            "inputParameters": {
                "Username": username,
                "Password": password,
            },
        }

        async with session.post(LOGIN_URL, json=payload, headers=headers) as resp:
            print(f"Status: {resp.status}")
            body = await resp.json(content_type=None)
            print(f"Full response: {json.dumps(body, indent=2)[:1000]}")

        print("\n--- Cookies after login ---")
        _extract_csrf(jar)


asyncio.run(main())
