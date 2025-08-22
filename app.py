# app.py
# Trainer Booking — v0.1.2-alpha
# - Replaced deprecated st.experimental_dialog → st.dialog
# - Replaced st.experimental_rerun → st.rerun
# - Keeps all prior UI/UX polish (hover, focus-visible, privacy dots, thin bar)

import json
import os
from pathlib import Path
from datetime import datetime, date, timedelta
import csv
import io

import streamlit as st

# ----------------------------- Constants -----------------------------
TZ = 'Asia/Singapore'  # label only
STORAGE_PATH = Path('storage.json')
SLOT_LENGTH_MIN = 60
DEFAULT_DAY_START = 6
DEFAULT_DAY_END = 21

# ----------------------------- Utilities -----------------------------
@st.cache_data(show_spinner=False)
def _load_storage_cached(ts: float):
    if not STORAGE_PATH.exists():
        return {"bookings": [], "blocked": [], "settings": {"dayStartHour": DEFAULT_DAY_START, "dayEndHour": DEFAULT_DAY_END, "trainerPin": "1234"}}
    with open(STORAGE_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_storage():
    mtime = STORAGE_PATH.stat().st_mtime if STORAGE_PATH.exists() else 0.0
    return _load_storage_cached(mtime)

def save_storage(data):
    tmp = STORAGE_PATH.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STORAGE_PATH)
    _load_storage_cached.clear()


def to_date_str(dt: date) -> str:
    return dt.strftime('%Y-%m-%d')

def from_date_str(s: str) -> date:
    return datetime.strptime(s, '%Y-%m-%d').date()

def slot_iso(d: date, hr: int) -> str:
    return datetime(d.year, d.month, d.day, hr, 0, 0).isoformat()

def add_minutes_iso(iso: str, minutes: int) -> str:
    dt = datetime.fromisoformat(iso)
    return (dt + timedelta(minutes=minutes)).isoformat()

def fmt_date(dt: date) -> str:
    return dt.strftime('%a, %d %b %Y')

def uid(n=6):
    chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    import secrets
    return ''.join(secrets.choice(chars) for _ in range(n))

# ----------------------------- Page setup & State -----------------------------
st.set_page_config(page_title='Trainer Booking', page_icon='🏋️', layout='wide')

# Design tokens & global CSS
st.markdown(
    """
    <style>
      :root {
        --bg-page: #f8fafc; --bg-card: #ffffff; --border: #e5e7eb;
        --text: #111827; --muted: #6b7280; --accent: #111111;
        --bar-free: #bbf7d0; --dot-booked: #60a5fa;
        --radius: 12px; --cell-h: 92px; --bar-h: 6px;
        --space-xs: 4px; --space-sm: 8px; --space-md: 12px;
      }
      @media (prefers-color-scheme: dark) {
        :root {
          --bg-page: #0a0c10; --bg-card: #0b0f15; --border: #1f2937;
          --text: #e5e7eb; --muted: #9ca3af; --accent: #e5e7eb;
          --bar-free: #065f46; --dot-booked: #2563eb;
        }
      }
      body { background: var(--bg-page); }

      .topbar-right { display:flex; gap:6px; align-items:center; justify-content:flex-end; }
      .month-label { font-weight:600; font-size:13px; color:var(--text); opacity:.9; }

      /* Calendar cells */
      .calendar-btn button {
        width: 100%; height: var(--cell-h); border-radius: var(--radius) !important;
        background: var(--bg-card); border: 1px solid var(--border);
        text-align: left; padding: var(--space-sm);
        transition: border-color 120ms ease, box-shadow 120ms ease, transform 120ms ease, background-color 120ms ease;
      }
      .calendar-btn button:hover { border-color: var(--text); box-shadow: 0 4px 14px rgba(0,0,0,.06); transform: translateY(-1px); }
      .calendar-btn button:active { transform: translateY(0); box-shadow: 0 2px 8px rgba(0,0,0,.05); }
      .calendar-btn button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
      .calendar-selected button { box-shadow: 0 0 0 2px var(--accent) inset, 0 2px 8px rgba(0,0,0,.04); }
      .chip { font-size:10px; background: var(--accent); color:#fff; border-radius:6px; padding:2px 6px; }

      /* Availability bar */
      .avail-bar { position: relative; top: calc(var(--space-sm) * -1); }
      .avail-track { height: var(--bar-h); width: 100%; background: var(--border); border-radius: 0 0 var(--radius) var(--radius); overflow:hidden; }
      .avail-fill { height: var(--bar-h); background: var(--bar-free); transition: width 220ms ease; }

      /* Dots for booked count */
      .dots { position: relative; top: -28px; padding-left: var(--space-sm); display:flex; gap:4px; }
      .dot { width:6px; height:6px; border-radius:9999px; background: var(--dot-booked); opacity:.95; }

      .weekday-label { font-size:12px; color: var(--muted); margin-top: 2px; }

      /* Subtle hover for ALL Streamlit buttons */
      .stButton>button {
        transition: background-color 120ms ease, border-color 120ms ease, box-shadow 120ms ease, transform 120ms ease;
        border-radius: 9999px;
      }
      .stButton>button:hover { box-shadow: 0 4px 14px rgba(0,0,0,.06); transform: translateY(-1px); border-color: var(--text); }
      .stButton>button:active { transform: translateY(0); box-shadow: 0 2px 8px rgba(0,0,0,.05); }
      .stButton>button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
    </style>
    """,
    unsafe_allow_html=True,
)

