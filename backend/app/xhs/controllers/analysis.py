from __future__ import annotations

import json
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.database import SessionLocal, get_db
from app.common.services.ai_config import get_ai_credentials
from app.common.services.ai_gateway import service as ai_gateway_service
from app.common.services.ai_gateway.base import EVENT_CITATION, EVENT_DELTA, EVENT_ERROR, EVENT_USAGE, AIRequest
from app.common.services.skill_runtime import runtime_service as skill_runtime
from app.common.services.skill_runtime.context_resolver import ContextTooLargeError
from app.common.services.skill_runtime.loader import SkillRuntimeError
from app.analysis.services import analysis_service
from app.skills.services import registry_service
from app.xhs.schemas.xhs import (
    AddProjectNotesIn,
    AnalysisProjectCreateIn,
    AppendReportIn,
    NoteAnalysisCreateIn,
    NoteAnalysisOut,
    RenameProjectIn,
    SaveCombinedReportIn,
    SaveReportIn,
    SetFeedbackIn,
)
from app.xhs.services import analysis_project, note_analysis, report_service, tasks

router = APIRouter(prefix="/api/xhs", tags=["xhs-analysis"])


def _get_project_or_404(db: Session, project_id: int):
    project = analysis_project.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "分析项目不存在")
    return project


