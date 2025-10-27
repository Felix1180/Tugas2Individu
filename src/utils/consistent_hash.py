# src/utils/consistent_hash.py

import mmh3  # Pastikan Anda sudah 'pip install mmh3'
import bisect

class ConsistentHashRing:
    """Implementasi Consistent Hashing Ring sederhana."""
    def __init__(self, nodes=None, replicas=3):
        self.replicas = replicas
        self.ring = dict()
        self._sorted_keys = []
        if nodes:
            for node in nodes:
                self.add_node(node)

    def add_node(self, node_id):
        """Menambahkan node ke ring."""
        for i in range(self.replicas):
            # Buat 'virtual node' untuk distribusi yang lebih baik
            key = self._hash(f"{node_id}:{i}")
            self.ring[key] = node_id
            bisect.insort(self._sorted_keys, key)

    def remove_node(self, node_id):
        """Menghapus node dari ring."""
        for i in range(self.replicas):
            key = self._hash(f"{node_id}:{i}")
            if key in self.ring:
                del self.ring[key]
                # Menghapus dari list yang terurut itu mahal,
                # jadi kita bangun ulang saja
        self._sorted_keys = sorted(self.ring.keys())

    def get_node(self, key):
        """Mendapatkan node yang bertanggung jawab atas kunci (key) tertentu."""
        if not self.ring:
            return None
        
        hash_key = self._hash(key)
        # Cari posisi insertion point di list yang terurut
        index = bisect.bisect(self._sorted_keys, hash_key)
        
        # Jika index di akhir, putar kembali ke awal (ring)
        if index == len(self._sorted_keys):
            index = 0
            
        return self.ring[self._sorted_keys[index]]

    def _hash(self, key):
        """Fungsi hash internal."""
        # Menggunakan mmh3 untuk hash 32-bit yang cepat dan terdistribusi baik
        return mmh3.hash(key, signed=False)