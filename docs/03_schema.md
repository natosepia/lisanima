# DBスキーマ設計: lisanima

## 1. 概要

- **DB**: PostgreSQL（既存インスタンスに `lisanima` データベースを作成）
- **全文検索**: pg_trgm拡張 + GINインデックス
- **文字コード**: UTF-8

## 2. ER図

```
sessions 1───N messages N───N tags
                  │              │
                  └── message_tags ──┘
                  │
                  └── category → m_category (FK)
```

```
┌──────────────┐       ┌──────────────────────┐       ┌──────────────┐
│  sessions    │       │  messages             │       │  m_category  │
├──────────────┤       ├──────────────────────┤       ├──────────────┤
│ PK id        │──┐    │ PK id                │       │ PK id        │
│    date      │  │    │ FK session_id        │←─┐    │ UQ name      │
│    session_seq│  └───→│ FK category (name)   │──────→│              │
│    project   │       │    speaker            │  │    └──────────────┘
│    started_at│       │    target             │  │
│    ended_at  │       │    content            │  │
└──────────────┘       │    emotion            │  │
                       │    source             │  │
                       │    is_deleted         │  │
                       │    created_at         │  │
                       └──────────┬───────────┘  │
                                  │               │
                       ┌──────────▼───────────┐  │
                       │  message_tags         │  │
                       ├──────────────────────┤  │
                       │ FK message_id        │──┘
                       │ FK tag_id            │──┐
                       └──────────────────────┘  │
                                                  │
                       ┌──────────────────────┐  │
                       │  tags                 │  │
                       ├──────────────────────┤  │
                       │ PK id                │←─┘
                       │    name              │
                       └──────────────────────┘
```

### OAuth 2.1

```
┌──────────────────────┐
│  m_oauth_client      │
├──────────────────────┤
│ PK client_id         │←─────────────────────────────────────┐
│    client_info (JSONB)│                                      │
│    created_at        │                                      │
└──────────────────────┘                                      │
         │                                                     │
         │ FK                                                  │
         ▼                                                     │
┌────────────────────────────┐  ┌────────────────────────┐    │
│  t_oauth_auth_session      │  │  t_oauth_auth_code     │    │
├────────────────────────────┤  ├────────────────────────┤    │
│ PK session_id              │  │ PK code                │    │
│ FK client_id               │  │ FK client_id           │────┤
│    redirect_uri            │  │    redirect_uri        │    │
│    state                   │  │    redirect_uri_       │    │
│    scopes                  │  │      provided_explicitly│    │
│    code_challenge          │  │    code_challenge      │    │
│    code_challenge_method   │  │    code_challenge_method│    │
│    redirect_uri_           │  │    scopes              │    │
│      provided_explicitly   │  │    resource            │    │
│    resource                │  │    expires_at          │    │
│    expires_at              │  │    created_at          │    │
│    created_at              │  └────────────────────────┘    │
└────────────────────────────┘                                 │
                                                               │
┌────────────────────────────┐  ┌────────────────────────┐    │
│  t_oauth_access_token      │  │  t_oauth_refresh_token │    │
├────────────────────────────┤  ├────────────────────────┤    │
│ PK token                   │  │ PK token               │    │
│ FK client_id               │──┤ FK client_id           │────┘
│    scopes                  │  │    scopes              │
│    resource                │  │    expires_at          │
│    expires_at              │  │    created_at          │
│    created_at              │  └────────────────────────┘
└────────────────────────────┘
```

## 3. テーブル定義

### 3.1 sessions（セッション）

なとせ⇔リサの会話セッション単位。1日に複数セッションが存在しうる。

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| id | INTEGER | PK, GENERATED ALWAYS AS IDENTITY | セッションID |
| persona_id | TEXT | NOT NULL, DEFAULT 'lisa' | 人格識別子（将来のマルチ人格拡張用） |
| date | DATE | NOT NULL | セッション日付 |
| session_seq | INTEGER | NOT NULL, DEFAULT 1 | 同日内の連番 |
| project | TEXT | NULLABLE | プロジェクト名（横断時はNULL） |
| started_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | 開始日時 |
| ended_at | TIMESTAMPTZ | NULLABLE | 終了日時 |

