"""Command line: `python -m uniparent <command>` (or `docker exec -it uniparent uniparent <command>`).

  serve                                   run the web app (default)
  create-user <username> --role admin|parent [--name "Display Name"]
  set-password <username>
  list-users
  unblock-all                             escape hatch: clear every off/pause, pause all schedules, unblock managed devices
"""
import argparse
import asyncio
import getpass
import os
import sys

from . import auth
from .config import Settings
from .db import DB


def _password() -> str:
    pw = os.environ.get("UNIPARENT_PASSWORD") or getpass.getpass("Password (8+ characters): ")
    if not os.environ.get("UNIPARENT_PASSWORD") and getpass.getpass("Again: ") != pw:
        sys.exit("Passwords didn't match.")
    return pw


def main(argv=None):
    p = argparse.ArgumentParser(prog="uniparent")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("serve")
    cu = sub.add_parser("create-user")
    cu.add_argument("username")
    cu.add_argument("--role", choices=auth.ROLES, required=True)
    cu.add_argument("--name", default="")
    sp = sub.add_parser("set-password")
    sp.add_argument("username")
    sub.add_parser("list-users")
    sub.add_parser("unblock-all")
    a = p.parse_args(argv)
    s = Settings()

    if a.cmd in (None, "serve"):
        import uvicorn
        uvicorn.run("uniparent.main:app", host=os.environ.get("HOST", "0.0.0.0"),
                    port=int(os.environ.get("PORT", "8095")), proxy_headers=True, forwarded_allow_ips="*")
        return

    db = DB(s.db_path)
    if a.cmd == "create-user":
        try:
            auth.create_user(db, a.username, a.name, _password(), a.role)
        except Exception as e:
            sys.exit(f"Could not create user: {e}")
        print(f"Created {a.role} {a.username}.")
    elif a.cmd == "set-password":
        u = db.one("SELECT id FROM users WHERE username=?", (a.username,))
        if u is None:
            sys.exit("No such user.")
        auth.set_password(db, u["id"], _password())
        print("Password changed; that user's phones will need to sign in again.")
    elif a.cmd == "list-users":
        for u in db.q("SELECT username, display_name, role FROM users ORDER BY id"):
            print(f"{u['username']:<16} {u['role']:<7} {u['display_name']}")
    elif a.cmd == "unblock-all":
        from .service import Service
        from .unifi import UniFi

        async def run():
            unifi = UniFi(s.unifi_host, s.unifi_api_key, s.unifi_site, s.unifi_verify_tls)
            try:
                n = await Service(s, db, unifi).unblock_all("Command line")
            finally:
                await unifi.close()
            print(f"Unblocked {n} device(s); all offs, pauses and schedules cleared.")
        asyncio.run(run())


if __name__ == "__main__":
    main()
