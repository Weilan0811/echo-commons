import { useEffect, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  useSaveDraft,
  type AuthoringContent,
  type AuthoringDraft,
} from '@/api/authoring';
import { queryKeys } from '@/api/queryKeys';
import { ApiError } from '@/api/http';

/**
 * 步骤内的草稿编辑状态。
 *
 * 表单是服务端草稿的本地工作副本：显式点「保存修改」才 PUT 完整 content；
 * 保存成功后接口层把新草稿写入缓存，本 hook 在 revision 推进时用权威内容
 * 重置表单。版本冲突（409）时不保留猜测，直接重读草稿并提示。
 */
export function useDraftEditor(playerId: string, draft: AuthoringDraft) {
  const queryClient = useQueryClient();
  const saveMutation = useSaveDraft(playerId, draft.draft_id);
  const [form, setForm] = useState<AuthoringContent>(draft.content);
  const [conflict, setConflict] = useState(false);
  const syncedRevision = useRef(draft.revision);

  useEffect(() => {
    if (draft.revision !== syncedRevision.current) {
      syncedRevision.current = draft.revision;
      setForm(draft.content);
      setConflict(false);
    }
  }, [draft.revision, draft.content]);

  const dirty = useMemo(
    () => JSON.stringify(form) !== JSON.stringify(draft.content),
    [form, draft.content],
  );

  const patch = (changes: Partial<AuthoringContent>) => {
    setForm((current) => ({ ...current, ...changes }));
  };

  // 允许在同一次事件里先改后存（例如清空采访），覆盖值同时写回本地表单。
  const save = async (override?: AuthoringContent): Promise<boolean> => {
    setConflict(false);
    const content = override ?? form;
    if (override !== undefined) setForm(override);
    try {
      await saveMutation.mutateAsync({ expectedRevision: draft.revision, content });
      return true;
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setConflict(true);
        void queryClient.invalidateQueries({
          queryKey: queryKeys.authoring.draft(playerId, draft.draft_id),
        });
      }
      return false;
    }
  };

  return {
    form,
    patch,
    dirty,
    save,
    isSaving: saveMutation.isPending,
    saveError: saveMutation.error,
    conflict,
  };
}
