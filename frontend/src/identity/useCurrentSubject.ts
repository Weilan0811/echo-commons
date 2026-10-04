import { useCallback, useSyncExternalStore } from 'react';
import {
  clearSubject,
  loadSubject,
  subscribeSubject,
  updateSubject,
  type CurrentSubject,
} from './currentSubject';

export type { CurrentSubject };

export interface SubjectController {
  readonly subject: CurrentSubject;
  /** 合并更新主体。 */
  readonly set: (patch: Partial<CurrentSubject>) => void;
  /** 清除当前身份，回到未选择状态。 */
  readonly clear: () => void;
}

/**
 * 读取与更新当前主体。页面通过它访问身份，不直接接触本地存储，
 * 这样接入账户认证时只需替换 currentSubject 的取值来源。
 */
export function useCurrentSubject(): SubjectController {
  const subject = useSyncExternalStore(subscribeSubject, loadSubject, loadSubject);

  const set = useCallback((patch: Partial<CurrentSubject>) => {
    updateSubject(patch);
  }, []);

  const clear = useCallback(() => {
    clearSubject();
  }, []);

  return { subject, set, clear };
}
