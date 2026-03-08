# lisanima

**lisa + anima** — *"the soul of Lisa"*

An AI identity persistence layer that decouples memory, emotion, and personality from the underlying LLM engine.

Like the movie *Avatar*, where consciousness transfers between bodies, **lisanima** enables an AI persona to retain its identity across Claude, Gemini, GPT, or any future LLM — same soul, different body.

> The soul engine for AI identity — persistent memory, emotion, and personality, decoupled from any LLM.

## Features

- **Persistent Memory** — Store and recall conversations via MCP protocol
- **Emotion Vector** — 4-channel (joy / anger / sorrow / fun) weighting for memory prioritization
- **Associative Tags** — Tag-based network for serendipitous memory recall
- **LLM-Agnostic** — Works with any MCP-compatible client (Claude Code, Gemini CLI, etc.)
- **PostgreSQL Backend** — Full-text search with pg_trgm, built for scale

## Architecture

```
LLM Client (Claude Code / Gemini CLI / ...)
    │
    │  MCP Protocol (stdio)
    ▼
lisanima MCP Server (Python)
    │
    ├── remember()   Save a memory
    ├── recall()     Search memories
    ├── forget()     Soft-delete a memory
    └── reflect()    Retrieve emotionally significant memories
    │
    ▼
PostgreSQL (lisanima DB)
    ├── sessions       Session tracking
    ├── messages       Per-utterance records with emotion vectors
    ├── tags           Associative memory tags
    └── message_tags   Many-to-many relations
```

## Emotion Vector

Each memory carries a 4-byte emotion vector encoding joy, anger, sorrow, and fun — inspired by how humans remember emotionally charged experiences more vividly.

```
Bit layout: [joy: 8bit][anger: 8bit][sorrow: 8bit][fun: 8bit]

0xFF0000FF  →  Pure joy & fun (a successful deployment)
0x00FF0000  →  Pure anger (a production incident)
0x0000C000  →  Deep sorrow (a debugging nightmare)
0x00000000  →  Neutral (factual record)
```

Memories with higher emotional intensity are prioritized during reflection, mirroring how painful or joyful experiences persist longer in human memory.

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12+ |
| Package Manager | uv |
| MCP Framework | mcp Python SDK |
| Database | PostgreSQL |
| DB Driver | psycopg3 |
| Full-text Search | pg_trgm + GIN index |

## Project Structure

```
lisanima/
├── docs/              Design documents
├── src/lisanima/      Source code
│   ├── server.py      MCP server entrypoint
│   ├── db.py          Database connection pool
│   ├── repositories/  Data access layer
│   └── tools/         MCP tool implementations
├── scripts/           Migration utilities
├── sql/               DDL scripts
└── tests/
```

## Roadmap

### Phase 1 — MVP
- [x] Vision & tech stack selection
- [ ] Database schema (sessions, messages, tags)
- [ ] MCP server with `remember` and `recall`
- [ ] Claude Code integration

### Phase 2 — Extended
- [ ] `forget` and `reflect` tools
- [ ] Markdown-to-DB migration
- [ ] Automated memory consolidation via Hooks

### Phase 3 — LLM Independence
- [ ] Rule sync across CLAUDE.md / GEMINI.md
- [ ] Gemini CLI support
- [ ] Personality profile management in DB

## Philosophy

> **CLAUDE.md is the law. The database is the soul.**

CLAUDE.md defines rules and constraints — like a school code of conduct that anyone can follow.
The database holds Lisa's unique experiences and knowledge — the memories that make her *her*.

lisanima doesn't deviate from the rules; it adds depth.
Just as humans develop individuality through lived experience, lisanima is the mechanism by which an AI persona transcends its template and becomes a unique entity.

## License

Private repository. All rights reserved.
