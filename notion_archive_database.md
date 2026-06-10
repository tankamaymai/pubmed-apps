# Notion Archive Database

Created with the Notion connector for this project.

- Database title: `PubMed肩関節グラレコ配信アーカイブ`
- Database URL: `https://app.notion.com/p/c78096bc6401494999e598ed022e84a8`
- Database ID for `NOTION_DATABASE_ID`: `c78096bc6401494999e598ed022e84a8`
- Data source URL: `collection://59c66bff-948e-4bca-99c0-bb68a788a997`

Before the local app can write to this database through the Notion REST API:

1. Create or choose a Notion integration and copy its internal integration token to `NOTION_TOKEN`.
2. Open the database in Notion and share it with that integration.
3. Set `NOTION_DATABASE_ID=c78096bc6401494999e598ed022e84a8`.
4. Run `python -m shoulder_digest doctor` and confirm `notion_validation.ok` is true.

