# app.py
# Streamlit version of the Trainer Booking app tailored for simple, accurate 1-hour slot scheduling.
# Key features:
# - Month-first flow: pick a date from a Mon-Sun grid that shows a left-to-right availability bar.
# - Book a slot with name and optional remark.
# - Get a booking code to reschedule or cancel later.
# - Manage booking by code: move to another available slot on any day, or cancel.
# - Trainer mode (PIN): see day's schedule, block/unblock slots, export CSV.
# - Accuracy: strong conflict checks against persisted storage to avoid double-booking.
# - Persistence: JSON file on disk (storage.json). For multi-user hosting, switch to a DB.
#
# Deploy: `pip install -r requirements.txt` then `streamlit run app.py`
# Requirements (save as requirements.txt):
#   streamlit>=1.36
#
# Note: Streamlit runs per-session; this app defensively reloads from disk before writes to avoid conflicts.

import json
import os
from pathlib import Path
from datetime import datetime, date, timedelta, time
import csv
import io
import random
import string

import streamlit as st

TZ = 'Asia/Singapore'  # For labeling only. Streamlit server time governs true tz unless you use pytz.
STORAGE_PATH = Path('storage.json')
SLOT_LENGTH_MIN = 60
DEFAULT_DAY_START = 6
DEFAULT_DAY_END = 21

# ----------------------------- Utilities -----------------------------
@st.cache_data(show_spinner=False)
def _load_storage_cached(ts: float):
    """Load storage snapshot for a given mtime fingerprint."""
    if not STORAGE_PATH.exists():
        return {"bookings": [], "blocked": [], "settings": {"dayStartHour": DEFAULT_DAY_START, "dayEndHour": DEFAULT_DAY_END, "trainerPin": "1234"}}
    with open(STORAGE_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_storage():
    mtime = STORAGE_PATH.stat().st_mtime if STORAGE_PATH.exists() else 0.0
    return _load_storage_cached(mtime)


def save_storage(data):
    # Write atomically to reduce race conditions
    tmp = STORAGE_PATH.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STORAGE_PATH)
    # Bust cache
    _load_storage_cached.clear()


def to_date_str(dt: date) -> str:
    return dt.strftime('%Y-%m-%d')


def from_date_str(s: str) -> date:
    return datetime.strptime(s, '%Y-%m-%d').date()


def slot_iso(d: date, hour: int) -> str:
    return datetime(d.year, d.month, d.day, hour, 0, 0).isoformat()


def add_minutes_iso(iso: str, minutes: int) -> str:
    dt = datetime.fromisoformat(iso)
    return (dt + timedelta(minutes=minutes)).isoformat()


def fmt_date(dt: date) -> str:
    return dt.strftime('%a, %d %b %Y')


def fmt_time(dt: datetime) -> str:
    return dt.strftime('%H:%M')


def uid(n=6):
    chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    return ''.join(random.choice(chars) for _ in range(n))


# ----------------------------- State -----------------------------
st.set_page_config(page_title='Trainer Booking', page_icon='🏋️')

if 'selected_date' not in st.session_state:
    st.session_state.selected_date = date.today()
if 'trainer_mode' not in st.session_state:
    st.session_state.trainer_mode = False

storage = load_storage()
bookings = storage.get('bookings', [])
blocked = set(storage.get('blocked', []))  # list of startISO strings
settings = storage.get('settings', {"dayStartHour": DEFAULT_DAY_START, "dayEndHour": DEFAULT_DAY_END, "trainerPin": "1234"})

start_hour = int(settings.get('dayStartHour', DEFAULT_DAY_START))
end_hour = int(settings.get('dayEndHour', DEFAULT_DAY_END))

hours = list(range(start_hour, end_hour + 1))

# Helpers on current snapshot

def is_blocked(start_iso: str) -> bool:
    return start_iso in blocked


def is_booked(start_iso: str) -> bool:
    return any(b['startISO'] == start_iso for b in bookings)


def booking_at(start_iso: str):
    for b in bookings:
        if b['startISO'] == start_iso:
            return b
    return None


# ----------------------------- Layout helpers -----------------------------
@st.experimental_dialog('Confirm booking')
def confirm_booking_dialog(slot_date: date, hour: int):
    start_iso = slot_iso(slot_date, hour)
    end_iso = add_minutes_iso(start_iso, SLOT_LENGTH_MIN)

    with st.form('booking_form', clear_on_submit=False):
        name = st.text_input('Your name', placeholder='e.g. Alex Tan')
        remark = st.text_area('Remark (optional)', placeholder='Goals, focus areas, injuries. Max 200 chars.', max_chars=200)
        submitted = st.form_submit_button('Confirm')

    if submitted:
        # Reload storage right before writing
        latest = load_storage()
        latest_blocked = set(latest.get('blocked', []))
        latest_bookings = latest.get('bookings', [])
        if start_iso in latest_blocked:
            st.error('That slot is blocked. Please pick another.')
            return
        if any(b['startISO'] == start_iso for b in latest_bookings):
            st.error('Sorry, the slot was just taken. Please pick another.')
            return
        code = f"{uid(3)}-{uid(3)}"
        booking = {
            'id': f"bk_{int(datetime.now().timestamp()*1000)}",
            'name': name.strip(),
            'remark': (remark or '').strip(),
            'startISO': start_iso,
            'endISO': end_iso,
            'createdAtISO': datetime.now().isoformat(),
            'code': code,
        }
        if not booking['name']:
            st.error('Please enter your name.')
            return
        latest_bookings.append(booking)
        latest['bookings'] = latest_bookings
        save_storage(latest)
        st.success('Booked. Copy your code to manage this booking.')
        st.code(code)
        st.stop()


