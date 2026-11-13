# Lab ekstraksi berita dengan LLM

Alat opsional untuk mencoba **satu URL artikel publik** di laptop. [Crawl4AI 0.9.5](https://github.com/unclecode/crawl4ai/releases/tag/v0.9.5) (Apache-2.0) mengambil halaman lewat Chromium lokal. Teks halaman dikirim ke LLM yang kamu pilih untuk menghasilkan JSON. Tidak perlu key Apify, Crawl4AI Cloud, atau layanan scraping lain. Lab berdiri sendiri: tidak membaca/menulis PostgreSQL dan belum menjadi konektor `ingestion-worker` DERAI.

Di macOS atau Linux, dari root repo:

```sh
cd connector-lab
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
[ -f .env ] || cp .env.example .env
```

Di Debian/Ubuntu, jika pustaka sistem Chromium belum tersedia, gunakan `.venv/bin/python -m playwright install --with-deps chromium`. Di server bersama, koordinasikan pemasangan paket sistem dengan admin. Di macOS bisa memakai Chrome yang sudah ada dengan `--browser-channel chrome`.

Di Windows, buka PowerShell dari root repo:

```powershell
Set-Location connector-lab
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Jika Chrome atau Edge sudah terpasang, lewati `playwright install chromium` dan tambahkan `--browser-channel chrome` atau `--browser-channel msedge` saat menjalankan lab. Browser membuka profil baru yang terisolasi. Tambahkan `--crawl-only` untuk melihat Markdown hasil crawl tanpa key atau panggilan ke LLM.

Isi `LLM_API_KEY` di `.env` dan pilih provider berikut:

| `LLM_PROVIDER` | `LLM_MODEL` | `LLM_BASE_URL` |
| --- | --- | --- |
| `gemini` | Contoh: `gemini-3.5-flash-lite` | Otomatis: endpoint Chat Completions resmi Gemini. Gunakan [key Google AI Studio](https://aistudio.google.com/apikey) dan cek [free tier serta batas model](https://aistudio.google.com/docs/pricing#gemini-3.5-flash-lite) pada proyekmu. Langganan Google AI Pro tidak menggantikan API key. |
| `openrouter` | `openrouter/free` atau slug model pilihanmu | Otomatis: `https://openrouter.ai/api/v1`. Gunakan key OpenRouter dan cek [ketersediaan model gratis](https://openrouter.ai/collections/free-models). |
| `compatible` | ID model yang disediakan endpoint | Isi base URL endpoint yang menerima `POST /chat/completions`, misalnya `https://gateway.example/v1` atau `http://127.0.0.1:8000/v1`. Key boleh kosong bila endpoint lokal tidak memerlukannya. Login OpenCode/Codex bukan API key atau endpoint tersebut. |

```powershell
.\.venv\Scripts\python.exe connector_lab.py 'https://science.nasa.gov/missions/artemis/artemis-2/nasas-artemis-ii-moon-mission-research-continues-on-earth/' --browser-channel chrome
```

Untuk macOS/Linux dengan Chromium yang dipasang Playwright, gunakan `.venv/bin/python connector_lab.py '<URL-artikel-publik>'`. Tambah `--crawl-only` untuk tes browser tanpa key.

Ganti URL contoh dengan artikel yang ingin diuji. Program menulis JSON berisi `headline`, `text`, `canonical_url`, dan `published_at` bila model menemukan tanggal yang valid. `canonical_url` diambil dari halaman atau URL akhir hasil crawl; tanggal berasal dari ekstraksi model dan perlu diverifikasi jika dipakai sebagai filter. Halaman yang memerlukan autentikasi, membatasi browser, atau tidak berisi artikel dapat gagal diekstrak. Lab ini tidak melakukan pencarian keyword, scraping medsos, atau pengambilan otomatis berkala.

Gunakan URL publik pilihan sendiri; program lokal ini tidak dibuat untuk menerima URL dari pengguna lain melalui server. Isi halaman yang digunakan untuk ekstraksi dikirim ke provider LLM yang dipilih. Key hanya dipakai untuk request ke provider dan tidak ditulis ke output. Jangan bagikan file `.env`.

Uji jalur request/response LLM tanpa key dan tanpa menghubungi provider:

```powershell
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest -q tests
```

Acuan: [Crawl4AI quick start](https://docs.crawl4ai.com/core/quickstart/), [Gemini OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai), [OpenRouter Chat Completions](https://openrouter.ai/docs/api-reference/chat-completion).
