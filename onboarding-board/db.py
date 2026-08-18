"""Storage layer for the client onboarding dashboard.

Uses Postgres when DATABASE_URL is set (the Railway Postgres add-on injects it
automatically), and falls back to a local SQLite file otherwise. Queries are
written with `?` placeholders and translated to `%s` for Postgres.

Note: the placeholder translation is a plain string replace, so SQL in this
module must never contain a literal `?` inside a string literal.
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

DATABASE_URL = (os.environ.get('DATABASE_URL') or '').strip()
IS_PG = DATABASE_URL.startswith('postgres')
SQLITE_PATH = os.environ.get('DB_PATH') or 'onboarding.db'

if IS_PG:
    import psycopg2
    import psycopg2.extras


# ── Pipeline definition ──────────────────────────────────────────────────────
# These are the columns of the old color-coded Google Sheet, left to right.

STAGES = [
    {'key': 'forms_complete',    'label': 'Onboarding Forms Complete', 'short': 'Forms'},
    {'key': 'ghl_setup',         'label': 'GHL Account Set Up',        'short': 'GHL'},
    {'key': 'website_updated',   'label': 'Website Updates Made',      'short': 'Website'},
    {'key': 'a2p_submitted',     'label': 'A2P Submitted',             'short': 'A2P Sub'},
    {'key': 'a2p_complete',      'label': 'A2P Complete',              'short': 'A2P Done'},
    {'key': 'workbook_complete', 'label': 'Workbook Complete',         'short': 'Workbook'},
    {'key': 'ads_created',       'label': 'Ads Created',               'short': 'Ads'},
    {'key': 'closebot_setup',    'label': 'CloseBot Set Up',           'short': 'CloseBot'},
    {'key': 'final_review',      'label': 'Final Review Complete',     'short': 'Review'},
    {'key': 'all_systems_live',  'label': 'All Systems Live',          'short': 'Live'},
]

STAGE_KEYS = [s['key'] for s in STAGES]
STAGE_LABELS = {s['key']: s['label'] for s in STAGES}

# The stage a GHL form submission satisfies on arrival, and the one that means
# the client is fully launched.
INTAKE_STAGE = 'forms_complete'
FINAL_STAGE = 'all_systems_live'

STATUSES = ('not_started', 'in_progress', 'blocked', 'done')
DEFAULT_STATUS = 'not_started'


def utcnow():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def parse_ts(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def parse_date_input(value):
    """Turn a YYYY-MM-DD date from the UI into our stored timestamp format.

    Anchored at midday UTC so the date a person picked is the date that shows
    back to them regardless of their timezone.
    """
    if not value:
        return None
    try:
        day = datetime.strptime(str(value).strip()[:10], '%Y-%m-%d')
    except (ValueError, TypeError):
        return None
    return day.strftime('%Y-%m-%dT12:00:00Z')


def days_since(value):
    ts = parse_ts(value)
    if not ts:
        return None
    delta = datetime.now(timezone.utc) - ts
    return round(delta.total_seconds() / 86400, 1)


# ── Connection handling ──────────────────────────────────────────────────────

def _ph(sql):
    """Translate `?` placeholders to `%s` when talking to Postgres."""
    return sql.replace('?', '%s') if IS_PG else sql


@contextmanager
def get_conn():
    if IS_PG:
        conn = psycopg2.connect(DATABASE_URL)
    else:
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _cursor(conn):
    if IS_PG:
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return conn.cursor()


def query(sql, params=(), one=False):
    with get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(_ph(sql), params)
        rows = cur.fetchall()
        rows = [dict(r) for r in rows]
        cur.close()
    if one:
        return rows[0] if rows else None
    return rows


def execute(sql, params=()):
    with get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(_ph(sql), params)
        rowcount = cur.rowcount
        cur.close()
    return rowcount


def insert(sql, params=()):
    """Run an INSERT and return the new row id."""
    with get_conn() as conn:
        cur = _cursor(conn)
        if IS_PG:
            cur.execute(_ph(sql) + ' RETURNING id', params)
            new_id = cur.fetchone()['id']
        else:
            cur.execute(sql, params)
            new_id = cur.lastrowid
        cur.close()
    return new_id


# ── Schema ───────────────────────────────────────────────────────────────────

def init_db():
    pk = 'SERIAL PRIMARY KEY' if IS_PG else 'INTEGER PRIMARY KEY AUTOINCREMENT'
    with get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS clients (
                id {pk},
                name TEXT NOT NULL,
                email TEXT,
                phone TEXT,
                company TEXT,
                website TEXT,
                brand TEXT,
                owner TEXT,
                ghl_contact_id TEXT,
                ghl_location_id TEXT,
                source TEXT,
                notes TEXT,
                raw_payload TEXT,
                archived INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS client_stages (
                id {pk},
                client_id INTEGER NOT NULL,
                stage_key TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'not_started',
                completed_at TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE (client_id, stage_key)
            )
        """)
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS events (
                id {pk},
                client_id INTEGER,
                kind TEXT NOT NULL,
                message TEXT NOT NULL,
                actor TEXT,
                created_at TEXT NOT NULL
            )
        """)
        cur.execute('CREATE INDEX IF NOT EXISTS idx_stages_client ON client_stages (client_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_events_client ON events (client_id)')
        cur.close()
    _migrate_stage_keys()


# Stage keys that were renamed after the board went out. Old rows are carried
# over so a rename never resets anyone's history. The original pipeline split
# intake across "onboarded" and "info_submitted"; those merged into a single
# "forms_complete", so the second one carries the timestamp and the first is
# dropped.
RENAMED_STAGE_KEYS = {
    'info_submitted': 'forms_complete',
    'atp_submitted': 'a2p_submitted',
    'atp_approved': 'a2p_complete',
    'ads_finalized': 'ads_created',
    'launched': 'all_systems_live',
}
RETIRED_STAGE_KEYS = ('onboarded',)


def _migrate_stage_keys():
    present = {r['stage_key'] for r in query('SELECT DISTINCT stage_key FROM client_stages')}
    for old, new in RENAMED_STAGE_KEYS.items():
        if old not in present:
            continue
        # Drop any placeholder row already sitting on the new key so the
        # carried-over row does not collide with it.
        execute(
            'DELETE FROM client_stages WHERE stage_key = ? AND client_id IN'
            ' (SELECT client_id FROM client_stages WHERE stage_key = ?)',
            (new, old),
        )
        execute('UPDATE client_stages SET stage_key = ? WHERE stage_key = ?', (new, old))
    for dead in RETIRED_STAGE_KEYS:
        if dead in present:
            execute('DELETE FROM client_stages WHERE stage_key = ?', (dead,))


# ── Events ───────────────────────────────────────────────────────────────────

def log_event(client_id, kind, message, actor=None):
    insert(
        'INSERT INTO events (client_id, kind, message, actor, created_at) VALUES (?, ?, ?, ?, ?)',
        (client_id, kind, message, actor, utcnow()),
    )


def get_events(client_id, limit=50):
    return query(
        'SELECT * FROM events WHERE client_id = ? ORDER BY id DESC LIMIT ?',
        (client_id, limit),
    )


# ── Clients ──────────────────────────────────────────────────────────────────

CLIENT_FIELDS = (
    'name', 'email', 'phone', 'company', 'website', 'brand', 'owner',
    'ghl_contact_id', 'ghl_location_id', 'source', 'notes',
)


def create_client(data, actor='system', raw_payload=None):
    now = utcnow()
    new_id = insert(
        """INSERT INTO clients
           (name, email, phone, company, website, brand, owner,
            ghl_contact_id, ghl_location_id, source, notes, raw_payload,
            archived, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
        (
            data.get('name') or 'Unnamed client',
            data.get('email'), data.get('phone'), data.get('company'),
            data.get('website'), data.get('brand'), data.get('owner'),
            data.get('ghl_contact_id'), data.get('ghl_location_id'),
            data.get('source'), data.get('notes'),
            json.dumps(raw_payload) if raw_payload else None,
            now, now,
        ),
    )
    for key in STAGE_KEYS:
        insert(
            'INSERT INTO client_stages (client_id, stage_key, status, completed_at, updated_at)'
            ' VALUES (?, ?, ?, NULL, ?)',
            (new_id, key, DEFAULT_STATUS, now),
        )
    log_event(new_id, 'created', f"Client added ({data.get('source') or 'manual'})", actor)
    return new_id


