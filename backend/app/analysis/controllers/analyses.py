from __future__ import annotations

import json
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.analysis.schemas.analysis import AnalysisCreateIn, AnalysisRunDetailOut, AnalysisRunOut
from app.analysis.services import analysis_service
from app.common.services.ai_gateway import service as ai_gateway_service
from app.common.services.ai_gateway.base import (
    EVENT_CITATION,
    EVENT_DELTA,
    EVENT_ERROR,
    EVENT_USAGE,
    AIRequest,
)
from app.common.services.ai_config import get_ai_credentials
from app.common.services.skill_runtime import runtime_service
from app.common.services.skill_runtime.context_resolver import ContextTooLargeError
from app.common.services.skill_runtime.loader import SkillRuntimeError
from app.core.database import SessionLocal, get_db
from app.core.deps import get_current_user
from app.skills.services import registry_service

router = APIRouter(prefix="/api/analyses", tags=["analyses"])


@router.post("")
def create_analysis(
    body: AnalysisCreateIn, db: Session = Depends(get_db), user=Depends(get_current_user)
):
    skill = registry_service.get_skill(db, body.skill_key)
    if not skill:
        raise HTTPException(404, "Skill 不存在")
    if not skill.enabled:
        raise HTTPException(400, "Skill 已禁用")

    template_row = None
    if body.template_key:
        template_row = registry_service.get_template_row(db, skill, body.template_key)
        if not template_row:
            raise HTTPException(404, "模板不存在或未启用")
        schema = json.loads(template_row.input_schema_json) if template_row.input_schema_json else None
        if schema:
            missing = [f for f in schema.get("required", []) if f not in body.inputs]
            if missing:
                raise HTTPException(400, f"缺少必填字段：{'、'.join(missing)}")

    try:
        prepared = runtime_service.prepare_run(
            db,
            body.skill_key,
            body.template_key,
            body.inputs,
            body.question,
            body.options.enable_search,
        )
    except (SkillRuntimeError, ContextTooLargeError) as e:
        raise HTTPException(400, str(e))

    provider, api_key, default_model, default_thinking = get_ai_credentials(db)
    if not api_key:
        raise HTTPException(400, "尚未配置 AI 模型 API Key，请先在系统设置 → API 配置里配置")

    model = body.model or default_model
    thinking_enabled = (
        body.options.thinking_enabled if body.options.thinking_enabled is not None else default_thinking
    )
    request_id = uuid4().hex

    run = analysis_service.create_run(
        db,
        request_id=request_id,
        user_id=user.id,
        skill_id=prepared.skill.skill_id,
        skill_version_id=prepared.skill.skill_version_id,
        template_id=template_row.id if template_row else None,
        model=model,
        inputs=body.inputs,
        system_snapshot=prepared.system_instruction,
    )

    ai_request = AIRequest(
        provider=provider,
        model=model,
        system_instruction=prepared.system_instruction,
        messages=[{"role": "user", "content": prepared.user_message}],
        tools=prepared.tools,
        thinking_enabled=thinking_enabled,
        request_id=request_id,
    )

    def event_stream():
        full_text = ""
        citations: list[dict] = []
        usage: dict = {}
        failed = False

        for event in ai_gateway_service.stream(ai_request, api_key):
            etype = event["type"]
            if etype == EVENT_DELTA:
                full_text += event["text"]
                yield f"data: {json.dumps({'delta': event['text']}, ensure_ascii=False)}\n\n"
            elif etype == EVENT_CITATION:
                citations.extend(event["citations"])
                yield f"data: {json.dumps({'citations': event['citations']}, ensure_ascii=False)}\n\n"
            elif etype == EVENT_USAGE:
                usage = event["usage"]
                yield f"data: {json.dumps({'usage': usage}, ensure_ascii=False)}\n\n"
            elif etype == EVENT_ERROR:
                failed = True
                save_db = SessionLocal()
                try:
                    analysis_service.mark_failed(save_db, run.id, event["message"])
                finally:
                    save_db.close()
                yield f"data: {json.dumps({'error': event['message']}, ensure_ascii=False)}\n\n"

        if not failed:
            save_db = SessionLocal()
            try:
                analysis_service.mark_completed(save_db, run.id, full_text, citations, usage)
            finally:
                save_db.close()
        yield f"data: {json.dumps({'done': True, 'run_id': run.id})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("", response_model=list[AnalysisRunOut])
def list_analyses(
    skill_key: Optional[str] = None, db: Session = Depends(get_db), _=Depends(get_current_user)
):
    return analysis_service.list_runs(db, skill_key=skill_key)


@router.get("/{run_id}", response_model=AnalysisRunDetailOut)
def get_analysis(run_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    detail = analysis_service.get_run_detail(db, run_id)
    if not detail:
        raise HTTPException(404, "执行记录不存在")
    return detail


@router.delete("/{run_id}")
def delete_analysis(run_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    ok = analysis_service.delete_run(db, run_id)
    if not ok:
        raise HTTPException(404, "执行记录不存在")
    return {"success": True}
