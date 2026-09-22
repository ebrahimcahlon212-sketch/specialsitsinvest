"""Launch the trusted UI with Edge WebView2 and the pywebview bridge."""

import ctypes
import logging
import os
import sys
from contextlib import closing
from pathlib import Path

from app.constants import APP_NAME, DEV_URL, PROJECT_DIR, UI_DIR, WEBVIEW2_CLIENT_ID


def data_folder() -> Path:
    location = os.environ.get("LOCALAPPDATA")
    if not location:
        raise RuntimeError("Windows LOCALAPPDATA is unavailable; the data folder cannot be located.")
    path = (Path(location) / APP_NAME).resolve()
    if path.is_relative_to(PROJECT_DIR):
        raise RuntimeError("The research data folder must be outside the repository.")
    return path


def webview2_version() -> str:
    import winreg

    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(
                    hive, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_ID}",
                    0, winreg.KEY_READ | view,
                ) as key:
                    version = winreg.QueryValueEx(key, "pv")[0]
                    if version and version != "0.0.0.0":
                        return version
            except FileNotFoundError:
                continue
    raise RuntimeError(
        "Microsoft Edge WebView2 Runtime is missing. Install the Evergreen Runtime "
        "from https://developer.microsoft.com/microsoft-edge/webview2/ and try again."
    )


def create_app_window(data_dir: Path):
    import webview

    from app.bridge import Bridge
    from app.db import DATA_LOCK, check_search, connect, initialize

    version = webview2_version()
    if (data_dir / "app.db").exists():
        with DATA_LOCK:
            with closing(connect(data_dir)) as connection:
                current = connection.execute("PRAGMA user_version").fetchone()[0]
            initialize(data_dir, target_version=max(current, 2))
            search = check_search(data_dir)
            if search["available"]:
                initialize(data_dir)
                from app.sec import recover_interrupted

                recover_interrupted(data_dir)
                from app.cases import recover_model_runs

                recover_model_runs(data_dir)
    logging.info("Edge WebView2 Runtime %s is registered.", version)
    dev = os.environ.get("APP_DEV") == "1"
    if not dev and not (UI_DIR / "index.html").is_file():
        raise RuntimeError("The interface has not been built. Run npm run build inside ui first.")
    webview.settings["ALLOW_FILE_URLS"] = False
    bridge = Bridge(data_dir)
    window = webview.create_window(
        APP_NAME, DEV_URL if dev else str(UI_DIR / "index.html"),
        js_api=bridge, width=1100, height=800, min_size=(700, 500),
    )
    bridge._window = window
    from app.cases import cancel_summaries_on_close

    window.events.closing += lambda: cancel_summaries_on_close(data_dir)
    return window


def main() -> int:
    try:
        if sys.platform != "win32":
            raise RuntimeError("This desktop app requires Windows and Edge WebView2.")
        folder = data_folder()
        folder.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=folder / "app.log", level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        if sys.version_info[:2] != (3, 13):
            raise RuntimeError("Use Python 3.13 in this repository's .venv. See README.md.")
        import webview

        create_app_window(folder)
        webview.start(gui="edgechromium", http_server=True)
        return 0
    except Exception as error:
        logging.exception("Application launch failed.")
        message = f"InvestResearch could not start.\n\n{error}\n\nUse the README launch steps."
        if sys.stderr is not None:
            print(message, file=sys.stderr)
        if sys.platform == "win32":
            ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
