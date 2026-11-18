"""Communication module: recipient resolution + send logic for `Broadcast`.

Recipient resolution reads the SAME sources Vendor Hub and project
membership already use (`V2ProjectMembership` for PM/Supervisor/Internal
Employee, `ProjectVendor` + `V2Vendor`/`V2VendorContact` for vendors) - no
new "who is on this project" concept is introduced.

Delivery is deliberately synchronous and simulated, mirroring this
codebase's existing `SandboxProviderAdapter` philosophy (see
`app/services/message_dispatch.py`'s header comment): no outbound network
call is made. A recipient with at least one contactable channel (WhatsApp
number or, for internal users, an email/in-app account) is marked 'sent'
immediately; one with none is marked 'skipped_no_contact'. Wiring a real
WhatsApp/email provider later only needs to change how a 'pending' row is
resolved - the data shape (channels, delivery_status) is already built for it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.broadcast_models import Broadcast, BroadcastRecipient, BroadcastTemplate
from app.config import settings
from app.execution_models import MessageDelivery, OutboxEvent
from app.models import EmployeeProfile, User
from app.project_models import V2Project, V2ProjectMembership
from app.routes.projects_v2 import add_audit
from app.services.message_dispatch import (
    SandboxProviderAdapter,
    WhatsAppProviderAdapter,
)
from app.services.message_templates import render_components, resolve
from app.services.outbox_scheduler import _build_adapter
from app.vendor_models import ProjectVendor, V2Vendor, V2VendorContact

GROUP_ROLE_LABEL = {
    "project_manager": "Project Manager",
    "site_supervisor": "Site Supervisor",
    "internal_employee": "Internal Employee",
}
INTERNAL_GROUPS = tuple(GROUP_ROLE_LABEL)
ALL_GROUPS = INTERNAL_GROUPS + ("vendor", "vendor_contact")
BROADCAST_EVENT_TYPE = "broadcast.message_dispatched"


def _default_whatsapp_adapter() -> WhatsAppProviderAdapter:
    return _build_adapter()


def _default_telegram_adapter() -> WhatsAppProviderAdapter:
    if settings.telegram_access_token:
        from app.services.telegram_provider import TelegramProviderAdapter

        return TelegramProviderAdapter()
    return SandboxProviderAdapter()


def _format_broadcast_text(broadcast: Broadcast, project_name: str) -> str:
    lines = [
        f"*{broadcast.title}*",
        f"Project: {project_name}",
    ]
    if broadcast.meeting_date:
        when = broadcast.meeting_date.isoformat()
        if broadcast.meeting_time:
            when = f"{when} {broadcast.meeting_time}"
        lines.append(f"When: {when}")
    elif broadcast.meeting_time:
        lines.append(f"Time: {broadcast.meeting_time}")
    if broadcast.location_or_link:
        lines.append(f"Location/Link: {broadcast.location_or_link}")
    if broadcast.agenda:
        lines.append(f"Agenda: {broadcast.agenda}")
    lines.append("")
    lines.append(broadcast.message_body)
    return "\n".join(lines)


def _internal_recipients(db: Session, project_id: uuid.UUID, project_role: str) -> list[dict]:
    rows = db.execute(
        select(User, EmployeeProfile.active_channel, EmployeeProfile.telegram_chat_id)
        .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
        .join(V2ProjectMembership, V2ProjectMembership.employee_id == EmployeeProfile.id)
        .where(
            V2ProjectMembership.project_id == project_id,
            V2ProjectMembership.project_role == project_role,
            V2ProjectMembership.ends_at.is_(None),
            User.active.is_(True),
        )
        .distinct()
    ).all()
    role_label = GROUP_ROLE_LABEL[project_role]
    results = []
    for user, active_channel, telegram_chat_id in rows:
        # U11 (docs/plans/2026-09-16-001-feat-telegram-messaging-channel-plan.md,
        # step 1): resolve the actual contactable channel from
        # `EmployeeProfile.active_channel` instead of inferring it purely
        # from phone presence. Internal users always have a portal account
        # (email is required at signup) - "no contact" only ever applies to
        # vendors below.
        if active_channel == "telegram" and telegram_chat_id:
            messaging_channel = ["telegram"]
        else:
            messaging_channel = ["whatsapp"] if user.phone else []
        channels = ["in_app", "email"] + messaging_channel
        results.append({
            "key": f"{project_role}:{user.id}", "recipient_type": project_role,
            "user_id": user.id, "vendor_id": None, "vendor_contact_id": None,
            "name": user.name, "role_label": role_label, "company_name": None,
            "phone": user.phone, "email": user.email, "channels": channels,
        })
    return results


def _vendor_recipients(db: Session, project_id: uuid.UUID) -> list[dict]:
    vendor_ids = db.scalars(
        select(ProjectVendor.vendor_id).where(
            ProjectVendor.project_id == project_id, ProjectVendor.ends_at.is_(None),
        )
    ).all()
    if not vendor_ids:
        return []
    vendors = db.scalars(
        select(V2Vendor)
        .where(V2Vendor.id.in_(vendor_ids), or_(V2Vendor.status.is_(None), V2Vendor.status == "active"))
        .order_by(V2Vendor.name)
    ).all()
    results = []
    for vendor in vendors:
        # U11 (step 2): `active_channel` lives on `V2VendorContact`, not
        # `V2Vendor` - resolve it from the vendor's primary contact instead
        # of the vendor's own phone/whatsapp fields. Looked up per-vendor
        # (not via a join) so a vendor with zero or more than one contact
        # flagged `is_primary` falls back to the vendor's own fields below,
        # matching today's behavior, rather than a join silently picking
        # one row or multiplying results.
        primary_contacts = db.scalars(
            select(V2VendorContact).where(V2VendorContact.vendor_id == vendor.id, V2VendorContact.is_primary.is_(True))
        ).all()
        primary_contact = primary_contacts[0] if len(primary_contacts) == 1 else None
        if primary_contact is not None:
            phone = primary_contact.whatsapp or primary_contact.phone
            if primary_contact.active_channel == "telegram" and primary_contact.telegram_chat_id:
                channels = ["telegram"] + (["email"] if vendor.email else [])
            else:
                channels = (["whatsapp"] if phone else []) + (["email"] if vendor.email else [])
        else:
            phone = vendor.whatsapp or vendor.phone
            channels = (["whatsapp"] if phone else []) + (["email"] if vendor.email else [])
        results.append({
            "key": f"vendor:{vendor.id}", "recipient_type": "vendor",
            "user_id": None, "vendor_id": vendor.id, "vendor_contact_id": None,
            "name": vendor.contact_person or vendor.name,
            "role_label": "Main Vendor" if vendor.engagement_type == "main" else "Sub-vendor",
            "company_name": vendor.name, "phone": phone, "email": vendor.email, "channels": channels,
        })
    return results


def _vendor_contact_recipients(db: Session, project_id: uuid.UUID) -> list[dict]:
    vendor_ids = db.scalars(
        select(ProjectVendor.vendor_id).where(
            ProjectVendor.project_id == project_id, ProjectVendor.ends_at.is_(None),
        )
    ).all()
    if not vendor_ids:
        return []
    rows = db.execute(
        select(V2VendorContact, V2Vendor)
        .join(V2Vendor, V2Vendor.id == V2VendorContact.vendor_id)
        .where(
            V2VendorContact.vendor_id.in_(vendor_ids),
            or_(V2Vendor.status.is_(None), V2Vendor.status == "active"),
        )
        .order_by(V2Vendor.name, V2VendorContact.name)
    ).all()
    results = []
    for contact, vendor in rows:
        # V2VendorContact carries no email column - only phone/whatsapp.
        phone = contact.whatsapp or contact.phone
        # U11 (step 3): same active_channel resolution as steps 1-2.
        if contact.active_channel == "telegram" and contact.telegram_chat_id:
            channels = ["telegram"]
        else:
            channels = ["whatsapp"] if phone else []
        results.append({
            "key": f"vendor_contact:{contact.id}", "recipient_type": "vendor_contact",
            "user_id": None, "vendor_id": vendor.id, "vendor_contact_id": contact.id,
            "name": contact.name, "role_label": "Vendor Contact", "company_name": vendor.name,
            "phone": phone, "email": None, "channels": channels,
        })
    return results


def resolve_group(db: Session, project_id: uuid.UUID, group: str) -> list[dict]:
    if group in INTERNAL_GROUPS:
        return _internal_recipients(db, project_id, group)
    if group == "vendor":
        return _vendor_recipients(db, project_id)
    if group == "vendor_contact":
        return _vendor_contact_recipients(db, project_id)
    raise HTTPException(400, f"Unknown recipient group '{group}'.")


def group_counts(db: Session, project_id: uuid.UUID) -> dict[str, int]:
    return {group: len(resolve_group(db, project_id, group)) for group in ALL_GROUPS}


def resolve_recipients(db: Session, project_id: uuid.UUID, groups: list[str]) -> list[dict]:
    unknown = set(groups) - set(ALL_GROUPS)
    if unknown:
        raise HTTPException(400, f"Unknown recipient group(s): {', '.join(sorted(unknown))}.")
    seen: dict[str, dict] = {}
    for group in groups:
        for recipient in resolve_group(db, project_id, group):
            seen.setdefault(recipient["key"], recipient)
    return list(seen.values())


def _status_from_recipients(recipients: list[dict] | list[BroadcastRecipient]) -> str:
    if not recipients:
        return "failed"
    if isinstance(recipients[0], dict):
        skipped = sum(1 for r in recipients if not r["channels"])
        if skipped == 0:
            return "sent"
        if skipped == len(recipients):
            return "failed"
        return "partially_failed"
    sent_count = sum(1 for r in recipients if r.delivery_status == "sent")
    if sent_count == len(recipients):
        return "sent"
    if sent_count == 0:
        return "failed"
    return "partially_failed"


def _ensure_broadcast_outbox_event(
    db: Session, broadcast: Broadcast, payload: dict,
) -> OutboxEvent | None:
    """Creates or retrieves the OutboxEvent for this broadcast when the
    outbox_events table is available in the current database schema."""
    key = f"broadcast:{broadcast.id}"
    try:
        with db.begin_nested():
            event = db.scalar(select(OutboxEvent).where(OutboxEvent.idempotency_key == key))
            if event is None:
                event = OutboxEvent(
                    event_type=BROADCAST_EVENT_TYPE,
                    aggregate_type="project",
                    aggregate_id=broadcast.project_id,
                    payload=payload,
                    idempotency_key=key,
                    status="dispatched",
                )
                db.add(event)
                db.flush()
            return event
    except OperationalError:
        return None


def _record_message_delivery(
    db: Session,
    outbox_event: OutboxEvent | None,
    *,
    employee_id: uuid.UUID | None,
    vendor_contact_id: uuid.UUID | None,
    recipient_phone: str,
    template: str,
    channel: str,
    status: str,
    provider: str = "sandbox",
    provider_message_id: str | None = None,
    failure_code: str | None = None,
    failure_reason: str | None = None,
) -> None:
    """Persists or updates a `MessageDelivery` row for the broadcast
    recipient when a valid recipient FK (`employee_id` or
    `vendor_contact_id`) and the `message_deliveries` table exist."""
    if outbox_event is None or (employee_id is None and vendor_contact_id is None):
        return
    try:
        with db.begin_nested():
            stmt = select(MessageDelivery).where(
                MessageDelivery.outbox_event_id == outbox_event.id,
                MessageDelivery.template == template,
            )
            if employee_id is not None:
                stmt = stmt.where(
                    MessageDelivery.recipient_employee_id == employee_id,
                    MessageDelivery.recipient_vendor_contact_id.is_(None),
                )
            else:
                stmt = stmt.where(
                    MessageDelivery.recipient_vendor_contact_id == vendor_contact_id,
                    MessageDelivery.recipient_employee_id.is_(None),
                )
            delivery = db.scalar(stmt)
            if delivery is None:
                delivery = MessageDelivery(
                    outbox_event_id=outbox_event.id,
                    recipient_employee_id=employee_id,
                    recipient_vendor_contact_id=vendor_contact_id,
                    recipient_phone=recipient_phone,
                    template=template,
                    channel=channel,
                    status=status,
                    attempt_count=1,
                    provider=provider,
                    provider_message_id=provider_message_id,
                    failure_code=failure_code,
                    failure_reason=failure_reason,
                )
                db.add(delivery)
            else:
                delivery.recipient_phone = recipient_phone
                delivery.channel = channel
                delivery.status = status
                delivery.attempt_count += 1
                delivery.provider = provider
                delivery.provider_message_id = provider_message_id
                delivery.failure_code = failure_code
                delivery.failure_reason = failure_reason
                db.add(delivery)
            db.flush()
    except (OperationalError, IntegrityError):
        return


def _dispatch_broadcast_recipients(
    db: Session,
    broadcast: Broadcast,
    project: V2Project | None,
    recipients: list[BroadcastRecipient],
    *,
    whatsapp_adapter: WhatsAppProviderAdapter | None = None,
    telegram_adapter: WhatsAppProviderAdapter | None = None,
) -> None:
    """Dispatches broadcast messages to eligible recipients using the shared
    WhatsApp / Telegram provider adapters, template registry, and delivery
    tracking infrastructure."""
    now_ts = datetime.now(timezone.utc)
    project_name = project.name if project else "Unknown project"
    spec = resolve(BROADCAST_EVENT_TYPE)
    event_payload = {
        "broadcast_id": str(broadcast.id),
        "project_id": str(broadcast.project_id),
        "project_name": project_name,
        "title": broadcast.title,
        "meeting_date": broadcast.meeting_date.isoformat() if broadcast.meeting_date else "",
        "meeting_time": broadcast.meeting_time or "",
        "location_or_link": broadcast.location_or_link or "",
        "agenda": broadcast.agenda or "",
        "message_body": broadcast.message_body,
    }
    components = render_components(spec, event_payload)
    whatsapp_payload = {**event_payload, "components": components, "language_code": spec.language}
    telegram_payload = {"text": _format_broadcast_text(broadcast, project_name)}

    outbox_event = _ensure_broadcast_outbox_event(db, broadcast, event_payload)
    adapters: dict[str, WhatsAppProviderAdapter] = {
        "whatsapp": whatsapp_adapter or _default_whatsapp_adapter(),
        "telegram": telegram_adapter or _default_telegram_adapter(),
    }

    for recipient in recipients:
        # Duplicate prevention: never re-send to a recipient already marked 'sent'.
        if recipient.delivery_status == "sent":
            continue

        employee_id: uuid.UUID | None = None
        vendor_contact_id: uuid.UUID | None = recipient.vendor_contact_id
        target_channel: str | None = None
        target_address: str = ""

        if recipient.user_id is not None:
            user = db.get(User, recipient.user_id)
            profile = db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == recipient.user_id))
            membership = (
                db.scalar(
                    select(V2ProjectMembership).where(
                        V2ProjectMembership.project_id == broadcast.project_id,
                        V2ProjectMembership.employee_id == profile.id,
                        V2ProjectMembership.ends_at.is_(None),
                    )
                )
                if profile is not None
                else None
            )
            if profile is not None:
                employee_id = profile.id
            if user is None or not user.active or profile is None or membership is None:
                recipient.delivery_status = "failed"
                recipient.delivered_at = None
                _record_message_delivery(
                    db,
                    outbox_event,
                    employee_id=employee_id,
                    vendor_contact_id=None,
                    recipient_phone=recipient.phone or (user.phone if user else "") or "",
                    template=spec.meta_template_name,
                    channel=(profile.active_channel if profile else None) or "whatsapp",
                    status="failed",
                    failure_code="recipient_offboarded" if (user is not None and not user.active) else "recipient_ineligible",
                    failure_reason="Recipient is inactive or no longer an active project member.",
                )
                continue

            # Telegram only when the person actually linked a chat - the same
            # rule `_internal_recipients` uses for the preview. Anyone else
            # (including Telegram-preferred but never connected) goes to
            # WhatsApp, the primary channel.
            if profile.active_channel == "telegram" and profile.telegram_chat_id:
                target_address = profile.telegram_chat_id
                target_channel = "telegram"
            else:
                target_address = recipient.phone or user.phone or ""
                if target_address:
                    target_channel = "whatsapp"
                elif "whatsapp" in (recipient.channels or []):
                    recipient.delivery_status = "skipped_no_contact"
                    recipient.delivered_at = None
                    _record_message_delivery(
                        db,
                        outbox_event,
                        employee_id=employee_id,
                        vendor_contact_id=None,
                        recipient_phone="",
                        template=spec.meta_template_name,
                        channel="whatsapp",
                        status="failed",
                        failure_code="missing_phone",
                        failure_reason="Recipient has no phone number on file.",
                    )
                    continue

        elif recipient.vendor_contact_id is not None:
            contact = db.get(V2VendorContact, recipient.vendor_contact_id)
            vendor = db.get(V2Vendor, contact.vendor_id) if contact else None
            mapping = (
                db.scalar(
                    select(ProjectVendor).where(
                        ProjectVendor.project_id == broadcast.project_id,
                        ProjectVendor.vendor_id == contact.vendor_id,
                        ProjectVendor.ends_at.is_(None),
                    )
                )
                if contact is not None
                else None
            )
            if contact is None or mapping is None or (vendor is not None and vendor.status not in (None, "active")):
                recipient.delivery_status = "failed"
                recipient.delivered_at = None
                continue

            if contact.active_channel == "telegram" and contact.telegram_chat_id:
                target_address = contact.telegram_chat_id
                target_channel = "telegram"
            else:
                target_address = recipient.phone or contact.whatsapp or contact.phone or ""
                if not target_address:
                    recipient.delivery_status = "skipped_no_contact"
                    recipient.delivered_at = None
                    continue
                target_channel = "whatsapp"

        else:
            # recipient_type == 'vendor'
            vendor = db.get(V2Vendor, recipient.vendor_id) if recipient.vendor_id else None
            mapping = (
                db.scalar(
                    select(ProjectVendor).where(
                        ProjectVendor.project_id == broadcast.project_id,
                        ProjectVendor.vendor_id == recipient.vendor_id,
                        ProjectVendor.ends_at.is_(None),
                    )
                )
                if recipient.vendor_id is not None
                else None
            )
            if vendor is None or mapping is None or vendor.status not in (None, "active"):
                recipient.delivery_status = "failed"
                recipient.delivered_at = None
                continue

            primary_contacts = db.scalars(
                select(V2VendorContact).where(
                    V2VendorContact.vendor_id == vendor.id,
                    V2VendorContact.is_primary.is_(True),
                )
            ).all()
            primary_contact = primary_contacts[0] if len(primary_contacts) == 1 else None
            if primary_contact is not None:
                vendor_contact_id = primary_contact.id

            if (
                primary_contact is not None
                and primary_contact.active_channel == "telegram"
                and primary_contact.telegram_chat_id
            ):
                target_address = primary_contact.telegram_chat_id
                target_channel = "telegram"
            else:
                target_address = (
                    recipient.phone
                    or (primary_contact.whatsapp or primary_contact.phone if primary_contact is not None else None)
                    or vendor.whatsapp
                    or vendor.phone
                    or ""
                )
                if target_address:
                    target_channel = "whatsapp"

        if target_channel in ("whatsapp", "telegram") and target_address:
            adapter = adapters[target_channel]
            send_payload = telegram_payload if target_channel == "telegram" else whatsapp_payload
            result = adapter.send(
                recipient_phone=target_address,
                template=spec.meta_template_name,
                payload=send_payload,
            )
            _record_message_delivery(
                db,
                outbox_event,
                employee_id=employee_id,
                vendor_contact_id=vendor_contact_id if employee_id is None else None,
                recipient_phone=target_address if target_channel == "whatsapp" else (recipient.phone or ""),
                template=spec.meta_template_name,
                channel=target_channel,
                status="sent" if result.ok else "failed",
                provider=getattr(adapter, "provider_name", "sandbox"),
                provider_message_id=result.provider_message_id,
                failure_code=result.failure_code,
                failure_reason=result.failure_reason,
            )
            if result.ok:
                recipient.delivery_status = "sent"
                recipient.delivered_at = now_ts
            else:
                recipient.delivery_status = "failed"
                recipient.delivered_at = None
        else:
            if recipient.channels and any(ch in ("in_app", "email") for ch in recipient.channels):
                recipient.delivery_status = "sent"
                recipient.delivered_at = now_ts
            else:
                recipient.delivery_status = "skipped_no_contact"
                recipient.delivered_at = None

    broadcast.status = _status_from_recipients(recipients)
    broadcast.sent_at = now_ts


def create_broadcast(
    db: Session, actor: User, project: V2Project, *,
    title: str, meeting_date, meeting_time: str | None, location_or_link: str | None,
    agenda: str | None, message_body: str, groups: list[str], excluded_keys: list[str],
    send_mode: str, scheduled_at,
    whatsapp_adapter: WhatsAppProviderAdapter | None = None,
    telegram_adapter: WhatsAppProviderAdapter | None = None,
) -> Broadcast:
    if not groups:
        raise HTTPException(422, "Select at least one recipient group.")
    if send_mode == "scheduled" and not scheduled_at:
        raise HTTPException(422, "A scheduled broadcast requires a scheduled date and time.")
    if send_mode == "now":
        scheduled_at = None

    excluded = set(excluded_keys or [])
    included = [r for r in resolve_recipients(db, project.id, groups) if r["key"] not in excluded]

    broadcast = Broadcast(
        project_id=project.id, title=title.strip(), meeting_date=meeting_date, meeting_time=meeting_time or None,
        location_or_link=location_or_link or None, agenda=agenda or None, message_body=message_body.strip(),
        recipient_groups=list(groups), send_mode=send_mode, scheduled_at=scheduled_at,
        status="scheduled" if send_mode == "scheduled" else _status_from_recipients(included),
        created_by=actor.id,
    )
    db.add(broadcast)
    db.flush()

    recipient_rows: list[BroadcastRecipient] = []
    for recipient in included:
        row = BroadcastRecipient(
            broadcast_id=broadcast.id, recipient_type=recipient["recipient_type"], user_id=recipient["user_id"],
            vendor_id=recipient["vendor_id"], vendor_contact_id=recipient["vendor_contact_id"], name=recipient["name"],
            role_label=recipient["role_label"], company_name=recipient["company_name"], phone=recipient["phone"],
            email=recipient["email"], channels=recipient["channels"],
            delivery_status="pending",
            delivered_at=None,
        )
        db.add(row)
        recipient_rows.append(row)
    db.flush()

    if send_mode == "now":
        _dispatch_broadcast_recipients(
            db, broadcast, project, recipient_rows,
            whatsapp_adapter=whatsapp_adapter, telegram_adapter=telegram_adapter,
        )

    add_audit(
        db, actor, project,
        "BROADCAST_SCHEDULED" if send_mode == "scheduled" else "BROADCAST_SENT",
        f"Broadcast \"{broadcast.title}\" {'scheduled' if send_mode == 'scheduled' else 'sent'} to {len(included)} recipient(s).",
        entity_type="broadcast", entity_id=broadcast.id,
    )
    db.commit()
    db.refresh(broadcast)
    return broadcast


def send_scheduled_broadcast(
    db: Session,
    actor: User,
    broadcast: Broadcast,
    *,
    whatsapp_adapter: WhatsAppProviderAdapter | None = None,
    telegram_adapter: WhatsAppProviderAdapter | None = None,
) -> Broadcast:
    if broadcast.status not in ("scheduled", "partially_failed", "failed"):
        raise HTTPException(409, "Only a scheduled or failed broadcast can be sent.")
    recipients = list(
        db.scalars(select(BroadcastRecipient).where(BroadcastRecipient.broadcast_id == broadcast.id)).all()
    )
    project = db.get(V2Project, broadcast.project_id)
    _dispatch_broadcast_recipients(
        db, broadcast, project, recipients,
        whatsapp_adapter=whatsapp_adapter, telegram_adapter=telegram_adapter,
    )

    add_audit(
        db, actor, project, "BROADCAST_SENT",
        f"Scheduled broadcast \"{broadcast.title}\" sent to {len(recipients)} recipient(s).",
        entity_type="broadcast", entity_id=broadcast.id,
    )
    db.commit()
    db.refresh(broadcast)
    return broadcast


# ---- serialization -----------------------------------------------------

def recipient_json(recipient: BroadcastRecipient) -> dict:
    return {
        "id": str(recipient.id), "recipient_type": recipient.recipient_type, "name": recipient.name,
        "role_label": recipient.role_label, "company_name": recipient.company_name, "phone": recipient.phone,
        "email": recipient.email, "channels": recipient.channels, "delivery_status": recipient.delivery_status,
        "delivered_at": recipient.delivered_at.isoformat() if recipient.delivered_at else None,
    }


def broadcast_summary_json(db: Session, broadcast: Broadcast) -> dict:
    project = db.get(V2Project, broadcast.project_id)
    creator = db.get(User, broadcast.created_by)
    recipient_count = db.scalar(
        select(func.count()).select_from(BroadcastRecipient).where(BroadcastRecipient.broadcast_id == broadcast.id)
    ) or 0
    return {
        "id": str(broadcast.id), "project_id": str(broadcast.project_id),
        "project_name": project.name if project else "Unknown project", "project_code": project.code if project else None,
        "title": broadcast.title, "meeting_date": broadcast.meeting_date.isoformat() if broadcast.meeting_date else None,
        "meeting_time": broadcast.meeting_time, "location_or_link": broadcast.location_or_link,
        "recipient_groups": broadcast.recipient_groups, "recipient_count": recipient_count,
        "send_mode": broadcast.send_mode, "scheduled_at": broadcast.scheduled_at.isoformat() if broadcast.scheduled_at else None,
        "status": broadcast.status, "created_by_name": creator.name if creator else "SiteOps user",
        "created_at": broadcast.created_at.isoformat(), "sent_at": broadcast.sent_at.isoformat() if broadcast.sent_at else None,
    }


def broadcast_detail_json(db: Session, broadcast: Broadcast) -> dict:
    recipients = db.scalars(
        select(BroadcastRecipient).where(BroadcastRecipient.broadcast_id == broadcast.id)
        .order_by(BroadcastRecipient.role_label, BroadcastRecipient.name)
    ).all()
    data = broadcast_summary_json(db, broadcast)
    data.update({
        "agenda": broadcast.agenda, "message_body": broadcast.message_body,
        "recipients": [recipient_json(item) for item in recipients],
        "channels_used": sorted({channel for item in recipients for channel in item.channels}),
        "delivery_summary": {
            "sent": sum(1 for item in recipients if item.delivery_status == "sent"),
            "pending": sum(1 for item in recipients if item.delivery_status == "pending"),
            "skipped_no_contact": sum(1 for item in recipients if item.delivery_status == "skipped_no_contact"),
            "failed": sum(1 for item in recipients if item.delivery_status == "failed"),
        },
    })
    return data


def template_json(template: BroadcastTemplate) -> dict:
    return {
        "id": str(template.id), "name": template.name, "title": template.title,
        "agenda": template.agenda, "message_body": template.message_body, "created_at": template.created_at.isoformat(),
    }
