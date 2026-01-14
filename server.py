# server.py
import socket
import threading
import time
import traceback
from collections import deque, defaultdict

from protocol import (
    UDP_OFFER_PORT, pack_offer,
    recv_exact,
    unpack_request,
    CLIENT_PAYLOAD_SIZE, unpack_client_payload,
    pack_server_payload,
    RES_NOT_OVER, RES_WIN, RES_LOSS, RES_TIE
)
from blackjack import new_shuffled_deck, RoundState, hand_total

SERVER_NAME = "Protected-Casino"
OFFER_INTERVAL_SEC = 1.0

TCP_BACKLOG = 50
TCP_TIMEOUT_SEC = 15.0  # per-socket timeout

PRINT_LOCK = threading.Lock()


class RateLimiter:
    """
    Simple sliding-window limiter:
    allow at most `max_events` per `window_seconds` for each key (e.g., client IP).
    """
    def __init__(self, max_events: int, window_seconds: float):
        self.max_events = max_events
        self.window_seconds = window_seconds
        self.events = defaultdict(deque)  # key -> deque[timestamps]
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        cutoff = now - self.window_seconds
        with self.lock:
            dq = self.events[key]
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= self.max_events:
                return False
            dq.append(now)
            return True


# ---- Rate limit config (demo-friendly defaults) ----
RL_MAX_CONNECTIONS = 2
RL_WINDOW_SECONDS = 5.0
rate_limiter = RateLimiter(RL_MAX_CONNECTIONS, RL_WINDOW_SECONDS)


def log(msg: str) -> None:
    with PRINT_LOCK:
        print(msg, flush=True)


