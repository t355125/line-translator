import os
import json
import datetime
import random
import re
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

重要:回傳「純 JSON」,不要任何開場白、不要 markdown 反引號。
另外:西班牙文的重音字母(á é í ó ú)、ñ、¿ ¡ 一定要完整正確寫出,絕不可省略或用普通字母代替(要寫 está、español、año,不是 esta、espanol、ano)。
格式如下:
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
    if r.status_code >= 400:
        # 把 API 回的錯誤原因印出來(不含金鑰),方便在 Actions log 看到真正原因
        print("Anthropic API error:", r.status_code, r.text[:600])
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
        block = f"{n}  {c['word']}  【{c.get('pos','')}】\n"
        block += f"\u3000📌 {c.get('meaning','')}"
        if c.get("detail"):
            block += f"\n\u3000📝 {c['detail']}"
        if c.get("example_es"):
            block += f"\n\u3000💬 {c['example_es']}"
            if c.get("example_zh"):
                block += f"\n\u3000\u3000\u3000{c['example_zh']}"
        lines.append(block)
    return "\n\n".join(lines)


def short_date(d):
    """2026-10-11 -> 10/11"""
    if d and len(d) >= 10:
        return d[5:7] + "/" + d[8:10]
    return ""


def format_review(items, default_date=""):
    """複習清單:只列單字+意思,並注記『已學過』與學習日期"""
    lines = []
    for c in items:
        d = short_date(c.get("date") or default_date)
        tag = f"✓已學過 {d}" if d else "✓已學過"
        lines.append(f"\u3000• {c['word']} —— {c.get('meaning','')}　{tag}")
    return "\n".join(lines)


def build_button_flex(title, subtitle, url):
    """一張帶按鈕的 Flex 卡片,網址藏在按鈕背後,不顯示"""
    return {
        "type": "flex",
        "altText": title,
        "contents": {
            "type": "bubble",
            "body": {
                "type": "box", "layout": "vertical", "spacing": "md",
                "contents": [
                    {"type": "text", "text": title, "weight": "bold",
                     "size": "lg", "color": "#c0623f", "wrap": True},
                    {"type": "text", "text": subtitle, "size": "sm",
                     "color": "#8a8478", "wrap": True},
                ],
            },
            "footer": {
                "type": "box", "layout": "vertical",
                "contents": [
                    {"type": "button", "style": "primary", "color": "#c0623f",
                     "action": {"type": "uri", "label": "\U0001f4d6 \u6253\u958b\u55ae\u5b57\u5eab", "uri": url}},
                ],
            },
        },
    }


def broadcast_messages(text, flex=None):
    """flex(按鈕卡片)在前,文字內容在後,一次發出。LINE 一次最多 5 則。"""
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    messages = []
    if flex:
        messages.append(flex)
    # 文字太長自動切段,連同 flex 總數不超過 5 則
    room = 5 - len(messages)
    chunks = [text[i:i+4900] for i in range(0, len(text), 4900)][:room]
    messages += [{"type": "text", "text": c} for c in chunks]
    payload = {"messages": messages}
    r = requests.post(LINE_BROADCAST_URL, headers=headers, json=payload, timeout=20)
    r.raise_for_status()


POOL_FILE = "words_pool.json"   # 單字池(來自網站主題字彙,約 900 字)
_ART = re.compile(r"^(el|la|los|las|un|una)(/(el|la|los|las))?\s+")

GENDER_HINT = {
    "m": "陽性名詞", "f": "陰性名詞", "mf": "陰陽同形名詞",
    "adj": "形容詞", "v": "動詞", "adv": "副詞", "x": "片語或其他詞類",
}

