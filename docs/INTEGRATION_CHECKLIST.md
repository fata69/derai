# Verifikasi integrasi dan perpindahan server

Dokumen ini memisahkan bukti yang dapat diperoleh dari implementasi lokal dan bukti yang memerlukan kode acuan DERAI. Tidak ada perintah di sini yang menjalankan deployment secara otomatis.

## Kode acuan yang diperlukan

PRD menunjuk snapshot container `derai-platform` yang berjalan pada 13 November 2026:

- `app/workers.py`: `collection_scheduler_once`, `build_connector`, `ingestion_once`, dan loop `main`.
- `app/db.py` dan `migrations/versions/0001_operational_rls.py`.
- `compose.yaml`, `compose.external.yaml`, dan `tests/test_social_ingestion.py`.

Gunakan salinan kode dan database fixture yang terisolasi di laptop. Rahasia konfigurasi tidak perlu dimasukkan ke repositori.

## Perbandingan scheduler lama dan baru

1. Muat topik yang sama ke dua database fixture terisolasi, dengan schema, constraint, grant, dan RLS yang sama.
2. Patok waktu tick identik, termasuk contoh WIB dan UTC pada PRD.
3. Jalankan fungsi scheduler lama dan `derai-scheduler tick --at ...` pada fixture masing-masing.
4. Bandingkan semua kolom kontrak, setelah `data` di-parse menjadi JSON. Kecualikan `id` dan `created_at` karena memang dibuat saat penulisan.
5. Ulangi untuk Unicode, non-string lama, status `failed`, salah satu jenis job sudah ada, pergantian jam, invalid JSON, dan dua tick bertumpuk.

Gunakan [export-jobs.sql](../scripts/export-jobs.sql) dengan `psql -X -qAt -v ON_ERROR_STOP=1 -v tick_at=... -f scripts/export-jobs.sql` terhadap masing-masing **database fixture** dan simpan stdout ke JSON. Script hanya membaca job pada jam UTC dari `tick_at`. Untuk database demo Compose, `./scripts/local.ps1 Snapshot` melakukan ekspor yang sama sebagai `derai_worker`. Jalankan `python scripts/compare-contracts.py old-jobs.json new-jobs.json` untuk membandingkan hasil. `fixtures/expected-prd-jobs.json` berisi output yang diturunkan dari contoh PRD; file ini dapat memeriksa baseline, tetapi tidak menggantikan ekspor hasil scheduler lama.

## Kompatibilitas ingestion yang sebenarnya

1. Buat satu topik dengan satu kata kunci; scheduler baru harus menulis tepat dua baris `queued`.
2. Jalankan **fungsi `ingestion_once` dari kode acuan**, dengan konektor uji yang tidak mengakses internet dan storage/event stub yang sesuai antarmuka aslinya.
3. Buktikan social job memakai daftar dari `CONNECTOR_PLATFORMS`, sedangkan news job memakai `online_news` dan `max_pages` string.
4. Buktikan jendela sosial diteruskan dan filter `[period_start, period_end)` diterapkan. News job tidak memiliki field periode.
5. Buktikan kedua job diambil ingestion dan dapat menjadi `ready`.

Simulator yang hanya menyalin payload atau mengubah status sendiri bukan bukti kompatibilitas worker acuan. Jangan menyatakan kriteria ini lulus tanpa menjalankan worker aslinya.

## Uji scheduler saja di server Linux

Jalankan dari checkout repo ini. Pilih nama proyek Compose khusus uji dan port loopback yang kosong; contoh di bawah menggunakan `55433`. Database dan role pada perintah ini berasal dari fixture Compose.

```sh
export DERAI_DEV_DB_PORT=55433
docker compose -p derai-scheduler-check --profile dev up -d --wait db
docker compose -p derai-scheduler-check --profile dev --profile test run --rm --build test
docker compose -p derai-scheduler-check --profile dev --profile test down
```

Perintah `down` mempertahankan volume fixture. Tes memakai `derai_scheduler_test` dan tidak memerlukan kredensial atau akses ke PostgreSQL DERAI. Untuk demonstrasi tick `4 → 0`, gunakan dua perintah tick di [README](../README.md#macos-dan-linux-tanpa-powershell) dengan nama proyek yang sama.

## Perpindahan service setelah integrasi lulus

1. Siapkan konfigurasi scheduler baru pada database DERAI hasil migrasi; pastikan role worker melihat semua scope yang dilayani dan boleh menulis job sesuai RLS.
2. Hentikan `collection-scheduler` lama dan sesuaikan konfigurasi Compose milik deployment agar tidak otomatis aktif lagi.
3. Jalankan scheduler baru; job lama tetap dipertahankan. Kunci deduplikasi identik melindungi jam transisi.
4. Periksa log `processed`, jumlah job baru per jenis, dan status setelah ingestion.
5. Untuk rollback, hentikan scheduler baru sebelum mengaktifkan scheduler lama.

Implementasi lokal tidak memberikan otorisasi tersendiri untuk tindakan pada server.
