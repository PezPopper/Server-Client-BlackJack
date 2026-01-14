# client.py
import socket
from dataclasses import dataclass
from typing import Tuple, List
import time
from dataclasses import dataclass

from protocol import (
    UDP_OFFER_PORT,
    SERVER_PAYLOAD_SIZE,

    RES_NOT_OVER, RES_TIE, RES_LOSS, RES_WIN,

    pack_request,
    unpack_offer,
    pack_client_payload,
    unpack_server_payload,

    recv_exact,
)




# ----------------------------
# Pretty card formatting
# ----------------------------
SUIT_NAMES = {
    0: "Heart",
    1: "Diamond",
    2: "Club",
    3: "Spade",
}
RANK_NAMES = {
    1: "A",
    11: "J",
    12: "Q",
    13: "K",
}
RESULT_STR = {
    RES_WIN: "WIN ✅",
    RES_LOSS: "LOSS ❌",
    RES_TIE: "TIE 🤝",
    RES_NOT_OVER: "…",
}

def rank_to_name(rank: int) -> str:
    return RANK_NAMES.get(rank, str(rank))

def card_value(rank: int) -> int:
    # Simplified rules: Ace always 11, face cards 10
    if rank == 1:
        return 11
    if rank in (11, 12, 13):
        return 10
    return rank

def fmt_card(rank: int, suit: int) -> str:
    return f"{rank_to_name(rank)} of {SUIT_NAMES.get(suit, '???')}"


@dataclass
class Offer:
    tcp_port: int
    server_name: str
    server_ip: str
@dataclass
class OfferWithIP:
    server_ip: str
    tcp_port: int
    server_name: str



@dataclass
class ServerPayload:
    result: int
    rank: int
    suit: int


def recv_exact(sock: socket.socket, n: int) -> bytes:
    chunks = []
    got = 0
    while got < n:
        chunk = sock.recv(n - got)
        if not chunk:
            raise ConnectionError("socket closed while receiving")
        chunks.append(chunk)
        got += len(chunk)
    return b"".join(chunks)


# ----------------------------
# Rate-limit demo easter egg
# ----------------------------
def dos_demo(server_ip: str, server_port: int, client_name: str,
                    attempts: int = 5000, delay: float = 0.01) -> None:
    """
    Demonstrates server-side connection rate limiting.
    We connect quickly many times, send an INVALID request (rounds=0),
    and close immediately so the server threads exit fast.
    """
    print(f"\n🧪 Attacking: burst {attempts} TCP connects to {server_ip}:{server_port}")
    print("   (server should print 🛡️ RATE LIMIT blocked messages.)")

    for _ in range(attempts):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        try:
            s.connect((server_ip, server_port))
            # send invalid rounds=0 so server closes quickly (safe + clean demo)
            s.sendall(pack_request(0, client_name))
        except Exception:
            pass
        finally:
            try:
                s.close()
            except Exception:
                pass
        time.sleep(delay)

    print("✅ Demo DoS and Rate Limiting finished. Check the SERVER output.\n")


# ----------------------------
# Game session
# ----------------------------
@dataclass
class RoundStats:
    hits: int = 0
    stands: int = 0
    player_bust: bool = False
    player_total: int = 0
    dealer_total: int = 0
    result: int = RES_TIE

def play_one_round(tcp: socket.socket, round_idx: int) -> RoundStats:
    stats = RoundStats()
    player: List[Tuple[int, int]] = []
    dealer: List[Tuple[int, int]] = []

    print(f"\n=== Round {round_idx} ===")

    # Initial deal: 3 payloads: P, P, Dealer up-card
    for _ in range(2):
        p = unpack_server_payload(recv_exact(tcp, SERVER_PAYLOAD_SIZE))
        if not p:
            raise ConnectionError("invalid server payload (player card)")
        player.append((p.rank, p.suit))
        print(f"You got: {fmt_card(p.rank, p.suit)}")

    up = unpack_server_payload(recv_exact(tcp, SERVER_PAYLOAD_SIZE))
    if not up:
        raise ConnectionError("invalid server payload (dealer up card)")
    dealer.append((up.rank, up.suit))
    print(f"Dealer shows: {fmt_card(up.rank, up.suit)}")

    def total(hand: List[Tuple[int, int]]) -> int:
        return sum(card_value(r) for r, _ in hand)

    # Player turn
    while True:
        stats.player_total = total(player)
        print(f"Your total: {stats.player_total}")

        if stats.player_total > 21:
            # In normal flow server should already have ended, but keep safe.
            stats.player_bust = True
            stats.result = RES_LOSS
            print("You busted!")
            break

        choice = input("Hit or stand? (h/s): ").strip().lower()
        if choice in ("s", "stand"):
            stats.stands += 1
            tcp.sendall(pack_client_payload("Stand"))
            break
        elif choice in ("h", "hit"):
            stats.hits += 1
            tcp.sendall(pack_client_payload("Hittt"))

            # server replies with the new card (possibly final)
            p = unpack_server_payload(recv_exact(tcp, SERVER_PAYLOAD_SIZE))
            if not p:
                raise ConnectionError("invalid server payload (hit reply)")
            player.append((p.rank, p.suit))
            stats.player_total = total(player)

            print(f"You drew: {fmt_card(p.rank, p.suit)}")
            print(f"Your total: {stats.player_total}")

            if p.result != RES_NOT_OVER:
                # Round ended immediately (player bust -> LOSS)
                stats.result = p.result
                stats.player_bust = (stats.player_total > 21)
                # dealer total may not be fully known; keep as current known (up-card only)
                stats.dealer_total = total(dealer)
                print(f"Result: {RESULT_STR.get(stats.result, '???')}")
                return stats
        else:
            print("Please type 'h' or 's'.")

    # Dealer phase starts now: server will stream dealer cards until final result != 0
    # First: reveal hidden dealer card
    while True:
        sp = unpack_server_payload(recv_exact(tcp, SERVER_PAYLOAD_SIZE))
        if not sp:
            raise ConnectionError("invalid server payload (dealer phase)")

        # Add dealer card
        dealer.append((sp.rank, sp.suit))

        # Print what happened
        if len(dealer) == 2:
            print(f"Dealer reveals: {fmt_card(sp.rank, sp.suit)}")
        else:
            print(f"Dealer draws: {fmt_card(sp.rank, sp.suit)}")

        stats.dealer_total = total(dealer)
        stats.player_total = total(player)

        # If this payload ended the round, stop
        if sp.result != RES_NOT_OVER:
            stats.result = sp.result
            print(f"Dealer total: {stats.dealer_total}")
            print(f"Result: {RESULT_STR.get(stats.result, '???')}")
            return stats


