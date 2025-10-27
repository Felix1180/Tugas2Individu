# tests/integration/test_lock_manager_raft.py

import pytest
import requests # Perlu: pip install requests
import time

# Asumsi node berjalan di port 5001, 5002, 5003
NODE_URLS = ["http://localhost:5001", "http://localhost:5002", "http://localhost:5003"]
REQUEST_TIMEOUT = 5 # Timeout per request (detik)
STABILIZE_WAIT = 2.5 # Waktu tunggu replikasi/stabilisasi (detik)

def get_node_statuses():
    """Mendapatkan status dari semua node yang bisa dihubungi."""
    statuses = {}
    for url in NODE_URLS:
        try:
            response = requests.get(f"{url}/status", timeout=1)
            response.raise_for_status() # Error jika status bukan 2xx
            statuses[url] = response.json()
        except requests.RequestException as e:
            print(f"Warning: Could not reach {url}: {e}")
            statuses[url] = None # Tandai node tidak bisa dihubungi
    return statuses

def get_leader_url(statuses=None):
    """Mencari URL leader dari dictionary status."""
    if statuses is None:
        statuses = get_node_statuses()
    for url, status in statuses.items():
        if status and status.get("state") == "LEADER":
            return url
    return None

def get_follower_urls(leader_url, statuses=None):
     """Mendapatkan list URL follower yang aktif."""
     if statuses is None:
        statuses = get_node_statuses()
     followers = []
     for url, status in statuses.items():
          if url != leader_url and status and status.get("state") == "FOLLOWER":
               followers.append(url)
     return followers

@pytest.fixture(scope="module", autouse=True)
def wait_for_system():
    """Menunggu sistem stabil & leader terpilih sebelum semua tes di modul ini."""
    print("\nWaiting for system to stabilize and elect a leader...")
    leader = None
    for i in range(15): # Coba selama maks 15 detik
        statuses = get_node_statuses()
        leader = get_leader_url(statuses)
        followers = get_follower_urls(leader, statuses)
        num_nodes_up = sum(1 for s in statuses.values() if s is not None)

        if leader and len(followers) >= 1 and num_nodes_up >= 2 : # Butuh leader + min 1 follower
            print(f"System stabilized: Leader={leader}, Followers={followers}")
            # Cek term konsisten (opsional tapi baik)
            terms = {s['term'] for s in statuses.values() if s}
            if len(terms) == 1:
                 print(f"Consistent term found: {terms.pop()}")
                 return # Sistem siap
            else:
                 print(f"Inconsistent terms found ({terms}), waiting...")

        print(f"Waiting... ({i+1}/15)")
        time.sleep(1)
    pytest.fail("System did not stabilize or elect a leader with enough followers in time.")


def test_lock_acquire_replicates_state():
    """Menguji acquire lock di leader tereplikasi ke follower."""
    statuses_before = get_node_statuses()
    leader_url = get_leader_url(statuses_before)
    follower_urls = get_follower_urls(leader_url, statuses_before)
    assert leader_url, "Leader not found at test start"
    assert follower_urls, "No followers found at test start"
    follower_url = follower_urls[0] # Ambil satu follower

    resource = f"int_res_{int(time.time())}"
    client = "client_int_test"

    # --- Acquire Lock ---
    print(f"\nAcquiring lock for '{resource}' on leader {leader_url}")
    acquire_payload = {"resource_id": resource, "client_id": client, "lock_type": "exclusive"}
    response_acq = requests.post(f"{leader_url}/lock/acquire", json=acquire_payload, timeout=REQUEST_TIMEOUT)
    response_acq.raise_for_status()
    assert response_acq.json().get("success") is True, f"Acquire failed: {response_acq.text}"

    # --- Beri waktu replikasi & Cek Follower ---
    print(f"Waiting {STABILIZE_WAIT}s for replication...")
    time.sleep(STABILIZE_WAIT)
    print(f"Checking status on follower {follower_url}")
    response_status = requests.get(f"{follower_url}/status", timeout=REQUEST_TIMEOUT)
    response_status.raise_for_status()
    status_data = response_status.json()

    print("Follower status after acquire:", status_data)
    assert status_data["commit_index"] >= statuses_before[follower_url]["commit_index"] + 1, "Commit index did not advance"
    assert resource in status_data["locks"]["active_locks"], f"Resource '{resource}' not found in follower's active locks"
    assert status_data["locks"]["active_locks"][resource]["owners"] == [client], "Incorrect owner in follower's lock state"
    assert status_data["locks"]["active_locks"][resource]["type"] == "exclusive", "Incorrect lock type in follower's state"

    # --- Release Lock (Cleanup) ---
    print(f"Releasing lock for '{resource}' on leader {leader_url}")
    release_payload = {"resource_id": resource, "client_id": client}
    response_rel = requests.post(f"{leader_url}/lock/release", json=release_payload, timeout=REQUEST_TIMEOUT)
    response_rel.raise_for_status()
    assert response_rel.json().get("success") is True, f"Release failed: {response_rel.text}"

    # --- Verifikasi Release di Follower ---
    print(f"Waiting {STABILIZE_WAIT}s for release replication...")
    time.sleep(STABILIZE_WAIT)
    print(f"Checking status again on follower {follower_url}")
    response_status_after = requests.get(f"{follower_url}/status", timeout=REQUEST_TIMEOUT)
    response_status_after.raise_for_status()
    status_data_after = response_status_after.json()

    print("Follower status after release:", status_data_after)
    assert status_data_after["commit_index"] >= status_data["commit_index"] + 1, "Commit index did not advance after release"
    assert resource not in status_data_after["locks"]["active_locks"], f"Resource '{resource}' still present after release"