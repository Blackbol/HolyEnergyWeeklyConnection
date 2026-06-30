"""HTTP client for connecting to the Holy Energy Shopify store via saved session."""

import base64
import json
import logging
import os
import re
import time
import urllib.parse
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

from holy_energy_weekly_connection.exceptions import (
    AuthenticationError,
    NetworkError,
)
from holy_energy_weekly_connection.models import ConnectionResult, Credentials

logger = logging.getLogger(__name__)

_PROD = 25  # human-friendly log level, between INFO(20) and WARNING(30)

# Shopify rotates _shopify_essential on every response.
# The updated value is persisted here so each run uses the latest cookie.
COOKIE_FILE = Path(os.getenv("HOLY_COOKIE_FILE", "data/cookie.txt"))

BASE_URL = "https://fr.holy.com"
ACCOUNT_URL = f"{BASE_URL}/account"
LOGIN_URL = f"{BASE_URL}/account/login"
LOYALTYLION_INIT_URL = "https://sdk.loyaltylion.net/sdk/init"

_CHROME_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_HEADERS = {
    "User-Agent": _CHROME_UA,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;"
        "q=0.8,application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Linux"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
}


def _js_encode(obj: object) -> str:
    """Replicate JS btoa(encodeURIComponent(JSON.stringify(obj))).

    LoyaltyLion encodes structured objects this way before sending them
    as query parameters to /sdk/init.
    """
    j = json.dumps(obj, separators=(",", ":"))
    pct = urllib.parse.quote(j, safe="~!*'()")
    return base64.b64encode(pct.encode()).decode()


