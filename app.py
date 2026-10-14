"""포켓몬 카드 포트폴리오
내 컴퓨터:  pip install -r requirements.txt  ->  streamlit run app.py
클라우드:   Streamlit Cloud 비밀값(secrets)에 supabase 설정이 있으면 회원가입·로그인이 켜져요 (secrets.toml.example 참고)
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import traceback
import uuid
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

import importlib

import portfolio_core as core
import storage

importlib.reload(core)  # 파일을 바꾼 뒤 앱을 다시 켜지 않아도 새 계산 코드를 쓰게
importlib.reload(storage)

APP_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = APP_DIR / "settings.json"
UP, DOWN = "#e34948", "#2a78d6"  # 국내 관례: 상승 빨강, 하락 파랑

st.set_page_config(page_title="pokefolio", page_icon="🃏", layout="wide",
                   initial_sidebar_state="collapsed")

PAGES = {  # 왼쪽 위 화살표로 여는 메뉴
    "home": ("홈", ":material/donut_large:"),
    "cards": ("보유 카드", ":material/style:"),
    "add": ("카드 추가", ":material/add_circle:"),
    "backup": ("백업", ":material/inventory_2:"),
}
page = st.session_state.setdefault("page", "home")

st.markdown("""
<style>
@import url("https://fonts.googleapis.com/css2?family=Fredoka:wght@600;700&display=swap");
@import url("https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css");
:root {
  --pf-up: #ff6b6b;      /* 상승: 빨강 (국내 관례) */
  --pf-down: #5aa2ff;    /* 하락: 파랑 */
  --pf-line: rgba(255,255,255,.08);
  --pf-card: #171a21;
  --pf-muted: #8b919c;
  --pf-accent: #f2b33d;
}
html, body, [class*="st-"], .stMarkdown, input, textarea, button {
  font-family: "Pretendard Variable", Pretendard, -apple-system, "Segoe UI", "Malgun Gothic", sans-serif !important;
}
[data-testid="stIconMaterial"], span[class*="material-symbols"], .material-symbols-rounded, .material-icons {
  font-family: "Material Symbols Rounded" !important;
}
.block-container { padding-top: 2.2rem; max-width: 1280px; }
[data-testid="stPopover"] button { border-radius: 10px; }
.pf-tile { margin-bottom: .45rem; }
[data-testid="stHeader"] { background: transparent; }

.pf-head { display:flex; align-items:baseline; justify-content:space-between; gap:1rem; flex-wrap:wrap; margin-bottom:1rem; }
.pf-title { font-size:1.55rem; font-weight:700; letter-spacing:-.02em; }
.pf-meta { color:var(--pf-muted); font-size:.85rem; font-variant-numeric:tabular-nums; }

