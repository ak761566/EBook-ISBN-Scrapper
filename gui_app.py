"""
Lightweight Local Desktop UI for Portico Batch Scraper.

Built using NiceGUI and native asyncio integration. Runs locally on the user's
machine without requiring an external web server or complex hosting.
"""
import os
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Any

from multipart import file_path
from selectolax.parser import HTMLParser

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

import asyncio
import logging
from nicegui import ui, events, app
from search_book_page import Searchbook
from excel_pipeline_handler import stream_result_to_excel, extract_input_memory_safe
from login_manager import configure_persistent_profile, UserCredentials, LoginPage

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger(__name__)

@dataclass
class UIState:
    """Mutable runtime container for UI selections and session state."""
    file_bytes: Optional[bytes] = None
    file_name: str = "uploaded_file.xlsx"
    processed_bytes: Optional[bytes] = None
    selected_file: Optional[Path] = None
    output_file: Optional[Path] = None
    authenticated: bool = False
    driver:  Optional[webdriver.Chrome] = None
    scraper: Optional[Searchbook] = None


def build_chrome_options()->Options:
    """Constructs ChromeOptions optimized for headless stability and memory safety."""
    options = Options()

    # Headless Stability Flags
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")  # Prevents /dev/shm memory crashes
    options.add_argument("--disable-gpu")
    options.add_argument("--enable-dom-storage")
    options.add_argument("--remote-allow-origins=*")
    options.add_argument("--disable-blink-features=AutomationControlled")

    # Mask Automation Detection
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    return options


def create_authenticated_browser_session()-> webdriver.Chrome:
    """
        Factory function instantiating a resilient Chrome WebDriver session.
        Guarantees clean profile locks and robust CDP socket attachment.
    """
    options = build_chrome_options()
    service = Service(ChromeDriverManager().install())
    logger.info("Instantiating Chrome session... ")
    driver = webdriver.Chrome(service=service, options=options)

    return driver

def destroy_chrome_driver(driver: Optional[webdriver.Chrome]) -> None:
    """Safely terminates an active Chrome WebDriver process tree."""
    if not driver:
        return

    logger.info("Terminating active Chrome WebDriver session...")
    try:
        driver.quit()
        logger.info("WebDriver process tree terminated cleanly.")
    except Exception as err:
        logger.error(f"Error encountered during driver.quit(): {err}")

