"""Бот автопостинга в Threads с подтверждением через Telegram.
  python3 post.py serve    — работает как бот: по расписанию шлёт черновики и мгновенно отвечает на кнопки и сообщения
  python3 post.py draft    — прислать один черновик сейчас
  python3 post.py preview  — показать следующий шаблонный пост в консоли
Переменные: THREADS_TOKEN, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, GITHUB_REPOSITORY, ANTHROPIC_API_KEY (для генерации и правок)."""
import json, os, signal, subprocess, sys, time, urllib.error, urllib.parse, urllib.request, random
from datetime import datetime, timedelta, timezone

here = os.path.dirname(os.path.abspath(__file__))
posts = json.load(open(f"{here}/posts.json", encoding="utf-8"))
state_path = f"{here}/state.json"
state = json.load(open(state_path)) if os.path.exists(state_path) else {}
for k, v in (("n", 0), ("offset", 0), ("pending", {}), ("rules", []), ("recent", []), ("done", [])):
    state.setdefault(k, v)
SLOTS = [(9, 30, "kk"), (12, 30, "ru"), (18, 30, "kk")]   # время Атырау (UTC+5)

# ---------- сохранение состояния ----------
_last = [None]
def save(): json.dump(state, open(state_path, "w"), ensure_ascii=False, indent=1)
def sync():
    """Сохраняет state.json и, если он изменился, коммитит в репозиторий (чтобы не терять между перезапусками)."""
    save()
    cur = json.dumps(state, sort_keys=True)
    if cur == _last[0] or not os.environ.get("GITHUB_ACTIONS"): _last[0] = cur; return
    _last[0] = cur
    sh = lambda *a: subprocess.run(a, cwd=here, capture_output=True)
    sh("git", "add", "state.json")
    if sh("git", "diff", "--cached", "--quiet").returncode:
        sh("git", "commit", "-m", "state")
        if sh("git", "push").returncode:
            sh("git", "pull", "--rebase", "-q"); sh("git", "push")

def http(url, data=None, headers={}):
    try:
        return json.load(urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=120))
    except urllib.error.HTTPError as e:
        sys.exit(f"Ошибка {e.code}: {e.read().decode()[:300]}")

