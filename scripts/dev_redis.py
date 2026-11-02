"""Local stand-in for Redis when Docker or a Redis install is not available.

Speaks the Redis protocol on localhost:6379, so the app uses it exactly like real Redis.
Data lives in memory and is lost when the process stops. Not for production.
"""
from fakeredis import TcpFakeServer

if __name__ == "__main__":
    print("Redis-compatible dev server on 127.0.0.1:6379 (Ctrl+C to stop)")
    TcpFakeServer(("127.0.0.1", 6379), server_type="redis").serve_forever()
