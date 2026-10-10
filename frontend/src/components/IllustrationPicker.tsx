import { useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import Cropper, { type Area } from 'react-easy-crop';
import { useInfiniteQuery, useMutation, useQuery } from '@tanstack/react-query';
import { assetImage, imageAssets, type ImageAsset, type ImageGeneration } from '@/api/assets';
import { ErrorNotice } from './ErrorNotice';
import type { SchemaOf } from '@/api/http';

const button = 'rounded-lg border border-border-strong px-3 py-2 text-sm disabled:opacity-40';
export function IllustrationPicker({ playerId, draft, description, onSelect, onClose }: {
  playerId: string;
  draft?: { id: string; revision: number };
  description?: string;
  onSelect: (asset: ImageAsset) => Promise<boolean>;
  onClose: () => void;
}) {
  const [style, setStyle] = useState('');
  const [appearance, setAppearance] = useState('');
  const storageKey = `echo-commons.illustration.${playerId}.${draft?.id ?? description}`;
  const [generation, setGeneration] = useState<ImageGeneration | null>(() => {
    const saved = localStorage.getItem(storageKey);
    return saved ? JSON.parse(saved) as ImageGeneration : null;
  });
  const pending = useRef<SchemaOf<'GenerationRequest'> | null>(null);
  const savedCrop = useRef<{ selection: string; asset: ImageAsset } | null>(null);
  const [selected, setSelected] = useState<ImageAsset | null>(null);
  const [crop, setCrop] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [area, setArea] = useState<Area | null>(null);
  const styles = useQuery({ queryKey: ['image-styles'], queryFn: imageAssets.styles });
  const assets = useInfiniteQuery({
    queryKey: ['illustrations', playerId], initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => imageAssets.list(playerId, pageParam),
    getNextPageParam: (page) => page.has_more ? page.cursor ?? undefined : undefined,
  });
  const status = useQuery({
    queryKey: ['image-generation', playerId, generation?.generation_id],
    queryFn: () => imageAssets.generation(playerId, generation!.generation_id),
    enabled: generation !== null,
    refetchInterval: (query) => query.state.data && ['completed', 'failed'].includes(query.state.data.status) ? false : 2000,
  });
  const current = status.data ?? generation;
  const generating = current !== null && !['completed', 'failed'].includes(current.status);
  const create = useMutation({
    mutationFn: () => {
      const body: SchemaOf<'GenerationRequest'> = {
      player_id: playerId, client_request_id: crypto.randomUUID(), purpose: 'character_illustration',
      style_id: style || styles.data?.find((item) => item.purposes.includes('character_illustration'))?.style_id || '',
      appearance, description: description ?? '', ...(draft ? { draft_id: draft.id, revision: draft.revision } : {}),
      };
      if (!pending.current || JSON.stringify({ ...pending.current, client_request_id: '' }) !== JSON.stringify({ ...body, client_request_id: '' })) pending.current = body;
      return imageAssets.generate(pending.current);
    },
    onSuccess: (result) => { pending.current = null; setGeneration(result); localStorage.setItem(storageKey, JSON.stringify(result)); },
  });
  const openAsset = useMutation({
    mutationFn: (id: string) => imageAssets.get(playerId, id),
    onSuccess: (asset) => { create.reset(); setSelected(asset); setCrop({ x: 0, y: 0 }); setZoom(1); },
  });
  const save = useMutation({
    mutationFn: async () => {
      const image = selected!.images.find((item) => item.variant === 'standard')!;
      const size = Math.min(Math.round(area!.width), Math.round(area!.height), image.width, image.height);
      const selection = JSON.stringify([selected!.asset_id, area]);
      const avatar = savedCrop.current?.selection === selection ? savedCrop.current.asset : await imageAssets.crop(selected!.asset_id, {
        player_id: playerId, client_request_id: crypto.randomUUID(), size,
        x: Math.max(0, Math.min(image.width - size, Math.round(area!.x))),
        y: Math.max(0, Math.min(image.height - size, Math.round(area!.y))),
      });
      savedCrop.current = { selection, asset: avatar };
      if (await onSelect(avatar)) onClose();
      else throw new Error('外观尚未保存，请重新尝试。');
    },
  });
  return <Dialog.Root open onOpenChange={(open) => { if (!open && !save.isPending) onClose(); }}>
    <Dialog.Portal>
      <Dialog.Overlay className="fixed inset-0 z-[60] bg-black/60" />
      <Dialog.Content aria-describedby={undefined} className="fixed inset-4 z-[61] mx-auto flex max-w-3xl flex-col gap-4 overflow-y-auto rounded-card border border-border-strong bg-surface p-5 text-content shadow-2xl">
        <div className="flex justify-between"><Dialog.Title className="display-title text-xl">角色插画与头像</Dialog.Title><button className={button} onClick={onClose} disabled={save.isPending}>关闭</button></div>
        {selected ? <>
          <p className="text-sm text-content-muted">拖动插画，选择头像范围。保存后使用这张插画和裁剪后的头像。</p>
          <div className="relative min-h-64 flex-1 bg-surface-sunken">
            <Cropper image={assetImage(selected)} crop={crop} zoom={zoom} aspect={1} onCropChange={setCrop} onZoomChange={setZoom} onCropComplete={(_, pixels) => setArea(pixels)} />
          </div>
          <label className="flex gap-3 text-sm">缩放<input aria-label="头像缩放" type="range" min={1} max={3} step={0.05} value={zoom} onChange={(event) => setZoom(Number(event.target.value))} /></label>
          <div className="flex gap-3"><button className={button} disabled={!area || save.isPending} onClick={() => save.mutate()}>{save.isPending ? '正在保存…' : '保存插画与头像'}</button><button className={button} disabled={save.isPending} onClick={() => setSelected(null)}>返回插画库</button></div>
        </> : <>
          <div className="grid gap-3 rounded-lg bg-surface-sunken p-4">
            <label className="text-sm">画风<select className="ml-3 rounded bg-surface p-2" value={style || styles.data?.find((item) => item.purposes.includes('character_illustration'))?.style_id || ''} onChange={(event) => setStyle(event.target.value)}>{styles.data?.filter((item) => item.purposes.includes('character_illustration')).map((item) => <option key={item.style_id} value={item.style_id}>{item.name}</option>)}</select></label>
            <label className="text-sm">外观补充<textarea className="mt-2 w-full rounded border border-border-subtle bg-surface p-2" rows={2} maxLength={4000} value={appearance} onChange={(event) => setAppearance(event.target.value)} placeholder="发型、衣服、姿势等，可以留空" /></label>
            <button className={button} disabled={generating || create.isPending || !styles.data?.length} onClick={() => create.mutate()}>{generating || create.isPending ? '正在生成插画…' : '生成角色插画'}</button>
            {current?.status === 'failed' ? <p className="text-sm text-danger">插画没有生成成功，可以重新尝试。已有插画仍可使用。</p> : null}
            {current?.status === 'completed' && current.asset_id ? <button className={button} onClick={() => openAsset.mutate(current.asset_id!)}>查看生成的插画并裁剪头像</button> : null}
          </div>
          <h3 className="text-sm">已有插画</h3>
          <div className="grid grid-cols-3 gap-3 sm:grid-cols-5">{assets.data?.pages.flatMap((page) => page.items).map((asset) => <button key={asset.asset_id} onClick={() => openAsset.mutate(asset.asset_id)} className="overflow-hidden rounded-lg border border-border-subtle"><img src={assetImage(asset)} alt="选择插画" className="aspect-[2/3] w-full object-cover" /></button>)}</div>
          {assets.data?.pages.every((page) => page.items.length === 0) ? <p className="text-sm text-content-muted">插画库为空，可以根据角色资料生成插画。</p> : null}
          {assets.hasNextPage ? <button className={button} disabled={assets.isFetchingNextPage} onClick={() => void assets.fetchNextPage()}>加载更多插画</button> : null}
        </>}
        {[styles.error, assets.error, status.error, create.error, openAsset.error, save.error].filter(Boolean).map((error, index) => <ErrorNotice key={index} error={error} />)}
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
