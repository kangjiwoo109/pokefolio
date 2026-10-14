"""포켓몬 카드 포트폴리오: 화면과 분리된 계산·API·저장 로직."""
from __future__ import annotations

import datetime as dt
import json
import numbers
import re
import time
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd
import requests

API_BASE = "https://www.pokemonpricetracker.com/api/v2"
LOG_PATH: Path | None = None  # 앱이 정해 줌. API 요청·응답 요약을 남겨 문제를 찾을 때 씀


def _log(entry: dict) -> None:
    if not LOG_PATH:
        return
    try:
        logs = load_json(LOG_PATH, [])
        logs = (logs if isinstance(logs, list) else [])[-39:] + [entry]
        save_json(LOG_PATH, logs)
    except Exception:
        pass  # 기록 실패는 앱 동작에 영향 없게

GRADES = [
    "Raw", "PSA 10", "PSA 9", "PSA 8", "PSA 7",
    "BGS 10", "BGS 9.5", "BGS 9", "CGC 10", "CGC 9.5", "CGC 9", "SGC 10", "SGC 9",
]
LANGS = {"english": "영문판", "japanese": "일본판", "korean": "한국판"}
ACQUIRED = {"buy": "매입", "pull": "팩 개봉"}
API_LANGS = {"english", "japanese"}  # 한국판은 API에 없어서 직접 입력

# 등급 카드 가격으로 볼 필드 우선순위 (실제 판매 기반 값 먼저)
GRADED_PRICE_KEYS = [
    "smartMarketPrice", "marketPrice7Day", "medianPrice", "median",
    "averagePrice", "avg", "average", "marketPrice", "market", "price",
]
SALES_KEYS = ["salesCount", "count", "sales", "totalSales"]


# ---------------------------------------------------------------- 공용 도구
def to_float(v):
    if v is None or v == "":
        return None
    if isinstance(v, dict):  # {"price": 12.3} 같은 형태
        for k in ("price", "value", "amount", "usd"):
            if k in v:
                return to_float(v[k])
        return None
    try:
        f = float(str(v).replace(",", "").replace("$", ""))
    except ValueError:
        return None
    return f if f == f else None  # NaN 제외


def norm(s) -> str:
    """'PSA 10' / 'psa_10' / 'PSA10' -> 'psa10', 'BGS 9.5' -> 'bgs95'"""
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def dig(d, *paths):
    """여러 후보 경로 중 처음 값이 있는 것을 돌려준다. 경로는 'a.b.c'."""
    for path in paths:
        cur = d
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                cur = None
                break
        if cur not in (None, "", [], {}):
            return cur
    return None


# ---------------------------------------------------------------- 저장
def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def save_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)  # 저장 도중 꺼져도 원본이 깨지지 않게


# ---------------------------------------------------------------- PokemonPriceTracker API
class ApiError(Exception):
    pass


