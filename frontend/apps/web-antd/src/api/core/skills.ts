import { requestClient } from '#/api/request';

export namespace SkillsApi {
  export interface SkillSummary {
    skill_key: string;
    display_name: string;
    description: string;
    category: null | string;
    source_type: string;
    enabled: boolean;
    risk_level: 'blocked' | 'high' | 'low' | 'medium';
    version: null | string;
    template_count: number;
    created_at: string;
    updated_at: string;
  }

  export interface SkillTemplate {
    template_key: string;
    name: string;
    description: null | string;
    prompt_path: null | string;
    output_template_path: null | string;
  }

  export interface SkillRuntime {
    preferred_provider: null | string;
    recommended_model: null | string;
    tools: Record<string, boolean>;
  }

  export interface SkillValidation {
    valid: boolean;
    errors: string[];
    warnings: string[];
    risk_level: string;
    total_size: number;
    file_count: number;
  }

  export interface SkillDetail extends SkillSummary {
    instruction: null | string;
    default_prompt: null | string;
    tags: string[];
    runtime: null | SkillRuntime;
    validation: null | SkillValidation;
    templates: SkillTemplate[];
  }

  export interface SkillVersion {
    id: number;
    version: string;
    content_hash: string;
    is_current: boolean;
    created_at: string;
  }

  export interface FileNode {
    name: string;
    path: string;
    type: 'dir' | 'file';
    size: null | number;
    children: FileNode[];
  }

  export interface FileContent {
    path: string;
    content: string;
    truncated: boolean;
  }

  export interface FileSaveResult {
    path: string;
    saved: boolean;
    manifest_error: null | string;
    validation: null | SkillValidation;
  }

  export interface ListParams {
    query?: string;
    category?: string;
    enabled?: boolean;
  }
}

export async function listSkillsApi(params?: SkillsApi.ListParams) {
  return requestClient.get<SkillsApi.SkillSummary[]>('/skills', { params });
}

export async function getSkillDetailApi(skillKey: string) {
  return requestClient.get<SkillsApi.SkillDetail>(`/skills/${skillKey}`);
}

export async function listSkillVersionsApi(skillKey: string) {
  return requestClient.get<SkillsApi.SkillVersion[]>(`/skills/${skillKey}/versions`);
}

export async function listSkillTemplatesApi(skillKey: string) {
  return requestClient.get<SkillsApi.SkillTemplate[]>(`/skills/${skillKey}/templates`);
}

export async function listSkillFilesApi(skillKey: string) {
  return requestClient.get<SkillsApi.FileNode[]>(`/skills/${skillKey}/files`);
}

export async function getSkillFileContentApi(skillKey: string, path: string) {
  return requestClient.get<SkillsApi.FileContent>(`/skills/${skillKey}/files/content`, {
    params: { path },
  });
}

export async function updateSkillFileContentApi(skillKey: string, path: string, content: string) {
  return requestClient.put<SkillsApi.FileSaveResult>(`/skills/${skillKey}/files/content`, {
    path,
    content,
  });
}
