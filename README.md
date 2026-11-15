<p align="center">
  <img src="installer/assets/ovozlab.png" width="72" alt="OvozLab">
</p>

<h1 align="center">OvozLab</h1>

<p align="center">
  O'zbek tili uchun ochiq kodli <b>matndan nutq</b>, <b>ovoz klonlash</b> va <b>nutqdan matn</b>.<br>
  Hammasi kompyuteringizda, internetsiz va bepul ishlaydi.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/litsenziya-Apache--2.0-black" alt="Apache-2.0"></a>
  <img src="https://img.shields.io/badge/platforma-Windows%2010%2F11-black" alt="Windows">
  <img src="https://img.shields.io/badge/python-3.12-black" alt="Python 3.12">
</p>

---

## Imkoniyatlar

- **Matndan nutq.** O'zbekcha matnni tabiiy ovozga aylantiradi. 5 000 belgigacha matn qabul qiladi, uzun matnni o'zi bo'laklarga ajratadi.
- **Ovoz klonlash.** 5–15 soniyalik yozuvdan istalgan ovozni nusxalaydi. Yozib olishda o'qish uchun tayyor matnlar chiqadi: oddiy, quvnoq, jiddiy, g'amgin va hikoyachi ohangida.
- **Nutqdan matn.** 60 daqiqagacha audio yoki videoni matnga o'giradi. Natijani TXT yoki SRT subtitr qilib saqlash mumkin.
- **Ovoz uslubi.** Jins, yosh, ovoz balandligi va shivirlash.
- **Maxfiylik.** Matn va ovozlaringiz kompyuterdan tashqariga chiqmaydi.
- **Lokal API.** Boshqa dasturlarga ulash uchun REST API va Swagger hujjatlari bor.

## O'rnatish (oddiy foydalanuvchilar uchun)