@router.get("/analysis-projects")
def list_projects(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return analysis_project.list_projects(db)


@router.post("/analysis-projects")
def create_project(
    body: AnalysisProjectCreateIn, db: Session = Depends(get_db), _=Depends(get_current_user)
):
    return analysis_project.create_project(db, body.name.strip())


@router.patch("/analysis-projects/{project_id}")
def rename_project(
    project_id: int, body: RenameProjectIn, db: Session = Depends(get_db), _=Depends(get_current_user)
):
    project = analysis_project.rename_project(db, project_id, body.name.strip())
    if not project:
        raise HTTPException(404, "分析项目不存在")
    return project


@router.delete("/analysis-projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    ok = analysis_project.delete_project(db, project_id)
    if not ok:
        raise HTTPException(404, "分析项目不存在")
    return {"success": True}


@router.get("/analysis-templates")
def list_analysis_templates(_=Depends(get_current_user)):
    return note_analysis.list_templates()


@router.get("/analysis-projects/{project_id}/notes")
def list_project_notes(project_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _get_project_or_404(db, project_id)
    return analysis_project.list_project_notes(db, project_id)


@router.post("/analysis-projects/{project_id}/notes")
def add_project_notes(
    project_id: int, body: AddProjectNotesIn, db: Session = Depends(get_db), _=Depends(get_current_user)
):
    _get_project_or_404(db, project_id)
    task = tasks.get_task(db, body.task_id)
    if not task:
        raise HTTPException(404, "采集任务不存在")
    analysis_project.add_notes(db, project_id, body.task_id, body.note_ids)
    return analysis_project.list_project_notes(db, project_id)


@router.delete("/analysis-projects/{project_id}/notes/{note_id}")
def remove_project_note(
    project_id: int, note_id: str, db: Session = Depends(get_db), _=Depends(get_current_user)
):
    _get_project_or_404(db, project_id)
    ok = analysis_project.remove_note(db, project_id, note_id)
    if not ok:
        raise HTTPException(404, "该笔记不在项目里")
    return {"success": True}


@router.get("/analysis-projects/{project_id}/analyses", response_model=list[NoteAnalysisOut])
def list_project_analyses(project_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _get_project_or_404(db, project_id)
    return note_analysis.list_analyses(db, project_id)


def _create_skill_backed_analysis(
    db: Session,
    project_id: int,
    notes: list[dict],
    question: str,
    body: NoteAnalysisCreateIn,
    provider: str,
    api_key: str,
    model: str,
    thinking_enabled: bool,
    user,
):
    """
    走通用 Skill Runtime 的分支：选中的笔记整理成"业务上下文"注入 Skill 的 Prompt，
    而不是走 note_analysis.TEMPLATES 里写死的指令。结果仍然按老样子存一条 XhsNoteAnalysis
    （报告保存/查看体验不变——设计文档"保留兼容适配层"），额外在通用 analysis_runs 表里
    存一条记录，固定住这次用的 Skill 版本，和从 /api/analyses 发起的执行记录结构一致
    （设计文档阶段 5 验收："同一个 Skill 可从不同业务入口调用，执行记录...保持一致"）。
    """
    skill = registry_service.get_skill(db, body.skill_key)
    if not skill:
        raise HTTPException(404, "Skill 不存在")
    if not skill.enabled:
        raise HTTPException(400, "Skill 已禁用")

    template_row = None
    if body.skill_template_key:
        template_row = registry_service.get_template_row(db, skill, body.skill_template_key)
        if not template_row:
            raise HTTPException(404, "Skill 模板不存在或未启用")

    try:
        business_context = note_analysis.format_notes_for_context(db, notes)
    except note_analysis.NotesContextTooLarge as e:
        raise HTTPException(400, str(e))
    try:
        prepared = skill_runtime.prepare_run(
            db,
            body.skill_key,
            body.skill_template_key,
            {},
            question,
            body.enable_search,
            business_context=business_context,
        )
    except (SkillRuntimeError, ContextTooLargeError) as e:
        raise HTTPException(400, str(e))

    note_ids = [n.get("note_id") for n in notes]
    request_id = uuid4().hex
    run = analysis_service.create_run(
        db,
        request_id=request_id,
        user_id=user.id,
        skill_id=prepared.skill.skill_id,
        skill_version_id=prepared.skill.skill_version_id,
        template_id=template_row.id if template_row else None,
        model=model,
        inputs={"question": question},
        system_snapshot=prepared.system_instruction,
        context_refs=[{"type": "xhs_notes", "project_id": project_id, "note_ids": note_ids}],
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
    # 老的 template 字段是自由文本，塞一个可辨识的标记，不需要改表结构就能在现有报告/
    # 分析记录列表里看出这轮用的是哪个 Skill（+模板）
    display_template = f"skill:{body.skill_key}" + (f":{body.skill_template_key}" if body.skill_template_key else "")

    def event_stream():
        full_text = ""
        citations: list[dict] = []
        usage: dict = {}
        error_message: Optional[str] = None

        for event in ai_gateway_service.stream(ai_request, api_key):
            etype = event["type"]
            if etype == EVENT_DELTA:
                full_text += event["text"]
                yield f"data: {json.dumps({'delta': event['text']}, ensure_ascii=False)}\n\n"
            elif etype == EVENT_CITATION:
                citations.extend(event["citations"])
            elif etype == EVENT_USAGE:
                usage = event["usage"]
            elif etype == EVENT_ERROR:
                error_message = event["message"]
                yield f"data: {json.dumps({'error': event['message']}, ensure_ascii=False)}\n\n"

        if citations and not error_message:
            cite_text = "\n\n来源：\n" + "\n".join(f"- [{c['title']}]({c['url']})" for c in citations)
            full_text += cite_text
            yield f"data: {json.dumps({'delta': cite_text}, ensure_ascii=False)}\n\n"

        save_db = SessionLocal()
        try:
            if error_message:
                note_analysis.save_analysis(
                    save_db, project_id, question, model, "failed", error=error_message, template=display_template
                )
                analysis_service.mark_failed(save_db, run.id, error_message)
            else:
                note_analysis.save_analysis(
                    save_db, project_id, question, model, "success", result=full_text, template=display_template
                )
                analysis_service.mark_completed(save_db, run.id, full_text, citations, usage)
        finally:
            save_db.close()
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/analysis-projects/{project_id}/analyses")
def create_project_analysis(
    project_id: int,
    body: NoteAnalysisCreateIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _get_project_or_404(db, project_id)

    provider, api_key, model, thinking_enabled = get_ai_credentials(db)
    if not api_key:
        raise HTTPException(400, "尚未配置 AI 模型 API Key，请先在系统设置 → API 配置里配置")

    notes = analysis_project.list_project_notes(db, project_id)
    if not notes:
        raise HTTPException(400, "该项目暂无笔记，无法分析")

    if body.note_ids:
        note_id_set = set(body.note_ids)
        notes = [n for n in notes if n.get("note_id") in note_id_set]
        if not notes:
            raise HTTPException(400, "选中的笔记不在项目里")

    question = body.question.strip()

    if body.skill_key:
        return _create_skill_backed_analysis(
            db, project_id, notes, question, body, provider, api_key, model, thinking_enabled, user
        )

    template = body.template
    try:
        messages = note_analysis.build_conversation(db, project_id, notes, question, template)
    except note_analysis.NotesContextTooLarge as e:
        raise HTTPException(400, str(e))

    def event_stream():
        full_text = ""
        try:
            # 统一走 AI Gateway：gemini / deepseek 的流式调用、错误包装都在里面处理，
            # 这里只关心统一事件（delta / error）。
            ai_request = AIRequest(
                provider=provider,
                model=model,
                system_instruction="",
                messages=messages,
                thinking_enabled=thinking_enabled,
            )
            for event in ai_gateway_service.stream(ai_request, api_key):
                etype = event["type"]
                if etype == EVENT_DELTA:
                    full_text += event["text"]
                    yield f"data: {json.dumps({'delta': event['text']}, ensure_ascii=False)}\n\n"
                elif etype == EVENT_ERROR:
                    save_db = SessionLocal()
                    try:
                        note_analysis.save_analysis(
                            save_db, project_id, question, model, "failed",
                            error=event["message"], template=template,
                        )
                    finally:
                        save_db.close()
                    yield f"data: {json.dumps({'error': event['message']}, ensure_ascii=False)}\n\n"
                    return
        except Exception as e:
            save_db = SessionLocal()
            try:
                note_analysis.save_analysis(
                    save_db, project_id, question, model, "failed",
                    error=f"请求失败：{e}", template=template,
                )
            finally:
                save_db.close()
            yield f"data: {json.dumps({'error': f'请求失败：{e}'}, ensure_ascii=False)}\n\n"
            return

        save_db = SessionLocal()
        try:
            note_analysis.save_analysis(
                save_db, project_id, question, model, "success", result=full_text, template=template
            )
        finally:
            save_db.close()
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.delete("/analysis-projects/{project_id}/analyses/{analysis_id}")
def delete_project_analysis(
    project_id: int, analysis_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)
):
    ok = note_analysis.delete_analysis(db, project_id, analysis_id)
    if not ok:
        raise HTTPException(404, "分析记录不存在")
    return {"success": True}


@router.patch("/analysis-projects/{project_id}/analyses/{analysis_id}", response_model=NoteAnalysisOut)
def set_analysis_feedback(
    project_id: int,
    analysis_id: int,
    body: SetFeedbackIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    analysis = note_analysis.set_feedback(db, project_id, analysis_id, body.feedback)
    if not analysis:
        raise HTTPException(404, "分析记录不存在")
    return analysis


# ------------------------------------------------------------- 分析报告 ----


@router.post("/analysis-projects/{project_id}/analyses/{analysis_id}/report")
def save_analysis_report(
    project_id: int,
    analysis_id: int,
    body: SaveReportIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    _get_project_or_404(db, project_id)
    try:
        return report_service.save_report(db, project_id, analysis_id, body.title.strip(), body.note_ids)
    except report_service.ReportError as e:
        raise HTTPException(400, str(e))


@router.post("/analysis-projects/{project_id}/report")
def save_combined_report(
    project_id: int,
    body: SaveCombinedReportIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """把项目里勾选的几轮问答整理成一篇新报告，区别于上面按单条分析保存的接口。"""
    _get_project_or_404(db, project_id)
    try:
        return report_service.save_combined_report(
            db, project_id, body.title.strip(), body.note_ids, body.analysis_ids,
        )
    except report_service.ReportError as e:
        raise HTTPException(400, str(e))


@router.get("/reports")
def list_reports(
    query: Optional[str] = None,
    project_id: Optional[int] = None,
    template: Optional[str] = None,
    sort: str = "created_desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    return report_service.list_reports(
        db, query=query, project_id=project_id, template=template, page=page, page_size=page_size, sort=sort,
    )


@router.get("/reports/{report_id}")
def get_report(report_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    report = report_service.get_report(db, report_id)
    if not report:
        raise HTTPException(404, "报告不存在")
    return report


@router.delete("/reports/{report_id}")
def delete_report(report_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    ok = report_service.delete_report(db, report_id)
    if not ok:
        raise HTTPException(404, "报告不存在")
    return {"success": True}


@router.put("/reports/{report_id}/append")
def append_report(
    report_id: int,
    body: AppendReportIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """把项目里勾选的几轮问答追加到一份已有报告后面，而不是新建一份。"""
    try:
        return report_service.append_to_report(db, report_id, body.analysis_ids, body.note_ids)
    except report_service.ReportError as e:
        raise HTTPException(400, str(e))