def update_client(client_id, data, actor='system'):
    fields, params = [], []
    for key in CLIENT_FIELDS:
        if key in data:
            fields.append(f'{key} = ?')
            params.append(data[key])
    if data.get('created_at'):
        stamp = parse_date_input(data['created_at'])
        if stamp:
            fields.append('created_at = ?')
            params.append(stamp)
    if 'archived' in data:
        fields.append('archived = ?')
        params.append(1 if data['archived'] else 0)
    if not fields:
        return False
    fields.append('updated_at = ?')
    params.extend([utcnow(), client_id])
    execute(f"UPDATE clients SET {', '.join(fields)} WHERE id = ?", params)
    changed = ', '.join(k for k in data.keys() if k in CLIENT_FIELDS or k == 'archived')
    log_event(client_id, 'update', f'Updated: {changed}', actor)
    return True


def touch_client(client_id):
    execute('UPDATE clients SET updated_at = ? WHERE id = ?', (utcnow(), client_id))


def set_stage(client_id, stage_key, status, actor='system', completed_at=None):
    if stage_key not in STAGE_KEYS:
        raise ValueError(f'Unknown stage: {stage_key}')
    if status not in STATUSES:
        raise ValueError(f'Unknown status: {status}')
    now = utcnow()
    # completed_at is the clock the cycle-time metrics run on: stamped when a
    # stage is marked done, cleared if it gets moved back. An explicit date is
    # passed when backfilling a stage that was actually cleared weeks ago.
    completed_at = (completed_at or now) if status == 'done' else None
    execute(
        """INSERT INTO client_stages (client_id, stage_key, status, completed_at, updated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT (client_id, stage_key)
           DO UPDATE SET status = ?, completed_at = ?, updated_at = ?""",
        (client_id, stage_key, status, completed_at, now, status, completed_at, now),
    )
    touch_client(client_id)
    log_event(
        client_id, 'stage',
        f'{STAGE_LABELS[stage_key]} -> {status.replace("_", " ")}',
        actor,
    )


