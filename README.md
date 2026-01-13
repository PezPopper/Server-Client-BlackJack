# Blackijecky – Intro to Networks Blackjack (Client/Server)

A Python 3 client-server implementation of a simplified Blackjack game for the **Intro to Networks Hackathon**.

- **Server** (dealer): broadcasts UDP “offer” packets every second and hosts the game over TCP.
- **Client** (player): listens for offers, connects via TCP, requests a number of rounds, and plays interactively.

Includes an **educational rate-limiting demo** (“DoS demo”) you can trigger from the client to showcase defensive server logic in a controlled LAN environment.

---

## Features

### ✅ Assignment protocol compatibility
Implements the specified packet formats:
- **Offer** (UDP, server → clients)
- **Request** (TCP, client → server)
- **Payload** (TCP, both directions)

Uses the **magic cookie** `0xabcddcba` and the required message types (offer/request/payload).

### 🃏 Simplified Blackjack rules
- 52-card deck
- Card values: 2–10 → value, J/Q/K → 10, A → 11 (no 1/11 logic)
- Player: Hit / Stand
- Dealer: hit until total ≥ 17
- Win/Loss/Tie logic as described in the assignment

### 🛡️ Rate Limiting (Defense Mechanism)
The server applies a **sliding-window rate limit** per client IP (example defaults):
- allow at most `RL_MAX_CONNECTIONS` connections per `RL_WINDOW_SECONDS`

This prevents rapid repeated connections from consuming server resources (threads/sockets).

### 🎭 Easter egg: `dos` → `dos_demo`
Typing `dos` instead of a number in the client activates an educational “DoS demo” mode:
- the client makes **many quick, short TCP requests** to trigger the server’s rate limiter
- the server **blocks** excessive attempts and logs them
- no destructive payloads — just a controlled demonstration of rate limiting

---

## Project Structure

Typical layout:

```
.
├── server.py
├── client.py
├── protocol.py
├── blackjack.py
└── README.md
```

- `server.py` – TCP server + UDP offer broadcaster + round logic + rate limiter
- `client.py` – offer listener + interactive play + `dos_demo` mode
- `protocol.py` – pack/unpack helpers + constants + exact-length reads
- `blackjack.py` – deck/hand utilities and round state

---

## Requirements

- Python **3.9+** recommended (any Python 3.x should work)
- No external dependencies required (uses standard library only)

---

## How to Run (Two Computers on the Same LAN)

### 1) Start the server (Dealer)
On computer **A**:

```bash
python server.py
```

You should see something like:

```
Server started, listening on IP address 192.168.x.x, TCP port 54xxx
```

The server will broadcast UDP offers every second.

### 2) Start the client (Player)
On computer **B**:

```bash
python client.py
```

Expected flow:
1. Client asks for number of rounds.
2. Client listens on UDP port **13122** for offers.
3. Client connects to the first server offer it receives and plays.

---

## Client Modes

### A) Normal play (manual)
When prompted:

```
How many rounds do you want to play? (1-255):
```

Enter a number like `5`.

The client will:
- wait for an offer
- connect to the server
- send a request message containing the number of rounds
- play round-by-round (Hit/Stand)

At the end:
- prints total stats (W/L/T and win rate)
- closes TCP
- returns to listening for offers (as in the assignment example)

### B) `dos_demo` (rate limiting demonstration)
At the same prompt, type:

```
dos
```

This triggers:
- `dos_demo()` in the client
- many rapid connection attempts to the same server
- the server rate limiter blocks excess attempts
- the client prints how many attempts succeeded vs. were blocked/failed

**Goal:** demonstrate defensive networking, not disrupt a network.

> Note: This is not “DDoS” (distributed). It’s a single-source, controlled DoS-style connection burst used for a demo.

---

## Common LAN Troubleshooting

### UDP offers not received
- Make sure both machines are on the **same LAN/subnet**
- Ensure OS firewall allows:
  - UDP inbound on **13122** (client)
  - TCP inbound on the server’s chosen port (server prints it)
- Some networks block broadcast; if so, use a personal hotspot or a simpler LAN.

### Running multiple clients on the same machine
Multiple clients cannot bind to the same UDP port unless `SO_REUSEPORT` is used.
The assignment notes this; the client may include it.

### Timeouts / disconnections
The server uses a per-socket timeout (example: 15s). If a client hangs, the server closes the connection and stays alive.

---

## Notes on Compatibility

- The server broadcasts:
  - magic cookie + offer type + TCP port + 32-byte server name
- The client sends a request:
  - magic cookie + request type + 1-byte rounds + 32-byte client name
- Game payloads follow the assignment structure:
  - client sends decision (`Hittt` / `Stand`)
  - server responds with (result byte + encoded card)

---

## License
Educational project for a university networking assignment.