.pf-stats { display:grid; grid-template-columns: 1fr 1fr; gap:.75rem; margin-bottom:.4rem; }
@media (max-width: 640px) { .pf-stats { grid-template-columns: 1fr; } }
.pf-stat { background:var(--pf-card); border:1px solid var(--pf-line); border-radius:14px; padding:1rem 1.15rem; min-width:0; }
.pf-hero { background:linear-gradient(135deg, #1d212b, #171a21); }
.pf-label { color:var(--pf-muted); font-size:.8rem; margin-bottom:.35rem; }
.pf-value { font-size:2rem; font-weight:700; letter-spacing:-.02em; line-height:1.15; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.pf-value.sm { font-size:1.35rem; }
.pf-sub { margin-top:.35rem; font-size:.85rem; color:var(--pf-muted); font-variant-numeric:tabular-nums; }
.pf-sub.up, .pf-tile-pl.up { color:var(--pf-up); }
.pf-sub.down, .pf-tile-pl.down { color:var(--pf-down); }
.pf-pill { display:inline-block; margin-left:.35rem; padding:.05rem .45rem; border-radius:999px; font-size:.75rem; font-weight:600;
  background:rgba(255,255,255,.06); }
.pf-pill.up { background:rgba(255,107,107,.14); color:var(--pf-up); }
.pf-pill.down { background:rgba(90,162,255,.14); color:var(--pf-down); }

.stTabs [data-baseweb="tab-list"] { gap:1.4rem; }
.stTabs [data-baseweb="tab"] { font-size:.95rem; padding:.6rem 0; }

.pf-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(170px, 1fr)); gap:1rem; margin:.5rem 0 1rem; }
.pf-tile { background:var(--pf-card); border:1px solid var(--pf-line); border-radius:14px; padding:.7rem; min-width:0;
  transition: transform .15s ease, border-color .15s ease; }
.pf-tile:hover { transform: translateY(-2px); border-color: rgba(242,179,61,.45); }
.pf-tile-img { position:relative; aspect-ratio:63/88; border-radius:8px; overflow:hidden; background:#0f1115; margin-bottom:.6rem; }
.pf-tile-img img { width:100%; height:100%; object-fit:cover; display:block; }
.pf-noimg { width:100%; height:100%; display:flex; align-items:center; justify-content:center; color:var(--pf-muted);
  font-size:.8rem; border:1px dashed var(--pf-line); border-radius:8px; }
.pf-badge { position:absolute; top:.4rem; left:.4rem; background:var(--pf-accent); color:#1a1300; font-size:.7rem; font-weight:700;
  padding:.1rem .45rem; border-radius:6px; }
.pf-tile-name { font-weight:600; font-size:.9rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.pf-tile-set { color:var(--pf-muted); font-size:.75rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; margin-bottom:.35rem; }
.pf-tile-val { font-weight:700; font-variant-numeric:tabular-nums; }
.pf-tile-val.muted { color:var(--pf-muted); font-weight:500; font-size:.85rem; }
.pf-tile-pl { font-size:.8rem; color:var(--pf-muted); font-variant-numeric:tabular-nums; }

.pf-empty { text-align:center; padding:3rem 1rem; color:var(--pf-muted); border:1px dashed var(--pf-line); border-radius:14px; }
.pf-empty b { color:inherit; font-size:1.05rem; }
.pf-legend { display:flex; flex-direction:column; gap:.15rem; }
.pf-leg { display:grid; grid-template-columns: 12px 1fr auto 3.6rem; align-items:center; gap:.6rem; padding:.45rem .2rem;
  border-bottom:1px solid var(--pf-line); font-size:.9rem; }
.pf-leg:last-child { border-bottom:none; }
.pf-sw { width:12px; height:12px; border-radius:3px; }
.pf-leg-name { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; min-width:0; }
.pf-leg-val, .pf-leg-pct { font-variant-numeric:tabular-nums; text-align:right; }
.pf-leg-pct { color:var(--pf-muted); }
.pf-pl { border:1px solid var(--pf-line); border-radius:14px; overflow:hidden; margin-bottom:1.2rem; }
.pf-pl-row { display:grid; grid-template-columns: 1fr auto 9.5rem; align-items:center; gap:1rem; padding:.7rem 1rem;
  border-bottom:1px solid var(--pf-line); }
.pf-pl-row:last-child { border-bottom:none; }
.pf-pl-row.total { background:var(--pf-card); }
.pf-pl-name { min-width:0; display:flex; flex-direction:column; }
.pf-pl-name b { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.pf-pl-name span, .pf-pl-cost span { color:var(--pf-muted); font-size:.78rem; }
.pf-pl-cost { display:flex; flex-direction:column; text-align:right; font-size:.85rem; font-variant-numeric:tabular-nums; }
.pf-pl-num { display:flex; flex-direction:column; text-align:right; font-weight:700; font-size:1.05rem;
  font-variant-numeric:tabular-nums; color:var(--pf-muted); }
.pf-pl-num span { font-size:.8rem; font-weight:600; }
.pf-pl-num.up { color:var(--pf-up); }
.pf-pl-num.down { color:var(--pf-down); }
@media (max-width: 640px) { .pf-pl-row { grid-template-columns: 1fr auto; } .pf-pl-cost { display:none; } }
.pf-nav-title { color:var(--pf-muted); font-size:.75rem; letter-spacing:.06em; margin:.2rem 0 .4rem; }
[data-testid="stSidebar"] .stButton button { justify-content:flex-start; border-radius:10px; }
.pf-invest { margin-bottom:1.1rem; }
.pf-legend-title { color:var(--pf-muted); font-size:.8rem; margin:0 0 .3rem .2rem; }
.pf-me { font-weight:700; font-size:1.05rem; margin-bottom:.2rem; }
.pf-or { display:flex; align-items:center; gap:.7rem; color:var(--pf-muted); font-size:.8rem; margin:1rem 0 .6rem; }
.pf-or::before, .pf-or::after { content:""; flex:1; height:1px; background:var(--pf-line); }
.pf-login-head { text-align:center; margin:2.6rem 0 1.6rem; display:flex; flex-direction:column; align-items:center; }
.pf-logo { filter: drop-shadow(0 10px 24px rgba(240,138,36,.25)); margin-bottom:.3rem; }
.pf-wordmark { font-family:"Fredoka", "Pretendard Variable", sans-serif !important; font-weight:700; font-size:3rem;
  letter-spacing:-.01em; line-height:1; }
.pf-wordmark span { font-family:inherit !important; }
.pf-wordmark .pk { color:#f4f2ee; }
.pf-wordmark .fo { background:linear-gradient(135deg,#ffd166,#f08a24); -webkit-background-clip:text; background-clip:text; color:transparent; }
.pf-tagline { color:var(--pf-muted); font-size:.95rem; margin-top:.7rem; }
.pf-brand { display:flex; align-items:center; gap:.45rem; min-width:0; }
.pf-logo-sm { flex:none; filter: drop-shadow(0 4px 10px rgba(240,138,36,.25)); }
.pf-wordmark.sm { font-size:1.75rem; }
.pf-page { color:var(--pf-muted); font-size:1rem; font-weight:600; margin-left:.4rem; padding-left:.7rem;
  border-left:1px solid var(--pf-line); white-space:nowrap; }
.pf-head { align-items:center; }
@media (prefers-reduced-motion: reduce) { .pf-tile { transition:none; } .pf-tile:hover { transform:none; } }
</style>
""", unsafe_allow_html=True)




def won(x, sign=False):
    if x is None or pd.isna(x):
        return "–"
    if sign:
        return f"{'+' if x >= 0 else '-'}₩{abs(x):,.0f}"
    return f"₩{x:,.0f}"


def why(e: Exception) -> str:
    """오류 원인을 짧게 (비밀값은 들어가지 않음) + 서버 로그에 자세히"""
    traceback.print_exc()
    msg = str(e).replace(SB_KEY or "\x00", "***") if "SB_KEY" in globals() else str(e)
    return f"{type(e).__name__}: {msg[:180]}"


def secret(*path, default=None):
    try:
        v = st.secrets
        for k in path:
            v = v[k]
        return v
    except Exception:
        return default


# ---------------------------------------------------------------- 저장소: 클라우드(Supabase) 또는 내 컴퓨터
SB_URL, SB_KEY = secret("supabase", "url"), secret("supabase", "service_key")
CLOUD = bool(SB_URL and SB_KEY)
GOOGLE = CLOUD and bool(secret("auth", "google", "client_id")) and hasattr(st, "login")
if CLOUD:
    store = storage.SupabaseStore(SB_URL, SB_KEY)
    core.LOG_PATH = None
else:
    store = storage.LocalStore(APP_DIR)
    core.LOG_PATH = APP_DIR / "api_log.json"
price_cache = storage.PriceCache(store)


LOGO_SVG = """<svg class="pf-logo" viewBox="0 0 96 96" width="88" height="88" role="img" aria-label="pokefolio 로고">
  <defs>
    <linearGradient id="pfFront" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#ffd166"/><stop offset="1" stop-color="#f08a24"/>
    </linearGradient>
    <linearGradient id="pfBack" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#3a4150"/><stop offset="1" stop-color="#262b36"/>
    </linearGradient>
  </defs>
  <g transform="rotate(-12 48 50)">
    <rect x="22" y="14" width="44" height="62" rx="8" fill="url(#pfBack)" stroke="#4b5363" stroke-width="1.5"/>
  </g>
  <g transform="rotate(9 48 50)">
    <rect x="30" y="20" width="44" height="62" rx="8" fill="url(#pfFront)"/>
    <rect x="35" y="25" width="34" height="26" rx="4" fill="#ffffff" fill-opacity=".28"/>
    <rect x="35" y="56" width="22" height="4" rx="2" fill="#ffffff" fill-opacity=".55"/>
    <rect x="35" y="64" width="15" height="4" rx="2" fill="#ffffff" fill-opacity=".38"/>
  </g>
  <path d="M74 12 L77 21 L86 24 L77 27 L74 36 L71 27 L62 24 L71 21 Z" fill="#fff4cc"/>
  <path d="M18 70 L19.6 74.4 L24 76 L19.6 77.6 L18 82 L16.4 77.6 L12 76 L16.4 74.4 Z" fill="#f2b33d"/>
</svg>"""


def login_screen():
    st.markdown(f"""
<div class="pf-login-head">
  {LOGO_SVG}
  <div class="pf-wordmark" aria-label="pokefolio"><span class="pk">poke</span><span class="fo">folio</span></div>
  <div class="pf-tagline">내 카드의 시세와 손익을 한눈에</div>
</div>""", unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        if GOOGLE:
            st.button("Google로 계속하기", icon=":material/account_circle:", type="primary",
                      use_container_width=True, on_click=st.login, args=("google",))
            st.markdown('<div class="pf-or">또는 아이디로</div>', unsafe_allow_html=True)
        mode = st.segmented_control("로그인", ["로그인", "회원가입"], default="로그인", key="auth_mode",
                                    label_visibility="collapsed") or "로그인"
        with st.form("auth", border=True):
            uid_in = st.text_input("아이디", placeholder="영문 소문자·숫자 3~20자", autocomplete="username")
            pw = st.text_input("비밀번호", type="password", placeholder="8자 이상",
                               autocomplete="current-password" if mode == "로그인" else "new-password")
            pw2 = st.text_input("비밀번호 확인", type="password") if mode == "회원가입" else None
            go = st.form_submit_button(mode, type="secondary" if GOOGLE else "primary", use_container_width=True)
        if go:
            try:
                if mode == "회원가입":
                    if pw != pw2:
                        raise storage.AuthError("비밀번호 확인이 맞지 않아요.")
                    user = store.sign_up(uid_in, pw)
                else:
                    user = store.sign_in(uid_in, pw)
            except storage.AuthError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"서버에 연결하지 못했어요. 이 내용을 알려 주세요 → {why(e)}")
            else:
                for k in ("pf", "results", "picked", "trash", "refresh_log", "api"):
                    st.session_state.pop(k, None)
                st.session_state.user = user
                st.session_state.page = "home"
                st.rerun()
        st.caption("비밀번호를 잊으면 찾을 수 없어요 (메일 주소를 받지 않아요). 브라우저의 비밀번호 저장을 쓰면 편해요.")


def logout():
    google = (st.session_state.get("user") or {}).get("provider") == "google"
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    if google:
        st.logout()  # 구글 로그인 쿠키도 지우고 새로 고침
    st.rerun()


# 구글로 돌아온 사람은 이 앱 계정과 연결
if GOOGLE and not st.session_state.get("user") and st.user.is_logged_in:
    try:
        st.session_state.user = store.google_user(st.user.get("sub"), st.user.get("email") or "",
                                                  st.user.get("name") or "")
    except storage.AuthError as e:
        st.error(str(e))
        st.button("다시 로그인", on_click=st.logout)
        st.stop()
    except Exception as e:
        st.error(f"서버에 연결하지 못했어요. 이 내용을 알려 주세요 → {why(e)}")
        st.stop()

if CLOUD and not st.session_state.get("user"):
    login_screen()
    st.stop()
user = st.session_state.get("user") or {"id": "local", "login_id": ""}
uid = user["id"]

# ---------------------------------------------------------------- 상태
if "pf" not in st.session_state:
    try:
        st.session_state.pf = store.load_portfolio(uid)
    except json.JSONDecodeError:
        st.error("portfolio.json 파일이 손상돼서 읽지 못했어요. 백업 파일로 복원해 주세요.")
        st.session_state.pf = {"cards": [], "history": []}
    except Exception as e:
        st.error(f"내 카드를 불러오지 못했어요. 이 내용을 알려 주세요 → {why(e)}")
        st.stop()
pf = st.session_state.pf
pf.setdefault("cards", [])
pf.setdefault("history", [])
settings = {} if CLOUD else core.load_json(SETTINGS_FILE, {})


def persist():
    try:
        store.save_portfolio(uid, pf)
    except Exception as e:
        st.error(f"저장하지 못했어요. 이 내용을 알려 주세요 → {why(e)}")


# ---------------------------------------------------------------- 사이드바: API 키
with st.sidebar:
    st.markdown('<div class="pf-nav-title">메뉴</div>', unsafe_allow_html=True)
    for key, (label, icon) in PAGES.items():
        if st.button(label, icon=icon, key=f"nav_{key}", use_container_width=True,
                     type="primary" if page == key else "secondary"):
            st.session_state.page = key
            st.session_state.seen_menu_hint = True  # 메뉴를 한 번 쓰면 안내 문구 숨김
            st.rerun()
    st.divider()
    user_budget = None
    if CLOUD:
        api_key = secret("ppt_api_key", default="")
        user_budget = storage.Budget(store, uid, int(secret("daily_credit_limit", default=30)))
        st.markdown(f'<div class="pf-nav-title">계정</div><div class="pf-me">{html.escape(user["login_id"])}</div>',
                    unsafe_allow_html=True)
        try:
            st.caption(f"오늘 남은 시세 조회: {user_budget.left()} / {user_budget.limit}크레딧")
        except Exception:
            pass
        if st.button("로그아웃", icon=":material/logout:", use_container_width=True):
            logout()
        if user.get("provider") == "google":
            with st.expander("탈퇴"):
                sure = st.checkbox("계정과 카드 기록을 모두 지울게요", key="acc_sure_g")
                if st.button("탈퇴", key="acc_delete_g", disabled=not sure):
                    try:
                        store.delete_google_account(user)
                        logout()
                    except storage.AuthError as e:
                        st.error(str(e))
        else:
            with st.expander("비밀번호 변경 · 탈퇴"):
                old = st.text_input("지금 비밀번호", type="password", key="acc_old")
                new = st.text_input("새 비밀번호", type="password", key="acc_new")
                if st.button("비밀번호 바꾸기", key="acc_change", disabled=not (old and new)):
                    try:
                        store.change_password(user, old, new)
                        st.success("비밀번호를 바꿨어요.")
                    except storage.AuthError as e:
                        st.error(str(e))
                st.divider()
                sure = st.checkbox("계정과 카드 기록을 모두 지울게요", key="acc_sure")
                if st.button("탈퇴", key="acc_delete", disabled=not (sure and old)):
                    try:
                        store.delete_account(user, old)
                        for k in list(st.session_state.keys()):
                            del st.session_state[k]
                        st.rerun()
                    except storage.AuthError as e:
                        st.error(str(e))
                st.caption("탈퇴하려면 위의 '지금 비밀번호'를 넣어 주세요.")
    else:
        st.markdown('<div class="pf-nav-title">설정</div>', unsafe_allow_html=True)
        default_key = os.environ.get("PPT_API_KEY") or settings.get("api_key", "")
        api_key = st.text_input("PokemonPriceTracker API 키", value=default_key, type="password", key="api_key")
        remember = st.checkbox("이 컴퓨터에 키 저장", value=bool(settings.get("api_key")),
                               help="같은 폴더의 settings.json에 저장돼요. 이 파일은 다른 사람과 공유하지 마세요.")
        if remember and api_key != settings.get("api_key"):
            core.save_json(SETTINGS_FILE, {**settings, "api_key": api_key})
        elif not remember and settings.get("api_key"):
            core.save_json(SETTINGS_FILE, {k: v for k, v in settings.items() if k != "api_key"})
        if not api_key:
            st.caption("키가 없으면 시세를 직접 입력해서 쓸 수 있어요. 키는 pokemonpricetracker.com/api-keys 에서 무료로 받을 수 있어요.")

    if ("api" not in st.session_state or st.session_state.api.key != api_key.strip()
            or st.session_state.get("api_owner") != uid):
        st.session_state.api = core.PriceTracker(api_key, budget=user_budget)
        st.session_state.api_owner = uid
    api: core.PriceTracker = st.session_state.api
    if api.credits_left is not None and not CLOUD:
        st.metric("오늘 남은 크레딧", api.credits_left)

    @st.cache_data(ttl=3600, show_spinner=False)
    def cached_fx():
        return core.fx_latest()

    st.divider()
    live_fx, fx_src = cached_fx()
    if live_fx:
        fx = live_fx
        if not CLOUD and live_fx != settings.get("last_fx"):
            core.save_json(SETTINGS_FILE, {**core.load_json(SETTINGS_FILE, {}), "last_fx": live_fx})
        st.caption(f"시세는 달러로 받아서 원으로 바꿔 보여줘요. 1달러 = ₩{fx:,.2f} ({fx_src})")
    else:
        fx = st.number_input("환율을 가져오지 못했어요. 1달러 =", min_value=100.0, max_value=5000.0, step=1.0,
                             value=float(settings.get("last_fx") or 1350.0), key="fx_fallback")



# ---------------------------------------------------------------- 요약
df = core.compute(pf["cards"], fx)
t = core.totals(df)
last_update = max((c.get("price_updated") or "" for c in pf["cards"]), default="")


def clear(prefix: str):
    for key in [x for x in st.session_state if str(x).startswith(prefix)]:
        del st.session_state[key]


def tone(v):
    if v is None or pd.isna(v) or abs(v) < 0.5:
        return "flat"
    return "up" if v > 0 else "down"


pct_txt = f"{t['pl_pct']:+.1f}%" if t["pl_pct"] is not None else "–"
meta = [f"카드 {t['count']}장", f"1달러 ₩{fx:,.0f}"]
if last_update:
    meta.append(f"시세 {last_update}")
small_logo = LOGO_SVG.replace('class="pf-logo"', 'class="pf-logo-sm"').replace('width="88" height="88"', 'width="40" height="40"')
sub = "" if page == "home" else f'<span class="pf-page">{html.escape(PAGES[page][0])}</span>'

st.markdown(f"""
<div class="pf-head">
  <div class="pf-brand">{small_logo}<span class="pf-wordmark sm"><span class="pk">poke</span><span class="fo">folio</span></span>{sub}</div>
  <div class="pf-meta">{' · '.join(html.escape(m) for m in meta)}</div>
</div>
""", unsafe_allow_html=True)
if page == "home":
    if t["unpriced"]:
        st.caption(f"시세가 없는 카드 {t['unpriced']}종은 합계에서 빠져 있어요.")
    if st.session_state.get("seen_menu_hint") is None:
        st.caption("왼쪽 위 화살표( » )를 누르면 보유 카드 · 카드 추가 · 백업 메뉴와 설정이 나와요.")

# ---------------------------------------------------------------- 보유 카드
if page == "cards":
    trash = st.session_state.get("trash")
    if trash:
        with st.container(border=True):
            u1, u2 = st.columns([5, 1], vertical_alignment="center")
            u1.markdown(f"카드 {len(trash)}종을 지웠어요.")
            if u2.button("되돌리기", icon=":material/undo:", use_container_width=True):
                for pos, c in sorted(trash, key=lambda x: x[0]):
                    pf["cards"].insert(min(pos, len(pf["cards"])), c)
                persist()
                st.session_state.trash = None
                st.session_state.editor_ver = st.session_state.get("editor_ver", 0) + 1
                st.rerun()

    if df.empty:
        st.markdown('<div class="pf-empty"><b>아직 등록한 카드가 없어요</b><br>'
                    "왼쪽 메뉴의 '카드 추가'에서 세트를 고르고 첫 카드를 등록해 보세요.</div>", unsafe_allow_html=True)
    else:
        top1, top2 = st.columns([4, 1.6], vertical_alignment="center")
        query = top1.text_input("카드 찾기", placeholder="카드명이나 세트로 찾기", label_visibility="collapsed",
                                key="list_filter", icon=":material/search:")
        need = core.estimate_credits(pf["cards"])
        if top2.button(f"시세 갱신 · {need}크레딧", icon=":material/refresh:", disabled=not api_key or need == 0,
                       use_container_width=True,
                       help="모든 카드 시세를 새로 받아요. 미감정 카드 1크레딧, 등급 카드 2크레딧이고 무료 플랜은 하루 100크레딧이에요."):
            bar = st.progress(0.0, text="시세를 가져오는 중…")
            st.session_state.refresh_log = core.refresh_all(
                pf["cards"], api, lambda p, n: bar.progress(p, text=f"{n} 조회 완료"), cache=price_cache)
            core.snapshot(pf, core.compute(pf["cards"], fx), fx)
            persist()
            st.rerun()
        if st.session_state.get("refresh_log"):
            with st.expander("최근 시세 갱신 결과"):
                for name, msg in st.session_state.refresh_log:
                    st.write(f"- {name}: {msg}")

        by_id = {c["id"]: c for c in pf["cards"]}
        view = df.copy()
        view["shown_name"] = [core.display_name(n, num) for n, num in zip(view["name"], view["number"])]
        if query.strip():
            ql = query.strip().lower()
            view = view[view["shown_name"].str.lower().str.contains(ql, regex=False)
                        | view["set"].str.lower().str.contains(ql, regex=False)]
        if view.empty:
            st.caption("찾는 카드가 없어요.")
        view = view.sort_values("value", ascending=False, na_position="last")

        per_row = 5
        records = list(view.itertuples(index=False))
        for start_i in range(0, len(records), per_row):
            cols = st.columns(per_row)
            for col, r in zip(cols, records[start_i:start_i + per_row]):
                c = by_id[r.id]
                with col:
                    img = (f'<img src="{html.escape(r.image)}" loading="lazy" alt="">' if r.image
                           else '<div class="pf-noimg">사진 없음</div>')
                    badge = '<span class="pf-badge">팩</span>' if r.acquired == "팩 개봉" else ""
                    if pd.isna(r.value):
                        price = '<div class="pf-tile-val muted">시세 없음</div>'
                    else:
                        pct = "" if pd.isna(r.pl_pct) else f" · {r.pl_pct:+.1f}%"
                        price = (f'<div class="pf-tile-val">{won(r.value)}</div>'
                                 f'<div class="pf-tile-pl {tone(r.pl)}">{won(r.pl, sign=True)}{pct}</div>')
                    qty = f" · {int(r.qty)}장" if r.qty > 1 else ""
                    st.markdown(f'<div class="pf-tile"><div class="pf-tile-img">{img}{badge}</div>'
                                f'<div class="pf-tile-name">{html.escape(r.shown_name)}</div>'
                                f'<div class="pf-tile-set">{html.escape(r.set)} · {html.escape(r.grade)}{qty}</div>'
                                f'{price}</div>', unsafe_allow_html=True)

                    with st.popover("관리", icon=":material/edit:", use_container_width=True):
                        k = f"e_{r.id}"
                        cur = core.edit_row(c, fx)
                        st.markdown(f"**{html.escape(r.shown_name)}**  \n{html.escape(r.set)} {html.escape(r.number)}")
                        g1, g2 = st.columns(2)
                        grade = g1.selectbox("등급", core.GRADES, key=f"{k}_grade",
                                             index=core.GRADES.index(cur["grade"]) if cur["grade"] in core.GRADES else 0)
                        qty_in = g2.number_input("수량", min_value=1, step=1, value=cur["qty"], key=f"{k}_qty")
                        acq_labels = list(core.ACQUIRED.values())
                        acq = st.radio("얻은 방법", acq_labels, horizontal=True, key=f"{k}_acq",
                                       index=acq_labels.index(cur["acquired"]))
                        h1, h2 = st.columns(2)
                        unit = h1.number_input("1장 매입가(원)" if acq == "매입" else "1장 팩 값(원)", min_value=0,
                                               step=1000, value=int(cur["unit_cost"]), key=f"{k}_cost",
                                               help="투자금액에 들어가요. 팩에서 뽑은 카드는 0으로 둬도 돼요.")
                        when = h2.date_input("매입일" if acq == "매입" else "개봉일",
                                             value=cur["date"] or dt.date.today(), key=f"{k}_date")
                        price_in = st.number_input("1장 시세(원)", min_value=0, step=1000,
                                                   value=int(cur["cur"] or 0), key=f"{k}_cur",
                                                   help="직접 고치면 '직접 입력' 시세로 저장돼요. 시세 갱신을 하면 다시 API 값으로 바뀌어요.")
                        note = st.text_input("메모", value=cur["note"], key=f"{k}_note")
                        if st.button("저장", type="primary", icon=":material/check:", key=f"{k}_save",
                                     use_container_width=True):
                            new = {"grade": grade, "qty": qty_in, "acquired": acq, "unit_cost": unit, "date": when,
                                   "cur": price_in or None, "note": note}
                            if core.apply_edit(c, new, fx):
                                persist()
                                st.toast("저장했어요.")
                            clear(k)
                            st.rerun()
                        b1, b2 = st.columns(2)
                        if b1.button("시세 갱신", icon=":material/refresh:", key=f"{k}_ref", disabled=not api_key,
                                     use_container_width=True):
                            try:
                                st.toast(f"{r.shown_name}: {core.refresh_card(c, api, price_cache)}")
                                persist()
                            except core.ApiError as e:
                                st.toast(str(e))
                            clear(k)
                            st.rerun()
                        b2.link_button("eBay 판매가", core.ebay_sold_url(c), icon=":material/open_in_new:",
                                       use_container_width=True)
                        st.divider()
                        sure = st.checkbox("이 카드를 지울게요", key=f"{k}_sure")
                        if st.button("삭제", icon=":material/delete:", key=f"{k}_del", disabled=not sure,
                                     use_container_width=True):
                            st.session_state.trash = [(i, x) for i, x in enumerate(pf["cards"]) if x["id"] == r.id]
                            pf["cards"] = [x for x in pf["cards"] if x["id"] != r.id]
                            persist()
                            clear(k)
                            st.rerun()

# ---------------------------------------------------------------- 카드 추가
def acquire_inputs(prefix: str, default_how: str = "buy", default_price: float = 0.0, default_date=None):
    """획득 방법, 투자금액, 날짜 입력 (매입 / 팩 개봉)."""
    how = st.radio("어떻게 얻었나요?", list(core.ACQUIRED), format_func=core.ACQUIRED.get, horizontal=True,
                   index=list(core.ACQUIRED).index(default_how), key=f"{prefix}_how")
    c1, c2 = st.columns(2)
    if how == "buy":
        price = c1.number_input("1장 매입가(원)", min_value=0.0, step=1000.0, format="%.0f",
                                value=default_price, key=f"{prefix}_price")
    else:
        price = c1.number_input("1장 팩 값(원, 선택)", min_value=0.0, step=500.0, format="%.0f",
                                value=default_price, key=f"{prefix}_price",
                                help="투자금액에 들어가요. 비워 두면 0으로 계산해서 평가액이 그대로 이익이 돼요.")
    when = c2.date_input("매입일" if how == "buy" else "개봉일", value=default_date or dt.date.today(),
                         key=f"{prefix}_date")
    return how, price, when


def reset_keys(prefix: str):
    for k in [k for k in st.session_state if str(k).startswith(prefix)]:
        del st.session_state[k]


if page == "add":
    if not api_key:
        st.info("API 키를 사이드바에 넣으면 세트에서 카드를 골라 등록할 수 있어요. 지금은 아래 '직접 입력'만 쓸 수 있어요.")
    else:
        sets_cache = store.get_shared("sets") or {}
        l1, l2, l3 = st.columns([1, 4, 1.4])
        lang = l1.selectbox("언어", ["english", "japanese"], format_func=core.LANGS.get, key="add_lang")
        entry = sets_cache.get(lang, {})
        sets = entry.get("sets", [])
        if l3.button("세트 목록 새로고침" if sets else "세트 목록 불러오기", use_container_width=True,
                     help="요청 1번에 1크레딧이에요. 새 세트가 나왔을 때만 누르면 돼요."):
            try:
                with st.spinner("세트 목록을 불러오는 중…"):
                    sets = api.sets(lang)
                sets_cache[lang] = {"fetched": dt.date.today().isoformat(), "sets": sets}
                store.set_shared("sets", sets_cache)
                st.rerun()
            except core.ApiError as e:
                st.error(str(e))
        set_label = {f"{s['id']}|{s['name']}": s["name"] + (f"  ·  {s['release'][:4]}" if s["release"] else "")
                     for s in sets}
        chosen = l2.selectbox("세트", list(set_label), index=None, format_func=set_label.get,
                              placeholder="세트 이름을 입력해서 고르세요" if sets else "먼저 오른쪽에서 세트 목록을 불러오세요",
                              key="add_set")
        if entry.get("fetched"):
            st.caption(f"세트 {len(sets)}개 · {entry['fetched']} 기준. 세트를 고르지 않으면 전체에서 찾아요.")

        set_id, set_name = (chosen or "|").split("|", 1)
        ckey = f"{lang}|{set_id}"
        saved = (store.get_shared(f"setcards|{ckey}") or {}) if chosen else {}

        # 세트 카드 목록 저장: 저장해 두면 번호·이름 검색이 크레딧 없이 바로 돼요
        if chosen:
            with st.container(border=True):
                left = api.credits_left
                budget = max(0, int(left) - 5) if str(left or "").isdigit() else 95
                if user_budget:
                    budget = min(budget, user_budget.left())
                if saved.get("done"):
                    st.caption(f"이 세트 카드 {len(saved['cards'])}장이 저장돼 있어요. 번호나 이름으로 바로 찾아요 (크레딧 안 듦).")
                else:
                    have = len(saved.get("cards", []))
                    st.caption(("이 세트 카드 목록을 저장하면 카드 번호로 찾을 수 있고, 다음부터는 크레딧 없이 찾아요. "
                                "카드 1장당 1크레딧이고 크레딧이 모자라면 다음 날 이어서 받을 수 있어요.")
                               + (f" 지금까지 {have}장 저장됨." if have else ""))
                    if st.button(("이어서 저장" if have else "이 세트 카드 목록 저장") + f" (최대 {budget}크레딧)",
                                 disabled=budget < 1, key="save_set_cards"):
                        try:
                            with st.spinner("세트 카드 목록을 받는 중…"):
                                saved = core.load_set_cards(api, dict(saved), set_id, set_name, lang, budget)
                        except core.ApiError as e:
                            st.error(str(e))
                        else:
                            store.set_shared(f"setcards|{ckey}", saved)
                            st.rerun()

        with st.form("find"):
            f1, f2 = st.columns([4, 1])
            q = f1.text_input("포켓몬 이름(한글·영문) 또는 카드 번호", placeholder="피카츄 · pikachu · 276",
                              label_visibility="collapsed")
            go = f2.form_submit_button("찾기", use_container_width=True)
        if go and q.strip():
            st.session_state.pop("picked", None)
            st.session_state.results_lang = lang
            query, note = q.strip(), ""
            if core.HANGUL.search(query):
                names = store.get_shared("ko_names") or {}
                if not names:
                    with st.spinner("한글 포켓몬 이름표를 처음 한 번 받는 중…"):
                        names = core.fetch_ko_names()
                    if names:
                        store.set_shared("ko_names", names)
                query, unknown = core.translate_query(query, names)
                if not names:
                    st.warning("한글 이름표를 받지 못했어요. 인터넷 연결을 확인하거나 영문 이름으로 찾아 주세요.")
                elif unknown:
                    st.warning(f"'{' '.join(unknown)}'에 맞는 포켓몬을 못 찾았어요. 맞춤법을 확인하거나 영문으로 찾아 주세요.")
                if query:
                    note = f"'{q.strip()}' → '{query}'로 찾았어요. "
            if query:
                try:
                    if saved.get("cards"):
                        res = core.local_find(saved["cards"], query)
                        note += "저장된 세트 목록에서 찾아서 크레딧이 들지 않았어요."
                        if not res and not saved.get("done") and core.is_number_query(query):
                            note = "아직 저장되지 않은 카드일 수 있어요. 위에서 '이어서 저장'을 눌러 주세요."
                    else:
                        with st.spinner("찾는 중…"):
                            res = core.find_cards(api, query, set_id, set_name, lang)
                        note += "검색 결과 1장당 1크레딧이 들었어요."
                    st.session_state.results = res
                    st.session_state.results_note = note
                    if not res:
                        if core.is_number_query(query) and chosen and not saved.get("done"):
                            st.warning("번호로는 찾지 못했어요. 위의 '이 세트 카드 목록 저장'을 누르면 번호로 찾을 수 있어요.")
                        elif core.is_number_query(query) and not chosen:
                            st.warning("카드 번호로 찾으려면 먼저 세트를 골라 주세요.")
                        else:
                            st.warning("찾는 카드가 없어요. 세트를 바꾸거나 세트를 비우고 다시 찾아 보세요.")
                except core.ApiError as e:
                    st.error(str(e))

        results = st.session_state.get("results", [])
        if results and st.session_state.get("results_note"):
            st.caption(st.session_state.results_note)
        for i, raw in enumerate(results):
            s = core.card_summary(raw)
            price, _ = core.raw_price(raw)
            r1, r2, r3 = st.columns([1, 5, 1])
            if s["image"]:
                r1.image(s["image"], width=70)
            r2.markdown(f"**{s['name']}**  ·  {s['number']}  \n{s['set']} · {s['rarity']} · "
                        f"미감정 {won(price * fx) if price is not None else '시세 없음'}")
            if r3.button("담기", key=f"pick_{i}", use_container_width=True):
                st.session_state.picked = {**s, "raw_usd": price, "language": st.session_state.results_lang}
                reset_keys("pick_form")

        p = st.session_state.get("picked")
        if p:
            with st.container(border=True):
                st.markdown(f"#### {p['name']}  ·  {p['set']} {p['number']}")
                g1, g2 = st.columns(2)
                grade = g1.selectbox("등급", core.GRADES, key="pick_form_grade")
                qty = g2.number_input("수량", min_value=1, step=1, value=1, key="pick_form_qty")
                how, price, when = acquire_inputs("pick_form")
                if st.button("포트폴리오에 추가", type="primary", key="pick_form_add"):
                    card = {
                        "id": uuid.uuid4().hex[:10], "tcgPlayerId": p["tcgPlayerId"], "name": p["name"],
                        "set": p["set"], "number": p["number"], "language": p["language"], "grade": grade,
                        "qty": int(qty), "acquired": how, "buy_currency": "KRW", "buy_price": price,
                        "buy_date": when.isoformat(), "cur_usd": None, "price_source": "", "price_updated": "",
                        "image": p["image"], "note": "",
                    }
                    msg = ""
                    if grade == "Raw" and p.get("raw_usd") is not None:  # 검색 결과의 시세 그대로 (추가 크레딧 없음)
                        card.update(cur_usd=round(p["raw_usd"], 2), price_source="TCGPlayer 시세(prices.market)",
                                    price_updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
                    elif grade != "Raw":
                        try:
                            msg = core.refresh_card(card, api, price_cache)
                        except core.ApiError as e:
                            msg = str(e)
                    pf["cards"].append(card)
                    persist()
                    st.session_state.pop("picked", None)
                    reset_keys("pick_form")
                    st.toast(f"{card['name']} 추가했어요. {msg}")
                    st.rerun()

    with st.expander("직접 입력 (한국판처럼 API에 없는 카드)", expanded=not api_key):
        m1, m2, m3, m4 = st.columns(4)
        name = m1.text_input("카드명", key="man_name")
        set_name = m2.text_input("세트", key="man_set")
        number = m3.text_input("번호", key="man_number")
        langs = list(core.LANGS)
        language = m4.selectbox("언어", langs, format_func=core.LANGS.get, index=2, key="man_lang")
        n1, n2, n3 = st.columns(3)
        grade = n1.selectbox("등급", core.GRADES, key="man_grade")
        qty = n2.number_input("수량", min_value=1, step=1, value=1, key="man_qty")
        cur_krw = n3.number_input("현재 시세(원)", min_value=0.0, step=1000.0, format="%.0f", key="man_cur",
                                  help="eBay 판매 완료 가격 등에서 확인한 1장 시세. 영문판·일본판은 0으로 두면 API에서 찾아봐요.")
        how, price, when = acquire_inputs("man")
        if st.button("포트폴리오에 추가", key="man_add"):
            if not name.strip():
                st.error("카드명을 입력해 주세요.")
            else:
                card = {
                    "id": uuid.uuid4().hex[:10], "tcgPlayerId": "", "name": name.strip(), "set": set_name.strip(),
                    "number": number.strip(), "language": language, "grade": grade, "qty": int(qty),
                    "acquired": how, "buy_currency": "KRW", "buy_price": price, "buy_date": when.isoformat(),
                    "cur_usd": round(cur_krw / fx, 2) if cur_krw else None, "price_source": "직접 입력" if cur_krw else "",
                    "price_updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M") if cur_krw else "",
                    "image": "", "note": "",
                }
                msg = ""
                if not cur_krw and api_key and language in core.API_LANGS:
                    try:
                        msg = core.refresh_card(card, api, price_cache)
                    except core.ApiError as e:
                        msg = str(e)
                pf["cards"].append(card)
                persist()
                reset_keys("man")
                st.toast(f"{card['name']} 추가했어요. {msg}")
                st.rerun()

# ---------------------------------------------------------------- 차트
if page == "home":
    priced = df[df["value"].notna()].copy()
    if priced.empty:
        st.markdown(f'<div class="pf-stats"><div class="pf-stat"><div class="pf-label">투자금액</div>'
                    f'<div class="pf-value">{won(t["cost"])}</div><div class="pf-sub">매입가 + 팩 값</div></div></div>',
                    unsafe_allow_html=True)
        st.info("시세가 있는 카드가 생기면 평가액 원그래프가 나타나요.")
    else:
        # 평가액 비중 (원그래프). 색 순서는 색약 구분 검증을 거친 순서, '기타'는 회색
        PIE = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9"]
        sl = core.pie_slices(df)
        colors = [PIE[i] if not lab.startswith("기타 ") else "#6b6f78" for i, lab in enumerate(sl["label"])]
        p1, p2 = st.columns([1.15, 1], vertical_alignment="center")
        base = alt.Chart(sl).encode(
            theta=alt.Theta("value:Q", stack=True),
            order=alt.Order("order:Q"),
            color=alt.Color("label:N", scale=alt.Scale(domain=list(sl["label"]), range=colors), legend=None),
            tooltip=[alt.Tooltip("label:N", title="카드"), alt.Tooltip("value:Q", title="평가액(원)", format=",.0f"),
                     alt.Tooltip("share:Q", title="비중(%)", format=".1f")],
        )
        donut = base.mark_arc(innerRadius=118, outerRadius=172, stroke="#0f1115", strokeWidth=2, cornerRadius=3)
        pl_color = {"up": "#ff6b6b", "down": "#5aa2ff"}.get(tone(t["pl"]), "#8b919c")
        center = alt.Chart(pd.DataFrame([{"label": "총 평가액", "value": won(t["value"]),
                                          "pl": f"{won(t['pl'], sign=True)}  ({pct_txt})"}]))
        font = "Pretendard Variable, Pretendard, Malgun Gothic, sans-serif"
        value_size = 34 if len(won(t["value"])) <= 11 else 28  # 금액이 길면 조금 줄여 원 안에 맞춤
        p1.altair_chart(
            (donut
             + center.mark_text(fontSize=14, color="#8b919c", dy=-38, font=font).encode(text="label:N")
             + center.mark_text(fontSize=value_size, fontWeight=800, color="#f4f2ee", dy=-2, font=font).encode(text="value:N")
             + center.mark_text(fontSize=15, fontWeight=600, color=pl_color, dy=34, font=font).encode(text="pl:N")
             ).properties(height=380).configure_view(stroke=None),
            use_container_width=True,
        )
        legend = "".join(
            f'<div class="pf-leg"><span class="pf-sw" style="background:{col}"></span>'
            f'<span class="pf-leg-name">{html.escape(lab)}</span>'
            f'<span class="pf-leg-val">{won(v)}</span><span class="pf-leg-pct">{s:.1f}%</span></div>'
            for lab, v, s, col in zip(sl["label"], sl["value"], sl["share"], colors))
        p2.markdown(f'<div class="pf-stat pf-invest"><div class="pf-label">투자금액</div>'
                    f'<div class="pf-value sm">{won(t["cost"])}</div><div class="pf-sub">매입가 + 팩 값</div></div>'
                    f'<div class="pf-legend-title">카드별 평가액</div><div class="pf-legend">{legend}</div>',
                    unsafe_allow_html=True)

        # 카드별 손익 (숫자, 이익 빨강 / 손실 파랑)
        st.subheader("카드별 손익")
        rows_pl = priced.sort_values("pl", ascending=False)
        lines = []
        for r in rows_pl.itertuples(index=False):
            nm = core.display_name(r.name, r.number)
            pct = "" if pd.isna(r.pl_pct) else f"{r.pl_pct:+.1f}%"
            sub = f"{r.set} · {r.grade}" + (f" · {int(r.qty)}장" if r.qty > 1 else "") + \
                  (" · 팩 개봉" if r.acquired == "팩 개봉" else "")
            lines.append(
                f'<div class="pf-pl-row"><div class="pf-pl-name"><b>{html.escape(nm)}</b>'
                f'<span>{html.escape(sub)}</span></div>'
                f'<div class="pf-pl-cost">투자 {won(r.cost)}<span>평가 {won(r.value)}</span></div>'
                f'<div class="pf-pl-num {tone(r.pl)}">{won(r.pl, sign=True)}<span>{pct}</span></div></div>')
        total_pct = "" if t["pl_pct"] is None else f"{t['pl_pct']:+.1f}%"
        lines.append(
            f'<div class="pf-pl-row total"><div class="pf-pl-name"><b>합계</b><span>시세 있는 카드 {len(rows_pl)}종</span></div>'
            f'<div class="pf-pl-cost">투자 {won(t["cost"])}<span>평가 {won(t["value"])}</span></div>'
            f'<div class="pf-pl-num {tone(t["pl"])}">{won(t["pl"], sign=True)}'
            f'<span>{total_pct}</span></div></div>')
        st.markdown(f'<div class="pf-pl">{"".join(lines)}</div>', unsafe_allow_html=True)

    hist = pd.DataFrame(core.history_krw(pf.get("history", [])))
    st.subheader("평가액 추이")
    if len(hist) < 2:
        st.caption("'시세 전체 갱신'을 할 때마다 그날 평가액이 기록돼요. 이틀 이상 쌓이면 추이가 보여요.")
    else:
        hist["date"] = pd.to_datetime(hist["date"])
        long = hist.melt("date", ["value", "cost"], var_name="항목", value_name="원")
        long["항목"] = long["항목"].map({"value": "평가액", "cost": "투자금액"})
        st.altair_chart(
            alt.Chart(long).mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=50)).encode(
                x=alt.X("date:T", title=None, axis=alt.Axis(format="%m/%d")),
                y=alt.Y("원:Q", title="원", axis=alt.Axis(format=",.0f")),
                color=alt.Color("항목:N", scale=alt.Scale(domain=["평가액", "투자금액"], range=[DOWN, "#898781"]),
                                legend=alt.Legend(orient="top", title=None)),
                tooltip=[alt.Tooltip("date:T", title="날짜"), "항목:N", alt.Tooltip("원:Q", format=",.0f")],
            ),
            use_container_width=True,
        )

# ---------------------------------------------------------------- 백업
if page == "backup":
    st.write("카드 기록은 내 계정에 자동 저장돼요. 파일로 따로 보관하고 싶을 때 아래 기능을 쓰세요." if CLOUD else
             "데이터는 이 폴더의 `portfolio.json`에 자동 저장돼요. 다른 컴퓨터로 옮기거나 백업할 때 아래 기능을 쓰세요.")
    d1, d2 = st.columns(2)
    d1.download_button("전체 백업 (JSON)", json.dumps(pf, ensure_ascii=False, indent=2).encode("utf-8"),
                       file_name=f"pokefolio_{dt.date.today()}.json", mime="application/json", use_container_width=True)
    d2.download_button("보유 현황 표 (CSV, 엑셀용)", core.to_csv(df) if not df.empty else b"",
                       file_name=f"pokefolio_{dt.date.today()}.csv", mime="text/csv",
                       disabled=df.empty, use_container_width=True)
    st.divider()
    up = st.file_uploader("백업 파일로 복원 (JSON)", type="json")
    if up:
        try:
            incoming = json.loads(up.read().decode("utf-8"))
            assert isinstance(incoming.get("cards"), list)
        except Exception:
            st.error("포트폴리오 백업 파일이 아니에요. 이 앱에서 내려받은 JSON 파일을 올려 주세요.")
        else:
            st.write(f"카드 {len(incoming['cards'])}종, 기록 {len(incoming.get('history', []))}일치가 들어 있어요.")
            ok = st.checkbox("지금 데이터를 이 백업으로 바꿀게요 (지금 데이터는 사라져요)")
            if st.button("복원", disabled=not ok):
                incoming.setdefault("history", [])
                st.session_state.pf = incoming
                store.save_portfolio(uid, incoming)
                st.rerun()
