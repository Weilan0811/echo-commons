// 当前主体的唯一来源。页面不自行读取本地存储，见 adr/0001。
//
// 后端当前没有账户认证，player_id 由使用者在页面上选择，因此这里保存的是
// 本地测试身份。接入账户认证后只需替换本模块的取值来源（改为服务端会话），
// 页面与组件不改动：它们只通过 useCurrentSubject 读取主体。

const STORAGE_KEY = 'echo-commons.subject.v1';

export interface CurrentSubject {
  readonly playerId: string;
  readonly playerDisplayName: string;
  readonly communityId: string | null;
  readonly communityName: string | null;
}

const EMPTY: CurrentSubject = {
  playerId: '',
  playerDisplayName: '',
  communityId: null,
  communityName: null,
};

function parse(raw: string | null): CurrentSubject {
  if (raw === null) return EMPTY;
  try {
    const value: unknown = JSON.parse(raw);
    if (typeof value !== 'object' || value === null) return EMPTY;
    const record = value as Record<string, unknown>;
    const playerId = typeof record.playerId === 'string' ? record.playerId : '';
    if (playerId === '') return EMPTY;
    return {
      playerId,
      playerDisplayName:
        typeof record.playerDisplayName === 'string' ? record.playerDisplayName : playerId,
      communityId: typeof record.communityId === 'string' ? record.communityId : null,
      communityName: typeof record.communityName === 'string' ? record.communityName : null,
    };
  } catch {
    return EMPTY;
  }
}

// 快照缓存供 useSyncExternalStore 使用。缓存键取原始字符串，
// 因此外部清空或改写存储后会重新解析，不会返回过期值。
let cachedRaw: string | null | undefined;
let cachedSnapshot: CurrentSubject = EMPTY;

function readStorage(): string | null {
  if (typeof localStorage === 'undefined') return null;
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function loadSubject(): CurrentSubject {
  const raw = readStorage();
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    cachedSnapshot = parse(raw);
  }
  return cachedSnapshot;
}

const listeners = new Set<() => void>();

function writeStorage(next: CurrentSubject): void {
  try {
    if (next.playerId === '') localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // 隐私模式下写入会失败。主体保持内存中的值，不阻断界面。
  }
  cachedRaw = readStorage();
  cachedSnapshot = next.playerId === '' ? EMPTY : next;
  for (const listener of listeners) listener();
}

/** 合并更新当前主体；传空 playerId 视为退出当前身份。 */
export function updateSubject(patch: Partial<CurrentSubject>): void {
  writeStorage({ ...loadSubject(), ...patch });
}

/** 清除当前身份，回到未选择状态。 */
export function clearSubject(): void {
  writeStorage(EMPTY);
}

export function subscribeSubject(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** 当前是否已选定主体。未选定时页面应引导到主体与社群入口。 */
export function hasSubject(subject: CurrentSubject = loadSubject()): boolean {
  return subject.playerId !== '';
}
