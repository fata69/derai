# Hasil verifikasi lokal — 13 November 2026

Lingkungan: Windows (Python 3.14.7), Docker Desktop Linux engine 29.7.2,
PostgreSQL 17.12, APScheduler 3.11.3 dan SQLAlchemy 2.1.8. Database demo hanya
terikat ke `127.0.0.1:55432`. Pengujian tidak menggunakan kredensial DERAI.

| Kontrak | Bukti lokal |
| --- | --- |
| Fixture PRD, waktu 11.37 WIB | Tick pertama menulis 4 job `queued` untuk `TNI` dan `Indonesia`, dua jenis masing-masing, dengan `scheduled_for` `2026-11-13T04:00:00+00:00`. Tick kedua menulis 0. CLI terhubung sebagai `derai_worker` dengan SELECT/INSERT dan RLS fixture. |
| Zona waktu, jam, jendela periode, teks Unicode, dan payload | Tes kontrak memeriksa zona WIB/UTC/waktu polos, format literal `+00:00`, periode sosial, JSON berita, nama dan tipe field, hash TNI/Straße, UUID v4, dan waktu pembuatan aktual. |
| Idempotensi dan transaksi | Tes PostgreSQL memulai dua tick bertumpuk: satu menulis 4, satu 0; hanya empat kunci unik tersimpan. Job `failed` masih memblokir duplikat. Job yang hilang ditulis tanpa menduplikasi pasangannya. JSON topik rusak membatalkan seluruh tick. |
| Cakupan dan flag | Tes mencakup tenant/workspace berbeda, topik `deleting`, baris non-topik, array kosong, flag nonaktif tanpa akses DB, keyword baru di jam yang sama, dan tidak melakukan backfill. Tes PostgreSQL dengan RLS fixture aktif memakai `derai_worker` dan membuktikan dua scope yang diizinkan dibaca, scope lain diabaikan, dan job `failed` tetap mencegah duplikasi. |
| Loop di container | Build Linux berhasil, proses scheduler berjalan sebagai user `scheduler`. Log startup diikuti tick dengan jarak sekitar 60 detik. Sesudah rebuild terakhir: `14:18:16`, `14:19:16`, `14:20:16` WIB. Scheduler berhenti lewat SIGTERM dengan exit code 0 dan langsung tick setelah dijalankan kembali. Container dengan flag kosong dan DSN sengaja invalid melaporkan `processed=0`. Tes lifecycle juga memeriksa jeda sesudah tick gagal. |
| Hasil tes | 78 tes scheduler lulus, termasuk 8 tes PostgreSQL. Ruff check dan format lulus. Comparator menerima perubahan urutan/ID/`created_at`, menolak duplikat tambahan, dan menolak input yang tidak valid. |
| Snapshot PostgreSQL | Ekspor sebagai `derai_worker` untuk tick `11:37:20+07:00` dan `04:37:20Z` identik. Empat baris aktual cocok dengan `fixtures/expected-prd-jobs.json` pada seluruh kolom kontrak dan payload: `missing=0`, `unexpected=0`. Fixture diturunkan dari PRD, bukan dari scheduler lama. |

Lab ekstraksi terpisah: Crawl4AI 0.9.5 berhasil mengambil [artikel NASA publik](https://science.nasa.gov/missions/artemis/artemis-2/nasas-artemis-ii-moon-mission-research-continues-on-earth/) lewat Chrome lokal (`--crawl-only --browser-channel chrome`). Keluaran JSON ter-parse dan memuat URL kanonis serta 15.583 karakter Markdown setelah penyaringan. Sepuluh tes lab lulus, termasuk CLI lengkap dengan respons tiruan untuk konfigurasi Gemini dan endpoint kompatibel. Belum ada panggilan ke Gemini/OpenRouter atau key pengguna. Lihat [cara mencoba lab](../connector-lab/README.md).

Belum terverifikasi: perbandingan dengan `collection_scheduler_once` lama dan
uji `ingestion_once` asli sampai job `ready`. Source acuan tidak ada dalam paket
yang tersedia; lihat [audit source](SOURCE-VERIFICATION.md) dan
[checklist integrasi](INTEGRATION_CHECKLIST.md). Server belum diubah.
