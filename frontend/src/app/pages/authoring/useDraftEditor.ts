import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  useSaveDraft,
  type AuthoringContent,
  type AuthoringDraft,
} from '@/api/authoring';
import { queryKeys } from '@/api/queryKeys';
import { ApiError } from '@/api/http';

/**
 * 步骤内的草稿编辑状态：核对态与编辑态分离。
 *
 * 表单是服务端草稿的本地工作副本。进入章节默认是核对态，内容只读；显式
 * 「再次编辑」才进入编辑态，「暂存本章」PUT 完整 content，成功后回到核对态，
 * 「放弃修改」丢弃本地副本。这样 AI 生成与章节确认只面向已暂存内容，不会
 * 把未保存的修改悄悄覆盖。版本冲突（409）时重读草稿并提示，在最新版本上
 * 继续编辑。
 */
export function useDraftEditor(playerId: string, draft: AuthoringDraft) {
  const queryClient = useQueryClient();
  const saveMutation = useSaveDraft(playerId, draft.draft_id);
  const [form, setForm] = useState<AuthoringContent>(draft.content);
  const [conflict, setConflict] = useState(false);
  const [editing, setEditing] = useState(false);
  const syncedRevision = useRef(draft.revision);

  useEffect(() => {
    if (draft.revision !== syncedRevision.current) {
      syncedRevision.current = draft.revision;
      setForm(draft.content);
      // 服务端内容推进（接受建议等）后强制回到核对态；冲突提示保留到作者再次操作。
      setEditing(false);
    }
  }, [draft.revision, draft.content]);

  const dirty = useMemo(
    () => JSON.stringify(form) !== JSON.stringify(draft.content),
    [form, draft.content],
  );

  const startEdit = useCallback(() => {
    setConflict(false);
    setEditing(true);
  }, []);

  const cancelEdit = useCallback(() => {
    setForm(draft.content);
    setConflict(false);
    setEditing(false);
  }, [draft.content]);

  const patch = (changes: Partial<AuthoringContent>) => {
    setConflict(false);
    setForm((current) => ({ ...current, ...changes }));
  };

  // 允许在同一次事件里先改后存（例如清空采访），覆盖值同时写回本地表单。
  const save = useCallback(async (override?: AuthoringContent): Promise<boolean> => {
    setConflict(false);
    const content = override ?? form;
    if (override !== undefined) setForm(override);
    try {
      await saveMutation.mutateAsync({ expectedRevision: draft.revision, content });
      setEditing(false);
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
  }, [form, draft.revision, playerId, draft.draft_id, saveMutation, queryClient]);

  return {
    form,
    patch,
    dirty,
    save,
    editing,
    startEdit,
    cancelEdit,
    isSaving: saveMutation.isPending,
    saveError: saveMutation.error,
    conflict,
  };
}
