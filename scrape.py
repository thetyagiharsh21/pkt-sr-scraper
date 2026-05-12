from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
import time
from pathlib import Path
from extractor import extract_full_task_data
import random
from datetime import datetime
from sheets_handler import SheetsHandler
import os

# Configuration
USER_DATA_DIR = "../browser-profile"  # Look in parent directory (Practice Tool root)
STORAGE_STATE_FILE = "../config/auth_state.json"  # Shared authentication for both scrapers
LOGIN_TIMEOUT_SECONDS = 120
PAGE_LOAD_TIMEOUT = 60000
HEADLESS_MODE = os.getenv('HEADLESS', 'true').lower() == 'true'  # Default: run in background
DEBUG_MODE = os.getenv('DEBUG', 'false').lower() == 'true'  # Set DEBUG=true for screenshots

# Google Sheets Configuration
GOOGLE_SHEETS_ENABLED = True
CREDENTIALS_FILE = "../config/oauth_credentials.json"  # OAuth credentials for Drive upload
# Output sheet for SR Checks
SPREADSHEET_ID = "1LSxZ5bc6WXIlqETkpLcZ_RSzp-JOWkJ1qTUaPZYX_98"

# Input Google Sheet Configuration - Multi-tab structure for PKT Tool
FETCH_URLS_FROM_SHEET = True
INPUT_SPREADSHEET_ID = "1vTOCwDUZ2hhZEQj74TOWqpV5zsAusLdI8otVpA4Pr-g"
# Tab names for different check categories
INPUT_TABS = ["Policy", "Punts", "Horizontal", "Multiturn", "Freshness", "Factuality", "Others", "NA"]
URL_COLUMN = "A"  # Task links are in column A

# Fixed check headers for PKT tool (Senior Reviewer checks only)
FIXED_CHECKS = [
    "Loss Pattern Issues",
    "Any policy violation observed in the response?",
    "Horizontal Losses",
    "Multiturn",
    "Freshness (in priority)",
    "Fact Accuracy Check",
    "Factuality Source",
    "Inputs issues",
    "Factuality-Summarization issues",
    "Factuality-Reasoning Issues",
    "Factuality-Unfactual claims with no clear cause",
    "Specific bucket (for factuality losses)",
    "Numerical claim subcodes",
    "Others",
    "Temporal subcodes",
    "Domain",
    "User query analysis",
    "Check for caching",
    "Fanout validity",
    "Assess retrieval effectiveness",
    "Verify information availability",
    "Model utilization"
]


def check_if_logged_in(page):
    """Check if user is logged in"""
    current_url = page.url.lower()
    
    if any(keyword in current_url for keyword in ['login', 'signin', 'authenticate', 'accounts.google']):
        print(f"   ✗ On login page: {current_url[:60]}")
        return False
    
    if 'hume.google.com/datachangereview' in current_url:
        print(f"   ✓ LOGGED IN! On task page")
        return True
    
    return False


def generate_unique_task_id(used_ids=None):
    """
    Generate a unique Task ID in format: KMKAIM{YYYYMM}{5-digit random number}
    Example: KMKAIM20260112345
    
    Args:
        used_ids: Set of already used IDs to ensure uniqueness
    
    Returns:
        str: Unique task ID
    """
    if used_ids is None:
        used_ids = set()
    
    # Get current year and month (YYYYMM format)
    current_date = datetime.now()
    year_month = current_date.strftime("%Y%m")  # e.g., "202601"
    
    # Generate random 5-digit number between 10100 and 99999
    max_attempts = 1000  # Prevent infinite loop
    for _ in range(max_attempts):
        random_number = random.randint(10100, 99999)
        task_id = f"KMKAIM{year_month}{random_number}"
        
        # Check if this ID is unique
        if task_id not in used_ids:
            used_ids.add(task_id)
            return task_id
    
    # If we couldn't generate a unique ID after max_attempts, raise an error
    raise RuntimeError(f"Failed to generate unique Task ID after {max_attempts} attempts")


