from pathlib import Path

from textual.app import App
from textual.reactive import var

from .config import AppConfig, ConfigError
from .screens import InitScreen, MainScreen
from .ynab_client import Account as YnabAccount
from .ynab_client import YnabHandler


class YnabUpdater(App[None]):
    TITLE = "YNAB Updater"
    SUB_TITLE = "Quickly update account balances"
    CSS_PATH = [str(p) for p in (Path(__file__).parent / "style").glob("*.tcss")]
    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+r", "refresh_balances", "Refresh Balances"),
    ]

    config: var[AppConfig] = var(AppConfig.load)
    accounts_data: var[dict[str, YnabAccount]] = var({})
    is_loading: var[bool] = var(False)
    ynab_handler: var[YnabHandler | None] = var(None)

    def on_mount(self):
        """Called when the app is first mounted."""
        # self.set_loading(True)
        # Run the async setup logic in a worker

        def save_config(config: AppConfig | None):
            if config is None:
                raise ConfigError("Something went wrong when getting the config file.")
            self.config = config
            self.push_screen(MainScreen(self.config))

        self.push_screen(InitScreen(), save_config)

    # @on(InitScreen.Dismissed)
    # def start(self, event: IinitFinished):
    #     self.push_screen(MainScreen(self.config))
