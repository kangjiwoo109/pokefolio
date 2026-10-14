"""저장소: 내 컴퓨터(JSON 파일) 또는 클라우드(Supabase).

클라우드 모드에서는
- 회원가입·로그인은 Supabase 로그인 서비스가 비밀번호를 안전하게(해시) 보관한다.
- 데이터 테이블은 모두 행 보안(RLS)을 켜고 정책을 두지 않아서, 서버(서비스 키)만 읽고 쓸 수 있다.
- 시세·세트 목록은 모든 사용자가 같이 쓰는 공용 캐시에 저장해 API 크레딧을 아낀다.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import secrets
from pathlib import Path

import requests

import portfolio_core as core

EMPTY = {"cards": [], "history": []}
PRICE_TTL_HOURS = 24
ID_RULE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,19}$")
ID_DOMAIN = "users.pokefolio.app"  # 아이디를 로그인 서비스용 주소 형태로 바꿀 때 쓰는 가짜 도메인 (메일은 보내지 않음)


class AuthError(Exception):
    pass


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _fresh(stamp: str | None, hours: int = PRICE_TTL_HOURS) -> bool:
    if not stamp:
        return False
    try:
        t = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return _now() - t < dt.timedelta(hours=hours)


def price_key(card: dict) -> str | None:
    if not card.get("tcgPlayerId"):
        return None
    return f"price|{card.get('language', 'english')}|{card['tcgPlayerId']}|{card.get('grade', 'Raw')}"


class PriceCache:
    """시세 공용 캐시: 같은 카드·등급 시세는 24시간 동안 다시 사지 않는다."""

    def __init__(self, store):
        self.store = store

    def get(self, card: dict) -> dict | None:
        k = price_key(card)
        hit = self.store.get_shared(k) if k else None
        if hit and _fresh(hit.get("at")):
            return hit
        return None

    def put(self, card: dict) -> None:
        k = price_key(card)
        if k and card.get("cur_usd"):
            self.store.set_shared(k, {"usd": card["cur_usd"], "source": card.get("price_source", ""),
                                      "image": card.get("image", ""), "at": _now().isoformat()})


class Budget:
    """사람별 하루 API 크레딧 한도 (누구나 가입하는 앱이라 한 사람이 다 쓰지 않게)."""

    def __init__(self, store, uid: str, limit: int):
        self.store, self.uid, self.limit = store, uid, limit

    def used(self) -> int:
        return self.store.get_usage(self.uid, dt.date.today().isoformat())

    def left(self) -> int:
        return max(0, self.limit - self.used())

    def check(self, cost: int) -> None:
        if cost > self.left():
            raise core.ApiError(f"오늘 쓸 수 있는 조회 한도({self.limit}크레딧)를 다 썼어요. 내일 다시 할 수 있어요. "
                                "저장된 세트 목록에서 찾기와 다른 사람이 받아 둔 시세는 계속 쓸 수 있어요.")

    def spend(self, cost: int) -> None:
        if cost > 0:
            self.store.add_usage(self.uid, dt.date.today().isoformat(), cost)


# ---------------------------------------------------------------- 내 컴퓨터
class LocalStore:
    cloud = False
    FILES = {"sets": "sets_cache.json", "setcards": "set_cards_cache.json", "ko_names": "pokemon_ko_names.json"}

    def __init__(self, folder: Path):
        self.dir = Path(folder)

    def _file(self, key: str) -> tuple[Path, str | None]:
        head, _, rest = key.partition("|")
        if head in self.FILES:
            return self.dir / self.FILES[head], (rest or None)
        return self.dir / "shared_cache.json", key

    def get_shared(self, key: str):
        path, sub = self._file(key)
        data = core.load_json(path, {})
        return data.get(sub) if sub else (data or None)

    def set_shared(self, key: str, value) -> None:
        path, sub = self._file(key)
        if sub:
            data = core.load_json(path, {})
            data[sub] = value
            core.save_json(path, data)
        else:
            core.save_json(path, value)

    def load_portfolio(self, uid: str) -> dict:
        return core.load_json(self.dir / "portfolio.json", dict(EMPTY))

    def save_portfolio(self, uid: str, pf: dict) -> None:
        core.save_json(self.dir / "portfolio.json", pf)

    def get_usage(self, uid, day):
        return 0

    def add_usage(self, uid, day, n):
        pass


# ---------------------------------------------------------------- 클라우드 (Supabase)
class SupabaseStore:
    cloud = True

    def __init__(self, url: str, service_key: str, http=None):
        self.url = url.strip().rstrip("/")
        for tail in ("/rest/v1", "/auth/v1"):  # Data API 화면의 주소를 그대로 붙여 넣어도 되게
            if self.url.endswith(tail):
                self.url = self.url[: -len(tail)]
        self.key = service_key
        self.http = http or requests.Session()

    # ----- 공통 요청
    def _h(self, extra: dict | None = None) -> dict:
        h = {"apikey": self.key, "Content-Type": "application/json"}
        if self.key.startswith("eyJ"):  # 예전 형식 service_role 키(JWT)만 Authorization에도 넣음. 새 sb_secret_ 키는 apikey만
            h["Authorization"] = f"Bearer {self.key}"
        return {**h, **(extra or {})}

    def _rest(self, method: str, table: str, params: dict | None = None, body=None, prefer: str | None = None):
        r = self.http.request(method, f"{self.url}/rest/v1/{table}", params=params, timeout=20,
                              headers=self._h({"Prefer": prefer} if prefer else None),
                              data=json.dumps(body) if body is not None else None)
        if r.status_code >= 400:
            raise RuntimeError(f"데이터 저장소 오류 {r.status_code}: {r.text[:200]}")
        return r.json() if r.text else None

    # ----- 회원가입·로그인
    @staticmethod
    def id_to_email(user_id: str) -> str:
        return f"{user_id.strip().lower()}@{ID_DOMAIN}"

    def sign_up(self, user_id: str, password: str) -> dict:
        uid = user_id.strip().lower()
        if not ID_RULE.match(uid):
            raise AuthError("아이디는 영문 소문자·숫자로 시작하고, 영문 소문자·숫자·. _ - 로 3~20자예요.")
        if len(password) < 8:
            raise AuthError("비밀번호는 8자 이상으로 정해 주세요.")
        r = self.http.post(f"{self.url}/auth/v1/admin/users", headers=self._h(), timeout=20,
                           data=json.dumps({"email": self.id_to_email(uid), "password": password,
                                            "email_confirm": True, "user_metadata": {"login_id": uid}}))
        if r.status_code in (400, 409, 422) and ("already" in r.text.lower() or "exists" in r.text.lower()):
            raise AuthError("이미 쓰고 있는 아이디예요. 다른 아이디를 골라 주세요.")
        if r.status_code >= 400:
            raise AuthError(f"가입하지 못했어요. 잠시 뒤에 다시 해 주세요. ({r.status_code})")
        return self.sign_in(uid, password)

    def sign_in(self, user_id: str, password: str) -> dict:
        r = self.http.post(f"{self.url}/auth/v1/token", params={"grant_type": "password"}, headers=self._h(),
                           timeout=20, data=json.dumps({"email": self.id_to_email(user_id), "password": password}))
        if r.status_code in (400, 401):
            raise AuthError("아이디나 비밀번호가 맞지 않아요.")
        if r.status_code >= 400:
            raise AuthError(f"로그인하지 못했어요. 잠시 뒤에 다시 해 주세요. ({r.status_code})")
        j = r.json()
        return {"id": j["user"]["id"], "login_id": user_id.strip().lower()}

    def change_password(self, user: dict, old: str, new: str) -> None:
        self.sign_in(user["login_id"], old)  # 지금 비밀번호 확인
        if len(new) < 8:
            raise AuthError("새 비밀번호는 8자 이상으로 정해 주세요.")
        r = self.http.put(f"{self.url}/auth/v1/admin/users/{user['id']}", headers=self._h(), timeout=20,
                          data=json.dumps({"password": new}))
        if r.status_code >= 400:
            raise AuthError(f"비밀번호를 바꾸지 못했어요. ({r.status_code})")

    def delete_account(self, user: dict, password: str) -> None:
        self.sign_in(user["login_id"], password)
        r = self.http.delete(f"{self.url}/auth/v1/admin/users/{user['id']}", headers=self._h(), timeout=20)
        if r.status_code >= 400:
            raise AuthError(f"탈퇴하지 못했어요. ({r.status_code})")  # 포트폴리오는 계정 삭제 때 같이 지워짐

    # ----- 구글 로그인 (구글이 확인한 사용자를 이 앱 계정과 연결)
    def google_user(self, sub: str, email: str = "", name: str = "") -> dict:
        if not sub:
            raise AuthError("구글 계정 정보를 받지 못했어요. 다시 로그인해 주세요.")
        shown = email or name or "구글 계정"
        link = self.get_shared(f"google|{sub}")
        if link:
            return {"id": link["user_id"], "login_id": shown, "provider": "google", "sub": sub}
        # 처음 온 구글 사용자: 계정을 만들고 연결 정보 저장 (이 계정의 비밀번호는 아무도 모르는 무작위 값)
        r = self.http.post(f"{self.url}/auth/v1/admin/users", headers=self._h(), timeout=20,
                           data=json.dumps({"email": f"google-{sub}@{ID_DOMAIN}", "password": secrets.token_urlsafe(32),
                                            "email_confirm": True,
                                            "user_metadata": {"provider": "google", "google_email": email}}))
        if r.status_code >= 400:
            raise AuthError(f"구글 계정으로 가입하지 못했어요. 잠시 뒤에 다시 해 주세요. ({r.status_code})")
        uid = r.json()["id"]
        self.set_shared(f"google|{sub}", {"user_id": uid})
        return {"id": uid, "login_id": shown, "provider": "google", "sub": sub}

    def delete_google_account(self, user: dict) -> None:
        r = self.http.delete(f"{self.url}/auth/v1/admin/users/{user['id']}", headers=self._h(), timeout=20)
        if r.status_code >= 400:
            raise AuthError(f"탈퇴하지 못했어요. ({r.status_code})")
        self._rest("DELETE", "shared_cache", {"key": f"eq.google|{user['sub']}"})

    # ----- 포트폴리오 (사람별)
    def load_portfolio(self, uid: str) -> dict:
        rows = self._rest("GET", "portfolios", {"user_id": f"eq.{uid}", "select": "data"})
        return rows[0]["data"] if rows else {"cards": [], "history": []}

    def save_portfolio(self, uid: str, pf: dict) -> None:
        self._rest("POST", "portfolios", body={"user_id": uid, "data": pf, "updated_at": _now().isoformat()},
                   prefer="resolution=merge-duplicates,return=minimal")

    # ----- 공용 캐시
    def get_shared(self, key: str):
        rows = self._rest("GET", "shared_cache", {"key": f"eq.{key}", "select": "data"})
        return rows[0]["data"] if rows else None

    def set_shared(self, key: str, value) -> None:
        self._rest("POST", "shared_cache", body={"key": key, "data": value, "updated_at": _now().isoformat()},
                   prefer="resolution=merge-duplicates,return=minimal")

    # ----- 사람별 하루 사용량
    def get_usage(self, uid: str, day: str) -> int:
        rows = self._rest("GET", "usage", {"user_id": f"eq.{uid}", "day": f"eq.{day}", "select": "credits"})
        return int(rows[0]["credits"]) if rows else 0

    def add_usage(self, uid: str, day: str, n: int) -> None:
        self._rest("POST", "rpc/add_usage", body={"p_user": uid, "p_day": day, "p_n": int(n)})
