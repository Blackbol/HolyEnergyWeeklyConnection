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
        self._active_cookie = cookie_value
        self._http.cookies.set("_shopify_essential", cookie_value, domain="fr.holy.com")
        self._http.cookies.set("_shopify_essential", cookie_value, domain=".holy.com")
        logger.debug(
            "Cookie _shopify_essential assigné au client HTTP (domaines: fr.holy.com, .holy.com, taille: %d)",
            len(cookie_value),
        )

    def _load_persisted_cookie(self) -> str | None:
        """Read the persisted rolling cookie from disk if it exists."""
        try:
            if self._cookie_file.is_file():
                content = self._cookie_file.read_text(encoding="utf-8").strip()
                if content:
                    logger.debug("Lecture réussie du cookie roulant dans %s", self._cookie_file)
                    return content
                else:
                    logger.debug("Le fichier de cookie roulant %s est vide.", self._cookie_file)
            else:
                logger.debug(
                    "Aucun fichier de cookie roulant trouvé à l'emplacement %s", self._cookie_file
                )
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
        """Fetch Holy Energy page and extract customer tokens with fallback to .env."""
        logger.debug("Envoi de la requête GET vers %s...", ACCOUNT_LOGIN_URL)
        t0 = time.time()
        try:
            response = self._http.get(ACCOUNT_LOGIN_URL)
            elapsed = time.time() - t0
            logger.debug(
                "Réponse reçue en %.2fs : HTTP %d, URL finale : %s",
                elapsed,
                response.status_code,
                response.url,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Erreur HTTP %d lors de la requête vers Holy Energy", exc.response.status_code
            )
            raise NetworkError(
                f"HTTP error fetching Holy Energy ({exc.response.status_code})"
            ) from exc
        except httpx.RequestError as exc:
            logger.error("Erreur réseau de connexion vers Holy Energy: %s", exc)
            raise NetworkError(f"Network error connecting to Holy Energy: {exc}") from exc

        html = response.text
        final_url = str(response.url)

        if response.history:
            logger.debug(
                "Redirections suivies (%d) : %s",
                len(response.history),
                " -> ".join([str(r.url) for r in response.history] + [final_url]),
            )

        # Check for unauthenticated login redirection
        if self._is_login_redirect(final_url, html):
            logger.warning(
                "Redirection vers une page de connexion détectée (URL: %s). Le cookie semble non authentifié.",
                final_url,
            )
            # If we were using the persisted cookie, retry with the .env cookie as fallback
            env_cookie = self._credentials.shopify_cookie.get_secret_value()
            if use_env_fallback and self._active_cookie != env_cookie:
                logger.info(
                    "Le cookie roulant a été rejeté par Shopify ; tentative automatique de secours avec le cookie .env..."
                )
                self._set_client_cookies(env_cookie)
                return self._fetch_and_parse_customer(use_env_fallback=False)

            raise AuthenticationError(
                "Le cookie de session Holy Energy a expiré ou est invalide. "
                "Veuillez vous reconnecter sur fr.holy.com et mettre à jour le cookie _shopify_essential."
            )

        # Parse LoyaltyLion customer block
        customer_info = self._parse_loyaltylion_tokens(html)
        if not customer_info:
            logger.warning("Échec du parsing des identifiants LoyaltyLion dans le HTML.")
            # If customer tokens could not be found, check if retry with .env helps
            env_cookie = self._credentials.shopify_cookie.get_secret_value()
            if use_env_fallback and self._active_cookie != env_cookie:
                logger.info(
                    "Identifiants client absents avec le cookie roulant ; tentative avec le cookie .env..."
                )
                self._set_client_cookies(env_cookie)
                return self._fetch_and_parse_customer(use_env_fallback=False)

            raise AuthenticationError(
                "Impossible d'extraire les identifiants client LoyaltyLion. "
                "La session n'est pas connectée. Veuillez renouveler le cookie _shopify_essential."
            )

        # Session is valid: persist any refreshed cookie sent by Shopify
        new_cookie = self._extract_response_cookie(response)
        if new_cookie:
            self._save_cookie(new_cookie)

        logger.info(
            "✅ Session authentifiée vérifiée : customer_id=%s, email=%s, date_auth=%s",
            customer_info.customer_id,
            customer_info.email,
            customer_info.auth_date,
        )
        return customer_info

    def _parse_loyaltylion_tokens(self, html: str) -> CustomerInfo | None:
        """Extract customer ID, email, auth_date, mac, and shop_token from HTML."""
        # Find loyaltylion.init({...})
        m = re.search(r"loyaltylion\.init\(\{(.+?)\}\)", html, re.DOTALL)
        if not m:
            return None

        init_block = m.group(1)

        # Must have customer block or customer fields
        shop_token_match = re.search(r'token:\s*"([^"]+)"', init_block)
        shop_token = shop_token_match.group(1) if shop_token_match else DEFAULT_SHOP_TOKEN

        cid_match = re.search(r'id:\s*"([^"]+)"', init_block)
        email_match = re.search(r'email:\s*"([^"]+)"', init_block)
        date_match = re.search(r'date:\s*"([^"]+)"', init_block)
        mac_match = re.search(r'token:\s*"([a-f0-9]{40})"', init_block)

        if not (cid_match and email_match and date_match and mac_match):
            return None

        return CustomerInfo(
            customer_id=cid_match.group(1),
            email=email_match.group(1),
            auth_date=date_match.group(1),
            mac=mac_match.group(1),
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
