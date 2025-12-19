import os
import sys
import requests
import json
import argparse
import urllib.parse
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
import time
import random
import signal
from datetime import datetime, timezone

def signal_handler(sig, frame):
    print("\nCtrl+C pressed. Exiting immediately...")
    os._exit(0)

signal.signal(signal.SIGINT, signal_handler)

def get_collection_id(collection_input):
    """
    Extracts Collection ID from URL or returns the input if it's an ID.
    """
    if str(collection_input).isdigit():
        return int(collection_input)
    
    # Try to extract from URL
    # https://civitai.com/collections/12345
    try:
        path_parts = urlparse(collection_input).path.split('/')
        if 'collections' in path_parts:
            idx = path_parts.index('collections')
            if idx + 1 < len(path_parts):
                possible_id = path_parts[idx + 1]
                if possible_id.isdigit():
                    return int(possible_id)
    except:
        pass
    
    return None

def get_collection_name(collection_id, api_key):
    """
    Fetches the collection name via TRPC API.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    base_url = "https://civitai.com/api/trpc/collection.getById"
    input_data = {"json": {"id": collection_id}}
    encoded_input = urllib.parse.quote(json.dumps(input_data))
    url = f"{base_url}?input={encoded_input}"
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 200:
            data = response.json()
            # Path: result -> data -> json -> collection -> name
            json_data = data.get('result', {}).get('data', {}).get('json', {})
            collection = json_data.get('collection')
            
            if not collection:
                return None # Collection not found or deleted
                
            name = collection.get('name')
            if name:
                # Sanitize
                return "".join([c for c in name if c.isalpha() or c.isdigit() or c in (' ', '-', '_')]).strip()
    except:
        pass
    return f"Collection_{collection_id}"



def get_collection_images(collection_id, api_key, position=0):
    """
    Fetches all image metadata from the Collection via TRPC API.
    """
    images = []
    cursor = None
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # TRPC Endpoint
    base_url = "https://civitai.com/api/trpc/image.getInfinite"
    
    total_items_scanned = 0
    
    with tqdm(desc=f"Fetching Collection {collection_id}", unit="page", position=position, leave=False) as pbar:
        while True:
            # Construct TRPC Input
            json_params = {
                "collectionId": collection_id,
                "sort": "Newest",
                "limit": 100,
                # Browser-derived parameters for maximum visibility
                "period": "AllTime",
                "browsingLevel": 31,
                "include": ["cosmetics"],
                "excludedTagIds": [415792, 426772, 5188, 5249, 130818, 130820, 133182, 5351, 306619, 154326, 161829, 163032],
                "disablePoi": True,
                "disableMinor": True,
                "authed": True
            }
            if cursor:
                json_params["cursor"] = cursor
            
            input_data = {"json": json_params}
            
            encoded_input = urllib.parse.quote(json.dumps(input_data))
            url = f"{base_url}?input={encoded_input}"
            
            # Retry loop for 5xx errors
            max_retries = 5
            for attempt in range(max_retries):
                try:
                    # Random delay
                    time.sleep(random.uniform(0.1, 0.3))
                    
                    response = requests.get(url, headers=headers, timeout=30)
                    
                    if 500 <= response.status_code < 600:
                        wait_time = (attempt + 1) * 5
                        tqdm.write(f"Server error ({response.status_code}). Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                        
                    response.raise_for_status()
                    data = response.json()
                    break
                    
                except requests.exceptions.RequestException as e:
                    if attempt < max_retries - 1:
                        if "500" in str(e) or "502" in str(e) or "503" in str(e) or "504" in str(e):
                            wait_time = (attempt + 1) * 5
                            tqdm.write(f"Server error exception. Retrying in {wait_time}s...")
                            time.sleep(wait_time)
                            continue
                    
                    tqdm.write(f"API Request failed: {e}")
                    # raise e
            else:
                tqdm.write(f"Failed to fetch metadata after {max_retries} attempts.")
                break
            
            # Parse TRPC Response
            # Structure: result -> data -> json -> items
            #            result -> data -> json -> nextCursor
            
            result_data = data.get('result', {}).get('data', {}).get('json', {})
            batch = result_data.get('items', [])
            if not batch:
                break
                
            total_items_scanned += len(batch)
            
            images.extend(batch)
            
            pbar.update(1)
            
            next_cursor = result_data.get('nextCursor')
            
            if not next_cursor or next_cursor == cursor:
                if next_cursor == cursor:
                     tqdm.write("Pagination loop detected (cursor stuck). Breaking.")
                break
            cursor = next_cursor
                    

                
    tqdm.write(f"Found {len(images)} images for Collection ID {collection_id}.")
        
    return images

def get_collection_posts(collection_id, api_key, position=0):
    """
    Fetches all posts from the Collection via TRPC API.
    """
    posts = []
    cursor = None
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # TRPC Endpoint
    base_url = "https://civitai.com/api/trpc/post.getInfinite"
    
    with tqdm(desc=f"Fetching Posts Coll {collection_id}", unit="page", position=position, leave=False) as pbar:
        while True:
            # Construct TRPC Input
            json_params = {
                "collectionId": collection_id,
                "sort": "Newest",
                "limit": 100,
                # Browser-derived parameters
                "period": "AllTime", 
                "browsingLevel": 31,
                "include": ["cosmetics"],
                "excludedTagIds": [415792, 426772, 5188, 5249, 130818, 130820, 133182, 5351, 306619, 154326, 161829, 163032],
                "disablePoi": True,
                "disableMinor": True,
                "authed": True
            }
            if cursor:
                json_params["cursor"] = cursor
            
            input_data = {"json": json_params}
            
            encoded_input = urllib.parse.quote(json.dumps(input_data))
            url = f"{base_url}?input={encoded_input}"
            
            try:
                # Random delay
                time.sleep(random.uniform(0.1, 0.3))
                response = requests.get(url, headers=headers, timeout=30)
                response.raise_for_status()
                data = response.json()
                
            except Exception as e:
                tqdm.write(f"Error fetching posts: {e}")
                break
            
            result_data = data.get('result', {}).get('data', {}).get('json', {})
            batch = result_data.get('items', [])
            if not batch:
                break
                
            # Extract images from posts
            for post in batch:
                post_images = post.get('images', [])
                for img in post_images:
                     # Attach post metadata if useful
                     img['postId'] = post.get('id')
                     img['postDate'] = post.get('createdAt') or post.get('publishedAt')
                     if 'createdAt' not in img:
                         img['createdAt'] = img.get('postDate')
                     posts.append(img)
            
            pbar.update(1)
            
            cursor = result_data.get('nextCursor')
            if not cursor:
                break

    tqdm.write(f"Found {len(posts)} images from Posts for Collection ID {collection_id}.")
    return posts

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
                # Fallback if name is missing (unlikely based on debug)
                original_url = f"https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/{uuid}/original=true/image.png"
        else:
            # Existing logic for full URLs
            if '/width=' in url:
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
        
        # Get creator name
        username = img_data.get('user', {}).get('username')
        
        # Sanitize name
        if name:
             name = "".join([c for c in name if c.isalpha() or c.isdigit() or c in (' ', '-', '_')]).strip()
        if not name:
             name = f"image_{img_id}"
             
        # Sanitize username
        if username:
            # Remove slashes and other illegal chars
            username = "".join([c for c in username if c.isalpha() or c.isdigit() or c in (' ', '-', '_')]).strip()
            
        # Determine extension from mime type or URL
        mime_type = img_data.get('mimeType')
        ext = 'png' # Default
        
        if mime_type == 'video/mp4' or img_data.get('type') == 'video' or url.endswith('.mp4'):
            ext = 'mp4'
        elif '.' in url.split('/')[-1]:
             # Handle query params in extension
             ext_part = url.split('/')[-1].split('?')[0]
             if '.' in ext_part:
                 ext = ext_part.split('.')[-1]
             
        # Check if URL is just a UUID (common in TRPC response)
        if not url.startswith('http'):
            # Construct full URL
            # Base: https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/
            uuid = url
            name = img_data.get('name')
            
            # Sanitize name again just in case it came from URL
            if name:
                 name = "".join([c for c in name if c.isalpha() or c.isdigit() or c in (' ', '-', '_')]).strip()

            if ext == 'mp4':
                # Video URL construction
                if name:
                    original_url = f"https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/{uuid}/original=true/{name}.mp4"
                else:
                    original_url = f"https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/{uuid}/original=true/video.mp4"
            else:
                # Image URL construction
                if name:
                    original_url = f"https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/{uuid}/original=true/{name}"
                else:
                    original_url = f"https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/{uuid}/original=true/image.png"
        else:
            # Existing logic for full URLs
            if '/width=' in url:
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

        # Final filename construction
        if username:
            filename = f"{username}_{name}_{img_id}.{ext}"
        else:
            filename = f"{name}_{img_id}.{ext}"
            
        # Ensure filename is not too long and has no invalid chars
        # Windows max path is 260, filename max is 255. Let's be safe.
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
                        os.remove(dupe)
                        tqdm.write(f"Removed redundant duplicate: {os.path.basename(dupe)}")
                    except OSError as e:
                        tqdm.write(f"Error deleting duplicate {dupe}: {e}")
                else:
                    # New file doesn't exist (or is empty). Rename duplicate to new file.
                    if os.path.getsize(dupe) > 0:
                        try:
                            os.rename(dupe, filepath)
                            # tqdm.write(f"Renamed old file: {os.path.basename(dupe)} -> {os.path.basename(filepath)}")
                        except OSError as e:
                            tqdm.write(f"Error renaming {dupe}: {e}")
                            
        except Exception as e:
            tqdm.write(f"Error during duplicate check: {e}")

        # Check if file exists and has content (after potential rename)
        if os.path.exists(filepath):
            if os.path.getsize(filepath) > 0:
                return True # Skip existing valid file
            else:
                pass 
            
        # Retry loop for 429 errors
            
        # Retry loop for 429 errors
        max_retries = 10
        for attempt in range(max_retries):
            try:
                time.sleep(random.uniform(0.5, 1.5))
                
                r = requests.get(original_url, stream=True, timeout=30)
                
                if r.status_code == 429:
                    wait_time = (attempt + 1) * 10
                    tqdm.write(f"Rate limited (429). Waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                
                if r.status_code == 200:
                    with open(filepath, 'wb') as f:
                        for chunk in r.iter_content(1024):
                            f.write(chunk)
                    return True # Success
                
                # Fallback to original URL
                if original_url != url:
                    r = requests.get(url, stream=True, timeout=30)
                    if r.status_code == 429:
                        wait_time = (attempt + 1) * 10
                        tqdm.write(f"Rate limited (429). Waiting {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    if r.status_code == 200:
                        with open(filepath, 'wb') as f:
                            for chunk in r.iter_content(1024):
                                f.write(chunk)
                        return True
                
                tqdm.write(f"Failed to download {url}: Status {r.status_code}")
                return False
                
            except requests.exceptions.RequestException as e:
                if "429" in str(e):
                    wait_time = (attempt + 1) * 10
                    tqdm.write(f"Rate limited (429) exception. Waiting {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    tqdm.write(f"Network error {url}: {e}")
                    time.sleep(5)
                
        tqdm.write(f"Failed to download {url} after {max_retries} attempts.")                        
        return False
    except Exception as e:
        tqdm.write(f"Error downloading {img_data.get('url')}: {e}")
        return False

def process_collection(collection_input, api_key, position=0):
    """
    Process a single collection: resolve ID, fetch images, download.
    """
    collection_id = get_collection_id(collection_input)
        
    if not collection_id:
        tqdm.write(f"[{collection_input}] Failed to resolve Collection ID.")
        return

    tqdm.write(f"[{collection_input}] Processing (ID: {collection_id})...")
    
    # Resolve collection name first to check validity
    collection_name = get_collection_name(collection_id, api_key)
    
    if not collection_name:
        tqdm.write(f"[{collection_input}] Collection not found or deleted. Skipping.")
        return

    tqdm.write(f"[{collection_input}] Resolved Name: {collection_name}")
    
    images = get_collection_images(collection_id, api_key, position=position)
    posts_images = get_collection_posts(collection_id, api_key, position=position)
    
    # Merge
    all_items = {img['id']: img for img in images}
    for p_img in posts_images:
        if p_img['id'] not in all_items:
            all_items[p_img['id']] = p_img
            
    images = list(all_items.values())
    
    if not images:
        tqdm.write(f"[{collection_input}] No images found.")
        return
        
    output_dir = os.path.join("downloads", collection_name)
    os.makedirs(output_dir, exist_ok=True)
    
    tqdm.write(f"[{collection_id}] Found {len(images)} images.")
    
    from concurrent.futures import as_completed
    
    success_count = 0
    fail_count = 0
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(download_image, img, output_dir): img for img in images}
        
        bar_fmt = "{l_bar}{bar}| {n_fmt}/{total_fmt} Processed [{elapsed}<{remaining}, {rate_fmt}{postfix}]"
        
        with tqdm(total=len(images), unit="proc", desc=f"Coll_{collection_id:<10}", position=position, leave=True, bar_format=bar_fmt) as pbar:
            pbar.set_postfix(success=0, fail=0)
            for future in as_completed(futures):
                result = future.result()
                if result:
                    success_count += 1
                else:
                    fail_count += 1
                
                pbar.set_postfix(success=success_count, fail=fail_count)
                pbar.update(1)

# Configuration
# Add your target collections here (URL or ID)
TARGET_COLLECTIONS = [
    "https://civitai.com/collections/14197464",
    "https://civitai.com/collections/14071141",
    "https://civitai.com/collections/13957041",
    "https://civitai.com/collections/13973116"
    # "12345"
]



def main():
    parser = argparse.ArgumentParser(description="Civitai Collection Image Downloader")
    parser.add_argument("collections", nargs='*', help="List of Civitai Collection URLs or IDs")
    parser.add_argument("--key", help="Civitai API Key", default=None)
    
    args = parser.parse_args()
    

    
    api_key = args.key
    if not api_key:
        api_key = "b7b831368931d9cb453d89a6a2401198"
    
    collections = args.collections
    if not collections:
        collections = TARGET_COLLECTIONS
        
    if not collections:
        print("No collections specified. Please add URLs/IDs to TARGET_COLLECTIONS list or pass them as arguments.")
        return

    # Deduplicate
    seen = set()
    unique_colls = []
    for c in collections:
        c = c.strip()
        if c and c not in seen:
            unique_colls.append(c)
            seen.add(c)
    collections = unique_colls

    print(f"Processing {len(collections)} collections...")
    
    max_concurrent = 2
    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        futures = [executor.submit(process_collection, coll, api_key, i) for i, coll in enumerate(collections)]
        for future in futures:
            future.result()

    print("All tasks finished.")

if __name__ == "__main__":
    main()