class PriceTracker:
    def __init__(self, api_key: str, session: requests.Session | None = None, budget=None):
        self.key = (api_key or "").strip()
        self.http = session or requests.Session()
        self.credits_left: str | None = None
        self.budget = budget  # 사람별 하루 한도 (클라우드에서만). check(n), spend(n)

    @staticmethod
    def _cost(params: dict, endpoint: str, count: int | None = None) -> int:
        """크레딧 계산: 세트 목록은 요청 1번에 1, 카드는 1장당 1 (eBay 등급 데이터를 붙이면 2)."""
        if endpoint == "sets":
            return 1
        per = 2 if str(params.get("includeEbay")).lower() == "true" else 1
        n = count if count is not None else int(params.get("limit") or 1)
        return n * per

    def _get(self, params: dict, endpoint: str = "cards"):
        if not self.key:
            raise ApiError("API 키가 없어요. 왼쪽 사이드바에 키를 입력해 주세요.")
        if self.budget:
            self.budget.check(self._cost(params, endpoint))
        try:
            r = self.http.get(
                f"{API_BASE}/{endpoint}", params=params,
                headers={"Authorization": f"Bearer {self.key}"}, timeout=20,
            )
        except requests.RequestException as e:
            raise ApiError(f"PokemonPriceTracker에 연결하지 못했어요. 인터넷 연결을 확인해 주세요. ({e})") from e
        self.credits_left = r.headers.get("X-RateLimit-Daily-Remaining", self.credits_left)
        entry = {"time": dt.datetime.now().strftime("%H:%M:%S"), "endpoint": endpoint, "params": params,
                 "status": r.status_code}
        if r.status_code == 401:
            raise ApiError("API 키가 맞지 않아요. 키를 다시 확인해 주세요.")
        if r.status_code == 403:
            raise ApiError("지금 플랜에서는 쓸 수 없는 데이터예요.")
        if r.status_code == 429:
            raise ApiError("오늘 크레딧을 다 썼거나 1분 요청 한도를 넘었어요. 잠시 뒤에 다시 해 주세요.")
        if not r.ok:
            _log({**entry, "text": r.text[:300]})
            raise ApiError(f"API 오류 {r.status_code}: {r.text[:200]}")
        try:
            body = r.json()
        except ValueError as e:
            _log({**entry, "error": "JSON 아님", "text": r.text[:300]})
            raise ApiError("API 응답을 읽지 못했어요.") from e
        data = body.get("data") if isinstance(body, dict) else body
        items = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        first = items[0] if items and isinstance(items[0], dict) else {}
        _log({**entry, "count": len(items),
              "top_keys": list(body)[:15] if isinstance(body, dict) else None,
              "metadata": body.get("metadata") if isinstance(body, dict) else None,
              "first_keys": list(first)[:60],
              "first": {k: v for k, v in first.items() if not isinstance(v, (dict, list))} if first else None,
              "results": [{k: x.get(k) for k in ("name", "cardNumber", "number", "setName", "set", "tcgPlayerId", "id")
                           if k in x} for x in items[:10] if isinstance(x, dict)]})
        if self.budget:
            self.budget.spend(self._cost(params, endpoint, len(items)))
        if isinstance(data, dict):
            return [data]
        return data or []

    def search(self, query: str, set_name: str = "", language: str = "english", limit: int = 10):
        params = {"search": query, "limit": limit, "language": language}
        if set_name.strip():
            s = set_name.strip()
            params["setId" if s.isdigit() else "set"] = s
        return self._get(params)

    def sets(self, language: str = "english") -> list[dict]:
        """전체 세트 목록 (요청 1번에 1크레딧, 100개씩 나눠 받음)."""
        out, offset = [], 0
        while True:
            page = self._get({"language": language, "sortBy": "releaseDate", "sortOrder": "desc",
                              "limit": 100, "offset": offset}, endpoint="sets")
            out += [set_summary(x) for x in page if isinstance(x, dict)]
            if len(page) < 100 or offset >= 2000:
                break
            offset += 100
        seen, uniq = set(), []
        for x in out:  # 페이지가 겹쳐 와도 한 번만
            k = (x["id"], x["name"])
            if k not in seen:
                seen.add(k)
                uniq.append(x)
        return uniq

    def card(self, tcg_id: str, language: str = "english", graded: bool = False):
        params = {"tcgPlayerId": tcg_id, "language": language}
        if graded:
            params["includeEbay"] = "true"
        found = self._get(params)
        return found[0] if found else None


def image_url(c: dict) -> str:
    v = dig(c, "imageCdnUrl800", "imageCdnUrl", "imageUrl", "image", "images.large", "images.small", "imageCdnUrl400")
    if isinstance(v, str) and v.startswith("http"):
        return v
    for k, v in c.items():  # 필드 이름이 달라도 'image'가 들어간 주소를 찾기
        if "image" in k.lower() and isinstance(v, str) and v.startswith("http"):
            return v
    return ""


def display_name(name: str, number: str = "") -> str:
    """'Pikachu ex - 276/217' -> 'Pikachu ex' (번호는 따로 보여주므로)"""
    m = re.match(r"^(.*?)\s+-\s+(#?[A-Za-z]*\d+[A-Za-z]?(?:/[A-Za-z]*\d+)?)$", name or "")
    return m.group(1) if m else (name or "")


def card_summary(c: dict) -> dict:
    set_val = dig(c, "setName", "set.name", "set")
    return {
        "tcgPlayerId": str(dig(c, "tcgPlayerId", "tcgplayerId", "productId", "id") or ""),
        "name": str(dig(c, "name", "cleanName") or ""),
        "set": set_val if isinstance(set_val, str) else "",
        "number": str(dig(c, "cardNumber", "number") or ""),
        "rarity": str(dig(c, "rarity") or ""),
        "image": image_url(c),
    }


