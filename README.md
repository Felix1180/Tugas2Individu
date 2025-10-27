# Implementasi Sistem Sinkronisasi Terdistribusi (Tugas 2)

Repositori ini berisi implementasi sistem sinkronisasi terdistribusi sebagai bagian dari Tugas 2 Mata Kuliah Sistem Paralel dan Terdistribusi. Sistem ini mensimulasikan komponen-komponen penting untuk menjaga konsistensi data antar node dalam lingkungan terdistribusi.

---

## 📜 Deskripsi Proyek

Tujuan proyek ini adalah mengembangkan sistem yang mampu menangani sinkronisasi data antar beberapa node. Fitur utama meliputi:

- **Distributed Lock Manager:** Menggunakan algoritma konsensus Raft untuk _mutual exclusion_ yang _fault-tolerant_.
- **Distributed Queue System:** Menggunakan _Consistent Hashing_ untuk perutean topik dan Redis untuk persistensi, dengan jaminan _at-least-once delivery_ dasar.
- **Distributed Cache Coherence:** Implementasi protokol _write-invalidate_ sederhana dengan kebijakan LRU.
- **Containerization:** Sistem berjalan sebagai _multi-node cluster_ menggunakan Docker dan Docker Compose.

---

## ✨ Fitur Utama

- **Konsensus Raft:** Pemilihan _leader_ otomatis, replikasi log state _lock_, dan _fault tolerance_ dasar.
- **Lock Manager:** Mendukung _lock_ eksklusif (shared belum teruji penuh), dengan state direplikasi ke semua node.
- **Queue System:** Perutean pesan berbasis topik menggunakan _Consistent Hashing_, persistensi di Redis, _forwarding_ antar node, dan mekanisme ACK + _timeout_ untuk _at-least-once delivery_ dasar.
- **Cache Coherence:** Cache lokal per node dengan LRU dan protokol _write-invalidate_ sederhana.
- **Audit Logging:** Pencatatan dasar untuk operasi _acquire_ dan _release_ lock.
- **Containerized:** Mudah dijalankan dan diskalakan menggunakan Docker Compose.
- **API:** Endpoint HTTP untuk berinteraksi dengan semua fitur.

---

## 💻 Teknologi yang Digunakan

- **Bahasa:** Python 3.9+
- **Framework Web:** Flask (dengan wrapper ASGI `asgiref`)
- **Server ASGI:** Uvicorn
- **Konsensus:** Implementasi Raft manual
- **Komunikasi Antar Node:** `aiohttp` (HTTP Client/Server Asinkron)
- **Penyimpanan Queue:** Redis
- **Containerization:** Docker, Docker Compose
- **Hashing:** `mmh3` (untuk Consistent Hashing)
- **Testing:**
  - Manual: `curl`
  - Unit/Integrasi: `pytest`, `pytest-asyncio`, `requests`
  - Beban: `Locust`
- **Lainnya:** `python-dotenv`, `asyncio`

---

## 🏗️ Arsitektur

Sistem terdiri dari 3 node aplikasi identik dan 1 node Redis, berjalan dalam jaringan Docker. Setiap node aplikasi berisi logika Raft, Lock Manager, Queue Node, dan Cache Node. Raft digunakan untuk konsensus Lock Manager, Consistent Hashing untuk routing Queue ke Redis, dan broadcast HTTP untuk Cache Invalidation.

_Untuk detail lebih lanjut dan diagram visual, lihat file `docs/architecture.md`._

---

## 🚀 Setup & Menjalankan

**Prasyarat:**

- Git
- Docker & Docker Compose

**Langkah-langkah:**

1.  **Clone repository:**
    ```bash
    git clone [https://github.com/Felix1180/Tugas2Individu.git](https://github.com/Felix1180/Tugas2Individu.git)
    cd distributed-sync-system
    ```
2.  **(Opsional) Salin file environment:**
    ```bash
    # Windows PowerShell
    copy .env.example .env
    # Linux/macOS/Git Bash
    # cp .env.example .env
    ```
