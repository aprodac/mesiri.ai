"""Small Sarvam helpers for the training video (translate, speak, transcribe). The key is added by the proxy."""
import base64, json, ssl, time, urllib.request, uuid

CTX = ssl.create_default_context(cafile="/root/.ccr/ca-bundle.crt")
H = {"api-subscription-key": "set-by-proxy"}


def _post(path, body, files=None, tries=4):
    for i in range(tries):
        try:
            if files is None:
                req = urllib.request.Request(f"https://api.sarvam.ai{path}", data=json.dumps(body).encode(),
                                             headers={**H, "content-type": "application/json"})
            else:
                b = uuid.uuid4().hex
                parts = []
                for k, v in body.items():
                    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
                for k, (name, data, ctype) in files.items():
                    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\nContent-Type: {ctype}\r\n\r\n'.encode() + data + b"\r\n")
                parts.append(f"--{b}--\r\n".encode())
                req = urllib.request.Request(f"https://api.sarvam.ai{path}", data=b"".join(parts),
                                             headers={**H, "content-type": f"multipart/form-data; boundary={b}"})
            return json.load(urllib.request.urlopen(req, context=CTX, timeout=120))
        except urllib.error.HTTPError as e:
            msg = e.read()[:400]
            if e.code in (429, 500, 502, 503) and i < tries - 1:
                time.sleep(2 ** (i + 1)); continue
            raise RuntimeError(f"{path} {e.code} {msg}")
        except Exception:
            if i < tries - 1:
                time.sleep(2 ** (i + 1)); continue
            raise


def translate(text, mode="code-mixed"):
    return _post("/translate", {"input": text, "source_language_code": "en-IN", "target_language_code": "ml-IN",
                                "model": "mayura:v1", "mode": mode})["translated_text"]


def speak(text, path, speaker="kavitha", pace=1.0):
    d = _post("/text-to-speech", {"text": text, "target_language_code": "ml-IN", "model": "bulbul:v3",
                                  "speaker": speaker, "pace": pace, "speech_sample_rate": 24000})
    open(path, "wb").write(base64.b64decode("".join(d["audios"])))


def transcribe(path):
    data = open(path, "rb").read()
    return _post("/speech-to-text", {"model": "saarika:v2.5", "language_code": "ml-IN"},
                 files={"file": ("a.wav", data, "audio/wav")}).get("transcript")
