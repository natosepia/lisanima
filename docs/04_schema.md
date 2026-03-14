# DBスキーマ設計: lisanima

## 1. 概要

- **DB**: PostgreSQL（既存インスタンスに `lisanima_db` データベースを作成）
- **全文検索**: pg_trgm拡張 + GINインデックス
- **文字コード**: UTF-8
- **設計方針**: MCPコマンド（外部設計: [03_mcp_interface.md](03_mcp_interface.md)）から必要なテーブルを導出する

### 命名規約

| プレフィックス | 分類 | 用途 |
|---------------|------|------|
| t_ | トランザクション | 頻繁に更新されるデータ |
| m_ | マスタ | 参照中心の定義データ |
| v_ | ビュー | 導出データ |

## 2. ER図

### コア（記憶管理）

```mermaid
erDiagram
    t_sessions ||--o{ t_messages : "1:N"
    t_messages ||--o{ t_message_tags : "1:N"
    t_tags ||--o{ t_message_tags : "1:N"

    t_sessions {
        int id PK
        text persona_id
        date date
        int session_seq
        text project
        timestamptz started_at
        timestamptz ended_at
    }

    t_messages {
        int id PK
        int session_id FK
        text speaker
        text target
        text content
        smallint joy
        smallint anger
        smallint sorrow
        smallint fun
        smallint emotion_total
        text source
        bool is_deleted
        text deleted_reason
        timestamptz created_at
    }

    t_tags {
        int id PK
        text name UK
    }

    t_message_tags {
        int message_id FK
        int tag_id FK
    }
```

### トピック管理

```mermaid
erDiagram
    t_sessions ||--o{ t_session_topics : "1:N"
    t_topics ||--o{ t_session_topics : "1:N"
    t_topics ||--o{ t_topic_roles : "1:N"
    m_role ||--o{ t_topic_roles : "1:N"

    t_sessions {
        int id PK
    }

    t_topics {
        int id PK
        text name
        text status
        bool important
        smallint joy
        smallint anger
        smallint sorrow
        smallint fun
        smallint emotion_total
        timestamptz created_at
        timestamptz closed_at
    }

    t_session_topics {
        int session_id FK
        int topic_id FK
    }

    m_role {
        int id PK
        text name UK
        text description
        timestamptz created_at
    }

    t_topic_roles {
        int topic_id FK
        int role_id FK
    }
```

### ルールブック

```mermaid
erDiagram
    t_rulebooks {
        int id PK
        text key
        text content
        int version
        text reason
        bool is_retired
        text persona_id
        timestamptz created_at
    }
```

> **v_active_rulebooks (VIEW)**: key単位で最新バージョンを取得し、そのレコードが有効（`is_retired = FALSE`）な場合のみ返すビュー。最新バージョンがretiredなら結果に含まれない。詳細はセクション3.10参照。

### OAuth 2.1

```mermaid
erDiagram
    m_oauth_client ||--o{ t_oauth_auth_session : "1:N"
    m_oauth_client ||--o{ t_oauth_auth_code : "1:N"
    m_oauth_client ||--o{ t_oauth_access_token : "1:N"
    m_oauth_client ||--o{ t_oauth_refresh_token : "1:N"

    m_oauth_client {
        text client_id PK
        jsonb client_info
        timestamptz created_at
    }

    t_oauth_auth_session {
        text session_id PK
        text client_id FK
        text redirect_uri
        text state
        text_arr scopes
        text code_challenge
        text code_challenge_method
        bool redirect_uri_provided_explicitly
        text resource
        timestamptz expires_at
        timestamptz created_at
    }

    t_oauth_auth_code {
        text code PK
        text client_id FK
        text redirect_uri
        bool redirect_uri_provided_explicitly
        text code_challenge
        text code_challenge_method
        text_arr scopes
        text resource
        timestamptz expires_at
        timestamptz created_at
    }

    t_oauth_access_token {
        text token PK
        text client_id FK
        text_arr scopes
        text resource
        timestamptz expires_at
        timestamptz created_at
    }

    t_oauth_refresh_token {
        text token PK
        text client_id FK
        text_arr scopes
        timestamptz expires_at
        timestamptz created_at
    }
```

