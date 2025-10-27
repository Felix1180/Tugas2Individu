# Arsitektur Sistem Sinkronisasi Terdistribusi

Dokumen ini menjelaskan arsitektur tingkat tinggi dari sistem sinkronisasi terdistribusi yang diimplementasikan.

## Gambaran Umum

Sistem ini dirancang sebagai klaster multi-node (umumnya 3 node) yang berjalan dalam kontainer Docker terpisah. Tujuannya adalah untuk menyediakan mekanisme sinkronisasi seperti *distributed lock*, *distributed queue*, dan *distributed cache* yang konsisten dan toleran terhadap kegagalan. Sebuah instance Redis digunakan sebagai penyimpan state eksternal untuk komponen Queue.

Setiap node aplikasi identik dan mengekspos API HTTP untuk interaksi klien serta untuk komunikasi internal antar node. Orkestrasi keseluruhan sistem dilakukan menggunakan Docker Compose.

**(Diagram Arsitektur)**

```mermaid
graph LR
    subgraph "Distributed System"
        direction LR
        N1[Node 1 App<br>(Flask, Raft, Cache, Queue)]
        N2[Node 2 App<br>(Flask, Raft, Cache, Queue)]
        N3[Node 3 App<br>(Flask, Raft, Cache, Queue)]
        R[Redis<br>(Queue Persistence)]
    end

    C[Client] -->|HTTP API<br>(Any Node)| N1

    subgraph "Internal Communication"
        direction TB
        N1 <-->|Raft RPC| N2
        N2 <-->|Raft RPC| N3
        N1 <-->|Raft RPC| N3

        N1 -->|Cache Invalidate<br>(Broadcast)| N2
        N1 -->|Cache Invalidate<br>(Broadcast)| N3
        %% Similar broadcasts from N2 and N3 omitted for clarity

        N1 -->|Queue Forward| N2
        N2 -->|Queue Forward| N3
        N3 -->|Queue Forward| N1
        %% Forwarding depends on Consistent Hashing result

        N1 -->|Queue R/W| R
        N2 -->|Queue R/W| R
        N3 -->|Queue R/W| R
    end

    style R fill:#f9f,stroke:#333,stroke-width:2px



* **Saran:** Gunakan alat seperti [draw.io](https://app.diagrams.net/), Mermaid ([https://mermaid.live/](https://mermaid.live/)), atau Visio.
* **Tampilkan:**
    * 3 Kotak untuk Node Aplikasi (Node 1, Node 2, Node 3).
    * 1 Kotak untuk Redis.
    * Panah menunjukkan:
        * Komunikasi RPC Raft (dua arah) antar semua node aplikasi.
        * Komunikasi Cache Invalidation (satu arah broadcast) antar node aplikasi.
        * Komunikasi Queue (Push/Pop/Ack, bisa direct atau forwarding) antar node aplikasi.
        * Akses Node Aplikasi ke Redis (untuk Queue).
        * Akses Klien Eksternal ke salah satu Node Aplikasi via HTTP API.

## Komponen Utama

### Node Aplikasi (Python/Flask/Uvicorn)

Setiap node adalah aplikasi Python yang dibangun di atas Flask (dengan wrapper ASGI) dan dijalankan oleh server Uvicorn. Node berisi logika untuk:

1.  **Raft Consensus (`consensus/raft.py`)**:
    * Mengimplementasikan algoritma Raft untuk pemilihan *leader* dan replikasi *log*.
    * Berkomunikasi dengan *peer* lain melalui RPC (`/request_vote`, `/append_entries`).
    * Menjaga state Raft internal (`current_term`, `voted_for`, `log`, `commit_index`, `state`).
2.  **Lock Manager (`nodes/lock_manager.py`)**:
    * Bertindak sebagai *state machine* yang state-nya (`_locks`, `_wait_list`) dikelola secara konsisten oleh Raft.
    * Menangani logika `acquire` dan `release` *lock* (shared/exclusive).
    * Mengimplementasikan deteksi *deadlock* (saat ini bermasalah).
    * Menggunakan `asyncio.Lock` untuk *thread safety* internal.
3.  **Cache Node (`nodes/cache_node.py`)**:
    * Menyimpan cache lokal dalam `OrderedDict` (untuk LRU).
    * Mengimplementasikan protokol *write-invalidate* dengan mengirim RPC `/cache/invalidate` ke *peer*.
4.  **Queue Node (`nodes/queue_node.py`)**:
    * Berinteraksi dengan Redis (`redis-py asyncio`) untuk menyimpan pesan antrian (`RPUSH`, `LMOVE`, `LREM`, `HSET`, `HDEL`).
    * Menggunakan `ConsistentHashRing` (`utils/consistent_hash.py`) untuk menentukan node mana yang bertanggung jawab atas suatu topik.
    * Menangani *forwarding* permintaan `push`/`pop`/`ack` ke node yang benar.
    * Menjalankan *background task* (`_monitor_timeouts`) untuk menangani pesan yang tidak di-ACK (*at-least-once* dasar).
5.  **API Layer (`nodes/base_node.py`)**:
    * Mengekspos semua endpoint HTTP untuk klien dan komunikasi internal.
    * Merutekan permintaan ke komponen yang sesuai (`RaftNode`, `LockManager`, `CacheNode`, `QueueNode`).
    * Menggunakan `asgiref.wsgi.WsgiToAsgi` untuk menjembatani Flask dengan Uvicorn.

### Redis

Berfungsi sebagai *backend* penyimpanan data yang persisten dan terpusat (secara logis) untuk:
* Antrian pesan utama per topik (`queue:{topic}`).
* Daftar pesan yang sedang diproses per *consumer* (`processing:{topic}:{consumer_id}`).
* Timestamp pesan yang sedang diproses (`timestamps:{topic}:{consumer_id}`).

### Komunikasi Antar Node (`communication/message_passing.py`)

Menggunakan `aiohttp` untuk mengirim permintaan HTTP POST asinkron antar node untuk keperluan RPC Raft, Cache Invalidation, dan Queue Forwarding.

### Orkestrasi (Docker Compose)

File `docker-compose.yml` mendefinisikan:
* Layanan `redis` (dari image resmi Redis).
* Tiga layanan `node1`, `node2`, `node3` yang dibangun dari `Dockerfile.node`.
* Variabel lingkungan untuk setiap node (ID, port, host Redis).
* Jaringan Docker kustom (`distributed_system_net`) agar semua kontainer bisa berkomunikasi.
* Perintah `command` spesifik untuk Uvicorn agar setiap node berjalan di port yang benar.

## Alur Kerja Utama

* **Startup:** Docker Compose memulai semua kontainer. Node aplikasi memulai Raft, yang kemudian melakukan pemilihan *leader*.
* **Lock Acquire:** Klien mengirim `POST /lock/acquire` ke *leader*. *Leader* menambahkan perintah ke log, mereplikasikannya via `AppendEntries`, menunggu mayoritas, meng-*commit*, menerapkan ke `LockManager`, lalu merespons klien.
* **Queue Push:** Klien mengirim `POST /queue/push` ke node mana pun. Node tersebut menggunakan *consistent hash* untuk menemukan node target. Jika dirinya sendiri, ia `RPUSH` ke Redis. Jika node lain, ia *forward* request ke `/queue/internal/push` node target.
* **Queue Pop:** Klien mengirim `GET /queue/pop/...`. Node yang menerima menggunakan *hash* untuk menemukan node target. Jika dirinya sendiri, ia `LMOVE` pesan dari `queue:` ke `processing:`, mencatat *timestamp*, dan mengembalikan pesan. Jika node lain, ia *forward* request. Pesan yang *timeout* akan dikembalikan ke `queue:` oleh *monitor task*.
* **Cache Set:** Klien mengirim `POST /cache/set` ke node mana pun. Node tersebut memperbarui cache lokalnya dan mengirim `POST /cache/invalidate` ke semua *peer*.