def wait_for_login(page, timeout_seconds=120):
    """Wait for user to complete login"""
    print(f"\n🔐 Please log in with your corp account in the browser")
    print(f"⏳ Checking login status every second...")
    
    start_time = time.time()
    check_interval = 1
    last_url = ""
    
    while time.time() - start_time < timeout_seconds:
        elapsed = int(time.time() - start_time)
        current_url = page.url
        
        if current_url != last_url:
            print(f"   🌐 Current page: {current_url[:80]}...")
            last_url = current_url
        
        if check_if_logged_in(page):
            print(f"✅ Login detected after {elapsed} seconds!")
            return True
        
        if elapsed > 0 and elapsed % 10 == 0:
            remaining = timeout_seconds - elapsed
            print(f"   ⏱️  Still waiting for login... ({remaining}s remaining)")
        
        time.sleep(check_interval)
    
    raise TimeoutError(f"Login timeout after {timeout_seconds} seconds")


def scrape_task_url(page, task_metadata, index, total, used_ids):
    """Scrape a single task URL - extracts only SR checks"""
    url = task_metadata['task_link']
    check_category = task_metadata.get('check_category', 'Unknown')
    
    print(f"\n{'='*60}")
    print(f"➡️  Processing ({index}/{total}) [{check_category}]: {url}")
    print(f"{'='*60}")
    
    task_id = generate_unique_task_id(used_ids)
    
    try:
        print("   ⏳ Loading page...")
        page.goto(url, wait_until="load", timeout=PAGE_LOAD_TIMEOUT)
        
        print("   ⏳ Waiting for page to fully load...")
        
        # In headless mode, give extra time for Angular/Material components to render
        if HEADLESS_MODE:
            print("   ⏳ Extra wait for headless mode (Angular components)...")
            time.sleep(8)  # Reduced from 15s to 8s for faster scraping
            
            # Check for Angular components
            try:
                page.wait_for_function("() => document.readyState === 'complete'", timeout=3000)
                page.wait_for_function("() => !!document.querySelector('mat-expansion-panel')", timeout=8000)
                print("   ✓ Angular components detected")
            except Exception as e:
                print(f"   ⚠️  Warning: Angular components might not be fully loaded: {e}")
        else:
            time.sleep(3)
        
        # Take debug screenshot if enabled
        if DEBUG_MODE:
            screenshot_path = f"debug_task_{task_id}.png"
            page.screenshot(path=screenshot_path)
            print(f"   📸 Debug screenshot: {screenshot_path}")
        
        # Extract SR checks only
        print("   🔍 Extracting SR checks...")
        task_data = extract_full_task_data(page, url)
        
        print(f"   ✅ Task ID: {task_id}")
        print(f"   ✅ Report ID: {task_data['report_id']}")
        print(f"   ✅ Found {task_data['total_reviewers']} reviewer(s)")
        print(f"   ✅ Total checks: {task_data['total_checks']}")
        
        # Construct feedback hub link from report ID
        feedback_hub_link = f"https://hume.google.com/feedbackhub/report/{task_data['report_id']}" if task_data['report_id'] and task_data['report_id'] not in ['NOT FOUND', 'ERROR'] else ""
        
        task_data['task_id'] = task_id
        task_data['status'] = ''  # Leave blank - means checks scraped, FH pending
        task_data['check_category'] = check_category
        task_data['feedback_hub_link'] = feedback_hub_link
        task_data['job_short_name'] = task_metadata['job_short_name']
        task_data['reviewers_justification'] = task_metadata['reviewers_justification']
        task_data['r_ldap'] = task_metadata['r_ldap']
        task_data['sr_ldap'] = task_metadata['sr_ldap']
        task_data['error'] = None
        
        return task_data
        
    except Exception as e:
        print(f"   ❌ Error: {str(e)}")
        
        return {
            'task_id': task_id,
            'input_url': url,
            'report_id': "ERROR",
            'status': 'Error',
            'check_category': check_category,
            'feedback_hub_link': "",
            'job_short_name': task_metadata['job_short_name'],
            'reviewers_justification': task_metadata['reviewers_justification'],
            'r_ldap': task_metadata['r_ldap'],
            'sr_ldap': task_metadata['sr_ldap'],
            'decisions': [],
            'total_reviewers': 0,
            'total_checks': 0,
            'error': str(e)
        }