def run_session(server: OfferWithIP, rounds: int, client_name: str) -> None:
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp.settimeout(15.0)
    try:
        tcp.connect((server.server_ip, server.tcp_port))
        tcp.sendall(pack_request(rounds, client_name))
        print(f"Connected to server {server.server_name} at {server.server_ip}:{server.tcp_port}. Starting {rounds} rounds...")

        wins = losses = ties = 0
        busts = 0
        total_hits = 0
        total_stands = 0

        for i in range(1, rounds + 1):
            rs = play_one_round(tcp, i)

            total_hits += rs.hits
            total_stands += rs.stands
            busts += 1 if rs.player_bust else 0

            if rs.result == RES_WIN:
                wins += 1
            elif rs.result == RES_LOSS:
                losses += 1
            else:
                ties += 1

            # per-round stat line (what you asked for)
            print(f"[Round {i}] {RESULT_STR.get(rs.result)} | P={rs.player_total} D={rs.dealer_total} | hits={rs.hits} stands={rs.stands} | bust={rs.player_bust}")

        played = wins + losses + ties
        win_rate = (wins / played) * 100 if played else 0.0
        bust_rate = (busts / played) * 100 if played else 0.0

        print(f"\nFinished playing {rounds} rounds, win rate: {win_rate:.2f}% (W={wins}, L={losses}, T={ties})")
        print(f"Player bust rate: {bust_rate:.2f}%")
        print(f"Decisions totals: Hit={total_hits}, Stand={total_stands}\n")

    finally:
        try:
            tcp.close()
        except Exception:
            pass


# ----------------------------
# Main loop (assignment-style)
# ----------------------------
def open_udp_listener() -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # Allow multiple clients on same machine (if OS supports it)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except Exception:
        pass
    s.bind(("", UDP_OFFER_PORT))
    s.settimeout(2.0)
    return s

def wait_for_offer(udp: socket.socket) -> OfferWithIP:
    while True:
        try:
            data, addr = udp.recvfrom(2048)
        except socket.timeout:
            continue  # not busy-waiting

        try:
            o = unpack_offer(data)  # protocol.py unpack_offer(data)
        except Exception:
            continue  # ignore garbage packets

        offer = OfferWithIP(server_ip=addr[0], tcp_port=o.tcp_port, server_name=o.server_name)
        print(f"Received offer from {offer.server_ip} (server '{offer.server_name}', tcp_port={offer.tcp_port})")
        return offer


def prompt_rounds_and_mode() -> Tuple[int, bool]:
    """
    Returns (rounds, run_rate_limit_demo).
    Easter egg: type 'dos' here.
    """
    while True:
        raw = input("How many rounds do you want to play? (1-255): ").strip().lower()
        if raw == "dos":
            print("🛡️ DoS mode armed. Waiting for an offer...")
            # We'll run the demo once we receive an offer, then ask for rounds again.
            return (1, True)

        try:
            rounds = int(raw)
            if 1 <= rounds <= 255:
                return (rounds, False)
        except ValueError:
            pass
        print("Please enter a number 1-255 (or type 'dos').")

def main() -> None:
    client_name = input("Enter your team name (default: Blackijecky-Client): ").strip()
    if not client_name:
        client_name = "Blackijecky-Client"

    rounds, demo = prompt_rounds_and_mode()

    print("Client started, listening for offer requests...")
    udp = open_udp_listener()

    try:
        while True:
            offer = wait_for_offer(udp)

            # If demo mode was armed, run it ONCE on the offered server, then ask rounds normally
            if demo:
                dos_demo(offer.server_ip, offer.tcp_port, client_name)
                rounds, demo = prompt_rounds_and_mode()
                print("Client started, listening for offer requests...")
                continue

            # Normal play session
            run_session(offer, rounds, client_name)

            # Assignment says: close TCP and return to step 4 (listening)
            print("Client started, listening for offer requests...")

    except KeyboardInterrupt:
        print("\nClient exiting...")
    finally:
        try:
            udp.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
