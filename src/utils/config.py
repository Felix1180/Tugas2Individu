import os
from dotenv import load_dotenv

load_dotenv()

# Konfigurasi umum
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# Konfigurasi Node (dapat diperluas untuk banyak node)
NODE_ID = os.getenv("NODE_ID", "node1")
NODE_HOST = os.getenv("NODE_HOST", "0.0.0.0")
FLASK_PORT = int(os.getenv("FLASK_PORT", 5001))

# Daftar semua node dalam sistem (penting untuk Raft)
# Dalam produksi, ini biasanya ditemukan melalui service discovery.
# Format: "node_id:http://hostname:port"
PEERS = {
    "node1": "http://node1:5001",
    "node2": "http://node2:5002",
    "node3": "http://node3:5003",
}

# Hapus node saat ini dari daftar peer
if NODE_ID in PEERS:
    del PEERS[NODE_ID]

# Pengaturan Raft
ELECTION_TIMEOUT_MIN = 1.5  # Detik
ELECTION_TIMEOUT_MAX = 3.0   # Detik
HEARTBEAT_INTERVAL = 0.5   # Detik