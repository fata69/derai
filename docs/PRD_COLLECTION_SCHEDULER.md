# PRD Collection Scheduler DERAI

**Tujuan:** Mengganti implementasi `collection-scheduler` dengan framework pilihan tim sambil mempertahankan input PostgreSQL, aturan penjadwalan, dan output yang dipakai `ingestion-worker` DERAI. Acuan utamanya adalah kode di container yang berjalan pada 13 November 2026.

## 1. Ruang lingkup

Scheduler membaca topik dan membuat baris job berstatus `queued` dalam tabel PostgreSQL `public.records`. `ingestion-worker` yang sudah berjalan mengambil baris tersebut, membaca topik induk, dan menjalankan konektor. Pemanggilan konektor, pengambilan konten, penulisan ke MinIO, dan penerbitan event merupakan tanggung jawab komponen downstream. Scheduler hanya memerlukan koneksi PostgreSQL.

## 2. Kontrak input

| Input | Kontrak |
| --- | --- |
| PostgreSQL | Gunakan database DERAI yang sama setelah migrasi selesai. Role saat ini adalah `derai_worker`. Operasi scheduler membutuhkan `SELECT` dan `INSERT` pada `public.records` dengan kebijakan RLS yang sesuai. |
| Pemilihan topik | Baca baris dengan `kind = 'topic'` dan `status <> 'deleting'` dari seluruh tenant/workspace yang dilayani. |
| Identitas topik | Gunakan `id`, `tenant_id`, dan `workspace_id` dari baris topik. |
| Kata kunci | Parse `records.data` sebagai objek JSON yang disimpan dalam kolom `text`. Baca array `keywords` sesuai urutan aslinya. Jika field absen atau array kosong, topik menghasilkan nol job. API DERAI mendefinisikan kata kunci sebagai array string. |
| Waktu tick | Gunakan waktu saat tick dimulai. Sediakan cara memasukkan waktu tetap saat uji kontrak. Untuk kompatibilitas dengan fungsi lama, waktu tanpa zona pada input uji diartikan sebagai UTC. |

Contoh input baris topik:

```json
{
  "id": "11111111-1111-4111-8111-111111111111",
  "tenant_id": "22222222-2222-4222-8222-222222222222",
  "workspace_id": "33333333-3333-4333-8333-333333333333",
  "kind": "topic",
  "status": "ready",
  "data": "{\"keywords\":[\" TNI \",\"Indonesia\",\"tni\",\"\"]}"
}
```

### Konfigurasi runtime

| Pengaturan | Nilai di server acuan | Semantik |
| --- | --- | --- |
| `DATABASE_URL` dan autentikasi PostgreSQL | PostgreSQL eksternal DERAI dengan role `derai_worker` | Framework baru boleh memakai nama atau format pengaturan sendiri selama menunjuk database dan role yang sesuai. Deployment lama memakai `PGPASSWORD` secara terpisah. |
| `WORKER_INTERVAL` | `60` | Tick pertama segera setelah startup. Implementasi lama menunggu 60 detik setelah tiap tick selesai, termasuk setelah gagal. |
| `SOCIAL_COLLECTION_ENABLED` | `true` | Kedua jenis job aktif saat nilai setelah trim dan konversi huruf kecil adalah `1`, `true`, `yes`, atau `on`. Nilai lain menghasilkan nol job tanpa query topik. Default Compose aktif. |
| `CONNECTOR_ARTICLE_MAX_PAGES` | `1` | Masukkan nilai konfigurasi sebagai **string** di JSON berita. Default `"1"` bila variabel absen. |

## 3. Aturan penjadwalan

