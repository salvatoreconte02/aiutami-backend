from django.apps import AppConfig


class TasksConfig(AppConfig):
    """
    App contenitore per i plugin di task supportati (murder_mystery,
    nasa_moon_survival, generic).

    Ogni task è un sottopacchetto di apps.tasks che registra la propria
    classe TaskDefinition nel registry al momento dell'import.

    Il core (sessions, moderation, reports, turns, asr, tts, webrtc) non
    importa mai direttamente da apps.tasks.<specifico>: dialoga solo con
    apps.tasks.registry.get_task(key).
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tasks"
    label = "tasks"

    def ready(self) -> None:
        # Import dei sottopacchetti dei task: ogni __init__.py registra la
        # propria TaskDefinition nel registry. L'import qui in ready() forza
        # la registrazione al boot Django.
        #
        # Nota: importiamo SOLO i plugin di task. Il core del backend continua
        # a non sapere nulla dei task specifici e li raggiunge solo via
        # apps.tasks.registry.get_task(key).
        from . import murder_mystery  # noqa: F401
