"""Create a local API user and token after migrations."""

import argparse
import secrets

from sqlalchemy import select

from .db import SessionLocal
from .models import User
from .service import token_digest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    token = secrets.token_urlsafe(32)
    with SessionLocal.begin() as session:
        if session.scalar(select(User).where(User.name == args.name)):
            parser.error("user already exists")
        session.add(User(name=args.name, token_hash=token_digest(token)))
    print(f"API token for {args.name} (shown once): {token}")


if __name__ == "__main__":
    main()