class ScraperAppUi:
    def __init__(self):
        self.state = UIState()
        self.register_shutdown_hook()
        # UI Component references
        self.username_input: Optional[ui.input] = None
        self.password_input: Optional[ui.input] = None
        self.login_btn: Optional[ui.button] = None
        self.status_log: Optional[ui.log] = None
        self.progress_bar : Optional[ui.linear_progress] = None
        self.run_btn : Optional[ui.button] = None
        self.download_btn : Optional[ui.button] = None
        self.open_folder_btn : Optional[ui.button] = None

    def register_shutdown_hook(self):
        """
            Registers a lifecycle shutdown callback with NiceGUI
            to terminate background Selenium processes when the app exits.
        """
        def cleanup_resource():
            if self.state.driver:
                logger.info("Application shutdown detected. Closing active WebDrivers...")
                try:
                    self.state.driver.quit()
                except Exception as err:
                    logger.error(f"Error during shutdown driver cleanup {err}")

        # Register with NiceGUI's global app event listener
        app.on_shutdown(cleanup_resource)

    def _sync_browser_auth(self, cred: UserCredentials, login_url: str) -> Searchbook:
            """
                Synchronous worker executed in a background thread via asyncio.to_thread.
                Instantiates Chrome, executes login, and returns a ready SearchBook worker.
            """
            logger.info("Initialize background chrome instance for authentication...")
            """
                Constructs ChromeOptions optimized for headless stability and memory safety.
            """
            # profile_dir = Path(profile_path).resolve()
            # profile_dir.mkdir(parents=True, exist_ok=True)

            driver = create_authenticated_browser_session()
            logger.info("Chrome driver initialized cleanly.")
            try:
                auth_page = LoginPage(driver)
                auth_page.execute_login(credentials=cred, login_url=login_url)
                #search_book = SearchBook(driver, max_concurrent_request=5)
                self.state.driver = driver
                return Searchbook(driver, max_concurrent_request=5)
            except Exception as err:
                # If authentication fails midway, clean up the process tree immediately
                logger.error(f"Failed during browser authentication phase: {err}")
                destroy_chrome_driver(driver)
                raise err


    async def handle_login(self):
        #logger.info(f"{self.username_input}--{self.password_input}")
        username = self.username_input.value.strip() if self.username_input else ""
        password = self.password_input.value.strip() if self.password_input else ""

        #print(f"{username}---{password}")
        if not username or not password:
            ui.notify("Please enter username and password", type="warning")
            return

        cred = UserCredentials(username=username, password=password)
        URL = "https://audit.portico.org/Portico/login.html"

        self.login_btn.props("loading")
        self.status_log.push("Launching headless chrome authentication...")

        try:
            # Non-blocking offload of synchronous browser startup
            self.state.scraper = await asyncio.to_thread(self._sync_browser_auth, cred=cred, login_url=URL)
            self.state.authenticated = True

            self.status_log.push("Authentication successful! Session cookies acquired...")
            ui.notify("Logged in successfully", type="positive")

            if self.run_btn:
                self.run_btn.enable()
        except Exception as ex:
            logger.error(f"Authentication failure: {ex}", exc_info=True)
            self.status_log.push(f"Login Failed: {ex}")
            ui.notify(f"Authentication error: {ex}", type="negative")
        finally:
            self.login_btn.props(remove="loading")



    async def handle_upload(self, event: events.UploadEventArguments)->None:
            filename = getattr(event, "name", None) or getattr(event.file, "name", "uploaded_file.xlsx")
            safe_filename = Path(filename).name

            # Establish default target output path in the user's reports directory
            workspace_dir = Path.home() / "Portico_Audit_Report" / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)

            target_input_path = (workspace_dir / f"input_{filename}").resolve()
            logger.info(f"Resolving uploaded file payload to {target_input_path}")

            try:
                # 2. Extract file object
                file_obj = getattr(event, "file", None) or getattr(event, "content", None)
                # 3. CRITICAL FIX: Await the asynchronous read() coroutine
                if hasattr(file_obj, "read") and callable(file_obj.read):
                    read_res = event.file.read()
                    file_bytes = await read_res if asyncio.iscoroutine(read_res) else read_res
                    #print(file_bytes)
                    #logger.info(f"File Bytes:\n {file_bytes}")
                else:
                    raise ValueError(f"Uploaded file object does not expose a readable interface")

                target_input_path.write_bytes(file_bytes)
                self.state.selected_file = target_input_path

                # Establish default target output path in the user's reports directory
                report_dir = Path.home() / "Portico_Audit_Reports"
                self.state.output_file = report_dir / f"Audited_{filename}"


                if self.status_log:
                    self.status_log.push(f"Successfully loaded spreadsheet into memory: {filename}")
                    self.status_log.push(f"Output Target : {self.state.output_file} ")
                ui.notify(f"Loaded : {filename}", type="info")

                #print(target_path)
            except Exception as ex:
                logger.error(f"Failed to process uploaded file : {self.state.file_name} : {ex}", exc_info=True)
                ui.notify(f"File upload fail {safe_filename} : {ex}", type="negative")

    async def execute_scraping_pipeline(self)->None:
        """
            Orchestrates memory-safe streaming extraction, fetching, and report creation.
            """
        if not self.state.authenticated or not self.state.scraper:
            ui.notify("Please authenticate before executing batch tasks", type="warning")
            return

        if not self.state.selected_file or not self.state.output_file:
            ui.notify("Please upload and excel spreadsheet first..", type="warning")
            return

        if self.run_btn:
            self.run_btn.props("loading")
        if self.status_log:
            self.status_log.push("Reading ISBN inputs..")

        # 1. Memory-Safe Input Extraction
        indexed_inputs = await asyncio.to_thread(
            extract_input_memory_safe,
            file_path=self.state.selected_file,
            input_col=2,
            start_row=2
        )

        total_item = len(indexed_inputs)
        if total_item == 0:
            if self.status_log:
                self.status_log.push("No valid ISBN Found. Operation halted...")
            if self.run_btn:
                self.run_btn.props(remove="loading")
            return
        if self.status_log:
            self.status_log.push(f"Found total ISBN {total_item}. Starting streaming pipeline...")

        # Progress Update Callback Closure
        async def update_progress(ratio: float, message: str)->None:
            if self.progress_bar:
                self.progress_bar.value=ratio
            if self.status_log and int(ratio * 100) % 10 == 0:
                self.status_log.push(message)

        # 2. Instantiate Async Generator Stream
        result_stream = self.state.scraper.stream_request(indexed_inputs)

        # 3. Stream Async Generator Directly to Disk
        written_path = await stream_result_to_excel(
            result_generator=result_stream,
            output_path=self.state.output_file,
            total_count=total_item,
            progress_callback=update_progress
        )

        if self.status_log:
            self.status_log.push(f"Pipeline Complete! Report saved to: {written_path.name}")

        ui.notify("Audit completed successfully!", type="positive")

        if self.download_btn:
            self.download_btn.enable()
        if self.open_folder_btn:
            self.open_folder_btn.enable()
        if self.run_btn:
            self.run_btn.props(remove="loading")



    def trigger_download(self):
        # if not self.state.processed_bytes:
        #     ui.notify("No processed file available for download", type="warning")
        #     return

        target_path = self.state.output_file

        if not target_path or not target_path.exists():
            logger.error(f"Download failed. Target file path doesn't exist {target_path}")
            ui.notify(f"Error: Output report file not found on Disk: {target_path}", type="negative")
            return

        logger.info(f"Dispatching download for physical file {target_path}")
        # Passing a Path object directly to ui.download() bypasses WebView2 Blob restrictions!
        ui.download(target_path)

        if self.status_log:
            self.status_log.push(f"Downloaded: {target_path.name}")
            ui.notify(f"Downloading {target_path.name}...", type="positive")



    def open_output_folder(self)->None:
        target_path = self.state.output_file

        if not target_path or not target_path.parent.exists():
            ui.notify(f"Output directory does not exist", type="negative")
            return

        folder_dir = target_path.parent
        logger.info(f"Opening system file explorer at {folder_dir}")

        try:
            if platform.system() == "Windows":
                os.startfile(folder_dir)
            elif platform.system() == "Darwin":
                subprocess.run(["open", str(folder_dir)], check=True)
            else:  # Linux
                subprocess.run(["xdg-open", str(folder_dir)], check=True)
        except Exception as err:
            logger.error(f"Failed to open output folder: {err}")
            ui.notify(f"Could not open folder: {err}", type="negative")

