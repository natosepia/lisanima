# CRUDマトリックス

## 1. 概要

lisanima の6つのMCPコマンドおよびOAuth認証フローが、各テーブルに対してどのCRUD操作を行うかを一覧化する。

**作成背景**: issue #26（設計ドキュメント: CRUDマトリックス + 情報参照ビュー）のD-1として作成。

**凡例**

| 記号 | 意味 |
|------|------|
| C | CREATE（INSERT） |
| R | READ（SELECT） |
| U | UPDATE |
| D | DELETE（物理削除） |
| - | 操作なし |

## 2. テーブル一覧

### コアテーブル

| テーブル/ビュー | 種別 | 役割 |
|----------------|------|------|
| t_sessions | トランザクション | セッション（日付単位の会話区切り） |
| t_messages | トランザクション | メッセージ（記憶の最小単位） |
| t_tags | トランザクション | タグマスタ |
| t_message_tags | トランザクション | メッセージ-タグの多対多中間テーブル |
| t_topics | トランザクション | トピック |
| t_message_topics | トランザクション | メッセージ-トピックの多対多中間テーブル |
| t_message_roles | トランザクション | メッセージ-ロールの多対多中間テーブル |
| m_role | マスタ | ロールマスタ |
| m_rulebooks | マスタ | ルールブック（イミュータブル追記型） |
| v_active_rulebooks | ビュー | アクティブなルール（最新version かつ is_retired=FALSE） |

### OAuthテーブル

| テーブル | 種別 | 役割 |
|---------|------|------|
| m_oauth_client | マスタ | OAuthクライアント登録情報 |
| t_oauth_auth_session | トランザクション | 認可セッション（一時保存） |
| t_oauth_auth_code | トランザクション | 認可コード（1回使い切り） |
| t_oauth_access_token | トランザクション | アクセストークン |
| t_oauth_refresh_token | トランザクション | リフレッシュトークン |

## 3. CRUDマトリックス

### 3.1 MCPコマンド × テーブル

| テーブル | remember | recall | forget | organize | rulebook | topic_manage |
|---------|----------|--------|--------|----------|----------|-------------|
| t_sessions | CR | R | - | - | - | - |
| t_messages | C | R | U | R | - | - |
| t_tags | - | R | - | CR | - | - |
| t_message_tags | - | R | - | CD | - | - |
| t_topics | R | - | - | - | - | CRU |
| t_message_topics | C | R | - | R | - | CRD |
| t_message_roles | C | R | - | - | - | - |
| m_role | CR | R | - | - | - | - |
| m_rulebooks | - | - | - | - | CRU | - |
| v_active_rulebooks | - | - | - | - | R | - |

#### 各コマンドの詳細

**remember**
- t_sessions: `findOrCreateSession` で既存セッションをSELECT FOR UPDATE（R）、なければINSERT（C）
- t_messages: `insertMessage` でINSERT（C）
- t_topics: `getTopicById` でSELECT（R）。topic_id指定時のみ存在確認
- t_message_topics: `linkMessageTopic` でINSERT ON CONFLICT DO NOTHING（C）。topic_id指定時のみ
- m_role: `_findOrCreateRoles` でINSERT ON CONFLICT / SELECT（CR）。roles指定時のみ
- t_message_roles: `linkMessageRoles` でINSERT ON CONFLICT DO NOTHING（C）。roles指定時のみ

**recall**
- t_messages: `searchMessages` でSELECT（R）。JOINでt_sessions、条件によりt_tags/t_message_tags/t_message_topics/t_message_rolesも参照
- t_sessions: JOIN先として参照（R）
- t_tags: タグフィルタ時にJOIN（R）
- t_message_tags: タグフィルタ時・結果のタグ取得時にJOIN（R）
- t_message_topics: topic_idフィルタ時・topics_emptyフィルタ時にサブクエリで参照（R）
- t_message_roles: rolesフィルタ時にサブクエリで参照（R）
- m_role: rolesフィルタ時にJOIN（R）

**forget**
- t_messages: `softDelete` でUPDATE（is_deleted=TRUE, deleted_reason設定）。論理削除のためDではなくU

**organize**
- t_messages: `searchMessages` で対象メッセージを特定（R）。検索条件指定時のみ
- t_tags: `findOrCreateTags` で既存タグSELECT / 未登録タグINSERT（CR）。add_tags時のみ
- t_message_tags: `linkMessageTagsBatch` でINSERT（C）、`unlinkMessageTagsBatch` でDELETE（D）
- t_message_topics: topic_idフィルタ時にサブクエリで参照（R）

**rulebook**
- m_rulebooks: `setRulebook` で最新versionをSELECT後、新versionでINSERT（CR）。`retireRulebook` でSELECT後、is_retired=TRUEにUPDATE（RU）
- v_active_rulebooks: `getRulebook` / `listRulebooks` でSELECT（R）

