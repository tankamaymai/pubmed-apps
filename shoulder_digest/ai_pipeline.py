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
        "あなたは肩関節領域に詳しい理学療法士向け編集者です。\n"
        "以下のPubMed論文JSONだけを根拠に、理学療法現場向けの日本語ダイジェストを1本作成してください。\n"
        "優先テーマは、肩関節の解剖・基本構造・運動学・可動域、リハビリプログラム、"
        "徒手・運動療法、機能評価、ADL/スポーツ復帰、保守的治療です。\n"
        "手術成績や人工関節の話題は、リハビリや機能回復の観点がabstractにある場合のみ中心に据えてください。\n"
        "RCT、コホート、SR/MA、ガイドライン、解剖レビュー、バイオメカニクス、可動域研究を扱えます。\n"
        "推測で効果量や結論を補わないでください。abstractにないことは書かないでください。\n"
        "返答はMarkdownなしのJSONのみです。\n"
        "JSON schema:\n"
        "{\n"
        '  "digest_summary": "この1本を2-3文で要約",\n'
        '  "image_prompt": "文字情報を多めに盛り込んだ4:5縦長グラレコ用の詳細日本語プロンプト（見出し・要点カード・数値・臨床メモを具体的に指定）",\n'
        '  "papers": [\n'
        "    {\n"
        '      "pmid": "string",\n'
        '      "title": "string",\n'
        '      "japanese_title": "論文タイトルの自然な日本語訳",\n'
        '      "japanese_summary": "目的・方法・結果・臨床的意味を6-8文",\n'
        '      "clinical_takeaway": "理学療法現場向けの一言",\n'
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
        topics = "、".join(paper.topics[:5]) if paper.topics else ""
        paper_lines.append(
            f"- PMID {paper.pmid}: {paper.title}\n"
            f"  要約: {paper.japanese_summary}\n"
            f"  現場メモ: {paper.clinical_takeaway}\n"
            f"  トピック: {topics}\n"
            f"  エビデンス: {paper.evidence_type}"
        )
    source_text = (
        f"全体要約: {digest.digest_summary}\n\n"
        "論文:\n"
        + "\n".join(paper_lines)
    )
    return (
        "あなたは雑誌の特集ページを作るアートディレクター兼情報デザイナーです。\n"
        "以下の「可視化したい情報」は、肩関節の解剖・機能・リハビリまたは運動学に関する1本です。\n"
        "理学療法現場で読む人向けに、1枚で要点が伝わるグラレコにしてください。\n"
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
        "- タイトル下に2-3行のリード文\n"
        "- 中央にメイン図解\n"
        "- 周囲に5〜7個の要点カード（各カードに見出し＋2行程度の説明）\n"
        "- 「背景・目的」「方法」「結果」「臨床的ポイント」の4セクションを明示\n"
        "- 下部に「つまり何が大事？」というまとめ欄（2-3行）\n"
        "- 視線が上から下へ自然に流れる構成にする\n"
        "\n"
        "情報整理ルール：\n"
        "- 入力情報を、読者が理解しやすい順番に再構成する\n"
        "- 重要度の高い内容ほど大きく扱う\n"
        "- 要点カードには、短い見出し＋2行程度の説明文を入れる\n"
        "- 比較、手順、因果関係、構造がある場合は、表や矢印で表す\n"
        "- 専門用語は残しつつ、周囲に簡単な補足を添える\n"
        "- abstractにある数値・条件・対象患者は可能な限り画像内テキストに反映する\n"
        "- 入力にない事実や数字は追加しない\n"
        "\n"
        "画像内テキスト：\n"
        "- 日本語\n"
        "- 見出しは短く、印象的に\n"
        "- 本文は圧縮しつつも情報量を多めに（ミニ記事1枚分の読み応え）\n"
        "- 各セクション合計で15〜25個程度のテキスト要素（見出し・ラベル・短文・数値）を目安にする\n"
        "- 1枚だけで論文の要点が追える密度にする\n"
        "- 誤字を避けるため、長文段落は避け、箇条書きと短文で整理する\n"
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
            japanese_title=str(item.get("japanese_title", "")),
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
    image_wait_seconds: int = 120,
) -> Path | None:
    if mock:
        return None
    before = watcher.snapshot()
    started_at = time.time()
    prompt = build_image_prompt(digest)
    result = client.run_turn(
        prompt,
        allow_network=True,
        expect_image=True,
    )
    if result.saved_image_path:
        saved = Path(result.saved_image_path)
        if saved.exists():
            return saved
    return watcher.newest_after(before, started_at, wait_seconds=image_wait_seconds)


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
                japanese_title=paper.title,
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
        digest_summary="肩関節関連の新着論文から、医療現場で確認したい1本を抽出しました。",
        image_prompt="肩関節関連論文1本を、文字情報多めの4:5縦長インフォグラフィック風グラレコに整理する。",
        raw_ai_text="mock",
    )

