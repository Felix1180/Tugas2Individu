# tests/unit/test_consistent_hash.py

import pytest
from src.utils.consistent_hash import ConsistentHashRing # Pastikan path impor benar

def test_ring_creation_and_basic_get():
    """Tes pembuatan ring dan mendapatkan node."""
    nodes = ["node-a", "node-b", "node-c"]
    ring = ConsistentHashRing(nodes=nodes, replicas=5) # Gunakan beberapa replika

    # Pastikan get_node mengembalikan salah satu node yang valid
    node_for_key1 = ring.get_node("my_data_key_1")
    assert node_for_key1 in nodes

    node_for_key2 = ring.get_node("another_key_99")
    assert node_for_key2 in nodes

def test_ring_determinism():
    """Tes apakah key yang sama selalu dipetakan ke node yang sama (jika ring tidak berubah)."""
    nodes = ["node-a", "node-b", "node-c"]
    ring = ConsistentHashRing(nodes=nodes, replicas=5)

    node1 = ring.get_node("important_topic")
    node2 = ring.get_node("important_topic")
    assert node1 == node2 # Harus selalu sama

def test_ring_add_node_impact():
    """Tes bagaimana penambahan node mempengaruhi pemetaan."""
    nodes = ["node-a", "node-b"]
    ring = ConsistentHashRing(nodes=nodes, replicas=50) # Lebih banyak replika = distribusi lebih baik

    # Catat pemetaan awal untuk beberapa key
    mappings_before = {f"key_{i}": ring.get_node(f"key_{i}") for i in range(100)}

    # Tambah node baru
    ring.add_node("node-c")

    # Catat pemetaan setelah penambahan
    mappings_after = {f"key_{i}": ring.get_node(f"key_{i}") for i in range(100)}

    # Hitung berapa banyak key yang berpindah node
    moved_keys = 0
    for i in range(100):
        key = f"key_{i}"
        if mappings_before[key] != mappings_after[key]:
            # Pastikan key hanya pindah ke node baru atau node lama lainnya
            assert mappings_after[key] in ["node-a", "node-b", "node-c"]
            # Pastikan key tidak pindah DARI node baru (karena node baru belum ada sebelumnya)
            assert mappings_before[key] != "node-c"
            moved_keys += 1

    # Dengan consistent hashing, jumlah key yang berpindah harusnya relatif kecil
    # Ekspektasi kasar: ~ total_keys / num_nodes_after
    print(f"\nKeys moved after adding node: {moved_keys} / 100")
    assert moved_keys < 60 # Harusnya jauh lebih sedikit dari 100, mungkin sekitar 33

def test_ring_remove_node_impact():
    """Tes bagaimana penghapusan node mempengaruhi pemetaan."""
    nodes = ["node-a", "node-b", "node-c"]
    ring = ConsistentHashRing(nodes=nodes, replicas=50)

    mappings_before = {f"key_{i}": ring.get_node(f"key_{i}") for i in range(100)}

    # Hapus node
    ring.remove_node("node-b")

    mappings_after = {f"key_{i}": ring.get_node(f"key_{i}") for i in range(100)}

    moved_keys = 0
    for i in range(100):
        key = f"key_{i}"
        # Pastikan tidak ada key yang dipetakan ke node yang dihapus
        assert mappings_after[key] != "node-b"
        assert mappings_after[key] in ["node-a", "node-c"]
        if mappings_before[key] == "node-b": # Key ini PASTI pindah
             moved_keys += 1
        elif mappings_before[key] != mappings_after[key]: # Key lain mungkin juga pindah
            pass # Pengecekan ini lebih kompleks

    print(f"\nKeys originally on node-b that moved: {moved_keys} / ~33")
    # Sulit diprediksi jumlah pastinya, tapi harus ada yg pindah jika node-b memegang key