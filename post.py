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

def http(url, data=None, headers={}):
    try:
        return json.load(urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=120))
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

# ---------- Claude: правки по просьбе ----------
FACTS = """БЦ «Нурсаулет», Атырау, Махамбет Өтемісов 100, первая линия главной улицы. Цена 6 000 ₸ за м² в месяц; в стоимость включены
коммуналка, мебель, ежедневная уборка. Свежий ремонт, светлые тона, потолки 3,2 м, сплит-система в каждом помещении, два этажа,
несколько отдельных входов, автономное отопление, охрана, сигнализация, видеонаблюдение, решётки на окнах, пожарная сигнализация.
Свет, вода, газ, канализация, отопление, вентиляция. Бесплатная парковка на территории под круглосуточным видеонаблюдением.
Рядом остановки, супермаркет, кофейни, клиника. Контакт: WhatsApp +7 702 494 7000."""

def revise(text, instruction):
    system = ("Ты редактор постов для Threads об аренде офисов. Перепиши пост по просьбе владельца. Сохраняй язык поста (русский или казахский), "
              "если не просят другой. Используй только факты из списка и исходного поста, ничего не выдумывай. Цена, адрес и WhatsApp должны остаться. "
              "Не длиннее 500 символов. Пиши естественно, живо, без канцелярита. Верни только готовый текст поста, без пояснений.\n\nФакты:\n" + FACTS)
    out = text
    for _ in range(2):
        r = http("https://api.anthropic.com/v1/messages", json.dumps({
            "model": "claude-sonnet-5-5", "max_tokens": 1000, "system": system,
            "messages": [{"role": "user", "content": f"Текущий пост:\n{text}\n\nПросьба владельца: {instruction}"}]}).encode(),
            {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01", "content-type": "application/json"})
        out = r["content"][0]["text"].strip()
        if len(out) <= 500: return out
        instruction += " (сократи, строго до 450 символов)"
    return out[:500]

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
    # 3 поста в день: утро — казахский, день — русский, вечер — казахский; весь день про один кабинет
    n = state["n"]; slot = n % 3; d = n // 3; r = d // len(posts["cabinets"])
    lang = "ru" if slot == 1 else "kk"
    cab = posts["cabinets"][d % len(posts["cabinets"])]
    k = len(posts[lang][cab])
    var = r % k if lang == "ru" else (2 * r + (0 if slot == 0 else 1)) % k
    return n, lang, cab, posts[lang][cab][var]

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
        state["offset"] = u["update_id"] + 1; save()
        cb, msg = u.get("callback_query"), u.get("message")
        if cb and str(cb["message"]["chat"]["id"]) == CHAT():
            act, n = cb["data"].split(":"); p = state["pending"].get(n)
            try: tg("answerCallbackQuery", callback_query_id=cb["id"])
            except SystemExit: pass          # кнопка слишком старая — не страшно
            mid = cb["message"]["message_id"]
            if not p:
                tg("editMessageReplyMarkup", chat_id=CHAT(), message_id=mid, reply_markup={"inline_keyboard": []}); continue
            if act == "no":
                state["pending"].pop(n); tg("editMessageText", chat_id=CHAT(), message_id=mid, text="⏭ Пропущено\n\n" + p["text"])
            else:
                try:
                    publish(p["cab"], p["text"])
                except SystemExit as e:
                    tg("sendMessage", chat_id=CHAT(), text=f"⚠️ Не удалось опубликовать: {e.code}\nНажмите «Опубликовать» ещё раз.")
                    save(); continue
                state["pending"].pop(n)
                tg("editMessageText", chat_id=CHAT(), message_id=mid, text="✅ Опубликовано\n\n" + p["text"])
        elif msg and str(msg["chat"]["id"]) == CHAT() and msg.get("reply_to_message") and msg.get("text"):
            rid = msg["reply_to_message"]["message_id"]
            n = next((k for k, v in state["pending"].items() if rid in v["msg_ids"]), None)
            if n:
                t = msg["text"].strip()
                if t.startswith("="):      # «=текст» — свой текст целиком, без Claude
                    new = t[1:].strip()
                else:
                    new = revise(state["pending"][n]["text"], t)
                state["pending"][n]["text"] = new
                send_draft(n, new, "✏️ Новый вариант:\n\n")
        save()
    save()