def set_summary(x: dict) -> dict:
    return {
        "id": str(dig(x, "tcgPlayerId", "setId", "id", "groupId") or ""),
        "name": str(dig(x, "name", "setName") or ""),
        "series": str(dig(x, "series", "seriesName") or ""),
        "release": str(dig(x, "releaseDate", "publishedOn", "release") or "")[:10],
    }


def is_number_query(q: str) -> bool:
    return bool(re.fullmatch(r"#?\s*[a-z]{0,4}\d{1,4}[a-z]?(\s*/\s*[a-z]{0,4}\d{1,4})?", q.strip().lower()))


def _set_matches(c: dict, set_id: str, set_name: str) -> bool:
    s = card_summary(c)["set"].lower()
    sid = str(dig(c, "setId", "set.id", "setSlug") or "").lower()
    name = set_name.lower()
    core_name = name.split(":", 1)[-1].strip()  # "ME: Ascended Heroes" -> "ascended heroes"
    return bool(s) and (s == name or (core_name and core_name in s) or (sid and sid == set_id.lower()))


def find_cards(api: "PriceTracker", query: str, set_id: str, set_name: str, language: str) -> list[dict]:
    """세트 안에서 이름이나 번호로 카드 찾기. 한 방법으로 안 나오면 다음 방법으로."""
    q = query.strip()
    numeric = is_number_query(q)
    want = _num_key(q) if numeric else ""

    def keep(found):
        if numeric:
            found = [c for c in found if _num_key(card_summary(c)["number"]) == want]
        return found

    attempts = []
    if set_id:
        attempts.append((want or q, set_id))
    if set_name and set_name != set_id:
        attempts.append((want or q, set_name))
    for term, key in attempts:
        hits = keep(api.search(term, key, language, limit=10))
        if hits:
            return hits
    if numeric:
        return []  # 번호만으로는 세트 없이 찾을 수 없음 -> 이름으로 찾게 안내
    found = api.search(q, "", language, limit=20)  # 세트 조건 없이 찾고 세트는 직접 거르기
    if set_id or set_name:
        in_set = [c for c in found if _set_matches(c, set_id, set_name)]
        return in_set
    return found


def raw_price(c: dict):
    v = to_float(dig(c, "prices.market", "prices.marketPrice", "marketPrice", "prices.mid", "prices.low"))
    if v is not None:
        return v, "TCGPlayer 시세(prices.market)"
    variants = dig(c, "prices.variants", "variants")
    if isinstance(variants, dict):  # 인쇄 종류별 가격만 있을 때 첫 값
        for name, vd in variants.items():
            v = to_float(dig(vd, "marketPrice", "market", "price")) if isinstance(vd, dict) else to_float(vd)
            if v is not None:
                return v, f"TCGPlayer 시세({name})"
    return None, ""


def _find_grade_node(node, target: str, depth: int = 0):
    if depth > 6 or node is None:
        return None
    if isinstance(node, dict):
        for k, v in node.items():
            if norm(k) == target:
                return v
        for k, v in node.items():  # {"PSA": {"10": {...}}}
            if isinstance(v, dict):
                for k2, v2 in v.items():
                    if norm(k) + norm(k2) == target:
                        return v2
        for v in node.values():
            hit = _find_grade_node(v, target, depth + 1)
            if hit is not None:
                return hit
    elif isinstance(node, list):  # [{"grade": "PSA 10", ...}]
        for item in node:
            if isinstance(item, dict):
                g = item.get("grade") or item.get("gradeLabel")
                company = item.get("grader") or item.get("company") or ""
                if g is not None and target in (norm(g), norm(f"{company}{g}")):
                    return item
        for item in node:
            hit = _find_grade_node(item, target, depth + 1)
            if hit is not None:
                return hit
    return None


def graded_price(c: dict, grade: str):
    ebay = dig(c, "ebay", "ebayData", "graded", "gradedPrices")
    node = _find_grade_node(ebay, norm(grade))
    if node is None:
        return None, "", None
    if not isinstance(node, dict):
        v = to_float(node)
        return v, f"eBay 판매가({grade})", None
    sales = next((node[k] for k in SALES_KEYS if k in node), None)
    for k in GRADED_PRICE_KEYS:
        v = to_float(node.get(k))
        if v is not None:
            return v, f"eBay 판매가({grade}, {k})", sales
    return None, "", sales


def price_for(c: dict, grade: str):
    """(달러 가격, 출처 설명, 판매 건수)"""
    if grade == "Raw":
        v, src = raw_price(c)
        return v, src, None
    return graded_price(c, grade)


