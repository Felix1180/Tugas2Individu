import asyncio
from flask import Flask, jsonify, request
from threading import Thread
import logging
from asgiref.wsgi import WsgiToAsgi

# Perbaiki impor config agar lebih eksplisit
from ..utils.config import NODE_ID, PEERS, FLASK_PORT, REDIS_HOST, REDIS_PORT 
from ..consensus.raft import RaftNode
from ..nodes.lock_manager import LockManager
from ..utils.metrics import get_metrics
from ..nodes.cache_node import CacheNode
# Hapus import broadcast_rpc yang tidak digunakan langsung di sini
# from ..communication.message_passing import broadcast_rpc 
import redis.asyncio as aioredis
from ..utils.consistent_hash import ConsistentHashRing
from ..nodes.queue_node import QueueNode

# --- Inisialisasi Aplikasi ---
flask_app = Flask(__name__)
# Pastikan NODE_ID tersedia saat konfigurasi logging
logging.basicConfig(level=logging.INFO, format=f'{NODE_ID} - %(asctime)s - %(levelname)s - %(message)s')

# --- Inisialisasi Komponen Sistem Terdistribusi ---
lock_manager = LockManager()
raft_node = RaftNode(node_id=NODE_ID, peers=PEERS, lock_manager=lock_manager)
cache_node = CacheNode(node_id=NODE_ID, peers=PEERS)

redis_client = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=False)
hash_ring = ConsistentHashRing(nodes=list(PEERS.keys()) + [NODE_ID])
queue_node = QueueNode(NODE_ID, PEERS, hash_ring, redis_client)

