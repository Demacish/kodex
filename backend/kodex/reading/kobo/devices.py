"""The user's Kobo e-readers in the web client: one per Kobo key, with the
collection it syncs (the user's "Kobo" collection unless they choose
another) and when it last synced."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.collection import Collection
from app.models.user import User
from kodex.core.auth.models import ApiKey
from kodex.reading.kobo.api import device_for
from kodex.reading.models import KoboBook, KoboDevice

router = APIRouter(tags=["kobo"])


class KoboDeviceOut(BaseModel):
    key_id: int
    name: str
    collection_id: int | None
    collection_name: str | None
    books: int
    last_sync_at: dt.datetime | None


class KoboDeviceIn(BaseModel):
    collection_id: int | None


def _view(db: Session, key: ApiKey, device: KoboDevice) -> KoboDeviceOut:
    collection = db.get(Collection, device.collection_id) if device.collection_id is not None else None
    books = db.scalar(select(func.count()).where(KoboBook.device_id == device.id, KoboBook.removed.is_(False))) or 0
    return KoboDeviceOut(key_id=key.id, name=key.name, collection_id=device.collection_id,
                         collection_name=collection.name if collection else None, books=int(books),
                         last_sync_at=device.last_sync_at)  # fmt: skip


@router.get("/me/kobo", response_model=list[KoboDeviceOut])
def list_kobo_devices(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[KoboDeviceOut]:
    found = db.scalars(select(ApiKey).where(ApiKey.user_id == user.id, ApiKey.purpose == "kobo")
                       .order_by(ApiKey.created_at)).all()  # fmt: skip
    views = [_view(db, key, device_for(db, key, user)) for key in found]
    db.commit()
    return views


@router.put("/me/kobo/{key_id}", response_model=KoboDeviceOut)
def update_kobo_device(key_id: int, body: KoboDeviceIn, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)) -> KoboDeviceOut:  # fmt: skip
    """Which collection the device syncs; null syncs nothing."""
    key = db.get(ApiKey, key_id)
    if key is None or key.user_id != user.id or key.purpose != "kobo":
        raise HTTPException(status_code=404, detail="No such Kobo key")
    if body.collection_id is not None:
        collection = db.get(Collection, body.collection_id)
        if collection is None or collection.owner_user_id not in (None, user.id):
            raise HTTPException(status_code=404, detail="No such collection")
    device = device_for(db, key, user)
    device.collection_id = body.collection_id
    db.commit()
    return _view(db, key, device)