# ---------------------------------------------------------------- 환율 (시세는 달러로 오므로 원화 표시용)
def fx_latest(http=requests):
    """(1달러 원화 값, 기준 설명). 못 가져오면 (None, None)."""
    try:
        j = http.get("https://open.er-api.com/v6/latest/USD", timeout=10).json()
        if j.get("result") == "success":
            return float(j["rates"]["KRW"]), f"{j.get('time_last_update_utc', '')[5:16]} · open.er-api.com"
    except Exception:
        pass
    try:
        j = http.get("https://api.frankfurter.app/latest", params={"from": "USD", "to": "KRW"}, timeout=10).json()
        return float(j["rates"]["KRW"]), f"{j['date']} · 유럽중앙은행"
    except Exception:
        return None, None


# ---------------------------------------------------------------- 계산 (모두 원화, 현재 환율로 환산)
def cost_krw_of(c: dict, fx: float) -> float:
    """1장 투자금액(매입가 또는 팩 값) x 수량 (원). 달러로 넣었던 카드는 현재 환율로 바꾼다."""
    unit = to_float(c.get("buy_price")) or 0.0
    if c.get("buy_currency", "KRW") != "KRW":
        unit *= fx
    return unit * int(c.get("qty") or 1)


def compute(cards: list[dict], fx: float) -> pd.DataFrame:
    rows = []
    for c in cards:
        qty = int(c.get("qty") or 1)
        cost = cost_krw_of(c, fx)
        usd = to_float(c.get("cur_usd"))
        cur = usd * fx if usd is not None else None
        if cur is None:
            value = pl = pl_pct = None
        else:
            value = cur * qty
            pl = value - cost
            pl_pct = pl / cost * 100 if cost else None
        rows.append({
            "id": c["id"], "image": c.get("image") or None, "name": c.get("name", ""),
            "set": c.get("set", ""), "number": c.get("number", ""),
            "language": LANGS.get(c.get("language"), c.get("language", "")),
            "grade": c.get("grade", "Raw"), "qty": qty,
            "acquired": ACQUIRED.get(c.get("acquired", "buy"), "매입"),
            "cost": cost, "cur": cur, "value": value, "pl": pl, "pl_pct": pl_pct,
            "price_updated": c.get("price_updated", ""), "price_source": c.get("price_source", ""),
        })
    cols = ["id", "image", "name", "set", "number", "language", "grade", "qty", "acquired", "cost", "cur",
            "value", "pl", "pl_pct", "price_updated", "price_source"]
    return pd.DataFrame(rows, columns=cols)


def totals(df: pd.DataFrame) -> dict:
    priced = df[df["value"].notna()]
    cost = float(priced["cost"].sum())
    value = float(priced["value"].sum())
    return {
        "value": value, "cost": cost, "pl": value - cost,
        "pl_pct": (value - cost) / cost * 100 if cost else None,
        "unpriced": int(df["value"].isna().sum()), "count": int(df["qty"].sum()) if len(df) else 0,
        "pulled_value": float(priced.loc[priced["acquired"] == "팩 개봉", "value"].sum()),
        "bought_value": float(priced.loc[priced["acquired"] == "매입", "value"].sum()),
    }


def snapshot(pf: dict, df: pd.DataFrame, fx: float, today: str | None = None) -> None:
    """하루 한 번 평가액 기록 (같은 날은 덮어씀)."""
    t = totals(df)
    today = today or dt.date.today().isoformat()
    snap = {"date": today, "value_krw": round(t["value"]), "cost_krw": round(t["cost"]), "fx": fx}
    pf["history"] = [h for h in pf.get("history", []) if h.get("date") != today] + [snap]
    pf["history"].sort(key=lambda h: h["date"])


def history_krw(history: list[dict]) -> list[dict]:
    """달러로 저장된 예전 기록은 그날 환율이 없으면 빼고 원화 기록만."""
    out = []
    for h in history:
        if "value_krw" in h:
            out.append({"date": h["date"], "value": h["value_krw"], "cost": h["cost_krw"]})
        elif "value_usd" in h and h.get("fx"):
            out.append({"date": h["date"], "value": h["value_usd"] * h["fx"], "cost": h["cost_usd"] * h["fx"]})
    return out


EDITABLE = ["grade", "qty", "acquired", "unit_cost", "date", "cur", "note"]