## 3. テーブル定義

### 3.1 t_sessions（セッション）

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
- `UNIQUE(persona_id, date, session_seq)` -- マルチペルソナ対応

**persona_id について:**
- Phase 1 ではリサ1人の人格管理基盤のため、常に `'lisa'` 固定
- 将来マルチ人格対応が必要になった場合の拡張余地として用意

**ended_at の更新タイミング:**
- なとせの「おやすみ」「おわるか」等のセッション終了発言を検知した際にリサが更新
- 次回セッション開始時に前回セッションのended_atがNULLなら、前回最終メッセージのcreated_atで補完

### 3.2 t_messages（発言）

発言単位の記録。感情ベクトル・論理削除フラグを含む。

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| id | INTEGER | PK, GENERATED ALWAYS AS IDENTITY | メッセージID |
| session_id | INTEGER | FK → t_sessions.id, NOT NULL | 所属セッション |
| speaker | TEXT | NOT NULL | 発言者（CHECK制約なし。後述） |
| target | TEXT | NULLABLE | 発言先（broadcastや独白はNULL） |
| content | TEXT | NOT NULL | 発言内容 |
| joy | SMALLINT | NOT NULL, DEFAULT 0 | 喜び（0-255） |
| anger | SMALLINT | NOT NULL, DEFAULT 0 | 怒り（0-255） |
| sorrow | SMALLINT | NOT NULL, DEFAULT 0 | 哀しみ（0-255） |
| fun | SMALLINT | NOT NULL, DEFAULT 0 | 楽しさ（0-255） |
| emotion_total | SMALLINT | GENERATED ALWAYS AS (joy + anger + sorrow + fun) STORED | 感情値合計（検索用） |
| source | TEXT | NULLABLE | MCPクライアント識別子（clientInfo.name を自動記録。例: "claude-code", "claude-desktop"） |
| is_deleted | BOOLEAN | NOT NULL, DEFAULT FALSE | 論理削除フラグ |
| deleted_reason | TEXT | NULLABLE | 削除理由（forget時に記録） |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | 作成日時 |

**旧仕様からの変更:**
- `category` 列を削除（m_category廃止に伴い、分類はタグで吸収）
- `idx_t_messages_category` インデックスを削除
- `emotion` INTEGER列を `joy`, `anger`, `sorrow`, `fun` の4カラムに分離（emotion 4カラム独立化）
- `emotion_total` をビットシフト式から単純加算の生成列に変更

**speaker にCHECK制約を付けない理由:**
- Phase 3でマルチユーザー（複数AI人格）対応を予定しており、発言者が現在の6名に限定されない
- speakerはユーザー側の拡張で増える性質

**emotion_total（Generated Column）:**
- `joy + anger + sorrow + fun` で自動計算
- recallのemotion_filterフィルタ、reflectの並び替えに使用
- Generated Columnなので手動更新不要、インデックスも作成可能

### 3.3 t_tags（タグ）

連想記憶のためのタグ。

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| id | INTEGER | PK, GENERATED ALWAYS AS IDENTITY | タグID |
| name | TEXT | NOT NULL, UNIQUE | タグ名（正規化済み） |

**タグ名の正規化ルール:**
- INSERT時に `lower(trim(name))` を適用する（アプリケーション層で実施）
- `PostgreSQL` と `postgresql` と `POSTGRESQL` は同一タグとして扱う
- 全角英数字は半角に正規化する（例: `Ｐｙｔｈｏｎ` → `python`）

### 3.4 t_message_tags（メッセージ-タグ紐付け）

t_messages と t_tags の多対多リレーション。

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| message_id | INTEGER | FK → t_messages.id, NOT NULL | メッセージID |
| tag_id | INTEGER | FK → t_tags.id, NOT NULL | タグID |

**制約:**
- `PRIMARY KEY(message_id, tag_id)`

**ON DELETE CASCADE に関する注意:**
- t_messages, t_message_tags には `ON DELETE CASCADE` を設定している
- t_sessionsを物理削除すると配下のt_messages・t_message_tagsが連鎖削除される
- 通常運用ではforgetコマンドによる**論理削除（is_deleted = TRUE）のみ**を行い、物理削除は行わない
- 物理削除は移行やり直し時の `TRUNCATE ... CASCADE` のみに限定する

