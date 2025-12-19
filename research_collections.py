import requests
from bs4 import BeautifulSoup
import json

def inspect_collections(username):
    url = f"https://civitai.com/user/{username}/collections"
    print(f"Fetching {url}...")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        
        soup = BeautifulSoup(r.text, 'html.parser')
        next_data = soup.find('script', id='__NEXT_DATA__')
        
        if next_data:
            data = json.loads(next_data.string)
            print("Found __NEXT_DATA__")
            
            # Save to file for inspection
            with open('collections_data.json', 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            print("Saved to collections_data.json")
            
            # Try to find collections in the data
            # Structure might be props -> pageProps -> trpcState -> json -> queries
            # We are looking for something like 'collection.getInfinite'
            
        else:
            print("Could not find __NEXT_DATA__")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    inspect_collections("indigoray")

    # After running, I will inspect the output manually or via the file.
    # I want to see if I can find 'collections' in the data.