3.  **Jalankan dengan Docker Compose:**
    ```bash
    docker-compose -f docker/docker-compose.yml up --build
    ```
    Biarkan terminal ini berjalan. Tunggu hingga leader Raft terpilih.
4.  **Akses Sistem:** API tersedia di `http://localhost:5001`, `http://localhost:5002`, dan `http://localhost:5003`.

---

## 🛠️ Contoh Penggunaan API (via cURL)

_(Pastikan Anda mengirim request acquire/release ke **Leader** Raft saat ini, yang bisa dicek via `/status`)_

- **Cek Status Node:**
  ```bash
  curl http://localhost:5001/status
  ```
- **Acquire Lock (ke Leader, misal port 5002):**
  ```bash
  curl -X POST -H "Content-Type: application/json" -d '{"resource_id": "my-resource", "client_id": "my-app"}' http://localhost:5002/lock/acquire
  ```
- **Release Lock (ke Leader):**
  ```bash
  curl -X POST -H "Content-Type: application/json" -d '{"resource_id": "my-resource", "client_id": "my-app"}' http://localhost:5002/lock/release
  ```
- **Set Cache (ke node mana saja):**
  ```bash
  curl -X POST -H "Content-Type: application/json" -d '{"key": "user:1", "value": "Data User 1"}' http://localhost:5001/cache/set
  ```
- **Get Cache (dari node mana saja):**
  ```bash
  curl http://localhost:5001/cache/user:1
  ```
- **Push ke Queue (ke node mana saja):**
  ```bash
  curl -X POST -H "Content-Type: application/json" -d '{"topic": "emails", "message": "Kirim email selamat datang"}' http://localhost:5001/queue/push
  ```
- **Pop dari Queue (ke node yang di-hash, perlu ID consumer):**
  ```bash
  # Misal 'emails' di-hash ke node 3, consumer ID 'worker-bee'
  curl http://localhost:5003/queue/pop/emails/worker-bee
  ```
- **Ack Pesan Queue (ke node yang di-hash):**
  ```bash
  # Dapatkan message_id dari hasil pop
  curl -X POST -H "Content-Type: application/json" -d '{"consumer_id": "worker-bee", "message_id": "ID_DARI_HASIL_POP"}' http://localhost:5003/queue/ack/emails
  ```

_Untuk dokumentasi API yang lebih formal, lihat `docs/api_spec.yaml`._

---

## ✅ Pengujian

- **Unit Tests:** Menguji komponen individual (misal: Consistent Hashing).
  ```bash
  # Aktifkan .venv
  pip install pytest pytest-asyncio
  python -m pytest tests/unit
  ```
- **Integration Tests:** Menguji interaksi antar komponen/node (misal: replikasi Raft). Memerlukan sistem berjalan via `docker-compose`.
  ```bash
  # Aktifkan .venv
  pip install requests
  # Pastikan docker-compose up berjalan di terminal lain
  python -m pytest tests/integration
  ```
- **Load Tests:** Mengukur performa dan stabilitas di bawah beban.
  ```bash
  # Aktifkan .venv
  pip install locust
  # Pastikan docker-compose up berjalan
  locust -f benchmarks/load_test_scenarios.py --host http://localhost:5001
  # Buka http://localhost:8089 di browser
  ```

---

## 📺 Video Demonstrasi

Berikut adalah link video demonstrasi sistem ini di YouTube:

[\[Link Video YouTube\]](https://youtube.com/live/WtSDVJ4TyeU)

---

## ⚠️ Isu yang Diketahui / Tantangan

- **Deteksi Deadlock:** Implementasi deteksi deadlock di `LockManager` saat ini **tidak berfungsi dengan benar** berdasarkan hasil pengujian dan memerlukan debugging lebih lanjut.
- **At-least-once Delivery:** Mekanisme ACK bersifat dasar dan mungkin memiliki _race condition_ atau kurang efisien dibandingkan Redis Streams.
- **Error Handling:** Penanganan error secara umum masih bisa ditingkatkan.

---

## 🧑‍💻 Author

- **Nama:** Christian Felix
- **NIM:** 11221080
