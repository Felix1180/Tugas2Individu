# src/communication/failure_detector.py

import asyncio
import time
import logging
from .message_passing import send_rpc

class FailureDetector:
    """
    Implementasi failure detector berbasis heartbeat (pull model).
    Setiap node secara aktif memeriksa kesehatan peer-nya.
    """
    def __init__(self, node_id, peers, check_interval=2.0, failure_timeout=5.0):
        self.node_id = node_id
        self.peers = peers
        self.check_interval = check_interval
        self.failure_timeout = failure_timeout
        # Lacak status setiap peer: 'UP' atau 'DOWN'
        self.peer_status = {peer_id: 'UP' for peer_id in self.peers.keys()}
        # Lacak kapan terakhir kali peer merespons
        self.last_ack_time = {peer_id: time.time() for peer_id in self.peers.keys()}
        self.is_running = False

    async def monitor_peers(self):
        """Tugas background yang berjalan terus-menerus untuk memantau peer."""
        logging.info(f"[{self.node_id}] Failure Detector started.")
        self.is_running = True
        while self.is_running:
            # Periksa setiap peer secara paralel
            tasks = [self._check_peer(peer_id, peer_url) for peer_id, peer_url in self.peers.items()]
            await asyncio.gather(*tasks)
            
            # Perbarui status berdasarkan waktu ack terakhir
            current_time = time.time()
            for peer_id in self.peers.keys():
                if current_time - self.last_ack_time[peer_id] > self.failure_timeout:
                    if self.peer_status[peer_id] == 'UP':
                        self.peer_status[peer_id] = 'DOWN'
                        logging.warning(f"[{self.node_id}] Peer {peer_id} detected as DOWN.")
                else:
                    if self.peer_status[peer_id] == 'DOWN':
                        self.peer_status[peer_id] = 'UP'
                        logging.info(f"[{self.node_id}] Peer {peer_id} is back UP.")

            await asyncio.sleep(self.check_interval)

    async def _check_peer(self, peer_id, peer_url):
        """Mengirim ping/health check ke satu peer."""
        response = await send_rpc(peer_url, 'health', {'from': self.node_id})
        if response and response.get('status') == 'ok':
            # Jika berhasil, perbarui waktu ack
            self.last_ack_time[peer_id] = time.time()

    def get_alive_peers(self):
        """Mengembalikan daftar peer_id yang saat ini dianggap UP."""
        return [peer_id for peer_id, status in self.peer_status.items() if status == 'UP']
    
    def stop(self):
        self.is_running = False