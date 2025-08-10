from collections.abc import Iterable

from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Footer, Header

from ynab_updater.config import AppConfig
from ynab_updater.widgets import MainView

from .config_screen import ConfigScreen


class MainScreen(Screen):
    def __init__(self, config: AppConfig, config_screen: ConfigScreen):
        self.config = config
        self.config_screen = config_screen
        super().__init__()

    def compose(self) -> Iterable[Widget]:
        yield Header()
        yield MainView(config=self.config, config_screen=self.config_screen)
        yield Footer()