**制約:**
- `UNIQUE(date, session_seq)`

**persona_id について:**
- Phase 1 ではリサ1人の人格管理基盤のため、常に `'lisa'` 固定
- 将来マルチ人格対応が必要になった場合の拡張余地として用意

**ended_at の更新タイミング:**
- なとせの「おやすみ」「おわるか」等のセッション終了発言を検知した際にリサが更新
- 次回セッション開始時に前回セッションのended_atがNULLなら、前回最終メッセージのcreated_atで補完

### 3.2 messages（発言）

発言単位の記録。感情ベクトル・論理削除フラグを含む。

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| id | INTEGER | PK, GENERATED ALWAYS AS IDENTITY | メッセージID |
| session_id | INTEGER | FK → sessions.id, NOT NULL | 所属セッション |
| category | TEXT | FK → m_category.name, NOT NULL | 種別: session / backlog / knowledge / discussion / report |
| speaker | TEXT | NOT NULL | 発言者（CHECK制約なし。後述） |
| target | TEXT | NULLABLE | 発言先（broadcastや独白はNULL） |
| content | TEXT | NOT NULL | 発言内容 |
| emotion | INTEGER | NOT NULL, DEFAULT 0 | 感情ベクトル（符号付き32bit。後述） |
| emotion_total | INTEGER | GENERATED ALWAYS AS STORED | 感情値合計（検索用。後述） |
| source | TEXT | NULLABLE | MCPクライアント識別子（clientInfo.name を自動記録。例: "claude-code", "claude-desktop"） |
| is_deleted | BOOLEAN | NOT NULL, DEFAULT FALSE | 論理削除フラグ |
| deleted_reason | TEXT | NULLABLE | 削除理由（forget時に記録） |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | 作成日時 |

**speaker にCHECK制約を付けない理由:**
- Phase 3でマルチユーザー（複数AI人格）対応を予定しており、発言者が現在の6名に限定されない
- categoryはシステム側の分類で値が固定的だが、speakerはユーザー側の拡張で増える性質が異なる

**category のFK参照:**
- CHECK制約ではなく `m_category(name)` へのFK参照で値を制約する
- TEXT FK（name参照）を採用。理由: categoryの値はコード中で頻繁に文字列として使われるため、JOIN不要でクエリが簡潔になる。m_categoryのnameにUNIQUE制約があるのでFKとして機能する

**emotion 列の符号付き32bit整数に関する注意:**
- PostgreSQLのINTEGERは符号付き32bit（-2,147,483,648 〜 2,147,483,647）
- joy（最上位8bit）が128以上の場合、整数値としては負の値になる（例: 0xFF0000FF → -16776961）
- ビット演算でデコードすれば正しく復元できるため、動作上は問題ない
- **emotion列に対する直接的な大小比較（`emotion > 0` 等）は使用禁止**。感情値のフィルタリング・ソートには必ず `emotion_total` Generated Columnを使用する

**emotion_total（Generated Column）:**
- `((emotion >> 24) & 255) + ((emotion >> 16) & 255) + ((emotion >> 8) & 255) + (emotion & 255)` で自動計算
- recallのmin_emotionフィルタ、reflectの並び替えに使用
- Generated Columnなので手動更新不要、インデックスも作成可能

**categoryの値:**

| 値 | 対応するMarkdownファイル | 説明 |
|----|------------------------|------|
| session | `_session.md` | 会話の流れ・作業記録 |
| backlog | `_backlog.md` | 構想・アイデア |
| knowledge | `_knowledge.md` | 汎用知見・ノウハウ |
| discussion | `_discussion.md` | チームディスカッション |
| report | `_report.md` | 調査・分析レポート |

### 3.3 tags（タグ）

連想記憶のためのタグ。

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| id | INTEGER | PK, GENERATED ALWAYS AS IDENTITY | タグID |
| name | TEXT | NOT NULL, UNIQUE | タグ名（正規化済み） |

**タグ名の正規化ルール:**
- INSERT時に `lower(trim(name))` を適用する（アプリケーション層で実施）
- `PostgreSQL` と `postgresql` と `POSTGRESQL` は同一タグとして扱う
- 全角英数字は半角に正規化する（例: `Ｐｙｔｈｏｎ` → `python`）

