import json
import os
import time
from typing import Dict, List, Any

import streamlit as st

# ----------------------------
# Config
# ----------------------------
CTF_DURATION_SECONDS = 3 * 60 * 60  # 3 hours
BANK_PATH = "challenge_bank.json"

CATEGORIES = ["web", "osint", "crypto", "forensics", "misc"]
CATEGORY_LABELS = {
    "web": "Web",
    "osint": "OSINT",
    "crypto": "Crypto",
    "forensics": "Forensics",
    "misc": "Misc",
}

# ----------------------------
# Helpers
# ----------------------------
def load_bank(path: str) -> Dict[str, List[Dict[str, Any]]]:
    if not os.path.exists(path):
        return {c: [] for c in CATEGORIES}
    with open(path, "r", encoding="utf-8") as f:
        bank = json.load(f)
    for c in CATEGORIES:
        bank.setdefault(c, [])
    return bank

def normalize_flag(s: str) -> str:
    return (s or "").strip()

def now_epoch() -> int:
    return int(time.time())

def fmt_hms(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def remaining_seconds(started_at: int) -> int:
    elapsed = now_epoch() - started_at
    return max(0, CTF_DURATION_SECONDS - elapsed)

def points_for(ch: Dict[str, Any]) -> int:
    try:
        return int(ch.get("points", 0))
    except Exception:
        return 0

def seeded_sample(items: List[Dict[str, Any]], k: int, seed: int) -> List[Dict[str, Any]]:
    """Deterministic 'random' sample based on hash."""
    if not items:
        return []
    scored = []
    for it in items:
        key = f"{seed}:{it.get('id','')}:{it.get('title','')}"
        h = abs(hash(key))
        scored.append((h, it))
    scored.sort(key=lambda x: x[0])
    return [it for _, it in scored[: min(k, len(scored))]]

def build_room_challenges(bank: Dict[str, List[Dict[str, Any]]], room_seed: int) -> Dict[str, List[Dict[str, Any]]]:
    per_cat = {}
    for c in CATEGORIES:
        per_cat[c] = seeded_sample(bank.get(c, []), 5, room_seed)
    return per_cat

def init_state():
    st.session_state.setdefault("room_code", "")
    st.session_state.setdefault("player_name", "")
    st.session_state.setdefault("room_started_at", None)
    st.session_state.setdefault("room_seed", None)
    st.session_state.setdefault("selected", None)
    st.session_state.setdefault("solved", set())
    st.session_state.setdefault("score", 0)
    st.session_state.setdefault("team_log", [])  # local log
    st.session_state.setdefault("last_submit", None)  # tuple(kind, msg)
    st.session_state.setdefault("do_balloons", False)

def render_tags_and_difficulty(ch: Dict[str, Any]):
    tags = ch.get("tags", []) or []
    difficulty = (ch.get("difficulty") or "").strip()
    parts = []
    if difficulty:
        parts.append(f"**Difficulty:** {difficulty}")
    if tags:
        parts.append("**Tags:** " + ", ".join(tags))
    if parts:
        st.caption(" | ".join(parts))

def render_external_link(ch: Dict[str, Any]):
    link = ch.get("external_link")
    if link and isinstance(link, str):
        st.link_button("Open external link", link)

def render_attachments(ch: Dict[str, Any]):
    atts = ch.get("attachments", []) or []
    if not atts:
        return
    st.markdown("### Attachments")
    for a in atts:
        name = a.get("name", "download")
        url = a.get("url")
        ftype = a.get("type", "")
        if url:
            label = f"Download: {name}" + (f" ({ftype})" if ftype else "")
            st.link_button(label, url)

def can_show_writeup(ch: Dict[str, Any], solved: bool) -> bool:
    w = ch.get("writeup")
    if not isinstance(w, dict):
        return False
    mode = (w.get("visible") or "after_solve").lower()
    if mode == "always":
        return True
    if mode == "after_solve":
        return solved
    return False  # "never" or unknown

def render_writeup(ch: Dict[str, Any], solved: bool):
    w = ch.get("writeup")
    if not isinstance(w, dict):
        return
    if can_show_writeup(ch, solved):
        with st.expander("Writeup / Solution"):
            st.markdown(w.get("content_md", "") or "")

# ----------------------------
# Submit callback (IMPORTANT)
# ----------------------------
def handle_submit(flag_key: str, correct_flag: str, sel_id: str, pts: int, player: str):
    got = normalize_flag(st.session_state.get(flag_key, ""))
    correct = normalize_flag(correct_flag)

    if not got:
        st.session_state.last_submit = ("error", "Flag cannot be empty.")
    elif got == correct:
        st.session_state.solved.add(sel_id)
        st.session_state.score += pts
        st.session_state.team_log.append((now_epoch(), player or "Player", sel_id, pts))
        st.session_state.last_submit = ("success", f"Correct! +{pts} points.")
        st.session_state.do_balloons = True
    else:
        st.session_state.last_submit = ("error", "Wrong flag.")

    # ✅ Clear input SAFELY inside callback
    st.session_state[flag_key] = ""

# ----------------------------
# App UI
# ----------------------------
st.set_page_config(page_title="Mini CTF Practice", layout="wide")
init_state()

# Load bank (if JSON is invalid, you'll get JSONDecodeError—fix commas/quotes)
bank = load_bank(BANK_PATH)

st.title("Mini Jeopardy CTF Practice (Duo Ready)")

with st.sidebar:
    st.header("Room Setup")
    st.caption("Use the same Room Code with your duo to get the same board.")

    st.session_state.player_name = st.text_input("Your name", value=st.session_state.player_name, placeholder="e.g., Dani")
    st.session_state.room_code = st.text_input("Room code", value=st.session_state.room_code, placeholder="e.g., REHACK-APR29")

    c1, c2 = st.columns(2)

    if c1.button("Start / Join Room", use_container_width=True):
        if not st.session_state.room_code.strip():
            st.error("Room code is required.")
        else:
            seed = abs(hash(st.session_state.room_code.strip().lower())) % (10**9)
            st.session_state.room_seed = seed
            if st.session_state.room_started_at is None:
                st.session_state.room_started_at = now_epoch()
            st.success(f"Joined room: {st.session_state.room_code}")

    if c2.button("Reset (this browser)", use_container_width=True):
        st.session_state.room_started_at = None
        st.session_state.room_seed = None
        st.session_state.selected = None
        st.session_state.solved = set()
        st.session_state.score = 0
        st.session_state.team_log = []
        st.session_state.last_submit = None
        st.session_state.do_balloons = False
        st.info("Reset done (this browser session).")

    st.divider()
    st.header("Challenge Bank")
    st.caption("Edit challenge_bank.json. Keep unique IDs per challenge.")
    st.write("Counts:")
    for c in CATEGORIES:
        st.write(f"- {CATEGORY_LABELS[c]}: {len(bank.get(c, []))}")

# Must join room first
if not st.session_state.room_seed or not st.session_state.room_started_at:
    st.warning("Enter a Room Code in the sidebar, then click **Start / Join Room**.")
    st.stop()

# Countdown + score
rem = remaining_seconds(st.session_state.room_started_at)

top1, top2, top3 = st.columns([2, 1, 1])
with top1:
    st.subheader(f"Room: {st.session_state.room_code}")
with top2:
    st.metric("Time left", fmt_hms(rem))
with top3:
    st.metric("Your score", st.session_state.score)

if rem <= 0:
    st.error("Time is up. Reset the room to play again (sidebar).")
    st.stop()

room_board = build_room_challenges(bank, st.session_state.room_seed)

st.caption("Board is randomized by Room Code. Each category shows up to 5 challenges.")

# Board tiles
cols = st.columns(len(CATEGORIES))

def choose_challenge(category: str, ch_id: str):
    st.session_state.selected = (category, ch_id)

for i, cat in enumerate(CATEGORIES):
    with cols[i]:
        st.markdown(f"### {CATEGORY_LABELS[cat]}")
        if not room_board.get(cat):
            st.info("No challenges in bank yet.")
            continue

        for ch in room_board[cat]:
            cid = ch.get("id", "")
            title = ch.get("title", "Untitled")
            pts = points_for(ch)
            solved = cid in st.session_state.solved

            label = f"{title} ({pts})"
            if solved:
                label = f"✅ {label}"

            st.button(
                label,
                key=f"tile_{cat}_{cid}",
                use_container_width=True,
                on_click=choose_challenge,
                args=(cat, cid)
            )

# Selected challenge panel
st.divider()

if not st.session_state.selected:
    st.info("Click a challenge tile to open it.")
    st.stop()

sel_cat, sel_id = st.session_state.selected

selected_ch = None
for ch in room_board.get(sel_cat, []):
    if ch.get("id") == sel_id:
        selected_ch = ch
        break

if not selected_ch:
    st.warning("That challenge is not on the current board anymore (bank changed). Click another tile.")
    st.stop()

# Show submit result messages (from callback)
if st.session_state.last_submit:
    kind, msg = st.session_state.last_submit
    if kind == "success":
        st.success(msg)
    else:
        st.error(msg)
    st.session_state.last_submit = None

if st.session_state.do_balloons:
    st.balloons()
    st.session_state.do_balloons = False

st.markdown(f"## {CATEGORY_LABELS[sel_cat]} → {selected_ch.get('title','Untitled')}")
st.markdown(selected_ch.get("prompt", "") or "")

render_tags_and_difficulty(selected_ch)
render_external_link(selected_ch)
render_attachments(selected_ch)

# Hint (nice rendering)
hint = selected_ch.get("hint", "")
if hint:
    with st.expander("Hint"):
        st.code(hint, language="text")

already = sel_id in st.session_state.solved
if already:
    st.success("You already solved this challenge (in this browser session).")

# Flag input (keyed per challenge)
flag_key = f"flag_input_{sel_cat}_{sel_id}"
if flag_key not in st.session_state:
    st.session_state[flag_key] = ""

st.text_input(
    "Submit flag",
    placeholder="flag{...}",
    disabled=already,
    key=flag_key
)

st.button(
    "Submit",
    type="primary",
    disabled=already,
    on_click=handle_submit,
    args=(
        flag_key,
        selected_ch.get("flag", ""),
        sel_id,
        points_for(selected_ch),
        st.session_state.player_name or "Player"
    )
)

# Writeup (optional; show after solve / always)
render_writeup(selected_ch, solved=(sel_id in st.session_state.solved))

# Local scoreboard
st.divider()
st.subheader("Local Solve Log (this browser)")
if not st.session_state.team_log:
    st.caption("No solves yet.")
else:
    for ts, player, cid, pts in reversed(st.session_state.team_log):
        st.write(f"- {time.strftime('%H:%M:%S', time.localtime(ts))} — **{player}** solved `{cid}` (+{pts})")

st.caption("Want shared duo scoreboard + shared timer across devices? Next step is adding Supabase.")