def edit_row(c: dict, fx: float) -> dict:
    """표에서 고칠 수 있는 값만 뽑기 (금액은 원, 정수)."""
    try:
        date = dt.date.fromisoformat(c.get("buy_date") or "")
    except ValueError:
        date = None
    usd = to_float(c.get("cur_usd"))
    return {
        "grade": c.get("grade", "Raw"), "qty": int(c.get("qty") or 1),
        "acquired": ACQUIRED.get(c.get("acquired", "buy"), "매입"),
        "unit_cost": round(cost_krw_of({**c, "qty": 1}, fx)), "date": date,
        "cur": round(usd * fx) if usd is not None else None, "note": c.get("note", ""),
    }


def _blank(v) -> bool:
    try:
        return v is None or v == "" or bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _same(a, b) -> bool:
    if _blank(a) or _blank(b):
        return _blank(a) and _blank(b)  # None, NaN, 빈 값끼리는 같은 값
    if isinstance(a, numbers.Real) and isinstance(b, numbers.Real) and not isinstance(a, bool):
        return abs(float(a) - float(b)) < 0.5
    if hasattr(a, "isoformat") and hasattr(b, "isoformat"):
        return a.isoformat()[:10] == b.isoformat()[:10]  # date와 Timestamp 비교
    return a == b