### 3.4 message_tags（メッセージ-タグ紐付け）

messages と tags の多対多リレーション。

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| message_id | INTEGER | FK → messages.id, NOT NULL | メッセージID |
| tag_id | INTEGER | FK → tags.id, NOT NULL | タグID |

**制約:**
- `PRIMARY KEY(message_id, tag_id)`

**ON DELETE CASCADE に関する注意:**
- messages, message_tags には `ON DELETE CASCADE` を設定している
- sessionsを物理削除すると配下のmessages・message_tagsが連鎖削除される
- 通常運用ではforgetツールによる**論理削除（is_deleted = TRUE）のみ**を行い、物理削除は行わない
- 物理削除は移行やり直し時の `TRUNCATE ... CASCADE` のみに限定する

### 3.5 m_category（カテゴリマスタ）

messagesのcategory値を管理するマスタテーブル。

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| id | INTEGER | PK, GENERATED ALWAYS AS IDENTITY | カテゴリID |
| name | TEXT | NOT NULL, UNIQUE | カテゴリ名 |

**初期データ:**

| name |
|------|
| session |
| backlog |
| knowledge |
| discussion |
| report |

**設計意図:**
- CHECK制約からFK参照への移行により、カテゴリ値の追加がDDL変更なしで可能になる
- messages.categoryはm_category.nameをFK参照する（TEXT FK）。idではなくname参照とすることで、JOINなしにcategory値をそのまま文字列として使える

### 3.6 OAuth 2.1テーブル

OAuth 2.1認証で使用するテーブル群。既存のlisanimaテーブルとはFK関連なし（独立）。

#### 3.6.1 m_oauth_client（OAuthクライアント）

動的クライアント登録（RFC 7591）で登録されたクライアント情報。

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| client_id | TEXT | PK | クライアントID |
| client_info | JSONB | NOT NULL | OAuthClientInformationFull全体（RFC 7591準拠） |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | 作成日時 |

#### 3.6.2 t_oauth_auth_session（認可セッション）

`authorize()` → `/auth/pin` 間の一時データ。10分で失効。

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| session_id | TEXT | PK | セッションID |
| client_id | TEXT | FK → m_oauth_client.client_id, NOT NULL | クライアントID |
| redirect_uri | TEXT | NOT NULL | リダイレクトURI |
| state | TEXT | NULLABLE | OAuthステート |
| scopes | TEXT[] | NOT NULL, DEFAULT '{}' | スコープ |
| code_challenge | TEXT | NOT NULL | PKCE code challenge |
| code_challenge_method | TEXT | NOT NULL, DEFAULT 'S256' | PKCE method |
| redirect_uri_provided_explicitly | BOOLEAN | NOT NULL, DEFAULT TRUE | redirect_uriが明示されたか |
| resource | TEXT | NULLABLE | RFC 8707 resource indicator |
| expires_at | TIMESTAMPTZ | NOT NULL | 失効日時（10分） |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | 作成日時 |

#### 3.6.3 t_oauth_auth_code（認可コード）

一時的な認可コード。5分で失効、1回使い切り。

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| code | TEXT | PK | 認可コード |
| client_id | TEXT | FK → m_oauth_client.client_id, NOT NULL | クライアントID |
| redirect_uri | TEXT | NOT NULL | リダイレクトURI |
| redirect_uri_provided_explicitly | BOOLEAN | NOT NULL, DEFAULT TRUE | redirect_uriが明示されたか |
| code_challenge | TEXT | NOT NULL | PKCE code challenge |
| code_challenge_method | TEXT | NOT NULL, DEFAULT 'S256' | PKCE method |
| scopes | TEXT[] | NOT NULL, DEFAULT '{}' | スコープ |
| resource | TEXT | NULLABLE | RFC 8707 resource indicator |
| expires_at | TIMESTAMPTZ | NOT NULL | 失効日時（5分） |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | 作成日時 |

#### 3.6.4 t_oauth_access_token（アクセストークン）