# Session keys
if 'selected_date' not in st.session_state:
    st.session_state.selected_date = date.today()
if 'trainer_mode' not in st.session_state:
    st.session_state.trainer_mode = False
if 'show_trainer_modal' not in st.session_state:
    st.session_state.show_trainer_modal = False
if 'slots_modal_open' not in st.session_state:
    st.session_state.slots_modal_open = False
if 'slots_modal_date' not in st.session_state:
    st.session_state.slots_modal_date = date.today()
if 'flash' not in st.session_state:
    st.session_state.flash = None  # (msg, icon)

# One-shot toast renderer
if st.session_state.flash:
    msg, icon = st.session_state.flash
    try:
        st.toast(msg, icon=icon)
    except Exception:
        st.success(msg)
    st.session_state.flash = None

# Load storage snapshot
storage = load_storage()
bookings = storage.get('bookings', [])
blocked = set(storage.get('blocked', []))
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

# ----------------------------- Booking workflow -----------------------------
@st.dialog('Confirm booking')
def confirm_booking_dialog(slot_date: date, hour: int):
    start_iso = slot_iso(slot_date, hour)
    end_iso = add_minutes_iso(start_iso, SLOT_LENGTH_MIN)

    with st.form('booking_form', clear_on_submit=False):
        name = st.text_input('Your name', placeholder='e.g. Alex Tan')
        remark = st.text_area('Remark (optional)', placeholder='Goals, focus areas, injuries. Max 200 chars.', max_chars=200)
        submitted = st.form_submit_button('Confirm')

    if submitted:
        latest = load_storage()
        latest_blocked = set(latest.get('blocked', []))
        latest_bookings = latest.get('bookings', [])
        if start_iso in latest_blocked:
            st.error('That slot is blocked. Please pick another.')
            return
        if any(b['startISO'] == start_iso for b in latest_bookings):
            st.error('Sorry, the slot was just taken. Please pick another.')
            return
        if not name.strip():
            st.error('Please enter your name.')
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
        latest_bookings.append(booking)
        latest['bookings'] = latest_bookings
        save_storage(latest)
        st.session_state.slots_modal_open = False
        try:
            st.toast('Booked ✔', icon='✅')
        except Exception:
            pass
        st.success('Booked. Copy your code to manage this booking.')
        st.code(code)
        st.stop()

# ----------------------------- Calendar helpers -----------------------------

def month_matrix(cursor: date):
    first = cursor.replace(day=1)
    start_weekday = first.weekday()  # Mon=0..Sun=6
    # Days in month
    if first.month == 12:
        first_next = date(first.year + 1, 1, 1)
    else:
        first_next = date(first.year, first.month + 1, 1)
    days_in_month = (first_next - timedelta(days=1)).day

    cells = [None] * start_weekday
    cells += [first + timedelta(days=i) for i in range(days_in_month)]
    while len(cells) % 7 != 0:
        cells.append(None)
    return [cells[i:i+7] for i in range(0, len(cells), 7)]


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


def day_bookings_count(d: date) -> int:
    cnt = 0
    for hr in hours:
        if is_booked(slot_iso(d, hr)):
            cnt += 1
    return cnt

# ----------------------------- Top bar -----------------------------
header_left, header_right = st.columns([6, 6])
with header_left:
    st.markdown("## Trainer Booking")

with header_right:
    st.markdown('<div class="topbar-right">', unsafe_allow_html=True)
    st.markdown(f'<span class="month-label">{st.session_state.selected_date.strftime("%b %Y")}</span>', unsafe_allow_html=True)
    nav_c1, nav_c2, nav_c3 = st.columns([1, 1, 2])
    with nav_c1:
        if st.button('‹', key='prev_month', help='Previous month', use_container_width=True):
            d = st.session_state.selected_date
            prev_month = (d.replace(day=1) - timedelta(days=1)).replace(day=1)
            st.session_state.selected_date = prev_month
    with nav_c2:
        if st.button('›', key='next_month', help='Next month', use_container_width=True):
            d = st.session_state.selected_date
            year = d.year + (1 if d.month == 12 else 0)
            month = 1 if d.month == 12 else d.month + 1
            st.session_state.selected_date = date(year, month, 1)
    with nav_c3:
        if st.button('Today', key='today_btn_small'):
            st.session_state.selected_date = date.today().replace(day=1)
    if st.button('Trainer', key='trainer_btn'):
        st.session_state.show_trainer_modal = True
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown('<div class="weekday-label">Mon Tue Wed Thu Fri Sat Sun</div>', unsafe_allow_html=True)

