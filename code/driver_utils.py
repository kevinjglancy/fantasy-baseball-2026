"""Shared Selenium WebDriver setup and configuration."""

import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service


def create_driver() -> webdriver.Chrome:
    """Create a configured headless Chrome WebDriver.

    On GitHub Actions, CHROMEDRIVER_PATH env var points to the system chromedriver.
    Locally, Selenium's built-in manager finds the right driver automatically.
    """
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36')

    # Allow overriding Chrome binary (needed on GitHub Actions where it's chromium-browser)
    chrome_binary = os.environ.get('CHROME_BINARY')
    if chrome_binary:
        options.binary_location = chrome_binary

    chromedriver_path = os.environ.get('CHROMEDRIVER_PATH')
    if chromedriver_path:
        return webdriver.Chrome(service=Service(chromedriver_path), options=options)

    # Local: let Selenium manager find the driver automatically
    return webdriver.Chrome(options=options)


def setup_driver_with_cookies(swid: str, espn_s2: str) -> webdriver.Chrome:
    """Create driver, navigate to ESPN, and add auth cookies."""
    driver = create_driver()
    driver.get('https://fantasy.espn.com')
    driver.add_cookie({'name': 'SWID', 'value': swid})
    driver.add_cookie({'name': 'espn_s2', 'value': espn_s2})
    return driver
