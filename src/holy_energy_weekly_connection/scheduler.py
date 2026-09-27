"""Built-in standalone scheduler for weekly background execution."""

import logging
import signal
import time
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


class WeeklyScheduler:
    """Schedules and runs a task every week at a specified day and time.

    Supports configurable day of week, hour, minute, and timezone.
    Gracefully handles SIGINT and SIGTERM.
    """

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

        self.run_immediately = run_immediately
        self._running = False
        self._last_run_week: int | None = None
        self._last_heartbeat_time = 0.0

    def get_next_run(self, now: datetime | None = None) -> datetime:
        """Calculate the next upcoming execution datetime."""
        if now is None:
            now = datetime.now(self.tz)
        target = now.replace(
            hour=self.target_hour,
            minute=self.target_minute,
            second=0,
            microsecond=0,
        )
        days_ahead = (self.target_day - now.weekday()) % 7
        if days_ahead == 0 and (
            now.hour > self.target_hour
            or (now.hour == self.target_hour and now.minute >= self.target_minute)
        ):
            days_ahead = 7
        from datetime import timedelta

        return target + timedelta(days=days_ahead)

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

    def start(self) -> None:
        """Start the scheduler loop."""
        self._running = True

        # Signal handlers for clean shutdown
        def _handle_exit(signum: int, frame: object) -> None:
            logger.info("Signal d'arrêt reçu (%s), arrêt propre du démon...", signum)
            self._running = False

        signal.signal(signal.SIGINT, _handle_exit)
        signal.signal(signal.SIGTERM, _handle_exit)

        day_name = list(self.DAYS_MAP.keys())[self.target_day * 2].capitalize()
        now = datetime.now(self.tz)
        next_run = self.get_next_run(now)
        countdown = self.format_countdown(next_run, now)

        logger.info(
            "🚀 Démon Holy Energy initialisé avec succès.\n"
            "   ⏰ Planification récurrente : chaque %s à %02d:%02d (%s)\n"
            "   📅 Prochaine exécution : %s (%s)",
            day_name,
            self.target_hour,
            self.target_minute,
            self.tz.key,
            next_run.strftime("%A %d/%m/%Y à %H:%M"),
            countdown,
        )

        if self.run_immediately:
            logger.info(
                "⚡ Exécution immédiate au démarrage demandée (HOLY_RUN_ON_STARTUP=true)..."
            )
            self._execute_task()
            now = datetime.now(self.tz)
            next_run = self.get_next_run(now)
            logger.info(
                "📅 Prochaine exécution planifiée : %s (%s)",
                next_run.strftime("%A %d/%m/%Y à %H:%M"),
                self.format_countdown(next_run, now),
            )

        self._last_heartbeat_time = time.time()

        while self._running:
            try:
                now = datetime.now(self.tz)
                current_week = now.isocalendar().week

                is_target_day = now.weekday() == self.target_day
                is_target_time = now.hour == self.target_hour and now.minute == self.target_minute

                if is_target_day and is_target_time and self._last_run_week != current_week:
                    logger.info(
                        "⏰ Heure de connexion atteinte ! Démarrage de la tâche planifiée..."
                    )
                    self._execute_task()
                    self._last_run_week = current_week
                    now_after = datetime.now(self.tz)
                    next_run_after = self.get_next_run(now_after)
                    logger.info(
                        "📅 Prochaine exécution planifiée : %s (%s)",
                        next_run_after.strftime("%A %d/%m/%Y à %H:%M"),
                        self.format_countdown(next_run_after, now_after),
                    )
                    # Sleep past this minute to avoid duplicate run in the same minute
                    time.sleep(65)
                    continue

                # Periodic heartbeat log every 6 hours
                current_timestamp = time.time()
                if current_timestamp - self._last_heartbeat_time >= 21600:  # 6 hours
                    next_run_hb = self.get_next_run(now)
                    logger.info(
                        "💓 Démon actif en attente. Prochaine exécution : %s (%s)",
                        next_run_hb.strftime("%A %d/%m/%Y à %H:%M"),
                        self.format_countdown(next_run_hb, now),
                    )
                    self._last_heartbeat_time = current_timestamp

                # Sleep 20 seconds between checks
                time.sleep(20)
            except Exception as exc:
                logger.error("Erreur inattendue dans la boucle du démon: %s", exc)
                time.sleep(60)

        logger.info("Démon Holy Energy arrêté.")

    def _execute_task(self) -> None:
        t0 = time.time()
        logger.info("▶ Début d'exécution de la tâche hebdomadaire...")
        try:
            self.task()
            elapsed = time.time() - t0
            logger.info("✔ Tâche hebdomadaire exécutée avec succès en %.2fs.", elapsed)
        except Exception as exc:
            elapsed = time.time() - t0
            logger.error(
                "✖ Erreur lors de l'exécution de la tâche (durée: %.2fs): %s", elapsed, exc
            )
