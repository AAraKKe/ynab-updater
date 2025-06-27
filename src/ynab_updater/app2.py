from pathlib import Path

from textual.app import App

from ynab_updater.screens.main import MainScreen


class YnabUpdater(App):
    TITLE = "YNAB Updater"
    SUB_TITLE = "Quickly update account balances"
    CSS_PATH = [str(p) for p in (Path(__file__).parent / "style").glob("*.tcss")]
    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+r", "refresh_balances", "Refresh Balances"),
        ("f10", "reset_config_and_exit", "Reset Config (F10)"),
        ("p", "push_screen('main')"),
    ]
    SCREENS = {"main": MainScreen}
