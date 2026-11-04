# SiteOps MVP Stabilization Test Checklist

Use this checklist before deployment. Do not add new features during this cycle; only log/fix bugs.

## 1. Startup

- [ ] Run database/app locally.
- [ ] Open app on desktop browser.
- [ ] Open app on real mobile phone using laptop IP.
- [ ] Confirm login page loads.

## 2. Authentication

- [ ] Login with default Super Admin.
- [ ] Logout from desktop sidebar.
- [ ] Logout from mobile user card.
- [ ] Change password flow works.
- [ ] Forgot password local token flow works.


## 3. Users and roles

- [ ] Super Admin creates Admin.
- [ ] Admin creates Project Manager.
- [ ] Admin creates Supervisor.
- [ ] User list shows correct role counts.
- [ ] Deactivate/reactivate user works.
- [ ] Password reset by Admin/Super Admin works.

## 4. Vendors

- [ ] Create vendor.
- [ ] Edit vendor.
- [ ] Delete vendor.
- [ ] Vendor appears in task assignment dropdown.

## 5. Projects and generated tasks

- [ ] Create project with PM and Supervisor.
- [ ] 45-day calendar is generated.
- [ ] Date selection works for Admin/PM.
- [ ] Daily tasks show due dates.
- [ ] PM/Admin can edit task instruction, due date, and vendor.

## 6. Supervisor mobile workflow

- [ ] Supervisor sees only today's and carried-forward tasks.
- [ ] Future tasks are hidden from Supervisor.
- [ ] Supervisor opens task detail drawer.
- [ ] Supervisor updates status.
- [ ] Supervisor adds site note.
- [ ] Supervisor uploads one proof image from mobile.
- [ ] Supervisor can mark delayed/blocked with reason.
- [ ] Delayed task remains visible next day / carried-forward list.

## 7. PM approval workflow

- [ ] PM sees submitted task in Approvals.
- [ ] PM sees supervisor note and proof preview.
- [ ] PM approves submitted task.
- [ ] Approved task becomes completed.
- [ ] PM rejects submitted task with reason.
- [ ] Rejected task returns to Supervisor for correction.

## 8. Responsive UI

- [ ] Super Admin desktop layout looks correct.
- [ ] Admin desktop layout looks correct.
- [ ] PM desktop layout looks correct.
- [ ] Supervisor mobile layout looks correct.
- [ ] PM mobile layout looks usable.
- [ ] Bottom mobile navigation does not overlap critical form buttons.

## 9. Deployment readiness

- [ ] `npm run lint` passes.
- [ ] `npm run build` passes.
- [ ] `docker compose build app` passes when Docker Desktop is running.
- [ ] README run instructions are accurate.
- [ ] Default password is changed before real deployment.