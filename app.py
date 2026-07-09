import os
import json
import hmac
import hashlib
import base64
import requests
from flask import Flask, request, abort

app = Flask(__name__)

# ---- 環境變數（部署時在 Render 設定，不要寫死在程式裡）----
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"

# ---- 翻譯用的指令，Claude 會理解意圖再翻 ----
SYSTEM_PROMPT = """你是一個翻譯助手。使用者會傳一句話給你，內容可能包含：
- 明確指定目標語言，例如「幫我把這句翻成英文：...」「這句英文翻成日文：...」「泰文怎麼說...」
- 或只給一段文字，沒明講要翻成什麼

規則：
1. 如果使用者有指定目標語言，就翻成那個語言。
2. 如果沒指定目標語言，且原文是中文，就翻成英文；如果原文不是中文，就翻成繁體中文。
3. 只回傳翻譯後的結果，不要加任何解釋、拼音、標註或多餘的話。
4. 如果一句話裡有多種語言互翻的需求，理解意圖後照做。
5. 保持語氣自然、道地，符合該語言母語者的習慣。"""


def call_claude(user_text):
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 1024,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_text}],
    }
    r = requests.post(ANTHROPIC_URL, headers=headers, json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()
    parts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    return "".join(parts).strip() or "（翻譯失敗，請再試一次）"


def reply_to_line(reply_token, text):
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text[:4900]}],
    }
    requests.post(LINE_REPLY_URL, headers=headers, json=payload, timeout=15)


def verify_signature(body_bytes, signature):
    mac = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"), body_bytes, hashlib.sha256
    ).digest()
    expected = base64.b64encode(mac).decode("utf-8")
    return hmac.compare_digest(expected, signature or "")


@app.route("/", methods=["GET"])
def health():
    return "OK", 200


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data()

    if not verify_signature(body, signature):
        abort(400)

    events = json.loads(body).get("events", [])
    for event in events:
        if event.get("type") == "message" and event["message"].get("type") == "text":
            user_text = event["message"]["text"]
            reply_token = event["replyToken"]
            try:
                result = call_claude(user_text)
            except Exception as e:
                result = f"（發生錯誤：{e}）"
            reply_to_line(reply_token, result)

    return "OK", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