# ----------------------------- Calendar (month-first) -----------------------------

def month_matrix(cursor: date):
    first = cursor.replace(day=1)
    # Monday as 0..Sunday as 6
    start_weekday = (first.weekday())  # Monday=0
    days_in_month = (first.replace(month=first.month % 12 + 1, day=1) - timedelta(days=1)).day

    cells = [None] * start_weekday  # leading blanks
    cells += [first + timedelta(days=i) for i in range(days_in_month)]
    while len(cells) % 7 != 0:
        cells.append(None)

    # chunk into 6 rows
    rows = [cells[i:i+7] for i in range(0, len(cells), 7)]
    return rows


def day_availability_ratio(d: date) -> float:
    total = len(hours)
    taken = 0
    blocked_count = 0
    for hr in hours:
        s = slot_iso(d, hr)
        if is_booked(s):
            taken += 1
        elif is_blocked(s):
            blocked_count += 1
    free = max(0, total - taken - blocked_count)
    return (free / total) if total else 0.0


# ----------------------------- Top Bar -----------------------------
left, center, right = st.columns([1,2,1])
with left:
    if st.button('◀', use_container_width=True):
        d = st.session_state.selected_date
        prev_month = (d.replace(day=1) - timedelta(days=1)).replace(day=1)
        st.session_state.selected_date = prev_month
with center:
    st.markdown(f"### {st.session_state.selected_date.strftime('%B %Y')}")
    if st.button('Today', key='today_btn'):
        st.session_state.selected_date = date.today().replace(day=1)
with right:
    if st.button('▶', use_container_width=True):
        d = st.session_state.selected_date
        # next month first day
        year = d.year + (1 if d.month == 12 else 0)
        month = 1 if d.month == 12 else d.month + 1
        st.session_state.selected_date = date(year, month, 1)

# ----------------------------- Month Grid -----------------------------

cursor = st.session_state.selected_date.replace(day=1)
rows = month_matrix(cursor)

st.markdown('<div style="font-size:12px;color:#666;margin-top:4px;">Mon Tue Wed Thu Fri Sat Sun</div>', unsafe_allow_html=True)
for week in rows:
    cols = st.columns(7, vertical_alignment='center')
    for i, d in enumerate(week):
        with cols[i]:
            if d is None:
                st.write('')
            else:
                is_today = d == date.today()
                is_selected = d == st.session_state.selected_date
                pct = int(round(day_availability_ratio(d) * 100))
                box_style = (
                    'border:1px solid #e5e7eb;border-radius:12px;padding:8px;height:90px;background:#fff;position:relative;'
                    + ('box-shadow:0 0 0 2px #000 inset;' if is_selected else '')
                )
                badge = '<span style="font-size:10px;background:#000;color:#fff;border-radius:6px;padding:2px 4px;">Today</span>' if is_today else ''
                bar = f'<div style="position:absolute;left:0;bottom:0;height:8px;background:#bbf7d0;border-bottom-left-radius:12px;width:{pct}%;"></div>'
                st.markdown(f'<div style="{box_style}"><div style="display:flex;justify-content:space-between;align-items:center;"><div style="font-size:12px;color:#111;">{d.day}</div>{badge}</div>{bar}</div>', unsafe_allow_html=True)
                st.button('Select', key=f'sel-{to_date_str(d)}', on_click=lambda dd=d: st.session_state.__setitem__('selected_date', dd))

st.divider()

# ----------------------------- Day slots panel -----------------------------
sel_date = st.session_state.selected_date
st.subheader(f'Selected date: {fmt_date(sel_date)}')

slot_cols = st.columns(3)
for idx, hr in enumerate(hours):
    start_iso = slot_iso(sel_date, hr)
    end_iso = add_minutes_iso(start_iso, SLOT_LENGTH_MIN)
    booked = is_booked(start_iso)
    blocked_flag = is_blocked(start_iso)
    label = f"{hr:02d}:00"
    col = slot_cols[idx % 3]
    with col:
        disabled = booked or blocked_flag
        cap = 'Blocked' if blocked_flag else ('Booked' if booked else 'Available')
        st.caption(cap)
        if st.button(label, disabled=disabled, key=f'slot-{start_iso}'):
            confirm_booking_dialog(sel_date, hr)

# Show last code banner within dialog success only.

st.divider()

# ----------------------------- Manage booking -----------------------------
st.header('Manage booking')
code = st.text_input('Booking code (e.g. ABC-123)').strip().upper()
managed = next((b for b in bookings if b.get('code','').upper() == code), None)

