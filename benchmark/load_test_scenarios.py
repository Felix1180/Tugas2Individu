# benchmarks/load_test_scenarios.py

import random
import time
from locust import HttpUser, task, between

class DistributedSystemUser(HttpUser):
    # Tunggu antara 1 hingga 3 detik antara setiap tugas
    wait_time = between(1, 3)
    
    # Ganti host ini dengan alamat load balancer atau salah satu node Anda
    # Anda bisa mengaturnya saat menjalankan locust dari command line
    # contoh: locust --host http://localhost:5001
    
    def on_start(self):
        """Dipanggil ketika pengguna virtual memulai."""
        # Setiap pengguna virtual mendapatkan ID unik
        self.client_id = f"locust_user_{random.randint(1000, 9999)}"
        self.resource_id = f"resource_{random.randint(1, 10)}" # Simulasi beberapa resource
        print(f"Starting new user: {self.client_id}")

    @task
    def acquire_and_release_lock(self):
        """
        Skenario paling umum: klien meminta lock, melakukan 'pekerjaan', lalu melepaskan lock.
        """
        # 1. Acquire Lock
        acquire_payload = {
            "resource_id": self.resource_id,
            "lock_type": "exclusive",
            "client_id": self.client_id
        }
        with self.client.post("/lock/acquire", json=acquire_payload, name="/lock/acquire") as response:
            if not response.json().get("success"):
                response.failure(f"Failed to acquire lock for {self.resource_id}")
                return # Hentikan tugas jika gagal mendapatkan lock

        # 2. Simulate "work" (misalnya, operasi database)
        time.sleep(random.uniform(0.2, 0.8))

        # 3. Release Lock
        release_payload = {
            "resource_id": self.resource_id,
            "client_id": self.client_id
        }
        self.client.post("/lock/release", json=release_payload, name="/lock/release")

    @task(2) # Beri bobot lebih tinggi, jalankan 2x lebih sering
    def check_system_status(self):
        """Simulasi permintaan read-only untuk memeriksa status."""
        self.client.get("/status", name="/status")