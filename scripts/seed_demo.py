"""Demo seed data (Section 15.2) - idempotent."""
import io
import random
from datetime import UTC, datetime, timedelta

from app.extensions import db
from app.models import Claim, Institution, Match, Report, ReportImage, User
from app.models.enums import (
    Category,
    ClaimStatus,
    Custody,
    InstitutionType,
    MatchStatus,
    ReportStatus,
    ReportType,
    Role,
)
from app.services.images import validate_and_process
from app.services.jobs import process_report
from app.services.storage import get_storage

DEMO_USERS = [
    ("Admin", "admin@traceback.local", "Admin@12345", Role.ADMIN, None),
    ("Staff One", "staff@traceback.local", "Staff@12345", Role.STAFF, 1),
    ("Alice Example", "alice@example.com", "User@12345", Role.USER, None),
    ("Bob Example", "bob@example.com", "User@12345", Role.USER, None),
    ("Carol Example", "carol@example.com", "User@12345", Role.USER, None),
]

DEMO_INSTITUTIONS = [
    ("NIT Uttarakhand Library", "nit-uttarakhand-library", InstitutionType.COLLEGE,
     "Temporary Campus, Gangohi Road, Aamwala Tarla, Dehradun", 30.4145, 77.9797),
    ("Dehradun Railway Station", "dehradun-railway-station", InstitutionType.RAILWAY,
     "Govind Nagar, Dehradun, Uttarakhand", 30.3149, 78.0322),
    ("Pacific Mall Dehradun", "pacific-mall-dehradun", InstitutionType.MALL,
     "Rajpur Road, Dehradun", 30.3782, 78.0762),
]

# (kind, category, title, description, private_details, days_ago, lat, lng, loc_text, inst_idx, custody, colour, label, pair_key)
# pair_key: same key on a lost+found report = SAME object (positive label).
# Unique 'neg-*' keys mark hard/easy distractors (all their pairs are negative).
DEMOS = [
    # kind, category, title, description, private_details, days_ago, lat, lng,
    # loc_text, inst_idx, custody, colour, image_label, pair_key
    # pair_key: lost+found sharing a key = SAME object (positive label).
    # Unique "neg-*" keys = distractors (every pair is a negative label).
    ("lost", "WALLETS_CARDS", "Blue leather wallet lost near library",
     "Lost my blue leather wallet somewhere around the library lawn. Contains student ID and some cash.",
     "Blue two-fold leather wallet, chip in left pocket, initials A.R. inside", 3, 30.4149, 77.9800,
     "Library lawn", 0, None, "midnightblue", "WALLET", "pair-wallet-blue"),
    ("found", "WALLETS_CARDS", "Blue wallet handed in at library desk",
     "Found a blue leather wallet on a bench near the library. Has an ID card inside, kept safe at the desk.",
     "Two-fold blue wallet with initials inside", 2, 30.4151, 77.9801, "Library bench", 0,
     "AT_INSTITUTION", "midnightblue", "WALLET", "pair-wallet-blue"),

    ("lost", "ELECTRONICS", "Black wireless earbuds case lost at station",
     "I dropped my small black wireless earbuds charging case on the platform yesterday evening.",
     "Earbuds case with a scratch on the lid and a star sticker", 10, 30.3150, 78.0325,
     "Platform 2", 1, None, "black", "EARBUDS", "pair-earbuds"),
    ("found", "ELECTRONICS", "Black earbuds case found on platform",
     "A black earbuds charging case was found on platform 2 yesterday night, handed to the enquiry office.",
     "Star sticker on the lid", 9, 30.3152, 78.0326, "Enquiry office", 1, "AT_INSTITUTION",
     "black", "EARBUDS", "pair-earbuds"),

    ("lost", "BOTTLES_LUNCHBOXES", "Steel water bottle lost in classroom",
     "Left my silver steel water bottle in room 204 after the afternoon lecture.",
     "Bottle has a dent and name tape inside cap", 5, 30.4140, 77.9790, "Room 204, academic block",
     0, None, "silver", "BOTTLE", "pair-bottle"),
    ("found", "BOTTLES_LUNCHBOXES", "Steel bottle handed to office",
     "A silver steel water bottle was left in a classroom and given to the department office.",
     "Dent near the bottom", 4, 30.4138, 77.9792, "Department office", 0, "AT_INSTITUTION",
     "silver", "BOTTLE", "pair-bottle"),

    ("lost", "KEYS", "Key bunch with red fob lost in mall",
     "Dropped my key bunch (two keys, red round fob) somewhere in the mall food court.",
     "Red silicone fob shaped like a heart", 7, 30.3780, 78.0760, "Food court, second floor",
     2, None, "red", "KEYS", "pair-keys"),
    ("found", "KEYS", "Keys with red fob at mall info desk",
     "Found a bunch of two keys with a red heart-shaped fob in the food court, deposited at info desk.",
     None, 6, 30.3781, 78.0761, "Information desk", 2, "AT_INSTITUTION", "red", "KEYS", "pair-keys"),

    ("lost", "CLOTHING", "Grey hoodie left at railway waiting room",
     "Forgot my grey hoodie in the upper-class waiting room at Dehradun station.",
     "Small tear on left cuff", 15, 30.3155, 78.0330, "Waiting room", 1, None, "gray", "HOODIE", "pair-hoodie"),
    ("found", "CLOTHING", "Grey hoodie in waiting room",
     "A grey hooded sweatshirt was found draped over a chair in the waiting room and kept with the attendant.",
     None, 14, 30.3156, 78.0331, "Attendant counter", 1, "AT_INSTITUTION", "gray", "HOODIE", "pair-hoodie"),

    # C2 hard distractors: same category, DIFFERENT items (labelled negative)
    ("lost", "WALLETS_CARDS", "Red canvas wallet lost at market",
     "Lost my red canvas wallet at Paltan bazaar market on Saturday evening.",
     "Red canvas wallet, button closure", 9, 30.3165, 78.0350, "Paltan bazaar",
     1, None, "red", "WALLET2", "neg-wallet-red"),
    ("found", "WALLETS_CARDS", "Brown leather wallet found at canteen",
     "A small brown leather wallet was found under a canteen table and handed in.",
     None, 11, 30.4136, 77.9789, "Canteen", 0, "AT_INSTITUTION", "brown", "WALLET3",
     "neg-wallet-brown"),

    # unmatched singles: every pair involving them is a negative
    ("lost", "SPORTS", "Tennis racket cover missing",
     "Misplaced my tennis racket cover bag near the mall entrance, black cover with white stripes.",
     None, 8, 30.3779, 78.0759, "Entrance", 2, None, "white", "RACKET", "neg-racket"),
    ("found", "BOOKS_STATIONERY", "Quantum physics textbook found",
     "A thick quantum mechanics textbook was found in the canteen and handed over.",
     None, 12, 30.4135, 77.9788, "Canteen", 0, "AT_INSTITUTION", "green", "BOOK", "neg-book"),
    ("found", "SPORTS", "Cricket ball found on field",
     "A red cricket ball was found on the ground after practice.",
     None, 20, 30.4130, 77.9780, "Sports ground", 0, "AT_INSTITUTION", "red", "BALL", "neg-ball"),
    ("lost", "DOCUMENTS_ID", "Bus pass lost downtown",
     "Lost my bus pass wallet folder near the bus stand, yellow folder.",
     None, 25, 30.3200, 78.0400, "Bus stand", 1, None, "yellow", "PASS", "neg-pass"),
]


