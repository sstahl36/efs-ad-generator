"""Client onboarding dashboard: GHL webhook ingest, JSON API, and the board UI.

The board mirrors the color-coded onboarding sheet — one row per client, one
column per stage — but it is fed automatically from GoHighLevel and kept in a
real database instead of a spreadsheet.
"""

import csv
import hmac
import io
import json
import os
import re
from functools import wraps

from flask import (
    Blueprint, Response, jsonify, redirect, render_template, request,
    session, url_for,
)

import db

bp = Blueprint('onboarding', __name__)

WEBHOOK_SECRET = (os.environ.get('WEBHOOK_SECRET') or '').strip()
DASHBOARD_PASSWORD = (os.environ.get('DASHBOARD_PASSWORD') or '').strip()
STUCK_AFTER_DAYS = float(os.environ.get('STUCK_AFTER_DAYS') or 7)


# ── Auth ─────────────────────────────────────────────────────────────────────

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not DASHBOARD_PASSWORD or session.get('authed'):
            return fn(*args, **kwargs)
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Not authorized'}), 401
        return redirect(url_for('onboarding.login', next=request.path))
    return wrapper


def current_actor():
    return session.get('actor') or 'dashboard'


@bp.route('/onboarding/login', methods=['GET', 'POST'])
def login():
    if not DASHBOARD_PASSWORD:
        return redirect(url_for('onboarding.dashboard'))
    error = None
    if request.method == 'POST':
        supplied = request.form.get('password') or ''
        if hmac.compare_digest(supplied, DASHBOARD_PASSWORD):
            session['authed'] = True
            session.permanent = True
            name = (request.form.get('name') or '').strip()
            if name:
                session['actor'] = name
            nxt = request.args.get('next') or url_for('onboarding.dashboard')
            return redirect(nxt)
        error = 'That password is not right.'
    return render_template('login.html', error=error)


@bp.route('/onboarding/logout')
def logout():
    session.clear()
    return redirect(url_for('onboarding.login'))


# ── Webhook payload parsing ──────────────────────────────────────────────────

def _flatten(payload, prefix='', out=None, depth=0):
    """Flatten nested webhook JSON into dotted keys, e.g. contact.email."""
    if out is None:
        out = {}
    if depth > 4 or not isinstance(payload, dict):
        return out
    for key, value in payload.items():
        path = f'{prefix}{key}'
        if isinstance(value, dict):
            _flatten(value, path + '.', out, depth + 1)
        else:
            out[path] = value
    return out


def _norm(text):
    return re.sub(r'[^a-z0-9]', '', str(text).lower())


# Nested objects that describe something other than the contact. A bare `name`
# or `email` underneath one of these belongs to the sub-account or the assigned
# user, not the client, so we never read it as a contact field.
AMBIGUOUS_PARENTS = {
    'location', 'user', 'account', 'assigneduser', 'owner', 'workflow',
    'trigger', 'calendar', 'opportunity', 'pipeline', 'company', 'source',
}


def _pick(flat, *aliases):
    """Find the value whose key best matches one of the aliases.

    Aliases are tried in the order given, so `full_name` beats a bare `name`.
    Within one alias a whole-key match (`location.id` for `location_id`) beats a
    trailing-segment match (`contact.email` for `email`), and shallower keys beat
    deeper ones.
    """
    for alias in aliases:
        want = _norm(alias)
        best = None
        for key, value in flat.items():
            if value in (None, '', []):
                continue
            depth = key.count('.')
            if _norm(key.replace('.', '')) == want:
                rank = (0, depth)
            elif _norm(key.split('.')[-1]) == want:
                parent = _norm(key.split('.')[-2]) if depth else ''
                if parent in AMBIGUOUS_PARENTS:
                    continue
                rank = (1, depth)
            else:
                continue
            if best is None or rank < best[0]:
                best = (rank, str(value).strip())
        if best and best[1]:
            return best[1]
    return None


