from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from .codex_client import CodexAppServerClient
from .image_watcher import ImageWatcher
from .models import DigestPaper, DigestResult, Paper


def build_summary_prompt(run_date: str, papers: list[Paper]) -> str:
    payload = {
        "run_date": run_date,
        "papers": [paper.to_ai_dict() for paper in papers],
    }
    return (
        "あなたは肩関節領域に詳しい医療者向け編集者です。\n"
        "以下のPubMed論文JSONだけを根拠に、日本語の論文ダイジェストを作ってください。\n"
        "推測で効果量や結論を補わないでください。abstractにないことは書かないでください。\n"
        "返答はMarkdownなしのJSONのみです。\n"
        "JSON schema:\n"
        "{\n"
        '  "digest_summary": "全体を2-3文で要約",\n'
        '  "image_prompt": "4:5縦長の雑誌特集風インフォグラフィック・グラレコ画像を生成するための日本語プロンプト",\n'
        '  "papers": [\n'
        "    {\n"
        '      "pmid": "string",\n'
        '      "title": "string",\n'
        '      "japanese_summary": "目的・方法・結果・臨床的意味を4文以内",\n'
        '      "clinical_takeaway": "現場向けの一言",\n'
        '      "topics": ["string"],\n'
        '      "evidence_type": "string"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        f"PubMed JSON:\n{json.dumps(payload, ensure_ascii=False)}"
    )


def build_image_prompt(digest: DigestResult) -> str:
    paper_lines = []
    for paper in digest.papers:
        paper_lines.append(
            f"- PMID {paper.pmid}: {paper.title}\n  要点: {paper.clinical_takeaway or paper.japanese_summary}"
        )
    source_text = (
        f"全体要約: {digest.digest_summary}\n\n"
        "論文:\n"
        + "\n".join(paper_lines)
    )
    return (
        "あなたは雑誌の特集ページを作るアートディレクター兼情報デザイナーです。\n"
        "以下の「可視化したい情報」を、読みやすく美しい日本語インフォグラフィック風グラレコにしてください。\n"
        "\n"
        "コンセプト：\n"
        "- 雑誌の見開き特集ページのような、洗練された図解グラレコ\n"
        "- 手描き感と編集デザインのバランスを取る\n"
        "- SNSで保存したくなる、情報価値の高い1枚にする\n"
        "\n"
        "ビジュアルスタイル：\n"
        "- クリーンな白背景、または淡い紙のような背景\n"
        "- 手描き風の線と、整った編集レイアウトを組み合わせる\n"
        "- 見出し、サブ見出し、ミニコラム、アイコン、図解を使う\n"
        "- 配色は4色以内\n"
        "- 落ち着いた色味で、知的・親しみやすい印象\n"
        "- かわいすぎず、ビジネスや学習にも使える雰囲気\n"
        "\n"
        "レイアウト：\n"
        "- 4:5の縦長\n"
        "- 上部に大きなキャッチーなタイトル\n"
        "- タイトル下に一言でわかるリード文\n"
        "- 中央にメイン図解\n"
        "- 周囲に3〜5個の要点カード\n"
        "- 下部に「つまり何が大事？」というまとめ欄\n"
        "- 視線が上から下へ自然に流れる構成にする\n"
        "\n"
        "情報整理ルール：\n"
        "- 入力情報を、読者が理解しやすい順番に再構成する\n"
        "- 重要度の高い内容ほど大きく扱う\n"
        "- 要点カードには、短い見出し＋一言メモを入れる\n"
        "- 比較、手順、因果関係、構造がある場合は、表や矢印で表す\n"
        "- 専門用語は残しつつ、周囲に簡単な補足を添える\n"
        "- 入力にない事実や数字は追加しない\n"
        "\n"
        "画像内テキスト：\n"
        "- 日本語\n"
        "- 見出しは短く、印象的に\n"
        "- 本文は一言メモ程度に圧縮\n"
        "- 画像内の文字量は少なめ\n"
        "- 誤字を避けるため、長い文章をそのまま入れない\n"
        "\n"
        "###\n"
        "可視化したい情報：\n"
        f"{source_text}\n"
        "###\n"
    )


def summarize_with_codex(
    run_date: str,
    papers: list[Paper],
    client: CodexAppServerClient,
    mock: bool = False,
) -> DigestResult:
    if mock:
        return mock_digest(run_date, papers)
    prompt = build_summary_prompt(run_date, papers)
    result = client.run_turn(prompt)
    parsed = parse_digest_json(result.text)
    digest_papers = [
        DigestPaper(
            pmid=str(item.get("pmid", "")),
            title=str(item.get("title", "")),
            japanese_summary=str(item.get("japanese_summary", "")),
            clinical_takeaway=str(item.get("clinical_takeaway", "")),
            topics=[str(topic) for topic in item.get("topics", [])],
            evidence_type=str(item.get("evidence_type", "")),
        )
        for item in parsed.get("papers", [])
    ]
    return DigestResult(
        run_date=run_date,
        papers=digest_papers,
        digest_summary=str(parsed.get("digest_summary", "")),
        image_prompt=str(parsed.get("image_prompt", "")),
        raw_ai_text=result.text,
    )


def generate_image_with_codex(
    digest: DigestResult,
    client: CodexAppServerClient,
    watcher: ImageWatcher,
    mock: bool = False,
) -> Path | None:
    if mock:
        return None
    before = watcher.snapshot()
    started_at = time.time()
    prompt = build_image_prompt(digest)
    client.run_turn(prompt)
    return watcher.newest_after(before, started_at)


def parse_digest_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped, flags=re.IGNORECASE).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def mock_digest(run_date: str, papers: list[Paper]) -> DigestResult:
    digest_papers = []
    for paper in papers:
        digest_papers.append(
            DigestPaper(
                pmid=paper.pmid,
                title=paper.title,
                japanese_summary=(
                    f"{paper.title} の抄録に基づく要約です。研究の焦点は "
                    f"{', '.join(paper.topics[:3]) or '肩関節'} です。詳細はPubMed原文を確認してください。"
                ),
                clinical_takeaway="肩関節診療の最近の論点として確認する価値があります。",
                topics=paper.topics,
                evidence_type=paper.evidence_type,
            )
        )
    return DigestResult(
        run_date=run_date,
        papers=digest_papers,
        digest_summary="肩関節関連の新着論文から、臨床で確認したい3本を抽出しました。",
        image_prompt="肩関節関連論文3本を、医療者向けの4:5縦長インフォグラフィック風グラレコに整理する。",
        raw_ai_text="mock",
    )

