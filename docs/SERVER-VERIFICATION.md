# Verifikasi server DERAI — 13 November 2026

Checkout scheduler: `~/aldo/derai-platform/derai-collection-scheduler`. Parent
DERAI menjalankan service `collection-scheduler` pada project Compose yang sama
dengan API dan ingestion-worker. Scheduler memakai PostgreSQL dan tidak memakai
key LLM.

| Pemeriksaan | Hasil |
| --- | --- |
| Acuan yang benar | Command container lama menjalankan `scrapper/collection_scheduler.py` melalui bind mount. File itu cocok dengan hash di container. File worker, konektor, ekstraksi dimensi dan migrasi yang dipakai untuk fixture ingestion cocok dengan image ingestion aktif. |
| Skema, role dan RLS | Dua database fixture memakai migrasi `0001` dari image DERAI. Scheduler lama dan baru memakai `derai_worker` dengan RLS aktif. Probe hanya baca pada database aktif membuktikan role, grant SELECT/INSERT dan constraint deduplikasi tersedia untuk kandidat. |
| Parity | Pada jam yang dipatok, kedua scheduler menulis 4 job dengan kolom dan payload yang sama. Tick ulang pada jam sama dan setelah status `failed` menulis 0. Skenario satu job hilang dan Unicode di scope kedua menghasilkan 3 job tambahan, dengan 6 baris akhir yang cocok. |
| Ingestion asli | `ingestion_once` asli memproses 2 job baru menjadi `ready`, membuat 3 raw record dan 3 outbox record. Konektor fixture membuktikan pemilihan platform, opsi X, batas `[awal, akhir)` dan `max_pages` bertipe string. Broker, object store dan provider scraping eksternal tidak digunakan pada uji ini. |
| Cutover | Service baru mulai pukul 16:04 WIB memakai image `derai-collection-scheduler-fata:server` dan `derai-scheduler run`. Dua tick awal sukses dan tidak menggandakan job jam transisi. ID container DERAI lain tidak berubah. Pada dua pengukuran sebelum/sesudah, jam itu berisi 37 job berita (10 `ready`, 27 `failed`) dan 37 job sosial (`failed`). Status tersebut sudah ada sebelum cutover dan tidak menunjukkan penyebab kegagalan. |
| Lab LLM | Image Linux mengambil satu artikel publik lewat Chromium lalu mengembalikan judul, teks, dan URL kanonis dari permintaan Gemini yang berhasil. Key dibaca dari `.env` lab yang diabaikan Git; tidak dimasukkan ke image. Lab tetap terpisah dari ingestion produksi. |

## Uji ulang dengan image asli

Jalankan dari folder scheduler. Pilih ID image acuan yang diperoleh sebelum
cutover, bukan image scheduler baru. Image acuan harus memuat `app.workers` dan
migrasi DERAI. Skrip tidak mengambil environment dari container produksi.

```sh
bash scripts/verify-reference.sh "$LEGACY_IMAGE_ID" \
  derai-collection-scheduler-fata:server ../scrapper/collection_scheduler.py
```

Fixture PostgreSQL memakai container tanpa akses jaringan eksternal, database
sementara, dan runtime CPU `runc`. Gunakan `DERAI_TEST_OCI_RUNTIME` jika host
memerlukan nama runtime CPU berbeda. Output comparator mengecualikan hanya ID
dan waktu tulis aktual dari perbandingan kolom kontrak.

## Konfigurasi aktif dan rollback

Konfigurasi parent `compose.yaml` sudah memuat perubahan scheduler. Jangan
memakai file override tambahan untuk deployment normal; `compose.derai.yaml`
mendokumentasikan bentuk perubahan yang diperiksa sebelum cutover. Service
lain tetap memakai konfigurasi sebelumnya.

Backup Compose sebelum dan sesudah cutover, ID image lama, serta daftar ID
container ada di `.runtime/` pada checkout server. Sebelum rollback, cocokkan
Compose saat ini dengan salinan sesudah cutover. Jika berbeda, bandingkan dan
pulihkan **hanya blok scheduler** agar perubahan lain tidak tertimpa. Bila sama,
pulihkan backup sebelum cutover, cocokkan tag lama dengan ID yang dicatat, lalu
jalankan dari root `derai-platform`:

```sh
docker compose -p derai-platform --env-file .env --env-file .env.external \
  -f compose.yaml -f compose.external.yaml \
  up -d --no-deps --no-build --pull never collection-scheduler
```

Periksa command, image dan tick scheduler sesudah rollback. Tidak perlu
menghapus job atau menghentikan service lain.
