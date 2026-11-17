# DERAI Article Scraper

Pengganti Article Scraper Engine API [commit `8596ede`](https://github.com/aqshaaqso/article-scraper-engine-api/tree/8596ede07e9f30573013637636c1d716f2e432fc). Build mengambil checkout dari repo teman mentor dan menerapkan patch yang hanya mengganti sumber pencarian URL. Kode API, antrean PostgreSQL, ekstraktor, migrasi, schema JSON, filter tanggal, dan struktur error berasal dari commit acuan. Minta izin pemilik repo sebelum mendistribusikan ulang source atau image upstream; patch dan discovery disimpan terpisah di sini.

Service menyimpan antrean dan hasilnya di **PostgreSQL milik scraper**. Jalur lama tetap dapat mengambil hasil lewat HTTP. Untuk alur cron baru, Connector Lab mengirim satu item lewat `POST /api/v1/ingestion/normalized`; backend DERAI yang menyimpan dan menjalankan distribusi downstream. Scraper tidak memerlukan kredensial DB DERAI, RabbitMQ, MinIO, atau ClickHouse.

## Jalankan di server cron atau laptop

Dari root checkout `derai` (Windows: ganti `python3` dengan `py`):

```sh
cd article-scraper
python3 prepare.py --init-env
docker compose up -d --build --wait
curl -fsS http://127.0.0.1:18011/ready
python3 scripts/verify_service.py --query Indonesia
```

Nama Compose: `derai-article-scraper`. Base URL pada host yang sama: `http://127.0.0.1:18011`. `prepare.py` membuat `.env` hanya bila belum ada. Ambil `SCRAPER_API_KEY` dari `.env` server, simpan di konfigurasi rahasia cron, dan jangan tempelkan ke chat. PostgreSQL dan discovery tidak membuka port host. Untuk cron di container lain, gunakan alamat internal yang bisa dijangkau cron (misalnya `http://api:8010` bila bergabung ke jaringan Compose khusus scraper). Untuk host berbeda, gunakan proxy HTTPS internal dengan akses terbatas ke cron.

Pada dev-tessar, `COMPOSE_FILE=compose.yaml:compose.gateway.yaml` dan `ARTICLE_GATEWAY_BIND_HOST=10.10.101.151` di `.env` menambahkan port privat untuk gateway PopOS dan menghubungkan API ke jaringan eksternal `derai-platform_default` dengan alias `derai-article-engine`. Connector Lab di jaringan itu memakai `ARTICLE_ENGINE_URL=http://derai-article-engine:8010`.

## Kontrak HTTP engine

Kirim `POST /v1/search/jobs`, header `X-API-Key`, dan payload yang sama seperti engine lama:

```json
{"query":"Indonesia","max_articles":3,"max_pages":1}
```

1. `202` berarti job diterima. Tanpa filter tanggal, simpan `job_id` dan poll `GET` pada **`result_url`** dengan header yang sama.
2. Saat `status=completed`, ambil **`items[].article`** untuk item `status=success`. Periksa `succeeded`, `failed`, dan error item. Job `completed` juga bisa tidak memiliki artikel. Jika job `failed`, catat `error_code`/`error_detail` dan jangan tulis artikel kosong.
3. Untuk range tanggal, ikuti `progress_url`, ambil tiap job pada `job_ids`, dan panggil `continue_url` jika tersedia. Gunakan `include_excluded=true` hanya untuk audit; tanpa parameter itu, job bertanggal hanya menampilkan hasil yang lolos.

`POST /v1/articles/scrape` untuk satu URL dan `POST /v1/jobs` untuk batch URL juga tetap tersedia. Spesifikasi aktual ada pada `/openapi.json`. Kalau cron memanggil gateway DERAI `/api/v1/articles/...` hari ini, pertahankan URL cron; pada gateway, ubah `ARTICLE_SCRAPER_BASE_URL` dan `ARTICLE_SCRAPER_API_KEY` setelah uji. Kalau cron memanggil engine lama langsung, ubah base URL dan kredensial engine saja. Jangan arahkan cron produksi sebelum tes satu job lewat jalur cron dan konfirmasi satu record yang benar masuk ke DB tujuan.

## Handoff cron → Connector Lab → DERAI

Untuk jalur push mentor, lihat [runbook Connector Lab](../connector-lab/HANDOFF-NORMALIZED.md). Pada dev-tessar, engine berita aktif di `http://127.0.0.1:18011` dan direktori `~/aldo/derai-article-scraper`. Helper `collect.py` dapat dipanggil dari host dengan `SCRAPER_API_KEY`, `DERAI_API_URL=http://127.0.0.1:8080`, dan `DERAI_API_TOKEN` yang dimuat dari konfigurasi aman:

```sh
python3 collect.py "$SOURCE_URL" --persist --topic-id "$TOPIC_ID" \
  --tenant-id "$TENANT_ID" --workspace-id "$WORKSPACE_ID" --idempotency-key "$DELIVERY_KEY"
```

Tanpa `--persist`, helper mencetak JSON `ArticleResponse` persis dari engine dan tidak mengirim ke backend. Dengan `--persist`, helper mengirim JSON artikel yang sama sebagai `payload` dan stdout hanya berisi `status` dan `idempotency_key` untuk cron.

## Discovery tanpa SerpAPI

Default `DISCOVERY_MODE=rss` menggunakan feed publik ANTARA, CNN Indonesia, dan CNBC Indonesia. Feed dicache dan dicari dengan keyword, sehingga sistem bisa dipakai tanpa key LLM. URL yang ditemukan harus lolos validasi domain dan tetap diambil oleh worker acuan. Kontrak tanggal tetap dipakai, tetapi cakupan RSS terbatas pada feed dan cache, bukan replika arsip SerpAPI.

Opsional, isi `DISCOVERY_LLM_PROVIDER=gemini`, `openrouter`, `openai`, atau `compatible`, lalu `DISCOVERY_LLM_MODEL` dan `DISCOVERY_LLM_API_KEY`. Untuk `compatible`, beri `DISCOVERY_LLM_BASE_URL` berupa URL HTTPS endpoint layanan sampai `/v1`, tanpa `/chat/completions`. Ini hanya memilih kandidat RSS; LLM tidak menulis isi atau tanggal artikel. Jika respons AI gagal atau tidak ada kandidat terpilih, pencarian kembali ke pencocokan RSS.

`DISCOVERY_MODE=gemini_search` dengan provider `gemini` membuat Gemini memakai Google Search grounding untuk mencari URL, dan memakai RSS jika grounding gagal. Aktifkan hanya jika kuota/biaya proyek memungkinkan. Provider OpenRouter/compatible di build ini hanya merangking kandidat RSS. Codex CLI/subscription tidak menjadi endpoint HTTP sendiri; bila memakai proxy OpenAI-compatible yang memang Anda kelola, konfigurasikan sebagai `compatible`.

Perubahan `.env` untuk LLM cukup diterapkan pada service `discovery`: `docker compose up -d --no-deps --wait discovery`. Tidak perlu restart scheduler DERAI.

## Verifikasi lokal

```sh
python3 -m unittest discover -s tests
python3 scripts/verify_service.py
```

`scripts/verify_service.py` membuat satu job keyword, memeriksa bentuk artikel, membaca baris dari PostgreSQL scraper, dan menyimpan `artifacts/verification.json` serta `artifacts/example-article.json` secara lokal. Opsi `--oracle-url` membandingkan OpenAPI dan JSON untuk URL yang sama dengan instance referensi tidak dipatch; set `ORACLE_SCRAPER_API_KEY` di environment tes. Perbedaan waktu pengambilan `fetched_at` diabaikan pada komparasi isi.

Uji fixture sumber HTTP bisa diulang dengan Postman CLI:

```sh
postman simulation run postman/simulations/discovery.sim.yaml --port 18732 --no-history
# Terminal terpisah
python3 scripts/simulation_check.py
```
