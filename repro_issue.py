import requests
import json
import urllib.parse

def get_user_id_via_api(username):
    print(f"Attempting to resolve User ID via API for {username}...")
    headers = {"Content-Type": "application/json"}
    
    # Attempt 1: user.getAll (Search with query)
    try:
        query_input = {"json": {"query": username, "limit": 5}}
        encoded = urllib.parse.quote(json.dumps(query_input))
        url = f"https://civitai.com/api/trpc/user.getAll?input={encoded}"
        print(f"Checking user.getAll: {url}")
        
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            # Debug print
            # print(json.dumps(data, indent=2))
            
            items = data.get('result', {}).get('data', {}).get('json', {}).get('items', [])
            print(f"Items found: {len(items)}")
            for item in items:
                print(f"Found search result: {item.get('username')} (ID: {item.get('id')})")
                if item.get('username', '').lower() == username.lower():
                    print(f"Match found via user.getAll: {item.get('id')}")
                    # return item.get('id')

    except Exception as e:
        print(f"Error in user.getAll: {e}")

    # Attempt 2: user.getCreator (Direct lookup)
    try:
        query_input = {"json": {"username": username}}
        encoded = urllib.parse.quote(json.dumps(query_input))
        url = f"https://civitai.com/api/trpc/user.getCreator?input={encoded}"
        print(f"Checking user.getCreator: {url}")
        
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            user_data = data.get('result', {}).get('data', {}).get('json', {})
            print(f"getCreator result ID: {user_data.get('id')}")
    except Exception as e:
        print(f"Error in user.getCreator: {e}")

    except Exception as e:
        print(f"Error in user.getCreator: {e}")

def get_images_by_username(username, api_key):
    base_url = "https://civitai.com/api/trpc/image.getInfinite"
    
    input_data = {
        "json": {
            "username": username,
            "sort": "Newest",
            "limit": 10,
            "browsingLevel": 31
        }
    }
    encoded_input = urllib.parse.quote(json.dumps(input_data))
    url = f"{base_url}?input={encoded_input}"
    
    print(f"Fetching images for Username {username} from: {url}")
    headers = {
        "Content-Type": "application/json"
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        # ... rest is same
        response.raise_for_status()
        data = response.json()
        
        result_data = data.get('result', {}).get('data', {}).get('json', {})
        batch = result_data.get('items', [])
        print(f"Found {len(batch)} images.")
        if batch:
            print(f"First image date: {batch[0].get('createdAt')}")
            print(f"First image ID: {batch[0].get('id')}")
        else:
            print("No images found in batch.")
            
    except Exception as e:
        print(f"Error fetching images: {e}")

def test_posts(username, user_id, api_key):
    print("\n--- Testing Posts Endpoint ---")
    base_url = "https://civitai.com/api/trpc/post.getInfinite"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # Test by Username
    try:
        input_data = {
            "json": {
                "username": username,
                "sort": "Newest",
                "browsingLevel": 31
            }
        }
        encoded = urllib.parse.quote(json.dumps(input_data))
        url = f"{base_url}?input={encoded}"
        print(f"Fetching posts for Username {username}...")
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get('result', {}).get('data', {}).get('json', {}).get('items', [])
            print(f"Posts found (by username): {len(items)}")
            if items:
                 # print(f"First Post Date: {items[0].get('createdAt')}")
                 # print(f"First Post ID: {items[0].get('id')}")
                 print("First Post Structure Keys:", items[0].keys())
                 if 'images' in items[0]:
                     print("First Post Images:", json.dumps(items[0]['images'][0] if items[0]['images'] else "No images", indent=2))
    except Exception as e:
        print(f"Error fetching posts by username: {e}")

    # Test by User ID
    try:
        input_data = {
            "json": {
                "userId": user_id,
                "sort": "Newest",
                "browsingLevel": 31
            }
        }
        encoded = urllib.parse.quote(json.dumps(input_data))
        url = f"{base_url}?input={encoded}"
        print(f"Fetching posts for User ID {user_id}...")
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get('result', {}).get('data', {}).get('json', {}).get('items', [])
            print(f"Posts found (by ID): {len(items)}")
            if items:
                 print(f"First Post Date: {items[0].get('createdAt')}")
                 print(f"First Post ID: {items[0].get('id')}")
    except Exception as e:
        print(f"Error fetching posts by ID: {e}")

def test_videos(username, user_id, api_key):
    print("\n--- Testing Videos Endpoint ---")
    base_url = "https://civitai.com/api/trpc/video.getInfinite"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    try:
        input_data = {
            "json": {
                "userId": user_id,
                "sort": "Newest",
                "browsingLevel": 31
            }
        }
        encoded = urllib.parse.quote(json.dumps(input_data))
        url = f"{base_url}?input={encoded}"
        print(f"Fetching videos for User ID {user_id}...")
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get('result', {}).get('data', {}).get('json', {}).get('items', [])
            print(f"Videos found: {len(items)}")
            if items:
                 print(f"First Video Date: {items[0].get('createdAt')}")
                 print(f"First Video ID: {items[0].get('id')}")
        else:
            print(f"Video endpoint returned {resp.status_code}")
    except Exception as e:
        print(f"Error fetching videos: {e}")

if __name__ == "__main__":
    # username = "athrowaway7894561633"
    username = "76525460285"
    api_key = "38099a6de2b076f6b879dd08e233be6b"
    
    print(f"--- Testing User {username} ---")
    get_images_by_username(username, api_key)
    # We don't have ID for this user yet, so pass 0 for ID test, relying on username test
    test_posts(username, 0, api_key)

