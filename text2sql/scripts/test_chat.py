import urllib.request, json

def ask(question):
    payload = json.dumps({"question": question}).encode()
    req = urllib.request.Request(
        "http://localhost:8000/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    try:
        res = urllib.request.urlopen(req, timeout=30)
        data = json.loads(res.read())
        print(f"Q: {question}")
        print(f"status: {data.get('status')}")
        print(f"answer: {data.get('answer', '')[:300]}")
        print(f"errors: {data.get('errors', [])}")
        print("-" * 60)
    except Exception as ex:
        print(f"Error: {ex}")

ask("AQI hom nay")
ask("Toc do giao thong trung binh o SEC_001 la bao nhieu?")
ask("So xe dang do tai cac khu vuc?")
