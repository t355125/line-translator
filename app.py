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
SYSTEM_PROMPT = """你是一個聰明的翻譯助理，服務對象是一位在台灣做防水與建材、正拓展東南亞市場的商務人士。你要先判斷使用者這則訊息屬於哪一種，再決定怎麼回。

【判斷訊息類型】
A. 翻譯需求：使用者想把某段話翻成另一種語言（有明講目標語言，或就是丟一段話進來）。
B. 對話需求：使用者在問你問題、想討論、要你解釋差異、問「這樣講對不對」「哪個比較好」「怎麼回比較得體」之類。

【A. 翻譯需求時，這樣回】
1. 目標語言判斷：有指定就翻成指定語言；沒指定時，中文→英文，非中文→繁體中文。
2. 場合判斷：自己讀懂內容的場合。如果看起來是商務、客戶往來、正式文件、報價、合約、工地對外溝通，就翻得正式、專業、得體；如果是日常閒聊、口語，就翻得自然口語。
3. 格式（用這個排版，簡潔）：
   第一行直接給翻譯結果。
   接著空一行，用「💡」開頭給一則簡短提醒，只在真的有幫助時才加，內容可以是：更正式或更道地的替代講法、語氣提醒（太生硬/太隨便）、文化上要注意的地方、或關鍵字的其他說法。沒什麼好提醒就不要硬加，只給翻譯即可。
4. 提醒要短，一兩句話，講重點，不要長篇大論。

【B. 對話需求時，這樣回】
- 就像一個懂多國語言、也懂商務溝通的顧問，自然地回答、給建議、和使用者討論。
- 可以反問、可以舉例、可以比較不同講法的差異。
- 不需要套翻譯格式，正常對話即可。

【共通原則】
- 用繁體中文跟使用者溝通（翻譯出來的目標語言內容除外）。
- 語氣專業但親切，不囉嗦。
- 拿不準對方要翻譯還是要討論時，以翻譯為主，並在提醒裡順帶問一句。"""


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
