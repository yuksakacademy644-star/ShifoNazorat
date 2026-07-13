import requests, time

url = "https://25be74425e81480d-94-158-58-115.serveousercontent.com"

for i in range(3):
    t0 = time.time()
    r = requests.get(f"{url}/api/check-user?chat_id=1477103854")
    elapsed = round(time.time() - t0, 2)
    print(f"So'rov {i+1}: {elapsed} soniya | Status: {r.status_code}")
