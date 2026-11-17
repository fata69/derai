# Verifikasi scraper dan cutover — 17 November 2026

Kontrak diperiksa terhadap kedua dokumen mentor. `README-DERAI-INGESTION.md` di Downloads dan server memiliki SHA-256 `285c4980d665c09d037984451aee6341b867505f0d1c4ef6c5cb073ce968d268`. Kontrak publik engine dipatok ke repo `aqshaaqso/article-scraper-engine-api`, commit `8596ede07e9f30573013637636c1d716f2e432fc`.

## Hasil yang diverifikasi

- OpenAPI engine baru sama persis dengan instance referensi yang tidak dipatch. Satu URL artikel menghasilkan JSON yang sama selain waktu pengambilan `fetched_at`.
- Uji keyword `Indonesia` di dev-tessar mendapatkan 3 artikel, 3 sukses, tanpa SerpAPI. JSON artikel yang disimpan dalam DB scraper cocok dengan respons HTTP, memperhitungkan pembulatan nanodetik Go ke mikrodetik Python.
- Unit test discovery: 12 lulus. Test Connector Lab dan normalized delivery: 17 lulus. Simulasi HTTP Postman menguji feed dan Chat Completions fixture; ini bukan uji provider LLM live.
- Salinan image backend DERAI aktif diuji dengan jaringan `none`, SQLite sementara, dan object store memory. X dan berita masing-masing membuat 1 raw, canonical, dan outbox; retry menghasilkan existing; scope salah ditolak sebelum POST.
- Pengguna memilih satu topik gabungan **Partai Demokrat, SBY, AHY, dan Herzaky Mahendra**, ID `dbe2948e-5945-4dc8-bad1-c6f613cb3cd8`. Artikel ANTARA **AHY: Partai Demokrat tidak ajukan nama untuk isi kursi wapres** diimpor lewat API normalized, bukan SQL langsung. Pengiriman pertama created, retry existing; API Mentions menampilkan tepat satu item dengan teks dan waktu sumber yang cocok. Raw ID: `0bee8ce0-f1b0-43b4-a983-82b61efda11d`. Waktu sumber `2026-11-13T11:17:49+07:00`; filter dashboard harus mencakup tanggal itu. Dashboard visual dan proyeksi ClickHouse tidak diperiksa.

## Service aktif dan jalur pemanggilan

Engine baru: direktori `~/aldo/derai-article-scraper` pada `dev-tessar@10.10.101.151`. Compose project `derai-article-scraper`. API host `http://127.0.0.1:18011`, alamat privat gateway `http://10.10.101.151:18011`, dan alias pada jaringan `derai-platform_default` adalah `http://derai-article-engine:8010`. Key internal disimpan dalam `.env` server, tidak dalam Git.

Gateway lama tetap hidup di `192.168.99.160:8088`. Binary dan kredensial sosialnya tidak berubah. Hanya `ARTICLE_SCRAPER_BASE_URL` dan `ARTICLE_SCRAPER_API_KEY` diarahkan ke engine baru. Uji gateway sementara memverifikasi capabilities tidak berubah, keyword menghasilkan artikel, dan job historis memberikan field lama yang cocok. Setelah cutover, `UnifiedSocialConnector` asli pada image ingestion DERAI berhasil authenticate dan collect artikel lewat gateway aktif.

Sebanyak 2.621 command terminal, 3 search run, 2.619 job dan 643 item dari PostgreSQL engine lama diimpor ke DB scraper baru tanpa mengganti row uji baru. ID job dipertahankan; serial item internal dialokasikan ulang. Import transaksi memeriksa seluruh field setiap row. Tidak ada job aktif pada snapshot sebelum penghentian. Riwayat SQLite legacy tetap berada di volume legacy, tidak dicampurkan ke PostgreSQL.

Pada PopOS, container berikut stopped dengan restart policy `no`: `article-scraper-engine-api-article-scraper-1`, `derai-article-middleware-v06`, `derai-article-worker-v06`, dan `derai-article-postgres-v06`. Volume, source dan image lama dipertahankan. ID seluruh container lain yang berjalan pada host PopOS tetap sama.

Image `derai-connector-lab:local` di dev-tessar dipromosikan dari `normalized-candidate`. Image sebelumnya disimpan sebagai `derai-connector-lab:before-normalized-20261117`. Runner server menggunakan jaringan `derai-platform_default`; belum ada cron baru. Token DERAI yang berlaku 24 jam harus diperbarui untuk operasi berkala. Penemuan URL X tetap menjadi tanggung jawab runner mentor. RSS engine berita tidak menjamin kelengkapan arsip atau semua keyword.

## Bukti privat dan rollback

Pada dev-tessar: `~/aldo/derai-article-scraper/artifacts/verification.json`, `backend-verification.json`, `live-normalized-verification.json`. Snapshot history dan konfigurasi rahasia tersimpan di `.runtime/` yang diabaikan Git.

Pada PopOS: `~/konektor-medsos/.deploy/derai-replacement-20261117/` berisi backup `.env`, identitas runtime, snapshot history, `stage-report.json`, `promoted.json`, dan `retired.json`. Jangan membagikan direktori ini karena berisi credential.

Untuk rollback engine, dari direktori backup PopOS jalankan `python3 gateway_cutover.py rollback`. Script mengembalikan restart policy dan service lama serta konfigurasi gateway yang dibackup. Data engine baru tetap dipertahankan. Untuk rollback Connector Lab, tag kembali image `before-normalized-20261117` menjadi `local`; backup `.env` dan runner ada pada `~/aldo/derai-article-scraper/.runtime/runner-before-normalized`. Tidak perlu mengubah backend, MinIO, ClickHouse, atau scheduler untuk rollback engine.
