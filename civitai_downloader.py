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

def signal_handler(sig, frame):
    print("\nCtrl+C pressed. Exiting immediately...")
    os._exit(0)

signal.signal(signal.SIGINT, signal_handler)

def get_user_id(username):
    """
    Resolves User ID via API first, then falls back to scraping.
    """
    url = f"https://civitai.com/user/{username}"
    print(f"Resolving User ID for {username}...")
    
    # Attempt 1: API (user.getCreator) - Most reliable for ID
    try:
        # We don't need authentication for this public query usually, but using scraped page relies on auth context sometimes
        api_url = f"https://civitai.com/api/trpc/user.getCreator?input=%7B%22json%22%3A%7B%22username%22%3A%22{username}%22%7D%7D"
        resp = requests.get(api_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            user_data = data.get('result', {}).get('data', {}).get('json', {})
            if user_data.get('id'):
                # Check if it's the "old" ID or "new" ID?
                # Actually API returns the ID linked to username.
                # If username matches, it's correct.
                # Note: For 'athrowaway7894561633', API returned 1131131 but posts suggest 2463719.
                # However, the scraping also returned 1131131.
                # The browser found 2463719.
                # Let's trust the API for now, but if it fails to find posts, maybe we need the other one.
                # But wait, our repro script showed:
                # API (getCreator) -> 1131131
                # Posts for 1131131 -> Empty?
                # Posts for 2463719 -> Full.
                # This suggests 1131131 is the "Creator" ID but 2463719 might be the "Account" ID or vice versa?
                # Or maybe one is deprecated.
                # Let's stick to the scraping method which can find strict matches, 
                # OR we implement the recursive search from repro script.
                pass
    except:
        pass

    # Fallback to scraping which we know how to do, but improved
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        response.raise_for_status()
        
        # Check text directly for known pattern if possible? No.
        
        soup = BeautifulSoup(response.text, 'html.parser')
        script_tag = soup.find('script', id='__NEXT_DATA__')
        
        if not script_tag:
            print("Error: Could not find __NEXT_DATA__ on profile page.")
            return None
            
        data = json.loads(script_tag.string)
        
        # Recursive search for ID associated with username
        def find_id_recursive(obj, target_username):
            if isinstance(obj, dict):
                if 'username' in obj and isinstance(obj['username'], str) and obj['username'].lower() == target_username.lower():
                    if 'id' in obj:
                        return obj['id']
                for key, value in obj.items():
                    res = find_id_recursive(value, target_username)
                    if res:
                        return res
            elif isinstance(obj, list):
                for item in obj:
                    res = find_id_recursive(item, target_username)
                    if res:
                        return res
            return None

        found_id = find_id_recursive(data, username)
        if found_id:
             return found_id
             
        # Previous logic backups
        queries = data.get('props', {}).get('pageProps', {}).get('trpcState', {}).get('json', {}).get('queries', [])
        for query in queries:
            state = query.get('state', {})
            data_val = state.get('data', {})
            if isinstance(data_val, dict):
                if data_val.get('username', '').lower() == username.lower():
                    return data_val.get('id')
                    
        print("Could not locate User ID in __NEXT_DATA__.")
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

    return list(all_items.values())

def get_images(user_identifier, api_key, position=0, after_date=None, is_username=False):
    """
    Fetches all image metadata from the API using TRPC.
    If is_username is True, queries by username. Otherwise by userId.
    """
    # TRPC Endpoint
    base_url = "https://civitai.com/api/trpc/image.getInfinite"
    images = []
    cursor = None
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    total_items_scanned = 0
    
    with tqdm(desc=f"Fetching Metadata {user_identifier}", unit="page", position=position, leave=False) as pbar:
        while True:
            # Construct TRPC Input
            json_params = {
                "sort": "Newest",
                "limit": 100,
                "browsingLevel": 31
            }
            if is_username:
                json_params["username"] = user_identifier
            else:
                json_params["userId"] = int(user_identifier)
                
            if cursor:
                json_params["cursor"] = cursor
                
            input_data = {"json": json_params}
            
            encoded_input = urllib.parse.quote(json.dumps(input_data))
            url = f"{base_url}?input={encoded_input}"
                
            # Retry loop for 5xx errors
            max_retries = 5
            for attempt in range(max_retries):
                try:
                    time.sleep(random.uniform(0.1, 0.3))
                    response = requests.get(url, headers=headers, timeout=30)
                    if 500 <= response.status_code < 600:
                        wait_time = (attempt + 1) * 5
                        time.sleep(wait_time)
                        continue
                    response.raise_for_status()
                    data = response.json()
                    break 
                except requests.exceptions.RequestException as e:
                    if attempt < max_retries - 1:
                        if "500" in str(e) or "502" in str(e) or "503" in str(e) or "504" in str(e):
                            time.sleep((attempt + 1) * 5)
                            continue
                    tqdm.write(f"API Request failed: {e}")
            else:
                tqdm.write(f"Failed to fetch metadata after {max_retries} attempts.")
                break

            result_data = data.get('result', {}).get('data', {}).get('json', {})
            batch = result_data.get('items', [])
            total_items_scanned += len(batch)
            
            # Filter matches strict user ownership
            filtered_batch_ownership = []
            
            # We need to know who we are looking for.
            # If we queried by username, use that.
            # If by ID, use passed ID.
            
            for img in batch:
                # Relaxed Ownership Check
                # If queried by username, we assume the API returns correct items generally, 
                # but we can check if 'username' field matches if present.
                # The debug script showed items with UserId: None but correct content.
                
                # Check User ID mismatch ONLY if both are present and non-None
                img_user_id = img.get('userId')
                
                if not is_username:
                    # Query by ID: strict check if ID exists
                    if img_user_id is not None and img_user_id != user_identifier:
                        continue
                else:
                    # Query by Username: Check username mismatch if ID present?
                    # Actually, if query by username works, we might trust it more.
                    # Debug showed items returned by username query had 'None' userId initially but matched.
                    pass 

                # Also check date
                if after_date:
                    created_at_str = img.get('createdAt')
                    if created_at_str:
                        try:
                            created_at_str = created_at_str.replace('Z', '+00:00')
                            created_at = datetime.fromisoformat(created_at_str)
                            if created_at < after_date:
                                # Skip this item
                                continue
                        except:
                            pass
                
                filtered_batch_ownership.append(img)

            images.extend(filtered_batch_ownership)
            
            pbar.update(1)
            
            cursor = result_data.get('nextCursor')
            if not cursor:
                break
                
            # Date optimization check
            if after_date and batch:
                last_item = batch[-1]
                last_date_str = last_item.get('createdAt')
                if last_date_str:
                    try:
                        last_date_str = last_date_str.replace('Z', '+00:00')
                        last_date = datetime.fromisoformat(last_date_str)
                        if last_date < after_date:
                            break
                    except:
                        pass
        
    tqdm.write(f"Found {len(images)} images for {user_identifier}.")
    images.sort(key=lambda x: x.get('createdAt', ''), reverse=True)
    return images

def get_posts(user_identifier, api_key, position=0, after_date=None, is_username=False):
    """
    Fetches all posts from the API using TRPC.
    If is_username is True, queries by username.
    """
    base_url = "https://civitai.com/api/trpc/post.getInfinite"
    items = []
    cursor = None
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    total_scanned = 0
    
    with tqdm(desc=f"Fetching Posts {user_identifier}", unit="pg", position=position, leave=False) as pbar:
        while True:
            # Construct TRPC Input
            json_params = {
                "sort": "Newest",
                "limit": 100,
                "browsingLevel": 31
            }
            if is_username:
                json_params["username"] = user_identifier
            else:
                json_params["userId"] = int(user_identifier)
                
            if cursor:
                json_params["cursor"] = cursor
                
            input_data = {"json": json_params}
            
            encoded_input = urllib.parse.quote(json.dumps(input_data))
            url = f"{base_url}?input={encoded_input}"
                
            # Retry loop
            max_retries = 5
            for attempt in range(max_retries):
                try:
                    time.sleep(random.uniform(0.1, 0.3))
                    response = requests.get(url, headers=headers, timeout=30)
                    if 500 <= response.status_code < 600:
                         time.sleep((attempt + 1) * 5)
                         continue
                    response.raise_for_status()
                    data = response.json()
                    break
                except requests.exceptions.RequestException as e:
                    time.sleep((attempt + 1) * 2)
            else:
                break

            result_data = data.get('result', {}).get('data', {}).get('json', {})
            batch = result_data.get('items', [])
            total_scanned += len(batch)
            
            if not batch:
                break
            
            # Extract images from posts
            extracted_items = []
            for post in batch:
                # Strict Ownership Check for Post
                post_user_id = post.get('userId')
                
                # Only filter STRICTLY if we searched by ID and got a different ID
                if not is_username:
                     if post_user_id is not None and post_user_id != user_identifier:
                        continue
                
                # If searching by username, we trust the API (or check username string if needed)

                # Check date
                created_at_str = post.get('createdAt') or post.get('publishedAt')
                if after_date and created_at_str:
                    try:
                        created_at_str = created_at_str.replace('Z', '+00:00')
                        created_at = datetime.fromisoformat(created_at_str)
                        if created_at < after_date:
                            continue 
                    except:
                        pass
                
                # Extract images/videos from 'images' field in post
                post_images = post.get('images', [])
                for img in post_images:
                     # Attach post metadata if useful
                     img['postId'] = post.get('id')
                     img['postDate'] = post.get('createdAt') or post.get('publishedAt')
                     # Inherit createdAt from post if missing in image (usually image has it)
                     if 'createdAt' not in img:
                         img['createdAt'] = img.get('postDate')
                     
                     extracted_items.append(img)
            
            items.extend(extracted_items)
            pbar.update(1)
            
            next_cursor = result_data.get('nextCursor')
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
                
            # Date optimization check
            if after_date and batch:
                 last_post = batch[-1]
                 last_post_date_str = last_post.get('createdAt') or last_post.get('publishedAt')
                 if last_post_date_str:
                     last_post_date_str = last_post_date_str.replace('Z', '+00:00')
                     try:
                         last_date = datetime.fromisoformat(last_post_date_str)
                         if last_date < after_date:
                             break
                     except:
                         pass

    return items

def download_image(img_data, output_dir):
    """
    Downloads a single image.
    """
    try:
        url = img_data.get('url')
        if not url:
            return False
            
        # Check if URL is just a UUID (common in TRPC response)
        if not url.startswith('http'):
            # Construct full URL
            # Base: https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/
            # Format: Base + UUID + /original=true/ + Name
            uuid = url
            name = img_data.get('name')
            if name:
                original_url = f"https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/{uuid}/original=true/{name}"
            else:
                # Fallback if name is missing
                original_url = f"https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/{uuid}/original=true/image.png"
        else:
            if '/width=' in url:
                 # Replace width=... with original=true
                 # Regex or string split
                 parts = url.split('/')
                 new_parts = []
                 for part in parts:
                     if part.startswith('width='):
                         new_parts.append('original=true')
                     else:
                         new_parts.append(part)
                 original_url = "/".join(new_parts)
            else:
                original_url = url

        # Filename
        img_id = img_data.get('id')
        name = img_data.get('name') or f"image_{img_id}"
        
        # Sanitize name
        if name:
             name = "".join([c for c in name if c.isalpha() or c.isdigit() or c in (' ', '-', '_')]).strip()
        if not name:
             name = f"image_{img_id}"
             
        ext = 'png' # Default
        if '.' in url.split('/')[-1]:
             # Handle query params in extension
             ext_part = url.split('/')[-1].split('?')[0]
             if '.' in ext_part:
                 ext = ext_part.split('.')[-1]
                 
        # Special handling for known video types from metadata
        if img_data.get('type') == 'video':
            ext = 'mp4' 
        
        # If url ends with .mp4 etc, use that
        if url.endswith('.mp4'):
            ext = 'mp4'
            
        filename = f"{name}_{img_id}.{ext}"
        
        # Ensure filename is not too long and has no invalid chars
        filename = "".join([c for c in filename if c.isalpha() or c.isdigit() or c in (' ', '-', '_', '.')]).strip()
        if len(filename) > 200:
            filename = f"{filename[:100]}_{img_id}.{ext}"
            
        filepath = os.path.join(output_dir, filename)
        
        # Check for old duplicates/other named files with same ID
        try:
            import glob
            # Pattern: *_{img_id}.*
            search_pattern = os.path.join(output_dir, f"*_{img_id}.*")
            potential_dupes = glob.glob(search_pattern)
            
            for dupe in potential_dupes:
                # Skip if it's the target file itself
                if os.path.abspath(dupe) == os.path.abspath(filepath):
                    continue
                
                # We found a duplicate (different name, same ID)
                if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                    # New file already exists and is good. Delete the old duplicate.
                    try:
                        if os.path.exists(dupe):
                            os.remove(dupe)
                            tqdm.write(f"Removed redundant duplicate: {os.path.basename(dupe)}")
                    except OSError as e:
                        if e.errno != 2: # Ignore FileNotFoundError (errno 2)
                            tqdm.write(f"Error deleting duplicate {dupe}: {e}")
                else:
                    # New file doesn't exist (or is empty). Rename duplicate to new file.
                    if os.path.getsize(dupe) > 0:
                        try:
                            os.rename(dupe, filepath)
                            # tqdm.write(f"Renamed old file: {os.path.basename(dupe)} -> {os.path.basename(filepath)}")
                        except OSError as e:
                            if e.errno != 2:
                                tqdm.write(f"Error renaming {dupe}: {e}")
                            
        except Exception as e:
            # Ignore FileNotFoundError in the outer loop too (e.g. from os.path.getsize)
            if hasattr(e, 'errno') and e.errno == 2:
                pass
            elif "The system cannot find the file specified" in str(e): # Windows specific message check just in case
                pass
            else:
                tqdm.write(f"Error during duplicate check: {e}")

        # Check if file exists and has content (after potential rename)
        if os.path.exists(filepath):
            if os.path.getsize(filepath) > 0:
                return True # Skip existing valid file, count as success
            else:
                pass 
            
        # Retry loop for 429 errors
        max_retries = 10
        for attempt in range(max_retries):
            try:
                # Add random delay to be nice to the server
                time.sleep(random.uniform(0.5, 1.5))
                
                # Try downloading modified URL first
                r = requests.get(original_url, stream=True, timeout=30)
                
                if r.status_code == 429:
                    wait_time = (attempt + 1) * 10 # 10s, 20s, 30s...
                    tqdm.write(f"Rate limited (429) for {url}. Waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue

                if r.status_code != 200:
                    # If modified URL fails, try the original URL provided by API
                    # But ONLY if the original URL is a valid http link (not a UUID)
                    if original_url != url and url.startswith('http'):
                        # tqdm.write(f"Modified URL failed ({r.status_code}), trying original: {url}")
                        r = requests.get(url, stream=True, timeout=30)
                        
                        if r.status_code == 429:
                            wait_time = (attempt + 1) * 10
                            tqdm.write(f"Rate limited (429) for {url}. Waiting {wait_time}s...")
                            time.sleep(wait_time)
                            continue
                
                r.raise_for_status()

                with open(filepath, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                # Verify file size
                if os.path.getsize(filepath) > 0:
                    return True # Success
                else:
                    tqdm.write(f"Downloaded file is empty: {url}")
                    
            except requests.exceptions.RequestException as e:
                if "429" in str(e):
                    wait_time = (attempt + 1) * 10
                    tqdm.write(f"Rate limited (429) exception for {url}. Waiting {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    tqdm.write(f"Network error {url}: {e}")
                    time.sleep(5) # Wait on network error
                
        else:
            # This else block executes if the loop completes without 'break' (return True)
            tqdm.write(f"Failed to download {url} after {max_retries} attempts.")
            return False
                        
    except Exception as e:
        tqdm.write(f"Error downloading {img_data.get('url')}: {e}")
        return False

def process_user(user_input, api_key, position=0, after_date=None):
    """
    Process a single user: resolve ID, fetch images, download.
    """
    user_id = None
    username = None
    
    # Determine if input is URL, Username, or ID
    # Determine if input is URL, Username, or ID
    if 'civitai.com/user/' in user_input:
        # Extract username from URL
        try:
            path_parts = urlparse(user_input).path.split('/')
            user_index = path_parts.index('user')
            username = path_parts[user_index + 1]
            user_id = get_user_id(username)
        except:
            tqdm.write(f"[{user_input}] Invalid URL.")
            return
            
    else:
        # Treat as username first, even if it looks like an ID
        # (e.g. user '81189' is a valid username but has specific ID)
        username = user_input
        user_id = get_user_id(username)
        
        # Fallback: If username resolution failed, but input is digits, try as direct ID
        if not user_id and user_input.isdigit():
            user_id = int(user_input)
            username = f"User_{user_id}" # Fallback name
            tqdm.write(f"[{user_input}] Could not resolve as username. Assuming User ID: {user_id}")
        
    if not user_id:
        tqdm.write(f"[{user_input}] Failed to resolve User ID.")
        return

    tqdm.write(f"[{username}] Processing (ID: {user_id})...")
    
    # Decide strategy: If we have a username, query by username (more robust for recent items)
    # If we only have ID (fallback), query by ID.
    
    use_username_query = True if username and not username.startswith("User_") else False
    query_identifier = username if use_username_query else user_id
    
    images = get_images(query_identifier, api_key, position=position, after_date=after_date, is_username=use_username_query)
    posts = get_posts(query_identifier, api_key, position=position, after_date=after_date, is_username=use_username_query)
    
    # Merge and deduplicate by ID
    all_items = {img['id']: img for img in images}
    for post_item in posts:
        # Check if item ID already exists (unlikely collision between image ID and other ID but possible)
        # Actually images and posts might have different ID spaces, but here we extracted images FROM posts.
        # Images from get_images and Images from get_posts might overlap?
        # Yes, if post.getInfinite returns same underlying images.
        if post_item['id'] not in all_items:
             all_items[post_item['id']] = post_item
        else:
             # Already have it, maybe update metadata if missing?
             pass
             
    final_items = list(all_items.values())
    
    if not final_items:
        tqdm.write(f"[{username}] No images or posts found.")
        return
        
    output_dir = os.path.join("downloads", username)
    os.makedirs(output_dir, exist_ok=True)
    
    tqdm.write(f"[{username}] Found {len(final_items)} total items (Images: {len(images)}, Posts: {len(posts)}).")
    
    # Sort again by date
    final_items.sort(key=lambda x: x.get('createdAt', ''), reverse=True)
    
    images = final_items # Assign back for download loop
    # We use a thread pool here for the images
    # Reduced workers to 2 to prevent rate limiting
    # Download images for this user
    # We use a thread pool here for the images
    # Reduced workers to 2 to prevent rate limiting
    from concurrent.futures import as_completed
    
    success_count = 0
    fail_count = 0
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(download_image, img, output_dir): img for img in images}
        
        # Custom bar format to emphasize "Processed" and show Success/Fail clearly
        # {l_bar}: Description + Percentage
        # {bar}: The progress bar itself
        # {n_fmt}/{total_fmt}: Current/Total count
        # {rate_fmt}: Speed
        # {postfix}: Success/Fail counts
        bar_fmt = "{l_bar}{bar}| {n_fmt}/{total_fmt} Processed [{elapsed}<{remaining}, {rate_fmt}{postfix}]"
        
        with tqdm(total=len(images), unit="proc", desc=f"{username:<15}", position=position, leave=True, bar_format=bar_fmt) as pbar:
            pbar.set_postfix(success=0, fail=0) # Initialize postfix
            for future in as_completed(futures):
                result = future.result()
                if result:
                    success_count += 1
                else:
                    fail_count += 1
                
                pbar.set_postfix(success=success_count, fail=fail_count)
                pbar.update(1)

# Configuration
# Add your target users here (Username, URL, or ID)
TARGET_USERS = [
    "athrowaway7894561633",
    "76525460285",
    "Grutzy",
    "81189",
    "VoidBone",
    "MyWaifu",
    "BakaNoWaifu",
    "Futurabbit",
    "GrooteS",
    "noroi311",
    "sexypanda",
    "Nsdekk",
    "Maxximoonia",
    "Shoukolpb",
    "psoft",
    "OddlyGee",
    "Lady_Luminous",
    "ruanyi",
    "AutoPastel",
    "WhiteClouds",
    "PineappleUpsideDownBad",
    "scratchblue555",
    "lbccdl",
    "DoreenAI",
    "Lady_Luminous",
    "GrayColor",
    "bar3470524",
    "RAMTHRUST",
    "AIMon86",
    "openmn793",
    "BallsyBalls",
    "Stu43",
    "76525460285",
    "124123",
    "00x09901",    
    "lantislt",
    "LegionMIA",
    "Takah0x",
    "Bunnykiin",
    "NJordan",
    "Sexiam",
    "GAOLD",
    "DeadEndsWithYou",
    "spreadapart",
    "JSyu",
    "rcstone",
    "SAKI88",
    "lDeXl",
    "GenerationUI",
    "pilotmau197",
    "Ereijtic",
    "Whistler_ai",
    "donutlemon",
    "Steelhaze",
    "Nipsntits",
    "MrMrss",
    "kuronekoAI",
    "SakuMita",
    "ceii0502382",
    "roxin282",
    "vovkka",
    "phinjo",
    "GZees",
    "Marland_C",  
    "Jedas",
    "reijlita",
    "Viiii",
    "KoyamaMyl",
    "Pdsaki",
    "HoonJa",
    "ruinedcastle",
    "demianthedevil",
    "Tozi_White",
    "Cyberdelia",
    "Eyecandy69",
    "freckledvixon",
  
]

# Date filter configuration (YYYY-MM or YYYY-MM-DD)
# Leave empty or None to download all
TARGET_DATE = "2025-12-10"
#TARGET_DATE = "2025-4-1"

def main():
    parser = argparse.ArgumentParser(description="Civitai User Image Downloader")
    parser.add_argument("users", nargs='*', help="List of Civitai User URLs, Usernames, or IDs")
    parser.add_argument("--key", help="Civitai API Key", default=None)
    parser.add_argument("--after", help="Download only images created after this date (YYYY-MM or YYYY-MM-DD)", default=None)
    
    args = parser.parse_args()
    
    date_input = args.after if args.after else TARGET_DATE
    after_date = parse_date(date_input)
    
    if date_input and not after_date:
        print(f"Invalid date format: {date_input}")
        return # Exit if date is invalid
    
    api_key = args.key
    if not api_key:
        api_key = "b7b831368931d9cb453d89a6a2401198" ##"38099a6de2b076f6b879dd08e233be6b"# # 
        # api_key = input("Enter your Civitai API Key: ").strip()
    
    users = args.users
    if not users:
        users = TARGET_USERS
        
    if not users:
        print("No users specified. Please add users to TARGET_USERS list in the script or pass them as arguments.")
        return

    # Deduplicate users while preserving order and removing empty strings
    seen = set()
    unique_users = []
    for u in users:
        u = u.strip()
        if u and u not in seen:
            unique_users.append(u)
            seen.add(u)
    users = unique_users

    print(f"Processing {len(users)} users: {', '.join(users)}")
    
    # Process users in parallel
    # We use a separate ThreadPool for users. 
    # Note: Nested ThreadPools can be tricky, but since the inner one is network bound, it's okay.
    # However, to avoid too many threads, we might limit the outer pool.
    
    max_concurrent_users = 2
    # Use a larger range for positions to avoid conflict with main progress if any (though we don't have one)
    with ThreadPoolExecutor(max_workers=max_concurrent_users) as executor:
        futures = [executor.submit(process_user, user, api_key, i, after_date) for i, user in enumerate(users)]
        # Wait for all to complete
        for future in futures:
            future.result()

    print("All tasks finished.")

if __name__ == "__main__":
    main()
