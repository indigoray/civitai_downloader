import os
import sys
import requests
import json
import argparse
import urllib.parse
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
from bs4 import BeautifulSoup
import time
import random
import signal
from datetime import datetime, timezone
import glob

def signal_handler(sig, frame):
    print("\nCtrl+C pressed. Exiting immediately...")
    os._exit(0)

signal.signal(signal.SIGINT, signal_handler)

# Configuration
# Add your target users here (Username, URL, or ID)
TARGET_USERS = [
    # "ExampleUser",
    "freckledvixon",
    "Steelhaze",
]

# Date filter configuration (YYYY-MM or YYYY-MM-DD)
# Files created BEFORE this date will be deleted.
BEFORE_DATE = "2025-01" 

def get_user_id(username):
    """
    Scrapes the user profile page to find the internal User ID.
    Same logic as downloader.
    """
    url = f"https://civitai.com/user/{username}"
    # print(f"Resolving User ID for {username} from {url}...")
    
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        script_tag = soup.find('script', id='__NEXT_DATA__')
        
        if not script_tag:
            print("Error: Could not find __NEXT_DATA__ on profile page.")
            return None
            
        data = json.loads(script_tag.string)
        
        queries = data.get('props', {}).get('pageProps', {}).get('trpcState', {}).get('json', {}).get('queries', [])
        for query in queries:
            state = query.get('state', {})
            data_val = state.get('data', {})
            if isinstance(data_val, dict):
                if data_val.get('username', '').lower() == username.lower():
                    return data_val.get('id')
                    
        return None

    except Exception as e:
        print(f"Error resolving User ID: {e}")
        return None

def parse_date(date_str):
    """
    Parses a date string in 'YYYY-MM' or 'YYYY-MM-DD' format.
    Returns a timezone-aware datetime object (UTC).
    """
    if not date_str:
        return None
    try:
        if len(date_str.split('-')) == 2:
            # Format: YYYY-MM -> Default to 1st of the month
            dt = datetime.strptime(date_str, "%Y-%m")
        else:
            # Format: YYYY-MM-DD
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        print(f"Invalid date format: {date_str}. Use YYYY-MM or YYYY-MM-DD.")
        return None

def get_images_metadata(user_id, api_key, before_date):
    """
    Fetches image metadata and returns items OLDER than before_date.
    """
    # TRPC Endpoint
    base_url = "https://civitai.com/api/trpc/image.getInfinite"
    images_to_delete = []
    cursor = None
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    total_items_scanned = 0
    
    # We need to scan everything to find old items, or can we stop?
    # Since it's sorted by Newest, old items are at the end.
    # So we have to paginate until we hit the date, and THEN everything after that is old.
    # Wait, user wants to delete items BEFORE the date.
    # Newest -> Oldest.
    # 2025-05 (New) ... 2025-04 (Target) ... 2024 (Old)
    # We want to delete 2024.
    # So we skip items >= before_date.
    # Once we hit items < before_date, we collect them AND everything after them.
    
    with tqdm(desc=f"Scanning Metadata {user_id}", unit="page", leave=False) as pbar:
        while True:
            # Construct TRPC Input
            input_data = {
                "json": {
                    "userId": user_id,
                    "sort": "Newest",
                    "limit": 100,
                }
            }
            if cursor:
                input_data["json"]["cursor"] = cursor
            
            encoded_input = urllib.parse.quote(json.dumps(input_data))
            url = f"{base_url}?input={encoded_input}"
                
            # Retry loop for 5xx errors
            max_retries = 5
            for attempt in range(max_retries):
                try:
                    time.sleep(random.uniform(0.1, 0.3))
                    response = requests.get(url, headers=headers, timeout=30)
                    
                    if 500 <= response.status_code < 600:
                        time.sleep((attempt + 1) * 2)
                        continue
                        
                    response.raise_for_status()
                    data = response.json()
                    break 
                except Exception as e:
                    if attempt == max_retries - 1:
                        tqdm.write(f"Failed to fetch metadata: {e}")
                        return images_to_delete
                    time.sleep((attempt + 1) * 2)
            
            result_data = data.get('result', {}).get('data', {}).get('json', {})
            batch = result_data.get('items', [])
            total_items_scanned += len(batch)
            
            for img in batch:
                created_at_str = img.get('createdAt')
                if created_at_str:
                    try:
                        created_at_str = created_at_str.replace('Z', '+00:00')
                        created_at = datetime.fromisoformat(created_at_str)
                        
                        if created_at < before_date:
                            images_to_delete.append(img)
                    except ValueError:
                        pass 

            pbar.update(1)
            
            cursor = result_data.get('nextCursor')
            if not cursor:
                break
                
    return images_to_delete

def process_user_deletion(user_input, api_key, before_date):
    user_id = None
    username = None
    
    if 'civitai.com/user/' in user_input:
        try:
            path_parts = urlparse(user_input).path.split('/')
            user_index = path_parts.index('user')
            username = path_parts[user_index + 1]
            user_id = get_user_id(username)
        except:
            print(f"[{user_input}] Invalid URL.")
            return
    elif user_input.isdigit():
        user_id = int(user_input)
        username = f"User_{user_id}"
    else:
        username = user_input
        user_id = get_user_id(username)
        
    if not user_id:
        print(f"[{user_input}] Failed to resolve User ID.")
        return

    print(f"[{username}] Scanning for files created before {before_date.date()}...")
    
    items_to_delete = get_images_metadata(user_id, api_key, before_date)
    
    if not items_to_delete:
        print(f"[{username}] No items found older than {before_date.date()}.")
        return

    print(f"[{username}] Found {len(items_to_delete)} items to check for deletion.")
    
    output_dir = os.path.join("downloads", username)
    if not os.path.exists(output_dir):
        print(f"[{username}] Directory not found: {output_dir}")
        return

    deleted_count = 0
    
    for item in tqdm(items_to_delete, desc=f"Deleting {username}", unit="file"):
        img_id = item.get('id')
        # Find local files matching ID
        search_pattern = os.path.join(output_dir, f"*_{img_id}.*")
        matches = glob.glob(search_pattern)
        
        for filepath in matches:
            try:
                os.remove(filepath)
                # tqdm.write(f"Deleted: {os.path.basename(filepath)}")
                deleted_count += 1
            except OSError as e:
                tqdm.write(f"Error deleting {filepath}: {e}")
                
    print(f"[{username}] Deleted {deleted_count} files.")

def main():
    parser = argparse.ArgumentParser(description="Civitai File Deleter")
    parser.add_argument("users", nargs='*', help="List of Civitai User URLs, Usernames, or IDs")
    parser.add_argument("--key", help="Civitai API Key", default=None)
    parser.add_argument("--before", help="Delete files created BEFORE this date (YYYY-MM or YYYY-MM-DD)", default=None)
    
    args = parser.parse_args()
    
    before_date = parse_date(args.before)
    if not before_date:
        # Fallback to constant if not provided arg
        before_date = parse_date(BEFORE_DATE)
        
    if not before_date:
        print("Please specify a date using --before or set BEFORE_DATE in the script.")
        return
    
    api_key = args.key
    if not api_key:
        api_key = "38099a6de2b076f6b879dd08e233be6b" 
    
    users = args.users
    if not users:
        users = TARGET_USERS
        
    if not users:
        print("No users specified.")
        return
        
    print(f"Target Date: {before_date.date()} (Files older than this will be DELETED)")
    print(f"Target Users: {len(users)}")
    
    # Sequential processing for safety/clarity
    for user in users:
        process_user_deletion(user, api_key, before_date)

if __name__ == "__main__":
    main()