def run_raft_loop():
    """Wrapper function to run the Raft event loop in a new thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(raft_node.run())
    loop.close()

# --- Mulai Background Tasks ---
raft_thread = Thread(target=run_raft_loop, daemon=True)
raft_thread.start()
logging.info(f"[{NODE_ID}] Raft background thread started.")

# --- API Endpoints ---

# --- Queue API Endpoints ---
@flask_app.route('/queue/push', methods=['POST'])
async def queue_push():
    """Endpoint eksternal untuk mendorong pesan."""
    # PERBAIKAN: Hapus await
    data = request.get_json() 
    topic = data.get('topic')
    message = data.get('message')
    if not all([topic, message]):
        return jsonify({"success": False, "message": "Missing topic or message"}), 400
    
    # Tetap gunakan await di sini karena push_message adalah async
    result = await queue_node.push_message(topic, message) 
    return jsonify(result)

@flask_app.route('/queue/pop/<topic>/<consumer_id>', methods=['GET']) # Tambahkan consumer_id ke path
async def queue_pop(topic, consumer_id):
    """Endpoint eksternal untuk mengambil pesan."""
    if not consumer_id:
        return jsonify({"success": False, "message": "Missing consumer_id"}), 400
    result = await queue_node.pop_message(topic, consumer_id)
    return jsonify(result)

@flask_app.route('/queue/ack/<topic>', methods=['POST'])
async def queue_ack(topic):
    """Endpoint eksternal untuk acknowledge pesan."""
    data = request.get_json() # Hapus await
    consumer_id = data.get('consumer_id')
    message_id = data.get('message_id')
    if not all([consumer_id, message_id]):
        return jsonify({"success": False, "message": "Missing consumer_id or message_id"}), 400

    result = await queue_node.acknowledge_message(topic, consumer_id, message_id)
    return jsonify(result)

@flask_app.route('/queue/internal/pop/<topic>/<consumer_id>', methods=['POST'])
async def queue_internal_pop(topic, consumer_id):
     """Endpoint internal untuk menerima pop yang di-forward."""
     # Tidak perlu data dari request body
     result = await queue_node.internal_pop(topic, consumer_id)
     return jsonify(result)

@flask_app.route('/queue/internal/ack/<topic>', methods=['POST'])
async def queue_internal_ack(topic):
     """Endpoint internal untuk menerima ack yang di-forward."""
     data = request.get_json() # Hapus await
     consumer_id = data.get('consumer_id')
     message_id = data.get('message_id')
     result = await queue_node.internal_ack(topic, consumer_id, message_id)
     return jsonify(result)

@flask_app.route('/queue/internal/push', methods=['POST'])
async def queue_internal_push():
    """Endpoint internal untuk menerima pesan yang di-forward."""
    # PERBAIKAN: Hapus await
    data = request.get_json() 
    topic = data.get('topic')
    message = data.get('message')
    # Tetap gunakan await di sini karena internal_push adalah async
    result = await queue_node.internal_push(topic, message) 
    return jsonify(result)

# --- Cache API Endpoints (External) ---
@flask_app.route('/cache/<key>', methods=['GET'])
async def get_cache(key):
    """Mendapatkan nilai dari cache."""
    # Tetap gunakan await di sini karena get adalah async
    value = await cache_node.get(key) 
    if value is not None:
        return jsonify({"success": True, "key": key, "value": value})
    else:
        return jsonify({"success": False, "message": "Cache miss"}), 404

@flask_app.route('/cache/set', methods=['POST'])
async def set_cache():
    """Menetapkan nilai baru di cache dan menginvalidasi cache lain."""
    # SUDAH BENAR: await dihapus
    data = request.get_json() 
    key = data.get('key')
    value = data.get('value')
    if not all([key, value]):
        return jsonify({"success": False, "message": "Missing key or value"}), 400
    
    # Tetap gunakan await di sini karena set adalah async
    result = await cache_node.set(key, value) 
    return jsonify(result)

# --- Cache API Endpoints (Internal) ---
@flask_app.route('/cache/invalidate', methods=['POST'])
async def invalidate_cache():
    """Endpoint internal untuk menerima sinyal invalidasi dari peer."""
    # PERBAIKAN: Hapus await
    data = request.get_json() 
    key = data.get('key')
    if not key:
        return jsonify({"success": False, "message": "Missing key"}), 400
    
    # Tetap gunakan await di sini karena handle_invalidation adalah async
    result = await cache_node.handle_invalidation(key) 
    return jsonify(result)

# --- Lock API Endpoints (External - Client) ---
@flask_app.route('/lock/acquire', methods=['POST'])
async def acquire_lock():
    # PERBAIKAN: Hapus await
    data = request.get_json() 
    resource_id = data.get('resource_id')
    lock_type = data.get('lock_type', 'exclusive')
    client_id = data.get('client_id')

    if not all([resource_id, lock_type, client_id]):
        return jsonify({"success": False, "message": "Missing parameters"}), 400

    command = {
        "action": "acquire",
        "resource_id": resource_id,
        "lock_type": lock_type,
        "client_id": client_id
    }
    
    # Tetap gunakan await di sini karena handle_client_request adalah async
    result = await raft_node.handle_client_request(command) 
    return jsonify(result)

@flask_app.route('/lock/release', methods=['POST'])
async def release_lock():
    # PERBAIKAN: Hapus await
    data = request.get_json() 
    resource_id = data.get('resource_id')
    client_id = data.get('client_id')
    
    if not all([resource_id, client_id]):
        return jsonify({"success": False, "message": "Missing parameters"}), 400

    command = {
        "action": "release",
        "resource_id": resource_id,
        "client_id": client_id
    }
    
    # Tetap gunakan await di sini karena handle_client_request adalah async
    result = await raft_node.handle_client_request(command) 
    return jsonify(result)

# --- Raft API Endpoints (Internal - Peers) ---
@flask_app.route('/request_vote', methods=['POST'])
async def rpc_request_vote():
    # PERBAIKAN: Hapus await
    data = request.get_json() 
    # Tetap gunakan await di sini karena handle_request_vote adalah async
    response = await raft_node.handle_request_vote( 
        term=data['term'],
        candidate_id=data['candidate_id'],
        last_log_index=data['last_log_index'],
        last_log_term=data['last_log_term']
    )
    return jsonify(response)

@flask_app.route('/append_entries', methods=['POST'])
async def rpc_append_entries():
    # PERBAIKAN: Hapus await
    data = request.get_json() 
    # Tetap gunakan await di sini karena handle_append_entries adalah async
    response = await raft_node.handle_append_entries( 
        term=data['term'],
        leader_id=data['leader_id'],
        prev_log_index=data.get('prev_log_index', -1),
        prev_log_term=data.get('prev_log_term', 0),
        entries=data['entries'],
        leader_commit=data['leader_commit']
    )
    return jsonify(response)

# --- Status & Metrics Endpoints (Sinkron) ---
@flask_app.route('/status', methods=['GET'])
def get_status(): # Fungsi ini sinkron (def, bukan async def)
    status = {
        "node_id": raft_node.node_id,
        "state": raft_node.state.name,
        "term": raft_node.current_term,
        "leader": raft_node.leader_id,
        "log_length": len(raft_node.log),
        "commit_index": raft_node.commit_index,
        "locks": lock_manager.get_locks_status() # get_locks_status adalah sinkron
    }
    return jsonify(status)

@flask_app.route('/metrics', methods=['GET'])
def metrics(): # Fungsi ini sinkron
    # get_metrics() juga sinkron
    return jsonify(get_metrics()) 

# --- Menjalankan Raft di background thread ---
def run_raft_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(raft_node.run())
    loop.close()
    
# Bungkus aplikasi Flask HANYA SETELAH semua route didefinisikan.
app = WsgiToAsgi(flask_app)