"""Local unauthenticated forward proxy for Playwright/Chromium.

This VM's egress proxy requires auth and silently drops unauthenticated
connections, which Chromium cannot handle (it needs a 407 to trigger
auth). This tiny forwarder listens on 127.0.0.1 without auth, injects
Proxy-Authorization, and chains to the upstream proxy from env.

Usage:
    python pw_proxy.py [port]        # runs forever; reads https_proxy env

Credentials are read from the environment and never printed.
"""
import asyncio
import base64
import os
import sys
import urllib.parse


def upstream():
    raw = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY") or ""
    u = urllib.parse.urlparse(raw)
    if not u.hostname:
        raise SystemExit("no https_proxy in env")
    token = ""
    if u.username:
        creds = f"{urllib.parse.unquote(u.username)}:{urllib.parse.unquote(u.password or '')}"
        token = "Basic " + base64.b64encode(creds.encode()).decode()
    return u.hostname, u.port or 3128, token


UP_HOST, UP_PORT, AUTH = upstream()


async def relay(reader, writer):
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def handle(client_r, client_w):
    try:
        # read request head
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = await client_r.read(4096)
            if not chunk:
                return
            head += chunk
            if len(head) > 65536:
                return
        header_end = head.find(b"\r\n\r\n") + 4
        headers = head[:header_end]
        rest = head[header_end:]
        lines = headers.decode("latin1").split("\r\n")
        method, target, ver = lines[0].split(" ", 2)

        up_r, up_w = await asyncio.open_connection(UP_HOST, UP_PORT)

        if method.upper() == "CONNECT":
            # target is host:port
            req = f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n"
            if AUTH:
                req += f"Proxy-Authorization: {AUTH}\r\n"
            req += "\r\n"
            up_w.write(req.encode())
            await up_w.drain()
            # read upstream response head
            resp = b""
            while b"\r\n\r\n" not in resp:
                chunk = await up_r.read(4096)
                if not chunk:
                    break
                resp += chunk
            client_w.write(resp)
            await client_w.drain()
            if not resp.startswith(b"HTTP/1.1 200") and not resp.startswith(b"HTTP/1.0 200"):
                up_w.close()
                return
            await asyncio.gather(relay(client_r, up_w), relay(up_r, client_w))
        else:
            # plain HTTP: absolute-URI request through upstream
            out_lines = [lines[0]]
            for ln in lines[1:]:
                if ln.lower().startswith("proxy-authorization:"):
                    continue
                out_lines.append(ln)
            if AUTH:
                out_lines.insert(1, f"Proxy-Authorization: {AUTH}")
            up_w.write(("\r\n".join(out_lines) + "\r\n").encode("latin1"))
            if rest:
                up_w.write(rest)
            await up_w.drain()
            # forward any request body then relay response
            await relay(up_r, client_w)
            up_w.close()
    except Exception:
        pass
    finally:
        try:
            client_w.close()
        except Exception:
            pass


async def main(port):
    server = await asyncio.start_server(handle, "127.0.0.1", port)
    print(f"forward proxy on 127.0.0.1:{port} -> {UP_HOST}:{UP_PORT}", flush=True)
    await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 8899))
