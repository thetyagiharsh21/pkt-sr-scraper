"""
Google Sheets Handler
Handles all Google Sheets operations - reading input and writing output
"""

import gspread
import os
from google.oauth2.service_account import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as OAuthCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload
import pickle


class SheetsHandler:
    """Handles all Google Sheets operations"""
    
    def __init__(self, credentials_file, use_oauth=True):
        self.credentials_file = credentials_file
        self.use_oauth = use_oauth
        self.scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        self.client = None
        self.drive_service = None
        self.creds = None
    
    def authenticate(self):
        """Authenticate with Google Sheets and Drive using OAuth or Service Account"""
        try:
            if self.use_oauth:
                # OAuth authentication (for Drive uploads)
                self._authenticate_oauth()
            else:
                # Service account authentication
                self._authenticate_service_account()
            
            self.client = gspread.authorize(self.creds)
            self.drive_service = build('drive', 'v3', credentials=self.creds)
            return True
        except FileNotFoundError:
            raise FileNotFoundError(
                f"❌ Error: Credentials file not found!\n"
                f"   For OAuth: Place 'oauth_credentials.json' in config folder\n"
                f"   For Service Account: Place 'credentials.json' in config folder"
            )
    
    def _authenticate_service_account(self):
        """Authenticate using service account"""
        self.creds = Credentials.from_service_account_file(self.credentials_file, scopes=self.scopes)
    
    def _authenticate_oauth(self):
        """Authenticate using OAuth (opens browser on first run)"""
        token_file = os.path.join(os.path.dirname(self.credentials_file), 'token.pickle')
        
        # Try to load existing token
        if os.path.exists(token_file):
            with open(token_file, 'rb') as token:
                self.creds = pickle.load(token)
        
        # If no valid credentials, do OAuth flow
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                print("   🔄 Refreshing OAuth token...")
                self.creds.refresh(Request())
            else:
                print("   🔐 Starting OAuth authentication...")
                print("   🌐 A browser window will open for authorization...")
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_file, self.scopes)
                self.creds = flow.run_local_server(port=0)
                print("   ✅ Authentication successful!")
            
            # Save token for next run
            with open(token_file, 'wb') as token:
                pickle.dump(self.creds, token)
                print(f"   💾 Token saved to {token_file}")
    
    def fetch_input_data_from_multiple_tabs(self, spreadsheet_id, tab_names):
        """
        Fetch task URLs from multiple tabs (for PKT Tool multi-category structure)
        Each tab represents a check category (Policy, Punts, Horizontal, etc.)
        Returns list of task metadata dictionaries with tab name as check_category
        """
        if not self.client:
            self.authenticate()
        
        print(f"\n📊 Fetching task links from multiple tabs...")
        
        try:
            spreadsheet = self.client.open_by_key(spreadsheet_id)
        except gspread.exceptions.SpreadsheetNotFound:
            raise Exception(
                f"❌ Error: Spreadsheet with ID '{spreadsheet_id}' not found!\n"
                f"   Check that the spreadsheet ID is correct and the service account has access."
            )
        except Exception as e:
            raise Exception(f"❌ Error connecting to Google Sheets: {str(e)}")
        
        print(f"   ✓ Connected to: {spreadsheet.title}")
        
        all_tasks = []
        
        for tab_name in tab_names:
            try:
                sheet = spreadsheet.worksheet(tab_name)
                print(f"   📋 Reading tab: {tab_name}")
                
                # Get all values from the tab
                all_rows = sheet.get_all_values()
                
                if len(all_rows) <= 1:
                    print(f"      ⚠️  No data in {tab_name}, skipping...")
                    continue
                
                # Assuming Column A has task links, Column B might have status
                # Header row is row 0
                for row_idx in range(1, len(all_rows)):
                    task_link = all_rows[row_idx][0].strip() if len(all_rows[row_idx]) > 0 else ""
                    status = all_rows[row_idx][1].strip() if len(all_rows[row_idx]) > 1 else ""
                    
                    # Skip if already scraped or no valid link
                    if status.lower() in ['scraped', 'error']:
                        continue
                    
                    if task_link and task_link.startswith('http'):
                        all_tasks.append({
                            'task_link': task_link,
                            'check_category': tab_name,  # Store which tab this came from
                            'job_short_name': tab_name,  # Use tab name as job name
                            'reviewers_justification': '',
                            'r_ldap': '',
                            'sr_ldap': '',
                            'tab_name': tab_name,
                            'row_number': row_idx + 1,  # Store for status updates
                            'sheet_name': tab_name  # Store sheet name for updates
                        })
                
                print(f"      ✓ Found {sum(1 for t in all_tasks if t['tab_name'] == tab_name)} task(s)")
                
            except gspread.exceptions.WorksheetNotFound:
                print(f"      ⚠️  Tab '{tab_name}' not found, skipping...")
                continue
            except Exception as e:
                print(f"      ❌ Error reading tab '{tab_name}': {str(e)}")
                continue
        
        print(f"   ✅ Total tasks found across all tabs: {len(all_tasks)}")
        
        if not all_tasks:
            raise Exception(
                f"❌ No valid task links found in any of the tabs!\n"
                f"   Tabs checked: {', '.join(tab_names)}"
            )
        
        return all_tasks
    
    def fetch_input_data(self, spreadsheet_id, sheet_name):
        """
        Fetch task URLs and metadata from input Google Sheet
        Only fetches tasks that haven't been scraped yet (empty status or not 'Scraped')
        Returns list of task metadata dictionaries with row numbers
        """
        if not self.client:
            self.authenticate()
        
        print(f"\n📊 Fetching URLs and metadata from Google Sheet...")
        
        try:
            spreadsheet = self.client.open_by_key(spreadsheet_id)
            sheet = spreadsheet.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            raise Exception(
                f"❌ Error: Worksheet '{sheet_name}' not found in spreadsheet!\n"
                f"   Check that the sheet name is correct in the configuration."
            )
        except gspread.exceptions.SpreadsheetNotFound:
            raise Exception(
                f"❌ Error: Spreadsheet with ID '{spreadsheet_id}' not found!\n"
                f"   Check that the spreadsheet ID is correct and the service account has access."
            )
        except Exception as e:
            raise Exception(f"❌ Error connecting to Google Sheets: {str(e)}")
        
        print(f"   ✓ Connected to: {spreadsheet.title} / {sheet_name}")
        
        # Store sheet reference for status updates
        self.input_sheet = sheet
        self.input_spreadsheet_id = spreadsheet_id
        self.input_sheet_name = sheet_name
        
        # Get all rows
        all_rows = sheet.get_all_values()
        
        if len(all_rows) <= 1:
            raise Exception(
                f"❌ No data found in the sheet!\n"
                f"   Make sure the sheet has data rows (not just headers)"
            )
        
        # Parse header row to create column mapping
        header_row = all_rows[0]
        column_mapping = {}
        
        # Map header names to column indices (case-insensitive)
        # Clean up headers by removing "Column X" prefix and trimming spaces
        for idx, header in enumerate(header_row):
            # Remove "Column X" prefix (e.g., "Column 2 Email Address" → "Email Address")
            header_clean = header.strip()
            if header_clean.startswith('Column '):
                # Split by space and remove first two words if they match "Column X"
                parts = header_clean.split(' ', 2)
                if len(parts) >= 3 and parts[0].lower() == 'column' and parts[1].isdigit():
                    header_clean = parts[2]
            
            # Convert to lowercase for matching
            header_clean = header_clean.strip().lower()
            column_mapping[header_clean] = idx
        
        print(f"   ✓ Detected {len(header_row)} columns in sheet")
        
        # Define required columns and their possible names
        required_columns = {
            'email': ['email address', 'email', 'r_ldap email'],
            'task_link': ['task link', 'task url', 'url', 'link'],
            'job_name': ['job short name', 'job name', 'job'],
            'sr_ldap': ['sr ldap', 'sr_ldap'],
            'team_lead_ldap': ['team lead ldap', 'team_lead_ldap', 'tl ldap'],
            'reasoning': ['explain: reasoning', 'reasoning', 'reviewer\'s justification', 'justification'],
            'status': ['status', 'scrape status']
        }
        
        # Find column indices for required fields
        col_indices = {}
        for field, possible_names in required_columns.items():
            for name in possible_names:
                if name.lower() in column_mapping:
                    col_indices[field] = column_mapping[name.lower()]
                    print(f"   ✓ Found '{field}' column at index {col_indices[field]} ('{header_row[col_indices[field]]}')")
                    break
        
        # Check if Status column exists, if not, create it
        if 'status' not in col_indices:
            print(f"   ⚠️  'Status' column not found - adding it to the sheet...")
            try:
                # Add "Status" header to the end of header row
                status_col_idx = len(header_row)
                sheet.update_cell(1, status_col_idx + 1, "Status")  # 1-based index
                col_indices['status'] = status_col_idx
                print(f"   ✓ Added 'Status' column at index {status_col_idx}")
            except Exception as e:
                print(f"   ❌ Failed to add Status column: {str(e)}")
                print(f"   ⚠️  Continuing without status updates...")
        
        # Validate required columns exist (except status, which we just added)
        missing_columns = []
        for field in ['email', 'task_link']:
            if field not in col_indices:
                missing_columns.append(field)
        
        if missing_columns:
            # Show cleaned header names for debugging
            cleaned_headers = []
            for h in header_row:
                h_clean = h.strip()
                if h_clean.startswith('Column '):
                    parts = h_clean.split(' ', 2)
                    if len(parts) >= 3 and parts[0].lower() == 'column' and parts[1].isdigit():
                        h_clean = parts[2]
                cleaned_headers.append(h_clean.strip())
            
            raise Exception(
                f"❌ Missing required columns: {', '.join(missing_columns)}\n"
                f"   Available columns (cleaned): {', '.join(cleaned_headers)}\n"
                f"   Please ensure the sheet has the correct headers."
            )
        
        # Store column indices for status updates (1-based for gspread)
        if 'status' in col_indices:
            self.status_col_index = col_indices['status'] + 1  # Convert to 1-based
        else:
            # If status column wasn't found/created, disable status updates
            self.status_col_index = None
            print(f"   ⚠️  Status updates disabled (column not available)")
        
        # Parse data (skip header row)
        tasks_data = []
        skipped_count = 0
        
        for row_idx, row in enumerate(all_rows[1:], start=2):
            try:
                status = row[col_indices['status']].strip() if len(row) > col_indices['status'] else ""
                task_link = row[col_indices['task_link']].strip() if len(row) > col_indices['task_link'] else ""
                
                # Skip if status is "Scraped" or "Error"
                if status.lower() in ['scraped', 'error']:
                    skipped_count += 1
                    continue
                
                # Only process rows with valid task links
                if task_link and task_link.startswith('http'):
                    r_ldap_email = row[col_indices['email']].strip() if len(row) > col_indices['email'] else ""
                    job_short_name = row[col_indices['job_name']].strip() if 'job_name' in col_indices and len(row) > col_indices['job_name'] else ""
                    sr_ldap = row[col_indices['sr_ldap']].strip() if 'sr_ldap' in col_indices and len(row) > col_indices['sr_ldap'] else ""
                    team_lead_ldap = row[col_indices['team_lead_ldap']].strip() if 'team_lead_ldap' in col_indices and len(row) > col_indices['team_lead_ldap'] else ""
                    reviewers_justification = row[col_indices['reasoning']].strip() if 'reasoning' in col_indices and len(row) > col_indices['reasoning'] else ""
                    
                    # Extract LDAP from email (part before @)
                    r_ldap = r_ldap_email.split('@')[0] if '@' in r_ldap_email else r_ldap_email
                    
                    tasks_data.append({
                        'task_link': task_link,
                        'job_short_name': job_short_name,
                        'reviewers_justification': reviewers_justification,
                        'r_ldap': r_ldap,
                        'sr_ldap': sr_ldap,
                        'row_number': row_idx  # Store row number for status updates
                    })
            except IndexError:
                print(f"   ⚠️  Warning: Row {row_idx} has missing columns, skipping...")
                continue
        
        print(f"   ✓ Found {len(tasks_data)} task(s) ready to scrape")
        if skipped_count > 0:
            print(f"   ⏭️  Skipped {skipped_count} task(s) (already scraped or error)")
        
        if not tasks_data:
            if skipped_count > 0:
                raise Exception(
                    f"❌ No new tasks to scrape!\n"
                    f"   All {skipped_count} task(s) have already been processed."
                )
            else:
                raise Exception(
                    f"❌ No valid URLs found in column C!\n"
                    f"   Make sure the sheet has URLs starting with 'http' in column C"
                )
        
        return tasks_data
    
    def update_task_status_in_tab(self, spreadsheet_id, sheet_name, row_number, status):
        """
        Update the status of a task in a specific tab/sheet
        
        Args:
            spreadsheet_id: ID of the spreadsheet
            sheet_name: Name of the tab/sheet
            row_number: Row number in the sheet (1-based index)
            status: Status to set (e.g., "Scraped", "Error", "Processing")
        """
        try:
            if not self.client:
                self.authenticate()
            
            spreadsheet = self.client.open_by_key(spreadsheet_id)
            sheet = spreadsheet.worksheet(sheet_name)
            
            # Update column B (status column) with the status
            sheet.update_cell(row_number, 2, status)
            return True
        except Exception as e:
            print(f"   ⚠️  Failed to update status for row {row_number} in {sheet_name}: {str(e)}")
            return False
    
    def get_or_create_subfolder(self, main_folder_id, subfolder_name):
        """
        Get or create a subfolder within the main Drive folder
        Returns the subfolder ID
        """
        if not self.drive_service:
            self.authenticate()
        
        try:
            # Search for existing subfolder
            query = f"name='{subfolder_name}' and '{main_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
            results = self.drive_service.files().list(
                q=query,
                fields="files(id, name)",
                spaces='drive',
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute()
            
            files = results.get('files', [])
            
            if files:
                # Subfolder exists
                print(f"   ✓ Found existing subfolder: {subfolder_name}")
                return files[0]['id']
            else:
                # Create new subfolder
                print(f"   📁 Creating subfolder: {subfolder_name}")
                file_metadata = {
                    'name': subfolder_name,
                    'mimeType': 'application/vnd.google-apps.folder',
                    'parents': [main_folder_id]
                }
                folder = self.drive_service.files().create(
                    body=file_metadata,
                    fields='id',
                    supportsAllDrives=True
                ).execute()
                print(f"   ✓ Created subfolder: {subfolder_name}")
                return folder['id']
        except Exception as e:
            print(f"   ⚠️  Error with subfolder: {str(e)}")
            return None
    
    def upload_html_to_drive(self, html_content, file_name, folder_id):
        """
        Upload HTML content to Google Drive
        Returns the file ID
        """
        if not self.drive_service:
            self.authenticate()
        
        try:
            file_metadata = {
                'name': file_name,
                'parents': [folder_id],
                'mimeType': 'text/html'
            }
            
            media = MediaInMemoryUpload(
                html_content.encode('utf-8'),
                mimetype='text/html',
                resumable=True
            )
            
            file = self.drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink',
                supportsAllDrives=True  # Support for Shared Drives
            ).execute()
            
            file_id = file.get('id')
            web_link = file.get('webViewLink')
            
            print(f"   ✓ Uploaded: {file_name}")
            print(f"   🔗 Drive Link: {web_link}")
            
            return file_id
        except Exception as e:
            print(f"   ❌ Error uploading to Drive: {str(e)}")
            print(f"   💡 Make sure the Drive folder is shared with the service account email")
            print(f"   💡 Or use a Shared Drive instead of My Drive")
            return None
    
    def update_task_status(self, row_number, status):
        """
        Update the status of a task in the input sheet (Test Disagreement Sheet)
        
        Args:
            row_number: Row number in the sheet (1-based index)
            status: Status to set (e.g., "Scraped", "Error", "Processing")
        """
        try:
            if not hasattr(self, 'input_sheet'):
                print(f"   ⚠️  Cannot update status: Sheet reference not available")
                return False
            
            if not hasattr(self, 'status_col_index'):
                print(f"   ⚠️  Cannot update status: Status column not identified")
                return False
            
            # Update the status column with the dynamic column index
            self.input_sheet.update_cell(row_number, self.status_col_index, status)
            return True
        except Exception as e:
            print(f"   ⚠️  Failed to update status for row {row_number}: {str(e)}")
            return False
    
    def save_to_sheet(self, results, spreadsheet_id, fixed_checks, tab_name=None):
        """
        Save results to output Google Sheet (appends to existing data)
        If tab_name is provided, saves to that specific tab (creates if doesn't exist)
        """
        if not self.client:
            self.authenticate()
        
        print(f"\n📊 Connecting to Google Sheets...")
        
        try:
            spreadsheet = self.client.open_by_key(spreadsheet_id)
            
            # Get or create the specified tab
            if tab_name:
                try:
                    sheet = spreadsheet.worksheet(tab_name)
                    print(f"   ✓ Connected to tab: {tab_name}")
                except gspread.exceptions.WorksheetNotFound:
                    print(f"   📝 Creating new tab: {tab_name}")
                    sheet = spreadsheet.add_worksheet(title=tab_name, rows=1000, cols=50)
            else:
                sheet = spreadsheet.sheet1
            
            print(f"   ✓ Connected to: {spreadsheet.title}")
            
            # Build header with new structure (SR checks only for PKT tool)
            header = [
                'Task_Id',          # Column A
                'Status',           # Column B
                'Report_ID',        # Column C
                'Task Link',        # Column D
                'Feedback_Hub_Link' # Column E
            ]
            
            # Add check columns (without SR_ prefix)
            for check in fixed_checks:
                header.append(check)
            
            header.append('Error')
            
            # Check if sheet is empty or needs header
            existing_data = sheet.get_all_values()
            if not existing_data or len(existing_data) == 0:
                # Sheet is empty, write header first
                print(f"   📝 Sheet is empty, adding header row...")
                sheet.update('A1', [header])
                next_row = 2
            elif existing_data[0] != header:
                # Header exists but doesn't match, clear and rewrite everything
                print(f"   ⚠️  Header mismatch detected, clearing sheet...")
                sheet.clear()
                rows = [header]
                # We'll add new data below
                next_row = 2
            else:
                # Header exists and matches, just append data
                next_row = len(existing_data) + 1
                print(f"   ✓ Found existing data ({len(existing_data) - 1} rows), appending new data...")
            
            # Prepare rows (only data, no header)
            rows = []
            
            # Write data - one row per task
            for task in results:
                row = [
                    task.get('task_id', ''),              # Column A
                    task.get('status', ''),               # Column B - blank by default
                    task.get('report_id', ''),            # Column C
                    task.get('input_url', ''),            # Column D
                    task.get('feedback_hub_link', '')     # Column E
                ]
                
                # Create dictionary for SR checks only (PKT tool)
                senior_reviewer_data = {}
                
                if task.get('decisions'):
                    for decision in task['decisions']:
                        role = decision['role']
                        checks = decision['checks']
                        
                        # Build check data dictionary for Senior Reviewer
                        check_dict = {}
                        for check in checks:
                            check_name = check['check_name']
                            
                            # Format as JSON: {"codes": ["code1", "code2"], "text": "text value"}
                            import json
                            value_dict = {
                                'codes': check['codes'] if check['codes'] else [],
                                'text': check['text'] if check['text'] else ''
                            }
                            value = json.dumps(value_dict, ensure_ascii=False)
                            
                            check_dict[check_name] = value
                        
                        # Only process Senior Reviewer data
                        if 'senior' in role.lower() or 'sr' in role.lower():
                            senior_reviewer_data = check_dict
                
                # Add Senior Reviewer (SR_) check values in order
                for check_name in fixed_checks:
                    row.append(senior_reviewer_data.get(check_name, ''))
                
                # Add error column
                row.append(task.get('error', ''))
                
                rows.append(row)
            
            # Write new rows starting from next_row
            if rows:
                start_cell = f'A{next_row}'
                
                # If we cleared the sheet, we need to write header first
                if next_row == 2 and (not existing_data or len(existing_data) == 0 or existing_data[0] != header):
                    sheet.update('A1', [header] + rows)
                else:
                    # Just append the data rows
                    sheet.update(start_cell, rows)
                
                print(f"✅ Successfully added {len(results)} new task(s) to Google Sheets!")
            else:
                print(f"   ℹ️  No new data to add")
            
            # Format header row (bold, gray background) if it was just added
            if next_row == 2 or not existing_data:
                def col_to_letter(col_num):
                    """Convert column number (0-based) to Excel-style letter"""
                    result = ""
                    col_num += 1
                    while col_num > 0:
                        col_num -= 1
                        result = chr(65 + (col_num % 26)) + result
                        col_num //= 26
                    return result
                
                last_col = col_to_letter(len(header) - 1)
                header_range = f'A1:{last_col}1'
                sheet.format(header_range, {
                    'textFormat': {'bold': True},
                    'backgroundColor': {'red': 0.9, 'green': 0.9, 'blue': 0.9}
                })
                
                # Auto-resize columns
                sheet.columns_auto_resize(0, len(header) - 1)
            
            print(f"📊 View here: https://docs.google.com/spreadsheets/d/{spreadsheet_id}")
            
        except Exception as e:
            print(f"❌ Error saving to Google Sheets: {str(e)}")
            print(f"   Data is still saved to CSV/JSON files")
    
    def save_feedback_hub_data(self, results, spreadsheet_id, tab_name=None, drive_main_folder_id=None):
        """
        Save Feedback Hub data (prompt, response, images) to a separate sheet
        If tab_name is provided, saves to that specific tab (creates if doesn't exist)
        If drive_main_folder_id is provided, uploads screen captures to Drive
        """
        if not self.client:
            self.authenticate()
        
        print(f"\n📊 Saving Feedback Hub data to Google Sheets...")
        
        try:
            spreadsheet = self.client.open_by_key(spreadsheet_id)
            
            # Get or create the specified tab
            if tab_name:
                try:
                    sheet = spreadsheet.worksheet(tab_name)
                    print(f"   ✓ Connected to tab: {tab_name}")
                except gspread.exceptions.WorksheetNotFound:
                    print(f"   📝 Creating new tab: {tab_name}")
                    sheet = spreadsheet.add_worksheet(title=tab_name, rows=1000, cols=50)
            else:
                sheet = spreadsheet.sheet1
            
            print(f"   ✓ Connected to: {spreadsheet.title}")
            
            # Build header for Feedback Hub data (removed Task_Link, Feedback_Hub_Link, and Report_ID)
            header = [
                'Task_ID',                  # Column A
                'Status',                   # Column B
                'Date_Submitted',           # Column C
                'Country',                  # Column D
                'Language',                 # Column E
                'Search_Link',              # Column F
                'Feature_Tag',              # Column G
                'Additional_Feature_Tags',  # Column H
                'Reported_Value',           # Column I (NEW)
                'Fanout_Queries',           # Column J
                'From_Cache',               # Column K
                'Prompts',                  # Column L - JSON array
                'Interpretations',          # Column M - JSON array
                'Responses',                # Column N - JSON array
                'Response_Images',          # Column O - JSON array
                'Corroboration',            # Column P
                'User_Sentiment',           # Column Q
                'Issue_Type',               # Column R
                'Feedback_Comment',         # Column S
                'Screen_Capture_Drive_ID',  # Column T
                'Error'                     # Column U
            ]
            
            # Check if sheet is empty or needs header
            existing_data = sheet.get_all_values()
            if not existing_data or len(existing_data) == 0:
                print(f"   📝 Sheet is empty, adding header row...")
                sheet.update('A1', [header])
                next_row = 2
            elif existing_data[0] != header:
                print(f"   ⚠️  Header mismatch detected, clearing sheet...")
                sheet.clear()
                sheet.update('A1', [header])
                next_row = 2
            else:
                next_row = len(existing_data) + 1
                print(f"   ✓ Found existing data ({len(existing_data) - 1} rows), appending new data...")
            
            # Prepare rows
            rows = []
            
            for task in results:
                feedback_data = task.get('feedback_hub_data')
                
                # Initialize all fields
                status = "Ready"  # Default to Ready
                date_submitted = ""
                country = ""
                language = ""
                search_link = ""
                feature_tag = ""
                additional_feature_tags = ""
                reported_value = ""
                fanout_queries = ""
                from_cache = ""
                prompts_json = ""
                interpretations_json = ""
                responses_json = ""
                response_images_json = ""
                corroboration = ""
                user_sentiment = ""
                issue_type = ""
                feedback_comment = ""
                screen_capture_drive_id = ""
                error_msg = task.get('error', '')
                missing_fields = []  # Initialize missing_fields list here
                
                if feedback_data:
                    # Extract metadata
                    date_submitted = feedback_data.get('datetime', '')
                    country = feedback_data.get('country', '')
                    language = feedback_data.get('language', '')
                    search_link = feedback_data.get('search_link', '')
                    feature_tag = feedback_data.get('feature_tag', '')
                    additional_feature_tags = feedback_data.get('additional_feature_tags', '')
                    reported_value = feedback_data.get('reported_value', '')
                    fanout_queries = feedback_data.get('fanout_queries', '')
                    from_cache = feedback_data.get('from_cache', '')
                    
                    # Extract multi-turn conversation data and format as JSON with numbered keys
                    import json
                    conv_turns = feedback_data.get('conversation_turns', [])
                    
                    if conv_turns:
                        # Create dictionaries with numbered keys
                        prompts_dict = {}
                        interpretations_dict = {}
                        responses_dict = {}
                        images_dict = {}
                        
                        for idx, turn in enumerate(conv_turns, start=1):
                            prompts_dict[f'prompt{idx}'] = turn.get('prompt', '')
                            interpretations_dict[f'interpretation{idx}'] = turn.get('prompt_interpretation', '')
                            responses_dict[f'response{idx}'] = turn.get('response', '')
                            
                            # Handle response images for this turn
                            turn_images = []
                            if turn.get('response_image_urls'):
                                turn_images = turn['response_image_urls']
                            elif turn.get('response_image_url'):
                                turn_images = [turn['response_image_url']]
                            
                            if turn_images:
                                for img_idx, img_url in enumerate(turn_images, start=1):
                                    images_dict[f'image{idx}.{img_idx}'] = img_url
                        
                        # Convert to JSON strings with size limits (Google Sheets has 50K char limit)
                        MAX_CELL_SIZE = 45000  # Leave some buffer
                        
                        prompts_json = json.dumps(prompts_dict, ensure_ascii=False)
                        interpretations_json = json.dumps(interpretations_dict, ensure_ascii=False)
                        responses_json = json.dumps(responses_dict, ensure_ascii=False)
                        response_images_json = json.dumps(images_dict, ensure_ascii=False) if images_dict else ""
                        
                        # Truncate if too large
                        if len(prompts_json) > MAX_CELL_SIZE:
                            prompts_json = prompts_json[:MAX_CELL_SIZE] + '... [TRUNCATED]'
                            print(f"   ⚠️  Prompts JSON truncated (original size: {len(prompts_json)} chars)")
                        if len(interpretations_json) > MAX_CELL_SIZE:
                            interpretations_json = interpretations_json[:MAX_CELL_SIZE] + '... [TRUNCATED]'
                            print(f"   ⚠️  Interpretations JSON truncated")
                        if len(responses_json) > MAX_CELL_SIZE:
                            responses_json = responses_json[:MAX_CELL_SIZE] + '... [TRUNCATED]'
                            print(f"   ⚠️  Responses JSON truncated (original size: {len(responses_json)} chars)")
                        if len(response_images_json) > MAX_CELL_SIZE:
                            response_images_json = response_images_json[:MAX_CELL_SIZE] + '... [TRUNCATED]'
                            print(f"   ⚠️  Response images JSON truncated")
                    else:
                        # Fallback to single turn data with numbered keys
                        prompt = feedback_data.get('user_prompt', '')
                        interpretation = feedback_data.get('prompt_interpretation', '')
                        response = feedback_data.get('ai_response', '')
                        response_image = feedback_data.get('response_image_url', '')
                        
                        if prompt or response:
                            prompts_json = json.dumps({'prompt1': prompt}, ensure_ascii=False)
                            interpretations_json = json.dumps({'interpretation1': interpretation}, ensure_ascii=False)
                            responses_json = json.dumps({'response1': response}, ensure_ascii=False)
                            
                            if response_image:
                                response_images_json = json.dumps({'image1.1': response_image}, ensure_ascii=False)
                            else:
                                response_images_json = ""
                    
                    # Extract corroboration (with size limit)
                    corroboration = feedback_data.get('corroboration', '')
                    if len(corroboration) > 45000:
                        corroboration = corroboration[:45000] + '... [TRUNCATED]'
                        print(f"   ⚠️  Corroboration truncated")
                    
                    # Extract user feedback (with size limit)
                    user_feedback = feedback_data.get('user_feedback', {})
                    if user_feedback:
                        user_sentiment = user_feedback.get('sentiment', '')
                        issue_type = user_feedback.get('issue_type', '')
                        feedback_comment = user_feedback.get('comment', '')
                        if len(feedback_comment) > 45000:
                            feedback_comment = feedback_comment[:45000] + '... [TRUNCATED]'
                            print(f"   ⚠️  Feedback comment truncated")
                    
                    # Check for screen capture and upload to Drive
                    screen_capture_html = feedback_data.get('screen_capture_html', '')
                    if screen_capture_html and drive_main_folder_id:
                        # Get check category for subfolder
                        check_category = task.get('check_category', 'Others')
                        
                        # Get or create subfolder
                        subfolder_id = self.get_or_create_subfolder(drive_main_folder_id, check_category)
                        
                        if subfolder_id:
                            # Upload HTML file
                            task_id = task.get('task_id', 'unknown')
                            file_name = f"{task_id}_screen_capture.html"
                            
                            print(f"   📤 Uploading screen capture to Drive...")
                            file_id = self.upload_html_to_drive(screen_capture_html, file_name, subfolder_id)
                            
                            if file_id:
                                screen_capture_drive_id = file_id
                            else:
                                # Upload failed but we have HTML - still mark as Ready
                                screen_capture_drive_id = "UPLOAD_FAILED"
                                print(f"   ⚠️  Drive upload failed, but screen capture HTML was captured")
                        else:
                            screen_capture_drive_id = "FOLDER_ERROR"
                            print(f"   ⚠️  Could not create Drive subfolder, but screen capture HTML was captured")
                    elif screen_capture_html:
                        # HTML exists but no Drive upload requested
                        screen_capture_drive_id = "HTML_CAPTURED"
                    
                    # Validate all required data is present for "Ready" status
                    # Only check essential fields: prompts, responses, and screen capture HTML
                    validation_missing_fields = []
                    if not prompts_json:
                        validation_missing_fields.append('Prompts')
                    if not responses_json:
                        validation_missing_fields.append('Responses')
                    if not screen_capture_html:
                        validation_missing_fields.append('Screen Capture')
                    
                    # Set status based on validation (ignore Drive upload failures)
                    if validation_missing_fields:
                        status = "Error"
                        error_msg = f"Missing data: {', '.join(validation_missing_fields)}"
                    else:
                        # All essential data present - mark as Ready even if Drive upload failed
                        status = "Ready"
                else:
                    # No feedback data at all
                    status = "Error"
                    if not error_msg:
                        error_msg = "Failed to extract Feedback Hub data"
                
                # Build the row with new column order (without Report_ID)
                row = [
                    task.get('task_id', ''),              # Task_ID
                    status,                                # Status (Ready or Error)
                    date_submitted,                        # Date_Submitted
                    country,                               # Country
                    language,                              # Language
                    search_link,                           # Search_Link
                    feature_tag,                           # Feature_Tag
                    additional_feature_tags,               # Additional_Feature_Tags
                    reported_value,                        # Reported_Value (NEW - Column I)
                    fanout_queries,                        # Fanout_Queries
                    from_cache,                            # From_Cache
                    prompts_json,                          # Prompts (JSON array)
                    interpretations_json,                  # Interpretations (JSON array)
                    responses_json,                        # Responses (JSON array)
                    response_images_json,                  # Response_Images (JSON array)
                    corroboration,                         # Corroboration
                    user_sentiment,                        # User_Sentiment
                    issue_type,                            # Issue_Type
                    feedback_comment,                      # Feedback_Comment
                    screen_capture_drive_id,               # Screen_Capture_Drive_ID
                    error_msg                              # Error
                ]
                
                rows.append(row)
            
            # Write rows
            if rows:
                start_cell = f'A{next_row}'
                sheet.update(start_cell, rows)
                print(f"✅ Successfully added {len(results)} task(s) to Feedback Hub sheet!")
            else:
                print(f"   ℹ️  No new data to add")
            
            # Format header row if just added
            if next_row == 2 or not existing_data:
                def col_to_letter(col_num):
                    result = ""
                    col_num += 1
                    while col_num > 0:
                        col_num -= 1
                        result = chr(65 + (col_num % 26)) + result
                        col_num //= 26
                    return result
                
                last_col = col_to_letter(len(header) - 1)
                header_range = f'A1:{last_col}1'
                sheet.format(header_range, {
                    'textFormat': {'bold': True},
                    'backgroundColor': {'red': 0.9, 'green': 0.9, 'blue': 0.9}
                })
                sheet.columns_auto_resize(0, len(header) - 1)
            
            print(f"📊 View here: https://docs.google.com/spreadsheets/d/{spreadsheet_id}")
            
        except Exception as e:
            print(f"❌ Error saving Feedback Hub data: {str(e)}")
