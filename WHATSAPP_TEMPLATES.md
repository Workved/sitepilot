# WhatsApp Starter Templates

The 8 templates to create in **WhatsApp Manager -> Message templates -> Create template**.
The code (`backend/app/services/message_templates.py`) sends exactly these names and
fields, so copy them exactly.

## Settings for every template

| Setting | Value |
|---|---|
| Category | **Utility** |
| Type | Default (text only, no header, no buttons) |
| Language | **English** (`en`) - not English (US) |
| Variable type | **Number** (`{{1}}`, `{{2}}`, ...) |
| Name | Exactly as written below (lowercase, underscores) |

When Meta asks for **sample values**, use the samples given for each template.

Meta rules the bodies below already follow: a body must not start or end with a
variable, and variables are numbered in the order they appear.

---

## 1. `task_status_update`

Sent to the project's PM and Supervisor when a task changes status.

**Body**

```
SiteOps update for project {{1}}: task {{2}} has moved from {{3}} to {{4}}. Note: {{5}}. Open SiteOps for details.
```

| Variable | Field | Sample |
|---|---|---|
| `{{1}}` | Project name | Futurex Office |
| `{{2}}` | Task code and name | T003 - Flooring |
| `{{3}}` | Previous status | Ready |
| `{{4}}` | New status | In progress |
| `{{5}}` | Reason (or `-`) | Material delivered |

---

## 2. `task_approval_decision`

Sent when the PM approves or rejects a submitted task (Admin is copied).

**Body**

```
SiteOps: task {{1}} on project {{2}} has been {{3}}. Remarks: {{4}}. Open SiteOps for details.
```

| Variable | Field | Sample |
|---|---|---|
| `{{1}}` | Task code and name | T003 - Flooring |
| `{{2}}` | Project name | Futurex Office |
| `{{3}}` | Decision | Approved |
| `{{4}}` | Remarks (or `-`) | Finish quality is good |

---

## 3. `task_blocker_alert`

Sent when someone raises a blocker on a task.

**Body**

```
SiteOps alert: a blocker was raised on task {{1}} (project {{2}}). Type: {{3}}. Details: {{4}}. Please review it in SiteOps.
```

| Variable | Field | Sample |
|---|---|---|
| `{{1}}` | Task code and name | T003 - Flooring |
| `{{2}}` | Project name | Futurex Office |
| `{{3}}` | Blocker type | Material shortage |
| `{{4}}` | Description | Tiles not delivered yet |

---

## 4. `task_delay_recorded`

Sent when a delay is recorded on a task.

**Body**

```
SiteOps: task {{1}} on project {{2}} has a delay of {{3}} day(s) recorded. Responsibility: {{4}}. Please review it in SiteOps.
```

| Variable | Field | Sample |
|---|---|---|
| `{{1}}` | Task code and name | T003 - Flooring |
| `{{2}}` | Project name | Futurex Office |
| `{{3}}` | Delay in days | 2 |
| `{{4}}` | Responsibility | Vendor |

---

## 5. `task_vendor_assigned`

Sent to the vendor's primary contact when they are assigned a task. They reply on
WhatsApp to accept or decline.

**Body**

```
SiteOps: you have been assigned task {{1}} on project {{2}}. Reply ACCEPT {{3}} to accept this job, or reply DECLINE followed by the same code to decline.
```

| Variable | Field | Sample |
|---|---|---|
| `{{1}}` | Task code and name | T003 - Flooring |
| `{{2}}` | Project name | Futurex Office |
| `{{3}}` | Reply code | 1A2B3C4D |

---

## 6. `task_sla_overdue`

Daily reminder (06:30 IST) for a task that passed its due date and is still open.

**Body**

```
SiteOps reminder: task {{1}} on project {{2}} was due on {{3}} and is still open. Please update it in SiteOps today.
```

| Variable | Field | Sample |
|---|---|---|
| `{{1}}` | Task code and name | T003 - Flooring |
| `{{2}}` | Project name | Futurex Office |
| `{{3}}` | Due date | 05 Nov 2026 |

---

## 7. `external_approval_assigned`

Sent to the employee assigned an external approval (e.g. Fire NOC). They reply on
WhatsApp to accept or decline.

**Body**

```
SiteOps: you have been assigned the approval {{1}} for project {{2}}, due {{3}}. Reply GATEACCEPT {{4}} to accept, or reply GATEDECLINE followed by the same code to decline.
```

| Variable | Field | Sample |
|---|---|---|
| `{{1}}` | Approval name | Fire NOC |
| `{{2}}` | Project name | Futurex Office |
| `{{3}}` | Due date | 25 Dec 2026 |
| `{{4}}` | Reply code | A1B2C3D4 |

---

## 8. `project_broadcast_announcement`

Sent when an Admin sends a broadcast from the Broadcasts page.

**Body**

```
SiteOps announcement for project {{1}}: {{2}}. {{3}} - Sent by your SiteOps admin.
```

| Variable | Field | Sample |
|---|---|---|
| `{{1}}` | Project name | Futurex Office |
| `{{2}}` | Broadcast title | Site closed Saturday |
| `{{3}}` | Broadcast message | The site will be closed for inspection this Saturday. |

---

## Notes

- **Replies (ACCEPT / GATEACCEPT)** only work once Meta's webhook reaches the
  backend (Checkpoint 8). Locally that needs a public tunnel; on Render it works
  directly.
- **Meta may change the category** of a template (for example broadcast to
  Marketing). That still sends, but Marketing messages cost more and have stricter
  limits.
- **Every other notification** still uses its old template name, which does not
  exist in Meta yet, so those fail with a template error and are not retried.
  They get templates in Checkpoint 12.
- Changing a template's body or variables in Meta means it goes back for review,
  and the matching `variable_order` in `message_templates.py` must change with it.
