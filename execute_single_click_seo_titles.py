import os
import sys
import json
import urllib.request
import urllib.parse

def make_shopify_request(shop_domain: str, endpoint: str, token: str, method: str = "GET", payload: dict = None) -> dict:
    url = f"https://{shop_domain}/admin/api/2024-04/{endpoint}"
    data = json.dumps(payload).encode("utf-8") if payload else None
    
    req = urllib.request.Request(url, data=data, headers={
        "X-Shopify-Access-Token": token,
        "Accept": "application/json",
        "Content-Type": "application/json"
    }, method=method)
    
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        print(f"Shopify API HTTP Error on {endpoint}: {e.code} - {err_body}")
        return {"error": err_body}
    except Exception as e:
        print(f"Shopify API Error on {endpoint}: {e}")
        return {"error": str(e)}

def main():
    token = "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"
    shop_domain = "2feec0-4.myshopify.com"
    
    print("=================================================================")
    print("⚡ AGENCY OS: EXECUTING SINGLE-CLICK SEO TITLE OPTIMIZATION")
    print("=================================================================")
    
    print("1. Fetching products from Shopify...")
    products_res = make_shopify_request(shop_domain, "products.json?limit=50", token)
    
    products = products_res.get("products", [])
    if not products:
        print("❌ No products found to optimize.")
        return
        
    print(f"   Found {len(products)} products. Filtering for missing brand names...")
    
    update_count = 0
    for p in products:
        p_id = p.get("id")
        title = p.get("title") or ""
        
        # Check if the brand name "Abley" is already present in the title
        if not title.lower().startswith("abley"):
            new_title = f"Abley's {title}"
            print(f"   👉 Optimizing Title: '{title}' ➔ '{new_title}'")
            
            payload = {
                "product": {
                    "id": p_id,
                    "title": new_title
                }
            }
            
            res = make_shopify_request(
                shop_domain, 
                f"products/{p_id}.json", 
                token, 
                method="PUT", 
                payload=payload
            )
            
            if "product" in res:
                update_count += 1
            else:
                print(f"   ❌ Failed to update product '{title}': {res.get('error')}")
                
    print(f"\n🎉 SUCCESS! Programmatically optimized {update_count} product titles in a single sweep!")
    print("=================================================================\n")

if __name__ == "__main__":
    main()
