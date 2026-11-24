from django.apps import AppConfig


class DevToolsConfig(AppConfig):
    """Development only: the mock LinkedIn API and demo-data commands. Never installed in production.

    Installed by config/settings/dev.py and test.py, or anywhere MOCK_LINKEDIN=1 is set.
    """

    name = "dev_tools"
    verbose_name = "Development tools"
