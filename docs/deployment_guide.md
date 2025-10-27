# Panduan Deployment Sistem Sinkronisasi Terdistribusi

Panduan ini menjelaskan cara men-deploy dan menjalankan sistem menggunakan Docker dan Docker Compose.

## Prasyarat

* **Git:** Terinstal untuk mengkloning repository.
* **Docker:** Mesin Docker harus terinstal dan berjalan (misal: Docker Desktop). Versi [Sebutkan versi minimum jika tahu, misal: 20.10+].
* **Docker Compose:** Umumnya sudah termasuk dalam Docker Desktop. Versi [Sebutkan versi minimum jika tahu, misal: 1.29+].

## Langkah-langkah Deployment

1.  **Kloning Repository:**
    Buka terminal atau command prompt, navigasi ke direktori tempat Anda ingin menyimpan proyek, lalu kloning repository:
    ```bash
    git clone [https://github.com/ldclabs/anda](https://github.com/ldclabs/anda)
    ```

2.  **Masuk ke Direktori Proyek:**
    ```bash
    cd distributed-sync-system
    ```

3.  **(Opsional) Konfigurasi Lingkungan:**
    Proyek ini menggunakan file `.env` untuk beberapa konfigurasi. Salin file contoh:
    ```bash
    # (Opsional) Salin jika Anda perlu mengubah konfigurasi default
    # Di Windows PowerShell:
    copy .env.example .env
    # Di Linux/macOS/Git Bash:
    # cp .env.example .env
    ```
    Anda dapat mengedit file `.env` jika perlu mengubah port Redis atau parameter lainnya, meskipun pengaturan default seharusnya berfungsi.

4.  **Jalankan Sistem dengan Docker Compose:**
    Dari direktori root proyek (`distributed-sync-system`), jalankan perintah berikut:
    ```bash
    docker-compose -f docker/docker-compose.yml up --build
    ```
    * Flag `-f docker/docker-compose.yml` menunjuk ke file konfigurasi Docker Compose.
    * Flag `--build` akan membangun image Docker jika belum ada atau jika ada perubahan pada `Dockerfile` atau kode sumber. Proses ini mungkin memakan waktu beberapa menit saat pertama kali dijalankan karena perlu mengunduh base image dan menginstal dependensi.
    * Biarkan terminal ini tetap berjalan. Anda akan melihat log dari semua kontainer (3 node aplikasi dan 1 Redis). Tunggu hingga log menunjukkan pemilihan leader Raft selesai dan sistem stabil.

5.  **Akses Sistem:**
    Sistem sekarang berjalan dan siap menerima permintaan. API diekspos di port berikut di mesin lokal Anda:
    * Node 1: `http://localhost:5001`
    * Node 2: `http://localhost:5002`
    * Node 3: `http://localhost:5003`

    Gunakan `curl`, Postman, atau alat API lainnya untuk berinteraksi dengan endpoint API (lihat `api_spec.yaml` atau dokumentasi utama). Ingat, permintaan yang mengubah state Lock Manager (`/lock/acquire`, `/lock/release`) harus dikirim ke node yang sedang menjadi **Leader** Raft.

6.  **Hentikan Sistem:**
    Untuk menghentikan semua kontainer, kembali ke terminal tempat `docker-compose up` berjalan dan tekan `Ctrl + C`.

7.  **Bersihkan (Opsional):**
    Untuk menghapus kontainer, jaringan, dan volume (jika ada) yang dibuat oleh Docker Compose, jalankan:
    ```bash
    docker-compose -f docker/docker-compose.yml down
    ```

## Pemecahan Masalah (Troubleshooting)

Lihat bagian "Troubleshooting" di dokumen `architecture.md` atau laporan utama untuk solusi masalah umum yang mungkin terjadi selama deployment atau runtime.