# ---------- Telegram ----------
def tg(method, **p):
    p = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in p.items()}
    return http(f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/{method}", urllib.parse.urlencode(p).encode())["result"]
CHAT = lambda: os.environ["TELEGRAM_CHAT_ID"]
def say(text):
    try: tg("sendMessage", chat_id=CHAT(), text=text)
    except SystemExit: pass

def send_draft(n, note=""):
    p = state["pending"][n]
    for mid in p["msg_ids"]:      # убираем кнопки у старых версий, чтобы не путаться
        try: tg("editMessageReplyMarkup", chat_id=CHAT(), message_id=mid, reply_markup={"inline_keyboard": []})
        except SystemExit: pass
    kb = {"inline_keyboard": [[{"text": "✅ Опубликовать", "callback_data": f"ok:{n}"}],
                              [{"text": "🔄 Другой вариант", "callback_data": f"re:{n}"}, {"text": "⏭ Пропустить", "callback_data": f"no:{n}"}]]}
    m = tg("sendMessage", chat_id=CHAT(), text=note + p["text"], reply_markup=kb)
    p["msg_ids"] = [m["message_id"]]

# ---------- Claude ----------
FACTS = """БЦ «Нурсаулет», Атырау, Махамбет Өтемісов 100, первая линия главной улицы. Цена 6 000 ₸ за м² в месяц; в стоимость включены
коммуналка, мебель, ежедневная уборка. Свежий ремонт, светлые тона, потолки 3,2 м, сплит-система в каждом помещении, два этажа,
несколько отдельных входов, автономное отопление (зимой тепло), охрана, сигнализация, видеонаблюдение, решётки на окнах, пожарная сигнализация.
Свет, вода, газ, канализация, отопление, вентиляция. Бесплатная парковка на территории под круглосуточным видеонаблюдением.
Рядом остановки, супермаркет, кофейни, клиника. Контакт: WhatsApp +7 702 494 7000."""
ANGLES = ["забавный: лёгкая самоирония или шутка про офисную жизнь", "первая строка — вопрос к аудитории", "цена и что в неё входит, без скрытых платежей",
          "расположение: первая линия, парковка, кофейни, остановки", "для кого подходит этот кабинет по площади", "тепло зимой, безопасность, спокойствие",
          "заехал и сразу работаешь: ремонт, мебель, кондиционер", "мини-сценка из жизни арендатора, с юмором"]

def claude(system, user):
    r = http("https://api.anthropic.com/v1/messages", json.dumps({"model": "claude-sonnet-5-5", "max_tokens": 1000, "system": system,
             "messages": [{"role": "user", "content": user}]}).encode(),
             {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01", "content-type": "application/json"})
    return r["content"][0]["text"].strip()

def system_prompt():
    rules = "\n".join(f"- {r}" for r in state["rules"])
    return ("Ты пишешь посты для Threads об аренде офисов. Пиши естественно, живо, как человек, без канцелярита и шаблонных фраз. "
            "Используй только факты из списка, ничего не выдумывай. В конце поста: адрес, WhatsApp, один хэштег. Не длиннее 480 символов. "
            "Верни только готовый текст поста.\n\nФакты:\n" + FACTS + ("\n\nПостоянные правила владельца (соблюдай всегда):\n" + rules if rules else ""))

def short(text, user, user_extra=""):
    for _ in range(3):
        out = claude(system_prompt(), user + user_extra)
        if len(out) <= 500: return out
        user_extra = "\n(Слишком длинно: сократи строго до 400 символов.)"
    return out[:500]

def generate(lang, cab, angle=None):
    info = posts["info"][cab]
    n = state["n"]
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            angle = ANGLES[(n if angle is None else angle) % len(ANGLES)]
            recent = "\n---\n".join(state["recent"][-5:])
            return short(None, f"Напиши новый пост на {'русском' if lang == 'ru' else 'казахском'} языке про {info[lang]}. Цена {info['total']} ₸ в месяц. "
                         f"Подходит: {info['who_' + lang]}. Подход: {angle}.\nНе повторяй недавние посты:\n{recent}")
        except SystemExit as e:
            say(f"⚠️ Claude не ответил ({e.code}). Беру готовый шаблон.")
    k = len(posts[lang][cab]); return posts[lang][cab][(n if angle is None else angle) % k]

def revise(text, instruction):
    return short(None, f"Текущий пост:\n{text}\n\nПросьба владельца: {instruction}\nПерепиши пост с учётом просьбы, сохрани язык.")

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

# ---------- логика бота ----------
def make_draft(lang):
    n = state["n"]; cab = posts["cabinets"][(n // 3) % len(posts["cabinets"])]
    text = generate(lang, cab)
    state["pending"][str(n)] = {"cab": cab, "lang": lang, "text": text, "msg_ids": []}
    state["n"] = n + 1
    send_draft(str(n)); sync()

def check_schedule():
    now = datetime.now(timezone.utc) + timedelta(hours=5)
    for i, (h, m, lang) in enumerate(SLOTS):
        key, due = f"{now:%Y-%m-%d}#{i}", now.replace(hour=h, minute=m, second=0, microsecond=0)
        if key in state["done"] or now < due: continue
        state["done"] = (state["done"] + [key])[-30:]; sync()
        if now - due < timedelta(hours=3): make_draft(lang)

HELP = ("Как пользоваться:\n• Кнопки под черновиком: опубликовать, другой вариант, пропустить.\n"
        "• Чтобы изменить текст, просто напишите, что поправить («короче», «добавь про парковку», «смешнее»). Reply не нужен.\n"
        "• Свой текст целиком: начните сообщение со знака =\n• /правило ТЕКСТ: запомнить постоянное правило для всех постов (например, «без эмодзи»)\n"
        "• /правила: показать правила, /сброс: удалить их\n• /черновик ru или /черновик kk: прислать новый черновик сейчас")

def latest(reply_to=None):
    if reply_to:
        for k, v in state["pending"].items():
            if reply_to in v["msg_ids"]: return k
    return max(state["pending"], key=int) if state["pending"] else None

def on_message(msg):
    t = (msg.get("text") or "").strip()
    if not t: return
    low = t.lower()
    if low in ("/start", "/help", "/помощь"): return say(HELP)
    if low.startswith("/правила"): return say("Правила:\n" + ("\n".join(f"• {r}" for r in state["rules"]) or "пока нет"))
    if low.startswith("/сброс"): state["rules"] = []; return say("Правила удалены.")
    if low.startswith("/правило"):
        r = t[len("/правило"):].strip()
        if r: state["rules"].append(r); return say(f"Запомнил: {r}")
        return say("Напишите правило после команды, например: /правило без эмодзи")
    if low.startswith("/черновик") or low.startswith("/new"):
        lang = "kk" if "kk" in low or "каз" in low else "ru"
        return make_draft(lang)
    n = latest((msg.get("reply_to_message") or {}).get("message_id"))
    if n is None: return say("Сейчас нет черновиков. Напишите /черновик ru или /черновик kk.")
    p = state["pending"][n]
    if t.startswith("="): p["text"] = t[1:].strip()
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"): return say("Для правок нужен ключ ANTHROPIC_API_KEY в секретах GitHub.")
        say("✍️ Переписываю…")
        p["text"] = revise(p["text"], t)
    send_draft(n, "✏️ Новый вариант:\n\n")

def on_callback(cb):
    act, n = cb["data"].split(":"); mid = cb["message"]["message_id"]
    try: tg("answerCallbackQuery", callback_query_id=cb["id"])
    except SystemExit: pass
    p = state["pending"].get(n)
    if not p:
        try: tg("editMessageReplyMarkup", chat_id=CHAT(), message_id=mid, reply_markup={"inline_keyboard": []})
        except SystemExit: pass
        return
    if act == "no":
        state["pending"].pop(n); tg("editMessageText", chat_id=CHAT(), message_id=mid, text="⏭ Пропущено\n\n" + p["text"])
    elif act == "re":
        p["text"] = generate(p.get("lang", "ru"), p["cab"], random.randrange(100)); send_draft(n, "🔄 Другой вариант:\n\n")
    elif act == "ok":
        tg("editMessageText", chat_id=CHAT(), message_id=mid, text="⏳ Публикую, это займёт до минуты…\n\n" + p["text"])
        try:
            publish(p["cab"], p["text"])
        except SystemExit as e:
            kb = {"inline_keyboard": [[{"text": "✅ Попробовать ещё раз", "callback_data": f"ok:{n}"}]]}
            tg("editMessageText", chat_id=CHAT(), message_id=mid, text=f"⚠️ Не получилось опубликовать: {e.code}\n\n" + p["text"], reply_markup=kb)
            return
        state["pending"].pop(n); state["recent"] = (state["recent"] + [p["text"]])[-8:]
        tg("editMessageText", chat_id=CHAT(), message_id=mid, text="✅ Опубликовано\n\n" + p["text"])

def handle(u):
    if u.get("callback_query") and str(u["callback_query"]["message"]["chat"]["id"]) == CHAT(): on_callback(u["callback_query"])
    elif u.get("message") and str(u["message"]["chat"]["id"]) == CHAT(): on_message(u["message"])

def serve(hours=5.8):
    end = time.time() + hours * 3600
    signal.signal(signal.SIGTERM, lambda *a: (sync(), sys.exit(0)))
    print("Бот запущен")
    while time.time() < end:
        try:
            check_schedule()
            ups = tg("getUpdates", offset=state["offset"], timeout=25, allowed_updates=["callback_query", "message"])
        except SystemExit as e:
            print(e); time.sleep(5); continue
        for u in ups:
            state["offset"] = u["update_id"] + 1; sync()     # сначала помечаем прочитанным, чтобы не было дублей
            try: handle(u)
            except SystemExit as e: say(f"⚠️ Ошибка: {e.code}")
            except Exception as e: say(f"⚠️ Ошибка: {e!r}")
            sync()
    sync()

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "preview"
    if cmd == "serve": serve()
    elif cmd == "draft": make_draft(sys.argv[2] if len(sys.argv) > 2 else "ru")
    else:
        n = state["n"]; cab = posts["cabinets"][(n // 3) % len(posts["cabinets"])]
        print(generate("ru", cab))