def build_app():
    app_ui = ScraperAppUi()
    # Centered Header Container
    with ui.column().classes("w-full max-w-6xl mx-auto p-4 gap-4"):
        ui.label("Portico Audit App: E-Book").classes("text-3xl font-bold text-slate-800 mb-2")

        # Two-Column Equal Split Row (items-start ensures top alignment across both columns)
        with ui.row().classes("w-full gap-6 items-start"):
            # -----------------------------------------------------------------
            # LEFT COLUMN: User Input Steps & Action Controls (50% Width)
            # -----------------------------------------------------------------

            with ui.column().classes("w-full col md:w-1/2 gap-4"):

                # Step 1: Authentication Card
                with ui.card().classes("w-full p-6 shadow-sm border border-slate-200"):
                   ui.label("Step 1: Website Authentication").classes("text-lg font-semibold mb-2")
                   app_ui.username_input = ui.input("Username").classes("w-full")
                   app_ui.password_input = ui.input("Password", password=True, password_toggle_button=True).classes("w-full")
                   app_ui.login_btn = ui.button("Authentication Session", on_click=app_ui.handle_login).classes("w-full mt-2")

                # Step 2: Spreadsheet Execution Card
                with ui.card().classes("w-full p-6 shadow-sm border border-slate-200"):
                    ui.label("Step 2: Load spreadsheet & Execute")
                    ui.upload(on_upload=app_ui.handle_upload, auto_upload=True).props("accept=.xlsx").classes("w-full")

                    app_ui.run_btn = ui.button("Start Processing", on_click=app_ui.execute_scraping_pipeline)
                    app_ui.run_btn.disable()



            # -----------------------------------------------------------------
            # RIGHT COLUMN: System Execution Log & Progress (50% Width)
            # -----------------------------------------------------------------
            with ui.column().classes("w-full col md:w-1/2 gap-4"):
                with ui.card().classes("w-full p-6 shadow-sm border border-slate-200 h-full"):
                    ui.label("System execution status").classes("text-lg font-semibold mb-2")
                    app_ui.progress_bar=ui.linear_progress(value=0.0).classes("mb-2")
                    app_ui.status_log = ui.log(max_lines=16).classes("w-full h-80 bg-slate-900 text-green-400 p-3 rounded text-xs font-mono overflow-y-auto")

                    # Action Button Pair: Placed inside a 50/50 sub-row
                    with ui.row().classes("w-full gap-3"):
                        app_ui.download_btn = ui.button("Download Audited Excel",
                                                        on_click=app_ui.trigger_download, icon="download").classes(
                            "w-full col bg-positive text-white font-medium").props("color=positive")
                        app_ui.download_btn.disable()

                        app_ui.open_folder_btn = ui.button("Open Folder", on_click=app_ui.open_output_folder,
                                                           icon="folder_open").classes(
                            "w-full col bg-positive text-white font-medium")
                        app_ui.open_folder_btn.disable()



if __name__ in {"__main__", "__mp_main__"}:
    # Define the root page context
    ui.page("/")(build_app)
    # Launch NiceGUI native window
    ui.run(title="Portico E-Book App", native=True, reload=False, port=0)