class HolyEnergyClient:
    """Connects to Holy Energy to earn HOLY Coins loyalty points.

    Authenticates via a saved Shopify session cookie (_shopify_essential),
    then calls the LoyaltyLion SDK init endpoint to trigger the weekly
    visit point credit — the same call a real browser would make.

    Args:
        credentials: Credentials loaded from environment variables.
    """

    def __init__(self, credentials: Credentials) -> None:
        self._credentials = credentials
        # Prefer the persisted cookie (updated after each run) over the .env value.
        cookie = self._load_cookie(credentials.shopify_cookie.get_secret_value())
        self._http = httpx.Client(
            timeout=credentials.timeout,
            follow_redirects=True,
            cookies={"_shopify_essential": cookie},
        )

    @staticmethod
    def _load_cookie(env_cookie: str) -> str:
        """Return the persisted cookie if available, otherwise the .env value."""
        try:
            saved = COOKIE_FILE.read_text().strip()
            if saved:
                logger.debug("Using persisted cookie from %s", COOKIE_FILE)
                return saved
        except FileNotFoundError:
            pass
        return env_cookie

    def _save_cookie(self) -> None:
        """Persist the latest cookie Shopify sent so the next run stays valid."""
        # The jar can hold several _shopify_essential entries with different
        # Domain attributes (the one we seeded manually vs. the one Shopify
        # set in its response), so .get() raises CookieConflict. Take the
        # last match instead — it's the one most recently written to the jar.
        matches = [c for c in self._http.cookies.jar if c.name == "_shopify_essential"]
        if not matches:
            return
        new_value = matches[-1].value
        try:
            COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
            COOKIE_FILE.write_text(new_value)
            logger.debug("Cookie persisted to %s", COOKIE_FILE)
        except OSError as exc:
            logger.warning("Could not persist cookie: %s", exc)

    def connect(self) -> ConnectionResult:
        """Visit the account page and trigger the LoyaltyLion weekly visit credit.

        Flow:
          1. GET /account — verify session is valid, extract LoyaltyLion tokens
          2. POST to LoyaltyLion /sdk/init — triggers the weekly visit points
          3. Parse response to confirm whether points were credited

        Returns:
            A ConnectionResult describing the outcome.

        Raises:
            NetworkError: If the account page request fails.
            AuthenticationError: If the session cookie has expired.
        """
        logger.info("Starting weekly connection to %s", BASE_URL)
        logger.log(_PROD, "Connexion au site Holy Energy en cours (%s)...", self._credentials.email)

        page_html = self._fetch_account_page()
        self._save_cookie()  # persist the rotated cookie Shopify sent with the response
        points_credited, message, balance = self._track_loyalty_visit(page_html)

        logger.info(message)
        if points_credited:
            logger.log(_PROD, "25 points credites — Balance totale : %d points", balance)
        else:
            logger.log(_PROD, "Points deja credites cette semaine — Balance totale : %d points", balance)

        return ConnectionResult(
            success=True,
            timestamp=datetime.now(tz=UTC),
            message=message,
        )

    def _fetch_account_page(self) -> str:
        """GET the account page to verify the session and retrieve LoyaltyLion tokens.

        Returns:
            The response HTML body.

        Raises:
            NetworkError: On HTTP or network failure.
            AuthenticationError: If the cookie has expired or is invalid.
        """
        logger.debug("Visiting %s with saved session cookie", ACCOUNT_URL)
        try:
            response = self._http.get(ACCOUNT_URL, headers=_HEADERS)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise NetworkError(
                f"Account page returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise NetworkError(f"Network error visiting account page: {exc}") from exc

        if LOGIN_URL in str(response.url):
            raise AuthenticationError(
                "Session cookie has expired or is invalid. "
                "Log in to fr.holy.com in your browser, extract the "
                "_shopify_essential cookie value, and update "
                "HOLY_SHOPIFY_COOKIE in .env."
            )

        logger.debug("Account page loaded — session valid")
        return response.text

    def _track_loyalty_visit(self, page_html: str) -> tuple[bool, str, int]:
        """Call the LoyaltyLion SDK init endpoint to trigger the visit credit.

        Replicates exactly what the browser's JS SDK does: encodes the auth
        tokens embedded in the page HTML and POSTs them to LoyaltyLion's API.

        Args:
            page_html: The HTML body of the account page.

        Returns:
            A 2-tuple of (points_credited, message).
        """
        # Extract the loyaltylion.init({...}) block from the page.
        m = re.search(r"loyaltylion\.init\(\{(.+?)\}\)", page_html, re.DOTALL)
        if not m:
            logger.warning("LoyaltyLion init block not found in page HTML")
            return False, (
                "Weekly connection completed. "
                "Could not find LoyaltyLion SDK config in page — "
                "points status unknown."
            ), 0

        init_block = m.group(1)

        # Parse the individual fields from the JS object literal.
        try:
            shop_token = re.search(r'token:\s*"([^"]+)"', init_block).group(1)  # type: ignore[union-attr]
            cid = re.search(r'id:\s*"([^"]+)"', init_block).group(1)  # type: ignore[union-attr]
            email = re.search(r'email:\s*"([^"]+)"', init_block).group(1)  # type: ignore[union-attr]
            auth_date = re.search(r'date:\s*"([^"]+)"', init_block).group(1)  # type: ignore[union-attr]
            # The HMAC mac token is the 40-char hex string under auth:
            mac = re.search(r'token:\s*"([a-f0-9]{40})"', init_block).group(1)  # type: ignore[union-attr]
        except AttributeError:
            logger.warning("Could not parse all LoyaltyLion init fields")
            return False, (
                "Weekly connection completed. "
                "Could not parse LoyaltyLion auth tokens — points status unknown."
            ), 0

        logger.debug("LoyaltyLion tokens extracted for customer %s", cid)

        # Build the encoded parameters the SDK sends to /sdk/init.
        visitor_id = str(uuid.uuid4())
        auth_packet = _js_encode(
            {"email": email, "id": cid, "date": auth_date, "mac": mac}
        )
        pageview_data = _js_encode(
            {
                "context": {
                    "referrer": {},
                    "visitor_id": visitor_id,
                    "browser": {"name": "Chrome", "version": "124"},
                    "device": {"type": "desktop"},
                    "os": {"name": "Linux"},
                    "resolution": "1920x1080",
                    "viewport": "1280x800",
                },
                "properties": {"page": ACCOUNT_URL},
                "time": str(int(time.time() * 1000)),
            }
        )

        params = {
            "r": "",
            "site_token": shop_token,
            "visitor_id": visitor_id,
            "pageview_data": pageview_data,
            "cid": cid,
            "auth_packet": auth_packet,
        }

        logger.debug("Calling LoyaltyLion /sdk/init to track weekly visit")
        try:
            result = httpx.post(
                LOYALTYLION_INIT_URL,
                params=params,
                headers={
                    "User-Agent": _CHROME_UA,
                    "Referer": ACCOUNT_URL,
                    "Origin": BASE_URL,
                },
                timeout=30,
            )
            result.raise_for_status()
            ll_data = result.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
            logger.warning("LoyaltyLion SDK init call failed: %s", exc)
            return False, (
                "Weekly connection completed. "
                f"LoyaltyLion API error — points status unknown: {exc}"
            ), 0

        customer = ll_data.get("customer", {})
        points_approved = customer.get("pointsApproved", 0)

        # Find the visit rule ID from the actions history.
        visit_rule_id = next(
            (a.get("ruleId") for a in customer.get("actions", [])
             if a.get("ruleKind") == "pageview"),
            None,
        )

        # Check pendingNotifications: populated when points are first credited
        # in a session that hasn't yet dismissed the notification.
        for notif in customer.get("pendingNotifications", []):
            if "point" in json.dumps(notif).lower():
                logger.debug("pendingNotifications: %s", notif)
                return True, (
                    f"Weekly connection completed. "
                    f"25 HOLY Coins credited — pour avoir visité. "
                    f"Balance: {points_approved} points."
                ), points_approved

        # Check completedRules: the date shows when the rule was last completed.
        # If it was completed within the last 10 seconds, THIS call credited it.
        # If it's older, it was already credited before (e.g. via browser).
        now = datetime.now(tz=UTC)
        for rule in customer.get("completedRules", []):
            if rule.get("ruleId") != visit_rule_id:
                continue
            try:
                completed_at = datetime.fromisoformat(
                    rule["date"].replace("Z", "+00:00")
                )
                seconds_ago = (now - completed_at).total_seconds()
                if seconds_ago < 10:
                    return True, (
                        f"Weekly connection completed. "
                        f"25 HOLY Coins credited — pour avoir visité. "
                        f"Balance: {points_approved} points."
                    ), points_approved
                else:
                    credited_when = completed_at.strftime("%Y-%m-%d at %H:%M UTC")
                    return False, (
                        f"Weekly connection completed. "
                        f"Points already credited this week "
                        f"(on {credited_when}). "
                        f"Balance: {points_approved} points."
                    ), points_approved
            except (KeyError, ValueError):
                pass

        # Fallback: ruleContext confirms limit reached but no completedRules entry.
        for ctx in customer.get("ruleContext", []):
            if ctx.get("id") == visit_rule_id and ctx.get("limitReached"):
                return False, (
                    f"Weekly connection completed. "
                    f"Points already credited this week. "
                    f"Balance: {points_approved} points."
                ), points_approved

        return False, (
            f"Weekly connection completed. "
            f"Visit registered — points status unknown. "
            f"Balance: {points_approved} points."
        ), points_approved

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self._http.close()

    def __enter__(self) -> "HolyEnergyClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
