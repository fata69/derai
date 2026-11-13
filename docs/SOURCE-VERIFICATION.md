# Verifikasi kode acuan DERAI

Pencarian awal pada 13 November 2026 hanya mencakup workspace laptop. Setelah
akses server tersedia, acuan ditemukan dan diuji; lihat
[verifikasi server](SERVER-VERIFICATION.md). Catatan pencarian awal di bawah
menjelaskan mengapa hasil fixture lokal sebelumnya belum membuktikan integrasi.

## Hasil pencarian lokal

Kode platform yang disebut dalam PRD belum ditemukan di workspace lokal:

- `app/workers.py`, termasuk `collection_scheduler_once`, `ingestion_once`, dan
  `build_connector`.
- `app/db.py`.
- `migrations/versions/0001_operational_rls.py`.
- `tests/test_social_ingestion.py`.

Pencarian nama file juga mencakup file tersembunyi. Pencarian teks pada source
dan dokumentasi untuk fungsi scheduler, `uq_scope_kind_idem`, dan
`derai-platform` hanya menemukan PRD yang disalin ke proyek baru ini.

Daftar anggota 14 arsip handoff/source yang relevan juga diperiksa tanpa
mengekstrak atau mengubah isinya. Tidak ada file platform di atas dalam arsip
tersebut. Arsip image Docker berukuran besar dan dump database tidak dibuka.

## Source lain yang tersedia

Workspace berisi source konektor, scraper artikel, dan AI worker dari pekerjaan
sebelumnya. Source-source ini bukan worker platform pada PRD:

| Lokasi | Source/tujuan |
| --- | --- |
| `../konektor medsos/` | Gateway konektor Go; README menyatakan scheduler tidak termasuk cakupan. |
| `../konektor medsos/integrations/konektor/` | Source integrasi konektor, bukan worker platform. |
| `../tmp/article-scraper-review-2026-09-08/` | Source scraper artikel, bukan worker platform. |
| `../AI-Worker-Analytics/` | Worker analitik berbasis RabbitMQ/MinIO; berbeda dari ingestion berbasis `public.records` pada PRD. |

Remote lokal yang ditemukan tidak menunjuk repo `derai-platform`. Pencarian
publik berdasarkan nama repo/fungsi juga tidak menemukan source yang dapat
dipastikan sebagai platform tersebut; ini bukan bukti repo private tidak ada.
Pemeriksaan tambahan pada repo yang tersedia melalui konektor GitHub (`derai`
atau `derai-platform` pada nama, dan simbol `collection_scheduler_once`) juga
tidak mengembalikan hasil sebelum akses server diberikan.

## Batas validasi dan pengujian akhir

Uji payload, hashing, waktu, deduplikasi, transaksi, dan concurrency PostgreSQL
dapat dijalankan terhadap PRD serta database lokal terisolasi. Hasil tersebut
tidak menggantikan dua pengujian dengan kode platform aktual:

1. **Kesetaraan scheduler lama/baru.** Jalankan `collection_scheduler_once` lama
   dan scheduler baru dengan fixture serta waktu tetap yang sama. Bandingkan
   kolom kontrak dan JSON yang diparse, dengan mengecualikan `id` serta
   `created_at`.
2. **Kompatibilitas ingestion aktual.** Jalankan `ingestion_once` dari source
   platform terhadap job sosial dan berita hasil scheduler baru, dengan
   konektor uji dan penyimpanan/event test doubles yang diperlukan. Buktikan
   pemilihan platform, penerusan periode, dan perubahan `queued` menjadi
   `ready` menggunakan worker itu sendiri.

Kedua pengujian kemudian dijalankan memakai image yang sama dengan container
acuan, tanpa menyalin source internal ke repo ini. Compose aktif juga diperiksa
untuk memastikan entrypoint yang dipakai pada saat pergantian service.

Simulator ingestion yang dibuat terpisah hanya dapat memeriksa bentuk kontrak.
Simulator tersebut tidak boleh dilaporkan sebagai keberhasilan kompatibilitas
dengan worker ingestion yang sudah berjalan.