def extract_contact(payload):
    """Map an arbitrary GHL payload onto our client fields.

    GHL sends different shapes depending on whether the webhook comes from a
    workflow action, a form submission, or the contact API, so we search every
    nesting level for keys we recognise rather than assuming one layout.
    """
    flat = _flatten(payload)

    first = _pick(flat, 'first_name', 'firstName', 'first')
    last = _pick(flat, 'last_name', 'lastName', 'last')
    # Explicit full-name fields win, then first + last, and only then a bare
    # `name` key — which is the one most likely to belong to something else.
    name = _pick(flat, 'full_name', 'fullName', 'contact_name', 'contactName')
    if not name:
        name = ' '.join(p for p in (first, last) if p).strip() or None
    if not name:
        name = _pick(flat, 'name')

    company = _pick(
        flat, 'company', 'company_name', 'companyName', 'business',
        'business_name', 'businessName', 'organization', 'brand_name', 'brandName',
    )

    return {
        'name': name,
        'email': _pick(flat, 'email', 'email_address', 'emailAddress', 'contact_email'),
        'phone': _pick(flat, 'phone', 'phone_number', 'phoneNumber', 'mobile'),
        'company': company,
        'website': _pick(flat, 'website', 'website_url', 'websiteUrl', 'url', 'domain'),
        'brand': _pick(flat, 'brand', 'franchise', 'franchise_brand', 'niche'),
        'owner': _pick(flat, 'owner', 'account_manager', 'accountManager', 'assigned_to', 'assignedTo'),
        'ghl_contact_id': _pick(flat, 'contact_id', 'contactId', 'ghl_contact_id'),
        'ghl_location_id': _pick(flat, 'location_id', 'locationId', 'locationid'),
    }


def extract_stage(payload):
    """Pull an optional stage instruction out of the payload.

    Lets a GHL workflow advance the board directly — send `stage` (a key or a
    label like "A2P Complete") and optionally `stage_status`.
    """
    flat = _flatten(payload)
    raw_stage = _pick(flat, 'stage', 'stage_key', 'stageKey', 'onboarding_stage', 'onboardingStage')
    if not raw_stage:
        return None, None

    target = _norm(raw_stage)
    stage_key = None
    for stage in db.STAGES:
        if target in (_norm(stage['key']), _norm(stage['label']), _norm(stage['short'])):
            stage_key = stage['key']
            break
    if not stage_key:
        return None, None

    raw_status = _pick(flat, 'stage_status', 'stageStatus', 'status') or 'done'
    status_norm = _norm(raw_status)
    status_map = {
        'done': 'done', 'complete': 'done', 'completed': 'done', 'approved': 'done',
        'yes': 'done', 'true': 'done', 'finished': 'done',
        'inprogress': 'in_progress', 'progress': 'in_progress', 'started': 'in_progress',
        'pending': 'in_progress', 'submitted': 'in_progress', 'working': 'in_progress',
        'blocked': 'blocked', 'stuck': 'blocked', 'rejected': 'blocked', 'denied': 'blocked',
        'notstarted': 'not_started', 'reset': 'not_started', 'none': 'not_started',
    }
    return stage_key, status_map.get(status_norm, 'done')


# ── Webhook ──────────────────────────────────────────────────────────────────

def _secret_ok():
    if not WEBHOOK_SECRET:
        return True
    supplied = (
        request.headers.get('X-Webhook-Secret')
        or request.args.get('token')
        or ''
    )
    return hmac.compare_digest(supplied, WEBHOOK_SECRET)


@bp.route('/webhook/ghl', methods=['POST'])
def webhook_ghl():
    if not _secret_ok():
        return jsonify({'error': 'Invalid or missing webhook secret'}), 401

    payload = request.get_json(force=True, silent=True)
    if payload is None:
        payload = request.form.to_dict() or {}
    if not isinstance(payload, dict):
        return jsonify({'error': 'Expected a JSON object'}), 400

    contact = extract_contact(payload)
    if not (contact['email'] or contact['ghl_contact_id'] or contact['name']):
        return jsonify({
            'error': 'Could not find a name, email, or contact id in the payload',
            'received_keys': sorted(_flatten(payload).keys())[:40],
        }), 400

    existing = db.find_client(
        email=contact['email'],
        ghl_contact_id=contact['ghl_contact_id'],
        name=contact['name'],
    )

    if existing:
        client_id = existing['id']
        created = False
        # Only fill in blanks — never overwrite something a human has edited.
        updates = {
            key: value for key, value in contact.items()
            if value and not (existing.get(key) or '').strip()
        }
        if updates:
            db.update_client(client_id, updates, actor='ghl-webhook')
        db.merge_raw_payload(client_id, payload)
        db.log_event(client_id, 'webhook', 'Form data received from GHL', 'ghl-webhook')
    else:
        contact['source'] = 'ghl-webhook'
        client_id = db.create_client(contact, actor='ghl-webhook', raw_payload=payload)
        created = True
        # A client only reaches this webhook by submitting the onboarding form,
        # so that first stage is satisfied on arrival.
        db.set_stage(client_id, db.INTAKE_STAGE, 'done', actor='ghl-webhook')

    stage_key, status = extract_stage(payload)
    if stage_key:
        db.set_stage(client_id, stage_key, status, actor='ghl-webhook')

    return jsonify({
        'ok': True,
        'client_id': client_id,
        'created': created,
        'stage_applied': stage_key,
        'status_applied': status,
    })


