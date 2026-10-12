"""Один раз: превращает короткий токен (живёт 1 час) в долгий (60 дней).
Ничего не печатает на экран — готовый токен копируется в буфер обмена (pbcopy).
Запуск: python3 setup_token.py"""
import getpass, json, subprocess, sys, urllib.error, urllib.parse, urllib.request

short = getpass.getpass("Короткий токен из «Генератора маркеров» (ввод скрыт): ").strip()
secret = getpass.getpass("Секрет приложения Threads (Настройки приложения Threads → Секрет приложения Threads): ").strip()
q = urllib.parse.urlencode({"grant_type": "th_exchange_token", "client_secret": secret, "access_token": short})
try:
    r = json.load(urllib.request.urlopen(f"https://graph.threads.net/access_token?{q}"))
except urllib.error.HTTPError as e:
    sys.exit("Meta отклонила запрос: " + e.read().decode().replace(secret, "***").replace(short, "***"))
subprocess.run("pbcopy", input=r["access_token"].encode())
print(f"Готово. Долгий токен скопирован в буфер обмена, действует {r['expires_in']//86400} дней.")
print("Вставьте его (Cmd+V) в GitHub → Settings → Secrets → Actions → THREADS_TOKEN.")
