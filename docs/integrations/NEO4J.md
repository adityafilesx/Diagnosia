# Neo4j

Neo4j holds three graphs for DiagnoFast. **SQLite stays the record**, and Neo4j is a read-only copy that
can be thrown away and rebuilt at any time. Nothing flows back from Neo4j to SQLite.

| Graph | What it holds | Used for |
|---|---|---|
| Question graph | Complaint → follow-up questions → associated symptoms → red-flag screening questions | Choosing the next interview question |
| History graph | Patient → visits → coded symptoms, medicines, allergies → doctors | Known context for the interview, and a picture on the doctor's report |
| Evidence graph | Report row → cited answer (turn) → recording | Showing the doctor where each row of the report came from |

It is optional and off by default. With the switch off, Neo4j unreachable, or `ALLOW_REAL_PATIENT_DATA`
on, the interview chooses follow-ups with the AI alone (as before) and the evidence view is drawn
straight from SQLite. **Made-up patients only.**

Researched on 21 November 2026. Sources are listed with each fact.

## Rules

- **Only IDs and coded terms go in.** No names, no phone numbers, no transcripts and no free text.
  Symptoms, medicines and allergies are stored as short coded terms taken from finished records.
- **SQLite decides access.** A graph query returns IDs. Anything shown on screen is read again from
  SQLite, after the normal access check (`records/access.py`) and audit log.
- **Only finished records go in.** Never a draft, an unfinished interview, an unreviewed suggestion or an
  unconfirmed medicine.
- **The question graph is product content, not patient data.** It lives in a versioned seed file in git
  (`backend/diagnofast/graph/questions_v2.json`), marked "not clinically reviewed", and Neo4j is loaded
  from it. Red-flag nodes only add screening questions. They never decide anything and never replace
  `red_flags.screen`, which still runs first on every answer.
- **Graph results are suggestions to staff.** The walk-in department suggestion is shown to staff only,
  and staff confirm it before the patient sees a department.

## How records reach Neo4j

The same pattern as patient packs (`patient_pack/sync.py`):

1. A finished change (an intake reaching `done`, a review stamp) queues a reference in `graph_items`, in
   the **same SQLite transaction** as the change. CareFlow events carry no free text, so they can trigger
   work but can't supply content. The queue holds only the source type and ID.
2. A worker in the app's sweep reads each queued record **from SQLite**, turns it into IDs and coded
   terms, and writes it with idempotent `MERGE` statements. It calls `db.release(db)` first, so no write
   lock is held during the network call.
3. A failure is retried later with backoff. A record sent twice changes nothing, because every write is a
   `MERGE` on a unique key.
4. `python -m backend.operator_cli graph-rebuild` empties the projection and queues every finished record
   again.

## The driver

| Item | Value | Source |
|---|---|---|
| Package | `neo4j` 6.4.1, Apache-2.0 (with a Python-2.0 part), Python 3.10 or later, depends only on `pytz` | The wheel's own metadata, downloaded 21 Nov 2026 from <https://pypi.org/project/neo4j/> |
| Series | The current driver is the 6.x series, which supports Neo4j 4.4, 5.x, 2025.x and 2026.x servers | <https://neo4j.com/docs/python-manual/current/install/> |
| Creating it | `GraphDatabase.driver(uri, auth=(user, password))`. It connects lazily; `driver.verify_connectivity()` checks it | <https://neo4j.com/docs/python-manual/current/connect/> |
| Lifetime | Drivers are thread-safe and expensive to create, so create one per app and share it. Sessions aren't thread-safe | <https://neo4j.com/docs/python-manual/current/connect/>, <https://neo4j.com/docs/python-manual/current/transactions/> |
| Queries | `driver.execute_query(query, params, database_="neo4j")` returns records, a summary and keys. Always pass `database_`, which saves a round trip | <https://neo4j.com/docs/python-manual/current/performance/> |
| Batching | `UNWIND $rows AS row MERGE …`: one query for many rows | <https://neo4j.com/docs/python-manual/current/performance/> |
| URI | `neo4j://` (local, unencrypted), `neo4j+s://` (CA-signed, Aura), `neo4j+ssc://` (self-signed) | <https://neo4j.com/docs/python-manual/current/connect-advanced/> |
| Errors | `neo4j.exceptions.ServiceUnavailable`, `SessionExpired` and `AuthError`, all subclasses of `Neo4jError` or `DriverError` | The package source, `neo4j/exceptions.py` |

