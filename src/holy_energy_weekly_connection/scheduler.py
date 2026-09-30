"""Built-in standalone scheduler for background execution with ultra-low resource usage."""

import logging
import signal
import threading
import time
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from croniter import croniter

from holy_energy_weekly_connection.exceptions import ConfigurationError

PROD = 25
logging.addLevelName(PROD, "PROD")
logger = logging.getLogger(__name__)


class WeeklyScheduler:
    """Schedules and runs a task using a cron expression or day/time with ultra-low CPU usage.

    Uses OS kernel thread suspension (futex wait) to ensure 0.00% CPU when idle.
    Gracefully handles SIGINT and SIGTERM for instantaneous shutdown.
    """

    FRENCH_DAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

    DAYS_MAP = {
        "monday": 0,
        "lundi": 0,
        "tuesday": 1,
        "mardi": 1,
        "wednesday": 2,
        "mercredi": 2,
        "thursday": 3,
        "jeudi": 3,
        "friday": 4,
        "vendredi": 4,
        "saturday": 5,
        "samedi": 5,
        "sunday": 6,
        "dimanche": 6,
    }

    def __init__(
        self,
        task: Callable[[], None],
        cron_expression: str | None = None,
        day_of_week: str = "monday",
        time_str: str = "08:00",
        timezone_str: str = "Europe/Paris",
        run_immediately: bool = False,
    ) -> None:
        self.task = task
        self.target_day = self.DAYS_MAP.get(day_of_week.lower(), 0)
        try:
            parts = time_str.strip().split(":")
            self.target_hour = int(parts[0])
            self.target_minute = int(parts[1]) if len(parts) > 1 else 0
        except (ValueError, IndexError):
            self.target_hour = 8
            self.target_minute = 0

        try:
            self.tz = ZoneInfo(timezone_str)
        except Exception:
            self.tz = ZoneInfo("UTC")

        if cron_expression and cron_expression.strip():
            clean_cron = cron_expression.strip().strip("\"'")
            if not croniter.is_valid(clean_cron):
                raise ConfigurationError(
                    f"Expression cron invalide : {cron_expression!r}.\n"
                    "Format attendu : 'minute heure jour mois jour_semaine' (ex: '0 8 * * 1' pour chaque lundi à 08h00)."
                )
            self.cron_expression = clean_cron
        else:
            # Cron day of week: 0 = Sunday, 1 = Monday, ..., 6 = Saturday, 7 = Sunday.
            # Python weekday: 0 = Monday, ..., 6 = Sunday.
            cron_dow = (self.target_day + 1) % 7
            self.cron_expression = f"{self.target_minute} {self.target_hour} * * {cron_dow}"

        self.run_immediately = run_immediately
        self._running = False
        self._stop_event = threading.Event()

    def get_next_run(self, now: datetime | None = None) -> datetime:
        """Calculate the next upcoming execution datetime using the cron schedule."""
        if now is None:
            now = datetime.now(self.tz)
        if now.tzinfo is None:
            now = now.replace(tzinfo=self.tz)
        iterator = croniter(self.cron_expression, now)
        next_dt: datetime = iterator.get_next(datetime)
        return next_dt

    @classmethod
    def format_next_run_display(cls, dt: datetime) -> str:
        """Format datetime into a localized French string like 'Lundi 05/10/2026 à 08:00'."""
        day = cls.FRENCH_DAYS[dt.weekday()]
        return f"{day} {dt.strftime('%d/%m/%Y à %H:%M')}"

    @staticmethod
    def format_countdown(next_run: datetime, now: datetime) -> str:
        """Format the remaining duration into human-readable text."""
        total_seconds = int((next_run - now).total_seconds())
        if total_seconds <= 0:
            return "imminente"
        days, rem = divmod(total_seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes = rem // 60
        parts = []
        if days > 0:
            parts.append(f"{days} jour{'s' if days > 1 else ''}")
        if hours > 0:
            parts.append(f"{hours}h")
        parts.append(f"{minutes:02d}m")
        return "dans " + " ".join(parts)

    def stop(self) -> None:
        """Signal the scheduler loop to stop immediately."""
        self._running = False
        self._stop_event.set()

    def start(self) -> None:
        """Start the scheduler loop with ultra-low resource usage."""
        self._running = True
        self._stop_event.clear()

        # Signal handlers for clean shutdown
        def _handle_exit(signum: int, frame: object) -> None:
            logger.info("Signal d'arrêt reçu (%s), arrêt propre du démon...", signum)
            self.stop()

        try:
            signal.signal(signal.SIGINT, _handle_exit)
            signal.signal(signal.SIGTERM, _handle_exit)
        except ValueError:
            # When run from a worker thread in tests
            pass

        now = datetime.now(self.tz)
        next_run = self.get_next_run(now)
        countdown = self.format_countdown(next_run, now)
        next_run_display = self.format_next_run_display(next_run)

        # Logged at PROD level so it is ALWAYS visible, even with LOG_LEVEL=PROD and HOLY_RUN_ON_STARTUP=false
        logger.log(
            PROD,
            "🚀 Démon Holy Energy démarré [Cron: %s]. Prochaine activation : %s (%s)",
            self.cron_expression,
            next_run_display,
            countdown,
        )

        if self.run_immediately:
            logger.info(
                "⚡ Exécution immédiate au démarrage demandée (HOLY_RUN_ON_STARTUP=true)..."
            )
            self._execute_task()
            now = datetime.now(self.tz)
            next_run = self.get_next_run(now)
            countdown = self.format_countdown(next_run, now)
            next_run_display = self.format_next_run_display(next_run)
            logger.log(
                PROD,
                "📅 Prochaine activation : %s (%s)",
                next_run_display,
                countdown,
            )

        while self._running and not self._stop_event.is_set():
            try:
                now = datetime.now(self.tz)
                seconds_until_run = (next_run - now).total_seconds()

                if seconds_until_run <= 0.05:
                    logger.log(
                        PROD,
                        "⏰ Heure de connexion atteinte ! Démarrage de la tâche planifiée...",
                    )
                    self._execute_task()
                    now_after = datetime.now(self.tz)
                    next_run = self.get_next_run(now_after)
                    countdown = self.format_countdown(next_run, now_after)
                    next_run_display = self.format_next_run_display(next_run)
                    logger.log(
                        PROD,
                        "📅 Prochaine activation : %s (%s)",
                        next_run_display,
                        countdown,
                    )
                    continue

                # Wait chunk: maximum 6 hours (21600s) to emit a periodic heartbeat
                sleep_chunk = min(seconds_until_run, 21600.0)
                signaled = self._stop_event.wait(timeout=sleep_chunk)
                if signaled or self._stop_event.is_set():
                    break

                # If woken up by timeout (heartbeat) and not yet time to run
                now_hb = datetime.now(self.tz)
                if (next_run - now_hb).total_seconds() > 1.0:
                    logger.info(
                        "💓 Démon actif en attente. Prochaine exécution : %s (%s)",
                        self.format_next_run_display(next_run),
                        self.format_countdown(next_run, now_hb),
                    )
            except Exception as exc:
                logger.error("Erreur inattendue dans la boucle du démon: %s", exc)
                self._stop_event.wait(timeout=60.0)

        logger.log(PROD, "Démon Holy Energy arrêté.")

    def _execute_task(self) -> None:
        t0 = time.time()
        logger.info("▶ Début d'exécution de la tâche...")
        try:
            self.task()
            elapsed = time.time() - t0
            logger.info("✔ Tâche exécutée avec succès en %.2fs.", elapsed)
        except Exception as exc:
            elapsed = time.time() - t0
            logger.error(
                "✖ Erreur lors de l'exécution de la tâche (durée: %.2fs): %s", elapsed, exc
            )
