# src/nodes/lock_manager.py

import asyncio # Gunakan asyncio.Lock
import logging
import threading
from collections import defaultdict
from datetime import datetime # Untuk audit log timestamp

# Setup logger khusus untuk audit
audit_logger = logging.getLogger('audit')
audit_logger.setLevel(logging.INFO)
# (Tambahkan handler file/lainnya di sini jika ingin log audit terpisah)

class LockManager:
    """State machine untuk mengelola locks dengan asyncio.Lock, deteksi deadlock, dan audit log."""
    def __init__(self):
        self._locks = {}  # resource_id -> {'type': 'shared'/'exclusive', 'owners': set()}
        self._wait_list = defaultdict(list) # resource_id -> [client_id_1, ...]
        self._lock_obj = asyncio.Lock() # Gunakan asyncio.Lock

    async def apply_command(self, command):
        """Terapkan command dari log Raft ke state machine (sekarang async)."""
        async with self._lock_obj: # Gunakan async with
            action = command['action']
            resource_id = command['resource_id']
            client_id = command['client_id']

            if action == 'acquire':
                lock_type = command.get('lock_type', 'exclusive') # Default ke exclusive jika tidak ada
                # Panggil versi internal sinkron
                return self._internal_handle_acquire(resource_id, lock_type, client_id)
            elif action == 'release':
                # Panggil versi internal sinkron
                return self._internal_handle_release(resource_id, client_id)

        return {"success": False, "message": "Unknown command"}

    # --- Fungsi Internal (dijalankan di dalam 'async with self._lock_obj') ---

    def _internal_handle_acquire(self, resource_id, lock_type, client_id):
        """Logika inti sinkron untuk acquire, termasuk audit log."""
        lock_info = self._locks.get(resource_id)

        # Kasus 1: Belum ada lock
        if lock_info is None:
            self._locks[resource_id] = {"type": lock_type, "owners": {client_id}}
            self._remove_client_from_all_wait_lists(client_id)
            logging.info(f"Lock GRANTED (new) for {client_id} on {resource_id} ({lock_type})")
            audit_logger.info(f"LOCK_ACQUIRED; client={client_id}; resource={resource_id}; type={lock_type}; result=GRANTED_NEW; timestamp={datetime.utcnow().isoformat()}Z")
            return {"success": True, "message": "Lock granted"}

        # Kasus 2: Lock sudah ada
        current_owners = lock_info['owners']
        current_lock_type = lock_info['type']

        # 2a. Re-entrant check
        if client_id in current_owners:
            if current_lock_type == 'exclusive' or lock_type == 'shared':
                 logging.info(f"Lock already held (re-entrant) by {client_id} on {resource_id}")
                 audit_logger.info(f"LOCK_ACQUIRED; client={client_id}; resource={resource_id}; type={lock_type}; result=GRANTED_REENTRANT; timestamp={datetime.utcnow().isoformat()}Z")
                 return {"success": True, "message": "Lock already held (re-entrant)"}
            # else: Holds shared, requests exclusive -> KONFLIK

        # 2b. Cek KONFLIK
        is_conflict = False
        if current_lock_type == 'exclusive':
            is_conflict = True
        elif lock_type == 'exclusive' and current_owners:
            is_conflict = True

        # 2c. TIDAK ADA KONFLIK (shared on shared)
        if not is_conflict:
             lock_info['owners'].add(client_id)
             self._remove_client_from_all_wait_lists(client_id)
             logging.info(f"Lock GRANTED (shared, joining) for {client_id} on {resource_id}")
             audit_logger.info(f"LOCK_ACQUIRED; client={client_id}; resource={resource_id}; type=shared; result=GRANTED_JOINED; timestamp={datetime.utcnow().isoformat()}Z")
             return {"success": True, "message": "Shared lock granted"}

        # --- Kasus 3: KONFLIK TERJADI ---
        logging.info(f"Lock conflict for {client_id} on {resource_id}. Checking deadlock.")

        # 3a. Cek jika sudah menunggu
        if client_id in self._wait_list.get(resource_id, []):
            logging.info(f"{client_id} is already waiting for {resource_id}")
            # Tidak perlu audit log di sini karena state tidak berubah
            return {"success": False, "message": "Resource locked, request already in wait list."}

        # 3b. Tambahkan ke wait list SEBELUM cek deadlock
        self._wait_list[resource_id].append(client_id)
        logging.debug(f"Temporarily added {client_id} to waitlist for {resource_id} for deadlock check")

        # 3c. Cek deadlock
        deadlock_detected = False
        try:
            # PENTING: Pastikan fungsi _detect_deadlock dipanggil dengan benar
            if self._detect_deadlock(client_id):
                deadlock_detected = True
        except Exception as e:
            logging.error(f"Error during deadlock detection: {e}", exc_info=True)
            deadlock_detected = True # Assume deadlock if check fails

        # 3d. Proses hasil
        if deadlock_detected:
            # Hapus dari wait list jika deadlock
            if client_id in self._wait_list.get(resource_id, []): # Perlu cek lagi karena bisa dihapus oleh thread lain (meski kecil kemungkinannya di sini)
                self._wait_list[resource_id].remove(client_id)
            logging.warning(f"DEADLOCK DETECTED involving {client_id}! Request aborted.")
            audit_logger.warning(f"LOCK_ACQUIRE_FAILED; client={client_id}; resource={resource_id}; type={lock_type}; result=REJECTED_DEADLOCK; timestamp={datetime.utcnow().isoformat()}Z")
            return {"success": False, "message": "Deadlock detected! Request aborted"}
        else:
            # Tidak ada deadlock, biarkan di wait list
            logging.info(f"{client_id} added permanently to wait list for {resource_id}")
            audit_logger.info(f"LOCK_ACQUIRE_WAITING; client={client_id}; resource={resource_id}; type={lock_type}; timestamp={datetime.utcnow().isoformat()}Z")
            return {"success": False, "message": "Resource locked, request added to wait list."}

    def _internal_handle_release(self, resource_id, client_id):
        """Logika inti sinkron untuk release, termasuk audit log."""
        lock_info = self._locks.get(resource_id)

        if lock_info and client_id in lock_info['owners']:
            lock_info['owners'].remove(client_id)
            result_detail = "RELEASED_PARTIAL"

            if not lock_info['owners']:
                del self._locks[resource_id]
                logging.info(f"Lock RELEASED and REMOVED for {client_id} on {resource_id}")
                result_detail = "RELEASED_FINAL"
                # Hapus waitlist untuk resource ini jika sudah bebas
                if resource_id in self._wait_list:
                     del self._wait_list[resource_id] # Hapus semua waiter untuk resource ini
            else:
                logging.info(f"Lock RELEASED for {client_id} on {resource_id}, still held by others")

            # Hapus klien dari SEMUA waitlist lain tempat ia mungkin menunggu (seharusnya tidak perlu jika _remove_client... dipanggil saat acquire)
            # self._remove_client_from_all_wait_lists(client_id) # Mungkin redundan?
            audit_logger.info(f"LOCK_RELEASED; client={client_id}; resource={resource_id}; result={result_detail}; timestamp={datetime.utcnow().isoformat()}Z")
            return {"success": True, "message": "Lock released"}
        else:
            audit_logger.warning(f"LOCK_RELEASE_FAILED; client={client_id}; resource={resource_id}; reason=NOT_OWNER; timestamp={datetime.utcnow().isoformat()}Z")
            return {"success": False, "message": "You do not hold this lock"}

    # --- Deadlock Detection (Versi Iteratif yang Disempurnakan) ---
    def _detect_deadlock(self, start_client):
        """Deteksi siklus pada Wait-For Graph (WFG) - Versi Iteratif Final."""
        
        # Build the current dependency graph: client -> set(clients they depend on/wait for lock held by)
        # Ini perlu dibangun SETIAP KALI agar akurat dengan state saat ini
        dependency_graph = defaultdict(set)
        for resource, waiters in self._wait_list.items():
            # Hanya proses resource yang saat ini terkunci
            if resource in self._locks:
                 owners = self._locks[resource].get('owners', set())
                 # Jika resource terkunci (ada owner), tambahkan dependensi
                 if owners:
                      for waiter in waiters:
                           dependency_graph[waiter].update(owners)

        # Iterative DFS using explicit stack and visited set for current path tracking
        # `visiting` melacak node di path DFS saat ini untuk deteksi siklus
        # `visited_nodes` melacak semua node yang pernah dikunjungi untuk efisiensi
        
        visiting = set()
        visited_nodes = set()
        stack = [start_client] # Mulai DFS dari klien yang meminta

        while stack:
            client = stack[-1] # Lihat node teratas (peek)

            if client not in visited_nodes:
                visited_nodes.add(client)
                visiting.add(client)
            
            # Cari tetangga (node yang ditunggu oleh 'client') yang belum dikunjungi
            pushed_neighbor = False
            if client in dependency_graph:
                for neighbor in dependency_graph[client]:
                    if neighbor in visiting: # Jika tetangga ada di path saat ini -> SIKLUS!
                        logging.debug(f"Cycle detected: {neighbor} revisited in path {visiting}")
                        return True
                    if neighbor not in visited_nodes:
                        stack.append(neighbor)
                        pushed_neighbor = True
                        break # Telusuri lebih dalam

            # Jika tidak ada tetangga baru atau semua tetangga sudah dikunjungi (dari path ini)
            if not pushed_neighbor:
                last_node = stack.pop() # Backtrack
                visiting.remove(last_node) # Hapus dari path saat ini

        return False # Tidak ada siklus ditemukan

    # --- Helpers ---
    def _remove_client_from_all_wait_lists(self, client_id):
        """Hapus klien dari SEMUA daftar tunggu."""
        # Iterasi melalui salinan keys karena kita mungkin memodifikasi dict
        for res_id in list(self._wait_list.keys()):
            if client_id in self._wait_list[res_id]:
                self._wait_list[res_id].remove(client_id)
                # Hapus entri resource dari wait_list jika list-nya menjadi kosong
                if not self._wait_list[res_id]:
                    del self._wait_list[res_id]

    # --- Get Status (Sinkron untuk kompatibilitas Flask) ---
    def get_locks_status(self):
        # Gunakan lock internal sementara (threading lock) HANYA untuk operasi baca ini
        # Ini adalah kompromi karena endpoint /status sinkron
        temp_lock = threading.Lock() # Lock sementara, hanya untuk fungsi ini
        with temp_lock: # Menggunakan lock ini untuk memastikan pembacaan atomik
             # Akses langsung di sini aman karena kita tahu apply_command pakai asyncio.Lock
             locks_copy = {
                 res: {"type": info["type"], "owners": list(info["owners"])}
                 for res, info in self._locks.items()
             }
             wait_copy = {r: list(c) for r, c in self._wait_list.items() if c}
             return {"active_locks": locks_copy, "wait_list": wait_copy}