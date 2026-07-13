with open("static/app.js", "r", encoding="utf-8") as f:
    code = f.read()

brace_count = 0
in_string = False
string_char = ''
escaped = False

for i, char in enumerate(code):
    if escaped:
        escaped = False
        continue
    if char == '\\':
        escaped = True
        continue
    if char in ['"', "'", '`']:
        if not in_string:
            in_string = True
            string_char = char
        elif string_char == char:
            in_string = False
    elif not in_string:
        if char == '{':
            brace_count += 1
        elif char == '}':
            brace_count -= 1
            if brace_count < 0:
                print(f"Excess closing brace at character {i}!")
                break

print("Final brace count:", brace_count)
