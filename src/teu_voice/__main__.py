from __future__ import annotations

import argparse
import os
from ipaddress import IPv4Address, ip_address


def is_loopback_host(host: str) -> bool:
    return host.lower().rstrip(".") in {"127.0.0.1", "localhost", "::1"}


def is_private_lan_ipv4(host: str) -> bool:
    try:
        address = ip_address(host)
    except ValueError:
        return False
    return isinstance(address, IPv4Address) and address.is_private and not address.is_loopback


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tếu Voice Studio")
    parser.add_argument("--host", default=os.getenv("TEU_VOICE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("TEU_VOICE_PORT", "8765")))
    parser.add_argument("--reload", action="store_true", help="Tự tải lại khi sửa code")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not is_loopback_host(args.host) and not is_private_lan_ipv4(args.host):
        raise SystemExit(
            "Chỉ cho phép bind loopback hoặc một IPv4 private cụ thể; "
            "không dùng 0.0.0.0 hay IP public cho voice clone."
        )
    if is_private_lan_ipv4(args.host) and not os.getenv("TEU_VOICE_ACCESS_KEY"):
        raise SystemExit(
            "Chế độ LAN cần TEU_VOICE_ACCESS_KEY. Hãy chạy .\\run.ps1 để tạo khóa tạm."
        )
    # app.py is imported by Uvicorn after this point, so its Settings instance
    # receives the same exact host that Uvicorn binds.
    os.environ["TEU_VOICE_HOST"] = args.host
    import uvicorn

    uvicorn.run(
        "teu_voice.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
