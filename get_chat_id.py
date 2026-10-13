"""Показывает ваш Telegram Id. Сначала напишите своему боту любое сообщение (например, «привет»).
Запуск: python3 get_chat_id.py"""
import getpass, json, urllib.request
token = getpass.getpass("Токен бота от BotFather (ввод скрыт): ").strip()
r = json.load(urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getUpdates"))["result"]
people = {}
for u in r:
    m = u.get("message") or (u.get("callback_query") or {}).get("message")
    if m and not m["chat"].get("is_bot"): people[m["chat"]["id"]] = m["chat"].get("first_name", "")
if not people:
    print("Сообщений нет. Откройте своего бота, нажмите Start, напишите «привет» и запустите скрипт ещё раз.")
for cid, name in people.items():
    print(f"Ваш Id: {cid}  ({name})  ← вставьте это число в TELEGRAM_CHAT_ID")
