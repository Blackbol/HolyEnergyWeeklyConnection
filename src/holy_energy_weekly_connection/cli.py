"""Command-line interface for Holy Energy Weekly Connection."""

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pydantic import SecretStr

from holy_energy_weekly_connection.client import HolyEnergyClient
from holy_energy_weekly_connection.exceptions import (
    AuthenticationError,
    ConfigurationError,
    HolyEnergyError,
)
from holy_energy_weekly_connection.models import Credentials
from holy_energy_weekly_connection.scheduler import WeeklyScheduler

PROD = 25
logger = logging.getLogger("holy_energy_weekly_connection")


def setup_logging(level_name: str | None = None) -> None:
    """Configure console logging and persistent rotating file logging."""
    raw_level = level_name or os.getenv("LOG_LEVEL") or "INFO"
    level = raw_level.upper()
    console_level = PROD if level == "PROD" else getattr(logging, level, logging.INFO)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    # 1. Console stream handler
    console_fmt = (
        "%(message)s" if level == "PROD" else "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(logging.Formatter(console_fmt))
    root.addHandler(console_handler)

    # 2. Persistent rotating file handler (5 MB, 3 backups)
    log_file = Path(os.getenv("HOLY_LOG_FILE", "data/holy_energy.log"))
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        from logging.handlers import RotatingFileHandler

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_fmt = "%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d] %(message)s"
        file_handler.setFormatter(logging.Formatter(file_fmt))
        root.addHandler(file_handler)
    except OSError as exc:
        logging.warning("Impossible d'activer le fichier de log %s : %s", log_file, exc)


def validate_env_cookie(raw_cookie: str | None) -> str:
    """Validate that the session cookie is present and not a placeholder."""
    if not raw_cookie or not raw_cookie.strip():
        raise ConfigurationError(
            "Aucun cookie de session trouvé dans le fichier .env (variable HOLY_SHOPIFY_COOKIE absente ou vide).\n"
            "Le projet ne peut pas se lancer sans cookie de session.\n\n"
            "👉 Pour le configurer :\n"
            "  1. Connectez-vous sur https://fr.holy.com dans votre navigateur.\n"
            "  2. Ouvrez les outils de développement (F12 -> Application -> Cookies -> https://fr.holy.com).\n"
            "  3. Copiez la valeur du cookie '_shopify_essential'.\n"
            "  4. Renseignez la variable dans votre fichier .env :\n"
            "     HOLY_SHOPIFY_COOKIE=:AZ..."
        )

    clean = raw_cookie.strip().strip('"\'')

    # Detect placeholders from .env.example
    lower = clean.lower()
    placeholders = [
        "collez_votre_cookie",
        "collez_ici",
        "votre_cookie",
        "your_cookie",
        "remplacer",
        "<cookie>",
    ]
    for ph in placeholders:
        if ph in lower:
            raise ConfigurationError(
                f"Le cookie dans le fichier .env contient un texte d'exemple ({ph!r}).\n"
                "Vous devez remplacer cette valeur par votre véritable cookie '_shopify_essential'.\n\n"
                "👉 Rendez-vous sur https://fr.holy.com -> F12 -> Application -> Cookies -> _shopify_essential"
            )

    if "..." in clean:
        raise ConfigurationError(
            "Le cookie dans le fichier .env semble incomplet (contient '...').\n"
            "Veuillez vous assurer de copier l'intégralité de la valeur du cookie _shopify_essential."
        )

    if len(clean) < 15:
        raise ConfigurationError(
            f"Le cookie dans le fichier .env est anormalement court ({len(clean)} caractères).\n"
            "Un cookie _shopify_essential valide mesure généralement entre 800 et 1500 caractères.\n"
            "Vérifiez que vous avez bien copié toute la chaîne."
        )

    return clean


def load_credentials_from_env() -> Credentials:
    """Load configuration from environment variables and check requirements."""
    load_dotenv()

    raw_cookie = os.getenv("HOLY_SHOPIFY_COOKIE")
    cookie_file_path = Path(os.getenv("HOLY_COOKIE_FILE", "data/cookie.txt"))

    # Fallback to rolling cookie file if env cookie is not provided or empty
    candidate_cookie = raw_cookie
    if (not candidate_cookie or not candidate_cookie.strip()) and cookie_file_path.is_file():
        try:
            persisted = cookie_file_path.read_text(encoding="utf-8").strip()
            if persisted and len(persisted) >= 15 and "..." not in persisted:
                candidate_cookie = persisted
        except OSError:
            pass

    validated_cookie = validate_env_cookie(candidate_cookie)

    timeout_raw = os.getenv("HOLY_TIMEOUT", "30").strip()
    try:
        timeout = int(timeout_raw)
    except ValueError as exc:
        raise ConfigurationError(
            f"HOLY_TIMEOUT doit être un entier, reçu: {timeout_raw!r}"
        ) from exc

    discord_raw = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    telegram_bot_raw = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    telegram_chat = os.getenv("TELEGRAM_CHAT_ID", "").strip() or None
    ntfy_topic = os.getenv("NTFY_TOPIC", "").strip() or None
    ntfy_server = os.getenv("NTFY_SERVER", "https://ntfy.sh").strip()

    return Credentials(
        shopify_cookie=SecretStr(validated_cookie),
        email=os.getenv("HOLY_EMAIL", "").strip(),
        timeout=timeout,
        cookie_file=cookie_file_path,
        discord_webhook=SecretStr(discord_raw) if discord_raw else None,
        telegram_bot_token=SecretStr(telegram_bot_raw) if telegram_bot_raw else None,
        telegram_chat_id=telegram_chat,
        ntfy_topic=ntfy_topic,
        ntfy_server=ntfy_server,
    )


def cmd_run(args: argparse.Namespace) -> int:
    """Execute weekly claim once."""
    try:
        credentials = load_credentials_from_env()
    except ConfigurationError as exc:
        logger.error("Erreur de configuration : %s", exc)
        return 1

    try:
        with HolyEnergyClient(credentials) as client:
            client.connect()
        return 0
    except AuthenticationError as exc:
        logger.error("Authentification échouée : %s", exc)
        return 2
    except HolyEnergyError as exc:
        logger.error("Erreur lors de la connexion Holy Energy : %s", exc)
        return 3
    except Exception as exc:
        logger.exception("Erreur inattendue : %s", exc)
        return 4


def cmd_verify(args: argparse.Namespace) -> int:
    """Verify session cookie validity without claiming points."""
    try:
        credentials = load_credentials_from_env()
    except ConfigurationError as exc:
        logger.error("Erreur de configuration : %s", exc)
        return 1

    logger.info("Vérification de la session Holy Energy...")
    try:
        with HolyEnergyClient(credentials) as client:
            customer = client.verify_session()
            logger.info("✅ Session valide !")
            logger.info("👤 Compte client ID : %s", customer.customer_id)
            logger.info("📧 Email : %s", customer.email)
            logger.info("🔑 Date auth LoyaltyLion : %s", customer.auth_date)
        return 0
    except AuthenticationError as exc:
        logger.error("❌ Cookie de session invalide ou expiré : %s", exc)
        return 2
    except Exception as exc:
        logger.error("❌ Échec de la vérification : %s", exc)
        return 3


def cmd_daemon(args: argparse.Namespace) -> int:
    """Run in background daemon scheduler mode."""
    try:
        load_credentials_from_env()
    except ConfigurationError as exc:
        logger.error("Configuration invalide au démarrage : %s", exc)
        return 1

    day = os.getenv("HOLY_SCHEDULE_DAY", "monday")
    time_str = os.getenv("HOLY_SCHEDULE_TIME", "08:00")
    timezone = os.getenv("TZ", os.getenv("HOLY_TIMEZONE", "Europe/Paris"))
    run_now = os.getenv("HOLY_RUN_ON_STARTUP", "false").lower() in ("true", "1", "yes")

    def _job() -> None:
        try:
            creds = load_credentials_from_env()
            with HolyEnergyClient(creds) as client:
                client.connect()
        except Exception as exc:
            logger.error("Échec lors de l'exécution planifiée : %s", exc)

    scheduler = WeeklyScheduler(
        task=_job,
        day_of_week=day,
        time_str=time_str,
        timezone_str=timezone,
        run_immediately=run_now,
    )
    scheduler.start()
    return 0


def cmd_set_cookie(args: argparse.Namespace) -> int:
    """Save and test a new session cookie."""
    try:
        cookie = validate_env_cookie(args.cookie)
    except ConfigurationError as exc:
        logger.error("Cookie invalide : %s", exc)
        return 1

    cookie_file = Path(os.getenv("HOLY_COOKIE_FILE", "data/cookie.txt"))
    cookie_file.parent.mkdir(parents=True, exist_ok=True)
    cookie_file.write_text(cookie, encoding="utf-8")
    logger.info("Cookie écrit dans %s", cookie_file)

    # Test the newly saved cookie
    try:
        creds = Credentials(shopify_cookie=SecretStr(cookie), cookie_file=cookie_file)
        with HolyEnergyClient(creds) as client:
            customer = client.verify_session()
            logger.info("🎉 Succès ! Le cookie est valide.")
            logger.info(
                "👤 Connecté en tant que : %s (ID %s)", customer.email, customer.customer_id
            )
        return 0
    except Exception as exc:
        logger.error("Le cookie enregistré semble invalide : %s", exc)
        return 2


def cmd_login(args: argparse.Namespace) -> int:
    """Launch interactive browser to log in and automatically extract session cookie."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error(
            "Playwright n'est pas installé. Pour activer la connexion automatique via navigateur :\n"
            "  pip install playwright && playwright install chromium\n"
            "Ou utilisez 'holy-connect set-cookie <VOTRE_COOKIE>'."
        )
        return 1

    logger.info("Ouverture du navigateur pour la connexion à fr.holy.com...")
    logger.info(
        "Connectez-vous avec votre email et le code reçu. Le cookie sera capturé automatiquement."
    )

    cookie_captured = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://fr.holy.com/pages/account-login")

        logger.info("En attente de connexion...")
        # Poll for _shopify_essential cookie while user completes login
        for _ in range(120):  # 2 minutes timeout
            cookies = context.cookies(["https://fr.holy.com", "https://shopify.com"])
            for c in cookies:
                if c["name"] == "_shopify_essential" and len(c.get("value", "")) > 100:
                    cookie_captured = c["value"]
                    break
            if cookie_captured:
                break
            page.wait_for_timeout(1000)

        browser.close()

    if cookie_captured:
        cookie_file = Path(os.getenv("HOLY_COOKIE_FILE", "data/cookie.txt"))
        cookie_file.parent.mkdir(parents=True, exist_ok=True)
        cookie_file.write_text(cookie_captured, encoding="utf-8")
        logger.info("🎉 Cookie capturé et enregistré dans %s !", cookie_file)
        return 0
    else:
        logger.error("Aucun cookie de session capturé (délai dépassé ou fenêtre fermée).")
        return 1


def main() -> None:
    """CLI entrypoint."""
    setup_logging()

    parser = argparse.ArgumentParser(
        prog="holy-connect",
        description="Connexion hebdomadaire automatique à Holy Energy pour gagner 25 HOLY Coins.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Commandes disponibles")

    # Command: run (default)
    parser_run = subparsers.add_parser(
        "run", help="Exécute la connexion hebdomadaire et crédite les points (défaut)"
    )
    parser_run.set_defaults(func=cmd_run)

    # Command: verify
    parser_verify = subparsers.add_parser(
        "verify", help="Vérifie la validité du cookie de session actuel"
    )
    parser_verify.set_defaults(func=cmd_verify)

    # Command: daemon
    parser_daemon = subparsers.add_parser(
        "daemon", help="Lance le planificateur hebdomadaire en arrière-plan"
    )
    parser_daemon.set_defaults(func=cmd_daemon)

    # Command: set-cookie
    parser_set = subparsers.add_parser(
        "set-cookie", help="Définit et teste un nouveau cookie de session"
    )
    parser_set.add_argument("cookie", help="Valeur complète du cookie _shopify_essential")
    parser_set.set_defaults(func=cmd_set_cookie)

    # Command: login
    parser_login = subparsers.add_parser(
        "login", help="Connexion interactive via navigateur pour extraire le cookie"
    )
    parser_login.set_defaults(func=cmd_login)

    # If no subcommand is passed, default to run (unless HOLY_MODE=daemon is set)
    args = parser.parse_args()
    if not args.command:
        if os.getenv("HOLY_MODE", "").lower() == "daemon":
            sys.exit(cmd_daemon(args))
        else:
            sys.exit(cmd_run(args))
    else:
        sys.exit(args.func(args))


if __name__ == "__main__":
    main()