# ── JSON API ─────────────────────────────────────────────────────────────────

@bp.route('/api/clients', methods=['GET'])
@login_required
def api_list_clients():
    # Archived clients are returned so the board can offer an Archived view
    # without a second round trip; build_stats decides what they count toward.
    clients = db.list_clients(include_archived=True)
    return jsonify({
        'clients': clients,
        'stages': db.STAGES,
        'stats': build_stats(clients),
    })


@bp.route('/api/clients', methods=['POST'])
@login_required
def api_create_client():
    data = request.get_json(force=True, silent=True) or {}
    if not (data.get('name') or '').strip():
        return jsonify({'error': 'Name is required'}), 400
    data.setdefault('source', 'manual')
    client_id = db.create_client(data, actor=current_actor())
    return jsonify({'ok': True, 'client_id': client_id}), 201


@bp.route('/api/clients/<int:client_id>', methods=['GET'])
@login_required
def api_get_client(client_id):
    row = db.get_client(client_id)
    if not row:
        return jsonify({'error': 'Client not found'}), 404
    client = db.serialize_client(row, db.all_stages())
    client['events'] = db.get_events(client_id)
    return jsonify(client)


@bp.route('/api/clients/<int:client_id>', methods=['PATCH'])
@login_required
def api_update_client(client_id):
    if not db.get_client(client_id):
        return jsonify({'error': 'Client not found'}), 404
    data = request.get_json(force=True, silent=True) or {}
    db.update_client(client_id, data, actor=current_actor())
    return jsonify({'ok': True})


@bp.route('/api/clients/<int:client_id>', methods=['DELETE'])
@login_required
def api_delete_client(client_id):
    if not db.get_client(client_id):
        return jsonify({'error': 'Client not found'}), 404
    db.delete_client(client_id)
    return jsonify({'ok': True})


@bp.route('/api/clients/<int:client_id>/stage', methods=['POST'])
@login_required
def api_set_stage(client_id):
    if not db.get_client(client_id):
        return jsonify({'error': 'Client not found'}), 404
    data = request.get_json(force=True, silent=True) or {}
    try:
        db.set_stage(client_id, data.get('stage'), data.get('status'), actor=current_actor())
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify({'ok': True})


@bp.route('/api/clients/<int:client_id>/note', methods=['POST'])
@login_required
def api_add_note(client_id):
    if not db.get_client(client_id):
        return jsonify({'error': 'Client not found'}), 404
    data = request.get_json(force=True, silent=True) or {}
    message = (data.get('message') or '').strip()
    if not message:
        return jsonify({'error': 'Note cannot be empty'}), 400
    db.log_event(client_id, 'note', message, current_actor())
    db.touch_client(client_id)
    return jsonify({'ok': True})


@bp.route('/api/export.csv')
@login_required
def api_export_csv():
    clients = db.list_clients(include_archived=request.args.get('archived') == '1')
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ['Client', 'Company', 'Email', 'Phone', 'Website', 'Brand', 'Owner']
        + [s['label'] for s in db.STAGES]
        + [f"Days: {s['label']}" for s in db.STAGES]
        + [
            'Progress %', 'Current Stage', 'Days At Current Stage', 'Days Idle',
            'Days To Launch', 'Added', 'Launched',
        ]
    )
    for c in clients:
        writer.writerow(
            [
                c['name'], c['company'] or '', c['email'] or '', c['phone'] or '',
                c['website'] or '', c['brand'] or '', c['owner'] or '',
            ]
            + [c['stages'][s['key']]['status'] for s in db.STAGES]
            + [
                c['stages'][s['key']]['duration_days']
                if c['stages'][s['key']]['duration_days'] is not None else ''
                for s in db.STAGES
            ]
            + [
                c['progress'], c['current_stage_label'],
                c['current_wait_days'] if c['current_wait_days'] is not None else '',
                c['idle_days'] if c['idle_days'] is not None else '',
                c['days_to_launch'] if c['days_to_launch'] is not None else '',
                c['created_at'], c['launched_at'] or '',
            ]
        )
    return Response(
        buf.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=onboarding.csv'},
    )


def _mean(values):
    return round(sum(values) / len(values), 1) if values else None