# ----------------------------- Month grid (date cell is the button) -----------------------------
cursor = st.session_state.selected_date.replace(day=1)
rows = month_matrix(cursor)

for week in rows:
    columns = st.columns(7)
    for i, d in enumerate(week):
        with columns[i]:
            if d is None:
                st.write("")
                continue
            is_today = (d == date.today())
            is_selected = (d == st.session_state.selected_date)
            pct = int(round(day_availability_ratio(d) * 100))
            dots = min(day_bookings_count(d), 8)

            classes = 'calendar-btn'
            if is_selected:
                classes += ' calendar-selected'
            st.markdown(f'<div class="{classes}">', unsafe_allow_html=True)
            clicked = st.button(f"{d.day}", key=f'daybtn-{to_date_str(d)}', use_container_width=True)

            if is_today:
                st.markdown('<div style="position:relative; top:-86px; display:flex; justify-content:flex-end; padding-right:8px;"><span class="chip">Today</span></div>', unsafe_allow_html=True)
            if dots:
                st.markdown('<div class="dots">' + ''.join(['<span class="dot"></span>' for _ in range(dots)]) + '</div>', unsafe_allow_html=True)
            st.markdown('<div class="avail-bar"><div class="avail-track"><div class="avail-fill" style="width:'+str(pct)+'%;"></div></div></div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

            if clicked:
                st.session_state.selected_date = d
                st.session_state.slots_modal_date = d
                st.session_state.slots_modal_open = True

# ----------------------------- Slots dialog after date selection -----------------------------
@st.dialog('Select a time')
def slots_dialog():
    md = st.session_state.slots_modal_date
    st.write(f"**{fmt_date(md)}**")
    slot_cols = st.columns(3)
    for idx, hr in enumerate(hours):
        s = slot_iso(md, hr)
        booked = is_booked(s)
        blocked_flag = is_blocked(s)
        label = f"{hr:02d}:00"
        with slot_cols[idx % 3]:
            disabled = booked or blocked_flag
            cap = 'Blocked' if blocked_flag else ('Booked' if booked else 'Available')
            st.caption(cap)
            if st.button(label, disabled=disabled, key=f'sel-{s}'):
                confirm_booking_dialog(md, hr)

if st.session_state.slots_modal_open:
    slots_dialog()

st.divider()

# ----------------------------- Manage booking (page section) -----------------------------
st.header('Manage booking')
code = st.text_input('Booking code (e.g. ABC-123)').strip().upper()
managed = next((b for b in bookings if b.get('code','').upper() == code), None)

if managed:
    md = datetime.fromisoformat(managed['startISO'])
    st.markdown(f"**Name:** {managed['name']}")
    st.markdown(f"**Date:** {md.strftime('%a, %d %b %Y')}")
    st.markdown(f"**Time:** {md.strftime('%H:%M')}–{datetime.fromisoformat(managed['endISO']).strftime('%H:%M')}")
    if managed.get('remark'):
        st.markdown(f"**Remark:** {managed['remark']}")

    st.write('Move to:')
    move_date = st.date_input('New date', value=st.session_state.selected_date, key='move_date')
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
                    st.session_state.flash = ('Booking moved', '✅')
                    st.rerun()

    if st.button('Cancel this booking', type='primary'):
        latest = load_storage()
        keep = [b for b in latest.get('bookings', []) if b.get('code','').upper() != code]
        if len(keep) == len(latest.get('bookings', [])):
            st.error('Booking not found.')
        else:
            latest['bookings'] = keep
            save_storage(latest)
            st.session_state.flash = ('Booking canceled', '🗑️')
            st.rerun()

st.divider()

# ----------------------------- Trainer dialog (top-right) -----------------------------
@st.dialog('Trainer')
def trainer_dialog():
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
        sel_date = st.session_state.selected_date
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
            st.session_state.flash = ('Settings saved', '💾')
            st.rerun()

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
                        st.session_state.flash = ('Slot updated', '🚧')
                        st.rerun()

        # Export CSV for the day
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
        import csv as _csv
        cw = _csv.writer(csv_buf)
        cw.writerows(rows)
        st.download_button('Export day CSV', data=csv_buf.getvalue(), file_name=f'{to_date_str(sel_date)}-schedule.csv', mime='text/csv')

        if st.button('Lock'):
            st.session_state.trainer_mode = False
            st.session_state.show_trainer_modal = False
            st.session_state.flash = ('Trainer locked', '🔒')
            st.rerun()

if st.session_state.show_trainer_modal:
    trainer_dialog()

# Footer
st.caption('Timezone: Asia/Singapore · Data stored in storage.json (server-local). For persistence across restarts, use a database.')
