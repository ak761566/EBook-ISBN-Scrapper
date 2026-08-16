import logging
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from login_manager import UserCredentials, LoginPage, configure_persistent_profile


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)



URL = "https://audit.portico.org/Portico/login.html"

cred = UserCredentials(username="AKumar", password="Iwillown100crore@2023")

options = Options()
#options.add_argument("--headless=new")
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

driver = webdriver.Chrome(options=options)

auth_page = LoginPage(driver)

auth_page.execute_login(credentials=cred, login_url=URL)