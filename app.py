# app.py
# Trainer Booking — v0.1.13-alpha
# - Simplified, robust layout: columns-only header; safe top border & padding
# - Buttons guaranteed side-by-side on desktop; compact mobile row at <=480px
# - Capacity bar uses a single gradient (green left / red right)
# - Preserves single-dialog priority & booking form behavior

import json
import os
from pathlib import Path
from datetime import datetime, date, timedelta
import csv
import io

import streamlit as st

# ----------------------------- Constants -----------------------------
TZ = 'Asia/Singapore'
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

# ----------------------------- Page setup & CSS -----------------------------
st.set_page_config(page_title='Trainer Booking', page_icon='🏋️', layout='wide')

st.markdown(
    """
    <style>
      :root {
        --bg-page: #f6f8fb; --bg-card: #ffffff; --border: #e5e7eb; --border-strong: #cbd5e1;
        --text: #111827; --muted: #6b7280; --accent: #111111;
        --radius: 12px;

        --cell-h: clamp(54px, 8vw, 86px);
        --btn-h: clamp(28px, 3.2vw, 34px);
        --btn-font: clamp(12px, 1.1vw, 14px);
        --date-font: clamp(12px, 1.3vw, 16px);
        --weekday-font: clamp(10px, .95vw, 12px);
        --cap-h: clamp(6px, 1.1vw, 10px);
        --gap: 8px;
      }
      @media (prefers-color-scheme: dark) {
        :root {
          --bg-page: #0a0c10; --bg-card: #0b0f15; --border: #1f2937; --border-strong: #273244;
          --text: #e5e7eb; --muted: #9ca3af; --accent: #e5e7eb;
        }
      }

      /* Clean page frame with safe top padding + top border */
      .block-container {
        max-width: clamp(820px, 78vw, 980px);
        padding-top: 18px;
        box-shadow:
          inset 4px 0 0 var(--border-strong),
          inset -4px 0 0 var(--border-strong),
          inset 0 4px 0 var(--border-strong);
        border-radius: 10px;
        background: var(--bg-page);
      }

      /* Mobile adjustments */
      @media (max-width: 480px) {
        .block-container {
          max-width: 98vw;
          box-shadow:
            inset 2px 0 0 var(--border-strong),
            inset -2px 0 0 var(--border-strong),
            inset 0 3px 0 var(--border-strong);
          padding-left: 8px; padding-right: 8px;
        }
      }

      /* Buttons baseline */
      .stButton>button {
        height: var(--btn-h); padding: 0 12px;
        border: 1px solid var(--border); border-radius: 10px;
        font-size: var(--btn-font); background: var(--bg-card);
        transition: background-color 120ms ease, border-color 120ms ease, box-shadow 120ms ease, transform 120ms ease;
      }
      .stButton>button:hover { box-shadow: 0 3px 10px rgba(0,0,0,.06); transform: translateY(-1px); border-color: var(--text); }
      .stButton>button:active { transform: translateY(0); box-shadow: 0 2px 8px rgba(0,0,0,.05); }
      .stButton>button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

      /* Calendar cells */
      .calendar-cell {
        position: relative; border-radius: var(--radius);
        height: var(--cell-h); overflow: hidden;
        background: var(--bg-card);
        border: 1px solid var(--border);
      }
      .calendar-btn button {
        width: 100%; height: 100%; border-radius: var(--radius) !important;
        background: transparent; /* cell carries the bg/border */
        border: none;
        text-align: left; padding: 8px;
        transition: border-color 120ms ease, box-shadow 120ms ease, transform 120ms ease, background-color 120ms ease;
        position: relative; z-index: 2;
        font-size: var(--date-font);
      }
      .calendar-btn button:hover { box-shadow: inset 0 0 0 1px var(--text); }
      .calendar-selected .calendar-btn button { box-shadow: inset 0 0 0 2px var(--accent); }

      /* Capacity bottom bar — single gradient (green left, red right) */
      .cap-bar {
        position: absolute; left:0; right:0; bottom:0; height: var(--cap-h);
        border-radius: 0 0 var(--radius) var(--radius); overflow:hidden;
      }

      .chip { font-size: 10px; background: var(--accent); color:#fff; border-radius:6px; padding:2px 6px; }
      .today-chip { position:absolute; top:6px; right:8px; z-index:3; }
      .dots { position: absolute; bottom: calc(var(--cap-h) + 6px); left: 8px; display:flex; gap:3px; pointer-events:none; z-index:3; }
      .dot { width:5px; height:5px; border-radius:9999px; background: #60a5fa; opacity:.95; }

      .weekday-label { font-size: var(--weekday-font); color: var(--muted); text-align:center; }

      /* Title spacing */
      h2 { margin-top: 0; margin-bottom: 6px; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ----------------------------- Session State -----------------------------
if 'selected_date' not in st.session_state:
    st.session_state.selected_date = date.today()
if 'calendar_cursor' not in st.session_state:
    st.session_state.calendar_cursor = date.today().replace(day=1)

for key, default in [
    ('trainer_mode', False),
    ('show_trainer_modal', False),
    ('slots_modal_open', False),
    ('slots_modal_date', date.today()),
    ('open_confirm', False),
    ('pending_booking_date', None),
    ('pending_booking_hour', None),
    ('show_month_picker', False),
    ('month_picker_year', date.today().year),
    ('flash', None),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# One-shot toast
if st.session_state.flash:
    msg, icon = st.session_state.flash
    try: st.toast(msg, icon=icon)
    except Exception: st.success(msg)
    st.session_state.flash = None

# Load storage
storage = load_storage()
bookings = storage.get('bookings', [])
blocked = set(storage.get('blocked', []))
settings = storage.get('settings', {"dayStartHour": DEFAULT_DAY_START, "dayEndHour": DEFAULT_DAY_END, "trainerPin": "1234"})

start_hour = int(settings.get('dayStartHour', DEFAULT_DAY_START))
end_hour   = int(settings.get('dayEndHour',   DEFAULT_DAY_END))
hours = list(range(start_hour, end_hour + 1))

# ----------------------------- Helpers -----------------------------
def is_blocked(start_iso: str) -> bool:
    return start_iso in blocked

def is_booked(start_iso: str) -> bool:
    return any(b['startISO'] == start_iso for b in bookings)

def booking_at(start_iso: str):
    for b in bookings:
        if b['startISO'] == start_iso:
            return b
    return None

def month_matrix(cursor: date):
    first = cursor.replace(day=1)
    start_weekday = first.weekday()  # Mon=0..Sun=6
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

def day_availability_stats(d: date):
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
    return free, (taken + blocked_count), total

def day_bookings_count(d: date) -> int:
    return sum(1 for hr in hours if is_booked(slot_iso(d, hr)))

# ----------------------------- Dialogs -----------------------------
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
        st.session_state.open_confirm = False
        st.session_state.pending_booking_date = None
        st.session_state.pending_booking_hour = None
        try: st.toast('Booked ✔', icon='✅')
        except Exception: pass
        st.success('Booked. Copy your code to manage this booking.')
        st.code(code)
        st.stop()

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
                st.session_state.pending_booking_date = md
                st.session_state.pending_booking_hour = hr
                st.session_state.open_confirm = True
                st.session_state.slots_modal_open = False
                st.rerun()

@st.dialog('Choose month')
def month_picker_dialog():
    # Compact header: arrow, centered year, arrow
    c1, c2, c3 = st.columns([1,2,1])
    with c1:
        if st.button('‹', key='year_prev'): 
            st.session_state.month_picker_year -= 1
            st.rerun()
    with c2:
        st.markdown(f'<div style="display:flex;align-items:center;justify-content:center;"><span style="font-size:13px;opacity:.9">{st.session_state.month_picker_year}</span></div>', unsafe_allow_html=True)
    with c3:
        if st.button('›', key='year_next'):
            st.session_state.month_picker_year += 1
            st.rerun()

    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    grid = st.columns(3)
    for i, mlabel in enumerate(months):
        col = grid[i % 3]
        with col:
            if st.button(mlabel, key=f"mp-{mlabel}-{st.session_state.month_picker_year}"):
                y = st.session_state.month_picker_year
                m = i + 1
                st.session_state.calendar_cursor = date(y, m, 1)
                st.session_state.show_month_picker = False
                st.rerun()

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
                        if b.get('remark'): st.caption(b['remark'])
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

        # Export CSV
        day_bookings = [b for b in bookings if b['startISO'][:10] == to_date_str(sel_date)]
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

        if st.button('Close'):
            st.session_state.trainer_mode = False
            st.session_state.show_trainer_modal = False
            st.session_state.flash = ('Trainer closed', '🔒')
            st.rerun()

# ----------------------------- Header (pure columns: Title | Month | Today | Trainer) -----------------------------
# Desktop/tablet: guaranteed single row; Mobile (<=480px): Title row + compact buttons row beneath
if st.session_state.get('is_mobile_layout') is None:
    st.session_state.is_mobile_layout = False

# Heuristic: Streamlit can't give viewport width, but small devices usually render narrow columns.
# Provide a toggle (hidden behind an expander if needed) — or rely on CSS compacting.
# We'll keep one-row columns; CSS will shrink buttons on small screens.

title_col, month_col, today_col, trainer_col = st.columns([7, 2, 1.5, 1.5])
with title_col:
    st.markdown("## Trainer Booking")

with month_col:
    month_btn_label = st.session_state.calendar_cursor.strftime("%b %Y")
    if st.button(month_btn_label, key='month_btn', use_container_width=True):
        st.session_state.slots_modal_open = False
        st.session_state.open_confirm = False
        st.session_state.show_trainer_modal = False
        st.session_state.trainer_mode = False
        st.session_state.month_picker_year = st.session_state.calendar_cursor.year
        st.session_state.show_month_picker = True

with today_col:
    if st.button('Today', key='today_btn_small', use_container_width=True):
        st.session_state.slots_modal_open = False
        st.session_state.open_confirm = False
        st.session_state.show_trainer_modal = False
        st.session_state.trainer_mode = False
        st.session_state.calendar_cursor = date.today().replace(day=1)

with trainer_col:
    if st.button('Trainer', key='trainer_btn', use_container_width=True):
        st.session_state.slots_modal_open = False
        st.session_state.open_confirm = False
        st.session_state.show_month_picker = False
        st.session_state.trainer_mode = False
        st.session_state.show_trainer_modal = True

# Weekday header aligned to grid
weekday_cols = st.columns(7)
for i, label in enumerate(["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]):
    with weekday_cols[i]:
        st.markdown(f'<div class="weekday-label">{label}</div>', unsafe_allow_html=True)

# ----------------------------- Month grid -----------------------------
cursor = st.session_state.calendar_cursor
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

            free, occupied, total = day_availability_stats(d)
            free_pct = int(round((free / total) * 100)) if total else 0
            occ_pct = 100 - free_pct
            dots = min(day_bookings_count(d), 8)

            # cell wrapper
            st.markdown('<div class="calendar-cell">', unsafe_allow_html=True)

            # gradient capacity bar
            st.markdown(
                f'<div class="cap-bar" style="background: linear-gradient(90deg, #22c55e 0%, #22c55e {free_pct}%, #ef4444 {free_pct}%, #ef4444 100%);"></div>',
                unsafe_allow_html=True
            )

            wrapper_class = 'calendar-selected' if is_selected else ''
            if wrapper_class:
                st.markdown(f'<div class="{wrapper_class}">', unsafe_allow_html=True)
            st.markdown('<div class="calendar-btn">', unsafe_allow_html=True)
            clicked = st.button(f"{d.day}", key=f'daybtn-{to_date_str(d)}', use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
            if wrapper_class:
                st.markdown('</div>', unsafe_allow_html=True)

            if is_today:
                st.markdown('<div class="today-chip"><span class="chip">Today</span></div>', unsafe_allow_html=True)
            if dots:
                st.markdown('<div class="dots">' + ''.join(['<span class="dot"></span>' for _ in range(dots)]) + '</div>', unsafe_allow_html=True)

            st.markdown('</div>', unsafe_allow_html=True)

            if clicked:
                st.session_state.selected_date = d
                st.session_state.slots_modal_date = d
                st.session_state.slots_modal_open = True
                st.session_state.calendar_cursor = d.replace(day=1)

# ----------------------------- Launch exactly one dialog (priority) -----------------------------
if st.session_state.open_confirm and st.session_state.pending_booking_date is not None:
    confirm_booking_dialog(st.session_state.pending_booking_date, st.session_state.pending_booking_hour)
elif st.session_state.slots_modal_open:
    slots_dialog()
elif st.session_state.show_month_picker:
    month_picker_dialog()
elif st.session_state.show_trainer_modal:
    trainer_dialog()

st.divider()

# ----------------------------- Manage booking (form) -----------------------------
st.header('Manage booking')
with st.form('manage_form'):
    code = st.text_input('Booking code (e.g. ABC-123)').strip().upper()
    submitted_manage = st.form_submit_button('Submit')

if submitted_manage and code:
    managed = next((b for b in bookings if b.get('code','').upper() == code), None)
else:
    managed = None

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

# Footer
st.caption('Timezone: Asia/Singapore · Data stored in storage.json (server-local). For persistence across restarts, use a database.')
