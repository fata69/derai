# Serah terima Collection Scheduler DERAI

Implementasi baru menjalankan tick dengan APScheduler, membaca `public.records`,
dan memasukkan job `queued` untuk media sosial dan berita. Input, payload,
format jam, kunci deduplikasi, dan transaksi mengikuti PRD 13 November 2026.

## Reproduksi di MacBook, Linux, atau Windows

Untuk checkout baru, jalankan:

```sh
git clone https://github.com/fata69/derai.git
cd derai
```

Di macOS/Linux, ikuti [jalur Docker Compose](../README.md#macos-dan-linux-tanpa-powershell). Di Windows, jalankan helper berikut dari PowerShell:

```powershell
.\scripts\local.ps1 Setup
.\scripts\local.ps1 Demo
.\scripts\local.ps1 TestPostgres
```

Pada database demo baru, `Demo` melaporkan `processed=4`, lalu `processed=0`.
Database fixture tersedia pada `127.0.0.1:55432`; tes memakai database terpisah.
Jalankan `docker compose --profile dev up -d --build` untuk memulai loop.
Cara menjalankan uji lengkap dan menghentikan layanan ada di [README](../README.md).

Untuk verifikasi tambahan, pemilik repo bisa memilih **Run workflow** di [GitHub Actions](https://github.com/fata69/derai/actions/workflows/verify.yml). Workflow manual menjalankan tes scheduler tanpa PostgreSQL di macOS Apple Silicon dan tes lengkap dengan PostgreSQL fixture di Docker Linux. Tes tidak memakai API key atau database DERAI aktif. Jika runner tidak dapat dimulai, gunakan langkah Docker Compose di atas.

Repo memuat [contoh output yang diharapkan](../fixtures/expected-prd-jobs.json).
Untuk menghasilkan snapshot PostgreSQL dan mereproduksi `match=true`,
`missing=0`, `unexpected=0`, ikuti langkah ekspor sesuai OS di [README](../README.md).
Snapshot demo diambil dari database fixture dan tidak mengandung data produksi.

## Integrasi dengan DERAI

Scheduler baru sudah diuji terhadap skrip yang dijalankan service lama dan
fungsi ingestion asli dari image DERAI. Dua job yang dihasilkan scheduler baru
berpindah dari `queued` ke `ready` dengan konektor fixture. Hasil, cara uji ulang,
dan langkah rollback tercatat di [verifikasi server](SERVER-VERIFICATION.md).

Connector URL untuk Gemini/OpenRouter/endpoint kompatibel tersedia
di [connector-lab](../connector-lab/README.md). Kontrak persist dan pemanggilan
cron ada di [handoff normalized](../connector-lab/HANDOFF-NORMALIZED.md).
Engine berita baru sudah menggantikan engine lama pada gateway; hasil uji,
riwayat yang dipertahankan, dan rollback ada di
[verifikasi scraper](ARTICLE-SCRAPER-VERIFICATION.md). Key dan `.env` pribadi
tidak ikut di repo.