CARD_PROMPT_HEAD = """你是西班牙文老師。下面是今天要教一位台灣學習者的單字(A1~A2),每行格式:編號. 西語 | 中文意思 | 詞性提示。
請為每一個字做一張學習卡。

重要:回傳「純 JSON」,不要開場白、不要 markdown 反引號。
西班牙文的重音字母(á é í ó ú)、ñ、¿ ¡ 一定要完整正確寫出,不可省略。
每張卡的 "word" 必須和我給的西語完全一樣(包含 el/la 冠詞),不要改寫。格式:
{
  "cards": [
    {
      "word": "desayunar",
      "pos": "動詞",
      "meaning": "吃早餐",
      "detail": "變化:desayuno(我)/ desayunas(你)",
      "example_es": "Desayuno pan con café.",
      "example_zh": "我吃麵包配咖啡。"
    }
  ]
}
要求:
- 照我給的順序,每個字一張卡,不要少、不要多。
- meaning 以我給的中文為準,可以補充用法。
- 名詞的 detail 標陰陽性與單複數(如「陰性 la tienda / las tiendas」);動詞的 detail 標現在式常用變化;形容詞標陰陽性形式。
- example 用 A1~A2 生活化短句。
- 只輸出 JSON。

今天的單字:
"""


def norm(w):
    """去掉冠詞、轉小寫,用來比對同一個字"""
    w = (w or "").lower().strip()
    return _ART.sub("", w).strip()


def pick_from_pool(pool, used_norm, n=10):
    """從單字池挑 n 個沒學過的字,盡量分散在不同主題"""
    by_theme = {}
    for p in pool:
        if norm(p.get("word", "")) in used_norm:
            continue
        by_theme.setdefault(p.get("theme", ""), []).append(p)
    unused_total = sum(len(v) for v in by_theme.values())
    themes = list(by_theme.keys())
    random.shuffle(themes)
    for t in themes:
        random.shuffle(by_theme[t])
    picked = []
    while len(picked) < n and themes:
        for t in list(themes):
            if by_theme[t]:
                picked.append(by_theme[t].pop())
                if len(picked) >= n:
                    break
            else:
                themes.remove(t)
    return picked, unused_total - len(picked)


def fallback_card(p):
    return {
        "word": p["word"],
        "pos": GENDER_HINT.get(p.get("gender", ""), ""),
        "meaning": p.get("meaning", ""),
        "detail": "",
        "example_es": "",
        "example_zh": "",
    }


def generate_cards_for(items):
    """請 AI 為指定的單字做學習卡;AI 失敗或漏字時,用單字池本身的資料補上"""
    prompt = CARD_PROMPT_HEAD + "\n".join(
        f"{i}. {p['word']} | {p.get('meaning','')} | {GENDER_HINT.get(p.get('gender',''), '')}"
        for i, p in enumerate(items, 1)
    )
    data = []
    try:
        data = call_claude_json(prompt, max_tokens=3500).get("cards", [])
    except Exception as e:
        print("card generation failed, using fallback:", e)
    by_norm = {norm(c.get("word", "")): c for c in data if isinstance(c, dict)}
    cards = []
    for p in items:
        c = by_norm.get(norm(p["word"]))
        if c:
            c = dict(c)
            c["word"] = p["word"]  # 與單字池一致,網頁才對得上「已收錄」
            if not c.get("meaning"):
                c["meaning"] = p.get("meaning", "")
            c.setdefault("pos", GENDER_HINT.get(p.get("gender", ""), ""))
        else:
            c = fallback_card(p)
        cards.append(c)
    return cards


def generate_free_cards(used_words, need):
    """單字池用完時的備案:請 AI 自由出題,並避開已出過的字"""
    used_norm = set(norm(w) for w in used_words)
    got, have = [], set()
    for _ in range(3):
        if len(got) >= need:
            break
        recent = list(used_words)[-200:]
        avoid = ("\n\n【非常重要:以下這些字已經出過了,絕對不要再出,請出完全不同的新字】\n"
                 + "、".join(recent))
        try:
            cards = call_claude_json(NEW_VOCAB_PROMPT + avoid)["cards"]
        except Exception as e:
            print("free generation failed:", e)
            break
        for c in cards:
            n = norm(c.get("word", ""))
            if n and n not in used_norm and n not in have:
                got.append(c)
                have.add(n)
            if len(got) >= need:
                break
    return got[:need]


