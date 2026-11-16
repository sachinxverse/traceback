"""Flask CLI commands (Section 15.3)."""
from datetime import UTC, datetime, timedelta

import click


def register(app):
    @app.cli.command("init-db")
    def init_db():
        """Apply Alembic migrations (B3: upgrade() only, fails loudly)."""
        from flask_migrate import upgrade
        with app.app_context():
            upgrade()  # raises and exits non-zero on failure
            click.echo("Migrations applied.")

    @app.cli.command("create-admin")
    @click.option("--email", required=True)
    @click.option("--name", required=True)
    @click.password_option(help="Password (min 8 chars, 1 letter + 1 digit)")
    def create_admin(email, name, password):
        """Create an ADMIN user."""
        from app.extensions import db
        from app.models import User
        from app.models.enums import Role
        if len(password) < 8 or not any(c.isdigit() for c in password) \
                or not any(c.isalpha() for c in password):
            raise click.ClickException("Password must be 8+ chars with a letter and a digit")
        with app.app_context():
            if User.query.filter_by(email=email.lower()).first():
                raise click.ClickException("Email already exists")
            user = User(name=name, email=email.lower(), role=Role.ADMIN)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            click.echo(f"Admin created: {email}")

    @app.cli.command("seed-demo")
    @click.option("--reset", is_flag=True)
    def seed_demo(reset):
        """Load demo data (Section 15.2); idempotent unless --reset.
        D2: refuses to run when APP_CONFIG=production."""
        from app.extensions import db
        with app.app_context():
            if reset:
                wipe(db)
                click.echo("Database wiped.")
            from scripts.seed_demo import run_seed
            created = run_seed(app)
            click.echo(f"Seed complete: {created}")

    @app.cli.command("purge-otp")
    def purge_otp():
        """Delete expired OTP challenges (Part C4)."""
        from app.extensions import db
        from app.services.otp import purge_expired
        with app.app_context():
            n = purge_expired()
            click.echo(f"Purged {n} expired OTP challenges.")

    @app.cli.command("reindex")
    def reindex():
        """Recompute all embeddings and matches."""
        from app.services.jobs import reindex_all
        reindex_all(app)
        click.echo("Reindex complete.")

    @app.cli.command("expire-reports")
    def expire_reports():
        """ACTIVE reports older than REPORT_RETENTION_DAYS -> EXPIRED."""
        from datetime import datetime

        from app.extensions import db
        from app.models import Match, Report
        from app.models.enums import MatchStatus, ReportStatus
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=app.config["REPORT_RETENTION_DAYS"])
        with app.app_context():
            old = Report.query.filter(Report.status == ReportStatus.ACTIVE,
                                      Report.created_at < cutoff).all()
            for r in old:
                r.status = ReportStatus.EXPIRED
                for m in Match.query.filter(
                        (Match.lost_report_id == r.id) | (Match.found_report_id == r.id)).all():
                    if m.status == MatchStatus.SUGGESTED:
                        m.status = MatchStatus.EXPIRED
            db.session.commit()
            click.echo(f"Expired {len(old)} reports.")

    @app.cli.command("purge-orphans")
    def purge_orphans():
        """Delete upload files not referenced by any DB row."""
        import os

        from app.models import ClaimImage, ReportImage
        with app.app_context():
            referenced = {i.storage_key for i in ReportImage.query.all()}
            referenced |= {i.storage_key for i in ClaimImage.query.all()}
            root = app.config["UPLOAD_DIR"]
            removed = 0
            for dirpath, _, filenames in os.walk(root):
                for fn in filenames:
                    full = os.path.join(dirpath, fn)
                    key = os.path.relpath(full, root).replace("\\", "/")
                    if key not in referenced:
                        try:
                            os.remove(full)
                            removed += 1
                        except OSError:
                            pass
            click.echo(f"Removed {removed} orphan files.")

    @app.cli.command("purge-old-messages")
    def purge_old_messages():
        """Delete messages on completed claims older than 30 days."""
        from app.extensions import db
        from app.models import Claim, Message
        from app.models.enums import ClaimStatus
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30)
        with app.app_context():
            match_ids = [c.match_id for c in Claim.query.filter(
                Claim.verification_status == ClaimStatus.COMPLETED).all()]
            n = Message.query.filter(Message.match_id.in_(match_ids),
                                     Message.created_at < cutoff).delete(
                synchronize_session=False)
            db.session.commit()
            click.echo(f"Deleted {n} old messages.")

    @app.cli.command("purge-token-blocklist")
    def purge_token_blocklist():
        """Delete expired blocklist rows (older than the refresh lifetime)."""
        from app.extensions import db
        from app.models import TokenBlocklist
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=14)
        with app.app_context():
            n = TokenBlocklist.query.filter(TokenBlocklist.revoked_at < cutoff).delete()
            db.session.commit()
            click.echo(f"Deleted {n} blocklist entries.")


def wipe(db):
    """Delete all rows in dependency order (demo --reset)."""
    from app.models import (
        AuditLog,
        Claim,
        ClaimImage,
        Institution,
        Match,
        Message,
        Notification,
        Report,
        ReportImage,
        TokenBlocklist,
        User,
    )
    for model in (ClaimImage, Message, Notification, Claim, Match, ReportImage,
                  Report, TokenBlocklist, AuditLog, User, Institution):
        model.query.delete()
    db.commit = db.session.commit
    db.session.commit()
