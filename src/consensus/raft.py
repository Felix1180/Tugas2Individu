import asyncio
import random
import logging
from enum import Enum
from ..utils.config import ELECTION_TIMEOUT_MIN, ELECTION_TIMEOUT_MAX, HEARTBEAT_INTERVAL
from ..communication.message_passing import broadcast_rpc, send_rpc

class NodeState(Enum):
    FOLLOWER = 1
    CANDIDATE = 2
    LEADER = 3

class RaftNode:
    def __init__(self, node_id, peers, lock_manager):
        self.node_id = node_id
        self.peers = peers
        self.state = NodeState.FOLLOWER
        self.current_term = 0
        self.voted_for = None
        self.log = []  # Log entries: { 'term': term, 'command': command }
        self.commit_index = -1
        self.last_applied = -1
        self.leader_id = None
        self.lock_manager = lock_manager

        self._reset_election_timeout()

    def _reset_election_timeout(self):
        self.election_timeout = random.uniform(ELECTION_TIMEOUT_MIN, ELECTION_TIMEOUT_MAX)
        self.time_since_last_contact = 0.0

    async def run(self):
        """Main loop untuk node Raft."""
        logging.info(f"[{self.node_id}] Starting as {self.state.name} in term {self.current_term}")
        while True:
            if self.state == NodeState.FOLLOWER:
                await self._run_follower()
            elif self.state == NodeState.CANDIDATE:
                await self._run_candidate()
            elif self.state == NodeState.LEADER:
                await self._run_leader()

    async def _run_follower(self):
        await asyncio.sleep(0.1)
        self.time_since_last_contact += 0.1
        if self.time_since_last_contact > self.election_timeout:
            logging.info(f"[{self.node_id}] Follower timeout, becoming Candidate.")
            self.state = NodeState.CANDIDATE

    async def _run_candidate(self):
        self.current_term += 1
        self.voted_for = self.node_id
        self._reset_election_timeout()
        
        votes_received = 1
        
        request_vote_payload = {
            'term': self.current_term,
            'candidate_id': self.node_id,
            'last_log_index': len(self.log) - 1,
            'last_log_term': self.log[-1]['term'] if self.log else 0,
        }

        responses = await broadcast_rpc(self.peers, 'request_vote', request_vote_payload)

        for resp in responses:
            if resp and resp.get('vote_granted'):
                votes_received += 1
        
        if votes_received > (len(self.peers) + 1) / 2:
            logging.info(f"[{self.node_id}] Won election for term {self.current_term}. Becoming LEADER.")
            self.state = NodeState.LEADER
            self.leader_id = self.node_id
        else:
            logging.info(f"[{self.node_id}] Lost election for term {self.current_term}. Reverting to FOLLOWER.")
            self.state = NodeState.FOLLOWER

    async def _run_leader(self):
        heartbeat_payload = {
            'term': self.current_term,
            'leader_id': self.node_id,
            'leader_commit': self.commit_index,
            'entries': []
        }
        await broadcast_rpc(self.peers, 'append_entries', heartbeat_payload)
        await asyncio.sleep(HEARTBEAT_INTERVAL)

    async def handle_request_vote(self, term, candidate_id, last_log_index, last_log_term):
        if term < self.current_term:
            return {'term': self.current_term, 'vote_granted': False}
        
        if term > self.current_term:
            self.current_term = term
            self.state = NodeState.FOLLOWER
            self.voted_for = None

        vote_granted = False
        if (self.voted_for is None or self.voted_for == candidate_id):
            my_last_log_term = self.log[-1]['term'] if self.log else 0
            my_last_log_index = len(self.log) - 1
            if last_log_term > my_last_log_term or \
               (last_log_term == my_last_log_term and last_log_index >= my_last_log_index):
                self.voted_for = candidate_id
                vote_granted = True
                self._reset_election_timeout()
                logging.info(f"[{self.node_id}] Voted for {candidate_id} in term {self.current_term}")

        return {'term': self.current_term, 'vote_granted': vote_granted}

    # <<< PERBAIKI INDENTASI DI SINI
    async def handle_append_entries(self, term, leader_id, prev_log_index, prev_log_term, entries, leader_commit):
        """Menangani heartbeat dan entri log dari leader."""
        if term < self.current_term:
            return {'term': self.current_term, 'success': False}

        self._reset_election_timeout()
        if term > self.current_term:
            self.current_term = term
            self.voted_for = None
        self.state = NodeState.FOLLOWER
        self.leader_id = leader_id

        if prev_log_index > -1 and (len(self.log) <= prev_log_index or self.log[prev_log_index]['term'] != prev_log_term):
            logging.warning(f"[{self.node_id}] Log consistency check failed at index {prev_log_index}.")
            return {'term': self.current_term, 'success': False}

        if entries:
            self.log = self.log[:prev_log_index + 1]
            self.log.extend(entries)
            logging.info(f"[{self.node_id}] Follower accepted and appended {len(entries)} entries.")

        if leader_commit > self.commit_index:
            self.commit_index = min(leader_commit, len(self.log) - 1)
            await self._apply_log_entries()

        return {'term': self.current_term, 'success': True}

    # <<< PERBAIKI INDENTASI DI SINI
    async def handle_client_request(self, command):
        """Menangani permintaan dari klien dengan replikasi yang benar."""
        if self.state != NodeState.LEADER:
            return {"success": False, "leader": self.leader_id, "message": "Not a leader"}

        new_entry_index = len(self.log)
        log_entry = {'term': self.current_term, 'command': command}
        self.log.append(log_entry)
        logging.info(f"[{self.node_id}] Leader received command, appended to log at index {new_entry_index}")

        success_count = 1
        
        prev_log_index = new_entry_index - 1
        prev_log_term = self.log[prev_log_index]['term'] if prev_log_index >= 0 else 0
        
        payload = {
            'term': self.current_term,
            'leader_id': self.node_id,
            'prev_log_index': prev_log_index,
            'prev_log_term': prev_log_term,
            'entries': [log_entry],
            'leader_commit': self.commit_index
        }
        
        responses = await broadcast_rpc(self.peers, 'append_entries', payload)

        for resp in responses:
            if resp and resp.get('success'):
                success_count += 1
        
        if success_count > (len(self.peers) + 1) / 2:
            self.commit_index = new_entry_index
            logging.info(f"[{self.node_id}] Leader committed entry at index {self.commit_index} with {success_count} votes.")
            
            await self._apply_log_entries()
            return {"success": True, "message": "Command committed and applied by the cluster."}
        else:
            self.log.pop()
            logging.warning(f"[{self.node_id}] Failed to replicate entry, only received {success_count} confirmations.")
            return {"success": False, "message": "Failed to achieve consensus for the command."}

    async def _apply_log_entries(self):
        """Menerapkan entri log yang sudah di-commit ke state machine."""
        while self.last_applied < self.commit_index:
            self.last_applied += 1
            entry = self.log[self.last_applied]
            command = entry['command']
            
            logging.info(f"[{self.node_id}] Applying command to state machine: {command}")
            await self.lock_manager.apply_command(command)