1. Konversi waktu tick ke UTC dan bulatkan turun ke awal jam. Simpan hasilnya sebagai `hour`. Contoh: tick `2026-11-13T11:37:20+07:00` menghasilkan `2026-11-13T04:00:00+00:00`. Pakai bentuk ISO 8601 dengan detik, tanpa pecahan detik, dan offset literal `+00:00`. Bentuk ini juga masuk ke kunci deduplikasi.
2. Untuk setiap topik, trim kata kunci seperti Python `str.strip()`. Buang hasil kosong. Untuk kompatibilitas dengan data lama yang berisi elemen non-string, worker lama melakukan `str(raw_keyword)` sebelum trim. Contoh: JSON `null` menjadi `"None"`, boolean `true` menjadi `"True"`, dan angka `42` menjadi `"42"`.
3. Deduplicasi dalam satu topik dengan Unicode **full case folding** yang setara dengan Python `str.casefold()`. Ambil kemunculan pertama dan pertahankan ejaannya setelah trim untuk `query`. Contoh: `"Straße"` dan `"STRASSE"` memiliki bentuk deduplikasi yang sama, `strasse`.
4. Untuk setiap kata kunci unik, siapkan satu job media sosial dan satu job berita. Keduanya dijadwalkan untuk `hour`. Jendela media sosial adalah `[hour - 1 jam, hour)`. Job berita mengikuti jadwal yang sama dengan field periode absen.
5. Tick hanya mengevaluasi jam saat itu. Jika proses berhenti beberapa jam, saat hidup kembali ia hanya mengevaluasi jam saat ini. Kata kunci yang baru ditambahkan di tengah jam dapat dibuat pada tick berikutnya untuk jam yang sama.

## 4. Kontrak output PostgreSQL

Satu job adalah satu baris baru di `public.records`.

| Kolom | Tipe di PostgreSQL | Nilai awal |
| --- | --- | --- |
| `id` | `varchar(36)` | UUID v4 sebagai string kanonis. Buat di aplikasi sebelum INSERT. |
| `tenant_id` | `varchar(36)` | Salin `topic.tenant_id`. |
| `workspace_id` | `varchar(36)` | Salin `topic.workspace_id`. |
| `kind` | `varchar(40)` | `job`. |
| `parent_id` | `varchar(36)` | Salin `topic.id`. |
| `name` | `varchar(300)` | `social-media` atau `online-news`. |
| `data` | `text` | Objek JSON yang diserialisasi sekali menjadi string. Urutan properti dan spasi JSON bebas. Nama, nilai, tipe, serta keberadaan field mengikuti contoh. |
| `status` | `varchar(30)` | `queued`. Status selanjutnya dikelola ingestion. |
| `idempotency_key` | `varchar(200)` | Kunci deterministik dari topik, kata kunci, jenis job, dan jam. |
| `created_at` | `varchar(40)` | Waktu pembuatan baris dalam ISO 8601 UTC dengan `+00:00`. Gunakan waktu tulis aktual. |

### Payload media sosial

```json
{
  "topic_id": "11111111-1111-4111-8111-111111111111",
  "connector": "social-media",
  "query": "TNI",
  "search_type": "keyword",
  "fetch_mode": "page",
  "limit_per_platform": 10,
  "options": {},
  "scheduled_for": "2026-11-13T04:00:00+00:00",
  "period_start": "2026-11-13T03:00:00+00:00",
  "period_end": "2026-11-13T04:00:00+00:00"
}
```

Field `platforms` absen. Ingestion mengambil daftar platform dari `CONNECTOR_PLATFORMS`. Saat X termasuk daftar, ingestion meneruskan waktu awal dan akhir ke opsi pencarian X. Ingestion menerapkan filter periode pada hasil yang dikumpulkan.

### Payload berita online

```json
{
  "topic_id": "11111111-1111-4111-8111-111111111111",
  "connector": "social-media",
  "query": "TNI",
  "platforms": ["online_news"],
  "search_type": "keyword",
  "fetch_mode": "page",
  "limit_per_platform": 10,
  "options": {
    "online_news": {
      "max_pages": "1"
    }
  },
  "scheduled_for": "2026-11-13T04:00:00+00:00"
}
```

Field `period_start` dan `period_end` absen. Nama baris memakai `online-news`, sedangkan nama platform, properti di `options`, dan segmen kunci deduplikasi memakai `online_news`. `connector` tetap `social-media`.

### Kunci deduplikasi dan transaksi

Hitung `digest = hex_lower(SHA-256(UTF-8(keyword_normalized)))[:16]`. Untuk `TNI`, input hash adalah `tni` dan digest-nya `b08f256307ea4e66`.

```text
collection:{topic_id}:{digest}:{hour}
collection:{topic_id}:{digest}:online_news:{hour}
```

Kunci lengkap untuk kata kunci `TNI` pada contoh di atas:

```text
collection:11111111-1111-4111-8111-111111111111:b08f256307ea4e66:2026-11-13T04:00:00+00:00
collection:11111111-1111-4111-8111-111111111111:b08f256307ea4e66:online_news:2026-11-13T04:00:00+00:00
```

