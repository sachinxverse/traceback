# TRACEBACK — UI Audit (Part A)

## Method
- **A1 buttons/links:** Playwright crawl of every page for visitor / USER / STAFF / ADMIN
  at 375 px and 1280 px (script enumerated every `a[href]`, `button`, `[role=button]`,
  `input[type=submit]`); every internal link was then checked with a real HTTP request
  (16 distinct hrefs, all returned 200). JS-bound buttons were cross-checked against the
  bindings in `static/js/*.js`. A second Playwright pass at the end of Part D re-verified
  the final state.
- **A2 hard-coded data:** repo-wide grep for `localhost`/`127.0.0.1`, `href="#"`,
  `javascript:void(0)`, demo credentials, sample numbers, magic numbers.
- **A3 missing pages:** spec §11.3 route list compared with `app/web/routes.py`.

## A1. Button & link inventory

Legend: WORKS = verified action (navigation / real API call / working control).
Every row below was verified by the Playwright crawl or code trace; final status
after Part D is on the right.

| Page | Element | Selector | Expected action | Actual result | Audit status | Final (after D) |
|---|---|---|---|---|---|---|
| all | Skip to main content | `a.skip-link` | jump to `#main` | focus jumps to `<main id="main">` | WORKS | WORKS |
| all | Brand → home | `.navbar-brand` | navigate `/` | navigates | WORKS | WORKS |
| all | Report Lost / Found | nav links | navigate | navigates | WORKS | WORKS (user portal only) |
| all | Account menu | `a[data-bs-toggle=dropdown]` (`href="#"`) | open dropdown | Bootstrap dropdown opens (aria-haspopup, JS managed) | WORKS | WORKS |
| all | Theme toggle | `#theme-toggle` | cycle light/dark/system | sets `data-theme` + localStorage | WORKS | WORKS |
| all | Logout | `#logout-btn` | POST `/auth/logout`, redirect `/` | real API call, cookies cleared | WORKS | WORKS |
| all | Notification bell | `#notif-btn` | open notification dropdown | fetches `/notifications/unread-count`, opens panel | WORKS | WORKS |
| `/` | Find my item | `a.btn-amber` | navigate `/report/lost` | navigates | WORKS | WORKS |
| `/` | I found something | `a.btn-primary` | navigate `/report/found` | navigates | WORKS | WORKS |
| `/` | How it works | ghost button | navigate | navigates | WORKS | WORKS |
| `/` | View directory | `a.btn-found` | navigate `/institutions` | navigates | WORKS | WORKS |
| `/` | Institution card | `a.inst-card` | navigate `/i/{slug}` | navigates | WORKS | WORKS |
| `/` | CTA band buttons | CTAs | navigate report forms | navigate | WORKS | WORKS |
| `/institutions` | search input | `#inst-search-input` | debounced search via `/api/v1/institutions` | real API, grid re-renders | WORKS | WORKS |
| `/institutions` | Report lost/found here | per-card links | navigate with `?institution=` | navigate | WORKS | WORKS |
| `/login` | Continue | `#login-form submit` | login → `/dashboard` | real login flow | WORKS | WORKS (becomes 2-step OTP in C) |
| `/register` | Create account | `#register-form submit` | register → `/dashboard` | real API | WORKS | WORKS (ends in OTP step in C) |
| `/register`,`/login` | show password | `[data-toggle-pw]` | toggle visibility | toggles + aria-pressed | WORKS | WORKS |
| `/dashboard` | Lost/Found tabs | `data-bs-toggle=tab` | switch list | Bootstrap tabs | WORKS | WORKS |
| `/dashboard` | Open → | per-report link | navigate report | navigates | WORKS | WORKS |
| `/dashboard` | Report Lost/Found KPI buttons | links | navigate report forms | navigate | WORKS | WORKS |
| `/dashboard` | My claims / Browse / Notifications | quick links | navigate | navigate | WORKS | WORKS |
| `/report/*` | category cells | `.category-cell` | select category | keyboard + click select, aria-selected | WORKS | WORKS |
| `/report/*` | dropzone | `#dropzone` | open file picker | opens picker, previews | WORKS | WORKS |
| `/report/*` | map + search + use-my-location | `#geocode-btn`, `#geo-loc-btn` | geocode via backend proxy | real Nominatim proxy, pin set | WORKS | WORKS |
| `/report/*` | stepper Next/Back/Submit | `#step-next/#step-back/#submit-btn` | wizard nav, submit | validation + real POST | WORKS | WORKS |
| `/reports/{id}` | Close report / Re-match | `#close-btn`, `#rematch-btn` | POST close/rematch | real API + reload | WORKS | WORKS |
| `/reports/{id}` | carousel prev/next | `#img-prev`, `#img-next` | cycle images | cycles | WORKS | WORKS |
| `/reports/{id}` | Dismiss (match card) | `.dismiss-btn` | POST `/matches/{id}/dismiss` | real API | WORKS | WORKS |
| `/matches/{id}` | Submit claim | claim form | POST claim | real API | WORKS | WORKS |
| `/claims` | tabs My/Incoming | `data-bs-toggle=tab` | switch | Bootstrap tabs | WORKS | WORKS |
| `/claims/{id}` | Approve / Reject / hand over / confirm / withdraw | `button[data-action]` | claim transitions | real API (e2e-tested) | WORKS | WORKS |
| `/claims/{id}` | message send | `#send-btn` | POST message | real API | WORKS | WORKS |
| `/browse` | filter form | form submit | server-side filter | GET filter | WORKS | WORKS |
| `/notifications` | Mark all read | `#read-all` | POST read-all | real API + reload | WORKS | WORKS |
| `/profile` | Save changes / Update password | forms | PATCH me / change pw | real API | WORKS | WORKS (change-pw gains OTP in C) |
| `/admin` | KPI cards + charts | Chart.js | real `/admin/analytics/*` | real queries | WORKS | WORKS |
| `/admin` | heatmap Apply | `#hm-apply` | reload heatmap | real API | WORKS | WORKS |
| `/admin/reports` | search form | `#filter-form` | server filter | real API | WORKS | WORKS |
| `/admin/reports` | Remove → modal → confirm | `.remove-btn`, `#reason-confirm` | POST remove w/ reason | real API + audit log | WORKS | WORKS |
| `/admin/reports` | Restore | `.restore-btn` | POST restore | real API | WORKS | WORKS |
| `/admin/claims` | All/Pending/Disputed tabs | `a[data-status]` (`href="#"`) | filter table | JS-bound, real API | WORKS | WORKS (tab links rewritten to buttons in D) |
| `/admin/users` | search | `#user-q` | server search | real API | WORKS | WORKS |
| `/admin/users` | Edit | `.edit-user` | PATCH role/institution | real API (prompt-based; replaced by modal in D) | BROKEN-UX | WORKS (modal) |
| `/admin/users` | **Create staff/admin account** | — | create account | **did not exist** | MISSING | WORKS (modal, C.6/B1.6) |
| `/admin/institutions` | Download QR | `a[download]` | download QR PNG | real PNG endpoint | WORKS | WORKS |
| `/admin/institutions` | Edit institution | `.edit-inst` | open modal | opens prefilled | WORKS | WORKS |
| `/admin/institutions` | **Verified checkbox** | `#inst-verified` | PATCH verified | **JS `inst-save` never sent `verified`; state not prefilled** | DUMMY | WORKS |
| `/admin/audit` | table | — | display log | real query | WORKS | WORKS |
| `/staff` (staff user) | whole page | — | staff dashboard | **route did not exist → 404 for staff** | MISSING | WORKS (new `/staff`) |
| Leaflet map | zoom +/- | `a.leaflet-control-zoom-in/out` (`href="#"`) | zoom | Leaflet-managed control | WORKS | WORKS |