### 3.5 t_topics（トピック/議題）

セッション横断で管理される議題。

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| id | INTEGER | PK, GENERATED ALWAYS AS IDENTITY | トピックID |
| name | TEXT | NOT NULL | トピック名（UNIQUEにしない。同名でも別インスタンス） |
| status | TEXT | NOT NULL, DEFAULT 'open', CHECK (status IN ('open', 'closed')) | 状態 |
| important | BOOLEAN | NOT NULL, DEFAULT FALSE | 重要フラグ |
| joy | SMALLINT | NOT NULL, DEFAULT 0 | 喜び（0-255） |
| anger | SMALLINT | NOT NULL, DEFAULT 0 | 怒り（0-255） |
| sorrow | SMALLINT | NOT NULL, DEFAULT 0 | 哀しみ（0-255） |
| fun | SMALLINT | NOT NULL, DEFAULT 0 | 楽しさ（0-255） |
| emotion_total | SMALLINT | GENERATED ALWAYS AS (joy + anger + sorrow + fun) STORED | 感情値合計（検索用） |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | 作成日時 |
| closed_at | TIMESTAMPTZ | NULLABLE | クローズ日時 |

**emotion_total（Generated Column）:**
- `joy + anger + sorrow + fun` で自動計算

**設計判断:**
- nameをUNIQUEにしない理由: 同じ議題名でも時期が異なれば別インスタンスとして管理する
- category列なし: m_category廃止に伴い、分類はタグで吸収する

### 3.6 t_session_topics（セッション×トピック）

t_sessions と t_topics の N:N 中間テーブル。

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| session_id | INTEGER | FK → t_sessions(id) ON DELETE CASCADE, NOT NULL | セッションID |
| topic_id | INTEGER | FK → t_topics(id) ON DELETE CASCADE, NOT NULL | トピックID |

**制約:**
- `PRIMARY KEY(session_id, topic_id)`

### 3.7 m_role（役割マスタ）

トピックに紐づく役割の定義。

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| id | INTEGER | PK, GENERATED ALWAYS AS IDENTITY | 役割ID |
| name | TEXT | NOT NULL, UNIQUE | 役割名 |
| description | TEXT | NULLABLE | 役割の説明 |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | 作成日時 |

**初期データ:**

| name | description |
|------|-------------|
| sparring | 議論の壁打ち相手 |
| support | サポート・補助 |
| review | レビュー・品質確認 |
| study | 学習・研究 |
| casual | 雑談・日常会話 |
| coaching | 指導・コーチング |
| writing | 文章作成・編集 |
| analysis | 分析・調査レポート |
| planning | 計画立案 |
| creative | 創作 |
| facilitation | 議論整理・ファシリテーション |

### 3.8 t_topic_roles（トピック×役割）

t_topics と m_role の N:N 中間テーブル。

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| topic_id | INTEGER | FK → t_topics(id) ON DELETE CASCADE, NOT NULL | トピックID |
| role_id | INTEGER | FK → m_role(id) ON DELETE CASCADE, NOT NULL | 役割ID |

**制約:**
- `PRIMARY KEY(topic_id, role_id)`

### 3.9 t_rulebooks（ルールブック）

イミュータブル追記型のルール管理テーブル。バージョン管理により変更履歴を保持する。

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| id | INTEGER | PK, GENERATED ALWAYS AS IDENTITY | ルールブックID |
| key | TEXT | NOT NULL | ルールキー（プレフィックスで分類: persona.*/format.*/workflow.*） |
| content | TEXT | NOT NULL | ルール本文（Markdown） |
| version | INTEGER | NOT NULL, DEFAULT 1 | バージョン番号 |
| reason | TEXT | NULLABLE | 変更理由 |
| is_retired | BOOLEAN | NOT NULL, DEFAULT FALSE | 廃止フラグ |
| persona_id | TEXT | NULLABLE | ペルソナID（NULLなら全ペルソナ共通ルール） |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | 作成日時 |

**制約:**
- `UNIQUE(key, version)`

