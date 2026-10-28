import { useState } from 'react';
import type { AuthoringContent } from '@/api/authoring';
import type { SchemaOf } from '@/api/http';
import { usePeople, useRegisterPerson, usePersonBindings, useBindPerson } from '@/api/people';
import { useCommunityCharacters } from '@/api/directory';
import { useCurrentSubject } from '@/identity/useCurrentSubject';
import { ErrorNotice } from '@/components/ErrorNotice';
import { newUuid } from '@/lib/clientMessageId';

const fieldClass = 'w-full rounded-lg border border-border-subtle bg-surface-sunken px-3 py-2 text-[12px] disabled:opacity-60';

export function PersonPicker({ playerId, value, onChange, disabled = false, label = '人物', suggestedName = '' }: {
  readonly playerId: string;
  readonly value: string;
  readonly onChange: (id: string, name: string) => void;
  readonly disabled?: boolean;
  readonly label?: string;
  readonly suggestedName?: string;
}) {
  const people = usePeople(playerId);
  const register = useRegisterPerson(playerId);
  const { subject } = useCurrentSubject();
  const communityId = subject.communityId;
  const members = useCommunityCharacters(playerId, communityId);
  const bindings = usePersonBindings(playerId, communityId);
  const bind = useBindPerson(playerId, communityId);
  const [member, setMember] = useState('');
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState(suggestedName);
  const [description, setDescription] = useState('');
  return (
    <div className="flex flex-col gap-2">
      <label className="text-[12px] text-content-muted">{label}
        <select aria-label={label} className={`${fieldClass} mt-1`} value={value} disabled={disabled || people.isPending}
          onChange={(event) => {
            const selected = people.data?.find((person) => person.person_id === event.target.value);
            onChange(selected?.person_id ?? '', selected?.display_name ?? '');
          }}>
          <option value="">请选择人物编号</option>
          {people.data?.map((person) => <option key={person.person_id} value={person.person_id}>
            {person.display_name} · {person.person_id}
          </option>)}
        </select>
      </label>
      {!disabled && <button type="button" className="self-start text-[11px] text-accent" onClick={() => setAdding(!adding)}>
        {adding ? '取消登记' : '登记新人物'}
      </button>}
      {!disabled && communityId && <details className="text-[11px] text-content-muted">
        <summary>从已有社群成员选择</summary>
        <select aria-label="已有社群成员" className={`${fieldClass} mt-2`} value={member} onChange={(event) => {
          setMember(event.target.value);
          const [kind, ...identity] = event.target.value.split(':');
          const binding = bindings.data?.find((item) => item.actor_kind === kind && item.actor_id === identity.join(':'));
          const person = people.data?.find((item) => item.person_id === binding?.person_id);
          if (person) onChange(person.person_id, person.display_name);
        }}>
          <option value="">请选择成员</option>
          <option value={`player:${playerId}`}>当前玩家 · {playerId}</option>
          {members.data?.map((item) => <option key={item.character_id} value={`character:${item.character_id}`}>{item.display_name} · {item.character_id}</option>)}
        </select>
        {member && !bindings.data?.some((item) => `${item.actor_kind}:${item.actor_id}` === member) && <button type="button" className="mt-2 text-accent disabled:opacity-40" disabled={bind.isPending || register.isPending}
          onClick={() => { void (async () => {
            const [kind, ...identity] = member.split(':');
            const actorId = identity.join(':');
            const actorKind = kind === 'player' ? 'player' : 'character';
            const selectedName = actorKind === 'player' ? '当前玩家' : members.data?.find((item) => item.character_id === actorId)?.display_name ?? actorId;
            const person = value ? people.data?.find((item) => item.person_id === value) : await register.mutateAsync({ name: selectedName, description: '' });
            if (!person) return;
            await bind.mutateAsync({ personId: person.person_id, actorKind, actorId });
            onChange(person.person_id, person.display_name);
          })().catch(() => undefined); }}>{value ? '确认将所选人物关联到该成员' : '确认登记此成员的人物编号'}</button>}
      </details>}
      {adding && !disabled && <div className="flex flex-col gap-2 rounded-lg border border-border-subtle p-3">
        <input aria-label="新人物名称" placeholder="人物名称" maxLength={80} value={name} onChange={(event) => setName(event.target.value)} className={fieldClass} />
        <input aria-label="人物身份说明" placeholder="身份说明，例如所属作品、时期" maxLength={500} value={description} onChange={(event) => setDescription(event.target.value)} className={fieldClass} />
        <button type="button" disabled={!name.trim() || register.isPending} className="self-start text-[12px] text-accent disabled:opacity-40"
          onClick={() => { void register.mutateAsync({ name: name.trim(), description: description.trim() }).then((person) => {
            onChange(person.person_id, person.display_name); setAdding(false);
          }).catch(() => undefined); }}>确认登记并选择</button>
      </div>}
      {people.isError && <ErrorNotice error={people.error} />}
      {register.isError && <ErrorNotice error={register.error} />}
      {bind.isError && <ErrorNotice error={bind.error} />}
    </div>
  );
}

