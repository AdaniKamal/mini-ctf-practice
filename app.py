import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Dict, List, Any, Tuple

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
    "misc": "Misc"
}

# ----------------------------
# Helpers
# ----------------------------
def load_bank(path: str) -> Dict[str, List[Dict[str, Any]]]:
    if not os.path.exists(path):
        return {c: [] for c in CATEGORIES}
    with open(path, "r", encoding="utf-8") as f:
        bank = json.load(f)
    # Ensure all categories exist
    for c in CATEGORIES:
        bank.setdefault(c, [])
    return bank

def normalize_flag(s: str) -> str:
    return (s or "").strip()

def now_epoch() -> int:
    return int(time.time())

def init_room_state():
    if "room_code" not in st.session_state:
        st.session_state.room_code = ""
    if "player_name" not in st.session_state:
        st.session_state.player_name = ""
    if "room_started_at" not in st.session_state:
        st.session_state.room_started_at = None
    if "room_seed" not in st.session_state:
        st.session_state.room_seed = None
    if "selected" not in st.session_state:
        st.session_state.selected = None
    if "solved" not in st.session_state:
        st.session_state.solved = set()  # challenge ids solved by this browser session
    if "score" not in st.session_state:
        st.session_state.score = 0
    if "team_log" not in st.session_state:
        # Lightweight team log stored in browser session; for real shared scoreboard you’d use DB
        st.session_state.team_log = []  # (timestamp, player, chall_id, points)

def seeded_sample(items: List[Dict[str, Any]], k: int, seed: int) -> List[Dict[str, Any]]:
    # Deterministic selection without importing random (keeps deployment simpler)
    if not items:
        return []
    # Simple hash-based ordering
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

def remaining_seconds(started_at: int) -> int:
    elapsed = now_epoch() - started_at
    return max(0, CTF_DURATION_SECONDS - elapsed)