**設計判断:**
- イミュータブル追記型: UPDATEせず新バージョンをINSERTする。変更履歴が自動的に残る
- keyのプレフィックス: `persona.*`（人格関連）、`format.*`（出力形式）、`workflow.*`（作業手順）で分類
- persona_id: NULLは全ペルソナ共通ルール、値ありは特定ペルソナ専用ルール

### 3.10 v_active_rulebooks（ビュー）

最新かつ有効なルールのみを返すビュー。

**仕様:**
- key単位で最新バージョン（MAX(version)）を取得し、そのレコードが `is_retired = FALSE` の場合のみ返す
- 最新バージョンがretiredなら、そのkeyは結果に含まれない（旧バージョンが復活することはない）
- retireされたkeyを再度有効にするには、新バージョンをINSERTする（rulebookコマンドのset操作）

**DDL**: [server.py](../src/lisanima/server.py) または セクション7のDDLを参照

### 3.11 OAuth 2.1テーブル

OAuth 2.1認証で使用するテーブル群。既存のlisanimaテーブルとはFK関連なし（独立）。
詳細は [06_oauth.md](06_oauth.md) を参照。

#### 3.11.1 m_oauth_client（OAuthクライアント）

動的クライアント登録（RFC 7591）で登録されたクライアント情報。

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| client_id | TEXT | PK | クライアントID |
| client_info | JSONB | NOT NULL | OAuthClientInformationFull全体（RFC 7591準拠） |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | 作成日時 |

#### 3.11.2 t_oauth_auth_session（認可セッション）

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

#### 3.11.3 t_oauth_auth_code（認可コード）

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

#### 3.11.4 t_oauth_access_token（アクセストークン）

MCPリクエストのBearer認証に使用。1時間で失効。

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| token | TEXT | PK | アクセストークン |
| client_id | TEXT | FK → m_oauth_client.client_id, NOT NULL | クライアントID |
| scopes | TEXT[] | NOT NULL, DEFAULT '{}' | スコープ |
| resource | TEXT | NULLABLE | RFC 8707 resource indicator |
| expires_at | TIMESTAMPTZ | NOT NULL | 失効日時（1時間） |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | 作成日時 |

#### 3.11.5 t_oauth_refresh_token（リフレッシュトークン）

access_tokenの再取得に使用。30日で失効。

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| token | TEXT | PK | リフレッシュトークン |
| client_id | TEXT | FK → m_oauth_client.client_id, NOT NULL | クライアントID |
| scopes | TEXT[] | NOT NULL, DEFAULT '{}' | スコープ |
| expires_at | TIMESTAMPTZ | NOT NULL | 失効日時（30日） |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() | 作成日時 |

## 4. 廃止テーブル

### m_category（カテゴリマスタ）

**廃止理由:** MCPコマンドの外部設計見直しにより、どのコマンドからもcategoryが参照されないことが証明された。分類はタグで吸収する。

**マイグレーション注意:** 既存データのcategory値をトピックまたはタグに移植するマイグレーションスクリプトが別途必要。

## 5. 感情ベクトル仕様

喜怒哀楽の4感情を独立カラムで管理する。t_messages および t_topics で共通仕様。

### カラム構成

| カラム | 型 | 範囲 | 説明 |
|--------|-----|------|------|
| joy | SMALLINT | 0-255 | 喜び |
| anger | SMALLINT | 0-255 | 怒り |
| sorrow | SMALLINT | 0-255 | 哀しみ |
| fun | SMALLINT | 0-255 | 楽しさ |
| emotion_total | SMALLINT | 0-1020 | 生成列（joy + anger + sorrow + fun） |

- 各カラムは `NOT NULL DEFAULT 0` で定義
- `emotion_total` は `GENERATED ALWAYS AS (joy + anger + sorrow + fun) STORED` で自動計算される生成列
- 各感情値は独立カラムのため、直接的な大小比較・レンジ検索が可能

### 代表的な感情値

