"""Routes for the messenger: the inbox across organizations and the people to message."""

from fastapi import APIRouter

from src.auth.deps import CurrentPrincipal, Db
from src.chat import inbox
from src.chat.inbox_schemas import ContactList, InboxList

router = APIRouter(tags=["chat"])


@router.get("/chat/inbox")
def list_inbox(principal: CurrentPrincipal, db: Db) -> InboxList:
    return InboxList(items=inbox.inbox(db, principal.user.id))


@router.get("/chat/contacts")
def list_contacts(principal: CurrentPrincipal, db: Db) -> ContactList:
    return ContactList(items=inbox.contacts(db, principal.user.id))
