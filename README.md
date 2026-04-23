# CN-UDP-Multiplayer-Project
Overview

This project implements a real-time multiplayer simulation using UDP sockets in Python. It demonstrates how modern multiplayer systems handle low-latency communication, packet loss, and synchronization.
A central server manages multiple clients, processes player inputs, and broadcasts game state updates. The client uses prediction and reconciliation techniques to reduce perceived lag.

Objectives
Understand UDP socket programming
Implement client-server architecture
Simulate real-time multiplayer interaction
Handle packet loss and unreliable communication
Measure latency and jitter

Key Concepts Implemented
1. UDP Communication
Connectionless protocol (no guarantees of delivery)
Fast but unreliable → suitable for real-time systems
2. Client-Side Prediction
Client predicts its own movement locally
Reduces input delay
3. Server Reconciliation
Server sends authoritative state
Client corrects its predicted position
4. Packet Loss Simulation
Server randomly drops packets
Helps test robustness
5. Latency & Jitter Tracking
RTT (Round Trip Time) measured
Jitter calculated from variations

Architecture
Server:
Accepts multiple clients
Maintains player states
Broadcasts updates at fixed tick rate
Simulates packet loss
Sends statistics to clients
Client:
Connects to server
Sends movement inputs (W/A/S/D)
Predicts local movement
Reconciles with server updates
Displays ping, jitter, and stats

Results & Observations
Low latency communication achieved using UDP
Packet loss does not break the system due to continuous updates
Client-side prediction ensures smooth gameplay
Reconciliation corrects inconsistencies from packet loss
Jitter and latency values remain within expected range
(As seen in screenshots and logs in the project report)

References
Python Socket Programming Documentation
RFC 768 – UDP Protocol
Real-Time Multiplayer Networking Concepts
