# src/communication/message_passing.py

import aiohttp
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def send_rpc(peer_url, endpoint, data):
    """Mengirim pesan RPC ke node lain dan mengembalikan respons."""
    url = f"{peer_url}/{endpoint}"
    timeout = aiohttp.ClientTimeout(total=1.0) # Timeout 1 detik
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.post(url, json=data) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    # Jangan cetak error jika hanya timeout, itu normal
                    if response.status != 504:
                         logging.warning(f"Failed to send RPC to {url}: Status {response.status}")
                    return None
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError):
            # Ini adalah kegagalan jaringan yang diharapkan, tidak perlu log error
            return None
        except Exception as e:
            logging.error(f"An unexpected error occurred during RPC to {url}: {e}")
            return None


async def broadcast_rpc(peers, endpoint, data):
    """Menyiarkan pesan RPC ke semua peer secara paralel."""
    tasks = []
    for peer_url in peers.values():
        task = asyncio.create_task(send_rpc(peer_url, endpoint, data))
        tasks.append(task)
    
    responses = await asyncio.gather(*tasks)
    return responses