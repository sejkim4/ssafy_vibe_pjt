# Backend Agent Task Order #02 — Match Domain API (Start Worldcup → Play Rounds)

- Document version: v1.0
- Date: 2026-07-15
- Audience: backend engineering agent / developer
- Upstream documents:
  - [`요구사항명세서.md`](./요구사항명세서.md) (Requirements Specification, v1.1) — §2.2 user flow, §2.3 S1/S2 (round-sizing and bracket-formation rules), §3–4 screen requirements (MODAL-01–05, MATCH-01–05)
  - [`API명세서.md`](./API명세서.md) (API Specification, v1.0) — §0 (global rules), §1 (endpoint index), §2.1, §3.1–3.4 (the exact contract this task order implements)
  - [`backend_task_order_01_environment_and_db.md`](./backend_task_order_01_environment_and_db.md) — the DB schema and project skeleton this task order builds on top of. **Task order #01 must be complete before starting this one** (tables `locations`, `matches`, `match_filters`, `match_games` must already exist and `locations` must already be seeded).
- Scope of this task: implement the API surface that covers the flow **"press Start Worldcup" → "play rounds one by one" → "reach the final result."** Concretely, this is:
  1. `GET /api/locations/candidates`
  2. `POST /api/matches`
  3. `GET /api/matches/{match_id}`
  4. `POST /api/matches/{match_id}/games/{game_id}/result`
  5. `GET /api/matches/{match_id}/result`
  6. `GET /api/meta/regions`, `GET /api/meta/categories` (small supporting endpoints the modal needs to render filter chips)
- **Explicitly out of scope**: the chatbot (`POST /api/chat`) is being assigned to a separate agent — do not implement it, do not add any chat-related code, and do not add OpenAI as a dependency. The board/ranking endpoint (`GET /api/board/rankings`) and the review endpoints (`§5` of the API spec) are also out of scope — they belong to later task orders. If you find yourself needing something from those domains, stub the absolute minimum (e.g., a `location_id → title` lookup that already exists via the `locations` table) rather than building their endpoints early.

---

## 0. Definition of Done

1. All 7 endpoints listed above are implemented, return the exact response shapes from `API명세서.md`, and are mounted under the `/api` prefix except where the API spec says otherwise.
2. The full happy-path flow works end-to-end when driven manually or by an integration test:
   `GET candidates` → `POST /api/matches` → repeatedly `POST .../games/{id}/result` until `is_final_result: true` → `GET /api/matches/{id}/result` returns the correct winner.
