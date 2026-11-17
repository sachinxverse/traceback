# Copy existing local uploads into an S3-compatible bucket and verify
# (Issue 5). Dry-run by default; --apply performs the copy.
# Usage:
#   python scripts/migrate_storage.py --apply? [--report migration_report.txt]
"""For every ReportImage/ClaimImage row: check whether the object exists in
the target bucket; if not and the local file exists, copy it. Rows whose
local file is also missing are reported as MISSING (nothing can be done
programmatically). Never deletes the local copies."""
import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually copy (default: dry-run)")
    ap.add_argument("--report", default=None, help="write a verification report file")
    args = ap.parse_args()

    from app import create_app
    from app.extensions import db
    from app.models import ClaimImage, ReportImage
    from app.services.storage import get_storage

    app = create_app(os.environ.get("APP_CONFIG", "development"))
    with app.app_context():
        st = get_storage()
        if st.__class__.__name__ != "S3Storage":
            print("WARNING: STORAGE_BACKEND is not 's3' — nothing to migrate into.")
        rows = [(ReportImage, "report_image", "image")]
        rows.append((ClaimImage, "claim_image", "image"))
        copied = missing_remote_ok = 0
        missing_local = []
        for model, label, _kind in rows:
            for img in model.query.all():
                key = img.storage_key
                try:
                    st.open(key)
                    continue  # already in the bucket
                except Exception:
                    pass
                local_path = os.path.join(app.config["UPLOAD_DIR"], key)
                if os.path.exists(local_path):
                    if args.apply:
                        with open(local_path, "rb") as fh:
                            st.save(fh.read(), key)
                    copied += 1
                    print(f"{'COPIED' if args.apply else 'WOULD COPY'} {label} id={img.id} key={key}")
                else:
                    missing_local.append((label, img.id, key))
                    print(f"MISSING-LOCAL {label} id={img.id} key={key}")

        print(f"\nsummary: copied={copied} missing_local={len(missing_local)} "
              f"(dry-run={not args.apply})")
        if args.report:
            with open(args.report, "w", encoding="utf-8") as fh:
                fh.write("storage migration verification report\n")
                fh.write(f"copied: {copied}\nmissing local files: {len(missing_local)}\n")
                for label, iid, key in missing_local:
                    fh.write(f"MISSING {label} id={iid} key={key}\n")
            print(f"report written: {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
