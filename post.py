"""Автопостинг в Threads с подтверждением через Telegram.
  python3 post.py preview   — показать следующий пост в консоли
  python3 post.py draft     — прислать следующий черновик в Telegram
  python3 post.py poll      — обработать ответы (кнопки / правки) и опубликовать одобренное
Переменные: THREADS_TOKEN, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, GITHUB_REPOSITORY."""
import json, os, sys, time, urllib.parse, urllib.request, urllib.error

here = os.path.dirname(os.path.abspath(__file__))
posts = json.load(open(f"{here}/posts.json", encoding="utf-8"))
state_path = f"{here}/state.json"
state = json.load(open(state_path)) if os.path.exists(state_path) else {}
state.setdefault("n", 0); state.setdefault("offset", 0); state.setdefault("pending", {})
def save(): json.dump(state, open(state_path, "w"), ensure_ascii=False, indent=1)

def http(url, data=None):
    try:
        return json.load(urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=120))
    except urllib.error.HTTPError as e:
        sys.exit(f"Ошибка {e.code}: {e.read().decode()}")

# ---------- Telegram ----------
def tg(method, **p):
    p = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in p.items()}
    return http(f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/{method}", urllib.parse.urlencode(p).encode())["result"]
CHAT = lambda: os.environ["TELEGRAM_CHAT_ID"]

def send_draft(n, text, note=""):
    kb = {"inline_keyboard": [[{"text": "✅ Опубликовать", "callback_data": f"ok:{n}"},
                               {"text": "⏭ Пропустить", "callback_data": f"no:{n}"}]]}
    m = tg("sendMessage", chat_id=CHAT(), text=(note + text), reply_markup=kb)
    state["pending"][str(n)]["msg_ids"].append(m["message_id"])

# ---------- Threads ----------
API = "https://graph.threads.net/v1.0"
def th(method, path, **params):
    params["access_token"] = os.environ["THREADS_TOKEN"]
    q = urllib.parse.urlencode(params)
    return http(f"{API}/{path}", q.encode()) if method == "POST" else http(f"{API}/{path}?{q}")

def wait_ready(cid):
    for _ in range(60):
        st = th("GET", cid, fields="status,error_message")
        if st.get("status") == "FINISHED": return
        if st.get("status") in ("ERROR", "EXPIRED"): sys.exit(f"Контейнер {cid}: {st}")
        time.sleep(5)
    sys.exit("Медиа не обработалось за 5 минут")

def publish(cab, text):
    files = sorted(os.listdir(f"{here}/media/{cab}"))
    files = [f for f in files if f.endswith(".jpg")] + [f for f in files if f.endswith(".mp4")]
    repo = os.environ["GITHUB_REPOSITORY"]
    def item(f, **extra):
        vid = f.endswith(".mp4")
        url = f"https://raw.githubusercontent.com/{repo}/main/media/{cab}/{f}"
        cid = th("POST", "me/threads", media_type="VIDEO" if vid else "IMAGE", **{"video_url" if vid else "image_url": url}, **extra)["id"]
        wait_ready(cid); return cid
    if len(files) == 1:
        container = item(files[0], text=text)
    else:
        kids = [item(f, is_carousel_item="true") for f in files[:20]]
        container = th("POST", "me/threads", media_type="CAROUSEL", children=",".join(kids), text=text)["id"]
        wait_ready(container)
    return th("POST", "me/threads_publish", creation_id=container)["id"]

# ---------- команды ----------
def next_post():
    n = state["n"]; lang = "ru" if n % 2 == 0 else "kk"; idx = n // 2
    cab = posts["cabinets"][idx % len(posts["cabinets"])]
    return n, lang, cab, posts[lang][cab][(idx // len(posts["cabinets"])) % len(posts[lang][cab])]

cmd = sys.argv[1] if len(sys.argv) > 1 else "preview"
if cmd == "preview":
    n, lang, cab, text = next_post(); print(f"#{n} {lang} {cab}\n\n{text}")

elif cmd == "draft":
    n, lang, cab, text = next_post()
    state["pending"][str(n)] = {"cab": cab, "text": text, "msg_ids": []}
    state["n"] = n + 1
    send_draft(n, text); save()

elif cmd == "poll":
    for u in tg("getUpdates", offset=state["offset"], timeout=0, allowed_updates=["callback_query", "message"]):
        state["offset"] = u["update_id"] + 1
        cb, msg = u.get("callback_query"), u.get("message")
        if cb and str(cb["message"]["chat"]["id"]) == CHAT():
            act, n = cb["data"].split(":"); p = state["pending"].get(n)
            tg("answerCallbackQuery", callback_query_id=cb["id"])
            mid = cb["message"]["message_id"]
            if not p:
                tg("editMessageReplyMarkup", chat_id=CHAT(), message_id=mid, reply_markup={"inline_keyboard": []}); continue
            if act == "no":
                state["pending"].pop(n); tg("editMessageText", chat_id=CHAT(), message_id=mid, text="⏭ Пропущено\n\n" + p["text"])
            else:
                pid = publish(p["cab"], p["text"]); state["pending"].pop(n)
                tg("editMessageText", chat_id=CHAT(), message_id=mid, text="✅ Опубликовано\n\n" + p["text"])
        elif msg and str(msg["chat"]["id"]) == CHAT() and msg.get("reply_to_message") and msg.get("text"):
            rid = msg["reply_to_message"]["message_id"]
            n = next((k for k, v in state["pending"].items() if rid in v["msg_ids"]), None)
            if n:
                state["pending"][n]["text"] = msg["text"]
                send_draft(n, msg["text"], "✏️ Ваш вариант:\n\n")
        save()
