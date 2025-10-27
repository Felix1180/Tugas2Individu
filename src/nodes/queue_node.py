# src/nodes/queue_node.py

import logging
import asyncio
import time
import redis.asyncio as aioredis
from ..communication.message_passing import send_rpc

# Konstanta Timeout (dalam detik)
PROCESSING_TIMEOUT = 30  # Anggap gagal jika pesan diproses > 30 detik


class QueueNode:
    """
    Mengelola logika Distributed Queue.
    Bertanggung jawab untuk merutekan, menyimpan, dan mengambil pesan.
    """

    def __init__(self, node_id, peers, hash_ring, redis_client):
        self.node_id = node_id
        self.peers = peers
        self.hash_ring = hash_ring
        self.redis = redis_client
        self._monitor_task = None

        logging.info(f"[{self.node_id}] QueueNode initialized.")
        self.start_processing_monitor()

    # --------------------------------------------------------------------------
    # PUSH MESSAGE
    # --------------------------------------------------------------------------
    async def push_message(self, topic, message):
        """Mendorong pesan ke topik dan merutekannya ke node yang bertanggung jawab."""
        target_node_id = self.hash_ring.get_node(topic)

        if target_node_id == self.node_id:
            try:
                list_key = f"queue:{topic}"
                await self.redis.rpush(list_key, message)
                logging.info(f"[{self.node_id}] Pushed message to local queue: {topic}")
                return {"success": True, "message": "Message queued locally"}
            except Exception as e:
                logging.error(f"[{self.node_id}] Redis push error: {e}")
                return {"success": False, "message": str(e)}

        # Forward ke node lain
        peer_url = self.peers.get(target_node_id)
        if not peer_url:
            return {"success": False, "message": f"Peer {target_node_id} not found"}

        logging.info(f"[{self.node_id}] Forwarding message for topic {topic} to {target_node_id}")
        payload = {"topic": topic, "message": message}
        return await send_rpc(peer_url, "queue/internal/push", payload)

    # --------------------------------------------------------------------------
    # POP MESSAGE
    # --------------------------------------------------------------------------
    async def pop_message(self, topic, consumer_id):
        """Mengambil pesan dan memindahkannya ke list processing."""
        target_node_id = self.hash_ring.get_node(topic)

        if target_node_id != self.node_id:
            peer_url = self.peers.get(target_node_id)
            if not peer_url:
                return {"success": False, "message": f"Peer {target_node_id} not found"}

            logging.info(f"[{self.node_id}] Forwarding pop request for {topic} to {target_node_id}")
            return await send_rpc(peer_url, f"queue/internal/pop/{topic}/{consumer_id}", {})

        # Node ini bertanggung jawab
        main_queue_key = f"queue:{topic}"
        processing_list_key = f"processing:{topic}:{consumer_id}"

        try:
            message_bytes = await self.redis.lmove(main_queue_key, processing_list_key, "LEFT", "RIGHT")

            if not message_bytes:
                return {"success": False, "message": "Queue empty"}

            message_content = message_bytes.decode("utf-8")
            timestamp = time.time()

            await self.redis.hset(f"timestamps:{topic}:{consumer_id}", message_content, timestamp)
            logging.info(f"[{self.node_id}] Moved message from {topic} to processing for {consumer_id}")

            return {
                "success": True,
                "message_id": message_content,
                "message": message_content,
            }

        except Exception as e:
            logging.error(f"[{self.node_id}] Redis LMOVE error: {e}")
            return {"success": False, "message": str(e)}

    # --------------------------------------------------------------------------
    # ACKNOWLEDGE MESSAGE
    # --------------------------------------------------------------------------
    async def acknowledge_message(self, topic, consumer_id, message_id):
        """Menghapus pesan dari list processing setelah di-ACK."""
        target_node_id = self.hash_ring.get_node(topic)

        if target_node_id != self.node_id:
            peer_url = self.peers.get(target_node_id)
            if not peer_url:
                return {"success": False, "message": "Peer not found"}

            payload = {"consumer_id": consumer_id, "message_id": message_id}
            return await send_rpc(peer_url, f"queue/internal/ack/{topic}", payload)

        processing_list_key = f"processing:{topic}:{consumer_id}"
        timestamp_hash_key = f"timestamps:{topic}:{consumer_id}"

        try:
            removed_count = await self.redis.lrem(processing_list_key, 1, message_id.encode("utf-8"))
            await self.redis.hdel(timestamp_hash_key, message_id)

            if removed_count > 0:
                logging.info(
                    f"[{self.node_id}] ACK removed message {message_id} for {consumer_id} on {topic}"
                )
                return {"success": True, "message": "Message acknowledged"}
            else:
                logging.warning(
                    f"[{self.node_id}] ACK received but message {message_id} not found in processing list."
                )
                return {"success": False, "message": "Message not found or already acknowledged"}

        except Exception as e:
            logging.error(f"[{self.node_id}] Redis LREM/HDEL error: {e}")
            return {"success": False, "message": str(e)}

    # --------------------------------------------------------------------------
    # MONITOR PROCESSING TIMEOUT
    # --------------------------------------------------------------------------
    def start_processing_monitor(self):
        """Memulai task asyncio untuk memantau pesan timeout."""
        if self._monitor_task is None or self._monitor_task.done():
            logging.info(f"[{self.node_id}] Starting queue processing monitor...")
            self._monitor_task = asyncio.create_task(self._monitor_timeouts())
        else:
            logging.warning(f"[{self.node_id}] Monitor task already running.")

    async def _monitor_timeouts(self):
        """Secara periodik memeriksa pesan yang timeout di list processing."""
        while True:
            try:
                processing_keys = await self.redis.keys("processing:*")
                current_time = time.time()

                for key_bytes in processing_keys:
                    key = key_bytes.decode("utf-8")
                    parts = key.split(":")

                    if len(parts) != 3:
                        continue

                    _, topic, consumer_id = parts
                    if self.hash_ring.get_node(topic) != self.node_id:
                        continue

                    timestamp_hash_key = f"timestamps:{topic}:{consumer_id}"
                    messages_in_processing = await self.redis.lrange(key, 0, -1)
                    timestamps = await self.redis.hgetall(timestamp_hash_key)

                    for msg_bytes in messages_in_processing:
                        msg = msg_bytes.decode("utf-8")
                        ts_bytes = timestamps.get(msg_bytes)
                        if not ts_bytes:
                            continue

                        ts = float(ts_bytes.decode("utf-8"))
                        if current_time - ts > PROCESSING_TIMEOUT:
                            logging.warning(
                                f"[{self.node_id}] Message '{msg}' timed out for consumer {consumer_id} on {topic}. Re-queuing..."
                            )

                            main_queue_key = f"queue:{topic}"
                            moved = await self.redis.lmove(key, main_queue_key, "LEFT", "RIGHT", msg_bytes)
                            if moved:
                                await self.redis.hdel(timestamp_hash_key, msg)
                            else:
                                await self.redis.lrem(key, 1, msg_bytes)
                                await self.redis.hdel(timestamp_hash_key, msg)

            except Exception as e:
                logging.error(f"[{self.node_id}] Error in processing monitor: {e}", exc_info=True)

            await asyncio.sleep(10)

    # --------------------------------------------------------------------------
    # INTERNAL ENDPOINTS (untuk RPC forwarding)
    # --------------------------------------------------------------------------
    async def internal_push(self, topic, message):
        """Endpoint internal untuk menerima pesan yang diteruskan."""
        try:
            list_key = f"queue:{topic}"
            await self.redis.rpush(list_key, message)
            logging.info(f"[{self.node_id}] Accepted forwarded message for queue: {topic}")
            return {"success": True, "message": "Message queued locally from forward"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    async def internal_pop(self, topic, consumer_id):
        """Endpoint internal untuk pop message yang diteruskan."""
        main_queue_key = f"queue:{topic}"
        processing_list_key = f"processing:{topic}:{consumer_id}"

        try:
            message_bytes = await self.redis.lmove(main_queue_key, processing_list_key, "LEFT", "RIGHT")
            if not message_bytes:
                return {"success": False, "message": "Queue empty"}

            message_content = message_bytes.decode("utf-8")
            timestamp = time.time()
            await self.redis.hset(f"timestamps:{topic}:{consumer_id}", message_content, timestamp)

            logging.info(f"[{self.node_id}] Accepted forwarded pop for {topic} by {consumer_id}")
            return {"success": True, "message_id": message_content, "message": message_content}
        except Exception as e:
            logging.error(f"[{self.node_id}] Internal Redis LMOVE error: {e}")
            return {"success": False, "message": str(e)}

    async def internal_ack(self, topic, consumer_id, message_id):
        """Endpoint internal untuk ACK message yang diteruskan."""
        processing_list_key = f"processing:{topic}:{consumer_id}"
        timestamp_hash_key = f"timestamps:{topic}:{consumer_id}"

        try:
            removed_count = await self.redis.lrem(processing_list_key, 1, message_id.encode("utf-8"))
            await self.redis.hdel(timestamp_hash_key, message_id)

            if removed_count > 0:
                logging.info(
                    f"[{self.node_id}] Accepted forwarded ACK for {message_id} by {consumer_id} on {topic}"
                )
                return {"success": True, "message": "Message acknowledged"}

            return {"success": False, "message": "Message not found or already acknowledged"}
        except Exception as e:
            logging.error(f"[{self.node_id}] Internal Redis LREM/HDEL error: {e}")
            return {"success": False, "message": str(e)}
