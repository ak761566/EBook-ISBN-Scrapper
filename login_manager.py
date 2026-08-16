import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from selenium.common import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class UserCredentials:
    username: str
    password: str



class LoginPage:
    USERNAME_INPUT : Tuple[By, str] = (By.ID, "username")
    PASSWORD_INPUT : Tuple[By, str] = (By.ID, "password")
    SUBMIT_BUTTON :  Tuple[By, str] = (By.CSS_SELECTOR, "button[type='submit']")
    DASHBOARD_ELEMENT: Tuple[By, str] = (By.CLASS_NAME, "desktop-version")

    def __init__(self, driver: WebDriver, timeout: int = 10):
        self.driver = driver
        self.wait = WebDriverWait(driver, timeout)


    def is_authenticated(self) -> bool:
        try:
            WebDriverWait(self.driver, 3).until(
                EC.presence_of_element_located(self.DASHBOARD_ELEMENT)
            )
            return True
        except Exception as e:
            logger.info("Session is unauthenticated")
            return False


    def execute_login(self, credentials: UserCredentials, login_url: str):
        if self.is_authenticated():
            return

        logger.info(f"Navigating to login url {login_url}")
        try:
            self.driver.get(login_url)

            # 1. Populate Username
            logger.info(f"User Name {credentials.username}")
            user_field = self.wait.until(
                EC.element_to_be_clickable(self.USERNAME_INPUT)
            )
            user_field.clear()
            user_field.send_keys(credentials.username)

            # 2. Populate Password
            pass_field = self.wait.until(
                EC.element_to_be_clickable(self.PASSWORD_INPUT)
            )
            logger.info(f"User Name {credentials.password}")
            pass_field.clear()
            pass_field.send_keys(credentials.password)

            submit_btn = self.wait.until(
                EC.element_to_be_clickable(self.SUBMIT_BUTTON)
            )
            submit_btn.click()

            logger.info("Awaiting post-login session confirmation...")
            self.wait.until(
                EC.presence_of_element_located(self.DASHBOARD_ELEMENT)
            )
            logger.info("Login successful!")
        except WebDriverException as err:
            logger.warning("Disconnect VPN and try again...")



def configure_persistent_profile(profile_dir: str = ".chrome_profile") -> Options:
    options = Options()
    path = Path(profile_dir).resolve()
    path.mkdir(parents=True, exist_ok=True)

    # Execution Mode
    options.add_argument("--headless=new")  # Modern headless flag (Chrome 109+)

    # Stability & Memory
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")  # Bypass OS security model bottlenecks
    options.add_argument("--disable-dev-shm-usage")  # Overcomes limited resource problems

    # Anti-Detection & Stealth
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    # Experimental Options
    options.add_experimental_option("detach", True)
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    # Directs Chrome to persist local storage, cookies, and tokens across script runs
    options.add_argument(f"--user-data-dir={path}")
    options.add_argument("--profile-directory=Default")
    return options