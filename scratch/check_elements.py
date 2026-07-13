import re

with open("static/app.js", "r", encoding="utf-8") as f:
    js_content = f.read()

with open("static/index.html", "r", encoding="utf-8") as f:
    html_content = f.read()

ids_in_js = re.findall(r'document\.getElementById\((?:\'|")([a-zA-Z0-9_-]+)(?:\'|")\)', js_content)
# also search for querySelector for ids
ids_in_js.extend(re.findall(r'#([a-zA-Z0-9_-]+)', js_content))

# unique
ids_in_js = sorted(list(set(ids_in_js)))

print(f"Found {len(ids_in_js)} unique IDs referenced in JS.")

missing_ids = []
for idx in ids_in_js:
    # Check if id exists in html as id="idx" or id='idx'
    pattern = rf'id=(?:\'|"){idx}(?:\'|")'
    if not re.search(pattern, html_content):
        # some might be classes or general words, let's only flag those that are likely IDs
        # if they are used in document.getElementById in js
        if f'document.getElementById("{idx}")' in js_content or f"document.getElementById('{idx}')" in js_content:
            missing_ids.append(idx)

print("\nMissing IDs that are used in document.getElementById:")
for m in missing_ids:
    print("-", m)