The driver lives in `backend/requirements-integrations.txt`, next to `pymongo` and `psycopg`, because
the app runs without it. The code imports it only when the switch is on, and treats a missing package as
"Neo4j unavailable".

Idempotent writes use a uniqueness constraint per label, created once at start-up:

```cypher
CREATE CONSTRAINT patient_id IF NOT EXISTS FOR (p:Patient) REQUIRE p.id IS UNIQUE
```

and then, for example:

```cypher
UNWIND $rows AS row
MERGE (v:Visit {id: row.visit_id})
MERGE (p:Patient {id: row.patient_id})
MERGE (p)-[:HAD]->(v)
```

The next-question query uses a scoped subquery, `CALL (c) { ... }`, which needs Neo4j 5.23 or later
(the 5.26 image has it). The constraint syntax is from the Cypher manual (<https://neo4j.com/docs/cypher-manual/current/constraints/>).
It wasn't on the driver pages we read, so check it against the server version on first start.

## Running it locally

`docker-compose.integrations.yml` has a `neo4j` service:

| Item | Value | Source |
|---|---|---|
| Image | `neo4j:5.26-community`. 5.26 is the long-term support line; newer images use calendar versions such as `2026.10` | <https://hub.docker.com/_/neo4j>, <https://neo4j.com/docs/operations-manual/current/docker/introduction/> |
| Ports | 7474 (browser) and 7687 (Bolt), bound to `127.0.0.1` only | same |
| Password | `NEO4J_AUTH=neo4j/<password>` (at least 8 characters). It has no effect once a data volume already holds a database | same |
| Licence | Community Edition is GPL v3. We run the unmodified server image as a separate service and don't distribute it | <https://neo4j.com/licensing/> |

Running locally means no patient data, even made-up, goes to another company. Neo4j Aura would be a new
vendor and would need the same review as any other.

Settings: `NEO4J_URI` (for example `neo4j://127.0.0.1:7687`; empty means Neo4j is off), `NEO4J_USER` and
`NEO4J_PASSWORD`, from `.env`. The password can also be saved in Settings. Never in code.

## Live check (22 November 2026)

`CURAI_LIVE_TESTS=1 .venv/bin/python -m pytest -m live backend/tests/live/test_live_neo4j.py -s`, against
`neo4j:5.26-community` in Docker on this machine, with made-up data only: 12 of 12 passed.

- Loading the question graph twice leaves the node and relationship counts unchanged.
- For every complaint, the real next-question order and wording match the in-memory fake exactly:
  follow-ups, then red-flag screens, then associated symptoms. `CALL (c) { ... }` works on 5.26.
- Visits merge and read back, including one with no medicines, allergies or report rows (the FOREACH
  and empty-UNWIND paths). Merging a visit twice changes nothing.
- History, evidence and department votes return what the fake returns.

**Found and fixed:** three question IDs (`pain_site`, `pain_onset`, `pain_character`) had two wordings
in the seed. On a real server `MERGE` keeps one node per ID, so one wording silently replaced the other,
which the fake hid. The seed is now `questions_v2` with those IDs split, a test forbids two wordings
under one ID, and the fake now keeps one question per ID, as `MERGE` does.

Timings, local Docker: the first query of each kind took 1.5 to 1.8 s while the server planned it.
After that, each next-question step took about 2 to 6 ms, merging a visit 157 ms, history 62 ms,
evidence 47 ms and department votes 35 ms.

## Tests

Tests never need a Neo4j server. `backend/integrations/graph.py` talks to Neo4j through a small client
with a few named methods (`merge_rows`, `next_questions`, `history`, `evidence`). The tests swap in an
in-memory fake client, the same way `llm.ask` and `speech` are faked. One optional live test runs only
with `CURAI_LIVE_TESTS=1` and a local server.