def merge_raw_payload(client_id, payload):
    """Merge a fresh webhook payload into the stored one so nothing is lost."""
    row = query('SELECT raw_payload FROM clients WHERE id = ?', (client_id,), one=True)
    existing = {}
    if row and row.get('raw_payload'):
        try:
            existing = json.loads(row['raw_payload'])
        except (ValueError, TypeError):
            existing = {}
    if not isinstance(existing, dict):
        existing = {'previous': existing}
    existing.update(payload or {})
    execute(
        'UPDATE clients SET raw_payload = ?, updated_at = ? WHERE id = ?',
        (json.dumps(existing), utcnow(), client_id),
    )


def find_client(email=None, ghl_contact_id=None, name=None):
    """Look a client up by the most reliable identifier available."""
    if ghl_contact_id:
        row = query(
            'SELECT * FROM clients WHERE ghl_contact_id = ?', (ghl_contact_id,), one=True
        )
        if row:
            return row
    if email:
        row = query(
            'SELECT * FROM clients WHERE LOWER(email) = ?', (email.strip().lower(),), one=True
        )
        if row:
            return row
    if name:
        row = query(
            'SELECT * FROM clients WHERE LOWER(name) = ?', (name.strip().lower(),), one=True
        )
        if row:
            return row
    return None


def get_client(client_id):
    return query('SELECT * FROM clients WHERE id = ?', (client_id,), one=True)


def delete_client(client_id):
    execute('DELETE FROM client_stages WHERE client_id = ?', (client_id,))
    execute('DELETE FROM events WHERE client_id = ?', (client_id,))
    execute('DELETE FROM clients WHERE id = ?', (client_id,))


def all_stages():
    """Return {client_id: {stage_key: {...}}} for every client."""
    rows = query('SELECT client_id, stage_key, status, completed_at, updated_at FROM client_stages')
    out = {}
    for r in rows:
        out.setdefault(r['client_id'], {})[r['stage_key']] = {
            'status': r['status'],
            'completed_at': r['completed_at'],
            'updated_at': r['updated_at'],
        }
    return out


