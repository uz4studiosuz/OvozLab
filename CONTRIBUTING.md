# Hissa qo'shish

OvozLab'ni yaxshilashga yordam berganingiz uchun rahmat!

## Ishga tushirish

```bash
uv sync --extra xpu          # yoki --extra cuda / --extra cpu
uv run python -m ovozlab     # ilova oynasi
uv run uvicorn ovozlab.server:app --reload --port 8000   # faqat server
```

Toza o'rnatishni (o'rnatish ustasini) sinash uchun boshqa uy papkasini bering:

```bash
set OVOZLAB_HOME=%TEMP%\ovozlab-test
uv run python -m ovozlab
```

Server ishlayotganda tezkor tekshiruv: `uv run python scripts/smoke_test.py`.

## Qoidalar

- Interfeys matnlari o'zbek tilida (lotin yozuvi), `o'` va `g'` tutuq belgisi bilan yoziladi.
- Bir pull request bitta o'zgarish bo'lsin; nima uchun kerakligini qisqa yozing.
- Yangi bog'liqlik qo'shsangiz, `uv lock` ni ishga tushirib, `uv.lock` ni ham commit qiling.
- Interfeys o'zgarsa, oldin va keyingi skrinshotni qo'shing.

## Yordam kerak bo'lgan joylar

- O'zbekcha his-tuyg'uli nutq ma'lumotlari (emotsiyani to'g'ridan-to'g'ri boshqarish uchun fine-tune).
- Sonlar, sanalar va qisqartmalarni so'zga aylantirish (masalan, `2026` → `ikki ming yigirma olti`).
- macOS va Linux uchun o'rnatuvchilar.
