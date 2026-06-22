"""Shared Selenium WebDriver setup and configuration."""

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


def create_driver() -> webdriver.Chrome:
    """Create a configured headless Chrome WebDriver."""
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36')

    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)


def setup_driver_with_cookies(swid: str, espn_s2: str) -> webdriver.Chrome:
    """Create driver, navigate to ESPN, and add auth cookies."""
    driver = create_driver()
    driver.get('https://fantasy.espn.com')
    driver.add_cookie({'name': 'SWID', 'value': swid})
    driver.add_cookie({'name': 'espn_s2', 'value': espn_s2})
    return driver
