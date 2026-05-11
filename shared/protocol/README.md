# Shared Protocol

Protocol files in this directory describe the messages exchanged between the
ESP32-P4 firmware and the laptop client.

The project starts with protocol version `1`.

- Video is transported over HTTP endpoints.
- Commands and status are transported over WebSocket JSON.
- Message examples live in `shared/examples`.
