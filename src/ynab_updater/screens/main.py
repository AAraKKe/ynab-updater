from collections.abc import Iterable

from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Footer, Header

from ynab_updater.config import AppConfig
from ynab_updater.widgets import MainView


class MainScreen(Screen):
    def __init__(self, config: AppConfig):
        self.config = config
        super().__init__()

    def compose(self) -> Iterable[Widget]:
        yield Header()
        yield MainView(config=self.config)
        yield Footer()