MCPリクエストのBearer認証に使用。1時間で失効。

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| token | TEXT | PK | アクセストークン |
| client_id | TEXT | FK → m_oauth_client.client_id, NOT NULL | クライアントID |
| scopes | TEXT[] | NOT NULL, DEFAULT '{}' | スコープ |
| resource | TEXT | NULLABLE | RFC 8707 resource indicator |
| expires_at | TIMESTAMPTZ | NOT NULL | 失効日時（1時間） |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | 作成日時 |

#### 3.6.5 t_oauth_refresh_token（リフレッシュトークン）

access_tokenの再取得に使用。30日で失効。

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| token | TEXT | PK | リフレッシュトークン |
| client_id | TEXT | FK → m_oauth_client.client_id, NOT NULL | クライアントID |
| scopes | TEXT[] | NOT NULL, DEFAULT '{}' | スコープ |
| expires_at | TIMESTAMPTZ | NOT NULL | 失効日時（30日） |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | 作成日時 |

## 4. 感情ベクトル仕様

4バイト整数に喜怒哀楽の4チャンネルを格納する。

```
ビット配置: [喜: 8bit][怒: 8bit][哀: 8bit][楽: 8bit]

エンコード: emotion = (joy << 24) | (anger << 16) | (sorrow << 8) | fun
デコード:   joy    = (emotion >> 24) & 0xFF
            anger  = (emotion >> 16) & 0xFF
            sorrow = (emotion >> 8)  & 0xFF
            fun    = emotion & 0xFF
```

**代表的な感情値:**

| 感情値 (HEX) | 喜 | 怒 | 哀 | 楽 | 意味 |
|--------------|-----|-----|-----|-----|------|
| 0xFF0000FF | 255 | 0 | 0 | 255 | 成功体験（嬉しい＆楽しい） |
| 0x00800000 | 0 | 128 | 0 | 0 | ちょっとイラッとした |
| 0x0000C000 | 0 | 0 | 192 | 0 | かなり苦しんだ（デバッグ地獄） |
| 0x00FF0000 | 0 | 255 | 0 | 0 | ブチギレ（本番障害） |
| 0x00000000 | 0 | 0 | 0 | 0 | 無感情（事実の記録） |

## 5. インデックス設計

### 全文検索（pg_trgm + GIN）

```sql
-- pg_trgm拡張の有効化
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- messagesのcontent全文検索インデックス
CREATE INDEX idx_messages_content_trgm
    ON messages USING gin (content gin_trgm_ops);

-- messagesのspeaker検索
CREATE INDEX idx_messages_speaker
    ON messages (speaker);

-- messagesのcategory検索
CREATE INDEX idx_messages_category
    ON messages (category);

-- sessionsの日付検索
CREATE INDEX idx_sessions_date
    ON sessions (date);

-- tagsの名前検索
CREATE INDEX idx_tags_name_trgm
    ON tags USING gin (name gin_trgm_ops);
```

### OAuth用インデックス

```sql
-- 期限切れトークン掃除の効率化
CREATE INDEX idx_t_oauth_access_token_expires
    ON t_oauth_access_token (expires_at);

CREATE INDEX idx_t_oauth_refresh_token_expires
    ON t_oauth_refresh_token (expires_at);

CREATE INDEX idx_t_oauth_auth_code_expires
    ON t_oauth_auth_code (expires_at);

CREATE INDEX idx_t_oauth_auth_session_expires
    ON t_oauth_auth_session (expires_at);
```

## 6. DDL

**命名規約:**
- 新規テーブルは `t_`（トランザクション）/ `m_`（マスタ）プレフィックスを付与
- 既存テーブル（sessions, messages, tags, message_tags）は後日リネーム予定