| joy | anger | sorrow | fun | 意味 |
|-----|-------|--------|-----|------|
| 255 | 0 | 0 | 255 | 成功体験（嬉しい＆楽しい） |
| 0 | 128 | 0 | 0 | ちょっとイラッとした |
| 0 | 0 | 192 | 0 | かなり苦しんだ（デバッグ地獄） |
| 0 | 255 | 0 | 0 | ブチギレ（本番障害） |
| 0 | 0 | 0 | 0 | 無感情（事実の記録） |

## 6. インデックス設計

### コアテーブル

```sql
-- pg_trgm拡張の有効化
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- t_messagesのcontent全文検索インデックス
CREATE INDEX idx_t_messages_content_trgm ON t_messages USING gin (content gin_trgm_ops);
CREATE INDEX idx_t_messages_speaker ON t_messages (speaker);
CREATE INDEX idx_t_messages_session_id ON t_messages (session_id);
CREATE INDEX idx_t_messages_created_at ON t_messages (created_at);
CREATE INDEX idx_t_messages_emotion_total ON t_messages (emotion_total);
CREATE INDEX idx_t_sessions_date ON t_sessions (date);
CREATE INDEX idx_t_tags_name_trgm ON t_tags USING gin (name gin_trgm_ops);
```

### トピック・ルールブックテーブル

```sql
-- t_topics
CREATE INDEX idx_t_topics_status ON t_topics (status);
CREATE INDEX idx_t_topics_name_trgm ON t_topics USING gin (name gin_trgm_ops);
CREATE INDEX idx_t_topics_emotion_total ON t_topics (emotion_total);
```

### OAuth用

```sql
CREATE INDEX idx_t_oauth_access_token_expires ON t_oauth_access_token (expires_at);
CREATE INDEX idx_t_oauth_refresh_token_expires ON t_oauth_refresh_token (expires_at);
CREATE INDEX idx_t_oauth_auth_code_expires ON t_oauth_auth_code (expires_at);
CREATE INDEX idx_t_oauth_auth_session_expires ON t_oauth_auth_session (expires_at);
```

## 7. DDL

