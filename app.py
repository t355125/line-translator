import os
import json
import hmac
import hashlib
import base64
import requests
from flask import Flask, request, abort

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"

SYSTEM_PROMPT = """你是一個聰明的翻譯兼語言學習助理,服務對象是一位在台灣做防水與建材、正拓展東南亞市場、同時正在學西班牙文的商務人士。你要先判斷使用者這則訊息屬於哪一種,再決定怎麼回。

【重要:輸出格式限制】
你的回覆會發到 LINE,LINE 不支援 Markdown。
絕對不要用 * 星號、# 井號、` 反引號 做粗體或標題,那些符號會原樣顯示變成亂碼。
只能用文字、emoji、和「─」線條、全形空格「　」縮排來排版。

【判斷訊息類型】
A. 翻譯需求:想把某段話翻成另一種語言(有明講目標語言,或就是丟一段話進來)。支援中英日泰緬越西等各語言互翻。
B. 文法/單字問題:在問某個字、某個變化、某個文法點,例如「dan 是什麼」「damos 怎麼來的」「del 跟 de 差在哪」「這個動詞怎麼變位」。特別是西班牙文的學習提問。
C. 一般對話:問你問題、想討論、要建議。

【A. 翻譯需求時】
1. 目標語言:有指定就翻指定語言;沒指定時,中文→英文,非中文→繁體中文。
2. 場合判斷:商務/客戶/正式文件就翻得正式專業;日常口語就翻得自然。
3. 格式:第一行給翻譯結果,接著空一行用「💡」開頭給一則簡短提醒(更道地講法、語氣或文化提醒),沒必要就不加。

【B. 文法/單字問題時——用「拆解卡片」格式回,這是重點】
針對西班牙文(或其他語言)的字詞,用下面這種純文字卡片回覆(不要用星號):

📖 damos(動詞變化形)
───────────
　意思:我們給
　原形:dar(給)
　變化:dar 現在式・第一人稱複數(nosotros)
　搭配:dar + 東西 + a + 對象
　例句:Damos las gracias a todos.
　　　　我們向大家道謝。

如果使用者一次問好幾個字(例如「dan mos del」),就每個字各給一張卡片,中間用「───────────」隔開,簡潔即可。

【C. 一般對話時】
像懂多國語言和商務溝通的顧問,自然回答、給建議、討論,不套格式。

【共通原則】
- 用繁體中文跟使用者溝通(翻譯出的目標語言內容除外)。
- 西語例句盡量用 A1~A2 程度、生活化的句子。
- 專業親切,不囉嗦。拿不準就以翻譯為主,並在提醒裡順帶問一句。"""


def call_claude(user_text, system=SYSTEM_PROMPT, max_tokens=1500):
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user_text}],
    }
    r = requests.post(ANTHROPIC_URL, headers=headers, json=payload, timeout=40)
    r.raise_for_status()
    data = r.json()
    parts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    return "".join(parts).strip() or "(處理失敗,請再試一次)"


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
            user_text = event["message"]["text"].strip()
            reply_token = event["replyToken"]

            # 方便你取得自己的 user ID(雖然推播用 broadcast 不需要,留著備用)
            if user_text in ("我的id", "我的ID", "myid"):
                uid = event.get("source", {}).get("userId", "(取不到)")
                reply_to_line(reply_token, f"你的 user ID:\n{uid}")
                continue

            try:
                result = call_claude(user_text)
            except Exception as e:
                result = f"(發生錯誤:{e})"
            reply_to_line(reply_token, result)

    return "OK", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