def serialize_client(row, stage_map, include_payload=True):
    """Turn a client row plus its stages into the shape the dashboard expects.

    The stored GHL payload is only read on the client detail panel, which loads
    one client at a time, so the board list leaves it out — otherwise every
    background refresh ships every client's entire form submission.
    """
    stages = stage_map.get(row['id'], {})
    resolved = {}
    for key in STAGE_KEYS:
        entry = dict(stages.get(key) or {})
        entry.setdefault('status', DEFAULT_STATUS)
        entry.setdefault('completed_at', None)
        entry.setdefault('updated_at', row['created_at'])
        resolved[key] = entry

    # Walk the pipeline in order to work out how long each stage actually took.
    # A stage is "entered" the moment the stage before it was completed, so
    # duration = completed_at(this) - completed_at(previous). The team only has
    # to mark things done — same as the sheet — and the timings fall out.
    entered_at = row['created_at']
    for key in STAGE_KEYS:
        entry = resolved[key]
        entry['entered_at'] = entered_at
        entry['duration_days'] = None
        entry['waiting_days'] = None
        if entry['status'] == 'done' and entry['completed_at']:
            start, finish = parse_ts(entered_at), parse_ts(entry['completed_at'])
            if start and finish:
                entry['duration_days'] = max(
                    0.0, round((finish - start).total_seconds() / 86400, 1)
                )
            entered_at = entry['completed_at']
        else:
            entry['waiting_days'] = days_since(entered_at)

    done = [k for k in STAGE_KEYS if resolved[k]['status'] == 'done']
    blocked = [k for k in STAGE_KEYS if resolved[k]['status'] == 'blocked']
    in_progress = [k for k in STAGE_KEYS if resolved[k]['status'] == 'in_progress']

    is_live = resolved[FINAL_STAGE]['status'] == 'done'
    if is_live:
        overall = 'live'
    elif blocked:
        overall = 'blocked'
    elif done or in_progress:
        overall = 'in_progress'
    else:
        overall = 'not_started'

    # The current stage is the first one that is not finished.
    current = None
    for key in STAGE_KEYS:
        if resolved[key]['status'] != 'done':
            current = key
            break

    idle_days = days_since(row['updated_at'])
    # How long this client has been parked at the stage they are on right now.
    current_wait_days = resolved[current]['waiting_days'] if current else None

    days_to_launch = None
    if is_live:
        started = parse_ts(row['created_at'])
        launched = parse_ts(resolved[FINAL_STAGE]['completed_at'] or resolved[FINAL_STAGE]['updated_at'])
        if started and launched:
            days_to_launch = max(0.0, round((launched - started).total_seconds() / 86400, 1))

    raw = None
    if include_payload and row.get('raw_payload'):
        try:
            raw = json.loads(row['raw_payload'])
        except (ValueError, TypeError):
            raw = None

    return {
        'id': row['id'],
        'name': row['name'],
        'email': row['email'],
        'phone': row['phone'],
        'company': row['company'],
        'website': row['website'],
        'brand': row['brand'],
        'owner': row['owner'],
        'source': row['source'],
        'notes': row['notes'],
        'ghl_contact_id': row['ghl_contact_id'],
        'ghl_location_id': row['ghl_location_id'],
        'archived': bool(row['archived']),
        'created_at': row['created_at'],
        'updated_at': row['updated_at'],
        'stages': resolved,
        'submitted': raw,
        'done_count': len(done),
        'stage_count': len(STAGE_KEYS),
        'progress': round(len(done) / len(STAGE_KEYS) * 100),
        'overall': overall,
        'current_stage': current,
        'current_stage_label': STAGE_LABELS.get(current) if current else 'Live',
        'idle_days': idle_days,
        'current_wait_days': current_wait_days,
        'days_to_launch': days_to_launch,
        'launched_at': resolved[FINAL_STAGE]['completed_at'] if is_live else None,
    }


def list_clients(include_archived=False, include_payload=False):
    sql = 'SELECT * FROM clients'
    if not include_archived:
        sql += ' WHERE archived = 0'
    sql += ' ORDER BY created_at DESC, id DESC'
    rows = query(sql)
    stage_map = all_stages()
    return [serialize_client(r, stage_map, include_payload) for r in rows]