def fmt_hms(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def points_for(ch: Dict[str, Any]) -> int:
    try:
        return int(ch.get("points", 0))
    except Exception:
        return 0

def render_tags_and_difficulty(ch: Dict[str, Any]):
    tags = ch.get("tags", [])
    difficulty = ch.get("difficulty", "")
    pieces = []
    if difficulty:
        pieces.append(f"**Difficulty:** {difficulty}")
    if tags:
        pieces.append("**Tags:** " + ", ".join(tags))
    if pieces:
        st.caption(" | ".join(pieces))

def render_external_link(ch: Dict[str, Any]):
    link = ch.get("external_link")
    if link:
        st.link_button("Open external link", link)

def render_attachments(ch: Dict[str, Any]):
    atts = ch.get("attachments", [])
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
    if not w:
        return False
    mode = (w.get("visible") or "after_solve").lower()
    if mode == "always":
        return True
    if mode == "after_solve":
        return solved
    return False  # "never" or unknown

def render_writeup(ch: Dict[str, Any], solved: bool):
    w = ch.get("writeup")
    if not w:
        return
    if can_show_writeup(ch, solved):
        with st.expander("Writeup / Solution"):
            st.markdown(w.get("content_md", ""), unsafe_allow_html=False)

# ----------------------------
# UI
# ----------------------------
st.set_page_config(page_title="Mini CTF Practice", layout="wide")
init_room_state()

bank = load_bank(BANK_PATH)

st.title("Mini Jeopardy CTF Practice (Duo Ready)")

with st.sidebar:
    st.header("Room Setup")
    st.caption("Share one Room Code with your duo so you both get the same randomized board + timer.")

    st.session_state.player_name = st.text_input("Your name", value=st.session_state.player_name, placeholder="e.g., Dani")
    st.session_state.room_code = st.text_input("Room code", value=st.session_state.room_code, placeholder="e.g., REHACK-APR29")

    colA, colB = st.columns(2)

    if colA.button("Start / Join Room", use_container_width=True):
        if not st.session_state.room_code.strip():
            st.error("Room code is required.")
        else:
            # Room seed derived from room code (deterministic)
            seed = abs(hash(st.session_state.room_code.strip().lower())) % (10**9)
            st.session_state.room_seed = seed
            if st.session_state.room_started_at is None:
                st.session_state.room_started_at = now_epoch()
            st.success(f"Joined room: {st.session_state.room_code}")

    if colB.button("Reset (this browser)", use_container_width=True):
        st.session_state.room_started_at = None
        st.session_state.room_seed = None
        st.session_state.selected = None
        st.session_state.solved = set()
        st.session_state.score = 0
        st.session_state.team_log = []
        st.info("Reset done for this browser session.")

    st.divider()
    st.header("Challenge Bank")
    st.caption("Edit challenge_bank.json to add more challenges. Keep unique IDs per challenge.")
    st.write(f"Loaded categories: {', '.join(CATEGORIES)}")
    st.write("Counts:")
    for c in CATEGORIES:
        st.write(f"- {CATEGORY_LABELS[c]}: {len(bank.get(c, []))}")

# Must join a room first
if not st.session_state.room_seed or not st.session_state.room_started_at:
    st.warning("Enter a Room Code in the sidebar, then click **Start / Join Room**.")
    st.stop()

room_board = build_room_challenges(bank, st.session_state.room_seed)

# Top bar: countdown + score
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

st.caption("Board is randomized by Room Code. Each category shows up to 5 challenges from your bank.")

# Board view: category columns with clickable challenge tiles
cols = st.columns(len(CATEGORIES))

def challenge_tile(ch: Dict[str, Any], category: str):
    ch_id = ch.get("id", "")
    solved = ch_id in st.session_state.solved
    title = ch.get("title", "Untitled")
    pts = points_for(ch)
    label = f"{title} ({pts})"
    if solved:
        label = f"✅ {label}"
    if st.button(label, key=f"btn-{category}-{ch_id}", use_container_width=True):
        st.session_state.selected = (category, ch_id)

for i, c in enumerate(CATEGORIES):
    with cols[i]:
        st.markdown(f"### {CATEGORY_LABELS[c]}")
        for ch in room_board.get(c, []):
            challenge_tile(ch, c)
        if not room_board.get(c):
            st.info("No challenges in bank yet.")

# Selected challenge panel
st.divider()
sel = st.session_state.selected
if not sel:
    st.info("Click a challenge tile to open it.")
    st.stop()

sel_cat, sel_id = sel

# Find selected challenge
selected_ch = None
for ch in room_board.get(sel_cat, []):
    if ch.get("id") == sel_id:
        selected_ch = ch
        break

if not selected_ch:
    st.warning("That challenge is not on the current board (maybe bank changed). Click another tile.")
    st.stop()

st.markdown(f"## {CATEGORY_LABELS[sel_cat]} → {selected_ch.get('title','Untitled')}")
st.write(selected_ch.get("prompt", ""))
render_tags_and_difficulty(selected_ch)
render_external_link(selected_ch)
render_attachments(selected_ch)

hint = selected_ch.get("hint", "")
if hint:
    with st.expander("Hint"):
        st.code(hint, language="text")

already = sel_id in st.session_state.solved
if already:
    st.success("You already solved this challenge in this browser session.")

flag_key = f"flag_input_{sel_cat}_{sel_id}"
if flag_key not in st.session_state:
    st.session_state[flag_key] = ""

flag_in = st.text_input(
    "Submit flag",
    placeholder="flag{...}",
    disabled=already,
    key=flag_key
)

if submit:
    correct = normalize_flag(selected_ch.get("flag", ""))
    got = normalize_flag(flag_in)

    st.session_state[flag_key] = ""
    st.rerun()

    if not got:
        st.error("Flag cannot be empty.")
    elif got == correct:
        pts = points_for(selected_ch)
        st.session_state.solved.add(sel_id)
        st.session_state.score += pts
        st.session_state.team_log.append((now_epoch(), st.session_state.player_name or "Player", sel_id, pts))
        st.success(f"Correct! +{pts} points.")
        st.balloons()
    else:
        st.error("Wrong flag.")

render_writeup(selected_ch, solved=(sel_id in st.session_state.solved))

# Simple local scoreboard (per browser)
st.divider()
st.subheader("Local Solve Log (this browser)")
if not st.session_state.team_log:
    st.caption("No solves yet.")
else:
    for ts, player, cid, pts in reversed(st.session_state.team_log):
        st.write(f"- {time.strftime('%H:%M:%S', time.localtime(ts))} — **{player}** solved `{cid}` (+{pts})")

st.caption("For a real shared duo scoreboard across devices, add a DB (e.g., Supabase). Ask me and I’ll upgrade it.")

