from textual.widgets import Static


class NetWorth(Static):
    def compose(self):
        yield Static("Net Worth", id="net-worth-title")
        yield Static("**Coming soon!**")
