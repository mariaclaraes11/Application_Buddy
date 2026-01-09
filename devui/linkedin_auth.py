"""
LinkedIn Authentication Helper
Run this ONCE to log in and save your session.
After that, the scraper can run headless.

Usage: python linkedin_auth.py
"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

AUTH_STATE_PATH = Path(__file__).parent.parent / "playwright" / ".auth" / "state.json"


async def authenticate():
    """Open browser for manual LinkedIn login, then save session."""
    AUTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    print("Opening browser for LinkedIn login...")
    print("Please log in manually, then the session will be saved.\n")
    
    async with async_playwright() as p:
        # Try to use system browser first (works better in WSL)
        try:
            browser = await p.chromium.launch(
                headless=False,
                channel="msedge",  # Use Windows Edge
                args=['--no-sandbox']
            )
        except:
            try:
                browser = await p.chromium.launch(
                    headless=False,
                    channel="chrome",  # Try Chrome
                    args=['--no-sandbox']
                )
            except:
                # Fall back to Playwright's Chromium
                browser = await p.chromium.launch(
                    headless=False,
                    args=['--no-sandbox', '--disable-gpu']
                )
        
        context = await browser.new_context()
        page = await context.new_page()
        
        await page.goto("https://www.linkedin.com/login")
        
        print("Waiting for you to log in...")
        print("After login, you should see your LinkedIn feed.")
        
        # Wait for successful login (feed page)
        try:
            await page.wait_for_url("**/feed/**", timeout=300000)  # 5 min timeout
            print("\n✓ Login successful!")
            
            # Save the session
            await context.storage_state(path=str(AUTH_STATE_PATH))
            print(f"✓ Session saved to: {AUTH_STATE_PATH}")
            print("\nYou can now use 'Sync from LinkedIn' in the app!")
            
        except Exception as e:
            print(f"\n✗ Login failed or timed out: {e}")
        
        await browser.close()


if __name__ == "__main__":
    asyncio.run(authenticate())
