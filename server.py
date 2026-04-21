import socket
import time
import random
import threading
import json

HOST = "0.0.0.0"
PORT = 5555

TICK_RATE = 20          # Send game state 20 times per second
TICK_INTERVAL = 1.0 / TICK_RATE
PACKET_LOSS_CHANCE = 0.2

server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
server.bind((HOST, PORT))
server.setblocking(False)

# ─── Game State ────────────────────────────────────────────────────────────────
# Each client gets: position (x, y), health, score
game_state = {}     # addr_str -> { x, y, health, score, name }
clients = {}        # addr_str -> addr tuple
sequence_number = 0 # Global packet counter

# ─── Stats Tracking ────────────────────────────────────────────────────────────
stats = {
    "packets_sent": 0,
    "packets_dropped": 0,
    "total_latency": 0.0,
    "latency_samples": 0,
}

print("[UDP GAME SERVER STARTED]")
print(f"Tick Rate: {TICK_RATE} Hz  |  Packet Loss: {int(PACKET_LOSS_CHANCE*100)}%")
print("-" * 50)


def addr_key(addr):
    return f"{addr[0]}:{addr[1]}"


def broadcast(payload: dict, exclude=None):
    """Send a JSON packet to all clients, simulating packet loss."""
    global sequence_number
    sequence_number += 1
    payload["seq"] = sequence_number
    payload["server_time"] = time.time()

    data = json.dumps(payload).encode()

    for key, addr in list(clients.items()):
        if exclude and key == exclude:
            continue

        # Simulate packet loss
        if random.random() < PACKET_LOSS_CHANCE:
            stats["packets_dropped"] += 1
            print(f"[PACKET DROPPED] → {key}  (seq={sequence_number})")
            continue

        try:
            server.sendto(data, addr)
            stats["packets_sent"] += 1
        except Exception as e:
            print(f"[ERROR] Sending to {key}: {e}")


def send_to(addr, payload: dict):
    """Send a packet to one specific client (no packet loss for direct acks)."""
    global sequence_number
    sequence_number += 1
    payload["seq"] = sequence_number
    payload["server_time"] = time.time()
    try:
        server.sendto(json.dumps(payload).encode(), addr)
    except Exception as e:
        print(f"[ERROR] Direct send: {e}")


# ─── Tick Loop ─────────────────────────────────────────────────────────────────
def game_tick():
    """Fixed-rate loop: broadcasts full game state to all clients."""
    while True:
        tick_start = time.time()

        if clients:
            payload = {
                "type": "state_update",
                "players": game_state
            }
            broadcast(payload)

        # Sleep for remainder of tick
        elapsed = time.time() - tick_start
        sleep_time = TICK_INTERVAL - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)


# ─── Receive Loop ──────────────────────────────────────────────────────────────
def receive_loop():
    while True:
        try:
            data, addr = server.recvfrom(2048)
        except BlockingIOError:
            time.sleep(0.001)
            continue
        except Exception as e:
            print(f"[ERROR] Receive: {e}")
            continue

        key = addr_key(addr)

        try:
            msg = json.loads(data.decode())
        except Exception:
            print(f"[WARN] Bad packet from {key}")
            continue

        msg_type = msg.get("type")

        # ── Join ──────────────────────────────────────────────────────────────
        if msg_type == "join":
            name = msg.get("name", f"Player_{len(clients)+1}")
            clients[key] = addr
            game_state[key] = {
                "name": name,
                "x": random.randint(0, 800),
                "y": random.randint(0, 600),
                "health": 100,
                "score": 0
            }
            print(f"[JOIN] {name} connected from {key}")

            # Confirm join to new client
            send_to(addr, {
                "type": "join_ack",
                "your_id": key,
                "message": f"Welcome {name}! Players online: {len(clients)}"
            })

            # Notify all others
            broadcast({
                "type": "player_joined",
                "player_id": key,
                "name": name,
                "players_online": len(clients)
            }, exclude=key)

        # ── Player Input / Move ───────────────────────────────────────────────
        elif msg_type == "move":
            if key in game_state:
                client_time = msg.get("client_time", 0)
                if client_time:
                    latency = time.time() - client_time
                    stats["total_latency"] += latency
                    stats["latency_samples"] += 1

                # Apply movement (server is authoritative)
                dx = msg.get("dx", 0)
                dy = msg.get("dy", 0)
                game_state[key]["x"] = max(0, min(800, game_state[key]["x"] + dx))
                game_state[key]["y"] = max(0, min(600, game_state[key]["y"] + dy))

                # Send authoritative position back to this client for reconciliation
                send_to(addr, {
                    "type": "position_correction",
                    "x": game_state[key]["x"],
                    "y": game_state[key]["y"],
                    "client_seq": msg.get("client_seq", -1)
                })

                print(f"[MOVE] {game_state[key]['name']} → ({game_state[key]['x']}, {game_state[key]['y']})")

        # ── Chat Message ──────────────────────────────────────────────────────
        elif msg_type == "chat":
            if key in game_state:
                name = game_state[key]["name"]
                text = msg.get("text", "")
                print(f"[CHAT] {name}: {text}")
                broadcast({
                    "type": "chat",
                    "from": name,
                    "text": text,
                    "client_time": msg.get("client_time", 0)
                })

        # ── Ping ──────────────────────────────────────────────────────────────
        elif msg_type == "ping":
            send_to(addr, {
                "type": "pong",
                "client_time": msg.get("client_time", 0)
            })

        # ── Stats Request ─────────────────────────────────────────────────────
        elif msg_type == "get_stats":
            avg_latency = (
                stats["total_latency"] / stats["latency_samples"]
                if stats["latency_samples"] > 0 else 0
            )
            send_to(addr, {
                "type": "server_stats",
                "packets_sent": stats["packets_sent"],
                "packets_dropped": stats["packets_dropped"],
                "avg_latency_ms": round(avg_latency * 1000, 2),
                "players_online": len(clients)
            })

        # ── Disconnect ────────────────────────────────────────────────────────
        elif msg_type == "quit":
            if key in clients:
                name = game_state.get(key, {}).get("name", key)
                del clients[key]
                del game_state[key]
                print(f"[QUIT] {name} disconnected")
                broadcast({
                    "type": "player_left",
                    "player_id": key,
                    "name": name,
                    "players_online": len(clients)
                })


# ─── Start Threads ─────────────────────────────────────────────────────────────
threading.Thread(target=game_tick, daemon=True).start()
threading.Thread(target=receive_loop, daemon=True).start()

# Keep alive + print server stats every 10 seconds
print("Server running... (Ctrl+C to stop)\n")
try:
    while True:
        time.sleep(10)
        if stats["latency_samples"] > 0:
            avg = stats["total_latency"] / stats["latency_samples"] * 1000
            loss_pct = (
                stats["packets_dropped"] /
                (stats["packets_sent"] + stats["packets_dropped"]) * 100
                if (stats["packets_sent"] + stats["packets_dropped"]) > 0 else 0
            )
            print(f"\n[SERVER STATS] Players: {len(clients)} | "
                  f"Avg Latency: {avg:.1f}ms | "
                  f"Packet Loss: {loss_pct:.1f}% | "
                  f"Sent: {stats['packets_sent']} | "
                  f"Dropped: {stats['packets_dropped']}")
except KeyboardInterrupt:
    print("\n[SERVER STOPPED]")