def pick_older_review(library, today, exclude_norm, k=5):
    """從更早學過的字(3 天前以前)隨機抽 k 個來複習"""
    cutoff = (today - datetime.timedelta(days=3)).strftime("%Y-%m-%d")
    olds = [x for x in library
            if x.get("date", "9999-99-99") <= cutoff
            and norm(x.get("word", "")) not in exclude_norm]
    random.shuffle(olds)
    return olds[:k]


def main():
    today = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    date_str = today.strftime("%Y-%m-%d")

    state = load_json(STATE_FILE, {"morning": None, "evening": None})
    library = load_json(VOCAB_FILE, [])
    pool = load_json(POOL_FILE, [])

    used_words = [x.get("word", "") for x in library if x.get("word")]
    used_norm = set(norm(w) for w in used_words)

    # 1. 今天的新單字:優先從單字池抽「沒學過」的 10 個
    picked, remaining = pick_from_pool(pool, used_norm, 10)
    new_cards = generate_cards_for(picked) if picked else []

    # 2. 單字池不夠 10 個時,用 AI 自由出題補齊
    if len(new_cards) < 10:
        have_words = used_words + [c["word"] for c in new_cards]
        new_cards += generate_free_cards(have_words, 10 - len(new_cards))
    new_cards = new_cards[:10]

    # 3. 複習:上一批 + 更早學過的隨機幾個,都注記「已學過」
    if SLOT == "morning":
        review_batch = state.get("evening")
        review_label = "複習昨天下午"
        title = "🌅 早安!今日西語單字"
    else:
        review_batch = state.get("morning")
        review_label = "複習今天早上"
        title = "🌆 午後西語時間"

    prev_cards = (review_batch or {}).get("cards") or []
    prev_date = (review_batch or {}).get("date", "")
    exclude = set(norm(c.get("word", "")) for c in prev_cards)
    exclude |= set(norm(c.get("word", "")) for c in new_cards)
    older = pick_older_review(library, today, exclude, 5)

    web_url = "https://t355125.github.io/line-translator/"
    flex = build_button_flex(
        title,
        f"{date_str}｜累積已有 {len(library) + len(new_cards)} 字",
        web_url,
    )

    parts = []
    if prev_cards:
        parts.append(f"🔁 {review_label}（已學過，考考自己）\n{format_review(prev_cards, prev_date)}")
    if older:
        parts.append(f"\n🔁 更早學過的（隨機抽 {len(older)} 個）\n{format_review(older)}")
    parts.append(f"\n───  ✨ 今日新單字  ───\n\n{format_full(new_cards)}")
    footer = "\n\n"
    if pool:
        footer += f"📚 單字池還剩 {max(remaining, 0)} 個沒學過的字\n"
    footer += "💪 ¡Ánimo!"
    parts.append(footer)
    message = "\n".join(parts)

    broadcast_messages(message, flex=flex)

    # 4. 存檔:這批成為下次的複習對象,並累積進單字庫
    state[SLOT] = {"date": date_str, "cards": new_cards}
    save_json(STATE_FILE, state)

    existing = set(norm(x.get("word", "")) for x in library)
    for c in new_cards:
        n = norm(c.get("word", ""))
        if n and n not in existing:
            library.append({
                "word": c["word"],
                "pos": c.get("pos", ""),
                "meaning": c.get("meaning", ""),
                "date": date_str,
            })
            existing.add(n)
    save_json(VOCAB_FILE, library)

    os.makedirs("docs", exist_ok=True)
    save_json("docs/vocab.json", library)

    print(f"[{SLOT}] done: {len(new_cards)} new words, library has {len(library)} words, pool remaining {remaining}")


if __name__ == "__main__":
    main()