1. [Releases](https://github.com/ovozlab/ovozlab/releases) sahifasidan `OvozLab-Setup-x.y.z.exe` faylini yuklab oling.
2. Uni ishga tushiring. Administrator huquqi kerak emas. O'rnatuvchi Python va asosiy komponentlarni yuklaydi (~120 MB).
3. OvozLab'ni oching. **O'rnatish ustasi** quyidagilarni bajaradi:
   - videokartangizni aniqlaydi (Intel Arc, NVIDIA yoki CPU) va mos dvigatelni tavsiya qiladi;
   - modellar qayerga saqlanishini tanlatadi va bo'sh joyni ko'rsatadi;
   - nima yuklanishi, hajmi va joyini ko'rsatadi, keyin yuklab oladi.

| Komponent | Hajmi | Joylashuvi |
|---|---|---|
| PyTorch (Intel Arc / NVIDIA / CPU) | 3.9 / 4.6 / 0.9 GB | ilova papkasi |
| OmniVoice — nutq sintezi modeli | 3.3 GB | siz tanlagan papka |
| O'zbekcha Whisper (ixtiyoriy) | 3.1 GB | siz tanlagan papka |

**Tizim talablari:** Windows 10 (1809+) yoki 11, 64-bit, 16 GB RAM tavsiya etiladi, 10–12 GB bo'sh joy.
Intel Arc yoki NVIDIA videokarta tavsiya etiladi. CPU'da ham ishlaydi, lekin 5–10 baravar sekin.

## Dasturchilar uchun

Talablar: [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/ovozlab/ovozlab.git
cd ovozlab
uv sync --extra xpu      # Intel Arc   |  --extra cuda (NVIDIA)  |  --extra cpu
uv run python -m ovozlab # ilova oynasi
```

Faqat server (oynasiz), masalan Linux serverda:

```bash
uv run uvicorn ovozlab.server:app --host 127.0.0.1 --port 8000
```

Keyin brauzerda http://127.0.0.1:8000 manzilini oching. Birinchi ochilishda o'rnatish ustasi modellarni yuklaydi.

### O'rnatuvchini yig'ish

```bash
winget install JRSoftware.InnoSetup
powershell -ExecutionPolicy Bypass -File installer\build.ps1
```

Natija: `installer\Output\OvozLab-Setup-<versiya>.exe`.

## API

Server ishlayotganda to'liq hujjat `/docs` manzilida bo'ladi. Asosiy endpointlar:

| Metod | Yo'l | Vazifasi |
|---|---|---|
| `POST` | `/tts` | Matndan audio (JSON: `text`, `voice_id`, `speed`, `num_step`, `instruct`, `format`) |
| `POST` | `/clone` | Ovoz profilini yaratish (multipart: `audio`, `ref_text` ixtiyoriy, `name`) |
| `GET` / `PATCH` / `DELETE` | `/voices/{id}` | Ovozni ko'rish, nomini o'zgartirish, o'chirish |
| `POST` | `/stt` | Nutqdan matn (multipart: `audio`), vaqt belgilari bilan |
| `GET` | `/history` | Yaratilgan audiolar tarixi |

```bash
curl -X POST http://127.0.0.1:8000/tts -H "Content-Type: application/json" \
  -d "{\"text\": \"Assalomu alaykum!\", \"voice_id\": \"dilshod-3fa9c1\", \"format\": \"mp3\"}" -o salom.mp3
```

```python
import requests
API = "http://127.0.0.1:8000"
with open("men.wav", "rb") as f:
    voice = requests.post(f"{API}/clone", files={"audio": f}, data={"name": "Dilshod"}).json()
audio = requests.post(f"{API}/tts", json={"text": "Bugun havo ajoyib.", "voice_id": voice["id"]})
open("natija.wav", "wb").write(audio.content)
```

## Ko'p so'raladigan savollar

**Nega reference 5–15 soniya? Uzunroq bo'lsa aniqroq bo'lmaydimi?**
OmniVoice ovozni o'rganmaydi (fine-tune qilmaydi). U reference yozuvni namuna sifatida "eshitib", shunga o'xshatib gapiradi. 5–15 soniya ovoz tembri va ohangini ushlash uchun yetarli. 20 soniyadan uzun yozuv generatsiyani sekinlashtiradi, xotirani ko'p oladi va model mualliflarining o'zi yozganidek sifatni ham pasaytiradi. Uzunlikdan ko'ra yozuvning tozaligi muhimroq: shovqin, musiqa va aks-sado bo'lmasin.

**His-tuyg'u (kulgi, hayrat) qanday qo'shiladi?**
Eng ishonchli yo'l — kayfiyatli ovoz profili. Klonlashda "Quvnoq" yoki "G'amgin" matnini shu ohangda o'qib, alohida profil saqlang. Klon shu kayfiyatni oladi. `[laughter]`, `[sigh]` kabi teglar tajribaviy: model ularni asosan ingliz va xitoy tilida o'rgangan, o'zbekcha matnda ko'pincha sezilmaydi.

**Internet kerakmi?**
Faqat o'rnatish paytida kerak. Keyin to'liq oflayn ishlaydi.

## Loyiha tuzilmasi

```
ovozlab/          Ilova: server.py (API), engine.py (modellar), firstrun.py (o'rnatish ustasi),
                  desktop.py (Windows oynasi), static/ (interfeys)
omnivoice/        OmniVoice model kodi (Apache-2.0, Xiaomi)
installer/        Inno Setup skripti va yig'ish skripti
website/          Landing sahifa (statik HTML)
scripts/          Test skriptlari
```

## Hissa qo'shish

Xatolar va takliflar uchun [Issues](https://github.com/ovozlab/ovozlab/issues) bo'limiga yozing. Pull request'lar ham qabul qilinadi, batafsil: [CONTRIBUTING.md](CONTRIBUTING.md).

## Litsenziya va minnatdorchilik

OvozLab [Apache License 2.0](LICENSE) asosida tarqatiladi. Uchinchi tomon komponentlari ro'yxati: [NOTICE](NOTICE).

- [OmniVoice](https://github.com/k2-fsa/OmniVoice), Han Zhu / Xiaomi — nutq sintezi modeli
- [VoiceStudio](https://github.com/debpalash/VoiceStudio) — loyiha shu repozitoriyning `omnivoice/` paketidan boshlangan
- [navai-uz/whisper-medium-uzbek](https://huggingface.co/navai-uz/whisper-medium-uzbek) — o'zbekcha nutqni tanish modeli
- [Inter](https://rsms.me/inter/) shrifti (OFL)

Modellar bu repozitoriyga kirmaydi va o'z litsenziyalariga ega. Tijorat maqsadida ishlatishdan oldin model sahifalarini tekshiring.