export function RelationshipsEditor({ playerId, content, patch, editing, suggestions = [] }: {
  readonly playerId: string;
  readonly content: AuthoringContent;
  readonly patch: (changes: Partial<AuthoringContent>) => void;
  readonly editing: boolean;
  readonly suggestions?: readonly SchemaOf<'RelationshipSuggestion'>[];
}) {
  const [target, setTarget] = useState({ id: '', name: '' });
  const [text, setText] = useState('');
  const [suggestedName, setSuggestedName] = useState('');
  const relationships = content.relationships ?? [];
  return <section className="flex flex-col gap-4 rounded-card border border-border-subtle bg-surface p-4">
    <div>
      <h3 className="text-[13px] font-semibold">与 TA 的关系</h3>
      <p className="mt-1 text-[11px] leading-relaxed text-content-faint">选择明确的人物编号，写下共同经历、自己的看法和称呼。对方可以暂时没有创建为社群角色。</p>
    </div>
    <PersonPicker playerId={playerId} value={content.person_id ?? ''} disabled={!editing} label="当前角色对应的人物" suggestedName={content.display_name}
      onChange={(id) => patch({ person_id: id || null })} />
    {relationships.map((item, index) => <div key={item.relationship_id} className="flex flex-col gap-2 rounded-lg bg-surface-sunken/60 p-3">
      <PersonPicker playerId={playerId} value={item.target_person_id} disabled={!editing} label="关系对象"
        onChange={(id, name) => { if (id) patch({ relationships: relationships.map((row, position) => position === index ? { ...row, target_person_id: id, target_name: name } : row) }); }} />
      <textarea aria-label={`与${item.target_name}的关系`} rows={4} maxLength={4000} value={item.content} disabled={!editing} className={fieldClass}
        onChange={(event) => patch({ relationships: relationships.map((row, position) => position === index ? { ...row, content: event.target.value } : row) })} />
      {editing && <button type="button" className="self-start text-[11px] text-content-faint" onClick={() => patch({ relationships: relationships.filter((_, position) => position !== index) })}>删除这条关系</button>}
    </div>)}
    {editing && <div className="flex flex-col gap-2 border-t border-border-subtle pt-3">
      {suggestions.map((suggestion, index) => <div key={index} className="rounded-lg bg-surface-sunken/60 p-3">
        <p className="text-[12px]">人物建议：{suggestion.name}</p>
        <p className="mt-1 text-[11px] text-content-muted">{suggestion.content}</p>
        <button type="button" className="mt-2 text-[11px] text-accent" onClick={() => { setText(suggestion.content); setSuggestedName(suggestion.name); setTarget({ id: '', name: '' }); }}>使用这段文本并选择人物</button>
      </div>)}
      <PersonPicker key={suggestedName} playerId={playerId} value={target.id} suggestedName={suggestedName} onChange={(id, name) => setTarget({ id, name })} label="添加关系对象" />
      <textarea aria-label="新增关系文本" placeholder="TA 怎样认识这个人？共同经历了什么？现在怎样看待对方？" rows={4} maxLength={4000} value={text} onChange={(event) => setText(event.target.value)} className={fieldClass} />
      <button type="button" className="self-start text-[12px] text-accent disabled:opacity-40"
        disabled={!target.id || !text.trim() || target.id === content.person_id || relationships.some((item) => item.target_person_id === target.id) || relationships.length >= 40}
        onClick={() => { patch({ relationships: [...relationships, { relationship_id: newUuid(), target_person_id: target.id, target_name: target.name, content: text.trim() }] }); setText(''); setTarget({ id: '', name: '' }); }}>确认添加关系</button>
    </div>}
  </section>;
}