Removed elements: none needed to be removed — every DUMMY/MISSING row was
**implemented for real** (admin-claims tab links → real filter buttons with
`type="button"`; institutions verified toggle wired; users Edit → proper modal;
Create staff/admin modal added; `/staff` portal added).

## A2. Hard-coded data inventory

| # | Location | What was hard-coded | Where it comes from now |
|---|---|---|---|
| 1 | `app/api/institutions.py` (QR URL builder) | fallback literal `"http://localhost:5000"` | config `BASE_URL` only (no localhost fallback in code) |
| 2 | `app/static/js/map.js`, `admin.js` (×4) | default map centre `[30.0668, 79.0193]` | `/api/v1/meta` (`map_default_center`), injected once per page |
| 3 | `app/api/auth.py` | `LOGIN_MAX_FAILURES=5`, `LOGIN_WINDOW_SECONDS=900`, `LOGIN_LOCKOUT_SECONDS=900` | config: `LOGIN_MAX_FAILURES`, `LOGIN_LOCKOUT_WINDOW_SECONDS`, `LOGIN_LOCKOUT_SECONDS` |
| 4 | `app/api/auth.py` (new OTP code) | OTP expiry/attempts/resend/rate limits | config: `OTP_EXPIRES_SECONDS=300`, `OTP_MAX_ATTEMPTS=5`, `OTP_RESEND_COOLDOWN=30`, `OTP_MAX_RESENDS=3`, `OTP_HOURLY_LIMIT=5`, plus `OTP_CODE_LENGTH`, `OTP_DEV_ECHO`, `OTP_SENDER` |
| 5 | `app/static/js/admin.js` | chart colours `#D97706`/`#1D4ED8`/`#0D9488` | kept: presentational constants mirroring `tokens.css` (not business thresholds); noted as accepted |
| 6 | index page counters | server-rendered DB queries | still DB, **plus** new cached `GET /api/v1/stats/public` (5-min cache) used by the page |
| 7 | categories duplicated as literals in templates | Category enum | still from the enum server-side; JS now reads `GET /api/v1/meta` (`categories`, `institution_types`, `statuses`) |
| 8 | demo accounts | `scripts/seed_demo.py` only | unchanged (allowed by spec); `seed-demo` now **refuses to run in production**; no credentials on any page |
| 9 | `BASE_URL=http://localhost:5000` in `.env.example` | example value | documented as an example requiring change; code never defaults to localhost |
| 10 | institutions page type labels | `.replace('_',' ')` mapping | served by `/api/v1/meta` `institution_types` for JS-rendered lists |

Search results at audit time (documented for evidence): `grep -rn "localhost\|127.0.0.1" app/`
returned exactly one hit (item 1) outside comments; `href="#"` hits were the skip link,
Bootstrap dropdown toggles, Bootstrap tab links and the admin-claims filter tabs (item
rewritten in D); demo credentials appear only in `scripts/seed_demo.py`.

## A3. Missing / partially built pages (spec §11.3 vs routes)

| Spec route | Status at audit | Action taken |
|---|---|---|
| `/staff` staff dashboard (B1.8) | **missing** | new `/staff` portal (Part B) |
| Admin > Users: create staff/admin account (B1.6) | **missing** | new modal + `POST /api/v1/admin/users` (Part B/D) |
| `/api/v1/stats/public` (D2) | missing | implemented, 5-min cache |
| `/api/v1/meta` (D2) | missing | implemented |
| Institutions verified toggle | partially built | wired end-to-end |
| Forgot password | **missing** | new flow with OTP (Part C) |
| Separate portals + OTP | **missing** | Parts B + C |

No other §11.3 page was missing.