if managed:
    md = datetime.fromisoformat(managed['startISO'])
    st.markdown(f"**Name:** {managed['name']}  ")
    st.markdown(f"**Date:** {md.strftime('%a, %d %b %Y')}  ")
    st.markdown(f"**Time:** {md.strftime('%H:%M')}–{datetime.fromisoformat(managed['endISO']).strftime('%H:%M')}  ")
    if managed.get('remark'):
        st.markdown(f"**Remark:** {managed['remark']}")

    st.write('Move to:')
    # Choose a date then a time
    move_date = st.date_input('New date', value=sel_date, key='move_date')
    # times on that day
    move_cols = st.columns(3)
    for i, hr in enumerate(hours):
        s = slot_iso(move_date, hr)
        disabled = is_booked(s) or is_blocked(s)
        with move_cols[i % 3]:
            if st.button(f"{hr:02d}:00", disabled=disabled, key=f'mv-{s}'):
                latest = load_storage()
                raw = latest.get('bookings', [])
                idx = next((i for i, bb in enumerate(raw) if bb.get('code','').upper() == code), -1)
                if idx < 0:
                    st.error('Booking not found. Check your code.')
                elif any(b['startISO'] == s for b in raw):
                    st.error('New slot is already taken.')
                elif s in set(latest.get('blocked', [])):
                    st.error('New slot is blocked.')
                else:
                    raw[idx]['startISO'] = s
                    raw[idx]['endISO'] = add_minutes_iso(s, SLOT_LENGTH_MIN)
                    latest['bookings'] = raw
                    save_storage(latest)
                    st.success('Booking moved.')
                    st.rerun()

    if st.button('Cancel this booking', type='primary'):
        latest = load_storage()
        keep = [b for b in latest.get('bookings', []) if b.get('code','').upper() != code]
        if len(keep) == len(latest.get('bookings', [])):
            st.error('Booking not found.')
        else:
            latest['bookings'] = keep
            save_storage(latest)
            st.success('Booking canceled.')
            st.rerun()

st.divider()

# ----------------------------- Trainer mode -----------------------------
st.header('Trainer view')
if not st.session_state.trainer_mode:
    with st.form('pin_form'):
        pin = st.text_input('Enter PIN', type='password')
        if st.form_submit_button('Unlock'):
            if pin == str(settings.get('trainerPin', '1234')):
                st.session_state.trainer_mode = True
                st.rerun()
            else:
                st.error('Wrong PIN.')
else:
    # Day config
    st.write(f"Selected date: **{fmt_date(sel_date)}**")
    c1, c2, c3 = st.columns(3)
    with c1:
        new_start = st.number_input('Start hour', min_value=0, max_value=23, value=start_hour)
    with c2:
        new_end = st.number_input('End hour', min_value=0, max_value=23, value=end_hour)
    with c3:
        new_pin = st.text_input('Trainer PIN', value=str(settings.get('trainerPin','1234')))
    if st.button('Save settings'):
        latest = load_storage()
        latest.setdefault('settings', {})
        latest['settings']['dayStartHour'] = int(new_start)
        latest['settings']['dayEndHour'] = int(new_end)
        latest['settings']['trainerPin'] = new_pin[:8]
        save_storage(latest)
        st.success('Settings saved.')
        st.rerun()

    # Grid of slots with block toggles and details
    grid_cols = st.columns(3)
    for idx, hr in enumerate(hours):
        s = slot_iso(sel_date, hr)
        b = booking_at(s)
        blocked_flag = is_blocked(s)
        with grid_cols[idx % 3]:
            box = st.container(border=True)
            with box:
                st.write(f"**{hr:02d}:00**")
                if b:
                    st.write(f"{b['name']}")
                    if b.get('remark'):
                        st.caption(b['remark'])
                    st.code(b['code'])
                else:
                    st.caption('No booking')
                if st.button('Unblock' if blocked_flag else 'Block', key=f'blk-{s}'):
                    latest = load_storage()
                    blk = set(latest.get('blocked', []))
                    if s in blk: blk.remove(s)
                    else: blk.add(s)
                    latest['blocked'] = sorted(list(blk))
                    save_storage(latest)
                    st.rerun()

    # Export CSV of the day
    day_bookings = [b for b in bookings if from_date_str(b['startISO'][:10]) == sel_date]
    rows = [["Date", "Start", "End", "Client", "Remark", "Code"]]
    for b in sorted(day_bookings, key=lambda x: x['startISO']):
        dt = datetime.fromisoformat(b['startISO'])
        rows.append([
            dt.strftime('%Y-%m-%d'),
            dt.strftime('%H:%M'),
            datetime.fromisoformat(b['endISO']).strftime('%H:%M'),
            b['name'],
            b.get('remark',''),
            b['code'],
        ])
    csv_buf = io.StringIO()
    cw = csv.writer(csv_buf)
    cw.writerows(rows)
    st.download_button('Export day CSV', data=csv_buf.getvalue(), file_name=f'{to_date_str(sel_date)}-schedule.csv', mime='text/csv')

    if st.button('Lock'):
        st.session_state.trainer_mode = False
        st.rerun()
