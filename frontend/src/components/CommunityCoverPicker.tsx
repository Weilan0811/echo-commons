import { Check } from 'lucide-react';
import { PRESET_COVERS } from '@/lib/coverPresets';

export function CommunityCoverPicker({ value, onChange, disabled = false }: {
  readonly value: string | null;
  readonly onChange: (value: string) => void;
  readonly disabled?: boolean;
}) {
  const covers = [{ id: '', name: '默认渐变', url: null }, ...PRESET_COVERS.map(cover => ({
    id: cover.id, name: cover.matchNames[0], url: cover.url,
  }))];
  return <fieldset disabled={disabled} className="space-y-3">
    <legend className="mb-3 text-[13px] font-medium text-content-muted">官方封面</legend>
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {covers.map(cover => <button key={cover.id} type="button" aria-pressed={value === cover.id}
        onClick={() => onChange(cover.id)} aria-label={`选择${cover.name}`}
        className={`group overflow-hidden rounded-xl border text-left transition-colors focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50 ${value === cover.id ? 'border-accent bg-accent-soft' : 'border-border-subtle bg-surface-sunken hover:border-accent/40'}`}>
        <div className="relative aspect-[16/10] bg-gradient-to-br from-surface-overlay to-surface-sunken">
          {cover.url ? <img src={cover.url} alt="" className="h-full w-full object-cover" /> : null}
          {value === cover.id ? <span className="absolute right-2 top-2 flex size-5 items-center justify-center rounded-full bg-accent text-accent-ink"><Check size={13} /></span> : null}
        </div>
        <span className="block px-3 py-2 text-[12px]">{cover.name}</span>
      </button>)}
    </div>
  </fieldset>;
}
