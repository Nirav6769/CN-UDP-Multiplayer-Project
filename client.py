import socket
import threading
import time
import json

HOST = "127.0.0.1"   # ← Change to server's hotspot IP (e.g. 192.168.x.x)
PORT = 5555

client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
client.bind(("0.0.0.0", 0))
client.settimeout(2.0)

# ─── Client State ──────────────────────────────────────────────────────────────
my_id = None
my_name = input("Enter your player name: ").strip() or "Player"

local_state = {       # Local predicted position (client-side prediction)
    "x": 0,
    "y": 0
}
server_state = {}     # Last known state of all players from server
client_seq = 0        # Sequence number for our outgoing packets
pending_moves = []    # Unacknowledged moves (for reconciliation)

# ─── Latency / Jitter Tracking ────────────────────────────────────────────────
latency_history = []
last_latency = 0.0
jitter = 0.0
stats_lock = threading.Lock()


def update_latency(new_latency_ms):
    """Track latency and compute jitter (variation between samples)."""
    global last_latency, jitter
    with stats_lock:
        latency_history.append(new_latency_ms)
        if len(latency_history) > 50:      # Keep last 50 samples
            latency_history.pop(0)

        # Jitter = mean absolute deviation from previous sample
        jitter = abs(new_latency_ms - last_latency)
        last_latency = new_latency_ms


def avg_latency():
    with stats_lock:
        if not latency_history:
            return 0.0
        return sum(latency_history) / len(latency_history)


# ─── Send Helpers ──────────────────────────────────────────────────────────────
def send(payload: dict):
    payload["client_time"] = time.time()
    try:
        client.sendto(json.dumps(payload).encode(), (HOST, PORT))
    except Exception as e:
        print(f"[ERROR] Send failed: {e}")


def ping_server():
    """Send periodic pings to measure raw latency."""
    while True:
        send({"type": "ping"})
        time.sleep(2)


# ─── Client-Side Prediction ────────────────────────────────────────────────────
def apply_move(dx, dy):
    """
    Immediately apply movement locally (client prediction),
    then send to server. Server will confirm or correct.
    """
    global client_seq
    client_seq += 1

    # Predict locally
    local_state["x"] = max(0, min(800, local_state["x"] + dx))
    local_state["y"] = max(0, min(600, local_state["y"] + dy))

    move = {
        "type": "move",
        "dx": dx,
        "dy": dy,
        "client_seq": client_seq,
        "predicted_x": local_state["x"],
        "predicted_y": local_state["y"]
    }

    # Buffer for reconciliation until server confirms
    pending_moves.append(move.copy())
    send(move)


def reconcile(server_x, server_y, acked_seq):
    """
    Server correction: update position to authoritative value,
    then re-apply any moves the server hasn't seen yet.
    """
    # Discard moves the server has already acknowledged
    remaining = [m for m in pending_moves if m["client_seq"] > acked_seq]
    pending_moves.clear()
    pending_moves.extend(remaining)

    # Reset to server-authoritative position
    local_state["x"] = server_x
    local_state["y"] = server_y

    # Re-apply pending (unconfirmed) moves
    for move in pending_moves:
        local_state["x"] = max(0, min(800, local_state["x"] + move["dx"]))
        local_state["y"] = max(0, min(600, local_state["y"] + move["dy"]))


