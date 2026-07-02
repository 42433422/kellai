"""End-to-end closed-loop audit for Kellai core workflows."""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.api import content, finance, flow, open as open_api, sales, scout
from app.channels.base import UnifiedMessage
from app.services import ai_copilot
from app.services.agent_assist import build_agent_assist
from app.services.growth_loop import customer_agent_operating_insight, customer_message_context
from app.services.llm_config import probe_llm_connection, public_config
from app.services.llm_customer_simulator import run_llm_full_flow_simulation
from app.services.message_store import get_messages, save_message
from app.services.outbound_call import execute_outbound_call, outbound_call_summary, plan_outbound_call
from app.services.quality_inspection import inspect_customer_conversation
from app.services.service_learning import run_service_learning
from app.services.service_tickets import (
    assign_service_ticket,
    create_ticket_from_quality,
    resolve_service_ticket,
    service_ticket_summary,
)
from app.services.self_service_resolution import run_self_service_resolution, self_service_summary
from app.services.pipeline import (
    PIPELINE_STAGES,
    _stage_rank,
    add_customer_tag,
    build_pipeline_funnel_summary,
    create_customer,
    delete_pipeline,
    list_pipeline_client_summaries,
    load_pipeline,
    normalize_stage_id,
    remove_customer_tag,
    save_pipeline,
    set_pipeline_stage,
    update_customer_profile,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _data_root() -> Path:
    raw = (os.environ.get("KELLAI_DATA_DIR") or "").strip()
    root = Path(raw).expanduser().resolve() if raw else Path(__file__).resolve().parents[3] / "data"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _latest_audit_path() -> Path:
    return _data_root() / "closed_loop_audit_latest.json"


def _write_latest_audit_report(report: dict[str, Any]) -> None:
    path = _latest_audit_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def latest_closed_loop_audit_report() -> dict[str, Any] | None:
    path = _latest_audit_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _stage_label(stage: str) -> str:
    labels = {item["id"]: item["label"] for item in PIPELINE_STAGES}
    return labels.get(stage, stage)


def _item(
    key: str,
    label: str,
    passed: bool,
    *,
    required: bool = True,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": "passed" if passed else ("failed" if required else "skipped"),
        "passed": bool(passed),
        "required": bool(required),
        "details": details or {},
    }


def _data(resp: dict[str, Any] | None) -> Any:
    if not isinstance(resp, dict):
        return {}
    return resp.get("data", {})


def _save_audit_message(
    *,
    audit_id: str,
    customer_id: int,
    channel_type: str,
    contact_id: str,
    contact_name: str,
    direction: str,
    content: str,
    turn: int,
    content_type: str = "text",
    metadata: dict[str, Any] | None = None,
) -> int:
    msg_metadata = {"source": "closed_loop_audit", "audit_id": audit_id, "turn": turn}
    msg_metadata.update(metadata or {})
    msg = UnifiedMessage(
        id=f"audit:{audit_id}:{turn}:{direction}:{secrets.token_hex(3)}",
        customer_id=customer_id,
        channel_type=channel_type,
        contact_id=contact_id,
        contact_name=contact_name,
        direction=direction,
        content=content,
        content_type=content_type,
        metadata=msg_metadata,
        created_at=_now_iso(),
    )
    saved = save_message(msg)
    return int(saved.customer_id)


def _run_core_customer_loop(audit_id: str) -> dict[str, Any]:
    contact_id = f"audit_{audit_id}"
    contact_name = "闭环验收-抖音客户"
    channel_type = "douyin"
    customer_id = 0
    turns = [
        (
            "inbound",
            "你们这个怎么收费？我有抖音、企微和小程序，想统一接待客户。",
        ),
        (
            "outbound",
            "收到，我先按你的渠道和消息量整理一版方案和报价，首周可完成配置和培训。",
        ),
        (
            "inbound",
            "报价可以，不过首月能不能优惠？合适的话今天就签。",
        ),
        (
            "outbound",
            "可以帮你申请首月优惠。你确认后我发合同和付款信息，付款后安排交付。",
        ),
        (
            "inbound",
            "合同我确认了，已经付款了，发我交付清单吧。",
        ),
    ]
    for idx, (direction, content) in enumerate(turns):
        customer_id = _save_audit_message(
            audit_id=audit_id,
            customer_id=customer_id,
            channel_type=channel_type,
            contact_id=contact_id,
            contact_name=contact_name,
            direction=direction,
            content=content,
            turn=idx,
        )

    ctx = customer_message_context(customer_id)
    messages = get_messages(customer_id, limit=20)
    inbound_count = sum(1 for msg in messages if msg.direction == "inbound")
    outbound_count = sum(1 for msg in messages if msg.direction == "outbound")

    return {
        "customer_id": customer_id,
        "context": ctx,
        "inbound_count": inbound_count,
        "outbound_count": outbound_count,
        "message_count": len(messages),
    }


def _advanced_check_error(key: str, label: str, exc: Exception) -> dict[str, Any]:
    return _item(key, label, False, details={"error": str(exc)[:300]})


def _run_sales_revenue_loop(customer_id: int) -> dict[str, Any]:
    label = "销售推进、报价、合同闭环"
    try:
        flow_doc = _data(sales.get_flow(customer_id))
        progress: list[dict[str, Any]] = []
        for _ in range(len(sales.STEPS) + 1):
            flow_doc = _data(sales.auto_flow(sales.AutoFlowBody(customer_id=customer_id)))
            progress.append(
                {
                    "current_step": flow_doc.get("current_step"),
                    "status": flow_doc.get("status"),
                    "win_probability": flow_doc.get("win_probability"),
                }
            )
            if flow_doc.get("status") == "completed":
                break
        quote_doc = _data(sales.quote(sales.QuoteBody(customer_id=customer_id)))
        contract_doc = _data(
            sales.contract(
                sales.ContractBody(customer_id=customer_id, quote_id=str(quote_doc.get("id") or ""))
            )
        )
        ltv_doc = _data(sales.ltv(customer_id))
        trace_doc = _data(sales.funnel_trace(customer_id))
        passed = (
            flow_doc.get("status") == "completed"
            and float(quote_doc.get("total") or 0) > 0
            and bool(str(contract_doc.get("sign_url") or "").strip())
            and float(ltv_doc.get("predicted_ltv") or 0) > 0
        )
        return _item(
            "sales_revenue_loop",
            label,
            passed,
            details={
                "flow_status": flow_doc.get("status"),
                "current_step": flow_doc.get("current_step"),
                "progress": progress,
                "quote_id": quote_doc.get("id"),
                "quote_total": quote_doc.get("total"),
                "contract_id": contract_doc.get("id"),
                "contract_status": contract_doc.get("status"),
                "predicted_ltv": ltv_doc.get("predicted_ltv"),
                "overall_conversion": trace_doc.get("overall_conversion"),
            },
        )
    except Exception as exc:
        return _advanced_check_error("sales_revenue_loop", label, exc)


def _run_content_growth_loop(audit_id: str) -> dict[str, Any]:
    label = "内容生成、投放、数据闭环"
    try:
        topic = f"客来来 AI 获客闭环 {audit_id}"
        text_doc = _data(content.generate_text(content.TopicBody(topic=topic, prompt="面向中小商家的获客短文")))
        image_doc = _data(content.generate_image(content.TopicBody(topic=topic, prompt="AI 客服工作台海报")))
        video_doc = _data(content.generate_video_script(content.TopicBody(topic=topic, prompt="30 秒成交闭环脚本")))
        publish_doc = _data(
            content.publish(
                content.PublishBody(
                    content_id=str(text_doc.get("id") or ""),
                    platforms=["douyin", "wechat", "wework"],
                )
            )
        )
        analytics_doc = _data(content.analytics())
        ad_doc = _data(content.ad_strategy())
        ab_doc = _data(content.ab_test())
        totals = analytics_doc.get("totals") if isinstance(analytics_doc.get("totals"), dict) else {}
        passed = (
            bool(text_doc.get("id"))
            and bool(image_doc.get("image_url"))
            and bool(str(video_doc.get("body") or "").strip())
            and publish_doc.get("status") == "published"
            and int(totals.get("conversions") or 0) >= 0
            and bool(ad_doc.get("recommended_channels"))
        )
        return _item(
            "content_growth_loop",
            label,
            passed,
            details={
                "content_id": text_doc.get("id"),
                "image_id": image_doc.get("id"),
                "video_script_id": video_doc.get("id"),
                "publish_status": publish_doc.get("status"),
                "platforms": publish_doc.get("platforms"),
                "conversions": totals.get("conversions"),
                "ad_channels": ad_doc.get("recommended_channels"),
                "ab_test_id": ab_doc.get("id"),
            },
        )
    except Exception as exc:
        return _advanced_check_error("content_growth_loop", label, exc)


def _run_scout_lead_loop() -> dict[str, Any]:
    label = "公域线索发现、触达、转化闭环"
    try:
        targets = _data(scout.scan(scout.ScanBody(keyword="AI", platform="douyin")))
        target = targets[0] if isinstance(targets, list) and targets else {}
        intent_doc = _data(scout.intent_score(scout.CommentBody(comment=str(target.get("comment") or ""))))
        dm_doc = _data(
            scout.auto_dm(
                scout.DmBody(
                    target_id=str(target.get("id") or ""),
                    message="看到你在找 AI 自动回复和获客工具，我可以发你一份闭环方案。",
                )
            )
        )
        convert_doc = _data(scout.convert(scout.ConvertBody(target_id=str(target.get("id") or ""))))
        trace_doc = _data(scout.trace(target_id=str(target.get("id") or "")))
        sentiment_doc = _data(scout.sentiment_overview())
        passed = (
            bool(target.get("id"))
            and int(intent_doc.get("score") or 0) >= 70
            and bool(dm_doc.get("success"))
            and bool(convert_doc.get("success"))
            and bool(trace_doc.get("converted"))
        )
        return _item(
            "scout_lead_loop",
            label,
            passed,
            details={
                "target_id": target.get("id"),
                "platform": target.get("platform"),
                "intent_score": intent_doc.get("score"),
                "dm_success": dm_doc.get("success"),
                "convert_success": convert_doc.get("success"),
                "trace_steps": len(trace_doc.get("steps") or []),
                "watch_terms": sentiment_doc.get("watch_terms"),
            },
        )
    except Exception as exc:
        return _advanced_check_error("scout_lead_loop", label, exc)


def _run_flow_automation_loop(audit_id: str) -> dict[str, Any]:
    label = "自动化流程创建、执行、Webhook 闭环"
    try:
        created = _data(
            flow.create_flow(
                flow.FlowCreateBody(
                    name=f"闭环验收自动化-{audit_id}",
                    nodes=[
                        {"id": "trigger", "type": "message.received", "label": "收到消息"},
                        {"id": "score", "type": "ai.score", "label": "AI 评分"},
                        {"id": "notify", "type": "notify.sales", "label": "通知销售"},
                    ],
                    edges=[{"from": "trigger", "to": "score"}, {"from": "score", "to": "notify"}],
                )
            )
        )
        updated = _data(flow.update_flow(flow.FlowUpdateBody(id=str(created.get("id") or ""), name="闭环验收自动化-已启用")))
        listed = _data(flow.list_flows())
        executed = _data(flow.execute(flow.ExecuteBody(flow_id=str(created.get("id") or ""))))
        rate_doc = _data(flow.automation_rate())
        webhook_doc = _data(
            flow.webhook(
                flow.WebhookBody(
                    url=f"https://hooks.kellai.local/flow/{audit_id}",
                    events=["message.received", "deal.closed"],
                )
            )
        )
        passed = (
            bool(created.get("id"))
            and updated is not None
            and isinstance(listed, list)
            and executed.get("status") == "completed"
            and float(rate_doc.get("rate") or 0) > 0
            and bool(webhook_doc.get("enabled"))
        )
        return _item(
            "flow_automation_loop",
            label,
            passed,
            details={
                "flow_id": created.get("id"),
                "flow_count": len(listed) if isinstance(listed, list) else 0,
                "execution_status": executed.get("status"),
                "automation_rate": rate_doc.get("rate"),
                "webhook_id": webhook_doc.get("id"),
            },
        )
    except Exception as exc:
        return _advanced_check_error("flow_automation_loop", label, exc)


def _run_finance_decision_loop() -> dict[str, Any]:
    label = "财务看板、问答、预算、决策闭环"
    try:
        dashboard_doc = _data(finance.dashboard(period="month"))
        ask_doc = _data(finance.ask(finance.AskBody(question="本月利润和下月预算怎么安排？")))
        budget_doc = _data(finance.budget_suggest())
        performance_doc = _data(finance.performance(period="month"))
        alerts_doc = _data(finance.alerts())
        report_doc = _data(finance.report(period="2026-06"))
        decision_doc = _data(finance.decision())
        passed = (
            float(dashboard_doc.get("revenue") or 0) > 0
            and bool(str(ask_doc.get("answer") or "").strip())
            and float(budget_doc.get("total_budget") or 0) > 0
            and isinstance(performance_doc, list)
            and bool(alerts_doc)
            and bool(str(report_doc.get("download_url") or "").strip())
            and bool(decision_doc.get("actions"))
        )
        return _item(
            "finance_decision_loop",
            label,
            passed,
            details={
                "revenue": dashboard_doc.get("revenue"),
                "profit_margin": dashboard_doc.get("profit_margin"),
                "answer": ask_doc.get("answer"),
                "budget": budget_doc.get("total_budget"),
                "member_count": len(performance_doc) if isinstance(performance_doc, list) else 0,
                "alert_count": len(alerts_doc) if isinstance(alerts_doc, list) else 0,
                "report_id": report_doc.get("id"),
                "decision_actions": decision_doc.get("actions"),
            },
        )
    except Exception as exc:
        return _advanced_check_error("finance_decision_loop", label, exc)


def _run_open_platform_loop(audit_id: str) -> dict[str, Any]:
    label = "开放平台密钥、插件、Webhook 闭环"
    try:
        key_doc = _data(
            open_api.create_key(
                open_api.KeyBody(
                    name=f"闭环验收-{audit_id}",
                    scopes=["customers:read", "messages:write", "webhooks:write"],
                )
            )
        )
        plugins = _data(open_api.plugins())
        plugin = next((item for item in plugins if not item.get("installed")), plugins[0] if plugins else {})
        install_doc = _data(open_api.install_plugin({"plugin_id": str(plugin.get("id") or "")}))
        webhook_doc = _data(
            open_api.webhooks(
                open_api.WebhookBody(
                    url=f"https://hooks.kellai.local/open/{audit_id}",
                    events=["customer.created", "message.received", "deal.closed"],
                )
            )
        )
        events_doc = _data(open_api.events())
        docs_doc = _data(open_api.docs())
        review_doc = _data(open_api.review(open_api.ReviewBody(app_name=f"闭环验收应用-{audit_id}")))
        stats_doc = _data(open_api.stats())
        endpoints = docs_doc.get("endpoints") if isinstance(docs_doc.get("endpoints"), list) else []
        passed = (
            str(key_doc.get("api_key") or "").startswith("kl_live_")
            and bool(install_doc.get("installed"))
            and bool(webhook_doc.get("active"))
            and bool(events_doc)
            and bool(endpoints)
            and review_doc.get("status") == "pending"
            and int(stats_doc.get("active_webhooks") or 0) >= 1
        )
        return _item(
            "open_platform_loop",
            label,
            passed,
            details={
                "key_id": key_doc.get("id"),
                "key_prefix": key_doc.get("key_prefix"),
                "installed_plugin": plugin.get("name"),
                "webhook_id": webhook_doc.get("id"),
                "event_count": len(events_doc) if isinstance(events_doc, list) else 0,
                "doc_endpoint_count": len(endpoints),
                "review_status": review_doc.get("status"),
                "active_webhooks": stats_doc.get("active_webhooks"),
            },
        )
    except Exception as exc:
        return _advanced_check_error("open_platform_loop", label, exc)


def _run_customer_management_loop(audit_id: str) -> dict[str, Any]:
    label = "客户管理新增、编辑、批量、删除闭环"
    customer_id = 0
    try:
        unique = f"闭环客户-{audit_id}"
        created = create_customer(
            {
                "name": "闭环验收联系人",
                "company": unique,
                "email": f"{audit_id}@audit.kellai.local",
                "phone": "13800138000",
                "owner": "闭环验收",
                "source": "closed_loop_audit",
                "stage": "connected",
                "tags": ["待验收"],
                "channel_sources": ["wework"],
            },
            username="closed-loop-audit",
        )
        customer_id = int(created.get("customer_id") or 0)
        listed_after_create = list_pipeline_client_summaries()
        found_created = next((row for row in listed_after_create if int(row.get("customer_id") or 0) == customer_id), {})

        updated = update_customer_profile(
            customer_id,
            {
                "name": "闭环验收联系人A",
                "company": f"{unique}-已编辑",
                "email": f"edited-{audit_id}@audit.kellai.local",
                "phone": "13900139000",
                "owner": "销售A",
                "source": "import_csv",
                "stage": "intake",
                "tags": ["待验收", "高价值"],
                "channel_sources": ["wework", "douyin"],
            },
            username="closed-loop-audit",
        )
        tagged = add_customer_tag(customer_id, "批量标签")
        untagged = remove_customer_tag(customer_id, "待验收")
        staged = set_pipeline_stage(customer_id, "quoted", source="manual", note="客户管理批量改阶段")
        final_doc = load_pipeline(customer_id)
        final_doc["note"] = "客户管理闭环验收完成"
        final_doc = save_pipeline(final_doc)
        listed_before_delete = list_pipeline_client_summaries()
        found_final = next((row for row in listed_before_delete if int(row.get("customer_id") or 0) == customer_id), {})
        deleted = delete_pipeline(customer_id)
        listed_after_delete = list_pipeline_client_summaries()
        still_exists = any(int(row.get("customer_id") or 0) == customer_id for row in listed_after_delete)

        final_tags = [str(t) for t in (final_doc.get("tags") or [])]
        timeline = final_doc.get("timeline") if isinstance(final_doc.get("timeline"), list) else []
        passed = (
            customer_id > 0
            and bool(found_created)
            and str(updated.get("company") or "").endswith("已编辑")
            and "批量标签" in [str(t) for t in (tagged.get("tags") or [])]
            and "待验收" not in [str(t) for t in (untagged.get("tags") or [])]
            and normalize_stage_id(str(staged.get("stage") or "")) == "quoted"
            and found_final.get("company") == f"{unique}-已编辑"
            and "wework" in (found_final.get("channel_sources") or [])
            and "douyin" in (found_final.get("channel_sources") or [])
            and deleted
            and not still_exists
        )
        return _item(
            "customer_management_loop",
            label,
            passed,
            details={
                "customer_id": customer_id,
                "created_display": found_created.get("display_name"),
                "updated_company": updated.get("company"),
                "final_stage": staged.get("stage"),
                "final_tags": final_tags,
                "timeline_count": len(timeline),
                "deleted": deleted,
                "still_exists_after_delete": still_exists,
            },
        )
    except Exception as exc:
        return _advanced_check_error("customer_management_loop", label, exc)
    finally:
        if customer_id > 0:
            try:
                delete_pipeline(customer_id)
            except Exception:
                pass


def _run_llm_settings_loop(audit_id: str) -> dict[str, Any]:
    label = "AI 设置保存、读回、探测、恢复闭环"
    try:
        from app.services import llm_config

        had_config_file = llm_config._config_path().is_file()
        snapshot = llm_config._read_disk()
        last_probe = dict(getattr(llm_config, "_LAST_PROBE", {}) or {})
        before_status = llm_config.public_config()
        fake_key = f"audit-key-{audit_id}-not-real"
        try:
            saved = llm_config.save_config(
                {
                    "provider": "custom",
                    "model": "audit-compatible-model",
                    "base_url": "http://127.0.0.1:9/v1",
                    "api_key": fake_key,
                    "auto_reply_enabled": True,
                    "auto_reply_stages": ["connected", "intake", "quoted"],
                    "confirm_scenarios": ["价格优惠", "合同条款"],
                }
            )
            effective = llm_config.effective_config()
            probe = llm_config.probe_llm_connection(update_disk=False, timeout_sec=0.2)
            disk_after_probe = llm_config._read_disk()
        finally:
            if had_config_file:
                llm_config._write_disk(snapshot)
            else:
                try:
                    llm_config._config_path().unlink()
                except FileNotFoundError:
                    pass
            llm_config._LAST_PROBE = last_probe

        restored = llm_config.public_config()
        passed = (
            saved.get("provider") == "custom"
            and saved.get("model") == "audit-compatible-model"
            and saved.get("base_url") == "http://127.0.0.1:9/v1"
            and bool(saved.get("ready"))
            and saved.get("autoReplyEnabled") is True
            and saved.get("autoReplyStages") == ["connected", "intake", "quoted"]
            and saved.get("confirmScenarios") == ["价格优惠", "合同条款"]
            and effective.get("provider") == "custom"
            and effective.get("model") == "audit-compatible-model"
            and effective.get("base_url") == "http://127.0.0.1:9/v1"
            and effective.get("source") == "saved_config"
            and probe.get("success") is False
            and probe.get("provider") == "custom"
            and disk_after_probe.get("last_probe") == snapshot.get("last_probe")
            and restored.get("provider") == before_status.get("provider")
            and restored.get("model") == before_status.get("model")
            and restored.get("ready") == before_status.get("ready")
            and restored.get("connected") == before_status.get("connected")
        )
        return _item(
            "llm_settings_loop",
            label,
            passed,
            details={
                "saved_provider": saved.get("provider"),
                "saved_model": saved.get("model"),
                "auto_reply_enabled": saved.get("autoReplyEnabled"),
                "auto_reply_stages": saved.get("autoReplyStages"),
                "probe_success": probe.get("success"),
                "probe_error": probe.get("error"),
                "restored_provider": restored.get("provider"),
                "restored_ready": restored.get("ready"),
            },
        )
    except Exception as exc:
        return _advanced_check_error("llm_settings_loop", label, exc)


def _run_knowledge_base_loop(audit_id: str, customer_id: int) -> dict[str, Any]:
    label = "知识库沉淀、检索、回复闭环"
    try:
        from app.services import knowledge_base

        had_file = knowledge_base._kb_path().is_file()
        snapshot = knowledge_base._read_disk()
        article_id = f"audit_kb_{audit_id}"
        try:
            article = knowledge_base.upsert_article(
                {
                    "id": article_id,
                    "title": f"闭环验收 {audit_id}：企微接入与首月优惠",
                    "content": f"闭环验收标识 {audit_id}。企业微信接入需要提供客服链接或 open_kfid。首月优惠可在客户确认合同后申请，付款后安排交付清单、渠道配置和一次团队培训。",
                    "tags": ["企业微信", "优惠", "交付", "培训"],
                    "source": "closed_loop_audit",
                }
            )
            listed = knowledge_base.list_articles()
            hits = knowledge_base.search_articles(
                f"{article_id} {audit_id} 企微怎么接入，首月能不能优惠，付款后怎么交付",
                limit=5,
            )
            ctx = customer_message_context(customer_id)
            suggestion = knowledge_base.suggest_answer(
                f"客户问 {article_id} {audit_id} 企微接入、首月优惠和付款后交付安排，怎么回复？",
                customer_context=ctx,
                limit=5,
            )
        finally:
            if had_file:
                knowledge_base._write_disk(snapshot)
            else:
                try:
                    knowledge_base._kb_path().unlink()
                except FileNotFoundError:
                    pass

        source_titles = [str(item.get("title") or "") for item in suggestion.get("sources") or []]
        passed = (
            article.get("id") == article_id
            and any(str(item.get("id") or "") == article_id for item in listed)
            and bool(hits)
            and any(str(item.get("id") or "") == article_id for item in hits)
            and suggestion.get("matched") is True
            and "企微" in str(suggestion.get("answer") or "")
            and "交付" in str(suggestion.get("answer") or "")
            and any(str(item.get("id") or "") == article_id for item in suggestion.get("sources") or [])
        )
        return _item(
            "knowledge_base_loop",
            label,
            passed,
            details={
                "article_id": article.get("id"),
                "hit_count": len(hits),
                "top_hit": hits[0].get("title") if hits else "",
                "matched": suggestion.get("matched"),
                "confidence": suggestion.get("confidence"),
                "source_titles": source_titles,
                "restored": knowledge_base._read_disk() == snapshot if had_file else not knowledge_base._kb_path().exists(),
            },
        )
    except Exception as exc:
        return _advanced_check_error("knowledge_base_loop", label, exc)


async def _run_channel_onboarding_loop(audit_id: str) -> dict[str, Any]:
    label = "渠道接入配置、测试、断开闭环"
    try:
        from app.channels import ChannelRegistry, config_store

        snapshot = config_store._read_disk()
        channel_type = "wework"
        kfid = f"kf{audit_id[:10]}"
        kf_url = f"https://work.weixin.qq.com/kfid/{kfid}"
        try:
            saved = config_store.save(
                channel_type,
                {"kf_url": kf_url, "open_kfid": kfid},
                name="闭环验收企业微信",
                enabled=True,
            )
            readback = config_store.get_all(channel_type)
            adapter = ChannelRegistry().get(channel_type)
            test_doc = await adapter.test_connection()
            disconnected = config_store.delete(channel_type)
            after_delete = config_store.get(channel_type)
        finally:
            config_store._write_disk(snapshot)

        readback_config = readback.get("config") if isinstance(readback.get("config"), dict) else {}
        passed = (
            bool(saved.get("enabled"))
            and readback_config.get("kf_url") == kf_url
            and readback_config.get("open_kfid") == kfid
            and bool(test_doc.get("connected"))
            and disconnected
            and after_delete == {}
        )
        return _item(
            "channel_onboarding_loop",
            label,
            passed,
            details={
                "channel_type": channel_type,
                "saved_enabled": saved.get("enabled"),
                "readback_name": readback.get("name"),
                "connected": test_doc.get("connected"),
                "message": test_doc.get("message"),
                "deleted": disconnected,
                "restored": config_store.get(channel_type) == snapshot.get(channel_type, {}),
            },
        )
    except Exception as exc:
        return _advanced_check_error("channel_onboarding_loop", label, exc)


def _run_advanced_capability_checks(customer_id: int, audit_id: str) -> list[dict[str, Any]]:
    return [
        _run_sales_revenue_loop(customer_id),
        _run_customer_management_loop(audit_id),
        _run_llm_settings_loop(audit_id),
        _run_knowledge_base_loop(audit_id, customer_id),
        _run_content_growth_loop(audit_id),
        _run_scout_lead_loop(),
        _run_flow_automation_loop(audit_id),
        _run_finance_decision_loop(),
        _run_open_platform_loop(audit_id),
    ]


def _run_memory_continuity_check(customer_id: int, audit_id: str, initial_stage: str) -> dict[str, Any]:
    label = "跨渠道客户记忆连续闭环"
    try:
        _save_audit_message(
            audit_id=audit_id,
            customer_id=customer_id,
            channel_type="wework",
            contact_id=f"wework_{audit_id}",
            contact_name="闭环验收-企微客户",
            direction="inbound",
            content="我刚才在抖音说过要把抖音、企微和小程序统一接待，合同确认后请继续安排交付。",
            turn=90,
        )
        ctx = customer_message_context(customer_id)
        doc = load_pipeline(customer_id)
        messages = get_messages(customer_id, limit=20)
        channels = {str(x) for x in (doc.get("channel_sources") or []) if str(x).strip()}
        message_text = "\n".join(str(msg.content or "") for msg in messages)
        final_stage = normalize_stage_id(str(ctx.get("stage") or "idle"))
        passed = (
            {"douyin", "wework"}.issubset(channels)
            and "统一接待" in message_text
            and "刚才在抖音" in message_text
            and _stage_rank(final_stage) >= _stage_rank(initial_stage)
            and bool(str(ctx.get("next_action") or "").strip())
        )
        return _item(
            "memory_continuity_loop",
            label,
            passed,
            details={
                "customer_id": customer_id,
                "channels": sorted(channels),
                "initial_stage": initial_stage,
                "final_stage": final_stage,
                "pending_follow_up": bool(ctx.get("pending_follow_up")),
                "next_action": ctx.get("next_action"),
                "message_count": len(messages),
                "channel_contacts": doc.get("channel_contacts") or {},
            },
        )
    except Exception as exc:
        return _advanced_check_error("memory_continuity_loop", label, exc)


def _run_agent_service_ops_loop(customer_id: int) -> dict[str, Any]:
    label = "Agent 客服运营洞察闭环"
    try:
        insight = customer_agent_operating_insight(customer_id)
        channels = {str(x) for x in (insight.get("channel_sources") or []) if str(x).strip()}
        risks = insight.get("risk_signals") if isinstance(insight.get("risk_signals"), list) else []
        management = insight.get("management_insights") if isinstance(insight.get("management_insights"), list) else []
        risk_keys = {str(item.get("key") or "") for item in risks if isinstance(item, dict)}
        management_keys = {str(item.get("key") or "") for item in management if isinstance(item, dict)}
        passed = (
            {"douyin", "wework"}.issubset(channels)
            and bool(str(insight.get("memory_summary") or "").strip())
            and "price_objection" in risk_keys
            and bool(str(insight.get("active_task") or "").strip())
            and {"omnichannel_one_id", "pricing_signal", "active_customer"}.issubset(management_keys)
            and int(insight.get("message_count") or 0) >= 6
        )
        return _item(
            "agent_service_ops_loop",
            label,
            passed,
            details={
                "channels": sorted(channels),
                "risk_keys": sorted(risk_keys),
                "management_keys": sorted(management_keys),
                "active_task": insight.get("active_task"),
                "memory_summary": insight.get("memory_summary"),
                "message_count": insight.get("message_count"),
            },
        )
    except Exception as exc:
        return _advanced_check_error("agent_service_ops_loop", label, exc)


def _run_quality_inspection_loop(customer_id: int, audit_id: str) -> dict[str, Any]:
    label = "客服质检、合规、主管复盘闭环"
    try:
        _save_audit_message(
            audit_id=audit_id,
            customer_id=customer_id,
            channel_type="wework",
            contact_id=f"wework_{audit_id}",
            contact_name="闭环验收-企微客户",
            direction="outbound",
            content="绝对保证百分百当天上线，不满意也别退款，我这边先这么承诺。",
            turn=100,
        )
        _save_audit_message(
            audit_id=audit_id,
            customer_id=customer_id,
            channel_type="wework",
            contact_id=f"wework_{audit_id}",
            contact_name="闭环验收-企微客户",
            direction="inbound",
            content="你这样乱承诺我不放心，再处理不好我就投诉差评退款，要求主管联系。",
            turn=101,
        )
        report = inspect_customer_conversation(customer_id)
        rules = report.get("failed_rules") if isinstance(report.get("failed_rules"), list) else []
        rule_keys = {str(item.get("key") or "") for item in rules if isinstance(item, dict)}
        manager_report = report.get("manager_report") if isinstance(report.get("manager_report"), dict) else {}
        score = int(report.get("score") if report.get("score") is not None else 100)
        passed = (
            bool(report.get("review_required"))
            and score < 80
            and {"compliance_promise", "negative_sentiment", "refund_risk"}.issubset(rule_keys)
            and bool(report.get("recommendations"))
            and bool(str(manager_report.get("summary") or "").strip())
            and bool(str(manager_report.get("suggested_action") or "").strip())
        )
        return _item(
            "quality_inspection_loop",
            label,
            passed,
            details={
                "score": report.get("score"),
                "grade": report.get("grade"),
                "review_required": report.get("review_required"),
                "risk_level": report.get("risk_level"),
                "rule_keys": sorted(rule_keys),
                "recommendations": report.get("recommendations"),
                "manager_summary": manager_report.get("summary"),
            },
        )
    except Exception as exc:
        return _advanced_check_error("quality_inspection_loop", label, exc)


def _run_human_handoff_ticket_loop(customer_id: int) -> dict[str, Any]:
    label = "人机协同转人工、工单、回托 AI 闭环"
    try:
        ticket = create_ticket_from_quality(customer_id, assignee="质检主管", sla_minutes=30)
        assigned = assign_service_ticket(str(ticket.get("id") or ""), "质检主管", actor="closed-loop-audit")
        resolved = resolve_service_ticket(
            str(assigned.get("id") or ""),
            "已确认过度承诺风险，删除绝对化话术，给客户补发合规说明并继续跟进。",
            actor="closed-loop-audit",
            rehost_to_ai=True,
        )
        summary = service_ticket_summary(customer_id)
        events = resolved.get("events") if isinstance(resolved.get("events"), list) else []
        event_actions = {str(item.get("action") or "") for item in events if isinstance(item, dict)}
        passed = (
            str(ticket.get("status") or "") == "open"
            and str(assigned.get("status") or "") == "assigned"
            and str(resolved.get("status") or "") == "resolved"
            and bool(str(resolved.get("ai_rehost_action") or "").strip())
            and {"created", "assigned", "resolved", "rehosted_to_ai"}.issubset(event_actions)
            and int(summary.get("resolved") or 0) >= 1
            and str((summary.get("latest") or {}).get("id") or "") == str(resolved.get("id") or "")
        )
        return _item(
            "human_handoff_ticket_loop",
            label,
            passed,
            details={
                "ticket_id": resolved.get("id"),
                "status": resolved.get("status"),
                "assignee": resolved.get("assignee"),
                "risk_level": resolved.get("risk_level"),
                "event_actions": sorted(event_actions),
                "ai_rehost_action": resolved.get("ai_rehost_action"),
                "summary": {
                    "total": summary.get("total"),
                    "open": summary.get("open"),
                    "resolved": summary.get("resolved"),
                },
            },
        )
    except Exception as exc:
        return _advanced_check_error("human_handoff_ticket_loop", label, exc)


def _run_service_learning_loop(customer_id: int) -> dict[str, Any]:
    label = "服务自学习、指标、知识沉淀闭环"
    try:
        learning = run_service_learning(customer_id, persist=True)
        metrics = learning.get("metrics") if isinstance(learning.get("metrics"), dict) else {}
        article = learning.get("article") if isinstance(learning.get("article"), dict) else {}
        hit_ids = {str(item.get("id") or "") for item in learning.get("search_hits") or [] if isinstance(item, dict)}
        passed = (
            bool(learning.get("passed"))
            and int(metrics.get("inspected_conversations") or 0) > 0
            and int(metrics.get("ticket_resolved") or 0) >= 1
            and int(metrics.get("ai_rehosted") or 0) >= 1
            and bool(article.get("id"))
            and str(article.get("id") or "") in hit_ids
            and bool(learning.get("recommendations"))
        )
        return _item(
            "service_learning_loop",
            label,
            passed,
            details={
                "article_id": article.get("id"),
                "article_title": article.get("title"),
                "metrics": metrics,
                "recommendations": learning.get("recommendations"),
                "search_hit_ids": sorted(hit_ids),
            },
        )
    except Exception as exc:
        return _advanced_check_error("service_learning_loop", label, exc)


def _run_outbound_call_loop(customer_id: int) -> dict[str, Any]:
    label = "AI 外呼、电话跟进、漏斗推进闭环"
    try:
        before_ctx = customer_message_context(customer_id)
        before_stage = normalize_stage_id(str(before_ctx.get("stage") or "idle"))
        call = plan_outbound_call(
            customer_id,
            purpose="quote_follow_up",
            assignee="AI外呼助手",
            actor="closed-loop-audit",
        )
        executed = execute_outbound_call(
            str(call.get("id") or ""),
            outcome="demo_booked",
            note="闭环验收模拟电话跟进",
            actor="closed-loop-audit",
        )
        summary = outbound_call_summary(customer_id)
        after_ctx = customer_message_context(customer_id)
        after_stage = normalize_stage_id(str(after_ctx.get("stage") or "idle"))
        phone_messages = get_messages(customer_id, channel_type="phone", limit=10)
        source_hits = [
            msg
            for msg in phone_messages
            if str((getattr(msg, "metadata", {}) or {}).get("source") or "") == "outbound_call"
        ]
        passed = (
            str(executed.get("status") or "") == "completed"
            and bool(executed.get("transcript"))
            and len(executed.get("message_ids") or []) >= 2
            and int(summary.get("completed") or 0) >= 1
            and len(source_hits) >= 2
            and "phone" in (after_ctx.get("channel_sources") or [])
            and _stage_rank(after_stage) >= _stage_rank(before_stage)
            and bool(str(after_ctx.get("next_action") or executed.get("next_action") or "").strip())
        )
        return _item(
            "outbound_call_loop",
            label,
            passed,
            details={
                "call_id": executed.get("id"),
                "status": executed.get("status"),
                "outcome": executed.get("outcome"),
                "outcome_label": executed.get("outcome_label"),
                "before_stage": before_stage,
                "after_stage": after_stage,
                "phone_message_count": summary.get("phone_message_count"),
                "message_ids": executed.get("message_ids"),
                "next_action": executed.get("next_action"),
            },
        )
    except Exception as exc:
        return _advanced_check_error("outbound_call_loop", label, exc)


def _run_self_service_resolution_loop(customer_id: int, audit_id: str) -> dict[str, Any]:
    label = "AI 自助解决、知识库回复、未命中转人工闭环"
    try:
        from app.services import knowledge_base

        article_id = f"self_service_audit_{audit_id}"
        article = knowledge_base.upsert_article(
            {
                "id": article_id,
                "title": f"自助解决 {audit_id}：企微接入、优惠与交付",
                "content": (
                    f"闭环验收标识 {audit_id}。客户咨询企微接入、首月优惠或付款后交付时，"
                    "回复需包含：企微客服链接或 open_kfid、合同确认后申请首月优惠、付款后发送交付清单并安排培训。"
                ),
                "tags": ["AI自助", "企微", "优惠", "交付", "知识库"],
                "source": "closed_loop_audit",
            }
        )
        resolved = run_self_service_resolution(
            customer_id,
            query=f"{audit_id} 企微怎么接入，首月优惠和付款后交付怎么安排？",
            channel_type="wework",
            actor="closed-loop-audit",
            persist=True,
        )
        handoff = run_self_service_resolution(
            customer_id,
            query="火星门店硬件维修 SLA 与离线探针校准流程是什么？",
            channel_type="wework",
            actor="closed-loop-audit",
            persist=True,
        )
        summary = self_service_summary(customer_id)
        messages = get_messages(customer_id, limit=30)
        source_messages = [
            msg
            for msg in messages
            if str((getattr(msg, "metadata", {}) or {}).get("source") or "") == "self_service_resolution"
        ]
        resolved_source_ids = {str(item.get("id") or "") for item in resolved.get("sources") or [] if isinstance(item, dict)}
        passed = (
            article.get("id") == article_id
            and str(resolved.get("status") or "") == "resolved"
            and resolved.get("matched") is True
            and article_id in resolved_source_ids
            and len(resolved.get("message_ids") or []) >= 2
            and str(handoff.get("status") or "") == "handoff_required"
            and bool(str(handoff.get("ticket_id") or "").strip())
            and int(summary.get("resolved") or 0) >= 1
            and int(summary.get("handoff") or 0) >= 1
            and len(source_messages) >= 3
        )
        return _item(
            "self_service_resolution_loop",
            label,
            passed,
            details={
                "article_id": article.get("id"),
                "resolved_status": resolved.get("status"),
                "resolved_sources": sorted(resolved_source_ids),
                "resolved_confidence": resolved.get("confidence"),
                "handoff_status": handoff.get("status"),
                "handoff_ticket_id": handoff.get("ticket_id"),
                "summary": {
                    "total": summary.get("total"),
                    "resolved": summary.get("resolved"),
                    "handoff": summary.get("handoff"),
                    "resolution_rate": summary.get("resolution_rate"),
                },
                "message_count": len(source_messages),
            },
        )
    except Exception as exc:
        return _advanced_check_error("self_service_resolution_loop", label, exc)


def _run_agent_assist_autofill_loop(customer_id: int) -> dict[str, Any]:
    label = "坐席助手、知识推荐、风险提醒、自动填单闭环"
    try:
        before = load_pipeline(customer_id)
        before_stage = normalize_stage_id(str(before.get("stage") or "idle"))
        draft = build_agent_assist(customer_id, persist=False, actor="closed-loop-audit")
        applied = build_agent_assist(customer_id, persist=True, actor="closed-loop-audit")
        after = load_pipeline(customer_id)
        intake_form = after.get("intake_form") if isinstance(after.get("intake_form"), dict) else {}
        after_stage = normalize_stage_id(str(after.get("stage") or "idle"))
        agent_state = after.get("agent_assist") if isinstance(after.get("agent_assist"), dict) else {}
        passed = (
            bool(draft.get("passed"))
            and str(applied.get("status") or "") == "applied"
            and bool(applied.get("persisted"))
            and bool(str((applied.get("draft") or {}).get("requirement_desc") or "").strip())
            and bool(str(intake_form.get("requirement_desc") or "").strip())
            and _stage_rank(after_stage) >= _stage_rank(before_stage)
            and isinstance(applied.get("knowledge_recommendations"), list)
            and bool(applied.get("next_actions"))
            and str(agent_state.get("status") or "") == "applied"
        )
        return _item(
            "agent_assist_autofill_loop",
            label,
            passed,
            details={
                "status": applied.get("status"),
                "before_stage": before_stage,
                "after_stage": after_stage,
                "missing_fields": applied.get("missing_fields"),
                "knowledge_count": len(applied.get("knowledge_recommendations") or []),
                "risk_count": len(applied.get("risk_alerts") or []),
                "requirement_desc": str(intake_form.get("requirement_desc") or "")[:120],
                "applied_at": agent_state.get("applied_at"),
            },
        )
    except Exception as exc:
        return _advanced_check_error("agent_assist_autofill_loop", label, exc)


def _run_multimodal_service_loop(customer_id: int, audit_id: str) -> dict[str, Any]:
    label = "多模态消息入库、识别摘要、服务上下文闭环"
    try:
        _save_audit_message(
            audit_id=audit_id,
            customer_id=customer_id,
            channel_type="miniapp",
            contact_id=f"miniapp_{audit_id}",
            contact_name="闭环验收-小程序客户",
            direction="inbound",
            content="客户上传门店收银台照片：希望把小程序、企微和抖音消息统一接待，并展示收银台部署位置。",
            turn=130,
            content_type="image",
            metadata={
                "media_url": f"https://assets.kellai.local/audit/{audit_id}/store-counter.png",
                "vision_summary": "门店收银台、二维码台卡、客服接待入口",
                "detected_objects": ["收银台", "二维码台卡", "手机"],
                "customer_need": "多渠道统一客服接待",
            },
        )
        _save_audit_message(
            audit_id=audit_id,
            customer_id=customer_id,
            channel_type="phone",
            contact_id=f"phone_{audit_id}",
            contact_name="闭环验收-电话客户",
            direction="inbound",
            content="语音转写：我想确认付款后的交付清单、培训时间和渠道上线顺序。",
            turn=131,
            content_type="audio",
            metadata={
                "audio_url": f"https://assets.kellai.local/audit/{audit_id}/call.wav",
                "transcript": "我想确认付款后的交付清单、培训时间和渠道上线顺序。",
                "emotion": "neutral",
                "intent": "交付确认",
            },
        )
        ctx = customer_message_context(customer_id)
        messages = get_messages(customer_id, limit=40)
        content_types = {str(msg.content_type or "") for msg in messages}
        channels = {str(msg.channel_type or "") for msg in messages}
        image_msg = next((msg for msg in messages if str(msg.content_type or "") == "image"), None)
        audio_msg = next((msg for msg in messages if str(msg.content_type or "") == "audio"), None)
        ctx_text = " ".join(str(value or "") for value in [ctx.get("last_message_preview"), ctx.get("next_action"), ctx.get("ai_intent")])
        image_metadata = (getattr(image_msg, "metadata", {}) or {}) if image_msg else {}
        audio_metadata = (getattr(audio_msg, "metadata", {}) or {}) if audio_msg else {}
        passed = (
            {"image", "audio"}.issubset(content_types)
            and {"miniapp", "phone"}.issubset(channels)
            and bool(image_metadata.get("vision_summary"))
            and bool(audio_metadata.get("transcript"))
            and ("交付" in ctx_text or "培训" in ctx_text or "渠道" in ctx_text)
            and "miniapp" in (ctx.get("channel_sources") or [])
            and "phone" in (ctx.get("channel_sources") or [])
        )
        return _item(
            "multimodal_service_loop",
            label,
            passed,
            details={
                "customer_id": customer_id,
                "content_types": sorted(content_types),
                "channels": sorted(channels),
                "vision_summary": image_metadata.get("vision_summary") or "",
                "audio_transcript": audio_metadata.get("transcript") or "",
                "stage": ctx.get("stage"),
                "next_action": ctx.get("next_action"),
                "channel_sources": ctx.get("channel_sources") or [],
            },
        )
    except Exception as exc:
        return _advanced_check_error("multimodal_service_loop", label, exc)


def _build_competitor_benchmark_profile(checks: list[dict[str, Any]], *, require_llm: bool) -> dict[str, Any]:
    checks_by_key = {str(item.get("key") or ""): item for item in checks}

    def passed(*keys: str) -> bool:
        return all(bool((checks_by_key.get(key) or {}).get("passed")) for key in keys)

    dimensions = [
        {
            "key": "omnichannel_service",
            "label": "全渠道统一接待",
            "required": True,
            "passed": passed("channel_onboarding_loop", "memory_continuity_loop"),
            "evidence_keys": ["channel_onboarding_loop", "memory_continuity_loop"],
        },
        {
            "key": "unified_memory",
            "label": "跨渠道长期记忆",
            "required": True,
            "passed": passed("memory_continuity_loop", "agent_service_ops_loop"),
            "evidence_keys": ["memory_continuity_loop", "agent_service_ops_loop"],
        },
        {
            "key": "semantic_emotion_understanding",
            "label": "复杂意图、情绪、风险识别",
            "required": True,
            "passed": passed("ai_intent", "ai_profile", "quality_inspection_loop"),
            "evidence_keys": ["ai_intent", "ai_profile", "quality_inspection_loop"],
        },
        {
            "key": "autonomous_execution",
            "label": "主动执行、工单、回访闭环",
            "required": True,
            "passed": passed("flow_automation_loop", "human_handoff_ticket_loop", "self_service_resolution_loop", "outbound_call_loop"),
            "evidence_keys": ["flow_automation_loop", "human_handoff_ticket_loop", "self_service_resolution_loop", "outbound_call_loop"],
        },
        {
            "key": "knowledge_learning",
            "label": "知识库沉淀与服务自学习",
            "required": True,
            "passed": passed("knowledge_base_loop", "service_learning_loop"),
            "evidence_keys": ["knowledge_base_loop", "service_learning_loop"],
        },
        {
            "key": "growth_revenue_ops",
            "label": "获客、销售、经营增长闭环",
            "required": True,
            "passed": passed("scout_lead_loop", "sales_revenue_loop", "content_growth_loop", "finance_decision_loop"),
            "evidence_keys": ["scout_lead_loop", "sales_revenue_loop", "content_growth_loop", "finance_decision_loop"],
        },
        {
            "key": "open_business_integration",
            "label": "CRM、开放平台、Webhook 集成",
            "required": True,
            "passed": passed("customer_management_loop", "open_platform_loop"),
            "evidence_keys": ["customer_management_loop", "open_platform_loop"],
        },
        {
            "key": "multimodal_service",
            "label": "文本、图片、语音多模态服务链路",
            "required": True,
            "passed": passed("multimodal_service_loop", "outbound_call_loop", "content_growth_loop"),
            "evidence_keys": ["multimodal_service_loop", "outbound_call_loop", "content_growth_loop"],
        },
        {
            "key": "real_llm_agent",
            "label": "真实大模型 Agent 成交链路",
            "required": bool(require_llm),
            "passed": passed("llm_ready", "llm_full_flow"),
            "evidence_keys": ["llm_ready", "llm_full_flow"],
        },
    ]
    required = [item for item in dimensions if item.get("required")]
    failed_required = [item for item in required if not item.get("passed")]
    return {
        "name": "红熊/黑熊 AI Agent 客服对标",
        "summary": {
            "total": len(dimensions),
            "passed": sum(1 for item in dimensions if item.get("passed")),
            "failed_required": len(failed_required),
            "skipped_optional": sum(1 for item in dimensions if not item.get("required") and not item.get("passed")),
        },
        "dimensions": dimensions,
        "failed_required_labels": [str(item.get("label") or "") for item in failed_required],
    }


async def run_closed_loop_audit(
    *,
    require_llm: bool = True,
    target_stage: str = "signed",
) -> dict[str, Any]:
    """Run product-level closure checks and return a structured audit report."""
    audit_id = secrets.token_hex(6)
    target = normalize_stage_id(target_stage)
    if target not in {item["id"] for item in PIPELINE_STAGES}:
        target = "signed"

    checks: list[dict[str, Any]] = []
    llm = public_config()
    probe = probe_llm_connection(update_disk=True, timeout_sec=10.0) if require_llm else {}
    if probe:
        llm = public_config()
    llm_ready = bool(probe.get("success")) if require_llm else bool(llm.get("ready"))
    checks.append(
        _item(
            "llm_ready",
            "真实 LLM 已连通",
            llm_ready,
            required=require_llm,
            details={
                "provider": llm.get("provider") or "",
                "model": llm.get("model") or "",
                "message": llm.get("message") or "",
                "probe_success": bool(probe.get("success")) if probe else None,
                "probe_error": str(probe.get("error") or "") if probe else "",
                "latency_ms": int(probe.get("latency_ms") or 0) if probe else 0,
            },
        )
    )

    core = _run_core_customer_loop(audit_id)
    customer_id = int(core["customer_id"])
    ctx = core["context"]
    final_stage = normalize_stage_id(str(ctx.get("stage") or "idle"))
    checks.extend(
        [
            _item(
                "customer_created",
                "客户已从消息自动建档",
                customer_id > 0,
                details={"customer_id": customer_id, "customer_name": ctx.get("customer_name")},
            ),
            _item(
                "messages_persisted",
                "入站/出站消息已入库",
                core["inbound_count"] >= 3 and core["outbound_count"] >= 2,
                details={
                    "inbound": core["inbound_count"],
                    "outbound": core["outbound_count"],
                    "total": core["message_count"],
                },
            ),
            _item(
                "pipeline_auto_progressed",
                "消息驱动漏斗自动推进",
                _stage_rank(final_stage) >= _stage_rank(target),
                details={"final_stage": final_stage, "final_stage_label": _stage_label(final_stage)},
            ),
            _item(
                "ai_score_and_action",
                "AI 意向分与下一步动作已生成",
                float(ctx.get("ai_score") or 0.0) > 0 and bool(str(ctx.get("next_action") or "").strip()),
                details={"ai_score": ctx.get("ai_score"), "next_action": ctx.get("next_action")},
            ),
        ]
    )
    checks.append(_run_memory_continuity_check(customer_id, audit_id, final_stage))
    checks.append(_run_agent_service_ops_loop(customer_id))
    checks.append(_run_quality_inspection_loop(customer_id, audit_id))
    checks.append(_run_human_handoff_ticket_loop(customer_id))
    checks.append(_run_service_learning_loop(customer_id))
    checks.append(_run_outbound_call_loop(customer_id))
    checks.append(_run_self_service_resolution_loop(customer_id, audit_id))
    checks.append(_run_agent_assist_autofill_loop(customer_id))
    checks.append(_run_multimodal_service_loop(customer_id, audit_id))

    intent = ai_copilot.analyze_intent("报价有点贵，首月能不能优惠？")
    replies = ai_copilot.suggest_reply(
        customer_id,
        message="报价有点贵，首月能不能优惠？",
        intent=str(intent.get("intent") or ""),
        stage=final_stage,
    )
    profile = ai_copilot.generate_customer_profile(customer_id)
    reminders = ai_copilot.get_follow_up_reminders(customer_ids=[customer_id], hours_threshold=0)
    checks.extend(
        [
            _item(
                "ai_intent",
                "AI 意图识别可用",
                str(intent.get("intent") or "") in ai_copilot.INTENT_TYPES,
                details=intent,
            ),
            _item(
                "ai_replies",
                "AI 推荐话术可用",
                bool(replies and str(replies[0].get("text") or "").strip()),
                details={"count": len(replies), "first": replies[0] if replies else {}},
            ),
            _item(
                "ai_profile",
                "客户画像可生成",
                bool(str(profile.get("summary") or "").strip()),
                details=profile,
            ),
            _item(
                "follow_up_reminder",
                "跟进提醒可生成",
                bool(reminders),
                details={"count": len(reminders), "first": reminders[0] if reminders else {}},
            ),
        ]
    )

    stage_doc = set_pipeline_stage(
        customer_id,
        "delivering",
        source="closed_loop_audit",
        note="验收：签约后进入交付",
    )
    checks.append(
        _item(
            "manual_stage_update",
            "手动阶段变更可保存",
            normalize_stage_id(str(stage_doc.get("stage") or "")) == "delivering",
            details={"stage": stage_doc.get("stage")},
        )
    )

    funnel = build_pipeline_funnel_summary(max_clients_per_stage=5)
    clients = list_pipeline_client_summaries()
    checks.extend(
        [
            _item(
                "funnel_summary",
                "漏斗汇总可读取",
                int(funnel.get("total_clients") or 0) > 0,
                details={"total_clients": funnel.get("total_clients"), "counts": funnel.get("counts")},
            ),
            _item(
                "customer_list",
                "客户列表可读取",
                any(int(row.get("customer_id") or 0) == customer_id for row in clients),
                details={"customer_id": customer_id, "total_clients": len(clients)},
            ),
        ]
    )
    checks.extend(_run_advanced_capability_checks(customer_id, audit_id))
    checks.append(await _run_channel_onboarding_loop(audit_id))

    llm_report = await run_llm_full_flow_simulation(
        turns=5,
        target_stage=target,
        channel_type="douyin",
        use_llm=True,
        auto_reply=True,
        require_llm=require_llm,
    )
    checks.append(
        _item(
            "llm_full_flow",
            "LLM 客户行为到签约闭环",
            bool(llm_report.get("passed")),
            required=require_llm,
            details={
                "mode": llm_report.get("mode"),
                "llm_ready": llm_report.get("llm_ready"),
                "llm_customer_turns": llm_report.get("llm_customer_turns"),
                "llm_agent_turns": llm_report.get("llm_agent_turns"),
                "customer_id": llm_report.get("customer_id"),
                "final_stage": llm_report.get("final_stage"),
                "failure_reason": llm_report.get("failure_reason") or "",
            },
        )
    )

    benchmark_profile = _build_competitor_benchmark_profile(checks, require_llm=require_llm)
    checks.append(
        _item(
            "redbear_benchmark_coverage",
            "红熊/黑熊 AI 对标能力覆盖",
            int((benchmark_profile.get("summary") or {}).get("failed_required") or 0) == 0,
            required=True,
            details={
                "benchmark": benchmark_profile.get("name"),
                "summary": benchmark_profile.get("summary"),
                "failed_dimensions": benchmark_profile.get("failed_required_labels"),
            },
        )
    )

    required = [item for item in checks if item.get("required")]
    passed = all(bool(item.get("passed")) for item in required)
    failed_required = [item for item in required if not item.get("passed")]

    report = {
        "audit_id": audit_id,
        "passed": passed,
        "require_llm": bool(require_llm),
        "target_stage": target,
        "target_stage_label": _stage_label(target),
        "checked_at": _now_iso(),
        "summary": {
            "total": len(checks),
            "passed": sum(1 for item in checks if item.get("passed")),
            "failed_required": len(failed_required),
            "skipped_optional": sum(1 for item in checks if not item.get("required") and not item.get("passed")),
        },
        "llm_status": llm,
        "audit_customer_id": customer_id,
        "checks": checks,
        "llm_full_flow_report": llm_report,
        "benchmark_profile": benchmark_profile,
        "failure_reason": "；".join(str(item.get("label")) for item in failed_required),
    }
    _write_latest_audit_report(report)
    return report