3. Every error case listed in §5 below returns the exact `error_code` and HTTP status defined in `API명세서.md`.
4. The bracket-formation algorithm (§3 below) is implemented as pure, testable logic separated from the FastAPI route handlers (per the service-layer decision below), and has at least the unit tests listed in §6.
5. `uvicorn app.main:app --reload` boots without errors with the new routers mounted, and `GET /health` (from task order #01) still returns 200.

---

## 1. Project Structure Additions

Building on the skeleton from task order #01, add the following files. Do not restructure or rename anything task order #01 already created.

```
backend/
└── app/
    ├── routers/
    │   ├── __init__.py
    │   ├── locations.py       # NEW — GET /api/locations/candidates, GET /api/locations/{id}, GET /api/meta/*
    │   └── matches.py         # NEW — all /api/matches/* endpoints
    ├── schemas/
    │   ├── __init__.py
    │   ├── location.py        # NEW — Pydantic request/response models for location & meta endpoints
    │   └── match.py           # NEW — Pydantic request/response models for match/game endpoints
    ├── services/
    │   ├── __init__.py
    │   └── match_service.py   # NEW — bracket formation, winner recording, round-advancement logic (no FastAPI imports here)
    └── main.py                 # MODIFY — register the two new routers via app.include_router(...)
```

- **Router files** (`app/routers/*.py`) only contain FastAPI route declarations: parse the request, call into `match_service` (or direct DB queries for simple reads), shape the response, raise `HTTPException` on business-rule violations. Keep them thin.
- **Service file** (`app/services/match_service.py`) contains the actual bracket/round logic described in §3. It must be plain Python + SQLAlchemy session usage — no `fastapi` imports, no `HTTPException` raises. Instead, define and raise plain Python exceptions (e.g., `class RoundExceedsCandidatesError(Exception)`) that the router layer catches and translates into the correct HTTP response. This separation is what makes §6's unit tests possible without spinning up the FastAPI test client.
- **Schema files** (`app/schemas/*.py`) contain only `pydantic.BaseModel` subclasses — no SQLAlchemy imports. Name them so their purpose is unambiguous, e.g. `MatchCreateRequest`, `MatchCreateResponse`, `GameResultRequest`, `GameResultResponse`, `CandidatesResponse`, `MatchStateResponse`, `MatchResultResponse`.

---

## 2. Meta Endpoints (`app/routers/locations.py`)

These are small and exist purely to unblock the frontend's filter-chip rendering (API spec §0.6). Implement them first as a warm-up — they touch no database tables, just return hardcoded constants.

### 2.1 `GET /api/meta/regions`

Return the 25 Seoul districts using the **exact same code→name mapping table from task order #01 §4.3** (do not invent a new mapping — copy it verbatim so `locations.l_dong_signgu_cd` values always resolve correctly). Response shape:

```json
{
  "items": [
    { "code": "680", "name": "강남구" },
    { "code": "650", "name": "서초구" }
  ]
}
```
Full list and ordering: see `API명세서.md` §0.6 and task order #01 §4.3.

### 2.2 `GET /api/meta/categories`

Return the 6 categories using the **exact same slug table from task order #01 §4.2**:

```json
{
  "items": [
    { "code": "tourist_spot", "name": "관광지" },
    { "code": "culture_facility", "name": "문화시설" },
    { "code": "festival", "name": "축제·행사" },
    { "code": "leports", "name": "레포츠" },
    { "code": "accommodation", "name": "숙박" },
    { "code": "shopping", "name": "쇼핑" }
  ]
}
```

Implement both as a small constant list/dict at module scope in `app/routers/locations.py` (or a shared `app/constants.py` if you prefer — either is fine, but do not duplicate the mapping in two places).

---

## 3. Core Business Logic — Candidate Filtering & Bracket Formation

This section is the heart of the task. Read it fully before writing any code — the round-by-round generation logic in particular has a specific, order-dependent design that must be followed exactly (it is not "generate the whole bracket up front").

### 3.1 Candidate Filtering (shared logic, used by both `/candidates` and `POST /matches`)

Implement this as a single reusable function in `match_service.py`, e.g. `get_candidate_locations(db, regions: list[str], categories: list[str]) -> list[Location]`, because both `GET /api/locations/candidates` and `POST /api/matches` must apply **identical** filtering (API spec §3.1 step 1 explicitly requires this — the server re-validates using the same logic the modal used to compute `available_rounds`).

Logic (requirements spec §2.3 S1, API spec §2.1):
1. If `"ALL"` is present anywhere in the `regions` list, treat the region condition as "all 25 districts" (i.e., no `WHERE` filter on `l_dong_signgu_cd`). Otherwise filter `locations.l_dong_signgu_cd IN (regions)`.
2. If `"ALL"` is present anywhere in the `categories` list, treat the category condition as "all 6 categories" (no filter on `category`). Otherwise filter `locations.category IN (categories)`.
3. The final candidate set is the **intersection**: rows matching the region condition **AND** the category condition. This is not a union — re-read requirements spec §2.3 S1 if unsure ("(선택된 지역들의 합집합) ∩ (선택된 카테고리들의 합집합)").
4. `"ALL"` mixed with other explicit values in the same list (e.g. `["ALL", "680"]`) should be treated the same as `["ALL"]` alone — `"ALL"` wins, ignore the rest. This mirrors API spec §0.3 ("서버는 배열에 'ALL'이 포함되어 있으면 나머지 값을 무시").

### 3.2 Round Options Calculation

Given a candidate count `N`:
```
ROUND_OPTIONS = [4, 8, 16, 32, 64]
available_rounds = [r for r in ROUND_OPTIONS if r <= N]
```
This is a pure function — implement it standalone (e.g. `compute_available_rounds(candidate_count: int) -> list[int]`) so it's trivially unit-testable (see §6).

### 3.3 Bracket Formation on Match Creation (`POST /api/matches`)

Follow this exact sequence (API spec §3.1 "처리 로직", requirements spec §2.3 S2):

1. Run §3.1's candidate filtering with the request's `regions`/`categories`.
2. If `len(candidates) < total_rounds` → raise a service-level error (router translates to `400 ROUND_EXCEEDS_CANDIDATES`).
3. **Randomly sample exactly `total_rounds` locations from the candidate set, without replacement.** Use `random.sample(candidates, total_rounds)` (Python's `random` module) — do not seed the RNG, do not sort/shuffle-then-slice in a way that biases toward `id` order.
4. Create one `matches` row: `total_rounds=<request value>`, `status='in_progress'`.
5. Create `match_filters` rows:
   - For the region axis: if the request had `["ALL"]`, insert **one row** with `filter_type='region'`, `filter_value='ALL'`, `is_all=True`. Otherwise insert one row per region code with `is_all=False`.
   - Same pattern for the category axis with `filter_type='category'`.
   - (This exactly matches task order #01 §4.5's `is_all` sentinel design — do not store all 25 region rows when the user picked "ALL".)
6. Pair up the sampled `total_rounds` locations into `total_rounds / 2` games for round 1 (`round_no=1`). **Do not shuffle again before pairing** — the random sampling in step 3 already randomizes location order, so simply take the sampled list in order and pair `(list[0], list[1])`, `(list[2], list[3])`, etc. Assign `order_in_round = 0, 1, 2, ...` in that same order.
7. **Do not pre-generate rounds 2, 3, ... at this point.** Only round 1's games exist after `POST /api/matches` returns. Later rounds are generated lazily, on demand, as described in §3.4 — this is intentional (API spec §3.1 step 7 explains why: a pure single-elimination bracket with no byes has round *n+1*'s pairing fully determined by round *n*'s winners, so there is nothing valid to pre-generate).
8. If `total_rounds == 1`... this cannot happen: `ROUND_OPTIONS` starts at 4, so round 1 always has at least 2 games. No special-casing needed here. (The single-game final round is instead reached naturally when round-of-4 finishes — see §3.4.)
9. Determine `total_round_count = log2(total_rounds)` (e.g. 16 → 4 rounds: round of 16 → round of 8 → round of 4 → final). Note: "round of 4" here means 2 games; the **final** is the round with exactly 1 game, i.e. `round_no == total_round_count`.
10. Return the response shape from API spec §3.1, including the freshly created round-1, order-0 game as `first_game`.

### 3.4 Recording a Result & Advancing Rounds (`POST /api/matches/{match_id}/games/{game_id}/result`)

This is the most intricate piece of logic — implement it as its own function, e.g. `record_game_result(db, match_id, game_id, winner_id) -> GameResultOutcome`, and follow this exact order (API spec §3.3 "처리 로직"):

1. Fetch the `match_games` row for `(match_id, game_id)`. If it doesn't exist → error → router returns `404 GAME_NOT_FOUND`.
2. If `winner_id IS NOT NULL` already (i.e. this game already has a recorded result) → error → router returns `409 GAME_ALREADY_COMPLETED`.
3. If `winner_id` (from the request) is neither `location_a_id` nor `location_b_id` of this game → error → router returns `400 INVALID_WINNER`.
4. Update the row: set `winner_id`, `completed_at = now()`.
5. **Check whether the current round is now fully complete**: query all `match_games` for this `match_id` where `round_no` equals the just-completed game's `round_no`, and check whether any of them still has `winner_id IS NULL`.
   - **Case A — round not yet complete**: find the remaining game(s) in this round with `winner_id IS NULL`, pick the one with the lowest `order_in_round`, and return it as `next_game`. Response: `is_final_result=false`, `status='in_progress'`.
   - **Case B — round just completed, and it was the final** (i.e. that round had exactly 1 game and `is_final=True`): update the `matches` row to `status='finished'`, `finished_at=now()`. Return `is_final_result=true`, `status='finished'`, `next_game=null`, `winner_location_id=<that game's winner_id>`.
   - **Case C — round just completed, but it was not the final**: this is the "advance to next round" case, see §3.5 below.

### 3.5 Generating the Next Round (Case C above)

1. Collect this round's winners **in `order_in_round` ascending order** (i.e., the order in which the games were laid out — not the order in which results happened to be submitted, since a user could in theory submit game 2's result before game 1's, though the UI won't normally allow that). Requirements spec §2.3 S2: "직전 라운드 승자끼리 순서대로 대결" (winners face off *in order* — no reshuffling).
2. Pair them up the same way as §3.3 step 6: `(winners[0], winners[1])`, `(winners[2], winners[3])`, etc., as the games of `round_no = current_round_no + 1`, with `order_in_round = 0, 1, 2, ...`.
3. If this newly created round has exactly 1 game, mark that game `is_final=True`. Otherwise leave `is_final=False` on all of them (round 1's games are also always `is_final=False` unless `total_rounds == 2`, which cannot occur since 2 is not in `ROUND_OPTIONS`).
4. Return the first game of the new round (`order_in_round=0`) as `next_game`. Response: `is_final_result=false`, `status='in_progress'`.

> **Why lazy generation matters for correctness**: because round *n+1* is only createable once all of round *n*'s winners are known, trying to pre-generate the whole bracket at `POST /api/matches` time is not just unnecessary — it's impossible to do correctly (you'd have to fake placeholder winners). Do not attempt it. If a future task order needs to preview an entire bracket, that is a separate, additive feature — not something to retrofit into this creation flow.

### 3.6 Resuming a Match (`GET /api/matches/{match_id}`)

Used for refresh/back-navigation recovery (requirements spec MATCH-05). Logic (API spec §3.2):

1. If `matches.status == 'finished'` → return a result whose router-level handling is `409 MATCH_ALREADY_FINISHED` with `detail.redirect_to = f"/worldcup/{match_id}/result"` in the body (see API spec §3.2's error example for the exact shape — this is a body field alongside `error_code`/`message`, not a separate mechanism).
2. Otherwise, find the `match_games` row with `winner_id IS NULL` that has the lowest `(round_no, order_in_round)` — this is guaranteed to be unique and to exist for any `in_progress` match, since rounds are generated lazily and a round is only advanced once fully complete.
3. Compute `round_display` server-side: `N강 = total_rounds // 2**(round_no - 1)`, `M번째 경기 = order_in_round + 1`, formatted as the Korean string `"{N}강 {M}번째 경기"` (e.g. `"16강 2번째 경기"`). Match the exact format from `API명세서.md` §3.2 — the frontend renders this string as-is.

### 3.7 Fetching the Final Result (`GET /api/matches/{match_id}/result`)

1. If `matches.status != 'finished'` → `409 MATCH_NOT_FINISHED`.
2. Find the `match_games` row where `is_final=True` for this match, read its `winner_id`, and join to `locations` for the full location payload (API spec §3.4 response shape — all the fields needed for the map pin + headline on the result screen).

---

## 4. Endpoint Specifications

For each endpoint below, the authoritative request/response JSON shapes — including every example, every field, and every error case — live in `API명세서.md`. **Do not redefine the contract here**; this section only calls out implementation notes specific to each route that aren't obvious from the API spec alone.

### 4.1 `GET /api/locations/candidates`
- Reference: `API명세서.md` §2.1
- FastAPI signature: `regions: list[str] = Query(...)`, `categories: list[str] = Query(...)` — note these are **required** (`...`), not `Query(default=[])`, because the API spec marks them required and specifies `422` when absent/empty. Add a manual check that rejects an empty list even though the parameter was technically present (FastAPI won't reject `?regions=` producing `[]` on its own) — raise `HTTPException(422, ...)` with a body matching FastAPI's native validation error shape shown in the API spec's `422` example, or simply structure the Pydantic dependency so an empty list is naturally rejected via `Query(..., min_length=1)`.
- Calls `get_candidate_locations()` (§3.1) then `compute_available_rounds()` (§3.2). Returns `candidate_count` and `available_rounds` — no DB writes.

### 4.2 `GET /api/locations/{location_id}`
- Reference: `API명세서.md` §2.2
- Simple `SELECT` by primary key. Return `404 LOCATION_NOT_FOUND` if absent. Remember: `map_x`/`map_y`/`first_image` may legitimately be `null` — that is not an error condition, just pass the DB's `NULL` straight through as JSON `null`.
- This endpoint technically belongs to the "locations" resource rather than "match," but it's included in this task order because both the match-result screen and later screens need it, and it's trivial once `locations` is seeded (task order #01). Do not gold-plate it with fields not in the API spec's response shape.

### 4.3 `POST /api/matches`
- Reference: `API명세서.md` §3.1
- Request body validated via a `MatchCreateRequest` Pydantic model: `regions: list[str]`, `categories: list[str]` (both non-empty — enforce via `Field(min_length=1)`), `total_rounds: Literal[4, 8, 16, 32, 64]` (use `Literal` so FastAPI's automatic `422` matches the API spec's literal-error example exactly).
- On success return `201 Created` with the `MatchCreateResponse` shape from the API spec (`match_id`, `total_rounds`, `status`, `current_round_no`, `total_round_count`, `first_game`).
- On `RoundExceedsCandidatesError` from the service layer, return `400` with `error_code="ROUND_EXCEEDS_CANDIDATES"` and a message that includes the requested round count and actual candidate count (see the API spec's example message for the expected phrasing style).

### 4.4 `GET /api/matches/{match_id}`
- Reference: `API명세서.md` §3.2
- Return `404 MATCH_NOT_FOUND` if the match doesn't exist at all (distinct from `409` which is for a match that exists but is finished).

### 4.5 `POST /api/matches/{match_id}/games/{game_id}/result`
- Reference: `API명세서.md` §3.3
- Request body: `GameResultRequest` with a single field `winner_id: int`.
- This is the endpoint most likely to have subtle bugs — write it defensively and validate against the unit/integration tests in §6 before considering it done.
- Response shape varies by outcome (`next_game` present vs. `winner_location_id` present vs. neither) — model this with a single `GameResultResponse` schema where the outcome-specific fields are `Optional`, matching the three response examples in the API spec exactly (field presence/absence, not just types).

### 4.6 `GET /api/matches/{match_id}/result`
- Reference: `API명세서.md` §3.4
- Note this endpoint does **not** include reviews — reviews are a separate domain/task order. Do not join review data in here even though it might seem convenient for the frontend; the API spec is explicit that reviews are fetched separately (§3.4's note: "리뷰 목록은 별도 엔드포인트로 조회").

---

## 5. Error Handling Checklist

Every row below must be independently verifiable (see §6's test list). Use the shared error envelope from `API명세서.md` §0.5 — i.e. route handlers should raise `HTTPException(status_code=..., detail={"error_code": "...", "message": "..."})`, not `HTTPException(status_code=..., detail="...")` with a bare string.

| Endpoint | Status | error_code | Trigger |
|---|---|---|---|
| `GET /api/locations/candidates` | `422` | (FastAPI native) | `regions` or `categories` missing or empty |
| `GET /api/locations/{id}` | `404` | `LOCATION_NOT_FOUND` | unknown `location_id` |
| `POST /api/matches` | `400` | `ROUND_EXCEEDS_CANDIDATES` | candidate count < `total_rounds` |
| `POST /api/matches` | `422` | (FastAPI native) | `total_rounds` not in `{4,8,16,32,64}`, or `regions`/`categories` empty |
| `GET /api/matches/{id}` | `404` | `MATCH_NOT_FOUND` | unknown `match_id` |
| `GET /api/matches/{id}` | `409` | `MATCH_ALREADY_FINISHED` | match exists but `status='finished'` (body includes `redirect_to`) |
| `POST .../games/{gid}/result` | `404` | `GAME_NOT_FOUND` | `game_id` doesn't belong to `match_id` |
| `POST .../games/{gid}/result` | `400` | `INVALID_WINNER` | `winner_id` isn't the game's `location_a_id`/`location_b_id` |
| `POST .../games/{gid}/result` | `409` | `GAME_ALREADY_COMPLETED` | game already has a recorded `winner_id` |
| `GET /api/matches/{id}/result` | `404` | `MATCH_NOT_FOUND` | unknown `match_id` |
| `GET /api/matches/{id}/result` | `409` | `MATCH_NOT_FINISHED` | match still `in_progress` |

---

## 6. Required Tests

Write these as automated tests (pytest + FastAPI's `TestClient`, or pytest against `match_service` functions directly where noted) before reporting this task complete. Use a separate test SQLite database (e.g. `sqlite:///./test.db` or an in-memory `sqlite:///:memory:`), seeded with a small, deterministic fixture set of `locations` rows — do not run tests against the real seeded `app.db` from task order #01.

### 6.1 Unit tests — pure logic (no DB, no FastAPI)
- `compute_available_rounds(3) == []`
- `compute_available_rounds(4) == [4]`
- `compute_available_rounds(50) == [4, 8, 16, 32]`
- `compute_available_rounds(100) == [4, 8, 16, 32, 64]`

### 6.2 Integration tests — candidate filtering
- Seed locations across at least 3 distinct `l_dong_signgu_cd` values and 3 distinct `category` values. Verify:
  - `regions=["ALL"], categories=["ALL"]` returns every seeded location.
  - `regions=[<one code>], categories=["ALL"]` returns only that district's locations, across all categories.
  - `regions=["ALL"], categories=[<one category>]` returns only that category, across all districts.
  - `regions=[<code A>, <code B>], categories=[<cat X>]` returns the correct intersection — locations in district A or B **and** category X (not district A-or-B-or-category-X; verify this is a true AND/intersection, not a union, since this is the exact bug the requirements spec warns about).

### 6.3 Integration tests — match creation
- Creating a match with `total_rounds` greater than the candidate count returns `400 ROUND_EXCEEDS_CANDIDATES` and creates **no** `matches`/`match_filters`/`match_games` rows (verify no partial writes).
- Creating a valid match with `total_rounds=4` creates exactly 1 `matches` row, the correct `match_filters` rows (verify the `is_all` sentinel behavior for both an `["ALL"]` request and an explicit-list request), and exactly 2 `match_games` rows, all with `round_no=1`, `winner_id IS NULL`, `is_final=False`.
- The response's `first_game` matches the actual `order_in_round=0` row created in the DB.

### 6.4 Integration tests — full match playthrough (the most important test)
- Create a `total_rounds=4` match (round of 4 → 2 games in round 1, then 1 final).
- Submit a result for round-1 game 0 → response has `is_final_result=false`, `next_game` is round-1 game 1 (not yet a round-2 game, since round 1 isn't complete).
- Submit a result for round-1 game 1 → this completes round 1 → response's `next_game` is the newly created round-2 game, and `is_final=True` should be set on it (verify via DB query) since round 2 has only 1 game.
- Submit a result for the round-2 (final) game → response has `is_final_result=true`, `winner_location_id` set, `next_game=null`. Verify the `matches` row now has `status='finished'` and a non-null `finished_at`.
- `GET /api/matches/{id}/result` now returns `200` with the correct winner. Calling it before the final was submitted should have returned `409 MATCH_NOT_FINISHED` (test this at an intermediate point too).
- Also run this same playthrough for `total_rounds=8` to confirm the 3-round cascade (round of 8 → round of 4 → final) generates each round lazily and correctly, not just the trivial 2-round case above.

### 6.5 Integration tests — error cases
- Every row in §5's table gets at least one test asserting the exact `status_code` and `detail.error_code`.
- Submitting a `winner_id` that belongs to neither location in a game → `400 INVALID_WINNER`.
- Submitting a result twice for the same game → second call returns `409 GAME_ALREADY_COMPLETED`, and the winner recorded from the *first* call is unchanged.
- `GET /api/matches/{id}` on a finished match → `409 MATCH_ALREADY_FINISHED` with `detail.redirect_to == f"/worldcup/{id}/result"`.

### 6.6 Resume/recovery test
- Create a match, play one round-1 game, then call `GET /api/matches/{id}` (simulating a page refresh) — verify it returns the *other* round-1 game (the one still `winner_id IS NULL`), not the already-completed one, and that `round_display` is formatted correctly (e.g. `"4강 2번째 경기"`).

---

## 7. Explicitly Do Not Do

- Do not implement `POST /api/chat` or add any OpenAI-related code/dependencies — assigned to a separate agent.
- Do not implement `GET /api/board/rankings` or any review endpoints (`§5` of the API spec) — later task orders.
- Do not add authentication, sessions, or cookies of any kind — this service is fully anonymous by design (requirements spec §1.2).
- Do not pre-generate an entire bracket at match-creation time — see §3.3 step 7 and §3.5's note for why this is intentionally wrong to do.
- Do not introduce a `location_stats` cache table — out of scope per API spec §9, deferred until there's an actual performance need.
- Do not change anything in task order #01's deliverables (models, seed script, `.env` keys) unless you discover an actual defect in them — if you do, stop and flag it rather than silently patching around it, since other agents may depend on that contract too.

---

## 8. Reference — Requirements/API Spec Cross-Reference

| This task order's section | Requirements spec | API spec |
|---|---|---|
| §2 Meta endpoints | — | §0.6 |
| §3.1 Candidate filtering | §2.3 S1 | §2.1, §3.1 step 1 |
| §3.2 Round options | §2.3 S1 | §2.1 |
| §3.3 Match creation / bracket seeding | §2.3 S1, S2 | §3.1 |
| §3.4–3.5 Result recording / round advancement | §2.3 S2 | §3.3 |
| §3.6 Resume | MATCH-05 | §3.2 |
| §3.7 Final result | §2.3 S4 (boundary note only) | §3.4 |
| §5 Error handling | — | §0.5, and each endpoint's error table |
