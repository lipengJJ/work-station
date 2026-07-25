import { requestClient } from '#/api/request';

export namespace ChatApi {
  export interface Config {
    configured: boolean;
    model: string;
  }

  export interface ConfigIn {
    // 留空 = 不修改已保存的 key，只更新模型
    api_key?: string;
    model: string;
  }

  export interface Message {
    id: number;
    role: 'assistant' | 'user';
    content: string;
    created_at: string;
  }

  export interface StreamEvent {
    delta?: string;
    done?: boolean;
    error?: string;
  }
}

export async function getChatConfigApi() {
  return requestClient.get<ChatApi.Config>('/chat/config');
}

export async function setChatConfigApi(body: ChatApi.ConfigIn) {
  return requestClient.put<ChatApi.Config>('/chat/config', body);
}

export async function listChatMessagesApi() {
  return requestClient.get<ChatApi.Message[]>('/chat/messages');
}

export async function clearChatMessagesApi() {
  return requestClient.delete<{ success: boolean }>('/chat/messages');
}

export interface StreamChatHandlers {
  onDelta: (delta: string) => void;
  onError: (error: string) => void;
  onEnd: () => void;
}

/**
 * SSE 流式发送消息。每个 SSE data 块是一个完整 JSON 对象（{delta}/{error}/{done}），
 * 但 fetch 读到的 chunk 边界和 SSE 事件边界不一定对齐，所以要按 "\n\n" 缓冲拼接。
 */
export async function streamChatApi(content: string, handlers: StreamChatHandlers) {
  let buffer = '';
  await requestClient.postSSE(
    '/chat/stream',
    { content },
    {
      // postSSE 只有在请求头已经带了 application/json 时才会把 body 对象序列化成
      // JSON 字符串，不然会把裸对象直接塞进 fetch 的 body，后端收到的不是合法 JSON，
      // FastAPI 直接 422——这里必须显式声明
      headers: { 'Content-Type': 'application/json' },
      onMessage: (raw: string) => {
        buffer += raw;
        const events = buffer.split('\n\n');
        buffer = events.pop() ?? '';
        for (const event of events) {
          const line = event.trim();
          if (!line.startsWith('data:')) continue;
          const payload = line.slice(5).trim();
          if (!payload) continue;
          try {
            const parsed = JSON.parse(payload) as ChatApi.StreamEvent;
            if (parsed.error) {
              handlers.onError(parsed.error);
            } else if (parsed.delta) {
              handlers.onDelta(parsed.delta);
            }
          } catch {
            // 忽略解析失败的单个事件，不影响后续流
          }
        }
      },
      onEnd: handlers.onEnd,
    },
  );
}