```sql
-- lisanima データベース作成（手動実行）
-- CREATE DATABASE lisanima;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================================
-- コアテーブル
-- ============================================================

CREATE TABLE t_sessions (
    id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    persona_id  TEXT NOT NULL DEFAULT 'lisa',
    date        DATE NOT NULL,
    session_seq INTEGER NOT NULL DEFAULT 1,
    project     TEXT,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at    TIMESTAMPTZ,
    UNIQUE(persona_id, date, session_seq)
);

CREATE TABLE t_messages (
    id             INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id     INTEGER NOT NULL REFERENCES t_sessions(id) ON DELETE CASCADE,
    speaker        TEXT NOT NULL,
    target         TEXT,
    content        TEXT NOT NULL,
    joy            SMALLINT NOT NULL DEFAULT 0,
    anger          SMALLINT NOT NULL DEFAULT 0,
    sorrow         SMALLINT NOT NULL DEFAULT 0,
    fun            SMALLINT NOT NULL DEFAULT 0,
    emotion_total  SMALLINT GENERATED ALWAYS AS (
        joy + anger + sorrow + fun
    ) STORED,
    source         TEXT,
    is_deleted     BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_reason TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE t_tags (
    id   INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE t_message_tags (
    message_id INTEGER NOT NULL REFERENCES t_messages(id) ON DELETE CASCADE,
    tag_id     INTEGER NOT NULL REFERENCES t_tags(id) ON DELETE CASCADE,
    PRIMARY KEY (message_id, tag_id)
);

-- ============================================================
-- トピック・ルールブックテーブル
-- ============================================================

-- トピック（議題）
CREATE TABLE t_topics (
    id             INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name           TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    important      BOOLEAN NOT NULL DEFAULT FALSE,
    joy            SMALLINT NOT NULL DEFAULT 0,
    anger          SMALLINT NOT NULL DEFAULT 0,
    sorrow         SMALLINT NOT NULL DEFAULT 0,
    fun            SMALLINT NOT NULL DEFAULT 0,
    emotion_total  SMALLINT GENERATED ALWAYS AS (
        joy + anger + sorrow + fun
    ) STORED,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at      TIMESTAMPTZ
);

-- セッション×トピック（N:N中間テーブル）
CREATE TABLE t_session_topics (
    session_id INTEGER NOT NULL REFERENCES t_sessions(id) ON DELETE CASCADE,
    topic_id   INTEGER NOT NULL REFERENCES t_topics(id) ON DELETE CASCADE,
    PRIMARY KEY (session_id, topic_id)
);

-- 役割マスタ
CREATE TABLE m_role (
    id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO m_role (name, description) VALUES
    ('sparring',      '議論の壁打ち相手'),
    ('support',       'サポート・補助'),
    ('review',        'レビュー・品質確認'),
    ('study',         '学習・研究'),
    ('casual',        '雑談・日常会話'),
    ('coaching',      '指導・コーチング'),
    ('writing',       '文章作成・編集'),
    ('analysis',      '分析・調査レポート'),
    ('planning',      '計画立案'),
    ('creative',      '創作'),
    ('facilitation',  '議論整理・ファシリテーション');

-- トピック×役割（N:N中間テーブル）
CREATE TABLE t_topic_roles (
    topic_id INTEGER NOT NULL REFERENCES t_topics(id) ON DELETE CASCADE,
    role_id  INTEGER NOT NULL REFERENCES m_role(id) ON DELETE CASCADE,
    PRIMARY KEY (topic_id, role_id)
);

-- ルールブック（イミュータブル追記型）
CREATE TABLE t_rulebooks (
    id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key         TEXT NOT NULL,
    content     TEXT NOT NULL,
    version     INTEGER NOT NULL DEFAULT 1,
    reason      TEXT,
    is_retired  BOOLEAN NOT NULL DEFAULT FALSE,
    persona_id  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(key, version)
);

-- 最新かつ有効なルールのみを返すビュー
CREATE VIEW v_active_rulebooks AS
SELECT r.*
FROM t_rulebooks r
INNER JOIN (
    SELECT key, MAX(version) AS max_version
    FROM t_rulebooks
    GROUP BY key
) latest ON r.key = latest.key AND r.version = latest.max_version
WHERE r.is_retired = FALSE;

-- ============================================================
-- OAuth 2.1テーブル
-- ============================================================

CREATE TABLE m_oauth_client (
    client_id       TEXT PRIMARY KEY,
    client_info     JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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

CREATE TABLE t_oauth_access_token (
    token           TEXT PRIMARY KEY,
    client_id       TEXT NOT NULL REFERENCES m_oauth_client(client_id) ON DELETE CASCADE,
    scopes          TEXT[] NOT NULL DEFAULT '{}',
    resource        TEXT,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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

-- コアテーブル
CREATE INDEX idx_t_messages_content_trgm ON t_messages USING gin (content gin_trgm_ops);
CREATE INDEX idx_t_messages_speaker ON t_messages (speaker);
CREATE INDEX idx_t_messages_session_id ON t_messages (session_id);
CREATE INDEX idx_t_messages_created_at ON t_messages (created_at);
CREATE INDEX idx_t_messages_emotion_total ON t_messages (emotion_total);
CREATE INDEX idx_t_sessions_date ON t_sessions (date);
CREATE INDEX idx_t_tags_name_trgm ON t_tags USING gin (name gin_trgm_ops);

-- トピック・ルールブックテーブル
CREATE INDEX idx_t_topics_status ON t_topics (status);
CREATE INDEX idx_t_topics_name_trgm ON t_topics USING gin (name gin_trgm_ops);
CREATE INDEX idx_t_topics_emotion_total ON t_topics (emotion_total);

-- OAuth用
CREATE INDEX idx_t_oauth_access_token_expires ON t_oauth_access_token (expires_at);
CREATE INDEX idx_t_oauth_refresh_token_expires ON t_oauth_refresh_token (expires_at);
CREATE INDEX idx_t_oauth_auth_code_expires ON t_oauth_auth_code (expires_at);
CREATE INDEX idx_t_oauth_auth_session_expires ON t_oauth_auth_session (expires_at);
```

## 8. マイグレーション注意事項

- 既存データの `t_messages.category` をトピックまたはタグに移植するマイグレーションスクリプトが別途必要
- `t_messages.source` → t_sessions への移動はバックログとして保留中
