# -*- coding: utf-8 -*-
"""
Nightly deemed-approval job.

Under the Purvanchal Right to Public Services Act, an application not processed
within the statutory SLA stands approved. This job marks such applications
DEEMED_APPROVED and notifies the applicant by SMS.

    python scripts/deemed_approval.py            # do it
    python scripts/deemed_approval.py --dry-run  # only count what it would approve

Scheduled via cron, 02:00 daily. See deploy/crontab. Exits non-zero on any
failure so that cron/monitoring can see it (it used to fail silently for months).
"""
import os
import sys
from datetime import datetime, timedelta

import psycopg2
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings import load_config  # noqa: E402


def main(argv):
    dry_run = "--dry-run" in argv
    config = load_config()
    sla_days = config.getint("pension", "sla_days")
    gateway = config.get("app", "sms_gateway_url")
    cutoff = datetime.now() - timedelta(days=sla_days)

    conn = psycopg2.connect(
        host=config.get("database", "host"), port=config.get("database", "port"),
        dbname=config.get("database", "name"), user=config.get("database", "user"),
        password=config.get("database", "password"), connect_timeout=10)
    try:
        cur = conn.cursor()
        if dry_run:
            cur.execute("SELECT count(*) FROM applications "
                        "WHERE status = 'PENDING' AND submitted_at < %s", (cutoff,))
            print("%s dry-run: %d applications would be deemed approved"
                  % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), cur.fetchone()[0]))
            return 0
        cur.execute(
            """UPDATE applications
               SET status = 'DEEMED_APPROVED', decided_at = %s, decided_by = 'RTPS-AUTO'
               WHERE status = 'PENDING' AND submitted_at < %s
               RETURNING application_no, mobile""",
            (datetime.now(), cutoff))
        rows = cur.fetchall()
        conn.commit()
    finally:
        conn.close()

    for app_no, mobile in rows:
        try:
            requests.post(gateway + "/api/send", json={
                "to": mobile,
                "text": "Sewa Setu: your pension application %s stands approved "
                        "under the RTPS Act." % app_no}, timeout=5)
        except Exception:
            pass    # the approval is already committed; SMS is best-effort
    print("%s deemed approval: %d applications approved"
          % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
