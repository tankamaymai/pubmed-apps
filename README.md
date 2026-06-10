# PubMed肩関節グラレコLINE配信システム

PubMedで肩関節関連の新着論文を毎日検索し、Codex CLI `app-server` 経由でChatGPTサブスク内のAI/ImageGenを使ってグラレコ風画像を作り、承認後にLINEグループへ配信するローカル常駐アプリです。

## Quick Start

```powershell
python -m shoulder_digest doctor
python -m shoulder_digest serve --host 127.0.0.1 --port 8765
```

ブラウザで `http://127.0.0.1:8765/` を開きます。
セットアップの不足は `http://127.0.0.1:8765/setup` で確認できます。

開発時にCodex/ImageGenを使わず流れだけ確認する場合:

```powershell
$env:SHOULDER_DIGEST_MOCK_AI='1'
python -m shoulder_digest run --date 2026-06-08 --dry-run
```

Windowsで毎朝07:00に自動実行する場合:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_task.ps1 -Time 07:00
```

解除:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall_windows_task.ps1
```

## Required Setup

1. `.env.example` を参考に環境変数を設定します。まず `python -m shoulder_digest init-env` を実行すると、スタンドアロンCodexパスと作成済みNotion DB ID入りの `.env` が作られます。
2. PubMed E-utilitiesはAPI keyなしでも使えます。高レート運用にしたい場合はNCBIアカウントでAPI keyを作り、`NCBI_API_KEY` に設定します。
3. スタンドアロン版Codex CLIを入れ、`codex login` でChatGPTログインします。
4. `codex app-server generate-json-schema --out schemas/codex_app_server/generated` を実行し、現在のCodexバージョンのschemaを固定します。
5. LINE DevelopersでMessaging API channelを作り、`LINE_CHANNEL_ACCESS_TOKEN` と `LINE_CHANNEL_SECRET` を設定します。
6. LINE Official Accountの「グループ・複数人トークへの参加」を有効にし、Botを対象グループへ招待します。
7. `POST /webhook/line` をLINE webhookに設定し、グループ内で何か送るかjoinイベントを発生させて `groupId` を保存します。groupIdが既に分かっている場合は `python -m shoulder_digest set-line-group --group-id C...` または `/setup` のフォームで保存できます。
8. Notion API integrationとデータベースを作り、`NOTION_TOKEN` と `NOTION_DATABASE_ID` を設定します。

## Important Runtime Notes

- AI用途にOpenAI API keyは使いません。Codex CLIのChatGPTログインを使います。
- このアプリはローカルPC限定です。`codex app-server` のWebSocket公開やVPS公開はしません。
- LINEの画像メッセージはLINE側から取得できるHTTPS画像URLが必要です。実送信には `SHOULDER_DIGEST_PUBLIC_BASE_URL` をngrok/Cloudflare Tunnel等の公開HTTPS URLに設定してください。
- `SHOULDER_DIGEST_MOCK_AI=1` の場合、CodexとImageGenを呼ばずにダミー要約とダミー画像パスで処理します。PubMed/LINE/Notionのロジック確認用です。
- `NCBI_API_KEY` は任意です。未設定でもPubMed E-utilitiesを使いますが、NCBIの低レート制限に合わせた運用になります。
- `SHOULDER_DIGEST_PUBMED_LOOKBACK_DAYS` はPubMed検索の登録日lookbackです。既定は3日で、同じPMIDは重複配信しないため、朝の登録遅延を吸収しやすくしています。
- `SHOULDER_DIGEST_AUTO_SEND=1` にすると、日次ジョブ完了後に承認待ちを挟まずLINEへ自動送信します。既定は `0` で、Web UIの承認ボタンから送信します。
- LINEの `groupId` は `.env` の `LINE_GROUP_ID` に直接設定するか、`POST /webhook/line` で受け取ったグループイベントからSQLiteへ保存できます。`/setup` はどちらも認識します。
- `NOTION_API_BASE_URL` と `LINE_API_BASE_URL` はテスト用の高度設定です。本番運用では既定の公式API URLを使います。
- `python -m shoulder_digest doctor` は、Codex CLIが実行可能か、Codex schemaが生成済みか、LINE画像配信用URLがあるか、Notion DB schemaが期待通りかを確認します。
- `python -m shoulder_digest preflight --allow-incomplete` は、Codex schema、PubMed、Notion、LINEの実行前ゲートをJSONで確認します。PubMedへの実接続も確認したい場合は `--live-pubmed` を付けます。

## HTTP Interfaces

- `GET /healthz`
- `GET /setup`
- `POST /setup/line-group`
- `POST /jobs/daily` with JSON `{ "date": "YYYY-MM-DD", "dryRun": true }`
- `GET /runs/{date}`
- `POST /runs/{date}/approve-send`
- `POST /webhook/line`
- `GET /generated-images/{filename}`

## CLI

```powershell
python -m shoulder_digest serve --schedule
python -m shoulder_digest run --date 2026-06-08 --dry-run
python -m shoulder_digest approve-send --date 2026-06-08
python -m shoulder_digest set-line-group --group-id Cxxxxxxxx
python -m shoulder_digest doctor
python -m shoulder_digest preflight --allow-incomplete
```

## Notion Database Properties

This repository has a prepared Notion archive database recorded in [notion_archive_database.md](notion_archive_database.md). Share that database with your Notion integration, then set:

```powershell
$env:NOTION_DATABASE_ID='c78096bc6401494999e598ed022e84a8'
```

Create a database with exactly these property names and types:

- `Title` title
- `PMID` rich text
- `PubMed URL` URL
- `Publication Date` date
- `Journal` rich text
- `Topics` multi-select
- `Evidence Type` rich text
- `Relevance Score` number
- `Japanese Summary` rich text
- `Image Prompt` rich text
- `Image Path/URL` URL
- `Run Date` date
- `Status` rich text
- `LINE Delivered` checkbox
- `Error` rich text

`doctor` will report missing or mismatched properties when `NOTION_TOKEN` and `NOTION_DATABASE_ID` are configured.

## Tests

```powershell
python -m unittest discover -s tests
```
