import os
import sys
import requests
import json
import argparse
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
from bs4 import BeautifulSoup
import time
import random
import signal

def signal_handler(sig, frame):
    print("\nCtrl+C pressed. Exiting immediately...")
    os._exit(0)

signal.signal(signal.SIGINT, signal_handler)

def get_user_id(username):
    """
    Scrapes the user profile page to find the internal User ID.
    """
    url = f"https://civitai.com/user/{username}"
    print(f"Resolving User ID for {username} from {url}...")
    
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        script_tag = soup.find('script', id='__NEXT_DATA__')
        
        if not script_tag:
            print("Error: Could not find __NEXT_DATA__ on profile page.")
            return None
            
        data = json.loads(script_tag.string)
        
        # Navigate JSON to find user ID
        # Structure varies, but usually under props -> pageProps -> trpcState -> json -> queries -> ...
        # Or sometimes directly in pageProps -> user
        
        # Attempt 1: Look for 'user' object in pageProps
        if 'props' in data and 'pageProps' in data['props']:
             page_props = data['props']['pageProps']
             if 'username' in page_props and page_props['username'].lower() == username.lower():
                 if 'id' in page_props:
                     return page_props['id']
        
        # Attempt 2: Search recursively or look for specific query patterns if method 1 fails
        # The browser tool found it in the text content, let's try to parse the trpc state if needed.
        # But often it's in the initial state.
        
        # Let's try a simpler regex approach if JSON parsing is too deep/complex to guess
        # actually, let's just dump the json keys to debug if it fails, but for now return None
        
        # Fallback: Try to find any 'id' associated with the username in the json
        # This is a bit hacky, but effective if the structure changes.
        
        # Let's rely on the API if we can't find it? No, we need ID for API.
        # Let's try the /api/v1/creators endpoint? No, that lists creators.
        
        # Let's try to find the user id from the pre-fetched data in the browser tool which was successful.
        # It was found in __NEXT_DATA__.
        
        # Let's try to find it in the 'queries'
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