def main():
    print("=" * 60)
    print("🚀 PKT TOOL - SR CHECKS SCRAPER")
    print("=" * 60)
    
    # Initialize sheets handler with OAuth
    sheets_handler = SheetsHandler(CREDENTIALS_FILE, use_oauth=True)
    
    # Fetch URLs and metadata from multiple tabs
    if FETCH_URLS_FROM_SHEET:
        try:
            tasks_metadata = sheets_handler.fetch_input_data_from_multiple_tabs(INPUT_SPREADSHEET_ID, INPUT_TABS)
        except Exception as e:
            print(f"\n{e}")
            print("\n❌ Cannot proceed without URLs. Exiting...")
            return
    else:
        print(f"\n❌ FETCH_URLS_FROM_SHEET is disabled!")
        print(f"   Please enable it in the configuration.")
        return
    
    if not tasks_metadata:
        print("\n❌ No URLs to process! Exiting...")
        return
    
    print(f"\n📊 Total tasks to process: {len(tasks_metadata)}")
    
    # Check for existing storage state (like fetch.py does)
    storage_state_exists = Path(STORAGE_STATE_FILE).exists()
    
    if storage_state_exists:
        print(f"\n✅ Found existing session: {STORAGE_STATE_FILE}")
        print("   (Login session saved)")
    else:
        print(f"\n⚠️  No existing session - first run")
        print("   (You'll need to log in)")
    
    with sync_playwright() as p:
        print(f"\n🌐 Launching browser...")
        
        # Use storage_state approach (like fetch.py) instead of persistent_context
        # This is more reliable for headless mode with interactive components
        if not storage_state_exists:
            # First time: visible browser for login
            print("🖥️  First run: launching visible browser for login...")
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            
            # Go to Hume and wait for login
            page.goto("https://hume.google.com/", timeout=PAGE_LOAD_TIMEOUT)
            print("\n🔐 Please log in with your corp account")
            print("⏳ Waiting for you to complete login...")
            print("💡 After login, just wait - the script will detect it automatically")
            
            # Wait for navigation away from login page
            try:
                page.wait_for_url(lambda url: 'hume.google.com' in url and not any(k in url.lower() for k in ['login', 'signin', 'authenticate', 'accounts.google']), timeout=120000)
                print(f"\n✅ Login successful! Session saved to {STORAGE_STATE_FILE}")
                logged_in = True
            except:
                print("\n❌ Login timeout - couldn't detect successful login")
                logged_in = False
            
            if not logged_in:
                print("\n❌ Login timeout")
                browser.close()
                return
            
            # Save session state
            context.storage_state(path=STORAGE_STATE_FILE)
            print(f"\n✅ Login successful! Session saved to {STORAGE_STATE_FILE}")
            browser.close()
        
        # Now launch with saved session (works in headless!)
        browser = p.chromium.launch(headless=HEADLESS_MODE)
        context = browser.new_context(storage_state=STORAGE_STATE_FILE)
        
        if HEADLESS_MODE:
            print("🔇 Running in headless mode (background)")
        else:
            print("🖥️  Running with visible browser window")
        
        page = context.new_page()
        
        # Process all tasks
        print(f"\n{'=' * 60}")
        print(f"📊 SCRAPING {len(tasks_metadata)} TASK(S)")
        print("=" * 60)
        
        results = []
        used_ids = set()  # Track used Task IDs to ensure uniqueness
        
        for index, task_metadata in enumerate(tasks_metadata, start=1):
            row_number = task_metadata.get('row_number')
            sheet_name = task_metadata.get('sheet_name')
            check_category = task_metadata.get('check_category', 'Unknown')
            
            # Update status to "Processing" before starting
            if row_number and sheet_name:
                print(f"\n📝 Updating status to 'Processing' for row {row_number} in tab '{sheet_name}'...")
                sheets_handler.update_task_status_in_tab(INPUT_SPREADSHEET_ID, sheet_name, row_number, "Processing")
            
            try:
                result = scrape_task_url(page, task_metadata, index, len(tasks_metadata), used_ids)
                results.append(result)
                
                # Validate if meaningful data was extracted
                is_valid_extraction = (
                    result.get('report_id') and 
                    result['report_id'] != 'NOT FOUND' and 
                    result['report_id'] != 'ERROR' and
                    result.get('total_checks', 0) > 0
                )
                
                if not is_valid_extraction:
                    print(f"⚠️  WARNING: No meaningful data extracted!")
                    print(f"   Report ID: {result.get('report_id', 'MISSING')}")
                    print(f"   Total Checks: {result.get('total_checks', 0)}")
                    result['status'] = 'Error'
                    result['error'] = 'Data extraction failed: No checks found or invalid Report ID'
                
                # Save to Google Sheets immediately after scraping
                if GOOGLE_SHEETS_ENABLED:
                    print(f"💾 Writing SR checks to tab '{check_category}'...")
                    sheets_handler.save_to_sheet([result], SPREADSHEET_ID, FIXED_CHECKS, tab_name=check_category)
                
                # Update status based on scraping result AND data validation
                if row_number and sheet_name:
                    if is_valid_extraction and not result.get('error'):
                        print(f"✅ Updating status to 'Scraped' for row {row_number} in tab '{sheet_name}'")
                        sheets_handler.update_task_status_in_tab(INPUT_SPREADSHEET_ID, sheet_name, row_number, "Scraped")
                    else:
                        error_msg = result.get('error', 'Data extraction failed')
                        print(f"❌ Updating status to 'Error: {error_msg}' for row {row_number} in tab '{sheet_name}'")
                        sheets_handler.update_task_status_in_tab(INPUT_SPREADSHEET_ID, sheet_name, row_number, f"Error: {error_msg}")
            except Exception as e:
                print(f"❌ Exception occurred during scraping: {str(e)}")
                # Create error result
                result = {
                    'status': 'Error',
                    'error_message': str(e),
                    **task_metadata
                }
                results.append(result)
                
                # Save error result to Google Sheets immediately
                if GOOGLE_SHEETS_ENABLED:
                    print(f"💾 Writing error data to tab '{check_category}'...")
                    sheets_handler.save_to_sheet([result], SPREADSHEET_ID, FIXED_CHECKS, tab_name=check_category)
                
                # Update status to Error
                if row_number and sheet_name:
                    print(f"❌ Updating status to 'Error' for row {row_number} in tab '{sheet_name}'")
                    sheets_handler.update_task_status_in_tab(INPUT_SPREADSHEET_ID, sheet_name, row_number, "Error")
            
            time.sleep(1)
        
        browser.close()
        
        # Summary
        print("\n" + "=" * 60)
        print("📊 FINAL SUMMARY")
        print("=" * 60)
        
        success_count = sum(1 for r in results if r['status'] == 'Ready')
        error_count = sum(1 for r in results if r['status'] == 'Error')
        total_checks = sum(r.get('total_checks', 0) for r in results)
        
        print(f"✅ Successfully scraped: {success_count}/{len(tasks_metadata)} tasks")
        print(f"❌ Errors: {error_count}")
        print(f"📋 Total checks extracted: {total_checks}")
        print(f"\n💾 Data saved to Google Sheets:")
        print(f"   📊 https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}")
        print(f"🔐 Session file: {STORAGE_STATE_FILE}")
        print("=" * 60)
        
        # Ask user if they want to run Feedback Hub scraping (only in interactive mode)
        import sys
        if sys.stdin.isatty():  # Interactive mode (terminal)
            print("\n" + "=" * 60)
            print("🔄 NEXT STEP: Feedback Hub Scraping")
            print("=" * 60)
            response = input("\n❓ Do you want to run Feedback Hub Scraping now? (yes/no): ").strip().lower()
            
            if response in ['y', 'yes', 'ye', 'yeah']:
                print("\n🚀 Starting Feedback Hub Scraping...")
                print("=" * 60)
                import subprocess
                import sys
                feedback_hub_script = Path(__file__).parent.parent / "Feedback_Hub_Scrape" / "run.py"
                try:
                    result = subprocess.run([sys.executable, str(feedback_hub_script)], cwd=feedback_hub_script.parent)
                    sys.exit(result.returncode)
                except Exception as e:
                    print(f"\n❌ Error running Feedback Hub Scraping: {e}")
                    sys.exit(1)
            else:
                print("\n✅ Checks Scraping completed. Exiting...")
        else:
            # Non-interactive mode (GitHub Actions, cron, etc.)
            print("\n✅ Checks scraping completed (non-interactive mode)")
            print("💡 Feedback Hub scraping will run automatically next")


if __name__ == "__main__":
    main()
