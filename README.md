# DERAI Collection Scheduler

Implementasi lokal pengganti `collection-scheduler`, memakai APScheduler 3.11.3 dan PostgreSQL. Kontrak acuannya ada di [PRD_COLLECTION_SCHEDULER.md](docs/PRD_COLLECTION_SCHEDULER.md).

Scheduler membaca topik, lalu membuat job `queued` di `public.records`. API key LLM tidak diperlukan untuk menjalankan dan menguji scheduler ini. Pengambilan konten, konektor, MinIO, dan event berada di `ingestion-worker` yang sudah ada. Preferensi memakai Gemini/OpenRouter/OpenAI-compatible dengan key sendiri diterapkan pada konektor terpisah.

Untuk mencoba ekstraksi dari satu URL artikel dengan API key sendiri, buka [connector-lab](connector-lab/README.md). Lab memakai Chromium lokal, tanpa akun Apify atau Crawl4AI Cloud. Lab berjalan terpisah dari antrean DERAI; job demo di PostgreSQL tidak otomatis memanggil LLM.

## Coba di laptop tanpa database

Prasyarat: Python 3.12 atau lebih baru. Buka PowerShell dari folder proyek:

```powershell
.\scripts\local.ps1 Setup
.\scripts\local.ps1 Preview
```

Preview memakai waktu tetap `2026-11-13T11:37:20+07:00` dan fixture PRD. Hasil yang diharapkan: empat job, query `TNI` dan `Indonesia`, dengan `scheduled_for = 2026-11-13T04:00:00+00:00`. Preview tidak menulis database.

Uji Unicode:

```powershell
.\.venv\Scripts\python.exe -m derai_scheduler preview --topics fixtures/unicode-topics.json --at '2026-11-13T04:37:20Z'
```

Hasilnya dua job dengan query `Straße`; `STRASSE` terdeduplikasi. Preview dapat memakai `id` dan `created_at` baru setiap kali; kedua field tersebut tidak dipakai untuk perbandingan deterministik.

## macOS dan Linux (tanpa PowerShell)

Gunakan Docker Desktop di Mac, atau Docker Engine dengan plugin Compose v2 di Linux. Jalankan dari root repo. Seluruh scheduler dan tes PostgreSQL berjalan di container; Python di host tidak diperlukan.

```sh
docker compose --profile dev up -d --wait db
docker compose --profile dev run --rm --build --no-deps scheduler-dev \
  derai-scheduler tick --at '2026-11-13T11:37:20+07:00'
docker compose --profile dev run --rm --no-deps scheduler-dev \
  derai-scheduler tick --at '2026-11-13T04:37:20Z'
docker compose --profile dev --profile test run --rm --build test
```

Pada volume demo baru, dua tick itu melaporkan `processed=4`, lalu `processed=0`. Tes memakai database fixture yang terpisah di container `db`. Image dasar menyediakan `linux/arm64` dan `linux/amd64`; tidak perlu memaksa `platform: linux/amd64` pada Mac Apple Silicon. Jika port lokal `55432` sudah dipakai, set `DERAI_DEV_DB_PORT=55433` di `.env` atau ekspor di shell sebelum menjalankan Compose. Tes di dalam container tidak memakai port host.

Untuk memeriksa job yang tersimpan terhadap fixture PRD, jalankan sebelum menghentikan stack:

```sh
mkdir -p artifacts
docker compose --profile dev exec -T db psql -X -qAt -v ON_ERROR_STOP=1 \
  -v 'tick_at=2026-11-13T11:37:20+07:00' -U derai_worker -d derai_scheduler_local \
  -f - < scripts/export-jobs.sql > artifacts/local-prd-jobs.json
docker compose --profile dev --profile test run --rm \
  -v "$PWD/scripts/compare-contracts.py:/contract/compare.py:ro" \
  -v "$PWD/fixtures/expected-prd-jobs.json:/contract/expected.json:ro" \
  -v "$PWD/artifacts/local-prd-jobs.json:/contract/actual.json:ro" \
  test python /contract/compare.py /contract/expected.json /contract/actual.json
```

Untuk menjalankan scheduler terus menerus atau menghentikan stack demo sambil menyimpan volume:

