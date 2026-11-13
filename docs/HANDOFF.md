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

[GitHub Actions](https://github.com/fata69/derai/actions/workflows/verify.yml) menjalankan tes scheduler tanpa PostgreSQL di macOS Apple Silicon dan tes lengkap dengan PostgreSQL fixture di Docker Linux. Tes ini tidak memakai API key atau database DERAI aktif.

Repo memuat [contoh output yang diharapkan](../fixtures/expected-prd-jobs.json).
Untuk menghasilkan snapshot PostgreSQL dan mereproduksi `match=true`,
`missing=0`, `unexpected=0`, ikuti langkah ekspor sesuai OS di [README](../README.md).
Snapshot demo diambil dari database fixture dan tidak mengandung data produksi.

## Bukti yang masih dibutuhkan untuk integrasi

Mohon snapshot atau akses baca repo untuk revisi `derai-platform` yang cocok
dengan container acuan. Agar tes dapat dijalankan di laptop tanpa akses ke
layanan produksi, sertakan:

- Paket `app/`, khususnya `workers.py` dan `db.py`, beserta file dependensi.
- Migrasi yang membentuk `public.records`, constraint `uq_scope_kind_idem`,
  grant role, dan kebijakan RLS aktual.
- `tests/test_social_ingestion.py` dan fixture yang diimpornya, atau harness
  resmi yang menjalankan ingestion dengan konektor uji.
- Contoh konfigurasi dengan nilai dummy; kredensial produksi tidak diperlukan.

Setelah source tersedia, jalankan dua pemeriksaan dari
[checklist integrasi](INTEGRATION_CHECKLIST.md): bandingkan output scheduler lama
dan baru pada jam/fixture yang sama, lalu jalankan `ingestion_once` asli untuk
membuktikan kedua jenis job berpindah dari `queued` ke `ready`. Jangan gunakan
hasil fixture lokal sebagai bukti bahwa dua pemeriksaan ini sudah lulus.

Lab opsional untuk mencoba key Gemini/OpenRouter/endpoint kompatibel tersedia
di [connector-lab](../connector-lab/README.md). Lab belum terhubung ke antrean
atau worker asli. Key dan `.env` pribadi tidak ikut di repo.