def _placeholder_image(colour, label, size=(320, 320)):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", size, colour)
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=48)
    except TypeError:
        font = ImageFont.load_default()
    d.rectangle([size[0] * 0.2, size[1] * 0.4, size[0] * 0.8, size[1] * 0.6], fill="white")
    d.text((size[0] * 0.22, size[1] * 0.44), label[:9], fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def run_seed(app):
    # D2: demo data is for development/demos only — never in production.
    if app.config.get("APP_CONFIG", "") == "production" and not __import__("os").environ.get("ALLOW_SEED_IN_PRODUCTION"):
        raise RuntimeError("flask seed-demo refuses to run when APP_CONFIG=production")
    created = {"users": 0, "institutions": 0, "reports": 0}
    if User.query.filter_by(email="admin@traceback.local").first():
        return "already seeded"

    # institutions
    insts = []
    for name, slug, itype, addr, lat, lng in DEMO_INSTITUTIONS:
        inst = Institution(name=name, slug=slug, institution_type=itype, address=addr,
                           latitude=lat, longitude=lng, verified=True)
        db.session.add(inst)
        insts.append(inst)
        created["institutions"] += 1
    db.session.flush()

    users = []
    for name, email, pw, role, inst_idx in DEMO_USERS:
        u = User(name=name, email=email, role=role,
                 institution_id=insts[inst_idx - 1].id if inst_idx else None)
        u.set_password(pw)
        db.session.add(u)
        users.append(u)
        created["users"] += 1
    db.session.flush()

    random.seed(42)
    storage = get_storage(app)
    reports = []
    for (kind, category, title, desc, private, days_ago, lat, lng, loc,
         inst_idx, custody, colour, label, pair_key) in DEMOS:
        owner = users[2 + (len(reports) % 3)]  # alice/bob/carol rotate
        r = Report(
            user_id=owner.id,
            institution_id=insts[inst_idx - 1].id if inst_idx is not None else None,
            report_type=ReportType.LOST if kind == "lost" else ReportType.FOUND,
            category=Category(category),
            title=title, description=desc, private_details=private,
            latitude=lat, longitude=lng, location_text=loc,
            incident_date=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days_ago),
            custody=Custody(custody) if custody else None,
            status=ReportStatus.ACTIVE,
            processing_status="PENDING",
        )
        db.session.add(r)
        db.session.flush()
        data = _placeholder_image(colour, label)
        meta = validate_and_process(data, f"{label.lower()}.png",
                                    max_mb=app.config["MAX_IMAGE_MB"])
        key = f"{datetime.now(UTC).replace(tzinfo=None):%Y}/{datetime.now(UTC).replace(tzinfo=None):%m}/seed-{len(reports)}.jpg"
        storage.save(meta["data"], key)
        img = ReportImage(report=r, storage_key=key, mime_type="image/jpeg",
                          width=meta["width"], height=meta["height"],
                          size_bytes=meta["size_bytes"], position=0)
        db.session.add(img)
        reports.append(r)
        created["reports"] += 1
    db.session.commit()

    # run matching synchronously for all reports
    for r in reports:
        process_report(r.id)

    # write labelled pairs for scripts/evaluate_matching.py (C2): positives
    # come from the explicit pair_key; negatives are every other LOST x FOUND
    # combination within the same category (hard distractors) plus a sample of
    # cross-category combinations (easy negatives).
    import csv
    import os
    labels_path = os.path.join(os.path.dirname(__file__), "labels.csv")
    key_of = {}
    for (kind, category, title, desc, private, days_ago, lat, lng, loc,
         inst_idx, custody, colour, label, pair_key) in DEMOS:
        key_of[title] = pair_key
    with open(labels_path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["lost_id", "found_id", "is_same_item"])
        losts = [r for r in reports if r.report_type == ReportType.LOST]
        founds = [r for r in reports if r.report_type == ReportType.FOUND]
        n_easy = 0
        for l in losts:
            for f in founds:
                same_item = key_of[l.title] == key_of[f.title]
                same_cat = l.category == f.category
                if same_item:
                    writer.writerow([l.id, f.id, 1])
                elif same_cat:
                    writer.writerow([l.id, f.id, 0])  # hard negative
                elif n_easy < 12:  # cap easy cross-category negatives
                    writer.writerow([l.id, f.id, 0])
                    n_easy += 1

    _create_sample_claims(reports, users, created)
    db.session.commit()
    return created