```sh
docker compose --profile dev up -d --build scheduler-dev
docker compose logs -f scheduler-dev
# Ctrl+C menutup tampilan log; hentikan stack dengan:
docker compose --profile dev --profile test down
```

## Demo PostgreSQL lokal

Prasyarat tambahan: Docker Desktop berjalan dengan Linux containers.

```powershell
.\scripts\local.ps1 Demo
```

Helper menjalankan PostgreSQL khusus proyek ini, memuat topik contoh pada volume baru, kemudian menjalankan dua tick pada jam yang sama. Pada database baru, log tick pertama `processed=4` dan tick kedua `processed=0`. Jika contoh sudah dijalankan, keduanya bisa `processed=0`; job sebelumnya memang dipertahankan.

PostgreSQL dipublikasikan hanya pada `127.0.0.1:55432`, database `derai_scheduler_local`. Role scheduler `derai_worker` memiliki `SELECT` dan `INSERT`; akun admin lokal terpisah. Password contoh merupakan fixture lokal dan tidak dipakai sebagai konfigurasi deployment.

Menjalankan loop lokal setelah demo:

```powershell
.\scripts\local.ps1 Run
```

Atau jalankan scheduler dan database sepenuhnya dalam Docker:

```powershell
docker compose --profile dev up --build -d
docker compose logs -f scheduler-dev
```

Menghentikan proses Docker milik proyek sambil mempertahankan data:

```powershell
.\scripts\local.ps1 Stop
```

Loop yang dijalankan dengan `Run` dihentikan dengan `Ctrl+C`. PostgreSQL lokal dan resource proyek lain tidak dihapus oleh helper.

## Konfigurasi dan CLI

| Variabel | Default | Arti |
| --- | --- | --- |
| `DATABASE_URL` | wajib bila flag aktif | PostgreSQL tujuan; format `postgresql+psycopg://derai_worker@host:port/database` |
| `PGPASSWORD` | autentikasi driver | Password dapat terpisah dari URL. |
| `WORKER_INTERVAL` | `60` | Jeda setelah tick selesai atau gagal. Tick pertama segera saat startup. |
| `SOCIAL_COLLECTION_ENABLED` | `true` | Aktif hanya untuk `1`, `true`, `yes`, `on` setelah trim dan lowercase. Nilai lain melewati query topik. |
| `CONNECTOR_ARTICLE_MAX_PAGES` | `1` | Disimpan sebagai string pada payload berita. |

Contoh satu tick pada database yang sudah dikonfigurasi:

```powershell
$env:DATABASE_URL = 'postgresql+psycopg://derai_worker@127.0.0.1:55432/derai_scheduler_local'
$env:PGPASSWORD = 'derai_local_worker'
.\.venv\Scripts\python.exe -m derai_scheduler tick --at '2026-11-13T11:37:20+07:00'
.\.venv\Scripts\python.exe -m derai_scheduler run
```

`.env.example` adalah contoh konfigurasi. Salin ke `.env`; CLI dan Docker Compose membacanya otomatis. Variabel yang sudah diekspor di terminal mengalahkan `.env`. CLI juga menerima `--env-file PATH` sebelum subcommand. Saat flag nonaktif, `tick`/`run` tidak membuka koneksi database.

## Menggunakan database DERAI eksternal

Schema, constraint `uq_scope_kind_idem`, grant, serta RLS harus sudah tersedia melalui migrasi DERAI. Service scheduler tidak membuat tabel, role, atau policy saat startup. Script `scripts/init-local-db.sql` khusus database fixture lokal baru; policy lintas scope di dalamnya bukan migrasi produksi.

Untuk Compose, isi `EXTERNAL_DATABASE_URL` dan `EXTERNAL_PGPASSWORD` pada `.env`, lalu pilih service eksternal secara eksplisit:

```powershell
docker compose --profile external up --build -d scheduler
docker compose logs -f scheduler
```

Service ini tidak menjalankan database fixture. Alamat `localhost` di dalam container menunjuk container itu sendiri; jika PostgreSQL berjalan di host Docker Desktop (Windows/macOS), gunakan `host.docker.internal`.