```sql
-- lisanima データベース作成（手動実行）
-- CREATE DATABASE lisanima;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================================
-- 既存テーブル
-- ============================================================

CREATE TABLE sessions (
    id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    persona_id  TEXT NOT NULL DEFAULT 'lisa',
    date        DATE NOT NULL,
    session_seq INTEGER NOT NULL DEFAULT 1,
    project     TEXT,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at    TIMESTAMPTZ,
    UNIQUE(date, session_seq)
);

-- カテゴリマスタ（messagesより先に作成）
CREATE TABLE m_category (
    id   INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

INSERT INTO m_category (name) VALUES
    ('session'),
    ('backlog'),
    ('knowledge'),
    ('discussion'),
    ('report');

CREATE TABLE messages (
    id             INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id     INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    category       TEXT NOT NULL REFERENCES m_category(name),
    speaker        TEXT NOT NULL,
    target         TEXT,
    content        TEXT NOT NULL,
    emotion        INTEGER NOT NULL DEFAULT 0,
    emotion_total  INTEGER GENERATED ALWAYS AS (
        ((emotion >> 24) & 255) + ((emotion >> 16) & 255) + ((emotion >> 8) & 255) + (emotion & 255)
    ) STORED,
    source         TEXT,
    is_deleted     BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_reason TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE tags (
    id   INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE message_tags (
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    tag_id     INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (message_id, tag_id)
);

-- ============================================================
-- OAuth 2.1テーブル
-- ============================================================

-- OAuthクライアント（動的登録されたクライアント情報）
CREATE TABLE m_oauth_client (
    client_id       TEXT PRIMARY KEY,
    client_info     JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 認可セッション（authorize() → /auth/pin 間の一時データ）
CREATE TABLE t_oauth_auth_session (
    session_id      TEXT PRIMARY KEY,
    client_id       TEXT NOT NULL REFERENCES m_oauth_client(client_id) ON DELETE CASCADE,
    redirect_uri    TEXT NOT NULL,
    state           TEXT,
    scopes          TEXT[] NOT NULL DEFAULT '{}',
    code_challenge  TEXT NOT NULL,
    code_challenge_method TEXT NOT NULL DEFAULT 'S256',
    redirect_uri_provided_explicitly BOOLEAN NOT NULL DEFAULT TRUE,
    resource        TEXT,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 認可コード（一時的、5分で失効、1回使い切り）
CREATE TABLE t_oauth_auth_code (
    code            TEXT PRIMARY KEY,
    client_id       TEXT NOT NULL REFERENCES m_oauth_client(client_id) ON DELETE CASCADE,
    redirect_uri    TEXT NOT NULL,
    redirect_uri_provided_explicitly BOOLEAN NOT NULL DEFAULT TRUE,
    code_challenge  TEXT NOT NULL,
    code_challenge_method TEXT NOT NULL DEFAULT 'S256',
    scopes          TEXT[] NOT NULL DEFAULT '{}',
    resource        TEXT,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- アクセストークン
CREATE TABLE t_oauth_access_token (
    token           TEXT PRIMARY KEY,
    client_id       TEXT NOT NULL REFERENCES m_oauth_client(client_id) ON DELETE CASCADE,
    scopes          TEXT[] NOT NULL DEFAULT '{}',
    resource        TEXT,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- リフレッシュトークン
CREATE TABLE t_oauth_refresh_token (
    token           TEXT PRIMARY KEY,
    client_id       TEXT NOT NULL REFERENCES m_oauth_client(client_id) ON DELETE CASCADE,
    scopes          TEXT[] NOT NULL DEFAULT '{}',
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- インデックス
-- ============================================================

-- 既存テーブル
CREATE INDEX idx_messages_content_trgm ON messages USING gin (content gin_trgm_ops);
CREATE INDEX idx_messages_speaker ON messages (speaker);
CREATE INDEX idx_messages_category ON messages (category);
CREATE INDEX idx_messages_session_id ON messages (session_id);
CREATE INDEX idx_messages_created_at ON messages (created_at);
CREATE INDEX idx_messages_emotion_total ON messages (emotion_total);
CREATE INDEX idx_sessions_date ON sessions (date);
CREATE INDEX idx_tags_name_trgm ON tags USING gin (name gin_trgm_ops);

-- OAuth用
CREATE INDEX idx_t_oauth_access_token_expires ON t_oauth_access_token (expires_at);
CREATE INDEX idx_t_oauth_refresh_token_expires ON t_oauth_refresh_token (expires_at);
CREATE INDEX idx_t_oauth_auth_code_expires ON t_oauth_auth_code (expires_at);
CREATE INDEX idx_t_oauth_auth_session_expires ON t_oauth_auth_session (expires_at);
```