Gunakan batas unik PostgreSQL `uq_scope_kind_idem` pada `(tenant_id, workspace_id, kind, idempotency_key)`. Untuk framework baru, gunakan `ON CONFLICT ON CONSTRAINT uq_scope_kind_idem DO NOTHING RETURNING id` agar dua tick yang bertumpuk dapat berjalan tanpa membatalkan seluruh transaksi karena konflik. Hitung hanya INSERT yang berhasil. Baris yang sudah ada tetap berlaku untuk deduplikasi dalam status apa pun, termasuk `failed`. Bila satu dari dua jenis job sudah ada, buat jenis yang masih hilang.

Commit sekali per tick. Jika parsing data topik atau transaksi gagal, rollback tick, log kegagalan, lalu jalankan tick berikutnya sesuai interval. Untuk observabilitas yang kompatibel dengan worker lama, catat `{"worker":"collection-scheduler","processed":4}` saat tick berhasil, atau `worker`, `error`, dan pesan yang sudah disaring saat gagal. `processed` menghitung baris baru, bukan konten yang diambil.

## 5. Kriteria penerimaan

| Skenario | Hasil yang diharapkan |
| --- | --- |
| Input contoh, tick pukul 11.37 WIB | Empat baris. Masing-masing jenis job memiliki query `TNI` dan `Indonesia`. Semua memakai `scheduled_for` yang sama. |
| Zona dan batas waktu | Tick `2026-11-13T11:37:20+07:00` dan `2026-11-13T04:37:20Z` menghasilkan jam dan kunci identik. Batas sosial tepat satu jam, dengan ujung akhir eksklusif. |
| Unicode | `[" Straße ", "STRASSE"]` menghasilkan dua job untuk query `Straße`. Digest untuk kedua jenis job adalah `16d96952087774fe`. |
| Restart, tick ulang, atau dua tick bersamaan | Hanya satu baris per kombinasi topik, kata kunci, jenis, dan jam. Tick ulang setelah commit menghasilkan `processed = 0`, termasuk jika job sebelumnya sudah `failed`. |
| Satu jenis job sudah ada | Tick hanya menulis jenis yang masih hilang. |
| Jam berganti atau beberapa jam terlewat | Jam baru menghasilkan kunci baru. Tidak ada baris untuk jam yang terlewat. |
| Topik dihapus, kata kunci kosong, atau scheduler dinonaktifkan | Tidak ada job baru untuk kasus tersebut. Dengan flag nonaktif, scheduler tidak query topik. |
| Tenant/workspace berbeda | Setiap job menyalin cakupan topiknya sendiri. Kata kunci yang sama di topik berbeda tetap membuat job masing-masing. |
| Konfigurasi berita `CONNECTOR_ARTICLE_MAX_PAGES=3` | Payload berita berisi `"max_pages": "3"`. Payload sosial tetap memakai `"options": {}`. |
| Kompatibilitas ingestion | Jalankan worker ingestion yang ada terhadap dua baris fixture dari scheduler baru dengan konektor uji. Worker mengambil keduanya sebagai job `queued`, memakai daftar platform sesuai kontrak, dan dapat mengubah status menjadi `ready`. |

## 6. Penggantian di server

1. Bandingkan output scheduler lama dan baru dengan salinan data atau fixture yang sama dan waktu yang dipatok. Bandingkan kolom kontrak dan JSON yang sudah diparse. Kecualikan nilai acak `id` dan waktu tulis aktual `created_at`.
2. Setelah uji lulus, hentikan service `collection-scheduler` lama dan cegah Compose mengaktifkannya lagi pada deployment berikutnya. Jalankan scheduler baru pada PostgreSQL yang sama. Job lama tetap tersimpan dan kunci yang sama mencegah duplikasi pada jam transisi.
3. Periksa metrik tick, jumlah job baru per jenis, dan status job setelah ingestion. Jika perlu kembali ke scheduler lama, hentikan scheduler baru lalu aktifkan scheduler lama. Keduanya memakai format kunci yang sama.

## Acuan implementasi

File pada checkout `derai-platform` di server acuan. Alamat internal dan path akun server disimpan di salinan PRD asli.

- `app/workers.py` — `collection_scheduler_once`, `build_connector`, `ingestion_once`, dan loop `main`.
- `app/db.py` dan `migrations/versions/0001_operational_rls.py` — skema baris, kunci unik, grant, dan RLS.
- `compose.yaml` dan `compose.external.yaml` — konfigurasi service aktif.
- `tests/test_social_ingestion.py` — contoh uji jam UTC, payload berita, dan deduplikasi.