Pada Linux, gunakan alamat DNS/IP PostgreSQL yang memang dapat dijangkau dari jaringan container. Untuk uji kontrak di server gunakan profil `dev` dan `test` dengan nama proyek Compose terpisah (`docker compose -p derai-scheduler-check ...`) dan port fixture bebas. Profil `external` menulis ke database yang dikonfigurasi: jalankan hanya terhadap database uji atau setelah persetujuan perpindahan layanan sesuai [checklist integrasi](docs/INTEGRATION_CHECKLIST.md).

## Verifikasi

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Uji PostgreSQL lokal pada database terpisah dapat dijalankan dengan:

```powershell
.\scripts\local.ps1 TestPostgres
```

Helper memastikan database lokal `derai_scheduler_test` tersedia, memasang `TEST_DATABASE_URL` hanya selama pengujian, kemudian memulihkan konfigurasi terminal. Data demo di `derai_scheduler_local` dipertahankan.

Untuk menjalankan tes PostgreSQL sendiri, `TEST_DATABASE_URL` harus menunjuk PostgreSQL loopback (`localhost`, `127.0.0.1`, atau `::1`) dan nama database harus berawalan `test_` atau berakhiran `_test`. Fixture mengosongkan tabel `records` database uji sebelum dan sesudah tes; jangan menunjuk database DERAI aktif.

Aturan yang wajib dipertahankan mencakup `str.strip()`/`casefold()`, jam UTC dengan `+00:00`, dua jenis payload, deduplikasi tanpa melihat status lama, satu commit per tick, rollback seluruh tick, dan `ON CONFLICT ON CONSTRAINT uq_scope_kind_idem DO NOTHING RETURNING id`.

Uji dengan `ingestion-worker` acuan, perbandingan dengan scheduler lama, dan pergantian service server adalah langkah integrasi tersendiri. Bukti yang diperlukan tercantum dalam [INTEGRATION_CHECKLIST.md](docs/INTEGRATION_CHECKLIST.md); hasil uji lokal tidak otomatis membuktikan ketiganya.

Lihat [hasil verifikasi di laptop](docs/LOCAL-VERIFICATION.md) untuk bukti demo dan hasil tes.
Lihat [panduan serah terima](docs/HANDOFF.md) untuk langkah reproduksi dan daftar source yang dibutuhkan dari mentor.

Untuk membandingkan baris yang benar-benar tertulis setelah `Demo`, ekspor jam fixture (default 11.37 WIB) dan bandingkan dengan output yang diharapkan PRD:

```powershell
New-Item -ItemType Directory -Force artifacts | Out-Null
.\scripts\local.ps1 Snapshot | Set-Content -Encoding utf8 artifacts/local-prd-jobs.json
.\.venv\Scripts\python.exe scripts/compare-contracts.py fixtures/expected-prd-jobs.json artifacts/local-prd-jobs.json
```

Jika snapshot output worker lama sudah tersedia, gunakan snapshot tersebut sebagai acuan:

```powershell
.\.venv\Scripts\python.exe scripts/compare-contracts.py old-jobs.json artifacts/local-prd-jobs.json
```

Comparator memeriksa semua kolom kontrak dan JSON payload yang sudah di-parse, menghitung duplikasi, dan mengecualikan hanya `id` serta `created_at`. Exit code `0` berarti sama, `1` berbeda, dan `2` input tidak valid. Ini alat pembanding; menjalankannya pada dua output baru tidak membuktikan kesetaraan dengan worker lama.

## Fondasi open source

[APScheduler](https://github.com/agronholm/apscheduler) menyediakan mesin penjadwalan, mengacu pola [service BlockingScheduler resmi versi 3.11.3](https://github.com/agronholm/apscheduler/blob/3.11.3/examples/schedulers/blocking.py). Scheduler memakai job store memori; job bisnis tetap disimpan di tabel DERAI. API seri 3.x dipakai secara eksplisit, dan one-shot berikutnya diatur setelah tick selesai agar kompatibel dengan fixed delay PRD. Adapter data DERAI ditulis khusus mengikuti kontrak mentor, memakai [SQLAlchemy PostgreSQL ON CONFLICT](https://docs.sqlalchemy.org/en/21/dialects/postgresql.html#insert-on-conflict-upsert). Versi dependency yang teruji dicatat di `constraints.txt` dan dipakai oleh helper Setup serta build Docker.