**topic_manage**
- t_topics: create=INSERT（C）、close/reopen=UPDATE（U）、update=SELECT/UPDATE（RU）、list=SELECT（R）
- t_message_topics: create時にmessage_ids指定ありならINSERT（C）。update時にadd_message_ids指定ありならINSERT（C）、remove_message_ids指定ありならDELETE（D）。list時にCOUNTでmessage_count導出（R）

### 3.2 OAuth認証フロー × テーブル

| テーブル | DCR (register) | authorize | PIN認証 (GET) | PIN認証 (POST) | token (exchange) | token (refresh) | revoke | verify (load_access_token) | cleanup |
|---------|----------------|-----------|---------------|----------------|------------------|-----------------|--------|---------------------------|---------|
| m_oauth_client | CU | R | - | - | R | R | - | - | - |
| t_oauth_auth_session | - | C | R | RD | - | - | - | - | D |
| t_oauth_auth_code | - | - | - | C | RD | - | - | - | D |
| t_oauth_access_token | - | - | - | - | C | C | D | R | D |
| t_oauth_refresh_token | - | - | - | - | C | CD | D | - | D |

#### 各フローの詳細

**DCR (Dynamic Client Registration)**
- m_oauth_client: `saveClient` でINSERT ON CONFLICT DO UPDATE（CU）

**authorize**
- m_oauth_client: `get_client` でSELECT（R）。FastMCPフレームワークがクライアント検証で呼び出す
- t_oauth_auth_session: `saveAuthSession` でINSERT（C）

**PIN認証 (GET)**
- t_oauth_auth_session: `loadAuthSession` でSELECT（R）。セッション存在確認

**PIN認証 (POST)**
- t_oauth_auth_session: `loadAuthSession` でSELECT（R）、`deleteAuthSession` でDELETE（D）。検証成功/拒否時に削除
- t_oauth_auth_code: `saveAuthCode` でINSERT（C）。PIN検証成功時のみ

**token (exchange_authorization_code)**
- m_oauth_client: `get_client` でSELECT（R）。FastMCPフレームワークが呼び出す
- t_oauth_auth_code: `loadAuthCode` でSELECT（R）、`deleteAuthCode` でDELETE（D）。1回使い切り
- t_oauth_access_token: `saveAccessToken` でINSERT（C）
- t_oauth_refresh_token: `saveRefreshToken` でINSERT（C）

**token (exchange_refresh_token)**
- m_oauth_client: `get_client` でSELECT（R）
- t_oauth_refresh_token: `loadRefreshToken` でSELECT / `deleteRefreshToken` でDELETE / `saveRefreshToken` でINSERT（CRD）。トークンローテーション
- t_oauth_access_token: `saveAccessToken` でINSERT（C）

**revoke**
- t_oauth_access_token: `deleteAccessToken` / `deleteAccessTokensByClientId` でDELETE（D）
- t_oauth_refresh_token: `deleteRefreshToken` / `deleteRefreshTokensByClientId` でDELETE（D）

**verify (load_access_token)**
- t_oauth_access_token: `loadAccessToken` でSELECT（R）。リクエストごとの認証検証

**cleanup (cleanupExpiredTokens)**
- t_oauth_auth_session / t_oauth_auth_code / t_oauth_access_token / t_oauth_refresh_token: 期限切れレコードをDELETE（D）

## 4. 備考

- **論理削除**: `forget` コマンドは t_messages の `is_deleted` フラグをTRUEに更新する。物理削除（DELETE）は行わないため、CRUD上はU（UPDATE）として分類する
- **Generated Column**: t_messages の `emotion_total` は `joy + anger + sorrow + fun` の生成列（GENERATED ALWAYS AS STORED）であり、直接のINSERT/UPDATE対象ではない
- **イミュータブル追記**: m_rulebooks はバージョン管理のため、既存レコードのcontentを更新するのではなく新versionのレコードをINSERTする。retire時のみ既存レコードの `is_retired` をUPDATEする
- **ビュー**: v_active_rulebooks は m_rulebooks に対するビューであり、直接の書き込み操作は不可。rulebook の get / list で参照に使用する
- **ON CONFLICT DO NOTHING**: t_tags、t_message_tags、t_message_topics、t_message_roles、m_role で使用。冪等性を確保し、重複挿入を安全に無視する
- **ON CONFLICT DO UPDATE**: m_oauth_client の `saveClient` で使用。既存クライアント情報の上書き更新を行うため、CU（CREATE or UPDATE）として分類する
- **endSession**: session_repo に `endSession`（t_sessions を UPDATE）が定義されているが、現在どのMCPコマンドからも呼び出されていない。将来の拡張用として存在する