def _median(values):
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 1)
    return round((ordered[mid - 1] + ordered[mid]) / 2, 1)


def build_stats(clients):
    """Aggregate the operational metrics the team runs the pipeline on.

    Two different questions need two different populations. "What is happening
    right now" (in flight, stuck, piled up on a stage) counts only clients still
    on the board. "How have we performed" (time to live, days per stage) counts
    archived clients too — putting a finished client away should not erase the
    history that tells you how long they took.
    """
    active = [c for c in clients if not c.get('archived')]
    total = len(active)
    live = sum(1 for c in active if c['overall'] == 'live')
    blocked = sum(1 for c in active if c['overall'] == 'blocked')
    not_started = sum(1 for c in active if c['overall'] == 'not_started')

    stuck = [
        c for c in active
        if c['overall'] != 'live'
        and c['current_wait_days'] is not None
        and c['current_wait_days'] >= STUCK_AFTER_DAYS
    ]
    stuck.sort(key=lambda c: c['current_wait_days'], reverse=True)

    launch_times = [c['days_to_launch'] for c in clients if c['days_to_launch'] is not None]
    launched_recently = sum(
        1 for c in clients
        if c['days_to_launch'] is not None
        and db.days_since(c['launched_at']) is not None
        and db.days_since(c['launched_at']) <= 30
    )

    # Per-stage cycle time and work-in-progress. `done` is how many clients have
    # ever cleared the stage; `wip` is how many are sitting on it right now.
    stage_stats = []
    for stage in db.STAGES:
        key = stage['key']
        durations = [
            c['stages'][key]['duration_days'] for c in clients
            if c['stages'][key]['duration_days'] is not None
        ]
        waiting = [c for c in active if c['current_stage'] == key]
        waits = [c['current_wait_days'] for c in waiting if c['current_wait_days'] is not None]
        stage_stats.append({
            'key': key,
            'label': stage['label'],
            'short': stage['short'],
            'done': sum(1 for c in active if c['stages'][key]['status'] == 'done'),
            'pct': round(
                sum(1 for c in active if c['stages'][key]['status'] == 'done') / total * 100
            ) if total else 0,
            'blocked': sum(1 for c in active if c['stages'][key]['status'] == 'blocked'),
            'wip': len(waiting),
            'wip_names': [c['name'] for c in waiting][:8],
            'avg_days': _mean(durations),
            'median_days': _median(durations),
            'sample': len(durations),
            'longest_wait': max(waits) if waits else None,
        })

    # Two different questions: which stage historically eats the most days, and
    # which stage has the most clients piled up on it today.
    timed = [s for s in stage_stats if s['avg_days'] is not None and s['sample'] >= 2]
    slowest = max(timed, key=lambda s: s['avg_days']) if timed else None
    jammed_pool = [s for s in stage_stats if s['wip'] > 0]
    jammed = max(
        jammed_pool,
        key=lambda s: (s['wip'], s['longest_wait'] or 0),
    ) if jammed_pool else None

    return {
        'total': total,
        'archived': len(clients) - total,
        'live': live,
        'blocked': blocked,
        'not_started': not_started,
        'in_progress': total - live - blocked - not_started,
        'stuck': len(stuck),
        'stuck_clients': [
            {
                'id': c['id'],
                'name': c['name'],
                'stage': c['current_stage_label'],
                'days': c['current_wait_days'],
            }
            for c in stuck[:10]
        ],
        'stuck_after_days': STUCK_AFTER_DAYS,
        'avg_days_to_launch': _mean(launch_times),
        'median_days_to_launch': _median(launch_times),
        'fastest_launch': min(launch_times) if launch_times else None,
        'slowest_launch': max(launch_times) if launch_times else None,
        'launched_last_30': launched_recently,
        'stages': stage_stats,
        'slowest_stage': slowest,
        'jammed_stage': jammed,
    }


# ── Dashboard ────────────────────────────────────────────────────────────────

@bp.route('/onboarding')
@login_required
def dashboard():
    webhook_url = request.url_root.rstrip('/') + '/webhook/ghl'
    if WEBHOOK_SECRET:
        webhook_url += '?token=YOUR_WEBHOOK_SECRET'
    return render_template(
        'dashboard.html',
        stages_json=json.dumps(db.STAGES),
        statuses_json=json.dumps(list(db.STATUSES)),
        webhook_url=webhook_url,
        secret_required=bool(WEBHOOK_SECRET),
        password_set=bool(DASHBOARD_PASSWORD),
        actor=current_actor(),
    )
