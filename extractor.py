"""
Data extraction functions for Hume tasks
Extracts structured data like checks, decisions, etc.
"""
from playwright.sync_api import Page
from typing import List, Dict, Optional
import re
import os


DEBUG_MODE = os.getenv('DEBUG', 'false').lower() == 'true'


def extract_task_id_from_url(url: str) -> Optional[str]:
    """Extract task ID from URL"""
    match = re.search(r'/datachangereview/([A-Za-z0-9_-]+)', url)
    return match.group(1) if match else None


def extract_report_id(page: Page) -> Optional[str]:
    """Extract feedbackhub report ID from page"""
    try:
        # Method 1: Try to find the link in the header section
        link = page.locator('div.dcr-header a[href*="feedbackhub/report/"]').first
        
        # Method 2: Fallback to any link with feedbackhub
        if link.count() == 0:
            link = page.locator('a[href*="feedbackhub/report/"]').first
        
        if link.count() > 0:
            href = link.get_attribute('href')
            if href:
                # Extract Report ID from URL (last part after /)
                report_id = href.rstrip("/").split("/")[-1]
                # Clean any query parameters
                report_id = report_id.split('?')[0]
                print(f"   ✓ Extracted Report ID from link: {report_id}")
                return report_id
        
        # Method 3: Try to extract from the visible text in the header
        print(f"   ⚠️  Link not found, trying to extract from text...")
        header_text = page.locator('div.dcr-header h1').first
        if header_text.count() > 0:
            text = header_text.inner_text()
            # Report ID format is usually alphanumeric with underscores
            import re
            match = re.search(r'([A-Za-z0-9_-]{20,})', text)
            if match:
                report_id = match.group(1)
                print(f"   ✓ Extracted Report ID from text: {report_id}")
                return report_id
        
        print(f"   ⚠️  Could not extract report ID from page")
        
    except Exception as e:
        print(f"   ⚠️  Error extracting report ID: {str(e)}")
    
    return None


