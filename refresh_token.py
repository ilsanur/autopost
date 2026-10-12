"""Продлевает токен ещё на 60 дней и сохраняет в секрет THREADS_TOKEN репозитория.
Нужны: THREADS_TOKEN, GH_PAT (токен GitHub с правом Secrets: write), GITHUB_REPOSITORY. Запускается из workflow."""
import base64, json, os, urllib.parse, urllib.request
from nacl import encoding, public

q = urllib.parse.urlencode({"grant_type": "th_refresh_token", "access_token": os.environ["THREADS_TOKEN"]})
new = json.load(urllib.request.urlopen(f"https://graph.threads.net/refresh_access_token?{q}"))["access_token"]

repo, h = os.environ["GITHUB_REPOSITORY"], {"Authorization": f"Bearer {os.environ['GH_PAT']}", "Accept": "application/vnd.github+json"}
def gh(method, path, body=None):
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/{path}", method=method, headers=h,
                                 data=json.dumps(body).encode() if body else None)
    return urllib.request.urlopen(req)
key = json.load(gh("GET", "actions/secrets/public-key"))
box = public.SealedBox(public.PublicKey(key["key"].encode(), encoding.Base64Encoder()))
enc = base64.b64encode(box.encrypt(new.encode())).decode()
gh("PUT", "actions/secrets/THREADS_TOKEN", {"encrypted_value": enc, "key_id": key["key_id"]})
print("Токен продлён и сохранён.")