def offer_broadcaster(stop_event: threading.Event, tcp_port: int) -> None:
    """
    Sends UDP broadcast offers once every second on UDP port 13122.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        payload = pack_offer(tcp_port, SERVER_NAME)
        while not stop_event.is_set():
            try:
                s.sendto(payload, ("<broadcast>", UDP_OFFER_PORT))
            except Exception as e:
                log(f"[UDP] Failed to send offer: {e}")
            stop_event.wait(OFFER_INTERVAL_SEC)  # not busy-waiting
    finally:
        try:
            s.close()
        except Exception:
            pass


def send_card(conn: socket.socket, result: int, card: tuple[int, int]) -> None:
    rank, suit = card
    conn.sendall(pack_server_payload(result, rank, suit))


def decide_winner(player_total: int, dealer_total: int) -> int:
    if player_total > 21:
        return RES_LOSS
    if dealer_total > 21:
        return RES_WIN
    if player_total > dealer_total:
        return RES_WIN
    if dealer_total > player_total:
        return RES_LOSS
    return RES_TIE


def play_one_round(conn: socket.socket, client_name: str, round_idx: int) -> int:
    """
    Plays one simplified blackjack round.
    Returns RES_WIN/RES_LOSS/RES_TIE.

    Protocol we follow (important for compatibility):
      - Initial deal: server sends 3 payloads with result=0:
          player card, player card, dealer up-card
      - Player phase:
          client sends payload decisions ("Hittt"/"Stand")
          on "Hittt": server sends the new player card (result=0 unless it ends the round)
          if player busts on a hit: that same card is sent with result=LOSS and round ends
      - Dealer phase (after Stand, if player not bust):
          server reveals dealer hidden card (result=0)
          server hits until dealer_total >= 17 or bust, sending each card (result=0 unless it ends)
          final message: last revealed/drawn card is sent with final result (WIN/LOSS/TIE)
    """
    state = RoundState(deck=new_shuffled_deck(), player=[], dealer=[])

    # Deal initial cards
    state.player.append(state.draw())
    state.player.append(state.draw())
    state.dealer.append(state.draw())
    state.dealer.append(state.draw())

    log(f"[{client_name}] Round {round_idx}: dealing...")

    # Send player two cards + dealer up card (dealer[0])
    send_card(conn, RES_NOT_OVER, state.player[0])
    send_card(conn, RES_NOT_OVER, state.player[1])
    send_card(conn, RES_NOT_OVER, state.dealer[0])

    # Player turn
    while True:
        p_total = hand_total(state.player)
        if p_total > 21:
            # Safety (shouldn't happen here normally)
            log(f"[{client_name}] Player already bust ({p_total}).")
            send_card(conn, RES_LOSS, state.player[-1])
            return RES_LOSS

        # Wait for client decision
        data = recv_exact(conn, CLIENT_PAYLOAD_SIZE)
        decision = unpack_client_payload(data)
        log(f"[{client_name}] Player decision: {decision} (total={p_total})")

        if decision == "Stand":
            break

        # Hittt
        new_card = state.draw()
        state.player.append(new_card)
        p_total = hand_total(state.player)

        if p_total > 21:
            log(f"[{client_name}] Player hits {new_card} and busts ({p_total}). Dealer wins.")
            send_card(conn, RES_LOSS, new_card)  # last card with final result
            return RES_LOSS
        else:
            send_card(conn, RES_NOT_OVER, new_card)

    # Dealer turn (reveal hidden card first)
    hidden = state.dealer[1]
    send_card(conn, RES_NOT_OVER, hidden)
    log(f"[{client_name}] Dealer reveals hidden card. Dealer total now {hand_total(state.dealer)}")

    # Dealer hits until >= 17 or bust
    while True:
        d_total = hand_total(state.dealer)
        if d_total >= 17:
            break

        new_card = state.draw()
        state.dealer.append(new_card)
        d_total = hand_total(state.dealer)
        log(f"[{client_name}] Dealer hits. Dealer total now {d_total}")

        if d_total > 21:
            send_card(conn, RES_WIN, new_card)
            return RES_WIN

        send_card(conn, RES_NOT_OVER, new_card)

    # Decide winner (dealer stands)
    p_total = hand_total(state.player)
    d_total = hand_total(state.dealer)
    result = decide_winner(p_total, d_total)
    log(f"[{client_name}] Round over. Player={p_total}, Dealer={d_total}, Result={result}")

    # Send final result using dealer's last card (revealed/drawn)
    send_card(conn, result, state.dealer[-1])
    return result


def handle_client(conn: socket.socket, addr: tuple[str, int]) -> None:
    conn.settimeout(TCP_TIMEOUT_SEC)
    client_name = f"{addr[0]}:{addr[1]}"
    try:
        # Read request
        req_raw = recv_exact(conn, 38)  # REQUEST_SIZE, kept literal to avoid circular import
        req = unpack_request(req_raw)
        client_name = req.client_name or client_name
        rounds = req.rounds

        if rounds < 1:
            log(f"[{client_name}] Invalid rounds={rounds}. Closing.")
            return

        log(f"[{client_name}] Connected. Requested rounds: {rounds}")

        for i in range(1, rounds + 1):
            play_one_round(conn, client_name, i)

        log(f"[{client_name}] Finished {rounds} rounds. Closing TCP.")

    except socket.timeout:
        log(f"[{client_name}] Timeout waiting for data. Closing.")
    except ConnectionError as e:
        log(f"[{client_name}] Connection closed: {e}")
    except Exception as e:
        log(f"[{client_name}] ERROR: {e}")
        traceback.print_exc()
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_local_ip() -> str:
    """
    Best-effort local IP detection (so your 'listening on IP ...' print is useful).
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "0.0.0.0"
    finally:
        try:
            s.close()
        except Exception:
            pass


def main() -> None:
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tcp.bind(("", 0))  # choose any free port
    tcp.listen(TCP_BACKLOG)

    tcp_port = tcp.getsockname()[1]
    ip = get_local_ip()
    log(f"Server started, listening on IP address {ip}, TCP port {tcp_port}")

    stop_event = threading.Event()
    t = threading.Thread(target=offer_broadcaster, args=(stop_event, tcp_port), daemon=True)
    t.start()

    try:
        while True:
            conn, addr = tcp.accept()  # blocking accept, no busy waiting
            ip = addr[0]

            # ---- RATE LIMIT ENFORCEMENT (the missing part) ----
            if not rate_limiter.allow(ip):
                log(f"🛡️ RATE LIMIT: blocked TCP connection from {addr[0]}:{addr[1]}")
                try:
                    conn.close()
                except Exception:
                    pass
                continue

            log(f"[TCP] Accepted connection from {addr[0]}:{addr[1]}")
            th = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            th.start()

    except KeyboardInterrupt:
        log("Server shutting down...")
    finally:
        stop_event.set()
        try:
            tcp.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
