"""Collects rental listing IDs from 591.com.tw based on a provided URL.

This script navigates to a specified 591.com.tw rental listing page,
extracts listing IDs, and saves them to a joblib file.

It supports pagination to collect IDs from multiple pages.

Environment Variables:
    X591URL: The base URL for the 591.com.tw rental listings. This URL
        must contain a 'region' query parameter.

Functions:
    main: The main function to execute the listing collection process.
"""

import os
import re
import time
import random
from urllib.parse import urlparse, parse_qs

import typer
import joblib
from DrissionPage import ChromiumPage, ChromiumOptions

URL = os.environ["X591URL"]

LISTING_SELECTOR = "css:.item-info-title a"
DEBUG_DIR = "cache/debug"
# A normal desktop Chrome UA. Headless Chrome otherwise sends "HeadlessChrome",
# which is an easy signal for anti-bot systems.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
)


def create_browser(headless: bool = False) -> ChromiumPage:
    """Create a DrissionPage browser instance with anti-detection settings."""
    opts = ChromiumOptions()
    if headless:
        opts.headless()
    opts.set_user_agent(USER_AGENT)
    opts.set_argument("--no-sandbox")
    opts.set_argument("--disable-blink-features=AutomationControlled")
    opts.set_argument("--no-first-run")
    opts.set_argument("--no-default-browser-check")
    opts.set_argument("--lang=zh-TW")
    opts.set_argument("--window-size=1920,1080")
    return ChromiumPage(opts)


def dump_debug(page: ChromiumPage, name: str = "list_page"):
    """Save a screenshot and the HTML so we can see what 591 actually served."""
    os.makedirs(DEBUG_DIR, exist_ok=True)
    try:
        typer.echo(f"Page title: {page.title}")
        typer.echo(f"Page URL:   {page.url}")
        page.get_screenshot(path=DEBUG_DIR, name=f"{name}.png", full_page=True)
        with open(os.path.join(DEBUG_DIR, f"{name}.html"), "w", encoding="utf-8") as f:
            f.write(page.html)
        typer.echo(f"Saved debug screenshot/HTML to {DEBUG_DIR}/")
    except Exception as e:  # debugging must never hide the real error
        typer.echo(f"Failed to save debug info: {e}")


def navigate_to_a_page(page: ChromiumPage, url: str, attempts: int = 3) -> bool:
    """Open the list page; retry when listing items don't show up.

    Returns True if listing items were found.
    Note: DrissionPage's wait.eles_loaded() returns False on timeout instead of
    raising, so its return value must be checked explicitly.
    """
    for attempt in range(1, attempts + 1):
        try:
            page.get(url)
        except Exception as e:
            typer.echo(f"Failed to navigate to the page: {e}")
            raise e

        if page.wait.eles_loaded(LISTING_SELECTOR, timeout=15):
            typer.echo("Page content loaded.")
            time.sleep(random.random() * 2 + 1)
            return True

        typer.echo(f"Listing items not found (attempt {attempt}/{attempts}).")
        if attempt < attempts:
            time.sleep(10 * attempt + random.random() * 5)

    return False


def main(output_path: str = "cache/listings.jbl", max_pages: int = 10, quiet: bool = False):
    try:
        region = parse_qs(urlparse(URL).query)["region"][0]
    except (AttributeError, KeyError) as e:
        print("The URL must have a 'region' query argument!")
        raise e

    page = create_browser(headless=quiet)
    typer.echo("Browser initialized.")

    # Navigate to the specified URL
    if not navigate_to_a_page(page, URL):
        dump_debug(page)
        page.quit()
        typer.echo(
            "ERROR: 591 returned a page without any listings. "
            "It is probably blocking this machine (anti-bot / captcha). "
            "Check the 'debug' artifact for the screenshot."
        )
        raise typer.Exit(code=1)

    listings: set[str] = set()
    for i in range(max_pages):
        print(f"Page {i + 1}")

        # Extract listing IDs from links
        links = page.eles(LISTING_SELECTOR)
        for link in links:
            href = link.attr("href") or ""
            match = re.search(r"/(\d+)(?:\.html)?$", href)
            if match:
                listings.add(match.group(1))

        if i == max_pages - 1:
            typer.echo("Reached maximum pages. Exiting...")
            break

        # Find next page link
        next_page = page.ele("text=下一頁", timeout=3)

        if not next_page:
            typer.echo("No more pages to scrape. Exiting...")
            break

        next_href = (next_page.attr("href") or "").strip()
        if next_href in ("", "#"):
            typer.echo("No more pages to scrape. Exiting...")
            break

        next_page.click()
        time.sleep(random.random() * 2 + 1)

        # Wait for new page content
        page.wait.eles_loaded(LISTING_SELECTOR, timeout=10)

    if not listings:
        dump_debug(page)
        page.quit()
        typer.echo("ERROR: Collected 0 entries. Check the 'debug' artifact.")
        raise typer.Exit(code=1)

    joblib.dump(list(listings), output_path)
    print(f"Done! Collected {len(listings)} entries.")

    page.quit()


if __name__ == "__main__":
    typer.run(main)