def extract_previous_decisions(page: Page) -> List[Dict]:
    """Extract all Previous Decisions (checks) from the page"""
    decisions = []
    
    try:
        print("   🔍 Looking for expansion panels on the page...")
        
        # Wait for Angular Material components to load
        try:
            print("   ⏳ Waiting for Angular components to render...")
            page.wait_for_selector('mat-expansion-panel', timeout=10000, state='attached')
            page.wait_for_timeout(2000)  # Extra time for rendering
        except Exception as e:
            print(f"   ⚠️  Timeout waiting for expansion panels: {e}")
            print(f"   💡 Page might still be loading or doesn't have expansion panels")
        
        # Save page HTML for debugging if DEBUG mode is on
        if DEBUG_MODE:
            try:
                html_content = page.content()
                with open('debug_page.html', 'w', encoding='utf-8') as f:
                    f.write(html_content)
                print(f"   📄 Page HTML saved to debug_page.html")
            except Exception as e:
                print(f"   ⚠️  Could not save HTML: {e}")
        
        # Scroll to make sure content is loaded
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            page.wait_for_timeout(2000)
        except:
            pass
        
        # First, list ALL expansion panels to see what's available
        all_panels = page.locator('mat-expansion-panel').all()
        print(f"   📊 Found {len(all_panels)} expansion panel(s) on page")
        
        # Log what panels exist
        expansion_panel = None
        for i, panel in enumerate(all_panels):
            try:
                header = panel.locator('mat-expansion-panel-header').first
                if header.count() > 0:
                    panel_title = header.inner_text().strip()
                    print(f"   📋 Panel {i+1}: '{panel_title}'")
                    
                    # Look for variations of "Previous Decisions"
                    if any(keyword in panel_title.lower() for keyword in ['previous', 'decision', 'review', 'check']):
                        print(f"   ✓ Found matching panel: '{panel_title}'")
                        expansion_panel = panel
                        break
            except Exception as e:
                print(f"   ⚠️  Could not read panel {i+1}: {e}")
                continue
        
        if expansion_panel is None:
            print(f"   ❌ Could not find any matching expansion panel")
            print(f"   💡 The page might not have 'Previous Decisions' section")
            return decisions
        
        # Check if already expanded
        is_expanded = expansion_panel.get_attribute('class')
        
        if 'mat-expanded' not in (is_expanded or ''):
            print(f"   ✓ Clicking to expand panel...")
            try:
                expansion_panel.locator('mat-expansion-panel-header').first.click()
                page.wait_for_timeout(3000)
            except Exception as e:
                print(f"   ⚠️  Could not click panel: {e}")
                return decisions
        else:
            print(f"   ✓ Panel already expanded")
        
        # Wait for table rows to appear (reduced timeout - 15s)
        print(f"   ✓ Waiting for table content to load...")
        
        try:
            page.locator('mat-row').first.wait_for(state='visible', timeout=15000)
        except:
            print(f"   ⚠️  No table rows found after 15s")
            # Take a screenshot for debugging in headless mode
            try:
                page.screenshot(path="debug_no_rows.png")
                print(f"   📸 Screenshot saved to debug_no_rows.png")
            except:
                pass
            
            page.wait_for_timeout(3000)
            
            # Try alternative: look for any table data
            row_count = page.locator('mat-row').count()
            print(f"   📊 Total mat-row elements found: {row_count}")
            
            if row_count == 0:
                print(f"   ⚠️  No rows found. Checking for alternative table structures...")
                
                # Try looking for any table or list structure
                tables = page.locator('table').count()
                divs_with_data = page.locator('div[role="row"]').count()
                print(f"   📊 Found {tables} table(s), {divs_with_data} div[role=row]")
                
                if tables == 0 and divs_with_data == 0:
                    print(f"   ❌ No table data found - returning empty")
                    return decisions
        
        print(f"   ✓ Extracting from Material table...")
        
        data_rows = page.locator('mat-row').all()
        print(f"   ✓ Found {len(data_rows)} reviewer row(s)")
        
        for idx, row in enumerate(data_rows, start=1):
            cells = row.locator('mat-cell').all()
            
            if len(cells) < 4:
                print(f"      ⚠️  Row {idx} has insufficient cells: {len(cells)}")
                continue
            
            role_cell = cells[1]
            role_name = role_cell.inner_text().strip()
            answers_cell = cells[3]
            
            print(f"   📋 Extracting checks for: {role_name}")
            
            # Wait for check divs to be visible (10s timeout)
            try:
                answers_cell.locator('.previous-answer').first.wait_for(state='visible', timeout=10000)
            except:
                print(f"      ⚠️  No checks found for {role_name}")
                continue
            
            check_divs = answers_cell.locator('.previous-answer').all()
            checks = []
            
            for check_div in check_divs:
                check_name_elem = check_div.locator('.question-title').first
                if check_name_elem.count() == 0:
                    continue
                
                check_name = check_name_elem.inner_text().strip()
                
                codes = []
                chip_elems = check_div.locator('mat-chip .mdc-evolution-chip__text-label').all()
                for chip in chip_elems:
                    code_text = chip.inner_text().strip()
                    if code_text:
                        codes.append(code_text)
                
                text_content = ""
                text_rows = check_div.locator('.answer-row').all()
                for text_row in text_rows:
                    row_text = text_row.inner_text().strip()
                    if row_text.startswith('text:'):
                        text_div = text_row.locator('div').first
                        if text_div.count() > 0:
                            text_content = text_div.inner_text().strip()
                        break
                
                checks.append({
                    'check_name': check_name,
                    'codes': codes,
                    'text': text_content
                })
            
            # Only include Senior Reviewer checks for PKT tool
            is_senior_reviewer = any(keyword in role_name.lower() for keyword in ['senior', 'sr'])
            
            if is_senior_reviewer:
                decisions.append({
                    'role': role_name,
                    'role_number': idx,
                    'checks': checks
                })
                print(f"      ✅ Found {len(checks)} checks (Senior Reviewer)")
            else:
                print(f"      ⏭️  Skipping {len(checks)} checks (Non-SR role: {role_name})")
    
    except Exception as e:
        print(f"   ⚠️  Error extracting decisions: {str(e)}")
        import traceback
        traceback.print_exc()
    
    return decisions


def extract_full_task_data(page: Page, input_url: str) -> Dict:
    """Extract complete task data including ID, report link, and all checks"""
    task_id = extract_task_id_from_url(input_url)
    report_id = extract_report_id(page)
    decisions = extract_previous_decisions(page)
    
    return {
        'task_id': task_id,
        'input_url': input_url,
        'report_id': report_id or "NOT FOUND",
        'decisions': decisions,
        'total_reviewers': len(decisions),
        'total_checks': sum(len(d['checks']) for d in decisions)
    }