def _create_sample_claims(reports, users, created):
    """One pending claim, one completed recovery, one disputed claim."""
    # pick the wallet pair
    lost_wallet = next(r for r in reports if r.report_type == ReportType.LOST and r.category == Category.WALLETS_CARDS)
    found_wallet = next(r for r in reports if r.report_type == ReportType.FOUND and r.category == Category.WALLETS_CARDS)
    wallet_match = Match.query.filter_by(lost_report_id=lost_wallet.id,
                                         found_report_id=found_wallet.id).first()
    if wallet_match and not Claim.query.filter_by(match_id=wallet_match.id).first():
        claim = Claim(match_id=wallet_match.id, claimant_id=lost_wallet.user_id,
                      report_id=found_wallet.id,
                      claim_details="It is my wallet - blue leather, initials A.R. stitched inside, "
                                    "student ID with my photo, Rs 350 cash.",
                      verification_status=ClaimStatus.PENDING)
        db.session.add(claim)
        wallet_match.status = MatchStatus.CLAIMED
        found_wallet.status = ReportStatus.CLAIM_PENDING
        created["claims"] = 1

    # bottle pair -> completed recovery
    lost_bottle = next(r for r in reports if r.report_type == ReportType.LOST and r.category == Category.BOTTLES_LUNCHBOXES)
    found_bottle = next(r for r in reports if r.report_type == ReportType.FOUND and r.category == Category.BOTTLES_LUNCHBOXES)
    bottle_match = Match.query.filter_by(lost_report_id=lost_bottle.id,
                                         found_report_id=found_bottle.id).first()
    if bottle_match and not Claim.query.filter_by(match_id=bottle_match.id).first():
        claim = Claim(match_id=bottle_match.id, claimant_id=lost_bottle.user_id,
                      report_id=found_bottle.id,
                      claim_details="My steel bottle with a dent near the bottom and a name tape inside the cap.",
                      verification_status=ClaimStatus.COMPLETED,
                      review_note="Details match private description.",
                      handed_over_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=3),
                      received_confirmed_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=3))
        db.session.add(claim)
        bottle_match.status = MatchStatus.CONFIRMED
        lost_bottle.status = ReportStatus.RECOVERED
        lost_bottle.recovered_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=3)
        found_bottle.status = ReportStatus.RECOVERED
        found_bottle.recovered_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=3)

    # earbuds pair -> rejected then disputed
    lost_buds = next(r for r in reports if r.report_type == ReportType.LOST and r.category == Category.ELECTRONICS)
    found_buds = next(r for r in reports if r.report_type == ReportType.FOUND and r.category == Category.ELECTRONICS)
    buds_match = Match.query.filter_by(lost_report_id=lost_buds.id,
                                       found_report_id=found_buds.id).first()
    if buds_match and not Claim.query.filter_by(match_id=buds_match.id).first():
        claim = Claim(match_id=buds_match.id, claimant_id=lost_buds.user_id,
                      report_id=found_buds.id,
                      claim_details="Those earbuds are mine, white case.",
                      verification_status=ClaimStatus.DISPUTED,
                      review_note="Claim description did not match (white case vs black).")
        db.session.add(claim)
        created["disputed"] = 1
