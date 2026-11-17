"""Minimal vision probe against the LiteLLM proxy (OpenAI chat format).

Usage: python3 -I probe_vision.py <image> <model> <task> [runs]
Reads LLM_SERVICE_API_KEY from the environment; never prints it.
"""
import base64
import json
import mimetypes
import os
import sys
import time
import urllib.request

img, model, task = sys.argv[1], sys.argv[2], sys.argv[3]
runs = int(sys.argv[4]) if len(sys.argv) > 4 else 1
key = os.environ.get("LLM_SERVICE_API_KEY", "")
mime = mimetypes.guess_type(img)[0] or "image/jpeg"
b64 = base64.b64encode(open(img, "rb").read()).decode()

CATALOG = ("Katalog (artikel_id: bezeichnung): "
           "4711: Kaffee Crema ganze Bohne 1 kg; 4712: Espresso gemahlen 500 g; "
           "2001: Bio Vollmilch 3,8% 1 l; 2002: H-Milch 1,5% 1 l; "
           "3050: Butter 250 g; 5100: Apfelsaft 1 l")
PROMPTS = {
    "identify": CATALOG + ". Welcher Artikel ist auf dem Bild? Antworte NUR mit JSON "
                "{\"artikel_id\": str|null, \"confidence\": 0..1, \"grund\": str}.",
    "competitor": "Das Foto zeigt ein Preisschild eines Wettbewerbers. Extrahiere NUR JSON "
                  "{\"haendler\": str, \"artikel\": str, \"preis_eur\": number, "
                  "\"grundpreis\": str, \"lesbar\": bool}.",
    "esl": "Erwartet: Artikel 'Kaffee Crema ganze Bohne 1 kg' mit neuem Preis 12,99 EUR. "
           "Pruefe das Etikett. Antworte NUR mit JSON {\"preis_gelesen_eur\": number, "
           "\"stimmt_ueberein\": bool, \"grund\": str}.",
}
body = {
    "model": model,
    "max_tokens": 300,
    "messages": [{"role": "user", "content": [
        {"type": "text", "text": PROMPTS[task]},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
    ]}],
}
data = json.dumps(body).encode()
if os.environ.get("DUMP_BODY"):
    open(os.environ["DUMP_BODY"], "wb").write(data)
    sys.exit(0)
for i in range(runs):
    req = urllib.request.Request(
        "https://lite-llm.mymaas.net/v1/chat/completions", data=data,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            res = json.load(r)
        dt = time.time() - t0
        u = res.get("usage", {})
        txt = res["choices"][0]["message"]["content"]
        print(json.dumps({"model": model, "task": task, "run": i + 1, "secs": round(dt, 2),
                          "img_bytes": len(b64) * 3 // 4,
                          "prompt_tokens": u.get("prompt_tokens"),
                          "completion_tokens": u.get("completion_tokens"),
                          "answer": txt.strip()[:300]}, ensure_ascii=False))
    except urllib.error.HTTPError as e:
        print(json.dumps({"model": model, "task": task, "run": i + 1,
                          "secs": round(time.time() - t0, 2), "http": e.code,
                          "error": e.read().decode(errors="replace")[:300]}))
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"model": model, "task": task, "run": i + 1,
                          "secs": round(time.time() - t0, 2), "error": repr(e)[:300]}))
