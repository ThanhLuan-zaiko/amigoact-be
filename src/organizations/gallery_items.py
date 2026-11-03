"""Gallery rules that organization creation and the gallery routes share.

Kept apart from gallery.py, which imports the service, so the service and the
request schema can import these rules without a cycle.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy.orm import Session

from src.media import service as media_service
from src.models.organizations import OrganizationMedia

MAX_GALLERY_ITEMS = 10


def unique_asset_ids(asset_ids: Sequence[uuid.UUID]) -> list[uuid.UUID]:
    """Keep the first copy of each file, so a repeated id is one item."""
    return list(dict.fromkeys(asset_ids))


def attach_assets(
    db: Session,
    org_id: uuid.UUID,
    asset_ids: Sequence[uuid.UUID],
    user_id: uuid.UUID,
) -> None:
    """Add pictures and videos to a new organization. Does not commit.

    The caller commits together with the organization, so a rejected file
    leaves no organization behind.
    """
    for asset_id in unique_asset_ids(asset_ids):
        media_service.check_attachable(db, asset_id, user_id, allow_video=True)
        db.add(OrganizationMedia(org_id=org_id, asset_id=asset_id, added_by=user_id))
