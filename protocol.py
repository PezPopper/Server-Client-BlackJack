# protocol.py
import struct
import socket
from dataclasses import dataclass

MAGIC_COOKIE = 0xabcddcba

# Message types
MSG_OFFER = 0x2
MSG_REQUEST = 0x3
MSG_PAYLOAD = 0x4

# Server round results
RES_NOT_OVER = 0x0
RES_TIE = 0x1
RES_LOSS = 0x2
RES_WIN = 0x3

UDP_OFFER_PORT = 13122

NAME_LEN = 32
DECISION_LEN = 5

# Struct formats (network byte order)
# Offer: cookie(4) type(1) tcp_port(2) name(32) => 39 bytes
OFFER_FMT = "!IBH32s"
OFFER_SIZE = struct.calcsize(OFFER_FMT)

# Request: cookie(4) type(1) rounds(1) name(32) => 38 bytes
REQUEST_FMT = "!IBB32s"
REQUEST_SIZE = struct.calcsize(REQUEST_FMT)

# Client->Server payload: cookie(4) type(1) decision(5) => 10 bytes
CLIENT_PAYLOAD_FMT = "!IB5s"
CLIENT_PAYLOAD_SIZE = struct.calcsize(CLIENT_PAYLOAD_FMT)

# Server->Client payload: cookie(4) type(1) result(1) rank(2) suit(1) => 9 bytes
SERVER_PAYLOAD_FMT = "!IBBHB"
SERVER_PAYLOAD_SIZE = struct.calcsize(SERVER_PAYLOAD_FMT)


def pack_name(name: str) -> bytes:
    b = name.encode("utf-8", errors="ignore")
    b = b[:NAME_LEN]
    return b + b"\x00" * (NAME_LEN - len(b))


def unpack_name(b: bytes) -> str:
    return b.split(b"\x00", 1)[0].decode("utf-8", errors="ignore")


def recv_exact(sock: socket.socket, n: int) -> bytes:
    """Receive exactly n bytes from a TCP socket or raise ConnectionError."""
    chunks = []
    got = 0
    while got < n:
        chunk = sock.recv(n - got)
        if not chunk:
            raise ConnectionError("Peer closed the connection")
        chunks.append(chunk)
        got += len(chunk)
    return b"".join(chunks)


@dataclass(frozen=True)
class Offer:
    tcp_port: int
    server_name: str


def pack_offer(tcp_port: int, server_name: str) -> bytes:
    return struct.pack(OFFER_FMT, MAGIC_COOKIE, MSG_OFFER, tcp_port, pack_name(server_name))


def unpack_offer(data: bytes) -> Offer:
    if len(data) != OFFER_SIZE:
        raise ValueError("Bad offer size")
    cookie, mtype, tcp_port, name_b = struct.unpack(OFFER_FMT, data)
    if cookie != MAGIC_COOKIE or mtype != MSG_OFFER:
        raise ValueError("Bad offer header")
    return Offer(tcp_port=tcp_port, server_name=unpack_name(name_b))


@dataclass(frozen=True)
class Request:
    rounds: int
    client_name: str


def pack_request(rounds: int, client_name: str) -> bytes:
    return struct.pack(REQUEST_FMT, MAGIC_COOKIE, MSG_REQUEST, rounds & 0xFF, pack_name(client_name))


def unpack_request(data: bytes) -> Request:
    if len(data) != REQUEST_SIZE:
        raise ValueError("Bad request size")
    cookie, mtype, rounds, name_b = struct.unpack(REQUEST_FMT, data)
    if cookie != MAGIC_COOKIE or mtype != MSG_REQUEST:
        raise ValueError("Bad request header")
    return Request(rounds=rounds, client_name=unpack_name(name_b))


def pack_client_payload(decision: str) -> bytes:
    # must be exactly 5 bytes: "Hittt" or "Stand"
    if decision not in ("Hittt", "Stand"):
        raise ValueError("Decision must be 'Hittt' or 'Stand'")
    return struct.pack(CLIENT_PAYLOAD_FMT, MAGIC_COOKIE, MSG_PAYLOAD, decision.encode("ascii"))


def unpack_client_payload(data: bytes) -> str:
    if len(data) != CLIENT_PAYLOAD_SIZE:
        raise ValueError("Bad client payload size")
    cookie, mtype, decision_b = struct.unpack(CLIENT_PAYLOAD_FMT, data)
    if cookie != MAGIC_COOKIE or mtype != MSG_PAYLOAD:
        raise ValueError("Bad client payload header")
    decision = decision_b.decode("ascii", errors="ignore")
    if decision not in ("Hittt", "Stand"):
        raise ValueError("Bad decision value")
    return decision


def pack_server_payload(result: int, rank: int, suit: int) -> bytes:
    # rank: 1..13, suit: 0..3
    return struct.pack(SERVER_PAYLOAD_FMT, MAGIC_COOKIE, MSG_PAYLOAD, result & 0xFF, rank & 0xFFFF, suit & 0xFF)


@dataclass(frozen=True)
class ServerPayload:
    result: int
    rank: int
    suit: int


def unpack_server_payload(data: bytes) -> ServerPayload:
    if len(data) != SERVER_PAYLOAD_SIZE:
        raise ValueError("Bad server payload size")
    cookie, mtype, result, rank, suit = struct.unpack(SERVER_PAYLOAD_FMT, data)
    if cookie != MAGIC_COOKIE or mtype != MSG_PAYLOAD:
        raise ValueError("Bad server payload header")
    return ServerPayload(result=result, rank=rank, suit=suit)


SUIT_NAMES = ["Heart", "Diamond", "Club", "Spade"]
RANK_NAMES = {
    1: "A", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7",
    8: "8", 9: "9", 10: "10", 11: "J", 12: "Q", 13: "K"
}


def card_to_str(rank: int, suit: int) -> str:
    r = RANK_NAMES.get(rank, f"?{rank}")
    s = SUIT_NAMES[suit] if 0 <= suit < 4 else f"?{suit}"
    return f"{r} of {s}"
