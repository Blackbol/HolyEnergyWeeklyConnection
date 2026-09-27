"""HTTP client for connecting to Holy Energy and claiming weekly loyalty coins."""

import base64
import json
import logging
import re
import time
import urllib.parse
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from holy_energy_weekly_connection.dns_resolver import ensure_dns_resolution
from holy_energy_weekly_connection.exceptions import (
    AuthenticationError,
    LoyaltyLionError,
    NetworkError,
)
from holy_energy_weekly_connection.models import (
    ConnectionResult,
    Credentials,
    CustomerInfo,
)
from holy_energy_weekly_connection.notifier import send_notification

logger = logging.getLogger(__name__)

PROD = 25
logging.addLevelName(PROD, "PROD")

BASE_URL = "https://fr.holy.com"
ACCOUNT_URL = f"{BASE_URL}/account"
STORE_URL = f"{BASE_URL}/"
ACCOUNT_LOGIN_URL = f"{BASE_URL}/pages/account-login"
LOYALTYLION_INIT_URL = "https://sdk.loyaltylion.net/sdk/init"
DEFAULT_SHOP_TOKEN = "6e324c01a0c0fc74286ffcd8000b5912"

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
    return base64.b64encode(pct.encode("utf-8")).decode("ascii")


class HolyEnergyClient:
    """Automates weekly Holy Energy login and LoyaltyLion points claim.

    Authenticates using the persistent Shopify session cookie, extracts the
    LoyaltyLion authentication payload, and calls the LoyaltyLion SDK to claim
    the weekly visit reward.
    """

    def __init__(self, credentials: Credentials) -> None:
        self._credentials = credentials
        self._cookie_file: Path = credentials.cookie_file

        # Ensure DNS resolution is healthy (bypasses Pi-hole/AdGuard ad-blocking)
        ensure_dns_resolution("sdk.loyaltylion.net")

        # Load active cookie (preferring persisted rolling cookie, falling back to credentials)
        persisted = self._load_persisted_cookie()
        if persisted:
            logger.info(
                "Session : cookie roulant chargé depuis %s (taille: %d caractères, préfixe: %s...)",
                self._cookie_file,
                len(persisted),
                persisted[:12],
            )
            self._active_cookie = persisted
        else:
            env_val = credentials.shopify_cookie.get_secret_value()
            logger.info(
                "Session : cookie initial chargé depuis l'environnement .env (taille: %d caractères, préfixe: %s...)",
                len(env_val),
                env_val[:12],
            )
            self._active_cookie = env_val

        self._http = httpx.Client(
            timeout=credentials.timeout,
            follow_redirects=True,
            headers=_HEADERS,
        )
        self._set_client_cookies(self._active_cookie)

    def _set_client_cookies(self, cookie_value: str) -> None:
        """Assign the session cookie to the client jar for all Holy Energy domains."""
        self._active_cookie = cookie_value.strip().strip('"\'')
        for domain in ["fr.holy.com", ".holy.com", "shopify.com", ".shopify.com"]:
            self._http.cookies.set("_shopify_essential", self._active_cookie, domain=domain)
        self._http.cookies.set("_shopify_essential", self._active_cookie)
        logger.debug(
            "Cookie _shopify_essential assigné au client HTTP (domaines: fr.holy.com, .holy.com, shopify.com, .shopify.com, taille: %d)",
            len(self._active_cookie),
        )

    def _load_persisted_cookie(self) -> str | None:
        """Read the persisted rolling cookie from disk if it exists."""
        try:
            if not self._cookie_file.is_file():
                return None

            content = self._cookie_file.read_text(encoding="utf-8").strip().strip('"\'')
            if content and len(content) >= 15 and "..." not in content:
                logger.debug("Lecture réussie du cookie roulant dans %s", self._cookie_file)
                return content
            else:
                logger.debug("Le fichier de cookie roulant %s est vide ou invalide.", self._cookie_file)
        except OSError as exc:
            logger.warning("Impossible de lire le fichier de cookie %s: %s", self._cookie_file, exc)
        return None

    def _save_cookie(self, new_cookie: str | None) -> None:
        """Persist updated rolling cookie to disk."""
        if not new_cookie or not new_cookie.strip():
            logger.debug("Aucun nouveau cookie à persister (valeur vide).")
            return
        clean_cookie = new_cookie.strip()
        try:
            self._cookie_file.parent.mkdir(parents=True, exist_ok=True)
            self._cookie_file.write_text(clean_cookie, encoding="utf-8")
            self._active_cookie = clean_cookie
            logger.info(
                "🔄 Cookie roulant mis à jour et persisté dans %s (taille: %d caractères, préfixe: %s...)",
                self._cookie_file,
                len(clean_cookie),
                clean_cookie[:12],
            )
        except OSError as exc:
            logger.warning(
                "Échec de la persistance du cookie roulant dans %s: %s", self._cookie_file, exc
            )

    def _extract_response_cookie(self, response: httpx.Response) -> str | None:
        """Extract the latest _shopify_essential cookie returned by Shopify."""
        matches = [c for c in self._http.cookies.jar if c.name == "_shopify_essential"]
        if matches:
            val = matches[-1].value
            if val:
                logger.debug(
                    "Cookie _shopify_essential extrait de la réponse HTTP (taille: %d)", len(val)
                )
                return val
        return None

    def _is_login_redirect(self, url_str: str, html: str) -> bool:
        """Check if the URL or page corresponds to an unauthenticated login page."""
        lower_url = url_str.lower()
        if "shopify.com/authentication" in lower_url:
            logger.debug(
                "Détection déconnexion : redirection vers Shopify Accounts ('%s')", url_str
            )
            return True
        if "/customer_authentication/login" in lower_url:
            logger.debug(
                "Détection déconnexion : redirection vers customer_authentication/login ('%s')",
                url_str,
            )
            return True
        if "account/login" in lower_url and "/pages/account-login" not in lower_url:
            logger.debug("Détection déconnexion : redirection vers account/login ('%s')", url_str)
            return True

        # Check page markers
        if (
            ("<title>Se connecter" in html or "<title>Account login" in html)
            and 'action="/customer_authentication/login"' in html
            and 'id:"' not in html
        ):
            logger.debug(
                "Détection déconnexion : formulaire de login présent sans identifiants client connectés."
            )
            return True

        return False

    def verify_session(self) -> CustomerInfo:
        """Verify the current session cookie and extract customer tokens.

        Returns:
            CustomerInfo containing customer tokens and mac.

        Raises:
            AuthenticationError: If the cookie is expired or invalid.
            NetworkError: If the account page could not be fetched.
        """
        logger.debug("Checking session validity on Holy Energy...")
        info = self._fetch_and_parse_customer(use_env_fallback=True)
        return info

    def _fetch_and_parse_customer(self, use_env_fallback: bool = True) -> CustomerInfo:
        """Fetch Holy Energy storefront/account page and extract customer tokens with fallback."""
        urls_to_try = [ACCOUNT_URL, STORE_URL, ACCOUNT_LOGIN_URL]
        network_errors: list[Exception] = []
        any_http_success = False

        for url in urls_to_try:
            logger.debug("Tentative de récupération des identifiants client via %s...", url)
            t0 = time.time()
            try:
                response = self._http.get(url)
                elapsed = time.time() - t0
                logger.debug(
                    "Réponse reçue en %.2fs : HTTP %d, URL finale : %s",
                    elapsed,
                    response.status_code,
                    response.url,
                )
                response.raise_for_status()
                any_http_success = True
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                logger.debug("Requête sur %s a échoué : %s", url, exc)
                network_errors.append(exc)
                continue

            html = response.text
            final_url = str(response.url)

            if response.history:
                logger.debug(
                    "Redirections suivies (%d) : %s",
                    len(response.history),
                    " -> ".join([str(r.url) for r in response.history] + [final_url]),
                )

            # Check if this request redirected to an unauthenticated login page
            if self._is_login_redirect(final_url, html):
                logger.debug(
                    "Endpoint %s a redirigé vers une page de connexion (%s).",
                    url,
                    final_url,
                )
                continue

            # Parse LoyaltyLion customer block
            customer_info = self._parse_loyaltylion_tokens(html)
            if customer_info:
                # Session is valid: persist any refreshed cookie sent by Shopify
                new_cookie = self._extract_response_cookie(response)
                if new_cookie:
                    self._save_cookie(new_cookie)

                logger.info(
                    "✅ Session authentifiée vérifiée sur %s : customer_id=%s, email=%s, date_auth=%s",
                    url,
                    customer_info.customer_id,
                    customer_info.email,
                    customer_info.auth_date,
                )
                return customer_info
            else:
                logger.debug("Identifiants LoyaltyLion non trouvés sur %s.", url)

        # If all requests failed due to network errors, raise NetworkError
        if not any_http_success and network_errors:
            raise NetworkError(
                f"Échec de connexion réseau aux serveurs Holy Energy : {network_errors[-1]}"
            ) from network_errors[-1]

        logger.warning(
            "Échec de l'extraction des identifiants LoyaltyLion sur tous les endpoints testés."
        )

        # If customer tokens could not be found with active cookie, check if retry with .env helps
        env_cookie = self._credentials.shopify_cookie.get_secret_value()
        if use_env_fallback and self._active_cookie != env_cookie:
            logger.info(
                "Le cookie roulant a échoué ; tentative automatique de secours avec le cookie .env..."
            )
            self._set_client_cookies(env_cookie)
            return self._fetch_and_parse_customer(use_env_fallback=False)

        raise AuthenticationError(
            "Impossible d'extraire les identifiants client LoyaltyLion. "
            "La session n'est pas connectée. Veuillez renouveler le cookie _shopify_essential dans votre .env."
        )

    def _parse_loyaltylion_tokens(self, html: str) -> CustomerInfo | None:
        """Extract customer ID, email, auth_date, mac, and shop_token from HTML.

        Supports various formatting variations (unquoted IDs, spacing, multi-line blocks).
        """
        # 1. Search for loyaltylion.init(...) block
        m = re.search(r"loyaltylion\.init\s*\((.*?)\)\s*;", html, re.DOTALL)
        if not m:
            m = re.search(r"loyaltylion\.init\s*\((.*?)\)", html, re.DOTALL)

        search_text = m.group(1) if m else html
        if "customer" not in search_text and "customer" in html:
            search_text = html

        # 2. Extract Shop Token (32 hex characters)
        shop_token_m = re.search(
            r'["\']?(?:token|site_token)["\']?\s*:\s*["\']([a-f0-9]{32})["\']',
            search_text,
        )
        shop_token = shop_token_m.group(1) if shop_token_m else DEFAULT_SHOP_TOKEN

        # 3. Extract Customer Email
        email_m = re.search(
            r'["\']?email["\']?\s*:\s*["\']([^"\'\s,]+@[^"\'\s,]+)["\']',
            search_text,
        )
        if not email_m:
            return None
        email = email_m.group(1).strip()

        # 4. Extract Customer ID (numeric or alphanumeric)
        cid_m = re.search(
            r'customer\s*:\s*\{[^}]*?["\']?id["\']?\s*:\s*["\']?([0-9a-zA-Z_\-]+)["\']?',
            search_text,
            re.DOTALL,
        )
        if not cid_m:
            cid_m = re.search(
                r'["\']?customer_id["\']?\s*:\s*["\']?([0-9a-zA-Z_\-]+)["\']?',
                search_text,
            )
        if not cid_m:
            cid_m = re.search(
                r'id:\s*["\']?([0-9]{5,20})["\']?',
                search_text,
            )
        if not cid_m:
            return None
        cid = cid_m.group(1).strip()

        # 5. Extract Auth Date
        date_m = re.search(
            r'["\']?date["\']?\s*:\s*["\']?([0-9]{8,15}|[0-9]{4}-[0-9]{2}-[0-9]{2}[^"\'\s,]*)["\']?',
            search_text,
        )
        if not date_m:
            return None
        auth_date = date_m.group(1).strip()

        # 6. Extract MAC token (40 hex chars)
        mac_m = re.search(
            r'["\']?(?:token|mac)["\']?\s*:\s*["\']([a-f0-9]{40})["\']',
            search_text,
        )
        if not mac_m:
            return None
        mac = mac_m.group(1).strip()

        logger.debug(
            "Parsing LoyaltyLion réussi : id=%s, email=%s, date=%s, mac=%s, shop_token=%s",
            cid,
            email,
            auth_date,
            mac[:8] + "...",
            shop_token[:8] + "...",
        )

        return CustomerInfo(
            customer_id=cid,
            email=email,
            auth_date=auth_date,
            mac=mac,
            shop_token=shop_token,
        )

    def connect(self) -> ConnectionResult:
        """Execute weekly connection, credit LoyaltyLion points, and report results."""
        display_email = self._credentials.email or "compte Holy Energy"
        logger.info("Démarrage de la connexion hebdomadaire à %s", BASE_URL)
        logger.log(PROD, "Connexion au site Holy Energy en cours (%s)...", display_email)

        try:
            customer = self.verify_session()
        except Exception as exc:
            send_notification(self._credentials, error=exc)
            raise

        points_credited, message, balance = self._track_loyalty_visit(customer)

        logger.info(message)
        if points_credited:
            logger.log(PROD, "25 points crédités — Balance totale : %d points", balance)
        else:
            logger.log(
                PROD, "Points déjà crédités cette semaine — Balance totale : %d points", balance
            )

        result = ConnectionResult(
            success=True,
            timestamp=datetime.now(tz=UTC),
            points_credited=points_credited,
            points_awarded=25 if points_credited else 0,
            total_balance=balance,
            message=message,
            customer_id=customer.customer_id,
            customer_email=customer.email,
        )

        send_notification(self._credentials, result=result)
        return result

    def _track_loyalty_visit(self, customer: CustomerInfo) -> tuple[bool, str, int]:
        """Send tracking request to LoyaltyLion SDK to claim weekly points."""
        visitor_id = str(uuid.uuid4())
        auth_packet = _js_encode(
            {
                "email": customer.email,
                "id": customer.customer_id,
                "date": customer.auth_date,
                "mac": customer.mac,
            }
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
            "site_token": customer.shop_token,
            "visitor_id": visitor_id,
            "pageview_data": pageview_data,
            "cid": customer.customer_id,
            "auth_packet": auth_packet,
        }

        headers = {
            "User-Agent": _CHROME_UA,
            "Referer": ACCOUNT_URL,
            "Origin": BASE_URL,
        }

        logger.debug(
            "Envoi de la requête POST LoyaltyLion SDK init (site_token=%s, cid=%s, visitor_id=%s)...",
            customer.shop_token,
            customer.customer_id,
            visitor_id,
        )
        t0 = time.time()
        try:
            response = self._http.post(
                LOYALTYLION_INIT_URL,
                params=params,
                headers=headers,
                timeout=30,
            )
            elapsed = time.time() - t0
            logger.debug(
                "Réponse LoyaltyLion reçue en %.2fs : HTTP %d", elapsed, response.status_code
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
            logger.error("Erreur lors de l'appel à l'API LoyaltyLion: %s", exc)
            raise LoyaltyLionError(f"Échec de l'appel à l'API LoyaltyLion: {exc}") from exc

        return self._evaluate_loyaltylion_response(data)

    def _evaluate_loyaltylion_response(self, data: Mapping[str, Any]) -> tuple[bool, str, int]:
        """Analyze LoyaltyLion response payload to determine if points were awarded."""
        customer = data.get("customer")
        if not isinstance(customer, dict):
            logger.warning("Objet 'customer' absent du payload renvoyé par LoyaltyLion.")
            return False, "Visite enregistrée mais données client LoyaltyLion absentes.", 0

        balance = int(customer.get("pointsApproved") or 0)
        actions = customer.get("actions", [])
        visit_rule_id = next(
            (
                a.get("ruleId")
                for a in actions
                if isinstance(a, dict) and a.get("ruleKind") == "pageview"
            ),
            None,
        )
        logger.debug(
            "Données client LoyaltyLion : approvedPoints=%d, ruleId visit=%s",
            balance,
            visit_rule_id,
        )

        # 1. Check pendingNotifications (populated when points are awarded in current session)
        pending_notifs = customer.get("pendingNotifications", [])
        if isinstance(pending_notifs, list):
            for notif in pending_notifs:
                serialized = json.dumps(notif).lower()
                if "point" in serialized:
                    return (
                        True,
                        f"25 HOLY Coins crédités ! Solde total : {balance} points.",
                        balance,
                    )

        # 2. Check completedRules: rule completed in the last 30 seconds
        now = datetime.now(tz=UTC)
        completed_rules = customer.get("completedRules", [])
        if isinstance(completed_rules, list):
            for rule in completed_rules:
                if not isinstance(rule, dict) or rule.get("ruleId") != visit_rule_id:
                    continue
                rule_date_raw = rule.get("date")
                if not isinstance(rule_date_raw, str):
                    continue
                try:
                    completed_at = datetime.fromisoformat(rule_date_raw.replace("Z", "+00:00"))
                    seconds_ago = (now - completed_at).total_seconds()
                    if seconds_ago < 30:
                        return (
                            True,
                            f"25 HOLY Coins crédités ! Solde total : {balance} points.",
                            balance,
                        )
                    else:
                        date_str = completed_at.strftime("%Y-%m-%d %H:%M UTC")
                        return (
                            False,
                            f"Points déjà crédités cette semaine (le {date_str}). Solde total : {balance} points.",
                            balance,
                        )
                except (ValueError, TypeError):
                    pass

        # 3. Check ruleContext for limitReached
        rule_context = customer.get("ruleContext", [])
        if isinstance(rule_context, list):
            for ctx in rule_context:
                if (
                    isinstance(ctx, dict)
                    and ctx.get("id") == visit_rule_id
                    and ctx.get("limitReached")
                ):
                    return (
                        False,
                        f"Points déjà crédités cette semaine. Solde total : {balance} points.",
                        balance,
                    )

        return (
            False,
            f"Visite hebdomadaire enregistrée. Solde total : {balance} points.",
            balance,
        )

    def close(self) -> None:
        """Close HTTP client session."""
        self._http.close()

    def __enter__(self) -> "HolyEnergyClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
