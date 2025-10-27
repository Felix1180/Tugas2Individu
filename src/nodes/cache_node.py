# src/nodes/cache_node.py

import logging
import asyncio
import time
from collections import OrderedDict

from ..communication.message_passing import broadcast_rpc
from ..utils.metrics import record_latency, increment_counter


class CacheNode:
    """
    Mengimplementasikan cache node terdistribusi dengan protokol koherensi sederhana
    (invalidation) dan kebijakan penggantian LRU (Least Recently Used).
    """

    def __init__(self, node_id, peers, capacity=100):
        self.node_id = node_id
        self.peers = peers
        self.capacity = capacity

        # OrderedDict cocok untuk implementasi LRU karena mempertahankan urutan penggunaan.
        self.cache = OrderedDict()
        self.lock = asyncio.Lock()  # Melindungi akses ke cache (concurrency-safe)

        logging.info(f"[{self.node_id}] CacheNode initialized with capacity {self.capacity}")

    # --------------------------------------------------------------------------
    # 🧠 CACHE OPERATIONS
    # --------------------------------------------------------------------------

    async def get(self, key):
        """
        Mendapatkan nilai dari cache berdasarkan kunci.
        Menghitung latensi, menghitung hit/miss, dan memperbarui urutan LRU.
        """
        start_time = time.time()
        increment_counter("cache_get_requests")

        async with self.lock:
            if key not in self.cache:
                logging.info(f"[{self.node_id}] Cache MISS for key: {key}")
                increment_counter("cache_misses")
                record_latency("cache_get_miss_latency", start_time)
                return None

            # Pindahkan kunci ke akhir untuk menunjukkan penggunaan terbaru
            self.cache.move_to_end(key)
            logging.info(f"[{self.node_id}] Cache HIT for key: {key}")

            increment_counter("cache_hits")
            record_latency("cache_get_hit_latency", start_time)
            return self.cache[key]

    async def set(self, key, value):
        """
        Menetapkan nilai di cache.
        Jika penuh, item LRU akan dihapus.
        Setelah itu, broadcast invalidation ke semua peer.
        """
        start_time = time.time()
        increment_counter("cache_set_requests")

        async with self.lock:
            evicted = False

            # Jika cache penuh dan key baru → hapus yang paling lama
            if len(self.cache) >= self.capacity and key not in self.cache:
                oldest_key, _ = self.cache.popitem(last=False)
                logging.info(f"[{self.node_id}] Cache full. Evicted key: {oldest_key}")
                increment_counter("cache_evictions")
                evicted = True

            self.cache[key] = value
            self.cache.move_to_end(key)
            logging.info(f"[{self.node_id}] Set key '{key}' locally (evicted={evicted}).")

        # Siarkan pesan invalidasi ke semua peer lain
        logging.info(f"[{self.node_id}] Broadcasting invalidation for key: {key}")
        await broadcast_rpc(self.peers, 'cache/invalidate', {'key': key})

        record_latency("cache_set_latency", start_time)
        return {"success": True, "message": f"Key '{key}' set and invalidated across peers."}

    async def handle_invalidation(self, key):
        """
        Menangani permintaan invalidasi dari peer lain.
        Menghapus entri cache jika ada.
        """
        async with self.lock:
            if key in self.cache:
                del self.cache[key]
                logging.info(f"[{self.node_id}] Invalidated key '{key}' from local cache.")
                return {"success": True, "message": "Key invalidated"}

        return {"success": True, "message": "Key not in cache"}

    # --------------------------------------------------------------------------
    # 📊 STATUS & DIAGNOSTIC
    # --------------------------------------------------------------------------

    def get_status(self):
        """Mengembalikan status cache saat ini."""
        return {
            "node_id": self.node_id,
            "size": len(self.cache),
            "capacity": self.capacity,
            "keys": list(self.cache.keys())
        }
