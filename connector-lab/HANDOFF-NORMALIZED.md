# Handoff Connector Lab normalized ingest

Kontrak mentor: `README-DERAI-INGESTION.md` (SHA-256 `285c4980d665c09d037984451aee6341b867505f0d1c4ef6c5cb073ce968d268`).

Image **`derai-connector-lab:local`** di dev-tessar sudah dipromosikan dari kandidat yang diuji dan memakai **`derai-platform_default`**. Dari jaringan itu, backend adalah `http://api:8000`. `DERAI_API_TOKEN` berasal dari login akun layanan yang berizin tulis pada tenant/workspace tujuan, berlaku 24 jam, dan perlu diperbarui lewat pengelola rahasia atau sesi yang mengelola login. Jangan menempel token ke chat atau menyimpannya dalam Git. Variabel environment menang atas file yang diteruskan dengan `--env-file`.

```sh
cd ~/aldo/derai-platform/derai-collection-scheduler/connector-lab
docker run --runtime runc --rm --init --network derai-platform_default \
  --shm-size 256m --cap-drop ALL --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" --env DERAI_API_URL=http://api:8000 --env DERAI_API_TOKEN \
  --mount "type=bind,src=$PWD/.env,dst=/run/derai/llm.env,readonly" \
  derai-connector-lab:local "$SOURCE_URL" \
  --env-file /run/derai/llm.env --persist --topic-id "$TOPIC_ID" \
  --tenant-id "$TENANT_ID" --workspace-id "$WORKSPACE_ID" --idempotency-key "$DELIVERY_KEY"
```

Satu proses mengambil satu URL. Untuk X, Connector Lab mengambil teks dari [oEmbed X resmi](https://docs.x.com/x-for-websites/embedded-posts/overview) dan memverifikasi ID posting. Post privat, dihapus, atau teks tidak lengkap gagal dengan exit code nonzero. Untuk berita dari host, gunakan `~/aldo/derai-article-scraper/collect.py` seperti dijelaskan di [runbook Article Scraper](../article-scraper/README.md#handoff-cron--connector-lab--derai). Isi artikel dari engine tetap memakai semua field repo acuan. Backend menerima artikel itu sebagai `payload` dan media sosial X sebagai `payload.data[0]`.

Sebelum POST, Connector Lab memanggil `GET /api/v1/topics/{topic_id}` dan mencocokkan tenant, workspace, dan status topik. Lalu submit ke `POST /api/v1/ingestion/normalized`. Stdout sukses tepat satu objek, misalnya `{"status":"created","idempotency_key":"<delivery-key>"}`. Pengiriman ulang meminta konfirmasi backend lagi dan mengembalikan `existing` saat deduplikasi berlaku. Backend DERAI yang mengelola storage dan proyeksi.

Verifikasi di dev-tessar: runner `check` lulus; image terhubung ke readiness backend (`200`) dan berhasil membaca satu posting publik tanpa key LLM. Salinan image backend aktif yang diisolasi membuktikan normalized import untuk X dan berita, termasuk pengecekan scope, `created` lalu `existing`, dan bukti JSON asli di object store fixture. Impor artikel ke topik gabungan yang dipilih pengguna juga sudah menghasilkan satu Mentions dengan isi dan tanggal sumber yang cocok. Uji live tersebut adalah berita, bukan bukti impor X pada topik aktif atau proyeksi ClickHouse. Detail ada pada [verifikasi](../docs/ARTICLE-SCRAPER-VERIFICATION.md).

`connector_command()` pada runner server sudah memakai `--network derai-platform_default`, dan konfigurasi rahasia backend ada di `.env` mode `600`. Mentor dapat menjalankan `python3 derai-collection-scheduler/links/collection_links.py check` dari root `derai-platform` sebelum menjalankan runner X. Cron baru belum dipasang. Runner X tidak menggantikan koleksi berita: jangan mematikan `SOCIAL_COLLECTION_ENABLED` sampai kedua jenis job lama memang sudah dialihkan, karena flag itu mematikan penjadwalan berita juga. Perpindahan kali ini mengganti engine berita di belakang gateway, sehingga scheduler lama tetap digunakan.
