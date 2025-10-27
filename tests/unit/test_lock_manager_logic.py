# tests/unit/test_lock_manager_logic.py

import pytest
import asyncio # Jika menggunakan asyncio.Lock
from src.nodes.lock_manager import LockManager # Sesuaikan path

# Gunakan pytest-asyncio jika fungsi tes perlu async
# pip install pytest-asyncio
pytestmark = pytest.mark.asyncio


async def test_lock_acquire_new():
    """Tes acquire lock pada resource baru."""
    manager = LockManager()
    command = {"action": "acquire", "resource_id": "res1", "lock_type": "exclusive", "client_id": "c1"}
    result = await manager.apply_command(command)
    assert result == {"success": True, "message": "Lock granted"}

    status = manager.get_locks_status()
    assert "res1" in status["active_locks"]
    assert status["active_locks"]["res1"]["owners"] == ["c1"]
    assert status["active_locks"]["res1"]["type"] == "exclusive"

async def test_lock_acquire_conflict_exclusive():
    """Tes konflik saat acquire exclusive lock yang sudah dipegang."""
    manager = LockManager()
    # c1 kunci res1
    await manager.apply_command({"action": "acquire", "resource_id": "res1", "lock_type": "exclusive", "client_id": "c1"})

    # c2 coba kunci res1
    command_c2 = {"action": "acquire", "resource_id": "res1", "lock_type": "exclusive", "client_id": "c2"}
    result_c2 = await manager.apply_command(command_c2)

    # Harusnya gagal dan masuk wait list
    assert result_c2["success"] is False
    assert "wait list" in result_c2["message"]

    status = manager.get_locks_status()
    assert status["active_locks"]["res1"]["owners"] == ["c1"] # Masih dipegang c1
    assert "res1" in status["wait_list"]
    assert status["wait_list"]["res1"] == ["c2"] # c2 menunggu

async def test_lock_release():
    """Tes release lock."""
    manager = LockManager()
    # c1 kunci res1
    await manager.apply_command({"action": "acquire", "resource_id": "res1", "lock_type": "exclusive", "client_id": "c1"})
    # c2 menunggu res1
    await manager.apply_command({"action": "acquire", "resource_id": "res1", "lock_type": "exclusive", "client_id": "c2"})

    # c1 lepas res1
    command_release = {"action": "release", "resource_id": "res1", "client_id": "c1"}
    result_release = await manager.apply_command(command_release)
    assert result_release == {"success": True, "message": "Lock released"}

    status = manager.get_locks_status()
    assert "res1" not in status["active_locks"] # Lock sudah bebas
    # Penting: Implementasi saat ini tidak otomatis memberi lock ke waiter.
    # Wait list untuk res1 harusnya juga hilang KETIKA lock dihapus.
    assert "res1" not in status["wait_list"] # Verifikasi ini sesuai kode terakhir Anda

async def test_deadlock_detection_scenario_unit(caplog):
     """Tes skenario deadlock secara unit (jika logika bisa dipanggil langsung)."""
     manager = LockManager()
     # NOTE: Pengujian ini akan menguji _internal_handle_acquire/_detect_deadlock
     # Ini membutuhkan penyesuaian tergantung versi LockManager Anda (sync/async internal)
     # Versi terakhir menggunakan internal sync methods:

     # 1. A kunci X
     res_ax = manager._internal_handle_acquire("X", "exclusive", "A")
     assert res_ax["success"] is True

     # 2. B kunci Y
     res_by = manager._internal_handle_acquire("Y", "exclusive", "B")
     assert res_by["success"] is True

     # 3. A coba kunci Y (dipegang B) -> Harus masuk wait list
     res_ay = manager._internal_handle_acquire("Y", "exclusive", "A")
     assert res_ay["success"] is False
     assert "wait list" in res_ay["message"]
     status1 = manager.get_locks_status()
     assert status1["wait_list"].get("Y") == ["A"]

     # 4. B coba kunci X (dipegang A, yang menunggu Y yg dipegang B -> DEADLOCK)
     res_bx = manager._internal_handle_acquire("X", "exclusive", "B")
     
     # HASIL YANG DIHARAPKAN
     assert res_bx["success"] is False
     assert "Deadlock detected" in res_bx["message"]

     # Verifikasi bahwa B TIDAK ditambahkan ke wait list X
     status2 = manager.get_locks_status()
     assert "B" not in status2["wait_list"].get("X", [])
     # Pastikan A masih menunggu Y (karena deadlock tidak resolve otomatis)
     assert status2["wait_list"].get("Y") == ["A"]

     # (Cleanup manual jika perlu untuk tes berikutnya)
     manager._internal_handle_release("X", "A")
     manager._internal_handle_release("Y", "B")