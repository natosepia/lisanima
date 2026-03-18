# 40. Embedding基盤セットアップ

## 1. 概要

セマンティック検索（Phase 3.0）のためのembedding基盤を構築する。
ローカルで動作する日本語特化モデル **pkshatech/GLuCoSE-base-ja**（768次元）を採用し、CPU-onlyのVPS環境で実用的に運用する。

## 2. 技術選定の経緯

Discussion #17 にて、ありす（バックエンド）・桃華（UX）を中心に技術選定を議論した。

### 選定方針

- OpenAI Embedding APIは使わない（なとせ判断: 外部API非依存）
- 日本語特化モデルであること
- ローカル実行（CPU-only）で実用的な速度が出ること
- ライセンスが Apache 2.0 であること

### 候補比較

| モデル | 次元数 | 言語 | ライセンス | 備考 |
|--------|--------|------|-----------|------|
| all-MiniLM-L6-v2 | 384 | 英語主体 | Apache 2.0 | 軽量だが日本語精度に難あり |
| multilingual-e5-large | 1024 | 多言語 | MIT | 高次元、モデルサイズ大 |
| bge-m3 | 1024 | 多言語 | MIT | 高性能だがオーバースペック |
| cl-nagoya/sup-simcse-ja-large | 768 | 日本語特化 | CC-BY-SA-4.0 | ライセンスがSA条項で不採用 |
| **pkshatech/GLuCoSE-base-ja** | **768** | **日本語特化** | **Apache 2.0** | **採用** |

GLuCoSE-base-ja は日本語特化・Apache 2.0・768次元とバランスが良く、CPU推論でも実用的な速度が出るため採用とした。

## 3. 導入手順

実際の作業記録を以下に示す。

```bash
# 1. sentence-transformers 追加（PyTorch + CUDA含む、約10分）
uv add sentence-transformers

# 2. 追加依存（sentence-transformersが暗黙に必要とするもの）
uv add sentencepiece
uv add protobuf

# 3. transformers 5.x 互換性問題の回避
# GLuCoSE-base-ja の MLuke tokenizer が transformers 5.x で壊れる
uv add "transformers<5"

# 4. モデルダウンロード + 動作確認（初回約400MB DL）
uv run python -c "from sentence_transformers import SentenceTransformer; m = SentenceTransformer('pkshatech/GLuCoSE-base-ja'); print('OK', m.get_sentence_embedding_dimension())"
# → OK 768
```

## 4. ハマりどころ

### GPU版PyTorchの混入

sentence-transformers はデフォルトでGPU版PyTorch（nvidia-cuda系パッケージ）もインストールする。CPU-onlyのVPSでは不要だが、動作上の害はない。

### 暗黙の依存パッケージ

`sentencepiece` と `protobuf` は sentence-transformers が暗黙に必要とするが、自動インストールされない。手動で追加が必要。

### transformers 5.x との非互換

GLuCoSE-base-ja のトークナイザ（MLuke）は transformers 5.x で `TypeError` を起こす。`transformers<5` でバージョンをピンすること。

### HF_TOKEN 未設定の Warning

`HF_TOKEN` 環境変数が未設定の場合に Warning が出るが、GLuCoSE-base-ja はパブリックモデルのため無視して問題ない。

## 5. モデル情報

| 項目 | 値 |
|------|-----|
| Hugging Face | https://huggingface.co/pkshatech/GLuCoSE-base-ja |
| 次元数 | 768 |
| ライセンス | Apache 2.0 |
| モデルサイズ | 約532MB |
| キャッシュ場所 | `~/.cache/huggingface/hub/models--pkshatech--GLuCoSE-base-ja/` |
| CPU推論速度 | 約50ms/文（目安） |

## 6. 今後の予定（Phase 3.0 着手時）

- pgvector 導入（PostgreSQL拡張）
- remember時にembedding生成 → t_messages にベクトルカラム追加
- recall時のセマンティック検索（HNSW インデックス）
- 既存データへのバックフィル
- 関連issue: #16

## 7. 参照

- [Discussion #17: セマンティックベクトル検索の技術選定](https://github.com/natosepia/lisanima/discussions/17)
- [Issue #16: セマンティック検索用embedding API・実行環境の選定調査](https://github.com/natosepia/lisanima/issues/16)
