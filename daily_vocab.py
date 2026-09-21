import os
import json
import datetime
import requests

LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
# 由 workflow 傳入 "morning" 或 "evening"
SLOT = os.environ.get("SLOT", "morning")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
LINE_BROADCAST_URL = "https://api.line.me/v2/bot/message/broadcast"

VOCAB_FILE = "vocab_library.json"   # 累積單字庫(所有出過的字)
STATE_FILE = "last_batches.json"    # 記住早上/下午最近一批,供複習用


NEW_VOCAB_PROMPT = """請幫一位正在學西班牙文的台灣人,出 10 個西班牙文單字(A1~A2 程度)。

重要:回傳「純 JSON」,不要任何開場白、不要 markdown 反引號。格式如下:
{
  "cards": [
    {
      "word": "desayunar",
      "pos": "動詞",
      "meaning": "吃早餐",
      "detail": "變化:desayuno(我)/ desayunas(你)",
      "example_es": "Desayuno pan con cafe.",
      "example_zh": "我吃麵包配咖啡。"
    }
  ]
}
要求:
- 10 個字,動詞名詞常用字混搭,生活化、盡量每天不同。
- 名詞的 detail 標陰陽性與單複數(如「陰性 la tienda / las tiendas」)。
- 動詞的 detail 標現在式常用變化。
- example 用 A1~A2 生活化短句。
- 只輸出 JSON。"""


def call_claude_json(prompt, max_tokens=2500):
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    r = requests.post(ANTHROPIC_URL, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    text = "".join(b["text"] for b in data.get("content", []) if b.get("type") == "text").strip()
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


NUM = ["1\ufe0f\u20e3", "2\ufe0f\u20e3", "3\ufe0f\u20e3", "4\ufe0f\u20e3", "5\ufe0f\u20e3", "6\ufe0f\u20e3", "7\ufe0f\u20e3", "8\ufe0f\u20e3", "9\ufe0f\u20e3", "\U0001f51f"]


def format_full(cards):
    lines = []
    for i, c in enumerate(cards):
        n = NUM[i] if i < len(NUM) else f"{i+1}."
        block = f"{n} {c['word']}({c['pos']})\n"
        block += f"\u3000\u610f\u601d:{c['meaning']}\n"
        if c.get("detail"):
            block += f"\u3000{c['detail']}\n"
        block += f"\u3000\u4f8b\u53e5:{c['example_es']}\n"
        block += f"\u3000\u3000\u3000\u3000{c['example_zh']}"
        lines.append(block)
    return "\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n".join(lines)


def format_review(cards):
    lines = []
    for i, c in enumerate(cards):
        lines.append(f"\u3000{i+1}. {c['word']} \u2014 {c['meaning']}")
    return "\n".join(lines)


def broadcast(text):
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    chunks = [text[i:i+4900] for i in range(0, len(text), 4900)][:5]
    messages = [{"type": "text", "text": c} for c in chunks]
    payload = {"messages": messages}
    r = requests.post(LINE_BROADCAST_URL, headers=headers, json=payload, timeout=20)
    r.raise_for_status()


def main():
    today = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    date_str = today.strftime("%Y-%m-%d")

    state = load_json(STATE_FILE, {"morning": None, "evening": None})
    library = load_json(VOCAB_FILE, [])

    new_cards = call_claude_json(NEW_VOCAB_PROMPT)["cards"]

    if SLOT == "morning":
        review_batch = state.get("evening")
        review_label = "\u8907\u7fd2\u6628\u5929\u4e0b\u5348"
        title = "\U0001f305 \u65e9\u5b89!\u4eca\u65e5\u897f\u8a9e\u55ae\u5b57"
    else:
        review_batch = state.get("morning")
        review_label = "\u8907\u7fd2\u4eca\u5929\u65e9\u4e0a"
        title = "\U0001f306 \u5348\u5f8c\u897f\u8a9e\u6642\u9593"

    parts = [f"{title}({date_str})\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"]
    if review_batch and review_batch.get("cards"):
        parts.append(f"\n\U0001f501 {review_label}(\u5148\u81ea\u5df1\u60f3\u60f3\u610f\u601d):\n{format_review(review_batch['cards'])}")
        parts.append("\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501")
    parts.append(f"\n\u2728 \u65b0\u55ae\u5b57 10 \u500b:\n{format_full(new_cards)}")
    parts.append("\n\n\U0001f4aa \u00a1\u00c1nimo! \u7d2f\u7a4d\u5c31\u662f\u5be6\u529b\u3002\u5b8c\u6574\u55ae\u5b57\u5eab\u770b\u7db2\u9801\u3002")
    message = "\n".join(parts)

    broadcast(message)

    state[SLOT] = {"date": date_str, "cards": new_cards}
    save_json(STATE_FILE, state)

    existing_words = {item["word"] for item in library}
    for c in new_cards:
        if c["word"] not in existing_words:
            library.append({
                "word": c["word"],
                "pos": c["pos"],
                "meaning": c["meaning"],
                "date": date_str,
            })
            existing_words.add(c["word"])
    save_json(VOCAB_FILE, library)

    # 輸出一份給網頁讀(docs/ 是 GitHub Pages 網站根目錄)
    os.makedirs("docs", exist_ok=True)
    save_json("docs/vocab.json", library)

    print(f"[{SLOT}] done, library has {len(library)} words")


if __name__ == "__main__":
    main()