def apply_edit(c: dict, new: dict, fx: float) -> bool:
    """표에서 고친 값을 카드에 반영. 바뀐 게 있으면 True."""
    old = edit_row(c, fx)
    changed = [k for k in EDITABLE if k in new and not _same(old[k], new[k])]
    if not changed:
        return False
    for k in changed:
        v = new[k]
        if k == "grade":
            c["grade"] = v or "Raw"
            if "cur" not in changed:
                c["price_source"] = "등급 바뀜 · 시세 갱신 필요"
        elif k == "qty":
            c["qty"] = max(1, int(v or 1))
        elif k == "acquired":
            c["acquired"] = {lab: key for key, lab in ACQUIRED.items()}.get(v, "buy")
        elif k == "unit_cost":
            c["buy_price"] = round(to_float(v) or 0.0)
            c["buy_currency"] = "KRW"
            c.pop("buy_fx", None)
        elif k == "date":
            c["buy_date"] = v.isoformat()[:10] if hasattr(v, "isoformat") else (str(v)[:10] if v else "")
        elif k == "cur":
            f = to_float(v)
            c["cur_usd"] = round(f / fx, 2) if f else None  # 시세는 달러로 저장 (API와 같은 단위)
            c["price_source"] = "직접 입력" if f else ""
            c["price_updated"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M") if f else ""
        elif k == "note":
            c["note"] = v or ""
    return True


def _num_key(n) -> str:
    """'276/217', '#276', '0276' -> '276'"""
    head = str(n or "").strip().lstrip("#").split("/")[0].strip().lower()
    return head.lstrip("0") or head


def resolve_card(card: dict, api: PriceTracker) -> dict | None:
    """TCGPlayer ID 없이 직접 입력한 카드를 이름·세트·번호로 찾아 ID를 채운다."""
    name, set_name, lang = card.get("name", ""), card.get("set", ""), card.get("language", "english")
    found = api.search(name, set_name, lang, limit=10)
    if not found and set_name:
        found = api.search(name, "", lang, limit=10)  # 세트 이름 표기가 다를 때
    if not found:
        return None
    want = _num_key(card.get("number"))
    if want:
        hits = [c for c in found if _num_key(card_summary(c)["number"]) == want]
    else:
        hits = found if len(found) == 1 else []
    if len(hits) != 1:
        return None
    s = card_summary(hits[0])
    card["tcgPlayerId"] = s["tcgPlayerId"]
    card["set"] = card.get("set") or s["set"]
    card["image"] = card.get("image") or s["image"]
    return hits[0]


def refresh_card(card: dict, api: PriceTracker, cache=None) -> str:
    """카드 한 장 시세 갱신. cache가 있으면 24시간 안에 누군가 받아 둔 시세를 먼저 쓴다."""
    if card.get("language") not in API_LANGS:
        return "한국판은 API 지원이 없어 건너뜀"
    if cache and card.get("tcgPlayerId"):
        hit = cache.get(card)
        if hit:
            card["cur_usd"] = hit["usd"]
            card["price_source"] = hit.get("source") or "공용 시세"
            card["image"] = card.get("image") or hit.get("image", "")
            card["price_updated"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
            return f"${hit['usd']:,.2f} (최근 받은 시세, 크레딧 안 듦)"
    msg = _refresh_card_api(card, api)
    if cache and msg.startswith("$"):
        cache.put(card)
    return msg


def _refresh_card_api(card: dict, api: PriceTracker) -> str:
    if not card.get("tcgPlayerId"):
        found = resolve_card(card, api)
        if not found:
            return ("API에서 카드를 하나로 특정하지 못했어요. 카드명(영문)·세트·번호를 확인하거나 "
                    "'카드 추가 > API로 검색'으로 다시 등록해 주세요.")
        if card.get("grade", "Raw") == "Raw":  # 검색 결과에 미감정 시세가 있으면 추가 호출 없이 사용
            price, src = raw_price(found)
            if price is not None:
                card["cur_usd"] = round(price, 2)
                card["price_source"] = src
                card["price_updated"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
                return f"${price:,.2f}"
    data = api.card(card["tcgPlayerId"], card["language"], graded=card.get("grade") != "Raw")
    if not data:
        return "API에서 카드를 찾지 못함"
    card["image"] = card.get("image") or image_url(data)
    price, src, sales = price_for(data, card.get("grade", "Raw"))
    if price is None:
        return f"{card.get('grade')} 판매 데이터 없음 (기존 시세 유지)"
    card["cur_usd"] = round(price, 2)
    card["price_source"] = src + (f", 판매 {sales}건" if sales else "")
    card["price_updated"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"${price:,.2f}"


def refresh_all(cards: list[dict], api: PriceTracker, on_progress=None, cache=None) -> list[tuple[str, str]]:
    results = []
    targets = [c for c in cards if c.get("language") in API_LANGS]
    for i, c in enumerate(targets):
        try:
            msg = refresh_card(c, api, cache)
        except ApiError as e:
            results.append((c.get("name", ""), str(e)))
            if "크레딧" in str(e) or "키" in str(e) or "한도" in str(e):
                break  # 한도·키 문제면 계속 호출해도 소용없음
            continue
        results.append((c.get("name", ""), msg))
        if on_progress:
            on_progress((i + 1) / len(targets), c.get("name", ""))
        if len(targets) > 50:
            time.sleep(1.05)  # 분당 60회 한도
    return results


def estimate_credits(cards: list[dict]) -> int:
    n = 0
    for c in cards:
        if c.get("language") in API_LANGS:
            n += 1 if c.get("grade") == "Raw" else 2
            if not c.get("tcgPlayerId"):
                n += 3  # 처음 한 번 카드 찾기(검색 결과 수만큼 듦, 대략값)
    return n


def ebay_sold_url(card: dict) -> str:
    parts = [card.get("name", ""), card.get("set", ""), card.get("number", "")]
    if card.get("grade") and card["grade"] != "Raw":
        parts.append(card["grade"])
    if card.get("language") == "japanese":
        parts.append("japanese")
    elif card.get("language") == "korean":
        parts.append("korean")
    q = " ".join(p for p in parts if p)
    return f"https://www.ebay.com/sch/i.html?_nkw={quote_plus(q)}&_sacat=183454&LH_Sold=1&LH_Complete=1"


def to_csv(df: pd.DataFrame) -> bytes:
    out = df.drop(columns=["image", "id"]).round({"cost": 0, "cur": 0, "value": 0, "pl": 0, "pl_pct": 1}).rename(columns={
        "name": "카드명", "set": "세트", "number": "번호", "language": "언어", "grade": "등급", "qty": "수량",
        "acquired": "획득", "cost": "투자금액(원)", "cur": "1장 시세(원)", "value": "평가액(원)", "pl": "손익(원)",
        "pl_pct": "수익률(%)", "price_updated": "시세갱신", "price_source": "시세출처",
    })
    return out.to_csv(index=False).encode("utf-8-sig")  # 엑셀에서 한글 안 깨지게


# ---------------------------------------------------------------- 한글 포켓몬 이름 -> 영문
HANGUL = re.compile(r"[가-힣]")
_KO_QUERY = "query { %s(where: {language_id: {_in: [3, 9]}}) { name language_id pokemon_species_id } }"


def fetch_ko_names(http=requests) -> dict:
    """PokeAPI(무료, 키 없음)에서 포켓몬 한글·영문 이름표를 받아 {한글: 영문}으로."""
    tries = [("https://beta.pokeapi.co/graphql/v1beta", "pokemon_v2_pokemonspeciesname"),
             ("https://graphql.pokeapi.co/v1beta2", "pokemonspeciesname")]
    for url, table in tries:
        try:
            r = http.post(url, json={"query": _KO_QUERY % table}, timeout=30)
            rows = r.json()["data"][table]
        except Exception:
            continue
        ko, en = {}, {}
        for row in rows:
            (ko if row["language_id"] == 3 else en)[row["pokemon_species_id"]] = row["name"]
        names = {ko[i]: en[i] for i in ko if i in en}
        if len(names) > 500:
            return names
    return {}


def translate_query(q: str, names: dict) -> tuple[str, list[str]]:
    """'리자몽 ex' -> 'Charizard ex'. 모르는 한글 단어 목록도 돌려준다."""
    out, unknown = [], []
    for tok in q.split():
        if not HANGUL.search(tok):
            out.append(tok)
            continue
        en = names.get(tok) or next((v for k, v in names.items() if k.startswith(tok)), None)
        if en:
            out.append(en)
        else:
            unknown.append(tok)
    return " ".join(out), unknown


# ---------------------------------------------------------------- 세트 카드 목록 저장 (번호 검색용)
def slim(c: dict) -> dict:
    s = card_summary(c)
    price, _ = raw_price(c)
    return {"tcgPlayerId": s["tcgPlayerId"], "name": s["name"], "setName": s["set"], "cardNumber": s["number"],
            "rarity": s["rarity"], "imageUrl": s["image"], "prices": {"market": price}}


def load_set_cards(api: "PriceTracker", entry: dict, set_id: str, set_name: str, language: str,
                   budget: int, page: int = 50) -> dict:
    """세트 카드 목록을 budget 크레딧 안에서 이어 받아 entry에 쌓는다 (카드 1장당 1크레딧)."""
    cards = entry.setdefault("cards", [])
    seen = {c["tcgPlayerId"] for c in cards}
    key = entry.get("key") or set_id or set_name
    while budget >= 1 and not entry.get("done"):
        limit = min(page, budget)
        got = api._get({"set": key, "language": language, "limit": limit, "offset": entry.get("offset", 0)})
        if not got and not cards and key == set_id and set_name:
            key = set_name  # 세트 ID로 안 되면 세트 이름으로
            continue
        entry["key"] = key
        new = [slim(c) for c in got if isinstance(c, dict)]
        fresh = [c for c in new if c["tcgPlayerId"] not in seen]
        cards += fresh
        seen |= {c["tcgPlayerId"] for c in fresh}
        entry["offset"] = entry.get("offset", 0) + len(got)
        budget -= len(got)
        if len(got) < limit or not fresh:  # 마지막 페이지이거나 같은 페이지가 반복되면 끝
            entry["done"] = True
    entry["updated"] = dt.date.today().isoformat()
    return entry


def local_find(cards: list[dict], q: str) -> list[dict]:
    """저장된 세트 목록에서 번호나 이름으로 찾기 (크레딧 안 듦)."""
    q = q.strip()
    if is_number_query(q):
        want = _num_key(q)
        return [c for c in cards if _num_key(c.get("cardNumber")) == want]
    words = q.lower().split()
    return [c for c in cards if all(w in c.get("name", "").lower() for w in words)]


# ---------------------------------------------------------------- 차트용
def pie_slices(df: pd.DataFrame, top: int = 7) -> pd.DataFrame:
    """평가액 비중: 큰 카드 top장 + 나머지는 '기타'로 묶기."""
    priced = df[df["value"].notna() & (df["value"] > 0)].copy()
    if priced.empty:
        return pd.DataFrame(columns=["label", "value", "share", "order"])
    priced["label"] = [display_name(n, num) + ("" if g == "Raw" else f" · {g}")
                       for n, num, g in zip(priced["name"], priced["number"], priced["grade"])]
    priced = priced.sort_values("value", ascending=False)
    head = priced.head(top)[["label", "value"]]
    rest = priced.iloc[top:]["value"].sum()
    if rest > 0:
        head = pd.concat([head, pd.DataFrame([{"label": f"기타 {len(priced) - top}장", "value": rest}])])
    head = head.reset_index(drop=True)
    head["share"] = head["value"] / head["value"].sum() * 100
    head["order"] = range(len(head))
    return head