def get_images(user_id, api_key, position=0):
    """
    Fetches all image metadata from the API.
    """
    base_url = "https://civitai.com/api/v1/images"
    images = []
    cursor = None
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # print(f"Fetching image list for User ID {user_id}...")
    
    with tqdm(desc=f"Fetching Metadata {user_id}", unit="page", position=position, leave=False) as pbar:
        while True:
            params = {
                "userId": user_id,
                "limit": 100,
                "sort": "Newest",
                "nsfw": "true" # Important to get all images
            }
            if cursor:
                params["cursor"] = cursor
                
            try:
                response = requests.get(base_url, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()
                
                batch = data.get('items', [])
                images.extend(batch)
                
                pbar.update(1)
                
                metadata = data.get('metadata', {})
                if 'nextCursor' in metadata:
                    cursor = metadata['nextCursor']
                elif 'nextPage' in metadata:
                    # Fallback: try to extract cursor from URL or use URL directly (not implemented here, preferring nextCursor)
                    # If nextPage is a URL, we might need to parse it.
                    # But usually nextCursor is present in v1 API.
                    from urllib.parse import parse_qs, urlparse
                    parsed = urlparse(metadata['nextPage'])
                    qs = parse_qs(parsed.query)
                    cursor = qs.get('cursor', [None])[0]
                else:
                    cursor = None
                
                if not cursor:
                    break
                    
            except requests.exceptions.RequestException as e:
                tqdm.write(f"API Request failed: {e}")
                break
                
    tqdm.write(f"Found {len(images)} images for User ID {user_id}.")
    return images

def download_image(img_data, output_dir):
    """
    Downloads a single image.
    """
    try:
        url = img_data.get('url')
        if not url:
            return
            
        # Transform URL for original quality if possible
        # Civitai URLs often look like: https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/UUID/width=450/123.jpeg
        # We want to remove the width parameter or set it to original.
        # Actually, usually removing 'width=...' part or changing it works.
        # Let's try to strip the width part.
        # Format: .../UUID/width=XXX/name.jpeg -> .../UUID/original=true/name.jpeg or just .../UUID/name.jpeg?
        # Based on research, the 'url' field is usually the direct link.
        # But often it has /width=X/ in it.
        
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
        name = "".join([c for c in name if c.isalpha() or c.isdigit() or c in (' ', '-', '_')]).strip()
        if not name:
             name = f"image_{img_id}"
             
        ext = 'png' # Default
        if '.' in url.split('/')[-1]:
             ext = url.split('/')[-1].split('.')[-1].split('?')[0]
             
        filename = f"{name}_{img_id}.{ext}"
        filepath = os.path.join(output_dir, filename)
        
        # Check if file exists and has content
        if os.path.exists(filepath):
            if os.path.getsize(filepath) > 0:
                return # Skip existing valid file
            else:
                # File exists but is empty, re-download
                pass 
            
        # Retry loop for 429 errors
        max_retries = 5
        for attempt in range(max_retries):
            try:
                # Add random delay to be nice to the server
                time.sleep(random.uniform(0.1, 0.3))
                
                # Try downloading modified URL first
                r = requests.get(original_url, stream=True, timeout=10)
                
                if r.status_code == 429:
                    wait_time = (attempt + 1) * 5 # Linear backoff: 5, 10, 15...
                    tqdm.write(f"Rate limited (429). Waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                
                if r.status_code == 200:
                    with open(filepath, 'wb') as f:
                        for chunk in r.iter_content(1024):
                            f.write(chunk)
                    return # Success
                
                # If modified failed (but not 429), try original URL
                if original_url != url:
                    r = requests.get(url, stream=True, timeout=10)
                    
                    if r.status_code == 429:
                        wait_time = (attempt + 1) * 5
                        tqdm.write(f"Rate limited (429). Waiting {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                        
                    if r.status_code == 200:
                        with open(filepath, 'wb') as f:
                            for chunk in r.iter_content(1024):
                                f.write(chunk)
                        return # Success
                
                # If we got here, it's a non-recoverable error (e.g. 404) or failed both
                tqdm.write(f"Failed to download {url}: Status {r.status_code}")
                return
                
            except requests.exceptions.RequestException as e:
                tqdm.write(f"Network error {url}: {e}")
                time.sleep(2) # Short wait on network error
                
        tqdm.write(f"Failed to download {url} after {max_retries} attempts.")
                        
    except Exception as e:
        tqdm.write(f"Error downloading {img_data.get('url')}: {e}")

def process_user(user_input, api_key, position=0):
    """
    Process a single user: resolve ID, fetch images, download.
    """
    user_id = None
    username = None
    
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
    elif user_input.isdigit():
        # Input is likely an ID
        user_id = int(user_input)
        username = f"User_{user_id}" # Fallback name
    else:
        # Input is likely a username
        username = user_input
        user_id = get_user_id(username)
        
    if not user_id:
        tqdm.write(f"[{user_input}] Failed to resolve User ID.")
        return

    tqdm.write(f"[{username}] Processing (ID: {user_id})...")
    
    images = get_images(user_id, api_key, position=position)
    
    if not images:
        tqdm.write(f"[{username}] No images found.")
        return
        
    output_dir = os.path.join("downloads", username)
    os.makedirs(output_dir, exist_ok=True)
    
    tqdm.write(f"[{username}] Found {len(images)} images.")
    
    # Download images for this user
    # We use a thread pool here for the images
    # Reduced workers to 2 to prevent rate limiting
    with ThreadPoolExecutor(max_workers=2) as executor:
        # Use list to force execution
        list(tqdm(executor.map(lambda img: download_image(img, output_dir), 
                  images), 
                  total=len(images), 
                  unit="img", 
                  desc=f"{username:<15}", # Pad username for alignment
                  position=position, 
                  leave=True))

# Configuration
# Add your target users here (Username, URL, or ID)
TARGET_USERS = [
    #"Ereijtic",
    #"Whistler_ai",
    #"donutlemon",
    #"freckledvixon",
    #"Steelhaze"    
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
    "reijlita",
    #"Viiii",
    "KoyamaMyl",
    "Pdsaki",
    "HoonJa",
    "ruinedcastle",
    "demianthedevil",
    "Tozi_White",
    "Cyberdelia",
    "Eyecandy69",
    #"RAMTHRUST",
    #"AIMon86",
    "MrMrss",
    "kuronekoAI",
    "SakuMita",
    "ceii0502382",
    "roxin282",
    "vovkka",
    "phinjo",
    "GZees",
    "Marland_C",
    #"openmn793",
    "BallsyBalls",
    "Stu43",
    "76525460285",
    "124123",
    "00x09901",
    ""
    # "AnotherUser", 
    # "12345",
]

def main():
    parser = argparse.ArgumentParser(description="Civitai User Image Downloader")
    parser.add_argument("users", nargs='*', help="List of Civitai User URLs, Usernames, or IDs")
    parser.add_argument("--key", help="Civitai API Key", default=None)
    
    args = parser.parse_args()
    
    api_key = args.key
    if not api_key:
        api_key = "38099a6de2b076f6b879dd08e233be6b" #"b7b831368931d9cb453d89a6a2401198" #
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
        futures = [executor.submit(process_user, user, api_key, i) for i, user in enumerate(users)]
        # Wait for all to complete
        for future in futures:
            future.result()

    print("All tasks finished.")

if __name__ == "__main__":
    main()
