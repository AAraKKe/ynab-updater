"""Command-line interface entrypoint using Typer."""

import logging
import sys

import typer
from rich.logging import RichHandler

from .screens import UpdaterApp

app = typer.Typer(add_completion=False)


def setup_logging(log_level: str = "INFO") -> None:
    """Configure logging for the application."""
    log_format = "%(message)s"
    log_level_upper = log_level.upper()

    logging.basicConfig(
        level=log_level_upper,
        format=log_format,
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
    )
    # Silence noisy libraries if necessary
    # logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.info(f"Logging level set to {log_level_upper}")


@app.command()
def run(
    log_level: str = typer.Option(
        "INFO",
        "--log-level",
        "-l",
        help="Set the logging level (e.g., DEBUG, INFO, WARNING, ERROR)",
        case_sensitive=False,
    ),
) -> None:
    """Launch the YNAB Updater TUI application."""
    setup_logging(log_level)
    try:
        tui_app = UpdaterApp()
        tui_app.run()
    except Exception as e:
        logging.exception("An unexpected error occurred while running the application.")
        print(f"\n[bold red]Error:[/bold red] {e}", file=sys.stderr)
        # Optionally provide more user-friendly error message or exit code
        sys.exit(1)
    finally:
        logging.info("YNAB Updater finished.")


if __name__ == "__main__":
    app()
