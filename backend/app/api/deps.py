"""Shared API dependencies."""

from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import User
from app.security import decode_session_token


def db_session(db: Session = Depends(get_db)) -> Session:
    return db


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("tagp_session")
    if not token:
        raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "Login required"})
    try:
        payload = decode_session_token(token)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "Session expired"})
    user = db.scalar(select_user(payload.get("sub")))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "Login required"})
    return user


def select_user(user_id: str | None):
    from sqlalchemy import select

    return select(User).options(joinedload(User.role)).where(User.id == user_id)


def require_role(*roles: str) -> Callable:
    def checker(user: User = Depends(current_user)) -> User:
        if user.role.name not in roles:
            raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "You do not have access to this action"})
        return user

    return checker


def client_ip(request: Request) -> str | None:
    if request.client:
        return request.client.host
    return None
