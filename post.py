"""Публикует очередной пост в Threads. Запуск: python3 post.py [--dry-run]
Нужны переменные: THREADS_TOKEN, GITHUB_REPOSITORY (owner/repo)."""
import json, os, sys, time, urllib.parse, urllib.request, urllib.error

API = "https://graph.threads.net/v1.0"
DRY = "--dry-run" in sys.argv
here = os.path.dirname(os.path.abspath(__file__))
posts = json.load(open(f"{here}/posts.json", encoding="utf-8"))
state_path = f"{here}/state.json"
n = json.load(open(state_path))["n"] if os.path.exists(state_path) else 0

lang = "ru" if n % 2 == 0 else "kk"          # утро — русский, вечер — казахский
idx = n // 2                                  # один и тот же кабинет получает оба языка
cab = posts["cabinets"][idx % len(posts["cabinets"])]
variant = (idx // len(posts["cabinets"])) % len(posts[lang][cab])
text = posts[lang][cab][variant]

files = sorted(os.listdir(f"{here}/media/{cab}"))
files = [f for f in files if f.endswith(".jpg")] + [f for f in files if f.endswith(".mp4")]
repo = os.environ.get("GITHUB_REPOSITORY", "OWNER/REPO")
url = lambda f: f"https://raw.githubusercontent.com/{repo}/main/media/{cab}/{f}"
kind = lambda f: "VIDEO" if f.endswith(".mp4") else "IMAGE"

print(f"Пост #{n}: {lang}, {cab}, вариант {variant}, медиа: {files}\n{'-'*40}\n{text}\n{'-'*40}")
if DRY:
    sys.exit(0)

token = os.environ["THREADS_TOKEN"]

def call(method, path, **params):
    params["access_token"] = token
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"{API}/{path}" if method == "POST" else f"{API}/{path}?{data.decode()}",
                                 data=data if method == "POST" else None, method=method)
    try:
        return json.load(urllib.request.urlopen(req, timeout=120))
    except urllib.error.HTTPError as e:
        sys.exit(f"Ошибка Threads API {e.code}: {e.read().decode()}")

def wait_ready(cid):
    for _ in range(60):
        st = call("GET", cid, fields="status,error_message")
        if st.get("status") == "FINISHED":
            return
        if st.get("status") in ("ERROR", "EXPIRED"):
            sys.exit(f"Контейнер {cid}: {st}")
        time.sleep(5)
    sys.exit(f"Контейнер {cid} не обработался за 5 минут")

def item(f, **extra):
    key = "video_url" if kind(f) == "VIDEO" else "image_url"
    cid = call("POST", "me/threads", media_type=kind(f), **{key: url(f)}, **extra)["id"]
    wait_ready(cid)
    return cid

if len(files) == 1:
    container = item(files[0], text=text)
else:
    kids = [item(f, is_carousel_item="true") for f in files[:20]]
    container = call("POST", "me/threads", media_type="CAROUSEL", children=",".join(kids), text=text)["id"]
    wait_ready(container)

pid = call("POST", "me/threads_publish", creation_id=container)["id"]
print("Опубликовано, id:", pid)
json.dump({"n": n + 1}, open(state_path, "w"))