# ─── Receive Loop ──────────────────────────────────────────────────────────────
def receive():
    global my_id
    while True:
        try:
            data, _ = client.recvfrom(4096)
            msg = json.loads(data.decode())
        except socket.timeout:
            continue
        except Exception:
            break

        msg_type = msg.get("type")
        server_time = msg.get("server_time", 0)

        # Track latency for all packets that carry server_time
        if server_time:
            latency_ms = (time.time() - server_time) * 1000
            update_latency(latency_ms)

        # ── Join confirmed ────────────────────────────────────────────────────
        if msg_type == "join_ack":
            my_id = msg["your_id"]
            print(f"\n[CONNECTED] Your ID: {my_id}")
            print(f"[SERVER] {msg['message']}")

        # ── Full game state update (from tick loop) ───────────────────────────
        elif msg_type == "state_update":
            server_state.update(msg.get("players", {}))
            # Silently update — don't spam terminal

        # ── Server corrects our position ──────────────────────────────────────
        elif msg_type == "position_correction":
            sx, sy = msg["x"], msg["y"]
            acked = msg.get("client_seq", -1)
            old_x, old_y = local_state["x"], local_state["y"]

            reconcile(sx, sy, acked)

            # Only print if there was a noticeable correction
            diff = abs(local_state["x"] - old_x) + abs(local_state["y"] - old_y)
            if diff > 1:
                print(f"\n[RECONCILE] Server corrected position → ({local_state['x']}, {local_state['y']})")

        # ── Pong (latency measurement) ────────────────────────────────────────
        elif msg_type == "pong":
            ct = msg.get("client_time", 0)
            if ct:
                rtt_ms = (time.time() - ct) * 1000
                update_latency(rtt_ms)
                print(f"\n[PING] RTT: {rtt_ms:.1f}ms  |  Avg: {avg_latency():.1f}ms  |  Jitter: {jitter:.1f}ms")

        # ── Chat message ──────────────────────────────────────────────────────
        elif msg_type == "chat":
            ct = msg.get("client_time", 0)
            latency_str = f"  [{(time.time()-ct)*1000:.0f}ms]" if ct else ""
            print(f"\n[{msg['from']}]: {msg['text']}{latency_str}")

        # ── Player joined / left ──────────────────────────────────────────────
        elif msg_type == "player_joined":
            print(f"\n[+] {msg['name']} joined. Players online: {msg['players_online']}")

        elif msg_type == "player_left":
            print(f"\n[-] {msg['name']} left. Players online: {msg['players_online']}")
            server_state.pop(msg["player_id"], None)

        # ── Server stats ──────────────────────────────────────────────────────
        elif msg_type == "server_stats":
            print(f"\n[SERVER STATS]")
            print(f"  Players Online : {msg['players_online']}")
            print(f"  Avg Latency    : {msg['avg_latency_ms']} ms")
            print(f"  Packets Sent   : {msg['packets_sent']}")
            print(f"  Packets Dropped: {msg['packets_dropped']}")


# ─── Command Loop ──────────────────────────────────────────────────────────────
def command_loop():
    print("\nCommands:")
    print("  w/a/s/d     - Move up/left/down/right")
    print("  chat <msg>  - Send chat message")
    print("  pos         - Show your current position")
    print("  players     - Show all players")
    print("  stats       - Show latency & jitter stats")
    print("  serverstats - Request stats from server")
    print("  quit        - Disconnect\n")

    while True:
        try:
            cmd = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not cmd:
            continue

        # Movement (client prediction + server send)
        elif cmd == "w":
            apply_move(0, -10)
            print(f"[MOVE] Predicted pos: ({local_state['x']}, {local_state['y']})")
        elif cmd == "s":
            apply_move(0, 10)
            print(f"[MOVE] Predicted pos: ({local_state['x']}, {local_state['y']})")
        elif cmd == "a":
            apply_move(-10, 0)
            print(f"[MOVE] Predicted pos: ({local_state['x']}, {local_state['y']})")
        elif cmd == "d":
            apply_move(10, 0)
            print(f"[MOVE] Predicted pos: ({local_state['x']}, {local_state['y']})")

        # Chat
        elif cmd.startswith("chat "):
            text = cmd[5:].strip()
            if text:
                send({"type": "chat", "text": text})

        # Show local position
        elif cmd == "pos":
            print(f"[POSITION] You: ({local_state['x']}, {local_state['y']})")

        # Show all players
        elif cmd == "players":
            if not server_state:
                print("[INFO] No player data yet.")
            for pid, p in server_state.items():
                marker = " ← YOU" if pid == my_id else ""
                print(f"  {p['name']} | Pos: ({p['x']},{p['y']}) | HP: {p['health']} | Score: {p['score']}{marker}")

        # Local latency stats
        elif cmd == "stats":
            print(f"\n[LOCAL STATS]")
            print(f"  Avg Latency : {avg_latency():.1f} ms")
            print(f"  Last Latency: {last_latency:.1f} ms")
            print(f"  Jitter      : {jitter:.1f} ms")
            print(f"  Samples     : {len(latency_history)}")
            if latency_history:
                print(f"  Min / Max   : {min(latency_history):.1f} / {max(latency_history):.1f} ms")

        # Server-side stats
        elif cmd == "serverstats":
            send({"type": "get_stats"})

        # Quit
        elif cmd == "quit":
            send({"type": "quit"})
            print("[DISCONNECTED]")
            break

        else:
            print("[?] Unknown command. Use w/a/s/d, chat <msg>, pos, players, stats, serverstats, quit")


# ─── Start ─────────────────────────────────────────────────────────────────────
send({"type": "join", "name": my_name})

threading.Thread(target=receive, daemon=True).start()
threading.Thread(target=ping_server, daemon=True).start()

command_loop()
client.close()